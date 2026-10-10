"""Pretend to be the WhatsApp bridge (no phone needed).

Writes the same files bridge.js writes, so you can test the WhatsApp page and
auto-sync end to end. The web app starts it for you ("Try a simulated
connection"); you can also run it by hand:

    python scripts/simulate_bridge.py                 # QR for ~8 s, then connected
    CP_LIVE_DIR=data/users/1/live python scripts/simulate_bridge.py
"""
from __future__ import annotations

import json
import os
import random
import struct
import sys
import time
import zlib
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIVE = Path(os.environ.get("CP_LIVE_DIR") or ROOT / "data" / "live")
GROUP = {"id": "120363000000000001@g.us", "name": "CSE Final Year (live demo)", "participants": 64,
         "unread": 3, "last_activity": int(time.time())}
OTHER = {"id": "120363000000000002@g.us", "name": "Family", "participants": 9, "unread": 0,
         "last_activity": int(time.time()) - 3600}
SCRIPT = [
    ("Rahul (CR)", "Reminder: CN lab internal is on Monday 11 AM in Lab 4. Bring your record."),
    ("Priya", "ok"),
    ("Prof. Iyer", "Update: CN lab internal has been moved to Tuesday 2 PM in Lab 6."),
    ("Aditya", "someone said the CN internal is cancelled?? is it true"),
    ("Prof. Iyer", "No change from my last message. CN lab internal will be held as scheduled on Tuesday 2 PM. "
                   "Please ignore rumours."),
]
ACCOUNT = {"name": "Demo Student", "number": "••••••4321", "platform": "simulated",
           "about": "Hey there! I am using WhatsApp."}


def write(name: str, data) -> None:
    LIVE.mkdir(parents=True, exist_ok=True)
    tmp = LIVE / (name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(LIVE / name)


def status(state: str, detail: str, account=None) -> None:
    write("status.json", {"state": state, "detail": detail, "updated": datetime.now(timezone.utc).isoformat(),
                          "account": account, "pid": os.getpid(), "simulated": True})


def fake_qr_png(path: Path, size: int = 29, scale: int = 8) -> None:
    """A QR-looking placeholder image (pure Python, no libraries)."""
    rnd = random.Random(42)
    grid = [[rnd.random() < 0.45 for _ in range(size)] for _ in range(size)]
    for ox, oy in ((0, 0), (size - 7, 0), (0, size - 7)):  # finder squares
        for y in range(7):
            for x in range(7):
                edge = x in (0, 6) or y in (0, 6)
                core = 2 <= x <= 4 and 2 <= y <= 4
                grid[oy + y][ox + x] = edge or core
    rows = []
    for y in range(size * scale):
        row = bytearray([0])
        for x in range(size * scale):
            row.append(0 if grid[y // scale][x // scale] else 255)
        rows.append(bytes(row))
    w = h = size * scale

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(b"".join(rows))) + chunk(b"IEND", b"")
    path.write_bytes(png)


def stop_requested() -> bool:
    f = LIVE / "command.json"
    if not f.exists():
        return False
    try:
        cmd = json.loads(f.read_text()).get("action")
    except ValueError:
        return False
    if cmd in ("stop", "logout"):
        f.unlink(missing_ok=True)
        if cmd == "logout":
            status("logged_out", "Unlinked (simulated)")
        else:
            status("stopped", "Disconnected (simulated, session kept)")
        return True
    return False


def main() -> None:
    LIVE.mkdir(parents=True, exist_ok=True)
    qr_seconds = 0 if "--no-qr" in sys.argv else 8
    if qr_seconds:
        fake_qr_png(LIVE / "qr.png")
        end = time.time() + qr_seconds
        while time.time() < end:
            status("qr", "Waiting for you to scan the QR code (simulated — connects by itself)")
            if stop_requested():
                return
            time.sleep(1)
        (LIVE / "qr.png").unlink(missing_ok=True)
    write("groups.json", [GROUP, OTHER])
    (LIVE / "messages").mkdir(parents=True, exist_ok=True)
    out = LIVE / "messages" / "CSE_Final_Year_live_demo__sim.jsonl"
    sent = sum(1 for _ in out.open(encoding="utf-8")) if out.exists() else 0
    print("Simulated bridge connected. Select 'CSE Final Year (live demo)'.", flush=True)
    tick = 0
    while True:
        status("ready", "Connected (simulated)", ACCOUNT)
        if stop_requested():
            return
        selected = json.loads((LIVE / "selected_groups.json").read_text()) \
            if (LIVE / "selected_groups.json").exists() else []
        if GROUP["id"] in selected and sent < len(SCRIPT) and tick % 4 == 0:
            sender, text = SCRIPT[sent]
            rec = {"id": f"sim_{sent}", "group_id": GROUP["id"], "group_name": GROUP["name"],
                   "timestamp": int(time.time()), "sender": sender, "text": text, "wa_type": "chat",
                   "kind": "text", "file": None}
            with out.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec) + "\n")
            print(f"→ {sender}: {text}", flush=True)
            sent += 1
        tick += 1
        time.sleep(float(os.environ.get("SIM_TICK", "2")))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        status("stopped", "Simulator stopped")
