"""Starts and stops the IBKR Client Portal Gateway (IBKR's own Java program) from the app, on this computer.

The gateway files travel with the app (``vendor/clientportal``, IBKR's software, unmodified apart from its
``root/conf.yaml`` settings file). The app bundle must stay untouched, and the gateway writes logs and a cache beside
itself, so the first start copies the bundled files to a normal folder under the app's data folder and runs them there.
Nothing is started unless the owner presses Start, and only the one fixed command below is ever run: no path or
argument from the web page is used. Java is not bundled: it has to be installed on the Mac (Java 8 or newer).
"""

from __future__ import annotations

import atexit
import os
import shutil
import socket
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from source.collector.broker_common import BrokerError
from source.common import config
from source.common.db.meta import get_meta, set_meta

RUN_FOLDER = "ibkr-gateway"
PRIVATE_PORT = 5757            # the port the bundled gateway's conf.yaml uses: this app's own, on this computer only
_AUTOSTART = "ibkr_gateway_autostart"
_proc: subprocess.Popen | None = None      # only a gateway this program started


def bundled_dir() -> Path | None:
    """The gateway files that ship with the app (inside the app when built, beside the source otherwise)."""
    candidates = []
    if getattr(sys, "_MEIPASS", None):
        candidates.append(Path(sys._MEIPASS) / "vendor" / "clientportal")
    candidates.append(Path(__file__).resolve().parents[2] / "vendor" / "clientportal")
    candidates.append(Path.home() / "clientportal")           # a copy the person unzipped themselves
    for c in candidates:
        if (c / "bin" / "run.sh").is_file() and (c / "root" / "conf.yaml").is_file():
            return c
    return None


def run_dir() -> Path:
    return config.DATA_DIR / RUN_FOLDER


def prepare(src: Path | None = None, dest: Path | None = None) -> Path:
    """Makes sure a writable copy exists and returns it. An existing copy is kept (its settings and logs stay)."""
    src = src or bundled_dir()
    dest = dest or run_dir()
    if (dest / "bin" / "run.sh").is_file():
        return dest
    if src is None:
        raise BrokerError("The IBKR gateway files were not found. Download the Client Portal Gateway from IBKR "
                          "(interactivebrokers.com, Trading > API Solutions) and unzip it into a folder called clientportal in your home folder.")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dest, ignore=shutil.ignore_patterns("logs", ".vertx", "__pycache__"), dirs_exist_ok=True)
    (dest / "logs").mkdir(exist_ok=True)
    os.chmod(dest / "bin" / "run.sh", 0o755)
    return dest


