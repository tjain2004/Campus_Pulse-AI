"""Agent orchestrator: runs every stage of the pipeline in order.

    raw messages
      -> noise filter -> classify -> extract          (per message, rules + optional LLM)
      -> Rumor Shield: sender authority + hedges      (per message)
      -> deduplicate across groups                    (clusters)
      -> Rumor Shield cross-check                     (verified / unverified / contradicted)
      -> What Changed? engine                         (events, diffs, conflicts)
      -> Is this for me?                              (relevance)
      -> priority + tasks                             (Today's Brief, My Tasks)

Derived data is rebuilt from the raw messages each run, so the pipeline is
idempotent and the original messages remain the single source of truth.
Task done/pending status is preserved across runs.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import config
from agent import classifier, extractor, llm, personalizer, planner, trust_engine
from agent.change_detector import detect_changes, fmt_dt
from agent.deduplicator import assign_clusters
from agent.textutils import topic_signature
from database import repository as repo


@dataclass
class RunStats:
    messages: int = 0
    meaningful: int = 0
    noise: int = 0
    events: int = 0
    changes: int = 0
    conflicts: int = 0
    rumors: int = 0
    contradicted: int = 0
    tasks: int = 0
    llm_used: int = 0


def _to_dt(v) -> Optional[datetime]:
    if v is None or isinstance(v, datetime):
        return v
    try:
        return datetime.fromisoformat(str(v))
    except ValueError:
        return None


def analyze_row(conn: sqlite3.Connection, row: sqlite3.Row, use_llm: bool) -> Dict:
    text = row["text"]
    ts = _to_dt(row["timestamp"])
    official_list = json.loads(row["official_senders"] or "[]")
    authority = trust_engine.sender_authority(row["sender"], official_list)
    noise = classifier.is_noise(text, row["message_type"])
    prefer_last = bool(classifier.UPDATE_RE.search(text))
    ex = extractor.extract(text, ts, prefer_last=prefer_last)
    category, conf = classifier.classify_category(text, row["group_category"], authority == "official")
    mtype = classifier.classify_type(
        text, noise=noise, has_date=ex.primary is not None, is_deadline=ex.is_deadline,
        action=ex.action_required, has_link=bool(ex.links), message_type=row["message_type"],
    )
    topic, strong = topic_signature(text)
    item = {
        "id": row["id"], "text": text, "group": row["group_name"], "group_id": row["group_id"],
        "sender": row["sender"], "timestamp": ts, "authority": authority, "is_noise": noise,
        "category": category, "type": mtype, "confidence": round(conf if not noise else 0.9, 2),
        "primary": ex.primary, "has_time": ex.has_time, "location": ex.location, "links": ex.links,
        "title": ex.title, "action_required": ex.action_required and not noise,
        "needs_verification": ex.needs_verification, "topic": topic, "strong": strong,
        "has_link": bool(ex.links) or row["message_type"] == "media", "engine": "rules",
    }
    if mtype == "deadline" and ex.primary:
        item["confidence"] = round(min(0.95, item["confidence"] + (0.15 if ex.has_time else 0.05)), 2)

    if use_llm and not noise:
        data = llm.analyze_message(conn, text, row["group_name"], row["sender"], ts)
        if data:
            item.update(
                category=data["category"], type=data["message_type"], confidence=data["confidence"],
                needs_verification=data["needs_verification"] or item["needs_verification"],
                action_required=data["action_required"], engine="llm",
            )
            when = data.get("deadline") or data.get("event_at")
            if when:
                item["primary"] = _to_dt(when) if not isinstance(when, datetime) else when
            if data.get("location"):
                item["location"] = data["location"]
            if data.get("event_name"):
                item["title"] = data["event_name"]
    item["trust"] = trust_engine.initial_trust(text, authority) if not noise else {
        "label": None, "score": None, "reasons": [], "is_rumor": False}
    return item


def run_pipeline(conn: sqlite3.Connection, profile: Optional[Dict] = None,
                 now: Optional[datetime] = None, use_llm: Optional[bool] = None) -> RunStats:
    now = now or config.reference_now()
    profile = profile or repo.get_profile(conn)
    use_llm = llm.available() if use_llm is None else use_llm
    stats = RunStats()

    rows = repo.all_messages(conn)
    stats.messages = len(rows)
    repo.clear_derived(conn)

    items = [analyze_row(conn, r, use_llm) for r in rows]
    stats.llm_used = sum(1 for i in items if i["engine"] == "llm")

    assign_clusters(items)
    trust_engine.cross_check([i for i in items if not i["is_noise"]])

    links = detect_changes(conn, items)
    events = {e["id"]: e for e in repo.list_events(conn)}

    keep_tasks: List[int] = []
    events_with_task: set = set()
    for item in items:
        if item["is_noise"]:
            item.update(relevance="unknown", relevance_reason=None)
        else:
            item["relevance"], item["relevance_reason"] = personalizer.assess(item["text"], item["category"], profile)
        ev = events.get(links.get(item["id"])) if links.get(item["id"]) else None
        item["event_current_at"] = _to_dt(ev["current_at"]) if ev else None
        item.update(planner.score(item, now))

        when = item["event_current_at"] or item["primary"]
        is_deadline = item["type"] in ("deadline", "task") or (ev is not None and ev["kind"] == "deadline")
        summary = classifier.summarize(item["title"], fmt_dt(when) if when else None, item["location"],
                                       "deadline" if is_deadline else item["type"])
        repo.save_analysis(conn, item["id"], {
            "category": item["category"], "type": item["type"], "summary": summary,
            "action_required": item["action_required"],
            "deadline": item["primary"] if is_deadline else None,
            "event_at": item["primary"] if not is_deadline else None,
            "location": item["location"], "topic": item["title"], "is_noise": item["is_noise"],
            "confidence": item["confidence"], "needs_verification": item["needs_verification"],
            "cluster_id": item["cluster_id"], "relevance": item["relevance"],
            "relevance_reason": item["relevance_reason"],
            "trust_label": item["trust"]["label"], "trust_score": item["trust"]["score"],
            "trust_reasons": item["trust"]["reasons"], "priority": item["priority"],
            "priority_reason": item["priority_reason"], "engine": item["engine"],
        })

        # Tasks: one per cluster, never from rumors, never for clearly-not-for-me items.
        wants_task = (item["action_required"] and item["type"] in ("deadline", "task")
                      and item["cluster_id"] == item["id"] and not item["trust"]["is_rumor"]
                      and item["trust"]["label"] != "contradicted"
                      and item["relevance"] != "not_relevant" and when is not None
                      and when >= now - timedelta(days=1)
                      and not (ev is not None and ev["id"] in events_with_task))
        if wants_task:
            if ev is not None:
                events_with_task.add(ev["id"])
            title = extractor.task_title(item["text"], item["title"])
            repo.upsert_task(conn, item["id"], title, when, ev["id"] if ev else None)
            keep_tasks.append(item["id"])
    repo.prune_tasks(conn, keep_tasks)
    conn.commit()

    stats.noise = sum(1 for i in items if i["is_noise"])
    stats.meaningful = stats.messages - stats.noise
    stats.events = len(events)
    changes = repo.list_changes(conn)
    stats.changes = sum(1 for c in changes if c["kind"] == "change")
    stats.conflicts = sum(1 for c in changes if c["kind"] == "conflict")
    stats.rumors = sum(1 for i in items if i["trust"].get("is_rumor"))
    stats.contradicted = sum(1 for i in items if i["trust"].get("label") == "contradicted")
    stats.tasks = len(keep_tasks)
    return stats


def unanswered_questions(conn: sqlite3.Connection) -> List[Dict]:
    """Cross-group doubt solver input: questions nobody answered in their own group."""
    rows = conn.execute(
        """SELECT m.id, m.group_id, m.sender, m.text, m.timestamp, m.message_type, m.links_json,
                  g.name AS group_name, a.type, a.is_noise, a.trust_reasons
           FROM messages m JOIN groups g ON g.id = m.group_id
           JOIN message_analyses a ON a.message_id = m.id
           ORDER BY m.group_id, m.timestamp, m.id"""
    ).fetchall()
    by_group: Dict[int, List[Dict]] = {}
    for r in rows:
        topic, _ = topic_signature(r["text"])
        by_group.setdefault(r["group_id"], []).append({
            "id": r["id"], "sender": r["sender"], "type": r["type"], "topic": topic,
            "is_noise": bool(r["is_noise"]), "text": r["text"], "group": r["group_name"],
            "timestamp": r["timestamp"],
            "has_link": bool(json.loads(r["links_json"] or "[]")) or r["message_type"] == "media",
            "trust": {"is_rumor": "Hearsay" in (r["trust_reasons"] or "")},
        })
    out: List[Dict] = []
    for group_rows in by_group.values():
        out += trust_engine.find_unanswered_questions(group_rows)
    return out
