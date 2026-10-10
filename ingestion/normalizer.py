"""Turn parser output into NormalizedMessage records (+ privacy masking)."""
from __future__ import annotations

import hashlib
import re
from typing import List

from database.schemas import NormalizedMessage
from ingestion.whatsapp_parser import RawMessage

URL_RE = re.compile(r"https?://[^\s<>()\"']+|www\.[^\s<>()\"']+", re.I)
# 10+ digit phone numbers, optionally with +country code, spaces or dashes.
PHONE_RE = re.compile(r"(?<![\w/])\+?\d[\d\s\-]{8,}\d(?![\w/])")


def mask_phone(text: str) -> str:
    def _mask(m: re.Match) -> str:
        digits = re.sub(r"\D", "", m.group(0))
        if len(digits) < 10:
            return m.group(0)
        return ("+" if m.group(0).startswith("+") else "") + "•" * (len(digits) - 4) + digits[-4:]
    return PHONE_RE.sub(_mask, text)


def extract_links(text: str) -> List[str]:
    return [u.rstrip(".,;:!?") for u in URL_RE.findall(text)]


def fingerprint(group: str, raw: RawMessage) -> str:
    key = f"{group}|{raw.timestamp.isoformat() if raw.timestamp else ''}|{raw.sender or ''}|{raw.text}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()


def normalize(group_name: str, raws: List[RawMessage], redact_phones: bool = True) -> List[NormalizedMessage]:
    out: List[NormalizedMessage] = []
    for raw in raws:
        fp = fingerprint(group_name, raw)  # computed on the original text
        sender = raw.sender
        text = raw.text
        if redact_phones:
            sender = mask_phone(sender) if sender else sender
            text = mask_phone(text)
        out.append(
            NormalizedMessage(
                group_name=group_name,
                timestamp=raw.timestamp,
                sender=sender,
                text=text,
                message_type=raw.message_type,  # type: ignore[arg-type]
                links=extract_links(text),
                fingerprint=fp,
            )
        )
    return out
