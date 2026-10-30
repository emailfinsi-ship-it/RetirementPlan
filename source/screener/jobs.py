"""Screens run in the background (reading about 600 price histories takes a while): start one, then ask how far it has got.
Kept in memory only; the newest few are remembered."""

from __future__ import annotations

import secrets
import threading
import time

from source.screener import engine

_MAX_JOBS = 6
_jobs: dict[str, dict] = {}
_lock = threading.Lock()


def start(f: dict, *, scan=None) -> str:
    scan = scan or engine.scan
    job_id = secrets.token_urlsafe(8)
    job = {"id": job_id, "state": "running", "done": 0, "total": 0, "stage": "Starting", "result": None, "error": "",
           "cancel": False, "started": time.time(), "filters": f}

    def progress(done, total, stage="Reading prices"):
        job["done"], job["total"], job["stage"] = done, total, stage

    def work():
        try:
            job["result"] = scan(f, progress=progress, cancelled=lambda: job["cancel"])
            job["state"] = "cancelled" if job["cancel"] else "done"
        except Exception as exc:    # noqa: BLE001 -- shown to the person, never raised into the server
            job["error"] = str(exc) or exc.__class__.__name__
            job["state"] = "error"

    with _lock:
        for old in sorted(_jobs, key=lambda k: _jobs[k]["started"])[:max(0, len(_jobs) - _MAX_JOBS + 1)]:
            _jobs.pop(old, None)
        _jobs[job_id] = job
    threading.Thread(target=work, daemon=True).start()
    return job_id


def status(job_id: str) -> dict:
    job = _jobs.get(str(job_id or ""))
    if job is None:
        raise ValueError("That screen is no longer available. Run it again.")
    out = {"state": job["state"], "done": job["done"], "total": job["total"], "stage": job["stage"], "error": job["error"],
           "seconds": round(time.time() - job["started"], 1)}
    if job["state"] in ("done", "cancelled"):
        out["result"] = job["result"]
    return out


def cancel(job_id: str) -> None:
    job = _jobs.get(str(job_id or ""))
    if job is not None:
        job["cancel"] = True
