"""Information extraction: dates/times, deadlines, venues, links, titles.

Relative dates ("tomorrow", "Sunday") are resolved against the message's own
timestamp, not today's date - "tomorrow" in a message from last Tuesday
means last Wednesday. Ambiguous resolutions are flagged for verification.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Optional

import config

MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3, "apr": 4, "april": 4,
    "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7, "aug": 8, "august": 8, "sep": 9,
    "sept": 9, "september": 9, "oct": 10, "october": 10, "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}
WEEKDAYS = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4,
            "saturday": 5, "sunday": 6}
_MON = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"

RELATIVE_RE = re.compile(r"\b(day after tomorrow|tomorrow|tmrw|tmr|today|tonight|tonite)\b", re.I)
WEEKDAY_RE = re.compile(r"\b(?:(this|next|coming)\s+)?(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", re.I)
DAY_MONTH_RE = re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?{_MON}\b\.?(?:,?\s*(20\d{{2}}))?", re.I)
MONTH_DAY_RE = re.compile(rf"\b{_MON}\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\b(?:,?\s*(20\d{{2}}))?", re.I)
NUMERIC_RE = re.compile(r"(?<![\d:/.])(\d{1,2})[/\-](\d{1,2})(?:[/\-](\d{2,4}))?(?![\d/:])")

TIME_COLON_RE = re.compile(r"\b(\d{1,2})[:.](\d{2})\s*(a\.?m\.?|p\.?m\.?)?(?![\w])", re.I)
TIME_AMPM_RE = re.compile(r"\b(\d{1,2})\s*(a\.?m\.?|p\.?m\.?)(?![\w])", re.I)
TIME_WORD_RE = re.compile(r"\b(noon|midnight|eod|end of (?:the )?day)\b", re.I)

DEADLINE_RE = re.compile(
    r"\b(due|deadline|last date|closes?|closing|submit|submission|before|by\s+(?:today|tomorrow|tonight|\w+day|\d)|"
    r"register by|apply by|extended|no later than|latest by|upload)\b", re.I)
URL_RE = re.compile(r"https?://[^\s<>()\"']+|www\.[^\s<>()\"']+", re.I)

_LOC_HEAD = r"(?i:Room|Lab|Hall|Auditorium|Block|Library|Ground|Amphitheatre|Amphitheater|Classroom|Canteen|Cafeteria|Building|Centre|Center|LT|Seminar Hall|Conference Room)"
LOC_PREFIXED_RE = re.compile(
    rf"(?:\b(?i:in|at|venue|location|@)\b[:\s\-]*|@\s*)(?:(?i:the)\s+)?((?:[A-Z][\w'&]*\s+){{0,3}}{_LOC_HEAD}(?:[\s\-]?[A-Z]?\d{{1,4}}[A-Z]?)?)"
)
LOC_BARE_RE = re.compile(r"\b((?i:room|lab|lt|hall)[\s\-]?\d{1,4}[A-Z]?)\b")
VENUE_COLON_RE = re.compile(r"\b(?i:venue|location)\s*[:\-]\s*([^\n,.;]{3,40})")

ACTION_VERBS = ("submit", "register", "apply", "upload", "fill", "complete", "prepare", "bring",
                "pay", "attend", "send", "finish", "carry", "collect", "update your", "share your")


@dataclass
class DateHit:
    value: datetime
    start: int
    has_time: bool = False
    ambiguous: bool = False
    phrase: str = ""


@dataclass
class Extraction:
    datetimes: List[DateHit] = field(default_factory=list)
    primary: Optional[datetime] = None
    has_time: bool = False
    is_deadline: bool = False
    location: Optional[str] = None
    links: List[str] = field(default_factory=list)
    title: str = ""
    action_required: bool = False
    needs_verification: bool = False


def _infer_year(month: int, day: int, ref: datetime) -> Optional[datetime]:
    try:
        cand = datetime(ref.year, month, day)
    except ValueError:
        return None
    if cand < ref - timedelta(days=60):
        try:
            cand = datetime(ref.year + 1, month, day)
        except ValueError:
            return None
    return cand


def _find_dates(text: str, ref: datetime) -> List[DateHit]:
    hits: List[DateHit] = []
    base = datetime(ref.year, ref.month, ref.day)
    for m in RELATIVE_RE.finditer(text):
        word = m.group(1).lower()
        offset = {"today": 0, "tonight": 0, "tonite": 0, "tomorrow": 1, "tmrw": 1, "tmr": 1,
                  "day after tomorrow": 2}[word]
        hits.append(DateHit(base + timedelta(days=offset), m.start(), phrase=m.group(0)))
    for m in WEEKDAY_RE.finditer(text):
        target = WEEKDAYS[m.group(2).lower()]
        delta = (target - ref.weekday()) % 7
        ambiguous = False
        if delta == 0:
            delta, ambiguous = 7, True
        if (m.group(1) or "").lower() == "next" and delta < 3:
            ambiguous = True
        hits.append(DateHit(base + timedelta(days=delta), m.start(), ambiguous=ambiguous, phrase=m.group(0)))
    for m in DAY_MONTH_RE.finditer(text):
        day, mon, year = int(m.group(1)), MONTHS[m.group(2).lower()[:3]], m.group(3)
        dt = _explicit(day, mon, year, ref)
        if dt:
            hits.append(DateHit(dt, m.start(), phrase=m.group(0)))
    for m in MONTH_DAY_RE.finditer(text):
        mon, day, year = MONTHS[m.group(1).lower()[:3]], int(m.group(2)), m.group(3)
        if any(abs(h.start - m.start()) < 3 for h in hits):
            continue
        dt = _explicit(day, mon, year, ref)
        if dt:
            hits.append(DateHit(dt, m.start(), phrase=m.group(0)))
    for m in NUMERIC_RE.finditer(text):
        a, b, year = int(m.group(1)), int(m.group(2)), m.group(3)
        if config.DATE_ORDER == "MDY":
            a, b = b, a
        day, mon = a, b
        if not (1 <= day <= 31 and 1 <= mon <= 12):
            continue
        dt = _explicit(day, mon, year, ref)
        if dt:
            hits.append(DateHit(dt, m.start(), phrase=m.group(0)))
    hits.sort(key=lambda h: h.start)
    return hits


def _explicit(day: int, mon: int, year: Optional[str], ref: datetime) -> Optional[datetime]:
    if year:
        y = int(year)
        y = y + 2000 if y < 100 else y
        try:
            return datetime(y, mon, day)
        except ValueError:
            return None
    return _infer_year(mon, day, ref)


def _find_times(text: str):
    """Return list of (start, hour, minute)."""
    out = []
    for m in TIME_COLON_RE.finditer(text):
        h, mi, ap = int(m.group(1)), int(m.group(2)), (m.group(3) or "").lower()
        if m.group(0)[len(m.group(1))] == "." and not ap:
            continue  # "7.5 CGPA" is not a time
        if h > 23 or mi > 59:
            continue
        h = _apply_ampm(h, ap)
        if not ap and 1 <= h < 8:
            h += 12  # campus heuristic: "4:00" means 4 PM
        out.append((m.start(), h, mi))
    for m in TIME_AMPM_RE.finditer(text):
        if any(abs(s - m.start()) < 3 for s, _, _ in out):
            continue
        h = int(m.group(1))
        if h > 12:
            continue
        out.append((m.start(), _apply_ampm(h, m.group(2).lower()), 0))
    for m in TIME_WORD_RE.finditer(text):
        w = m.group(1).lower()
        out.append((m.start(), 12 if w == "noon" else 23, 0 if w == "noon" else 59))
    if re.search(r"\btonight\b", text, re.I) and not out:
        out.append((0, 21, 0))
    out.sort()
    return out


def _apply_ampm(h: int, ap: str) -> int:
    if ap.startswith("p") and h < 12:
        return h + 12
    if ap.startswith("a") and h == 12:
        return 0
    return h


def extract_location(text: str) -> Optional[str]:
    m = VENUE_COLON_RE.search(text)
    if m:
        return m.group(1).strip()
    found = [mm.group(1).strip() for mm in LOC_PREFIXED_RE.finditer(text)]
    if not found:
        found = [mm.group(1).strip() for mm in LOC_BARE_RE.finditer(text)]
    if not found:
        return None
    # For "moved from Room 204 to Main Auditorium", the last venue is the new one.
    loc = found[-1] if re.search(r"\b(moved|shifted|changed|now|instead)\b", text, re.I) else found[0]
    loc = re.sub(r"\s+", " ", loc)
    return loc[:1].upper() + loc[1:]


_HEAD_HINT = re.compile(
    r"\b[A-Z]{2,}\b|(?i:\b(assignment|exam|midsem|mid-sem|quiz|viva|lab|internship|placement|drive|hackathon|"
    r"ppt|submission|registration|workshop|seminar|fest|briefing|talk|round|interview|resume|project)\b)")


def _main_sentence(text: str) -> str:
    """Skip greetings / fillers like 'Good morning everyone.' or 'There is no change.'"""
    body = re.sub(r"^\s*(forwarded|fwd)\s*[:\-]?\s*\n?", "", text, flags=re.I)
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n", URL_RE.sub("", body)) if s.strip()]
    for s in sentences:
        if _HEAD_HINT.search(s) and len(s.split()) >= 2:
            return s
    return sentences[0] if sentences else body


def build_title(text: str, max_words: int = 8) -> str:
    t = _main_sentence(text)
    t = re.sub(r"^[^\w]+", "", t)  # leading emoji / bullets
    t = re.sub(r"^(update|updated|reminder|important|urgent|notice|announcement|fyi|attention|guys|hi all|"
               r"hello everyone|forwarded|fwd)\s*[:!,\-–—]*\s*", "", t, flags=re.I)
    t = re.sub(r"^(the|a|an)\s+", "", t, flags=re.I)
    cut = re.split(r"\s+(?:is|are|has|have|will|would|was|by|closes?|due|deadline|starts?|begins?|covers|"
                   r"includes|tomorrow|today|tonight|at|from|this|next)\b|\s[—–-]\s|:|,|\.\s|!|\?|\(", t, maxsplit=1)
    words = cut[0].split()[:max_words]
    title = " ".join(words).strip(" -–—:")
    if len(title) < 4:
        title = " ".join(t.split()[:max_words])
    return title[:1].upper() + title[1:] if title else "Announcement"


def task_title(text: str, title: str) -> str:
    low = title.lower()
    for noun, verb in (("submission", "Submit"), ("registration", "Register for"),
                       ("applications", "Apply for"), ("application", "Apply for")):
        if noun in low:
            rest = re.sub(rf"\b{noun}\b", "", title, flags=re.I)
            rest = re.sub(r"\s+(for|of)\s*$", "", re.sub(r"\s{2,}", " ", rest)).strip()
            rest = re.sub(r"^(for|of)\s+", "", rest, flags=re.I)
            return f"{verb} {rest}".strip()
    clean = URL_RE.sub("", text)
    if re.search(r"\bappl(?:y|ications?)\b", clean, re.I):
        return f"Apply for {title}"
    if re.search(r"\bregister\b", clean, re.I):
        return f"Register for {title}"
    m = re.search(rf"\b({'|'.join(ACTION_VERBS)})\b([^.!?\n:]{{0,60}})", clean, re.I)
    if m:
        phrase = (m.group(1) + m.group(2))
        phrase = re.split(r"\s+(?:by|before|on|latest|asap)\b", phrase, maxsplit=1)[0].strip(" ,:-")
        return phrase[:1].upper() + phrase[1:]
    return f"Act on: {title}"


def extract(text: str, ref: Optional[datetime], prefer_last: bool = False) -> Extraction:
    ref = ref or config.reference_now()
    ex = Extraction()
    ex.links = [u.rstrip(".,;:!?") for u in URL_RE.findall(text)]
    ex.datetimes = _find_dates(text, ref)
    times = _find_times(text)
    ex.is_deadline = bool(DEADLINE_RE.search(text))
    ex.location = extract_location(text)
    ex.title = build_title(text)
    low = text.lower()
    ex.action_required = ex.is_deadline or any(re.search(rf"\b{v}\b", low) for v in ACTION_VERBS)

    if ex.datetimes:
        hit = ex.datetimes[-1] if prefer_last else ex.datetimes[0]
        dt = hit.value
        if times:
            # pair with the time closest after the date phrase, else the first time
            after = [t for t in times if t[0] >= hit.start]
            _, h, mi = (after or times)[0]
            dt = dt.replace(hour=h, minute=mi)
            ex.has_time = True
        elif ex.is_deadline:
            dt = dt.replace(hour=23, minute=59)
        else:
            dt = dt.replace(hour=9, minute=0)
        ex.primary = dt
        ex.needs_verification = hit.ambiguous
        if len({h.value.date() for h in ex.datetimes}) > 1 and not prefer_last:
            ex.needs_verification = True
    elif times and RELATIVE_RE.search(text) is None and re.search(r"\b(class|lecture|meet|meeting|today)\b", low):
        _, h, mi = times[0]
        ex.primary = datetime(ref.year, ref.month, ref.day, h, mi)
        ex.has_time = True
    return ex
