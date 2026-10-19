#!/usr/bin/env python3
"""Fresh-install check: starts the app with an empty home folder and walks
through what a brand-new user sees, then restarts it to prove the data and
password survive an upgrade-style relaunch.

    python3 scripts/smoke_test.py                       # from source
    python3 scripts/smoke_test.py --server dist/app-server/app-server   # the built Mac app's server

Safe to run on your own Mac: it uses a throwaway home folder, its own port and
its own Keychain service name, so your real data and password are never
touched, and it removes what it added when it finishes."""
from __future__ import annotations

import argparse
import http.client
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PORT = 18998
PASSWORD = "smoke-test-password"


def request(method, path, body=None, cookie=None):
    conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=20)
    headers = {"Content-Type": "application/json"}
    if cookie:
        headers["Cookie"] = cookie
    conn.request(method, path, body=json.dumps(body).encode() if body is not None else None, headers=headers)
    resp = conn.getresponse()
    data = resp.read().decode("utf-8", "replace")
    conn.close()
    return resp, data


def start(cmd, env):
    proc = subprocess.Popen(cmd, env=env, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(120):
        time.sleep(0.5)
        try:
            if request("GET", "/api/health")[0].status == 200:
                return proc
        except OSError:
            pass
    proc.kill()
    raise SystemExit("FAIL: the app did not start within 60 seconds")


def stop(proc):
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


def check(ok, label):
    print(("PASS  " if ok else "FAIL  ") + label)
    if not ok:
        raise SystemExit(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", help="path to the packaged app-server binary (default: run from source)")
    args = ap.parse_args()
    home = tempfile.mkdtemp(prefix="smoke-home-")
    env = dict(os.environ, HOME=home, FINSI_PORT=str(PORT), PYTHONPATH=str(ROOT))
    env.pop("FINSI_DEMO", None)
    service = f"RetirementPlan-smoke-{os.getpid()}"
    env["RP_KEYCHAIN_SERVICE"] = service
    env.pop("RP_USE_LIVE_KEYCHAIN", None)
    if sys.platform != "darwin":      # no Keychain here: use a file-based store inside the throwaway home
        env.setdefault("PYTHON_KEYRING_BACKEND", "keyrings.alt.file.PlaintextKeyring")
        env.setdefault("XDG_DATA_HOME", home)
    cmd = [args.server, "--no-browser"] if args.server else [sys.executable, "-m", "source.webapp.dashboard", "--no-browser"]
    proc = None
    try:
        proc = start(cmd, env)
        r, _ = request("GET", "/")
        check(r.status == 302 and r.getheader("Location") == "/welcome.html", "first launch sends you to the welcome screen")
        r, page = request("GET", "/welcome.html")
        check("/icons/logo.svg" in page and "admin password" in page, "welcome screen shows the logo and asks for a password")
        r, _ = request("POST", "/api/assumptions", {})
        check(r.status == 403, "nothing can be saved before setup")
        r, data = request("POST", "/api/first-run", {"password": PASSWORD, "confirm": PASSWORD})
        info = json.loads(data)
        check(r.status == 200 and info.get("recovery_key"), "password and database created; recovery key shown")
        cookie = (r.getheader("Set-Cookie") or "").split(";")[0]
        r, _ = request("GET", "/", cookie=cookie)
        check(r.status == 302 and "wizard" in (r.getheader("Location") or ""), "next stop is the setup wizard")
        r, page = request("GET", "/summary.html", cookie=cookie)
        check(r.status == 200, "dashboard opens once signed in")
        stop(proc)
        proc = start(cmd, env)               # relaunch, as after an update
        r, _ = request("GET", "/summary.html")
        check(r.status == 302 and r.getheader("Location") == "/login.html", "after a restart you must log in")
        r, data = request("POST", "/api/login", {"password": "wrong password"})
        check(r.status == 401, "wrong password is refused")
        r, data = request("POST", "/api/login", {"password": PASSWORD})
        check(r.status == 200, "right password logs in")
        cookie = (r.getheader("Set-Cookie") or "").split(";")[0]
        r, data = request("POST", "/api/reset-password", {"recovery_key": info["recovery_key"], "password": "new-smoke-password", "confirm": "new-smoke-password"})
        check(r.status == 200 and json.loads(data).get("recovery_key"), "recovery key resets the password")
        r, _ = request("GET", "/legal.html")
        check(r.status == 200, "privacy and terms are readable")
        print("\nAll checks passed.")
    finally:
        if proc:
            stop(proc)
        shutil.rmtree(home, ignore_errors=True)
        if sys.platform == "darwin":
            for account in ("auth", "vault", "plaid", "default"):
                subprocess.run(["security", "delete-generic-password", "-s", service, "-a", account],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == "__main__":
    main()
