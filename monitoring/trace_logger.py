"""Trace logger — queries LangSmith for per-query traces.

Uses LangSmith as the observability backend (§3.8, §8.6).
LangChain/LangGraph auto-trace when LANGSMITH_TRACING=true is set.
This module reads trace data from LangSmith for dashboarding and alerting.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any


def _langsmith_available() -> bool:
    return bool(os.getenv("LANGSMITH_API_KEY"))


class TraceLogger:
    """Reads trace data from LangSmith for the monitoring dashboard."""

    def __init__(self, project_name: str | None = None) -> None:
        self._project = project_name or os.getenv(
            "LANGSMITH_PROJECT", "VentasAutomatizacion"
        )
        self._client = None

    def _get_client(self):
        if self._client is None:
            from langsmith import Client

            self._client = Client()
        return self._client

    @staticmethod
    def is_configured() -> bool:
        return _langsmith_available()

    def get_traces(
        self, limit: int = 100, agent: str | None = None
    ) -> list[dict[str, Any]]:
        if not _langsmith_available():
            return []
        try:
            client = self._get_client()
            kwargs: dict[str, Any] = {
                "project_name": self._project,
                "execution_order": 1,
                "limit": limit,
            }
            if agent:
                kwargs["filter"] = f'eq(name, "{agent}")'

            results = []
            for run in client.list_runs(**kwargs):
                latency = 0.0
                if run.end_time and run.start_time:
                    latency = round(
                        (run.end_time - run.start_time).total_seconds() * 1000, 1
                    )
                results.append(
                    {
                        "id": str(run.id),
                        "timestamp": run.start_time.isoformat()
                        if run.start_time
                        else "",
                        "agent": run.name or "",
                        "car_id": (run.extra or {})
                        .get("metadata", {})
                        .get("car_id", ""),
                        "prompt_tokens": run.prompt_tokens or 0,
                        "completion_tokens": run.completion_tokens or 0,
                        "total_tokens": run.total_tokens or 0,
                        "latency_ms": latency,
                        "status": run.status or "unknown",
                        "error": run.error or None,
                        "model": (run.extra or {})
                        .get("invocation_params", {})
                        .get("model", ""),
                    }
                )
            return results
        except Exception:
            return []

    def get_stats(self, hours: int = 24) -> dict[str, Any]:
        empty = {
            "total_calls": 0,
            "total_tokens": 0,
            "avg_latency_ms": 0,
            "p99_latency_ms": 0,
            "error_count": 0,
            "error_rate": 0,
        }
        if not _langsmith_available():
            return empty
        try:
            client = self._get_client()
            since = datetime.now(timezone.utc) - timedelta(hours=hours)
            runs = list(
                client.list_runs(
                    project_name=self._project,
                    execution_order=1,
                    start_time=since,
                )
            )
            total_calls = len(runs)
            if total_calls == 0:
                return empty

            total_tokens = sum(r.total_tokens or 0 for r in runs)
            latencies: list[float] = []
            errors = 0
            for r in runs:
                if r.end_time and r.start_time:
                    latencies.append((r.end_time - r.start_time).total_seconds() * 1000)
                if r.status == "error":
                    errors += 1

            avg_latency = round(sum(latencies) / len(latencies), 1) if latencies else 0
            p99_idx = (
                min(int(len(latencies) * 0.99), len(latencies) - 1) if latencies else 0
            )
            p99_latency = round(sorted(latencies)[p99_idx], 1) if latencies else 0

            return {
                "total_calls": total_calls,
                "total_tokens": total_tokens,
                "avg_latency_ms": avg_latency,
                "p99_latency_ms": p99_latency,
                "error_count": errors,
                "error_rate": round(errors / max(total_calls, 1) * 100, 2),
            }
        except Exception:
            return empty
