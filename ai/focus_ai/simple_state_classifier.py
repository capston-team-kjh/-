from __future__ import annotations

import math
from collections import defaultdict
from typing import Iterable, Sequence


class SimpleStateClassifier:
    """Small pickle-friendly Gaussian Naive Bayes classifier.

    The project only needs a predict_proba-compatible object in
    ai/models/state_classifier.pkl. Keeping this local avoids adding a runtime
    dependency just to train the optional state classifier.
    """

    def __init__(
        self,
        classes: Sequence[str],
        means: dict[str, list[float]],
        variances: dict[str, list[float]],
        priors: dict[str, float],
        min_variance: float = 1e-4,
    ) -> None:
        self.classes_ = [str(label) for label in classes]
        self.means_ = {str(label): [float(v) for v in values] for label, values in means.items()}
        self.variances_ = {
            str(label): [max(float(v), float(min_variance)) for v in values]
            for label, values in variances.items()
        }
        self.priors_ = {str(label): float(priors[label]) for label in self.classes_}
        self.min_variance = float(min_variance)

    @classmethod
    def fit(
        cls,
        rows: Sequence[Sequence[float]],
        labels: Sequence[str],
        *,
        balanced_priors: bool = True,
        min_variance: float = 1e-4,
    ) -> "SimpleStateClassifier":
        if len(rows) != len(labels):
            raise ValueError("rows and labels must have the same length")
        if not rows:
            raise ValueError("at least one training row is required")

        width = len(rows[0])
        if width == 0:
            raise ValueError("training rows must have at least one feature")

        grouped: dict[str, list[list[float]]] = defaultdict(list)
        for row, label in zip(rows, labels):
            values = [float(value) for value in row]
            if len(values) != width:
                raise ValueError("all training rows must have the same feature width")
            grouped[str(label)].append(values)

        classes = sorted(grouped)
        means: dict[str, list[float]] = {}
        variances: dict[str, list[float]] = {}
        total_count = float(len(rows))

        for label in classes:
            class_rows = grouped[label]
            count = float(len(class_rows))
            label_means = [
                sum(row[idx] for row in class_rows) / count
                for idx in range(width)
            ]
            means[label] = label_means
            variances[label] = [
                max(
                    sum((row[idx] - label_means[idx]) ** 2 for row in class_rows) / count,
                    float(min_variance),
                )
                for idx in range(width)
            ]

        if balanced_priors:
            priors = {label: 1.0 / len(classes) for label in classes}
        else:
            priors = {label: len(grouped[label]) / total_count for label in classes}

        return cls(classes, means, variances, priors, min_variance=min_variance)

    def predict_proba(self, rows: Iterable[Sequence[float]]) -> list[list[float]]:
        return [self._predict_one(row) for row in rows]

    def predict(self, rows: Iterable[Sequence[float]]) -> list[str]:
        predictions: list[str] = []
        for probabilities in self.predict_proba(rows):
            best_index = max(range(len(self.classes_)), key=lambda idx: probabilities[idx])
            predictions.append(self.classes_[best_index])
        return predictions

    def _predict_one(self, row: Sequence[float]) -> list[float]:
        values = [float(value) for value in row]
        log_probs: list[float] = []

        for label in self.classes_:
            prior = max(self.priors_.get(label, 0.0), 1e-12)
            log_prob = math.log(prior)
            means = self.means_[label]
            variances = self.variances_[label]

            for value, mean, variance in zip(values, means, variances):
                variance = max(float(variance), self.min_variance)
                log_prob += -0.5 * math.log(2.0 * math.pi * variance)
                log_prob += -((value - mean) ** 2) / (2.0 * variance)

            log_probs.append(log_prob)

        max_log = max(log_probs)
        exp_values = [math.exp(value - max_log) for value in log_probs]
        total = sum(exp_values)
        if total <= 0.0:
            return [1.0 / len(self.classes_) for _ in self.classes_]
        return [value / total for value in exp_values]
