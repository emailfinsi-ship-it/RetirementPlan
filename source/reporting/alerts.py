"""Alerts: tell you when something needs a look, without you having to open
the app. Three ways to hear about it, all optional:

  * in the app -- a bell with a count in the header and an Alerts card on the Summary
  * a short weekly e-mail digest (your own e-mail account, set up on the Setup tab)
  * a Mac notification when a new alert appears

What raises an alert: the chance your money lasts fell 5 points or more in
the last week (or is low), a problem in the Data check, one holding / sector /
firm dominating your investments, or your mix drifting 10+ points from your
goal. Alerts only point things out -- nothing here changes your plan.

State and settings are small JSON blobs in `meta`; the e-mail password lives
in the Keychain (see secrets_store)."""

from __future__ import annotations

import json
import smtplib
import ssl
import subprocess
import sys
from datetime import date, datetime, timedelta
from email.message import EmailMessage

from source.common import branding, db, secrets_store
from source.reporting import presentation, progress, rebalance
from source.reporting.portfolio_checkup import portfolio_checkup

_STATE_KEY = "alerts_state"
_SETTINGS_KEY = "alert_settings"
CHANCE_DROP = 0.05
DRIFT_ALERT_PTS = 10.0
DIGEST_EVERY_DAYS = 7

DEFAULT_SETTINGS = {
    "email_to": "", "smtp_host": "", "smtp_port": 587, "smtp_user": "", "smtp_from": "",
    "digest": False, "mac_notify": False,
}


# ---------- storage ----------

def _load(key: str) -> dict:
    raw = db.get_meta(key)
    try:
        data = json.loads(raw) if raw else {}
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def settings() -> dict:
    return {**DEFAULT_SETTINGS, **_load(_SETTINGS_KEY)}


def save_settings(values: dict) -> dict:
    cur = settings()
    new = dict(cur)
    for key in ("email_to", "smtp_host", "smtp_user", "smtp_from"):
        if key in values:
            new[key] = str(values[key] or "").strip()
    if "smtp_port" in values:
        try:
            port = int(values["smtp_port"])
        except (TypeError, ValueError):
            raise ValueError("The e-mail server port must be a number (usually 587).") from None
        if not 1 <= port <= 65535:
            raise ValueError("The e-mail server port must be between 1 and 65535.")
        new["smtp_port"] = port
    for key in ("digest", "mac_notify"):
        if key in values:
            new[key] = bool(values[key])
    if new["email_to"] and "@" not in new["email_to"]:
        raise ValueError("That does not look like an e-mail address.")
    db.set_meta(_SETTINGS_KEY, json.dumps(new))
    if values.get("smtp_password"):
        secrets_store.set_smtp_password(str(values["smtp_password"]))
    return new


def email_ready(cfg: dict | None = None) -> bool:
    cfg = cfg or settings()
    return bool(cfg["email_to"] and cfg["smtp_host"] and (cfg["smtp_from"] or cfg["smtp_user"]))


def _state() -> dict:
    s = _load(_STATE_KEY)
    return {"active": s.get("active") or [], "dismissed": s.get("dismissed") or [],
            "notified": s.get("notified") or [], "last_eval": s.get("last_eval") or "",
            "last_digest": s.get("last_digest") or "", "last_daily": s.get("last_daily") or ""}


def _save_state(state: dict) -> None:
    db.set_meta(_STATE_KEY, json.dumps(state))


# ---------- what raises an alert ----------

def _chance_a_week_ago(history: dict, today: date) -> float | None:
    older = []
    for k, v in history.items():
        try:
            d = datetime.strptime(k, "%Y-%m-%d").date()
        except ValueError:
            continue
        if timedelta(days=5) <= today - d <= timedelta(days=45):
            older.append((d, v))
    if not older:
        return None
    # the entry closest to 7 days ago
    return min(older, key=lambda x: abs((today - x[0]).days - 7))[1]


