"""Validate uploads and run the import step (file -> parsed -> stored)."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import config
from database import repository as repo
from ingestion.normalizer import normalize
from ingestion.whatsapp_parser import parse_whatsapp_text


class UploadError(ValueError):
    pass


@dataclass
class ImportResult:
    group_id: int
    group_name: str
    parsed: int
    new: int
    duplicates: int


def decode_upload(data: bytes, filename: str) -> str:
    if not filename.lower().endswith(".txt"):
        raise UploadError("Please upload a WhatsApp chat export (.txt).")
    if len(data) > config.MAX_UPLOAD_MB * 1024 * 1024:
        raise UploadError(f"File is larger than {config.MAX_UPLOAD_MB:.0f} MB.")
    for enc in ("utf-8-sig", "utf-16", "cp1252"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    raise UploadError("Could not read the file encoding. Re-export the chat as UTF-8 text.")


def guess_group_name(filename: str) -> str:
    stem = Path(filename).stem
    stem = stem.replace("WhatsApp Chat with ", "").replace("WhatsApp Chat - ", "")
    return stem.replace("_", " ").strip() or "Imported Group"


def import_chat(
    conn: sqlite3.Connection,
    content: str,
    group_name: str,
    category: str = "general",
    official_senders: Optional[List[str]] = None,
    redact_phones: bool = True,
) -> ImportResult:
    raws = parse_whatsapp_text(content)
    if not raws:
        raise UploadError("No WhatsApp messages found. Is this a chat export?")
    normalized = normalize(group_name, raws, redact_phones=redact_phones)
    group_id = repo.upsert_group(conn, group_name, category, official_senders)
    new, dup = repo.insert_messages(conn, group_id, normalized)
    return ImportResult(group_id, group_name, len(raws), new, dup)
