"""Parse WhatsApp chat exports (.txt) from Android and iOS.

Supported line headers (with or without seconds, 12h or 24h clock):
    Android: 10/10/26, 10:42 am - Sender Name: message
    iOS:     [10/10/26, 10:42:15 AM] Sender Name: message

Lines that don't start with a header belong to the previous message
(multi-line messages). Lines without "Sender: " are system messages.
Nothing is discarded: unparseable lines are preserved with missing values.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

import config

_INVISIBLE = dict.fromkeys(map(ord, "‎‏‪‫‬‭‮﻿"), None)

_DATE = r"(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2,4})"
_TIME = r"(\d{1,2}):(\d{2})(?::(\d{2}))?(?:\s?([AaPp])\.?\s?[Mm]\.?)?"

ANDROID_RE = re.compile(rf"^{_DATE},?\s+{_TIME}\s+-\s+(.*)$")
IOS_RE = re.compile(rf"^\[{_DATE},?\s+{_TIME}\]\s+(.*)$")

MEDIA_MARKERS = (
    "<media omitted>", "image omitted", "video omitted", "audio omitted", "document omitted",
    "sticker omitted", "gif omitted", "<attached:", "(file attached)",
)
DELETED_MARKERS = ("this message was deleted", "you deleted this message")


@dataclass
class RawMessage:
    timestamp: Optional[datetime]
    sender: Optional[str]
    text: str
    message_type: str = "text"  # text | media | system | deleted
    lines: List[str] = field(default_factory=list)


def _build_datetime(d1: str, d2: str, y: str, hh: str, mm: str, ss: Optional[str],
                    ampm: Optional[str], order: str) -> Optional[datetime]:
    a, b, year = int(d1), int(d2), int(y)
    if year < 100:
        year += 2000
    # Disambiguate day/month: a value > 12 can only be a day.
    if a > 12 and b <= 12:
        day, month = a, b
    elif b > 12 and a <= 12:
        month, day = a, b
    elif order == "MDY":
        month, day = a, b
    else:
        day, month = a, b
    hour, minute, second = int(hh), int(mm), int(ss or 0)
    if ampm:
        ampm = ampm.lower()
        if ampm == "p" and hour < 12:
            hour += 12
        if ampm == "a" and hour == 12:
            hour = 0
    try:
        return datetime(year, month, day, hour, minute, second)
    except ValueError:
        return None


def _split_sender(rest: str):
    """'Name: text' -> (Name, text). System lines have no 'name: ' prefix."""
    m = re.match(r"^([^:]{1,60}?):\s(.*)$", rest, flags=re.S)
    if m:
        return m.group(1).strip(), m.group(2)
    return None, rest


def _classify_raw(text: str, sender: Optional[str]) -> str:
    low = text.lower().strip()
    if sender is None:
        return "system"
    if any(mk in low for mk in DELETED_MARKERS):
        return "deleted"
    if any(mk in low for mk in MEDIA_MARKERS):
        return "media"
    return "text"


def parse_whatsapp_text(content: str, date_order: Optional[str] = None) -> List[RawMessage]:
    order = (date_order or config.DATE_ORDER).upper()
    content = content.translate(_INVISIBLE).replace(" ", " ").replace(" ", " ")
    messages: List[RawMessage] = []
    current: Optional[RawMessage] = None

    for line in content.splitlines():
        m = IOS_RE.match(line) or ANDROID_RE.match(line)
        if m:
            d1, d2, y, hh, mm, ss, ampm, rest = m.groups()
            ts = _build_datetime(d1, d2, y, hh, mm, ss, ampm, order)
            sender, text = _split_sender(rest)
            current = RawMessage(timestamp=ts, sender=sender, text=text, lines=[line])
            messages.append(current)
        elif current is not None:
            current.text += "\n" + line
            current.lines.append(line)
        elif line.strip():
            # Text before the first header: keep it, with missing-value markers.
            current = RawMessage(timestamp=None, sender=None, text=line, lines=[line])
            messages.append(current)

    for msg in messages:
        msg.text = msg.text.strip()
        msg.message_type = _classify_raw(msg.text, msg.sender)
    return [m for m in messages if m.text]
