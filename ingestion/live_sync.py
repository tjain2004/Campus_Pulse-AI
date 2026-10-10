"""Import messages streamed by the WhatsApp bridge (whatsapp_bridge/bridge.js).

The bridge writes, under data/live/:
    status.json            connection state + heartbeat
    groups.json            all groups on the linked number
    selected_groups.json   groups the student chose to sync (written by the dashboard)
    messages/*.jsonl       one JSON record per message
    media/*.pdf            PDFs shared in selected groups
This module turns those records into normal CampusPulse messages. WhatsApp
message IDs give stable fingerprints, so re-syncing never duplicates anything.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import config
from database import repository as repo
from database.schemas import NormalizedMessage
from ingestion.normalizer import extract_links, mask_phone

LIVE_DIR = config.DATA_DIR / "live"
HEARTBEAT_STALE_S = 30

CATEGORY_HINTS = [
    ("placements", r"placement|career|intern|job|tpo|t&p|recruit"),
    ("hackathons", r"hack|sih|devfolio|team\b"),
    ("events", r"fest|club|event|cultural|sports|volunteer|committee"),
    ("resources", r"notes|resource|material|study"),
    ("academics", r"cse|it\b|ece|class|section|batch|year|sem|faculty|dept|department|academic"),
]


@dataclass
class SyncResult:
    files: int = 0
    records: int = 0
    new: int = 0
    duplicates: int = 0
    documents: int = 0
    groups: int = 0


def _dir(live_dir: Optional[Path]) -> Path:
    return Path(live_dir) if live_dir else LIVE_DIR


def _read(name: str, default, live_dir: Optional[Path] = None):
    try:
        return json.loads((_dir(live_dir) / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def status(live_dir: Optional[Path] = None) -> Dict:
    """Bridge status with an 'alive' flag derived from the heartbeat."""
    d = _dir(live_dir)
    st = _read("status.json", {"state": "not_started"}, d)
    st["alive"] = False
    if st.get("updated"):
        try:
            updated = datetime.fromisoformat(st["updated"].replace("Z", "+00:00"))
            st["alive"] = (datetime.now(timezone.utc) - updated).total_seconds() < HEARTBEAT_STALE_S
        except ValueError:
            pass
    st["qr_path"] = str(d / "qr.png") if (d / "qr.png").exists() else None
    st["avatar_path"] = str(d / "profile.jpg") if (d / "profile.jpg").exists() else None
    return st


def available_groups(live_dir: Optional[Path] = None) -> List[Dict]:
    return _read("groups.json", [], live_dir)


def selected_groups(live_dir: Optional[Path] = None) -> List[str]:
    return _read("selected_groups.json", [], live_dir)


def save_selected_groups(ids: List[str], live_dir: Optional[Path] = None) -> None:
    d = _dir(live_dir)
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / "selected_groups.json.tmp"
    tmp.write_text(json.dumps(sorted(set(ids))), encoding="utf-8")
    tmp.replace(d / "selected_groups.json")


def send_command(action: str, live_dir: Optional[Path] = None) -> None:
    d = _dir(live_dir)
    d.mkdir(parents=True, exist_ok=True)
    (d / "command.json").write_text(json.dumps({"action": action}), encoding="utf-8")


def guess_category(group_name: str) -> str:
    low = group_name.lower()
    for cat, pattern in CATEGORY_HINTS:
        if re.search(pattern, low):
            return cat
    return "general"


def record_to_message(rec: Dict, redact_phones: bool = True) -> Optional[NormalizedMessage]:
    if not rec.get("id") or not rec.get("group_name"):
        return None
    ts = rec.get("timestamp")
    when = datetime.fromtimestamp(int(ts)) if ts else None  # local time, like chat exports
    text = (rec.get("text") or "").strip()
    sender = rec.get("sender") or None
    kind = rec.get("kind", "text")
    if kind not in ("text", "media", "system", "deleted"):
        kind = "text"
    if kind == "system" and not text:
        return None
    if not text:
        text = "<message>"
    if redact_phones:
        text = mask_phone(text)
        sender = mask_phone(sender) if sender else sender
    return NormalizedMessage(
        group_name=rec["group_name"], timestamp=when, sender=sender, text=text,
        message_type=kind,  # type: ignore[arg-type]
        links=extract_links(text),
        fingerprint=hashlib.sha1(f"wa:{rec['id']}".encode()).hexdigest(),
    )


def sync(conn: sqlite3.Connection, redact_phones: bool = True, live_dir: Optional[Path] = None) -> SyncResult:
    """Import every record the bridge has written so far (idempotent)."""
    res = SyncResult()
    d = _dir(live_dir)
    msg_dir = d / "messages"
    if not msg_dir.exists():
        return res
    by_group: Dict[str, List[NormalizedMessage]] = {}
    pdfs: Dict[str, str] = {}
    for f in sorted(msg_dir.glob("*.jsonl")):
        res.files += 1
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue  # partially written last line; picked up next sync
            res.records += 1
            msg = record_to_message(rec, redact_phones)
            if msg:
                by_group.setdefault(msg.group_name, []).append(msg)
            if rec.get("file"):
                pdfs[rec["file"]] = rec["group_name"]

    for name, msgs in by_group.items():
        gid = repo.upsert_group(conn, name, guess_category(name))
        new, dup = repo.insert_messages(conn, gid, msgs)
        res.new += new
        res.duplicates += dup
    res.groups = len(by_group)

    existing = {d["filename"] for d in repo.list_documents(conn)}
    for fname, group_name in pdfs.items():
        path = d / "media" / fname
        if fname in existing or not path.exists():
            continue
        try:
            from ingestion.pdf_parser import digest_pdf
            digest = digest_pdf(path.read_bytes())
        except Exception:
            continue
        gid = repo.upsert_group(conn, group_name, guess_category(group_name))
        repo.add_document(conn, fname, str(path), digest.summary, digest.pages, gid)
        res.documents += 1
    return res


def sync_and_process(conn: sqlite3.Connection, now: Optional[datetime] = None,
                     live_dir: Optional[Path] = None) -> SyncResult:
    res = sync(conn, live_dir=live_dir)
    if res.new or res.documents:
        from agent.orchestrator import run_pipeline
        run_pipeline(conn, now=now)
    return res
