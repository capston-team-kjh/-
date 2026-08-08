"""Separated evaluation metrics and pre-locked improvement guards."""

from collections import Counter
from dataclasses import asdict, dataclass
from typing import Mapping, Sequence

import numpy as np
from sklearn.metrics import confusion_matrix, precision_recall_fscore_support

from .config import DecisionThresholds


@dataclass(frozen=True)
class ClassificationReport:
    sample_count: int
    misclassification_count: int
    macro_f1: float
    weighted_f1: float
    balanced_accuracy: float
    focus_precision: float
    focus_recall: float
    per_class: Mapping[str, Mapping[str, float | int]]
    confusion_raw: Mapping[str, Mapping[str, int]]
    confusion_row_normalized: Mapping[str, Mapping[str, float]]
    dominant_prediction_class: str | None
    prediction_concentration: float

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ImprovementDecision:
    passed: bool
    failed_gates: tuple[str, ...]
    deltas: Mapping[str, Mapping[str, float]]


def classification_report(
    y_true: Sequence[str], y_pred: Sequence[str], class_order: Sequence[str]
) -> ClassificationReport:
    if len(y_true) != len(y_pred):
        raise ValueError('truth and prediction counts differ')
    classes = tuple(class_order)
    precision, recall, f1, support = precision_recall_fscore_support(
        y_true,
        y_pred,
        labels=classes,
        zero_division=0,
    )
    matrix = confusion_matrix(y_true, y_pred, labels=classes)
    row_totals = matrix.sum(axis=1, keepdims=True)
    normalized = np.divide(
        matrix,
        row_totals,
        out=np.zeros_like(matrix, dtype=np.float64),
        where=row_totals != 0,
    )
    per_class = {
        label: {
            'precision': float(precision[index]),
            'recall': float(recall[index]),
            'f1': float(f1[index]),
            'support': int(support[index]),
            'misclassification_count': int(support[index] - matrix[index, index]),
        }
        for index, label in enumerate(classes)
    }
    confusion_raw = {
        actual: {
            predicted: int(matrix[actual_index, predicted_index])
            for predicted_index, predicted in enumerate(classes)
        }
        for actual_index, actual in enumerate(classes)
    }
    confusion_normalized = {
        actual: {
            predicted: float(normalized[actual_index, predicted_index])
            for predicted_index, predicted in enumerate(classes)
        }
        for actual_index, actual in enumerate(classes)
    }
    sample_count = len(y_true)
    supported = support > 0
    balanced_accuracy = float(np.mean(recall[supported])) if supported.any() else 0.0
    total_support = int(support.sum())
    weighted_f1 = (
        float(np.dot(f1, support) / total_support) if total_support else 0.0
    )
    prediction_counts = Counter(str(label) for label in y_pred)
    if prediction_counts:
        order_index = {label: index for index, label in enumerate(classes)}
        dominant, dominant_count = min(
            prediction_counts.items(),
            key=lambda item: (-item[1], order_index.get(item[0], len(classes))),
        )
    else:
        dominant, dominant_count = None, 0
    focus = classes.index('focus')
    return ClassificationReport(
        sample_count=sample_count,
        misclassification_count=sum(
            str(actual) != str(predicted)
            for actual, predicted in zip(y_true, y_pred)
        ),
        macro_f1=float(np.mean(f1)),
        weighted_f1=weighted_f1,
        balanced_accuracy=balanced_accuracy,
        focus_precision=float(precision[focus]),
        focus_recall=float(recall[focus]),
        per_class=per_class,
        confusion_raw=confusion_raw,
        confusion_row_normalized=confusion_normalized,
        dominant_prediction_class=dominant,
        prediction_concentration=(dominant_count / sample_count if sample_count else 0.0),
    )


def add_a_deltas(
    report: Mapping[str, object], baseline: Mapping[str, object]
) -> dict[str, object]:
    result = dict(report)
    result['delta_from_a'] = {
        name: float(report[name]) - float(baseline[name])
        for name in (
            'macro_f1',
            'weighted_f1',
            'balanced_accuracy',
            'focus_precision',
            'focus_recall',
            'prediction_concentration',
        )
    }
    return result


def is_improved(
    candidate: Mapping[str, Mapping[str, object]],
    baseline: Mapping[str, Mapping[str, object]],
    thresholds: DecisionThresholds,
) -> ImprovementDecision:
    failed: list[str] = []
    deltas: dict[str, dict[str, float]] = {}
    for split in ('validation', 'test'):
        current = candidate[split]
        original = baseline[split]
        deltas[split] = {
            name: float(current[name]) - float(original[name])
            for name in (
                'macro_f1',
                'balanced_accuracy',
                'focus_recall',
                'focus_precision',
                'prediction_concentration',
            )
        }
        if (
            float(original['macro_f1']) - float(current['macro_f1'])
            > thresholds.maximum_validation_metric_regression
            and split == 'validation'
        ):
            failed.append('validation_macro_f1_regression')
        if (
            float(original['balanced_accuracy'])
            - float(current['balanced_accuracy'])
            > thresholds.maximum_validation_metric_regression
            and split == 'validation'
        ):
            failed.append('validation_balanced_accuracy_regression')
        if (
            float(original['focus_precision']) - float(current['focus_precision'])
            > thresholds.maximum_focus_precision_drop
        ):
            failed.append(f'{split}_focus_precision_drop')
        if (
            float(current['focus_recall']) > float(original['focus_recall'])
            and float(current['focus_precision'])
            < thresholds.minimum_focus_precision_when_recall_improves
        ):
            failed.append(f'{split}_focus_precision_floor')
        if (
            float(current['prediction_concentration'])
            > thresholds.maximum_prediction_concentration
        ):
            failed.append(f'{split}_prediction_concentration')
        for label, original_class in original['per_class'].items():
            current_class = current['per_class'][label]
            if (
                float(original_class['recall']) - float(current_class['recall'])
                > thresholds.maximum_per_class_recall_drop
            ):
                failed.append(f'{split}_{label}_recall_drop')

    if deltas['test']['macro_f1'] < thresholds.minimum_macro_f1_delta:
        failed.append('test_macro_f1_delta')
    if (
        deltas['test']['balanced_accuracy']
        < thresholds.minimum_balanced_accuracy_delta
    ):
        failed.append('test_balanced_accuracy_delta')
    if deltas['test']['focus_recall'] < thresholds.minimum_focus_recall_delta:
        failed.append('test_focus_recall_delta')

    safety = candidate.get('safety_gates', {})
    if isinstance(safety, Mapping):
        for name, passed in safety.items():
            if not bool(passed):
                failed.append(f'safety_{name}')
    return ImprovementDecision(
        passed=not failed,
        failed_gates=tuple(dict.fromkeys(failed)),
        deltas=deltas,
    )
