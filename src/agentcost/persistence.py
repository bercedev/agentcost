"""SQLite persistence layer for historical cost tracking."""
from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from agentcost.cost import TokenUsage


class CostPersistence:
    """Persist token usage and cost data to SQLite for historical tracking."""

    def __init__(self, db_path: Path = None):
        if db_path is None:
            db_path = Path.home() / ".agentcost" / "costs.db"
        self.db_path = db_path
        self._init_db()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """A connection that is closed however the block ends.

        ``with conn:`` alone commits or rolls back but leaves the connection
        open, so an exception between connect and close used to leak it.
        """
        conn = sqlite3.connect(str(self.db_path))
        try:
            with conn:  # commit on success, roll back on an exception
                yield conn
        finally:
            conn.close()

    def _init_db(self):
        """Create tables if they don't exist."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS token_usage (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    model TEXT NOT NULL,
                    input_tokens INTEGER DEFAULT 0,
                    output_tokens INTEGER DEFAULT 0,
                    cache_read_tokens INTEGER DEFAULT 0,
                    cache_write_tokens INTEGER DEFAULT 0,
                    estimated_cost_usd REAL DEFAULT 0.0,
                    actual_cost_usd REAL DEFAULT 0.0,
                    agent_id TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_token_usage_session 
                ON token_usage(session_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_token_usage_model 
                ON token_usage(model)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_token_usage_timestamp 
                ON token_usage(timestamp)
            """)

    def record(self, usage: TokenUsage, estimated_cost: float = 0.0, actual_cost: float = 0.0):
        """Record a single token usage entry."""
        with self._connect() as conn:
            conn.execute("""
                INSERT INTO token_usage 
                (session_id, model, input_tokens, output_tokens, 
                 cache_read_tokens, cache_write_tokens, 
                 estimated_cost_usd, actual_cost_usd, agent_id, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                usage.session_id or "",
                usage.model,
                usage.input_tokens,
                usage.output_tokens,
                usage.cache_read_tokens,
                usage.cache_write_tokens,
                estimated_cost,
                actual_cost,
                usage.agent_id,
                usage.timestamp.isoformat() if usage.timestamp else datetime.now(timezone.utc).isoformat(),
            ))

    def record_many(self, usages: list[tuple[TokenUsage, float, float]]):
        """Record multiple usage entries in a batch."""
        with self._connect() as conn:
            for usage, estimated, actual in usages:
                conn.execute("""
                    INSERT INTO token_usage 
                    (session_id, model, input_tokens, output_tokens, 
                     cache_read_tokens, cache_write_tokens, 
                     estimated_cost_usd, actual_cost_usd, agent_id, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    usage.session_id or "",
                    usage.model,
                    usage.input_tokens,
                    usage.output_tokens,
                    usage.cache_read_tokens,
                    usage.cache_write_tokens,
                    estimated,
                    actual,
                    usage.agent_id,
                    usage.timestamp.isoformat() if usage.timestamp else datetime.now(timezone.utc).isoformat(),
                ))

    def existing_keys(self) -> set:
        """Return the ``(session_id, model, timestamp)`` keys already stored.

        Used by the ``export`` command to skip entries that are already
        persisted so a re-run is idempotent. The timestamp is compared in the
        same ISO-8601 form :meth:`record` stores it, so two usages only
        collide when all three fields match exactly.
        """
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT session_id, model, timestamp FROM token_usage"
            ).fetchall()
        return {(session_id, model, timestamp) for session_id, model, timestamp in rows}

    @staticmethod
    def _key_for(usage: TokenUsage) -> tuple:
        """Build the dedup key for a usage, matching :meth:`record` storage."""
        ts = usage.timestamp.isoformat() if usage.timestamp else ""
        return (usage.session_id or "", usage.model, ts)

    def get_cost_summary(self, session_id: Optional[str] = None,
                        model: Optional[str] = None,
                        start_date: Optional[datetime] = None,
                        end_date: Optional[datetime] = None) -> dict:
        """Get aggregated cost summary with optional filters."""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row

            query = """
                SELECT 
                    COUNT(*) as total_records,
                    SUM(input_tokens) as total_input,
                    SUM(output_tokens) as total_output,
                    SUM(cache_read_tokens) as total_cache_read,
                    SUM(cache_write_tokens) as total_cache_write,
                    SUM(estimated_cost_usd) as total_estimated_cost,
                    SUM(actual_cost_usd) as total_actual_cost,
                    COUNT(DISTINCT model) as model_count,
                    COUNT(DISTINCT session_id) as session_count
                FROM token_usage
                WHERE 1=1
            """
            params = []

            if session_id:
                query += " AND session_id = ?"
                params.append(session_id)
            if model:
                query += " AND model = ?"
                params.append(model)
            if start_date:
                query += " AND timestamp >= ?"
                params.append(start_date.isoformat())
            if end_date:
                query += " AND timestamp <= ?"
                params.append(end_date.isoformat())

            row = conn.execute(query, params).fetchone()

        return {
            "total_records": row["total_records"] or 0,
            "total_input_tokens": row["total_input"] or 0,
            "total_output_tokens": row["total_output"] or 0,
            "total_cache_read": row["total_cache_read"] or 0,
            "total_cache_write": row["total_cache_write"] or 0,
            "total_estimated_cost": row["total_estimated_cost"] or 0.0,
            "total_actual_cost": row["total_actual_cost"] or 0.0,
        }

    def get_model_breakdown(self) -> list[dict]:
        """Get cost breakdown per model."""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row

            rows = conn.execute("""
                SELECT 
                    model,
                    COUNT(*) as records,
                    SUM(input_tokens) as input_tokens,
                    SUM(output_tokens) as output_tokens,
                    SUM(estimated_cost_usd) as estimated_cost,
                    SUM(actual_cost_usd) as actual_cost
                FROM token_usage
                GROUP BY model
                ORDER BY estimated_cost DESC
            """).fetchall()

        return [dict(r) for r in rows]

    def get_session_breakdown(self, limit: int = 20) -> list[dict]:
        """Get cost breakdown per session."""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row

            rows = conn.execute("""
                SELECT 
                    session_id,
                    COUNT(*) as records,
                    SUM(input_tokens) as input_tokens,
                    SUM(output_tokens) as output_tokens,
                    SUM(estimated_cost_usd) as estimated_cost,
                    SUM(actual_cost_usd) as actual_cost,
                    MIN(timestamp) as first_seen,
                    MAX(timestamp) as last_seen
                FROM token_usage
                GROUP BY session_id
                ORDER BY estimated_cost DESC
                LIMIT ?
            """, (limit,)).fetchall()

        return [dict(r) for r in rows]

    def get_daily_summary(self) -> list[dict]:
        """Get daily cost summary for trend analysis."""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row

            rows = conn.execute("""
                SELECT 
                    date(timestamp) as day,
                    COUNT(*) as records,
                    SUM(input_tokens) as input_tokens,
                    SUM(output_tokens) as output_tokens,
                    SUM(estimated_cost_usd) as estimated_cost,
                    SUM(actual_cost_usd) as actual_cost
                FROM token_usage
                GROUP BY day
                ORDER BY day DESC
            """).fetchall()

        return [dict(r) for r in rows]
