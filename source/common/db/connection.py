"""The one place a SQLite connection to this program's database is
opened -- a context manager that commits on clean exit and always
closes, with row_factory set to sqlite3.Row so every query result can
be read either by column name or converted straight to a dict.
"""

from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager

from source.common import config


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")



@contextmanager
def connect():
    # config.ensure_directories() used to run on every single call here
    # -- four Path.mkdir(exist_ok=True) syscalls -- even though every
    # real entry point (dashboard.run(), the collector scripts,
    # sync_industries, the test suite's own setup) already calls it
    # once at startup, and config.set_data_dir()/set_output_dir() call
    # it again themselves whenever the data location changes. A single
    # page load can open a dozen-plus connections (see
    # source.reporting.aggregate.build_summary), so that redundant
    # mkdir-times-4 was a real, if modest, per-request cost for
    # something that was already guaranteed true. Profiled via
    # cProfile against a build_summary() call: this alone was ~14% of
    # total time.
    conn = sqlite3.connect(str(config.DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
