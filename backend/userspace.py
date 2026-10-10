"""Per-user data isolation.

Every account gets its own folder:  data/users/<id>/
    campuspulse.db   messages, analyses, events, tasks (same schema as before)
    live/            WhatsApp bridge files for THIS user only
    uploads/         PDFs they uploaded
One student can never query another student's messages: there is no shared
message table to leak from.
"""
from __future__ import annotations

import shutil
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict

import config
from database import repository as repo
from database.connection import get_connection

_conns: Dict[int, sqlite3.Connection] = {}
_locks: Dict[int, threading.RLock] = {}
_guard = threading.Lock()


def user_dir(uid: int) -> Path:
    d = config.DATA_DIR / "users" / str(int(uid))
    d.mkdir(parents=True, exist_ok=True)
    return d


def live_dir(uid: int) -> Path:
    return user_dir(uid) / "live"


def upload_dir(uid: int) -> Path:
    d = user_dir(uid) / "uploads"
    d.mkdir(parents=True, exist_ok=True)
    return d


def lock(uid: int) -> threading.RLock:
    with _guard:
        return _locks.setdefault(uid, threading.RLock())


def conn(uid: int, name: str = "") -> sqlite3.Connection:
    with _guard:
        c = _conns.get(uid)
        if c is None:
            c = get_connection(user_dir(uid) / "campuspulse.db")
            _conns[uid] = c
            p = repo.get_profile(c)
            if name and p.get("name") in (None, "", config.DEFAULT_PROFILE["name"]):
                p["name"] = name
                repo.save_profile(c, p)
        return c


def now_for(c: sqlite3.Connection) -> datetime:
    """'Today' for this user: a pinned demo date if they set one, else real time."""
    pinned = repo.get_profile(c).get("demo_now")
    if pinned:
        try:
            return datetime.fromisoformat(pinned)
        except ValueError:
            pass
    return datetime.now().replace(microsecond=0)


def delete_user_data(uid: int) -> None:
    with _guard:
        c = _conns.pop(uid, None)
        if c:
            c.close()
    shutil.rmtree(config.DATA_DIR / "users" / str(int(uid)), ignore_errors=True)
