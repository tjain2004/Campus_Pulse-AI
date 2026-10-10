"""Stage D: duplicate detection across groups.

The same internship forwarded to three groups becomes ONE card with three
source references. All original messages are preserved.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Dict, List

from agent.textutils import jaccard

_FWD = re.compile(r"^(forwarded|fwd)[:\s-]*", re.I)


def _norm(text: str) -> str:
    t = _FWD.sub("", text.strip().lower())
    t = re.sub(r"[^\w\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def is_duplicate(a: Dict, b: Dict) -> bool:
    if a["links"] and set(a["links"]) & set(b["links"]) and (
            a["strong"] & b["strong"] or jaccard(a["topic"], b["topic"]) >= 0.2):
        return True
    na, nb = _norm(a["text"]), _norm(b["text"])
    if na and nb and SequenceMatcher(None, na, nb).ratio() >= 0.85:
        return True
    same_when = a["primary"] and b["primary"] and a["primary"] == b["primary"]
    if same_when and len(a["strong"] & b["strong"]) >= 2 and jaccard(a["topic"], b["topic"]) >= 0.5:
        return True
    return False


def assign_clusters(items: List[Dict]) -> None:
    """Sets item['cluster_id'] to the id of the earliest equivalent message."""
    eligible = [i for i in items if not i["is_noise"] and i["type"] not in ("chatter", "question")]
    heads: List[Dict] = []
    for item in eligible:
        for head in heads:
            if is_duplicate(item, head):
                item["cluster_id"] = head["id"]
                break
        else:
            item["cluster_id"] = item["id"]
            heads.append(item)
    for item in items:
        item.setdefault("cluster_id", item["id"])
