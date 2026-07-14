"""Incident manager — structured incident tracking per §8.7.

Lifecycle: detected → triaging → mitigating → resolved → postmortem.
Each incident links to the alert that triggered it.
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
        CREATE TABLE IF NOT EXISTS incidents (
            id            TEXT PRIMARY KEY,
            created_at    TEXT NOT NULL,
            updated_at    TEXT NOT NULL,
            status        TEXT NOT NULL DEFAULT 'detected',
            severity      TEXT NOT NULL DEFAULT 'medium',
            category      TEXT NOT NULL,
            title         TEXT NOT NULL,
            description   TEXT,
            alert_id      TEXT,
            root_cause    TEXT,
            mitigation    TEXT,
            postmortem    TEXT,
            resolved_at   TEXT
        )
    """)
    conn.commit()


def _get_conn() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH), timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    _ensure_table(conn)
    return conn


class IncidentManager:
    """Create and manage incidents through their full lifecycle."""

    VALID_STATUSES = ("detected", "triaging", "mitigating", "resolved", "postmortem")
    VALID_CATEGORIES = ("quality", "latency", "cost", "availability", "security")

    def __init__(self) -> None:
        self._conn: sqlite3.Connection | None = None

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = _get_conn()
        return self._conn

    def create(
        self,
        title: str,
        category: str,
        severity: str = "medium",
        description: str = "",
        alert_id: str = "",
    ) -> str:
        incident_id = str(uuid4())
        now = datetime.now(timezone.utc).isoformat()

        with _lock:
            conn = self._get_conn()
            conn.execute(
                """INSERT INTO incidents
                   (id, created_at, updated_at, status, severity, category, title, description, alert_id)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    incident_id,
                    now,
                    now,
                    "detected",
                    severity,
                    category,
                    title,
                    description,
                    alert_id,
                ),
            )
            conn.commit()
        return incident_id

    def update_status(self, incident_id: str, status: str, notes: str = "") -> None:
        now = datetime.now(timezone.utc).isoformat()
        updates = {"updated_at": now, "status": status}
        if status == "resolved":
            updates["resolved_at"] = now
        if status == "mitigating" and notes:
            updates["mitigation"] = notes
        if status == "postmortem" and notes:
            updates["postmortem"] = notes

        set_clause = ", ".join(f"{k}=?" for k in updates)
        values = list(updates.values()) + [incident_id]

        with _lock:
            conn = self._get_conn()
            conn.execute(f"UPDATE incidents SET {set_clause} WHERE id=?", values)
            conn.commit()

    def set_root_cause(self, incident_id: str, root_cause: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with _lock:
            conn = self._get_conn()
            conn.execute(
                "UPDATE incidents SET root_cause=?, updated_at=? WHERE id=?",
                (root_cause, now, incident_id),
            )
            conn.commit()

    def get_active(self) -> list[dict[str, Any]]:
        conn = self._get_conn()
        rows = conn.execute(
            """SELECT id, created_at, status, severity, category, title, description
               FROM incidents WHERE status NOT IN ('resolved', 'postmortem')
               ORDER BY created_at DESC""",
        ).fetchall()
        return [
            {
                "id": r[0],
                "created_at": r[1],
                "status": r[2],
                "severity": r[3],
                "category": r[4],
                "title": r[5],
                "description": r[6],
            }
            for r in rows
        ]

    def get_history(self, limit: int = 50) -> list[dict[str, Any]]:
        conn = self._get_conn()
        rows = conn.execute(
            """SELECT id, created_at, resolved_at, status, severity, category, title, root_cause
               FROM incidents ORDER BY created_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [
            {
                "id": r[0],
                "created_at": r[1],
                "resolved_at": r[2],
                "status": r[3],
                "severity": r[4],
                "category": r[5],
                "title": r[6],
                "root_cause": r[7],
            }
            for r in rows
        ]
