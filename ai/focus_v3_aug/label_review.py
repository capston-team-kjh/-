"""Review-priority candidates that never mutate source labels."""

import csv
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Iterable, Mapping, Sequence

import numpy as np
from sklearn.naive_bayes import GaussianNB
from sklearn.utils.class_weight import compute_sample_weight


LABEL_REVIEW_FIELDS = (
    'sample_id',
    'source_file',
    'timestamp',
    'split',
    'current_label',
    'suspected_label',
    'reason',
    'confidence',
    'priority_semantics',
    'feature_values',
    'label_source',
)


@dataclass(frozen=True)
class ReviewPriority:
    confidence: str
    alternative_label: str
    priority_semantics: str = 'human_review_priority_not_truth'


@dataclass(frozen=True)
class ReviewReference:
    feature_names: tuple[str, ...]
    class_names: tuple[str, ...]
    class_medians: Mapping[str, tuple[float, ...]]
    class_iqrs: Mapping[str, tuple[float, ...]]
    oof_predictions: Mapping[str, str]
    limitations: tuple[str, ...]
    train_sample_ids: tuple[str, ...]


def priority_from_signals(
    *, strong: int, moderate: int, alternative_label: str
) -> ReviewPriority:
    if strong >= 2:
        confidence = 'HIGH'
    elif strong >= 1 or moderate >= 2:
        confidence = 'MEDIUM'
    else:
        confidence = 'LOW'
    return ReviewPriority(confidence, alternative_label)


def _sample_id(row: Mapping[str, object], index: int) -> str:
    return str(row.get('sample_id', row.get('original_sample_id', index)))


def _matrix(
    rows: Sequence[Mapping[str, object]], feature_names: Sequence[str]
) -> np.ndarray:
    return np.asarray(
        [[float(row[name]) for name in feature_names] for row in rows],
        dtype=np.float32,
    )


def fit_review_reference(
    train_rows: Iterable[Mapping[str, object]], feature_names: Sequence[str]
) -> ReviewReference:
    rows = [dict(row) for row in train_rows if str(row.get('split')) == 'train']
    names = tuple(feature_names)
    class_names = tuple(sorted({str(row['label']) for row in rows}))
    class_medians: dict[str, tuple[float, ...]] = {}
    class_iqrs: dict[str, tuple[float, ...]] = {}
    for label in class_names:
        selected = [row for row in rows if str(row['label']) == label]
        values = _matrix(selected, names).astype(np.float64)
        class_medians[label] = tuple(float(value) for value in np.median(values, axis=0))
        q75, q25 = np.percentile(values, [75, 25], axis=0)
        class_iqrs[label] = tuple(float(max(value, 1e-9)) for value in q75 - q25)

    groups = sorted({str(row.get('source_group_id', '')) for row in rows})
    oof_predictions: dict[str, str] = {}
    limitations: list[str] = []
    if len(groups) < 2 or len(class_names) != 4:
        limitations.append('oof_unavailable')
    else:
        for group in groups:
            fit_rows = [row for row in rows if str(row.get('source_group_id', '')) != group]
            held_out = [row for row in rows if str(row.get('source_group_id', '')) == group]
            fit_labels = [str(row['label']) for row in fit_rows]
            if len(set(fit_labels)) != 4 or not held_out:
                continue
            model = GaussianNB(priors=None, var_smoothing=1e-9)
            weights = compute_sample_weight('balanced', fit_labels)
            model.fit(_matrix(fit_rows, names), fit_labels, sample_weight=weights)
            predicted = model.predict(_matrix(held_out, names))
            for index, (row, label) in enumerate(zip(held_out, predicted)):
                oof_predictions[_sample_id(row, index)] = str(label)
        if len(oof_predictions) != len(rows):
            limitations.append('oof_partial_group_class_coverage')

    return ReviewReference(
        feature_names=names,
        class_names=class_names,
        class_medians=class_medians,
        class_iqrs=class_iqrs,
        oof_predictions=oof_predictions,
        limitations=tuple(limitations),
        train_sample_ids=tuple(_sample_id(row, index) for index, row in enumerate(rows)),
    )