def evaluate(summary: dict, chance: float | None, positions: list[dict], data_issues: list[dict],
             history: dict, *, today: date | None = None) -> list[dict]:
    today = today or date.today()
    out: list[dict] = []

    def add(alert_id: str, level: str, title: str, detail: str, href: str) -> None:
        out.append({"id": alert_id, "level": level, "title": title, "detail": detail, "href": href})

    if chance is not None:
        before = _chance_a_week_ago(history, today)
        if before is not None and before - chance >= CHANCE_DROP:
            add("chance-drop", "warn", "Your chance of lasting fell",
                f"It went from {presentation.percent_display(before)} to {presentation.percent_display(chance)} "
                "in the last week or so.", "/monte-carlo.html")
        if chance < presentation.REVIEW_AT:
            add("chance-low", "warn", "Your chance of lasting is low",
                f"Your money lasts in {presentation.percent_display(chance)} of the test runs.", "/monte-carlo.html#assumptions")

    for issue in data_issues:
        if issue["level"] == "warn":
            add(f"dc:{issue['id']}", "warn", issue["title"], issue["detail"], issue["href"])

    flags = [f for f in portfolio_checkup(positions)["findings"] if f["level"] == "warn"]
    if flags:
        extra = f" (and {len(flags) - 1} more)" if len(flags) > 1 else ""
        add("concentration", "warn", "Your investments are too concentrated", flags[0]["text"] + extra,
            "/linked-positions.html#checkup")

    if positions:
        try:
            age = date.today().year - int(float(summary["assumptions"].get("birth_year")))
        except (TypeError, ValueError):
            age = None
        target = rebalance.get_target() or rebalance.risk_target("moderate", age)
        plan = rebalance.build_plan(positions, target, rebalance.get_overrides())
        rows = plan["rows"]
        if rows:
            worst = max(rows, key=lambda r: abs(r["drift_pts"]))
            if abs(worst["drift_pts"]) >= DRIFT_ALERT_PTS:
                word = "more" if worst["drift_pts"] > 0 else "less"
                add("drift", "info", "Your mix has drifted from your goal",
                    f"You hold {abs(worst['drift_pts']):.0f} points {word} {worst['cls'].lower()} than your goal.",
                    "/rebalance.html")
    return out


# ---------- keeping track ----------

def refresh(alerts: list[dict], *, today: date | None = None) -> list[dict]:
    """Remember the current alerts. A dismissed alert stays hidden until it
    goes away and later comes back. Returns the alerts still showing."""
    today = today or date.today()
    state = _state()
    ids = {a["id"] for a in alerts}
    state["active"] = alerts
    state["dismissed"] = [i for i in state["dismissed"] if i in ids]
    state["notified"] = [i for i in state["notified"] if i in ids]
    state["last_eval"] = today.isoformat()
    _save_state(state)
    return visible()


def visible() -> list[dict]:
    state = _state()
    return [a for a in state["active"] if a["id"] not in state["dismissed"]]


def count() -> int:
    try:
        return len(visible())
    except Exception:
        return 0


def dismiss(alert_id: str) -> None:
    state = _state()
    if alert_id and alert_id not in state["dismissed"]:
        state["dismissed"].append(alert_id)
        _save_state(state)


def dismiss_all() -> None:
    state = _state()
    state["dismissed"] = [a["id"] for a in state["active"]]
    _save_state(state)


# ---------- telling you ----------

def notify_mac(title: str, message: str) -> bool:
    """A macOS notification via osascript; quietly does nothing elsewhere."""
    if sys.platform != "darwin":
        return False
    safe = lambda s: str(s).replace("\\", " ").replace('"', "'")[:200]  # noqa: E731
    try:
        subprocess.run(["osascript", "-e", f'display notification "{safe(message)}" with title "{safe(title)}"'],
                       check=True, timeout=10, capture_output=True)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def send_email(subject: str, body: str) -> None:
    cfg = settings()
    if not email_ready(cfg):
        raise ValueError("Fill in your e-mail address and e-mail server first.")
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg["smtp_from"] or cfg["smtp_user"]
    msg["To"] = cfg["email_to"]
    msg.set_content(body)
    password = secrets_store.get_smtp_password()
    try:
        if cfg["smtp_port"] == 465:
            server = smtplib.SMTP_SSL(cfg["smtp_host"], 465, timeout=20, context=ssl.create_default_context())
        else:
            server = smtplib.SMTP(cfg["smtp_host"], cfg["smtp_port"], timeout=20)
            server.starttls(context=ssl.create_default_context())
        with server:
            if cfg["smtp_user"] and password:
                server.login(cfg["smtp_user"], password)
            server.send_message(msg)
    except (OSError, smtplib.SMTPException) as exc:
        raise ValueError(f"The e-mail could not be sent: {exc}") from None


