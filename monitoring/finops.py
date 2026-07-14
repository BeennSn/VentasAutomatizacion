"""FinOps reporter — cost attribution by agent/feature and trend analysis.

Implements §8.8 (Escalado y FinOps) using LangSmith trace data.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from monitoring.cost_tracker import CostTracker


class FinOpsReporter:
    """Generates FinOps reports: cost by agent, daily trends, cost per query."""

    def __init__(self, cost_tracker: CostTracker | None = None) -> None:
        self.cost_tracker = cost_tracker or CostTracker()

    def monthly_report(self) -> dict[str, Any]:
        summary = self.cost_tracker.get_monthly_spend()
        by_agent = self.cost_tracker.get_cost_by_agent(days=30)
        avg_per_query = self.cost_tracker.get_avg_cost_per_query(days=30)
        meets_target = avg_per_query <= 0.01

        return {
            "period": summary["month"],
            "total_spent_usd": summary["spent_usd"],
            "budget_usd": summary["budget_usd"],
            "remaining_usd": summary["remaining_usd"],
            "usage_pct": summary["usage_pct"],
            "total_calls": summary["total_calls"],
            "total_tokens": summary["total_tokens"],
            "avg_cost_per_query_usd": avg_per_query,
            "cost_target_met": meets_target,
            "cost_by_agent": by_agent,
        }

    def daily_trend(self, days: int = 14) -> list[dict[str, Any]]:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        runs = self.cost_tracker._get_runs_since(since)

        by_day: dict[str, dict[str, Any]] = {}
        for r in runs:
            day = r.start_time.strftime("%Y-%m-%d") if r.start_time else "unknown"
            pt = r.prompt_tokens or 0
            ct = r.completion_tokens or 0
            cost = CostTracker.estimate_cost("llama-3.3-70b-versatile", pt, ct)
            if day not in by_day:
                by_day[day] = {"calls": 0, "cost_usd": 0.0, "tokens": 0}
            by_day[day]["calls"] += 1
            by_day[day]["cost_usd"] += cost
            by_day[day]["tokens"] += pt + ct

        return [
            {
                "date": day,
                "calls": data["calls"],
                "cost_usd": round(data["cost_usd"], 4),
                "tokens": data["tokens"],
            }
            for day, data in sorted(by_day.items())
        ]
