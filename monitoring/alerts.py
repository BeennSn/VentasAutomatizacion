"""Alert manager — actionable alerts for latency, errors, cost, quality.

Implements §8.6 (monitoring and alerts) from the template.
Each alert has a level (info/warning/critical), is logged to SQLite and
optionally forwarded to Telegram.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "monitoring.sqlite"
_lock = threading.Lock()


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS alerts (
            id          TEXT PRIMARY KEY,
            timestamp   TEXT NOT NULL,
            level       TEXT NOT NULL,
            category    TEXT NOT NULL,
            message     TEXT NOT NULL,
            resolved    INTEGER DEFAULT 0,
            resolved_at TEXT,
            metadata_json TEXT
        )
    """)
    conn.commit()


def _get_conn() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH), timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    _ensure_table(conn)
    return conn


class AlertManager:
    """Creates, stores and queries operational alerts.

    Categories: latency, error_rate, cost, quality, security, system.
    """

    THRESHOLDS = {
        "latency_p95_ms": 15_000,
        "error_rate_pct": 10.0,
        "cost_budget_pct": 90.0,
    }

    def __init__(self) -> None:
        self._conn: sqlite3.Connection | None = None

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = _get_conn()
        return self._conn

    def fire(
        self,
        level: str,
        category: str,
        message: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        alert_id = str(uuid4())
        now = datetime.now(timezone.utc).isoformat()
        import json

        meta_json = json.dumps(metadata, ensure_ascii=False) if metadata else None

        with _lock:
            conn = self._get_conn()
            conn.execute(
                """INSERT INTO alerts (id, timestamp, level, category, message, metadata_json)
                   VALUES (?,?,?,?,?,?)""",
                (alert_id, now, level, category, message, meta_json),
            )
            conn.commit()
        return alert_id

    def resolve(self, alert_id: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with _lock:
            conn = self._get_conn()
            conn.execute(
                "UPDATE alerts SET resolved=1, resolved_at=? WHERE id=?",
                (now, alert_id),
            )
            conn.commit()

    def get_active(self, limit: int = 50) -> list[dict[str, Any]]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT id, timestamp, level, category, message FROM alerts WHERE resolved=0 ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [
            {
                "id": r[0],
                "timestamp": r[1],
                "level": r[2],
                "category": r[3],
                "message": r[4],
            }
            for r in rows
        ]

    def get_history(self, days: int = 7, limit: int = 200) -> list[dict[str, Any]]:
        conn = self._get_conn()
        cutoff = datetime.now(timezone.utc).isoformat()
        rows = conn.execute(
            """SELECT id, timestamp, level, category, message, resolved
               FROM alerts WHERE timestamp >= datetime(?, '-' || ? || ' days')
               ORDER BY timestamp DESC LIMIT ?""",
            (cutoff, days, limit),
        ).fetchall()
        return [
            {
                "id": r[0],
                "timestamp": r[1],
                "level": r[2],
                "category": r[3],
                "message": r[4],
                "resolved": bool(r[5]),
            }
            for r in rows
        ]

    def check_and_fire(
        self, trace_stats: dict[str, Any], cost_summary: dict[str, Any]
    ) -> list[str]:
        """Run threshold checks and fire alerts as needed. Returns list of fired alert IDs."""
        fired: list[str] = []

        if trace_stats.get("p99_latency_ms", 0) > self.THRESHOLDS["latency_p95_ms"]:
            aid = self.fire(
                "warning",
                "latency",
                f"Latencia p99 = {trace_stats['p99_latency_ms']:.0f}ms (umbral: {self.THRESHOLDS['latency_p95_ms']}ms)",
                metadata=trace_stats,
            )
            fired.append(aid)

        if trace_stats.get("error_rate", 0) > self.THRESHOLDS["error_rate_pct"]:
            aid = self.fire(
                "critical",
                "error_rate",
                f"Tasa de error = {trace_stats['error_rate']:.1f}% (umbral: {self.THRESHOLDS['error_rate_pct']}%)",
                metadata=trace_stats,
            )
            fired.append(aid)

        budget_pct = cost_summary.get("usage_pct", 0)
        if budget_pct >= 100:
            aid = self.fire(
                "critical",
                "cost",
                f"Presupuesto mensual AGOTADO ({budget_pct:.0f}%)",
                metadata=cost_summary,
            )
            fired.append(aid)
        elif budget_pct >= self.THRESHOLDS["cost_budget_pct"]:
            aid = self.fire(
                "warning",
                "cost",
                f"Presupuesto al {budget_pct:.0f}%",
                metadata=cost_summary,
            )
            fired.append(aid)

        return fired
