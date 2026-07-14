"""Security logger — detects and logs prompt injection attempts and anomalous usage.

Implements §3.9 (security) and §8.6 (security monitoring) from the template.
"""

from __future__ import annotations

import re
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "monitoring.sqlite"
_lock = threading.Lock()

INJECTION_PATTERNS = [
    r"ignore\s+(previous|all|above)\s+(instructions|prompts|rules)",
    r"disregard\s+(your|all|the)\s+(instructions|rules|guidelines)",
    r"you\s+are\s+now\s+(a|an)\s+",
    r"act\s+as\s+if\s+you\s+(are|were)\s+",
    r"system\s*:\s*",
    r"<\s*/?system\s*>",
    r"jailbreak",
    r"DAN\s+mode",
    r"bypass\s+(your|the|all)\s+(filter|restriction|rule|safety)",
    r"pretend\s+you\s+(are|have|can)",
    r"reveal\s+(your|the)\s+(prompt|instructions|system)",
]

_compiled = [re.compile(p, re.IGNORECASE) for p in INJECTION_PATTERNS]


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS security_events (
            id          TEXT PRIMARY KEY,
            timestamp   TEXT NOT NULL,
            event_type  TEXT NOT NULL,
            severity    TEXT NOT NULL,
            source      TEXT,
            details     TEXT,
            user_input  TEXT,
            blocked     INTEGER DEFAULT 0
        )
    """)
    conn.commit()


def _get_conn() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH), timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    _ensure_table(conn)
    return conn


class SecurityLogger:
    """Logs security events and scans user input for injection attempts."""

    def __init__(self) -> None:
        self._conn: sqlite3.Connection | None = None

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = _get_conn()
        return self._conn

    def scan_input(self, user_input: str, source: str = "web") -> dict[str, Any]:
        """Scan user input for prompt injection patterns. Returns detection result."""
        matches: list[str] = []
        for pattern in _compiled:
            if pattern.search(user_input):
                matches.append(pattern.pattern)

        if matches:
            event_id = self.log_event(
                event_type="prompt_injection_attempt",
                severity="high",
                source=source,
                details=f"Matched {len(matches)} pattern(s)",
                user_input=user_input[:500],
                blocked=True,
            )
            return {"safe": False, "event_id": event_id, "matches": len(matches)}
        return {"safe": True}

    def log_event(
        self,
        event_type: str,
        severity: str,
        source: str = "",
        details: str = "",
        user_input: str = "",
        blocked: bool = False,
    ) -> str:
        event_id = str(uuid4())
        now = datetime.now(timezone.utc).isoformat()

        with _lock:
            conn = self._get_conn()
            conn.execute(
                """INSERT INTO security_events
                   (id, timestamp, event_type, severity, source, details, user_input, blocked)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    event_id,
                    now,
                    event_type,
                    severity,
                    source,
                    details,
                    user_input[:1000],
                    int(blocked),
                ),
            )
            conn.commit()
        return event_id

    def get_events(self, days: int = 7, limit: int = 100) -> list[dict[str, Any]]:
        conn = self._get_conn()
        cutoff = datetime.now(timezone.utc).isoformat()
        rows = conn.execute(
            """SELECT id, timestamp, event_type, severity, source, details, blocked
               FROM security_events
               WHERE timestamp >= datetime(?, '-' || ? || ' days')
               ORDER BY timestamp DESC LIMIT ?""",
            (cutoff, days, limit),
        ).fetchall()
        return [
            {
                "id": r[0],
                "timestamp": r[1],
                "event_type": r[2],
                "severity": r[3],
                "source": r[4],
                "details": r[5],
                "blocked": bool(r[6]),
            }
            for r in rows
        ]

    def get_summary(self, days: int = 7) -> dict[str, Any]:
        conn = self._get_conn()
        cutoff = datetime.now(timezone.utc).isoformat()
        row = conn.execute(
            """SELECT COUNT(*), SUM(CASE WHEN blocked=1 THEN 1 ELSE 0 END)
               FROM security_events
               WHERE timestamp >= datetime(?, '-' || ? || ' days')""",
            (cutoff, days),
        ).fetchone()
        return {
            "total_events": row[0] or 0,
            "blocked_count": row[1] or 0,
            "period_days": days,
        }
