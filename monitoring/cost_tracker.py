"""Cost tracker — per-query cost estimation from LangSmith traces.

Implements §8.8 (FinOps) and §2.4 (cost < $0.01 per query).
Reads token usage from LangSmith and applies model-specific pricing.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

MODEL_PRICING: dict[str, dict[str, float]] = {
    "llama-3.3-70b-versatile": {"input_per_1m": 0.59, "output_per_1m": 0.79},
    "meta-llama/llama-4-scout-17b-16e-instruct": {
        "input_per_1m": 0.20,
        "output_per_1m": 0.20,
    },
    "llama-3.1-8b-instant": {"input_per_1m": 0.05, "output_per_1m": 0.08},
}

DEFAULT_PRICING = {"input_per_1m": 0.59, "output_per_1m": 0.79}


def _langsmith_available() -> bool:
    return bool(os.getenv("LANGSMITH_API_KEY"))


class CostTracker:
    """Computes costs from LangSmith trace data with budget alerting."""

    def __init__(
        self, monthly_budget_usd: float = 50.0, project_name: str | None = None
    ) -> None:
        self.monthly_budget_usd = monthly_budget_usd
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
    def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
        pricing = MODEL_PRICING.get(model, DEFAULT_PRICING)
        cost = (
            prompt_tokens * pricing["input_per_1m"]
            + completion_tokens * pricing["output_per_1m"]
        ) / 1_000_000
        return round(cost, 6)

    def _get_runs_since(self, since: datetime) -> list:
        if not _langsmith_available():
            return []
        try:
            client = self._get_client()
            return list(
                client.list_runs(
                    project_name=self._project,
                    execution_order=1,
                    start_time=since,
                )
            )
        except Exception:
            return []

    def get_monthly_spend(self) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        runs = self._get_runs_since(month_start)

        total_cost = 0.0
        total_tokens = 0
        for r in runs:
            pt = r.prompt_tokens or 0
            ct = r.completion_tokens or 0
            total_tokens += pt + ct
            total_cost += self.estimate_cost("llama-3.3-70b-versatile", pt, ct)

        spent = round(total_cost, 4)
        return {
            "month": now.strftime("%Y-%m"),
            "spent_usd": spent,
            "budget_usd": self.monthly_budget_usd,
            "remaining_usd": round(self.monthly_budget_usd - spent, 4),
            "usage_pct": round(spent / max(self.monthly_budget_usd, 0.01) * 100, 1),
            "total_calls": len(runs),
            "total_tokens": total_tokens,
        }

    def check_budget_alert(self) -> dict[str, Any] | None:
        summary = self.get_monthly_spend()
        pct = summary["usage_pct"]
        if pct >= 100:
            return {
                "level": "critical",
                "message": f"Presupuesto mensual AGOTADO ({pct:.0f}%)",
                **summary,
            }
        if pct >= 90:
            return {
                "level": "warning",
                "message": f"Presupuesto al {pct:.0f}% — quedan ${summary['remaining_usd']:.2f}",
                **summary,
            }
        if pct >= 70:
            return {"level": "info", "message": f"Presupuesto al {pct:.0f}%", **summary}
        return None

    def get_cost_by_agent(self, days: int = 30) -> list[dict[str, Any]]:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        runs = self._get_runs_since(since)

        by_agent: dict[str, dict[str, Any]] = {}
        for r in runs:
            name = r.name or "unknown"
            pt = r.prompt_tokens or 0
            ct = r.completion_tokens or 0
            cost = self.estimate_cost("llama-3.3-70b-versatile", pt, ct)
            if name not in by_agent:
                by_agent[name] = {"calls": 0, "total_cost_usd": 0.0, "total_tokens": 0}
            by_agent[name]["calls"] += 1
            by_agent[name]["total_cost_usd"] += cost
            by_agent[name]["total_tokens"] += pt + ct

        return [
            {
                "agent": name,
                "calls": data["calls"],
                "total_cost_usd": round(data["total_cost_usd"], 4),
                "total_tokens": data["total_tokens"],
            }
            for name, data in sorted(
                by_agent.items(), key=lambda x: x[1]["total_cost_usd"], reverse=True
            )
        ]

    def get_avg_cost_per_query(self, days: int = 7) -> float:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        runs = self._get_runs_since(since)
        if not runs:
            return 0.0
        total_cost = sum(
            self.estimate_cost(
                "llama-3.3-70b-versatile",
                r.prompt_tokens or 0,
                r.completion_tokens or 0,
            )
            for r in runs
        )
        return round(total_cost / len(runs), 6)
