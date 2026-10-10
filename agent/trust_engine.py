"""RUMOR SHIELD - the trust layer for campus WhatsApp groups (innovation).

Every claim floating around the groups gets a verdict with evidence:

    VERIFIED      from an official sender, or confirmed by one in any group
    UNVERIFIED    hearsay / forwarded / student claim with no official backing
    CONTRADICTED  an official message in some group says otherwise

Signals: sender authority, hedge language ("I heard", "apparently", "fwd"),
cross-group corroboration, and explicit official denials ("as scheduled",
"ignore rumours"). It also powers the Cross-Group Doubt Solver: questions
nobody answered in one group are answered with official info from another.
"""
from __future__ import annotations

import json
import re
from typing import Dict, List, Optional

from agent.textutils import has_hedge, hedge_hits, jaccard

OFFICIAL_RE = re.compile(
    r"\b(prof|professor|dr|hod|dean|faculty|coordinator|co-ordinator|tpo|placement cell|t&p|admin|"
    r"office|registrar|mentor|sir|ma'?am|principal|director|warden|exam cell|department|dept)\b\.?",
    re.I,
)
SEMI_OFFICIAL_RE = re.compile(r"\b(cr|class rep|class representative|gr|lead|captain|secretary|president)\b", re.I)
DENIAL_RE = re.compile(
    r"\b(no change|not postponed|not cancel+ed|as scheduled|as per schedule|fake|ignore (?:the )?rumou?rs?|"
    r"rumou?rs? (?:are|is) false|false news|no truth|not true|will be held as|stays the same|remains unchanged)\b",
    re.I,
)
CLAIM_RE = re.compile(r"\b(postponed|cancel+ed|preponed|moved|shifted|extended|holiday|off|declared|changed)\b", re.I)


def sender_authority(sender: Optional[str], official_senders: Optional[List[str]] = None) -> str:
    """'official' | 'semi' | 'member'"""
    if not sender:
        return "member"
    s = sender.lower()
    for name in official_senders or []:
        if name and name.lower() in s:
            return "official"
    if OFFICIAL_RE.search(sender):
        return "official"
    if SEMI_OFFICIAL_RE.search(sender):
        return "semi"
    return "member"


def initial_trust(text: str, authority: str) -> Dict:
    score = {"official": 88, "semi": 68, "member": 50}[authority]
    reasons = [{"official": "Posted by an official sender",
                "semi": "Posted by a class representative / lead",
                "member": "Posted by a group member"}[authority]]
    hedges = hedge_hits(text)
    if DENIAL_RE.search(text):  # "please ignore rumours" is a denial, not hearsay
        hedges = [h for h in hedges if h not in ("rumour", "rumor")]
    if hedges:
        score -= min(45, 25 + 10 * (len(hedges) - 1))
        reasons.append(f"Hearsay language: “{hedges[0]}”")
    if re.search(r"\bforwarded\b|\bfwd\b", text, re.I):
        score -= 8
        reasons.append("Forwarded message")
    score = max(5, min(98, score))
    if authority == "official" and not hedges:
        label = "verified"
    elif hedges or score < 55:
        label = "unverified"
    else:
        label = "unconfirmed"
    return {"label": label, "score": score, "reasons": reasons, "is_rumor": bool(hedges)}


def _related(a: Dict, b: Dict, loose: bool = True) -> bool:
    shared_strong = a["strong"] & b["strong"]
    jac = jaccard(a["topic"], b["topic"])
    if len(shared_strong) >= 2:
        return True
    return bool(shared_strong) and jac >= (0.15 if loose else 0.3)


def cross_check(items: List[Dict]) -> None:
    """Upgrade/downgrade trust using other groups. Mutates items in place.

    Each item: id, text, authority, trust{}, topic, strong, primary (datetime|None),
    group, timestamp, cluster_id, type.
    """
    officials = [i for i in items if i["authority"] == "official" and not i["trust"]["is_rumor"]]
    for item in items:
        if item["authority"] == "official" and not item["trust"]["is_rumor"]:
            continue
        evidence = None
        verdict = None
        for off in officials:
            if off["id"] == item["id"] or not _related(item, off):
                continue
            denies = bool(DENIAL_RE.search(off["text"]))
            claims_change = bool(CLAIM_RE.search(item["text"]))
            if denies and (claims_change or item["trust"]["is_rumor"]):
                verdict, evidence = "contradicted", off
                break
            if item["primary"] and off["primary"] and item["primary"].date() != off["primary"].date() \
                    and item["trust"]["is_rumor"]:
                verdict, evidence = "contradicted", off
                break
            same_cluster = item.get("cluster_id") and item.get("cluster_id") == off.get("cluster_id")
            same_date = item["primary"] and off["primary"] and item["primary"].date() == off["primary"].date()
            if same_cluster or same_date:
                verdict, evidence = "verified", off
        if verdict == "contradicted":
            item["trust"].update(label="contradicted", score=min(item["trust"]["score"], 12))
            item["trust"]["reasons"].append(
                f"Contradicted by {evidence['sender']} in {evidence['group']}")
            item["trust"]["evidence_id"] = evidence["id"]
        elif verdict == "verified":
            item["trust"].update(label="verified", score=max(item["trust"]["score"], 82))
            item["trust"]["reasons"].append(
                f"Confirmed by {evidence['sender']} in {evidence['group']}")
            item["trust"]["evidence_id"] = evidence["id"]
        elif item["trust"]["is_rumor"]:
            item["trust"]["reasons"].append("No official source in any group confirms this")


def find_unanswered_questions(rows: List[Dict], window: int = 6) -> List[Dict]:
    """Questions with no reply from someone else (sharing a topic word) shortly after.

    rows: per-group ordered list of dicts with id, sender, type, topic, is_noise, has_link.
    """
    unanswered = []
    for idx, row in enumerate(rows):
        if row["type"] != "question" or row["trust"]["is_rumor"]:
            continue
        answered = False
        for nxt in rows[idx + 1: idx + 1 + window]:
            if nxt["sender"] == row["sender"] or nxt["is_noise"] or nxt["type"] == "question":
                continue
            if row["topic"] & nxt["topic"] or nxt["has_link"]:
                answered = True
                break
        if not answered:
            unanswered.append(row)
    return unanswered


def reasons_json(trust: Dict) -> str:
    return json.dumps(trust.get("reasons", []))