def send_test() -> None:
    send_email(f"{branding.PRODUCT_NAME} test e-mail", f"This is a test from {branding.PRODUCT_NAME}. If you can read it, your weekly digest is set up.")


def digest_text(summary: dict, chance: float | None, alerts: list[dict], actions: list[dict]) -> str:
    lines = [f"Your {branding.PRODUCT_NAME} weekly digest", ""]
    if chance is not None:
        lines.append(f"Chance your money lasts: {presentation.percent_display(chance)}")
    lines.append(f"Net worth: ${float(summary.get('net_worth') or 0):,.0f}")
    lines.append("")
    if alerts:
        lines.append(f"Needs a look ({len(alerts)}):")
        lines += [f"  - {a['title']}: {a['detail']}" for a in alerts]
    else:
        lines.append("Nothing needs a look this week.")
    if actions:
        lines += ["", "Top next steps:"]
        lines += [f"  {a['rank']}. {a['title']}" for a in actions[:3]]
    lines += ["", "Open your dashboard to see the details.",
              "Not financial, investment, tax or legal advice."]
    return "\n".join(lines)


def run_daily(summary: dict, chance: float | None, positions: list[dict], data_issues: list[dict],
              actions: list[dict], *, today: date | None = None) -> dict:
    """The once-a-day job: refresh alerts, Mac-notify new ones, and send the
    weekly digest when it is due. Returns what happened (for tests/logs)."""
    today = today or date.today()
    cfg = settings()
    history = progress.plan_check_history()
    before = {a["id"] for a in _state()["active"]}
    shown = refresh(evaluate(summary, chance, positions, data_issues, history, today=today), today=today)
    result = {"alerts": len(shown), "notified": 0, "digest": False}

    state = _state()
    state["last_daily"] = today.isoformat()
    fresh = [a for a in shown if a["id"] not in state["notified"]]
    if cfg["mac_notify"] and fresh:
        if notify_mac(branding.PRODUCT_NAME, fresh[0]["title"] + (f" (+{len(fresh) - 1} more)" if len(fresh) > 1 else "")):
            result["notified"] = len(fresh)
    state["notified"] = sorted(set(state["notified"]) | {a["id"] for a in fresh})

    if cfg["digest"] and email_ready(cfg):
        last = state["last_digest"]
        due = True
        if last:
            try:
                due = (today - datetime.strptime(last, "%Y-%m-%d").date()).days >= DIGEST_EVERY_DAYS
            except ValueError:
                due = True
        if due:
            try:
                send_email(f"Your {branding.PRODUCT_NAME} weekly digest", digest_text(summary, chance, shown, actions))
                state["last_digest"] = today.isoformat()
                result["digest"] = True
            except ValueError as exc:
                print(f"Weekly digest not sent: {exc}")
    _save_state(state)
    result["new"] = len([i for i in (a["id"] for a in shown) if i not in before])
    return result


def run_daily_job() -> dict | None:
    """Builds today's numbers and runs run_daily -- called from the dashboard's
    background loop once a day (skips if it already ran today)."""
    today = date.today()
    if _state()["last_daily"] == today.isoformat():
        return None
    from source.common import backup, linked_data
    from source.reporting import advice, data_check
    from source.reporting.plan_health import plan_health_items
    from source.webapp.pages.summary import build_plan_views

    v = build_plan_views()
    if v["empty_plan"]:
        return None
    s, chance = v["s"], v["display_result"]["success_rate"]
    positions = linked_data.read_linked_portfolio_positions()
    issues = data_check.run_checks(s, positions, backup.verify_latest())
    actions = advice.build_actions(s, chance, positions, issues, plan_health_items(s))
    progress.record_plan_check(chance)
    return run_daily(s, chance, positions, issues, actions, today=today)