def _nearest_profile(
    vector: np.ndarray, reference: ReviewReference
) -> tuple[str, float, float]:
    distances: list[tuple[float, str]] = []
    for label in reference.class_names:
        center = np.asarray(reference.class_medians[label], dtype=np.float64)
        scale = np.asarray(reference.class_iqrs[label], dtype=np.float64)
        distance = float(np.median(np.abs(vector - center) / scale))
        distances.append((distance, label))
    distances.sort()
    best_distance, best_label = distances[0]
    runner_up = distances[1][0] if len(distances) > 1 else best_distance
    return best_label, best_distance, runner_up


def build_label_review(
    rows: Iterable[Mapping[str, object]], reference: ReviewReference
) -> list[dict[str, object]]:
    candidates: list[dict[str, object]] = []
    for index, source in enumerate(rows):
        row = dict(source)
        sample_id = _sample_id(row, index)
        vector = np.asarray(
            [float(row[name]) for name in reference.feature_names], dtype=np.float64
        )
        current = str(row['label'])
        nearest, distance, runner_up = _nearest_profile(vector, reference)
        oof = reference.oof_predictions.get(sample_id)
        reasons: list[str] = []
        alternatives: list[str] = []
        strong = 0
        moderate = 0
        if oof is not None and oof != current:
            strong += 1
            alternatives.append(oof)
            reasons.append('group_oof_disagreement')
        if nearest != current and runner_up - distance >= 0.25:
            strong += 1
            alternatives.append(nearest)
            reasons.append('class_profile_disagreement')
        elif nearest != current:
            moderate += 1
            alternatives.append(nearest)
            reasons.append('weak_class_profile_disagreement')
        try:
            label_confidence = float(row.get('label_confidence', 1.0))
        except (TypeError, ValueError):
            label_confidence = 1.0
        if label_confidence < 0.75:
            moderate += 1
            reasons.append('low_source_label_confidence')
        if not reasons:
            continue
        suspected = alternatives[0] if alternatives else current
        priority = priority_from_signals(
            strong=strong, moderate=moderate, alternative_label=suspected
        )
        candidates.append(
            {
                'sample_id': sample_id,
                'source_file': str(row.get('source_path', row.get('source_file', ''))),
                'timestamp': str(row.get('timestamp_ms', row.get('timestamp', ''))),
                'split': str(row.get('split', '')),
                'current_label': current,
                'suspected_label': priority.alternative_label,
                'reason': '|'.join(reasons),
                'confidence': priority.confidence,
                'priority_semantics': priority.priority_semantics,
                'feature_values': json.dumps(
                    {
                        name: float(row[name])
                        for name in reference.feature_names
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(',', ':'),
                ),
                'label_source': str(row.get('label_source', '')),
            }
        )
    return sorted(
        candidates,
        key=lambda row: (
            {'HIGH': 0, 'MEDIUM': 1, 'LOW': 2}[str(row['confidence'])],
            str(row['sample_id']),
        ),
    )


def review_frame_requests(
    candidates: Iterable[Mapping[str, object]], *, include_test: bool = False
) -> list[tuple[str, int, str]]:
    requests = []
    for candidate in candidates:
        if str(candidate.get('split')) == 'test' and not include_test:
            continue
        requests.append(
            (
                str(candidate['source_file']),
                int(float(candidate['timestamp'])),
                str(candidate['sample_id']),
            )
        )
    return requests


def write_label_review(
    path: Path | str, candidates: Iterable[Mapping[str, object]]
) -> Path:
    destination = Path(path)
    if destination.exists():
        raise FileExistsError(f'refusing to overwrite label review: {destination}')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=LABEL_REVIEW_FIELDS)
        writer.writeheader()
        for candidate in candidates:
            writer.writerow({field: candidate.get(field, '') for field in LABEL_REVIEW_FIELDS})
    return destination