def java_env() -> dict:
    """The environment to run Java in, or raises a plain-language error when no Java is installed.
    (On a Mac /usr/bin/java exists even with no Java installed, and running it opens an install pop-up, so
    macOS's own java_home check is used instead of just looking for the file.)"""
    env = dict(os.environ)
    if sys.platform == "darwin":
        try:
            out = subprocess.run(["/usr/libexec/java_home"], capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            out = None
        if out is None or out.returncode != 0 or not out.stdout.strip():
            raise BrokerError("Java is not installed on this Mac. Install it from adoptium.net (Temurin 11 or 17 work well; the gateway needs Java 8 update 192 or newer), then press Start again.")
        env["JAVA_HOME"] = out.stdout.strip()
        env["PATH"] = env["JAVA_HOME"] + "/bin:" + env.get("PATH", "")
    elif not shutil.which("java"):
        raise BrokerError("Java is not installed. Install Java 8 or newer, then press Start again.")
    return env


def running() -> bool:
    return _proc is not None and _proc.poll() is None


def start(*, src: Path | None = None, dest: Path | None = None, env: dict | None = None, popen=subprocess.Popen) -> dict:
    """Starts the gateway (once). Returns where to sign in; the person still signs in to IBKR in the browser."""
    global _proc
    if running():
        return {"started": False, "message": "The gateway was already started by this app."}
    folder = prepare(src, dest)
    env = env if env is not None else java_env()
    log = open(folder / "logs" / "finsi-start.log", "ab")
    try:
        _proc = popen(["bash", "bin/run.sh", "root/conf.yaml"], cwd=str(folder), env=env, stdout=log, stderr=subprocess.STDOUT,
                      stdin=subprocess.DEVNULL, start_new_session=True)
    finally:
        log.close()
    return {"started": True, "message": "Starting the IBKR gateway. It takes about 10 seconds. Then sign in to IBKR in your browser."}


def stop() -> bool:
    """Stops a gateway this app started. Returns whether there was one."""
    global _proc
    if not running():
        _proc = None
        return False
    try:
        os.killpg(os.getpgid(_proc.pid), signal.SIGTERM)
    except (OSError, ProcessLookupError):
        _proc.terminate()
    _proc = None
    return True


def listen_port(folder: Path | None = None) -> int | None:
    """The port in the gateway's conf.yaml (read as text; no YAML library needed)."""
    folder = folder or (run_dir() if (run_dir() / "root" / "conf.yaml").is_file() else bundled_dir())
    if folder is None:
        return None
    try:
        for line in (folder / "root" / "conf.yaml").read_text().splitlines():
            if line.strip().startswith("listenPort:"):
                return int(line.split(":", 1)[1].strip().split()[0])
    except (OSError, ValueError, IndexError):
        pass
    return None


# ---- start with the app ----

def port_open(port: int, host: str = "127.0.0.1", timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except (OSError, ValueError):
        return False


def autostart_enabled() -> bool:
    return str(get_meta(_AUTOSTART, "1")) != "0"


def set_autostart(on: bool) -> None:
    set_meta(_AUTOSTART, "1" if on else "0")


def _autostart_now(*, starter=None) -> str:
    """Starts the gateway unless one already answers on its port. Returns a short note (also printed)."""
    if not autostart_enabled():
        return "IBKR gateway auto-start is off."
    port = listen_port() or PRIVATE_PORT
    if port_open(port):
        return f"An IBKR gateway is already running on port {port}."
    try:
        out = (starter or start)()
    except BrokerError as exc:
        return f"IBKR gateway not started: {exc}"
    except Exception as exc:        # never let this get in the way of the dashboard
        return f"IBKR gateway not started ({exc.__class__.__name__}: {exc})"
    if out.get("started"):
        # Point the IBKR tab at it unless the person chose a different address themselves.
        if not get_meta("ibkr_gateway_url", ""):
            set_meta("ibkr_gateway_url", f"https://localhost:{port}")
    return out.get("message", "")


KEEPALIVE_SECONDS = 60


def keepalive_once() -> bool:
    """One keep-alive ping ("/tickle") to the gateway, if it is up. IBKR drops an idle gateway session after a few minutes;
    pinging keeps a session you already signed in to alive. It never signs in, and it cannot extend IBKR's own daily reset."""
    from source.collector import ibkr
    try:
        url = ibkr.clean_gateway_url(get_meta("ibkr_gateway_url", ibkr.DEFAULT_URL))
        ibkr.Gateway(url, timeout=5.0).call("POST", "/tickle")
        return True
    except Exception:  # noqa: BLE001 -- the gateway being down or signed out is normal; try again next minute
        return False


def _keepalive_loop() -> None:
    while True:
        time.sleep(KEEPALIVE_SECONDS)
        keepalive_once()


def start_with_app() -> None:
    """Called once when the dashboard starts (run_dashboard.sh, the other run scripts and the Mac app all end up here).
    Runs on a background thread so a slow or missing Java never delays the dashboard; stops the gateway when the app quits."""
    if config.DEMO or os.environ.get("FINSI_NO_GATEWAY") == "1" or "unittest" in sys.modules:
        return
    atexit.register(stop)

    def work():
        print(_autostart_now())

    threading.Thread(target=work, daemon=True).start()
    threading.Thread(target=_keepalive_loop, daemon=True).start()
