"""Tests for agentcost SQLite persistence layer."""
import sqlite3
import pytest
from datetime import datetime
from pathlib import Path

from agentcost.cost import TokenUsage, CostBreakdown
from agentcost.persistence import CostPersistence


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "test_costs.db"


@pytest.fixture
def persistence(db_path):
    return CostPersistence(db_path)


def test_init_creates_tables(db_path):
    persistence = CostPersistence(db_path)
    # Assert on the object, not just the path: the constructor is what creates
    # the database, so it must also remember where it put it.
    assert persistence.db_path == db_path
    assert db_path.exists()

    conn = sqlite3.connect(str(db_path))
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    conn.close()
    assert ("token_usage",) in tables


def test_record_single(persistence, db_path):
    usage = TokenUsage(
        model="meituan/longcat-2.0:free",
        input_tokens=1000,
        output_tokens=500,
        session_id="test-session",
        timestamp=datetime(2026, 9, 15, 12, 0, 0),
        agent_id="test-agent",
    )
    persistence.record(usage, estimated_cost=0.01, actual_cost=0.02)

    summary = persistence.get_cost_summary()
    assert summary["total_records"] == 1
    assert summary["total_input_tokens"] == 1000
    assert summary["total_output_tokens"] == 500
    assert summary["total_estimated_cost"] == 0.01
    assert summary["total_actual_cost"] == 0.02


def test_record_many(persistence):
    usages = [
        (TokenUsage(model="m1", input_tokens=100, output_tokens=50, session_id="s1"), 0.001, 0.002),
        (TokenUsage(model="m2", input_tokens=200, output_tokens=90, session_id="s2"), 0.003, 0.004),
    ]
    persistence.record_many(usages)
    summary = persistence.get_cost_summary()
    assert summary["total_records"] == 2
    assert summary["total_estimated_cost"] == 0.004


def test_get_model_breakdown(persistence):
    usages = [
        (TokenUsage(model="m1", input_tokens=100, output_tokens=50), 0.001, 0.002),
        (TokenUsage(model="m1", input_tokens=200, output_tokens=90), 0.003, 0.004),
        (TokenUsage(model="m2", input_tokens=300, output_tokens=130), 0.005, 0.006),
    ]
    persistence.record_many(usages)
    breakdown = persistence.get_model_breakdown()
    assert len(breakdown) == 2
    assert breakdown[0]["model"] in ("m1", "m2")
    assert breakdown[0]["records"] >= 1


def test_get_session_breakdown(persistence):
    usages = [
        (TokenUsage(model="m1", input_tokens=100, output_tokens=50, session_id="s1"), 0.001, 0.002),
        (TokenUsage(model="m1", input_tokens=200, output_tokens=90, session_id="s2"), 0.003, 0.004),
    ]
    persistence.record_many(usages)
    sessions = persistence.get_session_breakdown()
    assert len(sessions) == 2


def test_get_daily_summary(persistence):
    usage = TokenUsage(
        model="m1",
        input_tokens=100,
        output_tokens=50,
        timestamp=datetime(2026, 9, 15, 12, 0, 0),
    )
    persistence.record(usage, estimated_cost=0.001, actual_cost=0.002)
    daily = persistence.get_daily_summary()
    assert len(daily) >= 1
    assert daily[0]["day"] == "2026-09-15"


def test_empty_db_summary(db_path):
    persistence = CostPersistence(db_path)
    empty = persistence.get_cost_summary()
    persistence.record(TokenUsage(model="m1", input_tokens=100, output_tokens=50))
    populated = persistence.get_cost_summary()

    assert set(empty) == set(populated)
    assert all(value == 0 for value in empty.values())


def test_filter_by_session(persistence):
    usages = [
        (TokenUsage(model="m1", input_tokens=100, output_tokens=50, session_id="s1"), 0.001, 0.002),
        (TokenUsage(model="m1", input_tokens=200, output_tokens=90, session_id="s2"), 0.003, 0.004),
    ]
    persistence.record_many(usages)
    s1 = persistence.get_cost_summary(session_id="s1")
    assert s1["total_records"] == 1
    assert s1["total_input_tokens"] == 100


@pytest.fixture
def opened_connections(monkeypatch):
    """Every connection the persistence layer opens from here on."""
    opened = []
    real_connect = sqlite3.connect

    def tracking_connect(*args, **kwargs):
        conn = real_connect(*args, **kwargs)
        opened.append(conn)
        return conn

    monkeypatch.setattr(sqlite3, "connect", tracking_connect)
    return opened


def _is_closed(conn):
    try:
        conn.execute("SELECT 1")
    except sqlite3.ProgrammingError:
        return True
    return False


def test_a_failed_write_still_closes_its_connection(persistence, opened_connections):
    # model is NOT NULL, so this insert raises after the connection is open (#213).
    bad = TokenUsage(model=None, input_tokens=1, output_tokens=1, session_id="s")
    with pytest.raises(sqlite3.IntegrityError):
        persistence.record(bad)
    assert len(opened_connections) == 1
    assert _is_closed(opened_connections[0])


def test_a_failed_batch_closes_its_connection_and_stores_nothing(persistence, opened_connections):
    good = TokenUsage(model="m", input_tokens=1, output_tokens=1, session_id="s")
    bad = TokenUsage(model=None, input_tokens=1, output_tokens=1, session_id="s")
    with pytest.raises(sqlite3.IntegrityError):
        persistence.record_many([(good, 0.1, 0.0), (bad, 0.1, 0.0)])
    assert _is_closed(opened_connections[0])
    assert persistence.get_cost_summary()["total_records"] == 0


def test_every_read_closes_its_connection(persistence, opened_connections):
    persistence.record(TokenUsage(model="m", input_tokens=1, output_tokens=1, session_id="s"))
    persistence.existing_keys()
    persistence.get_cost_summary()
    persistence.get_model_breakdown()
    persistence.get_session_breakdown()
    persistence.get_daily_summary()
    assert len(opened_connections) == 6
    assert all(_is_closed(conn) for conn in opened_connections)
