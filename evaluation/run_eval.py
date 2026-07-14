"""Evaluation runner — executes the golden set against the acquisition agent.

Usage:
    python -m evaluation.run_eval              # requires GROQ_API_KEY env var
    python -m evaluation.run_eval --dry-run    # validates golden set structure only
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from typing import Any

from evaluation.golden_set import GOLDEN_SET
from evaluation.metrics import EvalMetrics


class EvaluationRunner:
    """Runs the golden set evaluation and produces a metrics report."""

    def __init__(self, api_key: str, model: str = "llama-3.3-70b-versatile") -> None:
        self.api_key = api_key
        self.model = model

    async def run(self, cases: list[dict] | None = None) -> dict[str, Any]:
        from agents.acquisition_agent import AcquisitionAgent
        from monitoring.cost_tracker import CostTracker

        cases = cases or GOLDEN_SET
        agent = AcquisitionAgent(api_key=self.api_key, model=self.model)
        cost_tracker = CostTracker()
        metrics = EvalMetrics()

        results: list[dict[str, Any]] = []
        for i, case in enumerate(cases):
            if i > 0:
                await asyncio.sleep(5)
            from shared.graph_state import CarSaleState

            state = CarSaleState(car_data=dict(case["input"]))

            start = time.perf_counter()
            try:
                result = await agent(state)
                latency_ms = (time.perf_counter() - start) * 1000
                car_data = result.get("car_data", {})

                cost_est = cost_tracker.estimate_cost(self.model, 2000, 500)

                metrics.add_result(
                    case=case,
                    result=car_data,
                    latency_ms=latency_ms,
                    cost_usd=cost_est,
                )
                entry = {
                    "case_id": case["id"],
                    "status": "ok",
                    "apto_venta": car_data.get("apto_venta"),
                    "precio_mercado": car_data.get("precio_mercado"),
                    "latency_ms": round(latency_ms, 1),
                }
                if car_data.get("error"):
                    entry["status"] = "agent_error"
                    entry["error"] = car_data["error"][:300]
                results.append(entry)
            except Exception as e:
                latency_ms = (time.perf_counter() - start) * 1000
                results.append(
                    {
                        "case_id": case["id"],
                        "status": "error",
                        "error": str(e)[:200],
                        "latency_ms": round(latency_ms, 1),
                    }
                )

        report = metrics.compute()
        report["run_results"] = results
        return report

    @staticmethod
    def validate_golden_set(cases: list[dict] | None = None) -> dict[str, Any]:
        """Dry-run: validate golden set structure without calling LLM."""
        cases = cases or GOLDEN_SET
        errors: list[str] = []
        for case in cases:
            cid = case.get("id", "?")
            if "input" not in case:
                errors.append(f"{cid}: missing 'input'")
            elif "año" not in case["input"]:
                errors.append(f"{cid}: input missing 'año'")
            if "expected" not in case:
                errors.append(f"{cid}: missing 'expected'")
            elif "apto_venta" not in case["expected"]:
                errors.append(f"{cid}: expected missing 'apto_venta'")
        return {
            "valid": len(errors) == 0,
            "total_cases": len(cases),
            "errors": errors,
        }


def main() -> None:
    import os

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

    if "--dry-run" in sys.argv:
        result = EvaluationRunner.validate_golden_set()
        print(json.dumps(result, indent=2, ensure_ascii=False))
        sys.exit(0 if result["valid"] else 1)

    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        print("ERROR: GROQ_API_KEY env var required", file=sys.stderr)
        sys.exit(1)

    runner = EvaluationRunner(api_key=api_key)
    report = asyncio.run(runner.run())
    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))

    if not report.get("passes_thresholds"):
        print("\n⚠️  Evaluation FAILED — thresholds not met", file=sys.stderr)
        sys.exit(1)
    print("\n✅ Evaluation PASSED")


if __name__ == "__main__":
    main()
