"""Stage A + B: noise filtering and classification (rule engine).

Rules first, LLM optional. Noise is never deleted - it is marked low
priority so it can still be inspected in the group view.
"""
from __future__ import annotations

import re
from typing import Optional, Tuple

CATEGORY_KEYWORDS = {
    "placements": ["internship", "intern", "placement", "ctc", "lpa", "stipend", "recruit", "hiring",
                   "drive", "interview", "resume", "cv", "offer", "aptitude", "tpo", "infosys", "tcs",
                   "wipro", "accenture", "amazon", "google", "microsoft", "deloitte", "capgemini",
                   "cognizant", "sde", "job", "company", "preplacement", "oa", "online assessment"],
    "hackathons": ["hackathon", "sih", "devfolio", "unstop", "problem statement", "prototype", "team",
                   "round", "pitch", "ppt", "mentor", "submission portal", "hack"],
    "academics": ["assignment", "exam", "quiz", "lab", "viva", "syllabus", "lecture", "class", "midsem",
                  "endsem", "internal", "attendance", "dbms", "os", "cn", "dsa", "toc", "marks",
                  "practical", "tutorial", "lms", "unit", "timetable", "semester", "project report"],
    "events": ["fest", "event", "workshop", "seminar", "webinar", "briefing", "cultural", "auditorium",
               "club", "volunteer", "competition", "talk", "orientation", "ceremony", "meetup"],
    "resources": ["notes", "pdf", "slides", "drive.google", "book", "youtube", "playlist", "resource",
                  "material", "pyq", "question bank", "reference", "cheatsheet"],
}

NOISE_RE = re.compile(
    r"^(ok+|okay|k+|kk|thanks?|thank you|thank u|ty|thx|tysm|lol+|lmao|haha+|hehe+|hmm+|yes|yeah|yep|no|nope|"
    r"done|same|\+1|noted|sure|cool|nice|great|wow|gm|good morning|good night|gn|welcome|np|"
    r"no idea|idk|ohh?|oh ok|ok sir|ok ma'?am|thank you sir|thank you ma'?am|yes sir|"
    r"congrats|congratulations|thanks for sharing|thank you so much|thanks a lot|really|seriously|on it|omg|same here|me too|true)[\s.!?🙏👍😂🤣😅🔥❤️💯😋😱]*$",
    re.I,
)
EMOJI_ONLY_RE = re.compile(r"^[\W_\s]+$")
QUESTION_START = re.compile(
    r"^(what|when|where|why|how|which|who|does|do|did|is|are|can|could|will|would|has|have|should|anyone|any one|any update)\b",
    re.I,
)
UPDATE_RE = re.compile(
    r"\b(moved|shifted|postponed|preponed|rescheduled|extended|changed|revised|cancel+ed|"
    r"new (?:venue|time|date|deadline)|is now|will now|instead of|updated (?:time|venue|date|deadline))\b",
    re.I,
)
RESOURCE_RE = re.compile(r"\b(notes|slides|pdf|material|playlist|pyq|resources?|question bank)\b", re.I)


def is_noise(text: str, message_type: str = "text") -> bool:
    t = text.strip()
    if message_type in ("system", "deleted"):
        return True
    if message_type == "media":
        return False  # attachments are kept: they may be posters/PDFs
    if NOISE_RE.match(t) or EMOJI_ONLY_RE.match(t):
        return True
    return len(t) <= 3


def classify_category(text: str, group_category: str = "general", is_official: bool = False) -> Tuple[str, float]:
    low = " " + text.lower() + " "
    low = re.sub(r"mid[\s\-]?sem", "midsem", low)
    scores = {}
    for cat, words in CATEGORY_KEYWORDS.items():
        s = 0
        for w in words:
            if re.search(rf"(?<![a-z]){re.escape(w)}(?![a-z])", low):
                s += 2 if " " in w or len(w) > 5 else 1
        scores[cat] = s
    best = max(scores, key=lambda k: scores[k])
    if scores[best] == 0:
        if is_official:
            return "faculty", 0.55
        return (group_category if group_category in CATEGORY_KEYWORDS else "general"), 0.4
    # group context breaks ties
    if group_category in scores and scores[group_category] == scores[best]:
        best = group_category
    total = sum(scores.values()) or 1
    return best, min(0.95, 0.5 + 0.5 * scores[best] / total)


def classify_type(text: str, *, noise: bool, has_date: bool, is_deadline: bool,
                  action: bool, has_link: bool, message_type: str = "text") -> str:
    t = text.strip()
    if noise:
        return "chatter"
    is_question = t.endswith("?") or "??" in t or bool(QUESTION_START.match(t))
    if UPDATE_RE.search(t) and (has_date or re.search(r"\b(venue|room|hall|lab|auditorium|cancel)", t, re.I)):
        return "update"
    if is_question and not (is_deadline and has_date and not t.endswith("?")):
        return "question"
    if is_deadline and has_date:
        return "deadline"
    if action and has_date:
        return "task"
    if RESOURCE_RE.search(t) and (has_link or message_type == "media"
                                  or re.search(r"\b(uploaded|shared|attached)\b", t, re.I)):
        return "resource"
    if has_link and len(t) < 60:
        return "resource"
    if action:
        return "task"
    if has_date or len(t) > 40:
        return "announcement"
    return "chatter" if len(t) < 20 else "announcement"


def summarize(title: str, when: Optional[str], location: Optional[str], mtype: str) -> str:
    parts = [title]
    if when:
        parts.append(("due " if mtype in ("deadline", "task") else "") + when)
    if location:
        parts.append(location)
    return " · ".join(parts)
