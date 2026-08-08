"""Deterministic SAFE image augmentation policy and B/C planning."""

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from hashlib import sha256
import statistics
from typing import Iterable, Mapping, Sequence

import cv2
import numpy as np

from .config import AugmentationConfig
from .lineage import derived_sample_id


SAFE_RANGES = {
    'brightness': {'factor': (0.90, 1.10)},
    'contrast': {'factor': (0.90, 1.10)},
    'gamma': {'gamma': (0.90, 1.10)},
    'gaussian_blur': {'kernel': (3, 3), 'sigma': (0.3, 0.8)},
    'sensor_noise': {'mean': 0.0, 'sigma': (1.0, 3.0)},
}
SAFE_KINDS = tuple(SAFE_RANGES)
CONDITIONAL = ('horizontal_flip', 'rotation', 'crop', 'scale')
UNSAFE = ('perspective_warp', 'synthetic_occlusion', 'temporal_reordering')

_SAFE_PARAMETERS: Mapping[str, Mapping[str, object]] = {
    'brightness': {'factor': 1.05},
    'contrast': {'factor': 1.05},
    'gamma': {'gamma': 0.95},
    'gaussian_blur': {'kernel': [3, 3], 'sigma': 0.5},
    'sensor_noise': {'mean': 0.0, 'sigma': 2.0},
}


@dataclass(frozen=True)
class AugmentationRequest:
    sample_id: str
    original_sample_id: str
    source_group_id: str
    label: str
    split: str
    augmentation_type: str
    parameters: Mapping[str, object]
    seed: int
    experiment: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class MinorityPlan:
    median_count: int
    original_counts: Mapping[str, int]
    targets: Mapping[str, int]
    requested_additions: Mapping[str, int]
    actual_additions: Mapping[str, int]
    final_requested_counts: Mapping[str, int]
    requests: tuple[AugmentationRequest, ...]


@dataclass(frozen=True)
class TransformEligibility:
    augmentation_type: str
    enabled: bool
    comparable_samples: int
    maximum_observed_delta: float | None
    failed_metrics: tuple[str, ...]
    reason: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _hash_number(*values: object) -> int:
    text = '|'.join(str(value) for value in values)
    return int.from_bytes(sha256(text.encode('utf-8')).digest(), 'big')


def _validate_enabled(enabled: Sequence[str]) -> tuple[str, ...]:
    ordered = tuple(kind for kind in SAFE_KINDS if kind in set(enabled))
    unknown = sorted(set(enabled) - set(SAFE_KINDS))
    if unknown:
        raise ValueError(f'non-SAFE transform cannot be auto-enabled: {unknown[0]}')
    if not ordered:
        raise ValueError('at least one SAFE transform must be enabled')
    return ordered


def _request(
    row: Mapping[str, object], kind: str, seed: int, experiment: str
) -> AugmentationRequest:
    if str(row.get('split')) != 'train':
        raise ValueError('augmentation requests require selected train rows')
    original_id = str(row['original_sample_id'])
    parameters = dict(_SAFE_PARAMETERS[kind])
    return AugmentationRequest(
        sample_id=derived_sample_id(original_id, kind, parameters, seed),
        original_sample_id=original_id,
        source_group_id=str(row.get('source_group_id', '')),
        label=str(row['label']),
        split='train',
        augmentation_type=kind,
        parameters=parameters,
        seed=seed,
        experiment=experiment,
    )


def build_transform_plan(
    rows: Iterable[Mapping[str, object]],
    config: AugmentationConfig,
    enabled: Sequence[str],
    *,
    seed: int,
) -> tuple[AugmentationRequest, ...]:
    kinds = _validate_enabled(enabled)
    materialized = sorted(
        (dict(row) for row in rows), key=lambda row: str(row['original_sample_id'])
    )
    if config.maximum_derivatives_b < 1:
        return ()
    requests = []
    for row in materialized:
        if str(row.get('split')) != 'train':
            raise ValueError('augmentation requests require selected train rows')
        index = _hash_number(seed, row['original_sample_id'], 'B') % len(kinds)
        requests.append(_request(row, kinds[index], seed, 'B'))
    return tuple(requests)


