from __future__ import annotations

import math
from collections import Counter
from typing import Iterable, Sequence


class SimpleKNNClassifier:
    """Small pickle-friendly k-nearest-neighbor classifier.

    This mirrors the minimal predict_proba interface used by the optional
    state classifier loader without adding a scikit-learn runtime dependency.
    """

    def __init__(
        self,
        k: int = 11,
        weighted: bool = True,
        balanced: bool = False,
    ) -> None:
        self.k = int(k)
        self.weighted = bool(weighted)
        self.balanced = bool(balanced)
        self.classes_: list[str] = []
        self.rows_: list[list[float]] = []
        self.labels_: list[str] = []
        self.means_: list[float] = []
        self.stds_: list[float] = []
        self.scaled_rows_: list[list[float]] = []
        self.class_weights_: dict[str, float] = {}

    def fit(
        self,
        rows: Sequence[Sequence[float]],
        labels: Sequence[str],
    ) -> "SimpleKNNClassifier":
        if len(rows) != len(labels):
            raise ValueError("rows and labels must have the same length")
        if not rows:
            raise ValueError("at least one training row is required")

        width = len(rows[0])
        if width == 0:
            raise ValueError("training rows must have at least one feature")

        self.rows_ = []
        for row in rows:
            values = [float(value) for value in row]
            if len(values) != width:
                raise ValueError("all training rows must have the same feature width")
            self.rows_.append(values)

        self.labels_ = [str(label) for label in labels]
        self.classes_ = sorted(set(self.labels_))
        self.k = max(1, min(int(self.k), len(self.rows_)))

        self.means_ = [
            sum(row[idx] for row in self.rows_) / len(self.rows_)
            for idx in range(width)
        ]
        self.stds_ = []
        for idx, mean in enumerate(self.means_):
            variance = sum((row[idx] - mean) ** 2 for row in self.rows_) / len(self.rows_)
            self.stds_.append(math.sqrt(variance) or 1.0)

        self.scaled_rows_ = [self._scale(row) for row in self.rows_]

        counts = Counter(self.labels_)
        class_count = max(len(counts), 1)
        total = float(len(self.labels_))
        self.class_weights_ = {
            label: (total / (class_count * count) if self.balanced else 1.0)
            for label, count in counts.items()
        }
        return self

    def predict_proba(self, rows: Iterable[Sequence[float]]) -> list[list[float]]:
        return [self._predict_one(row) for row in rows]

    def predict(self, rows: Iterable[Sequence[float]]) -> list[str]:
        predictions: list[str] = []
        for probabilities in self.predict_proba(rows):
            best_index = max(range(len(self.classes_)), key=lambda idx: probabilities[idx])
            predictions.append(self.classes_[best_index])
        return predictions

    def _scale(self, row: Sequence[float]) -> list[float]:
        values = [float(value) for value in row]
        return [
            (values[idx] - self.means_[idx]) / self.stds_[idx]
            for idx in range(len(self.means_))
        ]

    def _predict_one(self, row: Sequence[float]) -> list[float]:
        if not self.scaled_rows_:
            raise ValueError("classifier has not been fit")

        values = self._scale(row)
        distances: list[tuple[float, str]] = []
        for train_row, label in zip(self.scaled_rows_, self.labels_):
            distance = math.sqrt(
                sum((values[idx] - train_row[idx]) ** 2 for idx in range(len(values)))
            )
            distances.append((distance, label))
        distances.sort(key=lambda item: item[0])

        scores = {label: 0.0 for label in self.classes_}
        for distance, label in distances[: self.k]:
            weight = 1.0 / (distance + 1e-6) if self.weighted else 1.0
            scores[label] += weight * self.class_weights_.get(label, 1.0)

        total = sum(scores.values())
        if total <= 0.0:
            return [1.0 / len(self.classes_) for _ in self.classes_]
        return [scores[label] / total for label in self.classes_]
