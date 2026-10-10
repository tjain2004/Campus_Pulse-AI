"""Start/stop one WhatsApp bridge process per logged-in user.

Real mode runs `node whatsapp_bridge/bridge.js` with the user's own folder and
session id, so every student links their own number. Simulated mode runs
scripts/simulate_bridge.py for demos without a phone.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Dict, Optional

import config
from backend import userspace
from ingestion import live_sync

BRIDGE_DIR = config.BASE_DIR / "whatsapp_bridge"
_procs: Dict[int, subprocess.Popen] = {}
_guard = threading.Lock()


class BridgeError(RuntimeError):
    pass


def check_requirements() -> Optional[str]:
    """Return a human-readable problem, or None if the real bridge can start."""
    if not shutil.which("node"):
        return "Node.js isn't installed (or not on PATH). Install Node.js 18+ from nodejs.org and restart the server."
    if not (BRIDGE_DIR / "node_modules" / "whatsapp-web.js").exists():
        return "Run `npm install` once inside the whatsapp_bridge folder, then try again."
    return None


def is_running(uid: int) -> bool:
    with _guard:
        p = _procs.get(uid)
        return p is not None and p.poll() is None


def start(uid: int, simulate: bool = False) -> Dict:
    if is_running(uid):
        return {"started": False, "message": "Already running"}
    live = userspace.live_dir(uid)
    live.mkdir(parents=True, exist_ok=True)
    (live / "command.json").unlink(missing_ok=True)
    env = dict(os.environ, CP_LIVE_DIR=str(live), CP_SESSION_ID=f"user_{int(uid)}")
    if simulate:
        cmd = [sys.executable, str(config.BASE_DIR / "scripts" / "simulate_bridge.py")]
    else:
        problem = check_requirements()
        if problem:
            raise BridgeError(problem)
        cmd = [shutil.which("node") or "node", str(BRIDGE_DIR / "bridge.js")]
    log = open(live / "bridge.log", "a", encoding="utf-8")
    kwargs = {}
    if os.name == "nt":  # don't pop up a console window on Windows
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.Popen(cmd, cwd=str(BRIDGE_DIR if not simulate else config.BASE_DIR), env=env,
                            stdout=log, stderr=subprocess.STDOUT, **kwargs)
    with _guard:
        _procs[uid] = proc
    return {"started": True, "simulated": simulate}


def stop(uid: int, logout: bool = False, wait_s: float = 8.0) -> None:
    """Ask the bridge to exit cleanly (keeps or removes the WhatsApp session)."""
    live = userspace.live_dir(uid)
    live_sync.send_command("logout" if logout else "stop", live)
    with _guard:
        p = _procs.get(uid)
    if p is None:
        return
    deadline = time.time() + wait_s
    while time.time() < deadline and p.poll() is None:
        time.sleep(0.25)
    if p.poll() is None:
        p.terminate()
    with _guard:
        _procs.pop(uid, None)


def stop_all() -> None:
    for uid in list(_procs):
        try:
            stop(uid, wait_s=3)
        except Exception:
            pass


def log_tail(uid: int, lines: int = 25) -> str:
    f = userspace.live_dir(uid) / "bridge.log"
    if not f.exists():
        return ""
    return "\n".join(f.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])
