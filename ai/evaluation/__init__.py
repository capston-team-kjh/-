"""Metrics for comparing FocusAI predictions with manual annotations."""

from .core import EvaluationError, evaluate

__all__ = ["EvaluationError", "evaluate"]
