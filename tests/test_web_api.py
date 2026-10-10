"""Flask API: auth, CSRF, per-user isolation, core endpoints."""
import pytest

H = {"X-Requested-With": "CampusPulse"}


@pytest.fixture()
def client(monkeypatch, tmp_path):
    import config
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    from backend import userspace
    userspace._conns.clear()
    import app as A
    A.app.config["TESTING"] = True
    return A.app


def _register(app, email="a@college.edu", name="Asha Rao"):
    c = app.test_client()
    r = c.post("/api/auth/register", json={"name": name, "email": email, "password": "campus2026"}, headers=H)
    assert r.status_code == 201
    return c


def test_auth_rules(client):
    c = client.test_client()
    assert c.get("/api/dashboard").status_code == 401
    assert c.post("/api/auth/register", json={}).status_code == 403          # CSRF header required
    r = c.post("/api/auth/register", json={"name": "A", "email": "x@y.com", "password": "short"}, headers=H)
    assert r.status_code == 400
    _register(client)
    r = c.post("/api/auth/register", json={"name": "Asha", "email": "A@college.edu", "password": "campus2026"}, headers=H)
    assert "already exists" in r.get_json()["error"]
    assert c.post("/api/auth/login", json={"email": "a@college.edu", "password": "nope12345"}, headers=H).status_code == 401
    assert c.post("/api/auth/login", json={"email": "a@college.edu", "password": "campus2026"}, headers=H).status_code == 200
    assert c.get("/api/auth/me").get_json()["user"]["name"] == "Asha Rao"


def test_password_is_hashed(client):
    _register(client)
    import sqlite3
    import config
    row = sqlite3.connect(str(config.DATA_DIR / "auth.db")).execute("SELECT password_hash FROM accounts").fetchone()
    assert "campus2026" not in row[0] and row[0].startswith(("scrypt", "pbkdf2"))


def test_demo_and_endpoints(client):
    c = _register(client)
    stats = c.post("/api/import/demo", headers=H).get_json()["stats"]
    assert stats["changes"] == 3 and stats["conflicts"] == 1
    d = c.get("/api/dashboard").get_json()
    assert d["top"][0]["title"].startswith("SIH")
    for ep in ("/api/changes", "/api/rumors", "/api/deadlines", "/api/tasks", "/api/groups", "/api/resources",
               "/api/profile", "/api/whatsapp/status", "/api/calendar.ics"):
        assert c.get(ep).status_code == 200, ep
    a = c.post("/api/ask", json={"question": "Where is the fest briefing?"}, headers=H).get_json()
    assert "Main Auditorium" in a["answer"]


def test_users_cannot_see_each_other(client):
    a = _register(client, "a@college.edu")
    a.post("/api/import/demo", headers=H)
    b = _register(client, "b@college.edu", "Bilal Khan")
    assert b.get("/api/groups").get_json() == []
    assert b.get("/api/tasks").get_json() == []
    assert len(a.get("/api/groups").get_json()) == 4


def test_whatsapp_groups_only_known_ids(client):
    import json
    from backend import userspace
    c = _register(client)
    uid = c.get("/api/auth/me").get_json()["user"]["id"]
    live = userspace.live_dir(uid)
    live.mkdir(parents=True, exist_ok=True)
    (live / "groups.json").write_text(json.dumps([{"id": "1@g.us", "name": "CSE", "participants": 3}]))
    c.put("/api/whatsapp/groups", json={"group_ids": ["1@g.us", "evil@g.us"]}, headers=H)
    assert json.loads((live / "selected_groups.json").read_text()) == ["1@g.us"]