def build_minority_plan(
    rows: Iterable[Mapping[str, object]],
    config: AugmentationConfig,
    enabled: Sequence[str],
    *,
    seed: int,
) -> MinorityPlan:
    kinds = _validate_enabled(enabled)
    materialized = sorted(
        (dict(row) for row in rows), key=lambda row: str(row['original_sample_id'])
    )
    if any(str(row.get('split')) != 'train' for row in materialized):
        raise ValueError('minority augmentation requires selected train rows')
    counts = Counter(str(row['label']) for row in materialized)
    median_count = int(statistics.median(counts.values())) if counts else 0
    targets = {
        label: max(count, median_count) for label, count in sorted(counts.items())
    }
    requested = {
        label: max(median_count - count, 0)
        for label, count in sorted(counts.items())
    }
    by_label: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in materialized:
        by_label[str(row['label'])].append(row)

    requests: list[AugmentationRequest] = []
    actual: dict[str, int] = {}
    for label in sorted(counts):
        deficit = requested[label]
        selected = by_label[label]
        per_original_capacity = min(config.maximum_derivatives_c, len(kinds))
        capacity = len(selected) * per_original_capacity
        addition_count = min(deficit, capacity)
        actual[label] = addition_count
        ranked = sorted(
            selected,
            key=lambda row: (
                _hash_number(seed, row['original_sample_id'], label, 'C'),
                str(row['original_sample_id']),
            ),
        )
        for addition_index in range(addition_count):
            row = ranked[addition_index % len(ranked)]
            derivative_index = addition_index // len(ranked)
            kind_base = _hash_number(
                seed,
                row['original_sample_id'],
                label,
                'C',
            )
            kind_index = (kind_base + derivative_index) % len(kinds)
            requests.append(_request(row, kinds[kind_index], seed, 'C'))

    final_counts = {
        label: counts[label] + actual[label] for label in sorted(counts)
    }
    return MinorityPlan(
        median_count=median_count,
        original_counts=dict(sorted(counts.items())),
        targets=targets,
        requested_additions=requested,
        actual_additions=actual,
        final_requested_counts=final_counts,
        requests=tuple(requests),
    )


def apply_safe_transform(
    frame: np.ndarray,
    kind: str,
    parameters: Mapping[str, object],
    rng: np.random.Generator,
) -> np.ndarray:
    if kind not in SAFE_KINDS:
        raise ValueError(f'transform is not SAFE: {kind}')
    source = np.asarray(frame)
    if source.dtype != np.uint8:
        raise ValueError('SAFE augmentation expects uint8 frames')
    work = source.astype(np.float32)
    if kind == 'brightness':
        work *= float(parameters['factor'])
    elif kind == 'contrast':
        work = (work - 127.5) * float(parameters['factor']) + 127.5
    elif kind == 'gamma':
        gamma = float(parameters['gamma'])
        work = np.power(work / 255.0, gamma) * 255.0
    elif kind == 'gaussian_blur':
        kernel = tuple(int(value) for value in parameters['kernel'])
        work = cv2.GaussianBlur(work, kernel, float(parameters['sigma']))
    elif kind == 'sensor_noise':
        work += rng.normal(
            float(parameters['mean']), float(parameters['sigma']), work.shape
        ).astype(np.float32)
    return np.clip(np.rint(work), 0, 255).astype(np.uint8)


def transform_rng(request: AugmentationRequest) -> np.random.Generator:
    value = _hash_number(request.seed, request.sample_id) % (2**63 - 1)
    return np.random.default_rng(value)


def evaluate_transform_eligibility(
    original_stats: Mapping[str, float | int],
    transformed_stats: Mapping[str, Mapping[str, float | int]],
    config: AugmentationConfig,
) -> dict[str, TransformEligibility]:
    rate_names = (
        'vector_not_ready_rate',
        'face_failure_rate',
        'pose_failure_rate',
        'calibration_failure_rate',
    )
    results: dict[str, TransformEligibility] = {}
    for kind in SAFE_KINDS:
        stats = transformed_stats.get(kind, {})
        comparable = int(stats.get('comparable_samples', 0))
        if comparable < config.pilot_minimum_samples:
            results[kind] = TransformEligibility(
                kind,
                False,
                comparable,
                None,
                (),
                'insufficient_pilot_support',
            )
            continue
        deltas = {
            name: float(stats.get(name, 0.0))
            - float(original_stats.get(name, 0.0))
            for name in rate_names
        }
        failed = tuple(
            name
            for name in rate_names
            if deltas[name] > config.maximum_failure_rate_delta
        )
        results[kind] = TransformEligibility(
            kind,
            not failed,
            comparable,
            max(deltas.values()),
            failed,
            'failure_rate_increase' if failed else 'eligible',
        )
    return results
