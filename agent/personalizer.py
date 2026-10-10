"""'Is this for me?' engine.

Three distinct outcomes, never collapsed:
    relevant      matches the student's profile
    not_relevant  clearly conflicts with an explicit requirement
    unknown       not enough information
Nothing is hidden silently - not_relevant items stay inspectable with a reason.
"""
from __future__ import annotations

import re
from typing import Dict, Tuple

YEAR_WORDS = {"1st": 1, "first": 1, "2nd": 2, "second": 2, "3rd": 3, "third": 3,
              "4th": 4, "fourth": 4, "final": 4, "pre-final": 3, "prefinal": 3}
_Y = r"(1st|2nd|3rd|4th|first|second|third|fourth|final|pre-?final)"
YEAR_RE = re.compile(rf"\b{_Y}(?:\s*(?:,|/|&|and|or)\s*{_Y})?(?:\s*(?:,|/|&|and|or)\s*{_Y})?[\s\-]*years?\b", re.I)
BATCH_RE = re.compile(r"\b(?:(20\d{2})\s*(?:batch|graduates|grads|pass[\s\-]?outs?|passing out)|"
                      r"(?:batch|class) of\s*(20\d{2}))\b", re.I)
BRANCHES = ["CSE", "IT", "ECE", "EEE", "EE", "ME", "MECH", "CIVIL", "CE", "AIML", "AI&DS", "AIDS", "DS", "CSBS", "BIOTECH", "CHEM"]
BRANCH_RE = re.compile(r"(?<![A-Za-z&])(" + "|".join(re.escape(b) for b in BRANCHES) + r")(?![A-Za-z&])")
OPEN_ALL_RE = re.compile(r"\b(open (?:to|for) all|all (?:years|branches|students)|everyone can)\b", re.I)
TEAM_RE = re.compile(r"\bTeam\s+([A-Z][\w-]+)")


def _profile_branches(branch: str) -> set:
    tokens = {t.upper() for t in re.findall(r"[A-Za-z&]+", branch or "")}
    if "DATA" in tokens and "SCIENCE" in tokens:
        tokens |= {"DS", "AIDS", "AI&DS"}
    if "COMPUTER" in tokens:
        tokens.add("CSE")
    return tokens


def assess(text: str, category: str, profile: Dict) -> Tuple[str, str]:
    year = profile.get("year")
    grad = profile.get("grad_year")
    reasons_pos = []

    if OPEN_ALL_RE.search(text):
        return "relevant", "Open to all students"

    years = []
    for m in YEAR_RE.finditer(text):
        years += [YEAR_WORDS[g.lower().replace("-", "")] for g in m.groups() if g]
    if years and year:
        if int(year) not in years:
            yrs = ", ".join(f"{y}{'st' if y == 1 else 'nd' if y == 2 else 'rd' if y == 3 else 'th'}" for y in sorted(set(years)))
            return "not_relevant", f"Meant for {yrs} year; you are in year {year}"
        reasons_pos.append(f"for year {year}")

    batches = [int(a or b) for a, b in BATCH_RE.findall(text)]
    if batches and grad:
        if int(grad) not in batches:
            return "not_relevant", f"For the {', '.join(map(str, sorted(set(batches))))} batch; you graduate in {grad}"
        reasons_pos.append(f"{grad} batch")

    eligibility_context = re.search(r"\b(only|eligib|open to|for)\b", text, re.I)
    branches = {b.upper() for b in BRANCH_RE.findall(text)}
    mine = _profile_branches(profile.get("branch", ""))
    if branches and eligibility_context and mine:
        if not branches & mine:
            return "not_relevant", f"Restricted to {', '.join(sorted(branches))}"
        reasons_pos.append("your branch")

    teams = TEAM_RE.findall(text)
    my_teams = {t.lower().replace("team ", "").strip() for t in profile.get("teams", [])}
    if teams and my_teams and any(t.lower() in my_teams for t in teams):
        reasons_pos.append(f"your team ({teams[0]})")

    interests = [i.lower() for i in profile.get("interests", [])]
    skills = [s.lower() for s in profile.get("skills", [])]
    low = text.lower()
    if category in interests:
        reasons_pos.append(f"your interest in {category}")
    else:
        for kw in interests + skills:
            if len(kw) > 1 and re.search(rf"(?<![a-z]){re.escape(kw)}(?![a-z])", low):
                reasons_pos.append(f"mentions {kw}")
                break

    if reasons_pos:
        return "relevant", "Matches " + ", ".join(reasons_pos)
    return "unknown", "No eligibility conditions stated"
