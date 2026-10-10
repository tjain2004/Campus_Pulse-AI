import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

NOW = datetime(2026, 10, 10, 15, 22)


@pytest.fixture()
def conn():
    from database.connection import get_connection
    c = get_connection(":memory:")
    yield c
    c.close()


@pytest.fixture()
def demo(conn, monkeypatch):
    """In-memory DB loaded with the four demo groups, pipeline run at NOW."""
    import config
    monkeypatch.setattr(config, "reference_now", lambda: NOW)
    from scripts.seed_demo import load_demo
    from agent.orchestrator import run_pipeline
    load_demo(conn)
    run_pipeline(conn, now=NOW, use_llm=False)
    return conn
