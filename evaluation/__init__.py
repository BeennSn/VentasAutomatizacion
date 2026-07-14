"""Evaluation package — golden set, metrics, and evaluation runner."""

from evaluation.golden_set import GOLDEN_SET
from evaluation.metrics import EvalMetrics
from evaluation.run_eval import EvaluationRunner

__all__ = ["GOLDEN_SET", "EvalMetrics", "EvaluationRunner"]
