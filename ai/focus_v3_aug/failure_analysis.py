"""Multi-cause analysis for unusable FocusAI feature rows."""

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
import math
from typing import Iterable, Mapping, Sequence


REASON_PRECEDENCE = (
    'frame_decode_failure',
    'face_detection_failure',
    'pose_detection_failure',
    'calibration_not_ready',
    'temporal_history_insufficient',
    'required_feature_missing',
    'non_finite_feature',
    'hard_domain_range_violation',
    'train_distribution_outlier',
)

_TEMPORAL_TOKENS = ('rolling', 'slope', 'continuous_eye_closed')
_UNIT_INTERVAL_FEATURES = {
    'face_seen',
    'pose_seen',
    'face_valid_ratio',
    'pose_valid_ratio',
    'calibration_valid',
}


@dataclass(frozen=True)
class FailureRecord:
    sample_id: str
    primary_reason: str
    additional_reasons: tuple[str, ...]
    reason_features: Mapping[str, tuple[str, ...]]
    split: str = ''
    label: str = ''
    source_group_id: str = ''

    @property
    def all_reasons(self) -> tuple[str, ...]:
        return (self.primary_reason, *self.additional_reasons)

    def as_dict(self) -> dict[str, object]:
        value = asdict(self)
        value['additional_reasons'] = list(self.additional_reasons)
        value['reason_features'] = {
            reason: list(features)
            for reason, features in self.reason_features.items()
        }
        return value


def _number(value: object) -> float | None:
    if value is None or value == '':
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def analyze_feature_failures(
    rows: Iterable[Mapping[str, object]], feature_names: Sequence[str]
) -> list[FailureRecord]:
    failures: list[FailureRecord] = []
    for index, row in enumerate(rows):
        reason_features: dict[str, set[str]] = defaultdict(set)
        status = str(row.get('status', '')).lower()
        if (
            row.get('decode_error') is True
            or row.get('frame_decoded') is False
            or 'decode' in status and status not in {'decoded', 'extracted'}
        ):
            reason_features['frame_decode_failure'].add('frame')

        for quality_name, reason in (
            ('face_seen', 'face_detection_failure'),
            ('pose_seen', 'pose_detection_failure'),
            ('calibration_valid', 'calibration_not_ready'),
        ):
            value = _number(row.get(quality_name))
            if value is not None and value <= 0.0:
                reason_features[reason].add(quality_name)

        missing: list[str] = []
        non_finite: list[str] = []
        invalid_ranges: list[str] = []
        temporal_invalid: list[str] = []
        for name in feature_names:
            value = _number(row.get(name))
            if value is None:
                missing.append(name)
                if any(token in name for token in _TEMPORAL_TOKENS):
                    temporal_invalid.append(name)
                continue
            if not math.isfinite(value):
                non_finite.append(name)
                if any(token in name for token in _TEMPORAL_TOKENS):
                    temporal_invalid.append(name)
                continue
            if name in _UNIT_INTERVAL_FEATURES and not 0.0 <= value <= 1.0:
                invalid_ranges.append(name)
            elif name.endswith('_ear') and value < 0.0:
                invalid_ranges.append(name)

        if row.get('temporal_ready') is False:
            temporal_invalid.append('temporal_ready')
        if temporal_invalid:
            reason_features['temporal_history_insufficient'].update(temporal_invalid)
        if missing:
            reason_features['required_feature_missing'].update(missing)
        if non_finite:
            reason_features['non_finite_feature'].update(non_finite)
        if invalid_ranges:
            reason_features['hard_domain_range_violation'].update(invalid_ranges)
        if row.get('train_distribution_outlier') is True:
            reason_features['train_distribution_outlier'].add('feature_vector')

        ordered_reasons = tuple(
            reason for reason in REASON_PRECEDENCE if reason in reason_features
        )
        if not ordered_reasons:
            continue
        failures.append(
            FailureRecord(
                sample_id=str(row.get('sample_id', row.get('original_sample_id', index))),
                primary_reason=ordered_reasons[0],
                additional_reasons=ordered_reasons[1:],
                reason_features={
                    reason: tuple(sorted(reason_features[reason]))
                    for reason in ordered_reasons
                },
                split=str(row.get('split', '')),
                label=str(row.get('label', '')),
                source_group_id=str(row.get('source_group_id', '')),
            )
        )
    return failures


def summarize_failures(
    failures: Sequence[FailureRecord], total_rows: int
) -> dict[str, object]:
    reason_counts = Counter(
        reason for failure in failures for reason in failure.all_reasons
    )
    primary_counts = Counter(failure.primary_reason for failure in failures)
    dimensions: dict[str, Counter[str]] = {
        'split': Counter(),
        'label': Counter(),
        'source_group_id': Counter(),
        'feature': Counter(),
    }
    for failure in failures:
        dimensions['split'][failure.split] += 1
        dimensions['label'][failure.label] += 1
        dimensions['source_group_id'][failure.source_group_id] += 1
        for features in failure.reason_features.values():
            dimensions['feature'].update(features)
    denominator = max(total_rows, 1)
    unusable = len(failures)
    return {
        'total_rows': total_rows,
        'usable_rows': max(total_rows - unusable, 0),
        'unusable_rows': unusable,
        'unusable_rate': unusable / denominator,
        'baseline_unusable_rows': 14_797,
        'baseline_total_rows': 27_951,
        'baseline_unusable_rate': 14_797 / 27_951,
        'primary_reason_counts': dict(sorted(primary_counts.items())),
        'all_reason_counts': dict(sorted(reason_counts.items())),
        'all_reason_rates': {
            reason: count / denominator
            for reason, count in sorted(reason_counts.items())
        },
        'dimensions': {
            name: dict(sorted(counts.items()))
            for name, counts in dimensions.items()
        },
    }
