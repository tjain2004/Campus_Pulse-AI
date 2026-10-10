import json


def _event(conn, title_part):
    return next(e for e in conn.execute("SELECT * FROM events") if title_part.lower() in e["title"].lower())


def test_venue_and_time_change_detected(demo):
    ev = _event(demo, "Fest briefing")
    assert ev["status"] == "changed"
    assert ev["original_location"] == "Room 204" and ev["current_location"] == "Main Auditorium"
    assert ev["current_at"].startswith("2026-10-14T17:00")


def test_deadline_extension_updates_task(demo):
    ev = _event(demo, "Infosys")
    assert ev["original_at"].startswith("2026-10-12") and ev["current_at"].startswith("2026-10-15")
    task = next(t for t in demo.execute("SELECT * FROM tasks") if "Infosys" in t["title"])
    assert task["deadline"].startswith("2026-10-15")


def test_conflict_not_auto_resolved(demo):
    ev = _event(demo, "DBMS Assignment")
    assert ev["status"] == "conflict"
    assert ev["current_at"].startswith("2026-10-15")       # newer message did NOT silently win
    log = demo.execute("SELECT * FROM change_logs WHERE kind='conflict'").fetchone()
    assert "Fri 16 Oct" in json.loads(log["new_values"])["when"]


def test_duplicate_across_groups_is_one_cluster(demo):
    rows = demo.execute(
        "SELECT a.cluster_id, g.name FROM message_analyses a JOIN messages m ON m.id=a.message_id "
        "JOIN groups g ON g.id=m.group_id WHERE m.text LIKE '%Infosys Summer Internship%'").fetchall()
    assert len(rows) == 2 and len({r["cluster_id"] for r in rows}) == 1
    assert {r["name"] for r in rows} == {"CSE Final Year", "Placement Updates"}


def test_rumor_contradicted_by_official(demo):
    row = demo.execute("SELECT a.* FROM message_analyses a JOIN messages m ON m.id=a.message_id "
                       "WHERE m.text LIKE '%I heard OS mid-sem%'").fetchone()
    assert row["trust_label"] == "contradicted"
    assert "Prof. Sharma" in row["trust_reasons"]


def test_hearsay_never_changes_events(demo):
    ev = _event(demo, "OS mid-sem")
    assert ev["status"] == "active" and ev["current_at"].startswith("2026-10-14T10:00")


def test_not_for_me_is_labelled_not_hidden(demo):
    from agent.planner import build_brief
    from tests.conftest import NOW
    b = build_brief(demo, NOW)
    assert any("Amazon" in i["title"] for i in b["not_for_you"])
    assert not any("Amazon" in i["title"] for i in b["top"])


def test_pipeline_is_idempotent_and_keeps_task_status(demo):
    from agent.orchestrator import run_pipeline
    from database import repository as repo
    from tests.conftest import NOW
    t = repo.list_tasks(demo)[0]
    repo.set_task_status(demo, t["id"], "done")
    run_pipeline(demo, now=NOW, use_llm=False)
    assert demo.execute("SELECT status FROM tasks WHERE id=?", (t["id"],)).fetchone()[0] == "done"
    assert demo.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 11
