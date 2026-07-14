"""Tests for the evaluation module — golden set validation and metrics."""

from __future__ import annotations

from evaluation.golden_set import GOLDEN_SET
from evaluation.metrics import EvalMetrics
from evaluation.run_eval import EvaluationRunner


def test_golden_set_structure():
    result = EvaluationRunner.validate_golden_set()
    assert result["valid"] is True
    assert result["total_cases"] == 10


def test_golden_set_has_required_fields():
    for case in GOLDEN_SET:
        assert "id" in case
        assert "input" in case
        assert "expected" in case
        assert "año" in case["input"]
        assert "apto_venta" in case["expected"]


def test_metrics_perfect_score():
    metrics = EvalMetrics()
    case = {
        "id": "T-01",
        "expected": {
            "apto_venta": True,
            "precio_mercado_min": 10000,
            "precio_mercado_max": 15000,
        },
    }
    metrics.add_result(
        case=case,
        result={"apto_venta": True, "precio_mercado": 12000},
        latency_ms=1500,
        cost_usd=0.005,
    )
    report = metrics.compute()
    assert report["exactitud_pct"] == 100.0
    assert report["groundedness_pct"] == 100.0
    assert report["passes_thresholds"] is True


def test_metrics_wrong_decision():
    metrics = EvalMetrics()
    case = {
        "id": "T-02",
        "expected": {"apto_venta": False},
    }
    metrics.add_result(
        case=case,
        result={"apto_venta": True, "precio_mercado": 10000},
    )
    report = metrics.compute()
    assert report["exactitud_pct"] == 0.0
    assert report["passes_thresholds"] is False


def test_metrics_price_out_of_range():
    metrics = EvalMetrics()
    case = {
        "id": "T-03",
        "expected": {
            "apto_venta": True,
            "precio_mercado_min": 10000,
            "precio_mercado_max": 15000,
        },
    }
    metrics.add_result(
        case=case,
        result={"apto_venta": True, "precio_mercado": 25000},
    )
    report = metrics.compute()
    assert report["exactitud_pct"] == 100.0
    assert report["groundedness_pct"] == 0.0
