"""User accounts: registration, login, password hashing, brute-force protection.

Accounts live in data/auth.db, separate from each student's message data.
Passwords are stored only as salted scrypt/pbkdf2 hashes (werkzeug).
"""
from __future__ import annotations

import re
import sqlite3
import threading
import time
from collections import defaultdict, deque
from datetime import datetime
from typing import Dict, Optional, Tuple

from werkzeug.security import check_password_hash, generate_password_hash

import config

EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[A-Za-z]{2,}$")
MAX_FAILS, WINDOW_S = 5, 10 * 60

_lock = threading.Lock()
_fails: Dict[str, deque] = defaultdict(deque)

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    email         TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    last_login    TEXT
);
"""


class AuthError(ValueError):
    pass


def _db() -> sqlite3.Connection:
    path = config.DATA_DIR / "auth.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def _public(row) -> Dict:
    return {"id": row["id"], "name": row["name"], "email": row["email"],
            "created_at": row["created_at"], "last_login": row["last_login"]}


def validate(name: str, email: str, password: str) -> Tuple[str, str]:
    name, email = (name or "").strip(), (email or "").strip().lower()
    if not 2 <= len(name) <= 60:
        raise AuthError("Please enter your name (2–60 characters).")
    if not EMAIL_RE.match(email):
        raise AuthError("Please enter a valid email address.")
    if len(password or "") < 8 or not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        raise AuthError("Password must be at least 8 characters and include a letter and a number.")
    return name, email


def register(name: str, email: str, password: str) -> Dict:
    name, email = validate(name, email, password)
    with _lock, _db() as conn:
        if conn.execute("SELECT 1 FROM accounts WHERE email = ?", (email,)).fetchone():
            raise AuthError("An account with this email already exists. Try logging in.")
        cur = conn.execute(
            "INSERT INTO accounts (name, email, password_hash, created_at) VALUES (?,?,?,?)",
            (name, email, generate_password_hash(password), datetime.now().isoformat(timespec="seconds")),
        )
        row = conn.execute("SELECT * FROM accounts WHERE id = ?", (cur.lastrowid,)).fetchone()
        return _public(row)


def _throttled(key: str) -> bool:
    now = time.time()
    q = _fails[key]
    while q and now - q[0] > WINDOW_S:
        q.popleft()
    return len(q) >= MAX_FAILS


def login(email: str, password: str, client_ip: str = "") -> Dict:
    email = (email or "").strip().lower()
    key = f"{email}|{client_ip}"
    with _lock:
        if _throttled(key):
            raise AuthError("Too many failed attempts. Please wait 10 minutes and try again.")
    with _db() as conn:
        row = conn.execute("SELECT * FROM accounts WHERE email = ?", (email,)).fetchone()
        ok = bool(row) and check_password_hash(row["password_hash"], password or "")
        if not ok:
            with _lock:
                _fails[key].append(time.time())
            raise AuthError("Incorrect email or password.")  # same message: don't reveal which
        conn.execute("UPDATE accounts SET last_login = ? WHERE id = ?",
                     (datetime.now().isoformat(timespec="seconds"), row["id"]))
        with _lock:
            _fails.pop(key, None)
        return _public(row)


def get_account(account_id: int) -> Optional[Dict]:
    with _db() as conn:
        row = conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
        return _public(row) if row else None


def change_password(account_id: int, current: str, new: str) -> None:
    with _db() as conn:
        row = conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
        if not row or not check_password_hash(row["password_hash"], current or ""):
            raise AuthError("Current password is incorrect.")
        validate(row["name"], row["email"], new)
        conn.execute("UPDATE accounts SET password_hash = ? WHERE id = ?", (generate_password_hash(new), account_id))


def update_name(account_id: int, name: str) -> None:
    name = (name or "").strip()
    if 2 <= len(name) <= 60:
        with _db() as conn:
            conn.execute("UPDATE accounts SET name = ? WHERE id = ?", (name, account_id))


def delete_account(account_id: int) -> None:
    with _db() as conn:
        conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
