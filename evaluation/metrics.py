"""Evaluation metrics — per §5.2 of the project template.

Metrics:
  - Exactitud: % correct decisions (apto_venta match)
  - Groundedness: price within expected range
  - Currency detection: correct moneda_detectada
  - Latency p95
  - Cost per query
"""

from __future__ import annotations

from typing import Any


class EvalMetrics:
    """Computes evaluation metrics from a list of (case, result) pairs."""

    THRESHOLDS = {
        "exactitud_pct": 90.0,
        "groundedness_pct": 95.0,
        "latency_p95_ms": 3000.0,
        "cost_per_query_usd": 0.01,
    }

    def __init__(self) -> None:
        self.results: list[dict[str, Any]] = []

    def add_result(
        self, case: dict, result: dict, latency_ms: float = 0, cost_usd: float = 0
    ) -> None:
        expected = case["expected"]
        actual_apto = result.get("apto_venta")
        correct_decision = actual_apto == expected.get("apto_venta")

        in_range = True
        if expected.get("precio_mercado_min") is not None:
            pm = result.get("precio_mercado") or 0
            in_range = (
                expected["precio_mercado_min"]
                <= pm
                <= expected.get("precio_mercado_max", float("inf"))
            )

        correct_currency = True
        if expected.get("moneda_detectada"):
            correct_currency = (
                result.get("moneda_detectada") == expected["moneda_detectada"]
            )

        self.results.append(
            {
                "case_id": case["id"],
                "correct_decision": correct_decision,
                "price_in_range": in_range,
                "correct_currency": correct_currency,
                "latency_ms": latency_ms,
                "cost_usd": cost_usd,
                "expected_apto": expected.get("apto_venta"),
                "actual_apto": actual_apto,
                "precio_mercado": result.get("precio_mercado"),
            }
        )

    def compute(self) -> dict[str, Any]:
        if not self.results:
            return {"error": "No results to evaluate"}

        n = len(self.results)
        correct = sum(1 for r in self.results if r["correct_decision"])
        grounded = sum(1 for r in self.results if r["price_in_range"])
        currency_ok = sum(1 for r in self.results if r["correct_currency"])

        latencies = sorted(r["latency_ms"] for r in self.results if r["latency_ms"] > 0)
        p95_idx = max(0, int(len(latencies) * 0.95) - 1) if latencies else 0
        p95_latency = latencies[p95_idx] if latencies else 0

        costs = [r["cost_usd"] for r in self.results if r["cost_usd"] > 0]
        avg_cost = sum(costs) / len(costs) if costs else 0

        metrics = {
            "total_cases": n,
            "exactitud_pct": round(correct / n * 100, 1),
            "groundedness_pct": round(grounded / n * 100, 1),
            "currency_accuracy_pct": round(currency_ok / n * 100, 1),
            "latency_p95_ms": round(p95_latency, 1),
            "avg_cost_per_query_usd": round(avg_cost, 6),
        }

        metrics["passes_thresholds"] = all(
            [
                metrics["exactitud_pct"] >= self.THRESHOLDS["exactitud_pct"],
                metrics["groundedness_pct"] >= self.THRESHOLDS["groundedness_pct"],
            ]
        )

        metrics["details"] = self.results
        return metrics
