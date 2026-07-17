from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "listings.sqlite"
_lock = threading.Lock()


def _get_conn() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH), timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS listings (
            car_id TEXT PRIMARY KEY,
            car_data_json TEXT NOT NULL,
            published_at TEXT NOT NULL
        )"""
    )
    conn.commit()
    return conn


def save_listing(car_id: str, car_data: dict[str, Any]) -> None:
    """Guarda una foto del auto publicado para que el bot de Telegram pueda
    identificarlo cuando un cliente potencial le escribe desde el canal."""
    with _lock:
        conn = _get_conn()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO listings (car_id, car_data_json, published_at) VALUES (?,?,?)",
                (
                    car_id,
                    json.dumps(car_data, ensure_ascii=False),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            conn.commit()
        finally:
            conn.close()


def get_listing(car_id: str) -> dict[str, Any] | None:
    with _lock:
        conn = _get_conn()
        try:
            row = conn.execute(
                "SELECT car_data_json FROM listings WHERE car_id=?", (car_id,)
            ).fetchone()
        finally:
            conn.close()
    return json.loads(row[0]) if row else None
