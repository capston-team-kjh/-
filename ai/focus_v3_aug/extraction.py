"""Stateful MediaPipe/browser-v2 re-extraction for SAFE augmented streams."""

from dataclasses import asdict, dataclass, replace
from hashlib import sha256
import math
from pathlib import Path
from typing import Iterable, Mapping, Protocol, Sequence

import numpy as np

from ai.browser_ml.legacy_extraction import (
    BrowserFeatureStream,
    _crop_half,
    _sparse_landmarks,
)

from .augmentation import SAFE_KINDS, apply_safe_transform
from .config import canonical_json_bytes
from .failure_analysis import REASON_PRECEDENCE


@dataclass(frozen=True)
class StreamExtractionRequest:
    project_root: Path
    source_path: Path
    source_sha256: str
    source_group_id: str
    split: str
    camera_half: str
    timeline_ms: tuple[int, ...]
    retain_timestamps_ms: tuple[int, ...]
    feature_names: tuple[str, ...]
    augmentation_type: str
    augmentation_parameters: Mapping[str, object]
    seed: int


@dataclass(frozen=True)
class StreamExtractionResult:
    processed_timestamps_ms: tuple[int, ...]
    accepted_rows: tuple[dict[str, object], ...]
    rejected_rows: tuple[dict[str, object], ...]
    timeline_rows: tuple[dict[str, object], ...]


@dataclass(frozen=True)
class ParityReport:
    passed: bool
    abs_tol: float
    rel_tol: float
    maximum_absolute_error: float
    maximum_relative_error: float
    maximum_absolute_feature: str | None
    maximum_absolute_timestamp_ms: int | None
    maximum_relative_feature: str | None
    maximum_relative_timestamp_ms: int | None
    readiness_mismatches: tuple[int, ...]
    missing_timestamps: tuple[int, ...]

    def as_dict(self) -> dict[str, object]:
        value = asdict(self)
        value['readiness_mismatches'] = list(self.readiness_mismatches)
        value['missing_timestamps'] = list(self.missing_timestamps)
        return value


class TimelineDependencies(Protocol):
    def process_timeline(
        self, request: StreamExtractionRequest
    ) -> Sequence[Mapping[str, object]]: ...


_AUGMENTATION_REJECTION_PRECEDENCE = (
    *REASON_PRECEDENCE,
    'excessive_landmark_loss',
    'feature_count_mismatch',
    'feature_schema_order_mismatch',
    'vector_not_ready',
)


def _validate_request(request: StreamExtractionRequest) -> None:
    if request.split != 'train':
        raise ValueError('augmentation/parity streams require selected train rows')
    if not request.timeline_ms:
        raise ValueError('selected train stream timeline is empty')
    expected = tuple(range(0, max(request.timeline_ms) + 1, 1000))
    if request.timeline_ms != expected:
        raise ValueError('selected train stream must cover every second from zero')
    if not set(request.retain_timestamps_ms).issubset(request.timeline_ms):
        raise ValueError('retained timestamps must belong to the full timeline')
    if len(request.feature_names) != 34:
        raise ValueError('focus-state-v2 requires exactly 34 features')


def _feature_tuple(
    row: Mapping[str, object], feature_names: Sequence[str]
) -> tuple[object, ...]:
    if 'features' in row:
        return tuple(row['features'])
    values = row.get('values')
    if isinstance(values, Mapping):
        return tuple(values.get(name) for name in feature_names)
    return tuple(row.get(name) for name in feature_names)


def _finite(value: object) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _as_bool(value: object) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {'1', 'true', 'yes'}
    return bool(value)


def _missing(value: object) -> bool:
    return value is None or value == ''


def _rejection_reasons(
    row: Mapping[str, object],
    features: Sequence[object],
    request: StreamExtractionRequest,
) -> tuple[str, ...]:
    reasons: set[str] = set()
    if bool(row.get('decode_error')):
        reasons.add('frame_decode_failure')
    if row.get('face_detected') is False:
        reasons.add('face_detection_failure')
    if row.get('pose_detected') is False:
        reasons.add('pose_detection_failure')
    missing_names = [
        request.feature_names[index]
        for index, value in enumerate(features[: len(request.feature_names)])
        if value is None or value == ''
    ]
    non_finite_names = [
        request.feature_names[index]
        for index, value in enumerate(features[: len(request.feature_names)])
        if value is not None and value != '' and not _finite(value)
    ]
    if missing_names:
        reasons.add('required_feature_missing')
    if non_finite_names:
        reasons.add('non_finite_feature')
    temporal_names = [
        name
        for name in (*missing_names, *non_finite_names)
        if 'rolling' in name or 'slope' in name or 'continuous_eye_closed' in name
    ]
    if temporal_names or row.get('temporal_ready') is False:
        reasons.add('temporal_history_insufficient')
    if 'calibration_valid' in request.feature_names:
        index = request.feature_names.index('calibration_valid')
        if index < len(features):
            value = features[index]
            if _finite(value) and float(value) <= 0.0:
                reasons.add('calibration_not_ready')
    if row.get('calibration_ready') is False:
        reasons.add('calibration_not_ready')
    if row.get('excessive_landmark_loss') is True:
        reasons.add('excessive_landmark_loss')
    if len(features) != len(request.feature_names):
        reasons.add('feature_count_mismatch')
    declared_order = row.get('feature_names')
    if declared_order is not None and tuple(declared_order) != request.feature_names:
        reasons.add('feature_schema_order_mismatch')
    if row.get('vector_ready') is not True:
        reasons.add('vector_not_ready')
    return tuple(
        reason for reason in _AUGMENTATION_REJECTION_PRECEDENCE if reason in reasons
    )


def extract_augmented_stream(
    request: StreamExtractionRequest,
    *,
    dependencies: TimelineDependencies,
) -> StreamExtractionResult:
    _validate_request(request)
    timeline_rows = [dict(row) for row in dependencies.process_timeline(request)]
    timestamps = tuple(int(row['timestamp_ms']) for row in timeline_rows)
    if timestamps != request.timeline_ms:
        raise ValueError('stream did not return the complete ordered timeline')

    retained = set(request.retain_timestamps_ms)
    accepted: list[dict[str, object]] = []
    rejected: list[dict[str, object]] = []
    normalized_timeline: list[dict[str, object]] = []
    for row in timeline_rows:
        features = _feature_tuple(row, request.feature_names)
        normalized = {
            **row,
            'features': features,
            'feature_names': request.feature_names,
        }
        normalized_timeline.append(normalized)
        timestamp_ms = int(row['timestamp_ms'])
        if timestamp_ms not in retained:
            continue
        reasons = _rejection_reasons(row, features, request)
        lineage = {
            'source_sha256': request.source_sha256,
            'source_group_id': request.source_group_id,
            'timestamp_ms': timestamp_ms,
            'split': request.split,
            'augmentation_type': request.augmentation_type,
            'parameters': dict(request.augmentation_parameters),
            'seed': request.seed,
        }
        if reasons:
            rejected.append(
                {
                    **lineage,
                    'primary_reason': reasons[0],
                    'additional_reasons': list(reasons[1:]),
                    'available_features': list(features),
                }
            )
        else:
            accepted.append({**lineage, 'features': features})
    return StreamExtractionResult(
        processed_timestamps_ms=timestamps,
        accepted_rows=tuple(accepted),
        rejected_rows=tuple(rejected),
        timeline_rows=tuple(normalized_timeline),
    )


def _rows_by_timestamp(
    rows: Iterable[Mapping[str, object]],
) -> dict[int, Mapping[str, object]]:
    return {int(row['timestamp_ms']): row for row in rows}


def compare_parity_rows(
    original_rows: Iterable[Mapping[str, object]],
    candidate_rows: Iterable[Mapping[str, object]],
    feature_names: Sequence[str],
    *,
    abs_tol: float,
    rel_tol: float,
) -> ParityReport:
    original = _rows_by_timestamp(original_rows)
    candidate = _rows_by_timestamp(candidate_rows)
    missing = tuple(sorted(set(original) ^ set(candidate)))
    readiness_mismatches: list[int] = []
    maximum_absolute = 0.0
    maximum_relative = 0.0
    maximum_absolute_feature: str | None = None
    maximum_relative_feature: str | None = None
    maximum_absolute_timestamp: int | None = None
    maximum_relative_timestamp: int | None = None
    close = not missing
    for timestamp in sorted(set(original) & set(candidate)):
        original_ready = _as_bool(original[timestamp].get('vector_ready'))
        candidate_ready = _as_bool(candidate[timestamp].get('vector_ready'))
        if original_ready != candidate_ready:
            readiness_mismatches.append(timestamp)
            close = False
        original_features = _feature_tuple(original[timestamp], feature_names)
        candidate_features = _feature_tuple(candidate[timestamp], feature_names)
        if len(original_features) != len(feature_names) or len(candidate_features) != len(
            feature_names
        ):
            close = False
            continue
        for name, before, after in zip(
            feature_names, original_features, candidate_features
        ):
            if not _finite(before) or not _finite(after):
                if not (_missing(before) and _missing(after)) and str(
                    before
                ).lower() != str(after).lower():
                    close = False
                continue
            before_value = float(before)
            after_value = float(after)
            absolute = abs(after_value - before_value)
            relative = absolute / max(abs(before_value), np.finfo(np.float64).tiny)
            if absolute > maximum_absolute:
                maximum_absolute = absolute
                maximum_absolute_feature = str(name)
                maximum_absolute_timestamp = timestamp
            if relative > maximum_relative:
                maximum_relative = relative
                maximum_relative_feature = str(name)
                maximum_relative_timestamp = timestamp
            if not math.isclose(
                before_value, after_value, rel_tol=rel_tol, abs_tol=abs_tol
            ):
                close = False
    return ParityReport(
        passed=close and not readiness_mismatches,
        abs_tol=abs_tol,
        rel_tol=rel_tol,
        maximum_absolute_error=maximum_absolute,
        maximum_relative_error=maximum_relative,
        maximum_absolute_feature=maximum_absolute_feature,
        maximum_absolute_timestamp_ms=maximum_absolute_timestamp,
        maximum_relative_feature=maximum_relative_feature,
        maximum_relative_timestamp_ms=maximum_relative_timestamp,
        readiness_mismatches=tuple(readiness_mismatches),
        missing_timestamps=missing,
    )


class MediaPipeStreamDependencies:
    """Concrete adapter that reuses the current detector and browser stream."""

    def __init__(self, face_model_path: Path, pose_model_path: Path):
        self.face_model_path = Path(face_model_path).resolve()
        self.pose_model_path = Path(pose_model_path).resolve()

    @staticmethod
    def _rng(request: StreamExtractionRequest, timestamp_ms: int) -> np.random.Generator:
        identity = {
            'source_sha256': request.source_sha256,
            'augmentation_type': request.augmentation_type,
            'parameters': dict(request.augmentation_parameters),
            'seed': request.seed,
            'timestamp_ms': timestamp_ms,
        }
        seed = int.from_bytes(sha256(canonical_json_bytes(identity)).digest()[:8], 'big')
        return np.random.default_rng(seed)

    def process_timeline(
        self, request: StreamExtractionRequest
    ) -> Sequence[Mapping[str, object]]:
        import cv2
        import mediapipe as mp

        from ai.focus_ai.analyze import _create_face_landmarker, _create_pose_landmarker

        if request.camera_half not in {'full', 'left', 'right'}:
            raise ValueError(f'unsupported camera half: {request.camera_half}')
        if request.augmentation_type not in {*SAFE_KINDS, 'no_transform'}:
            raise ValueError(
                f'unsupported stream transform: {request.augmentation_type}'
            )
        capture = cv2.VideoCapture(str(request.source_path.resolve()))
        face_detector = _create_face_landmarker(str(self.face_model_path), 0.5)
        pose_detector = _create_pose_landmarker(str(self.pose_model_path))
        output: list[dict[str, object]] = []
        try:
            with BrowserFeatureStream(request.project_root) as stream:
                description = stream.describe()
                if tuple(description.get('feature_names', ())) != request.feature_names:
                    raise ValueError('focus-state-v2 feature order mismatch')
                face_indices = tuple(
                    int(value) for value in description['face_landmark_indices']
                )
                pose_indices = tuple(
                    int(value) for value in description['pose_landmark_indices']
                )
                for timestamp_ms in request.timeline_ms:
                    capture.set(cv2.CAP_PROP_POS_MSEC, timestamp_ms)
                    ok, frame = capture.read()
                    if not ok or frame is None:
                        output.append(
                            {
                                'timestamp_ms': timestamp_ms,
                                'features': (None,) * len(request.feature_names),
                                'vector_ready': False,
                                'decode_error': True,
                                'face_detected': False,
                                'pose_detected': False,
                            }
                        )
                        continue
                    if request.augmentation_type != 'no_transform':
                        frame = apply_safe_transform(
                            frame,
                            request.augmentation_type,
                            request.augmentation_parameters,
                            self._rng(request, timestamp_ms),
                        )
                    front = (
                        frame
                        if request.camera_half == 'full'
                        else _crop_half(frame, request.camera_half)
                    )
                    rgb = cv2.cvtColor(front, cv2.COLOR_BGR2RGB)
                    image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                    face_result = face_detector.detect_for_video(image, timestamp_ms)
                    pose_result = pose_detector.detect_for_video(image, timestamp_ms)
                    face_groups = getattr(face_result, 'face_landmarks', None) or []
                    pose_groups = getattr(pose_result, 'pose_landmarks', None) or []
                    response = stream.process(
                        {
                            'timestamp_ms': timestamp_ms,
                            'face_landmarks': _sparse_landmarks(
                                face_groups[0], face_indices
                            )
                            if face_groups
                            else None,
                            'pose_landmarks': _sparse_landmarks(
                                pose_groups[0], pose_indices
                            )
                            if pose_groups
                            else None,
                        }
                    )
                    values = response.get('values') or {}
                    output.append(
                        {
                            'timestamp_ms': timestamp_ms,
                            'features': tuple(
                                values.get(name) for name in request.feature_names
                            ),
                            'feature_names': request.feature_names,
                            'missing_features': tuple(
                                response.get('missingFeatures') or ()
                            ),
                            'vector_ready': response.get('vector') is not None,
                            'face_detected': bool(face_groups),
                            'pose_detected': bool(pose_groups),
                        }
                    )
        finally:
            capture.release()
            face_detector.close()
            pose_detector.close()
        return output


def run_selected_train_parity(
    request: StreamExtractionRequest,
    original_rows: Iterable[Mapping[str, object]],
    *,
    dependencies: TimelineDependencies,
    abs_tol: float,
    rel_tol: float,
) -> ParityReport:
    no_transform = replace(
        request, augmentation_type='no_transform', augmentation_parameters={}
    )
    candidate = extract_augmented_stream(
        no_transform, dependencies=dependencies
    ).timeline_rows
    return compare_parity_rows(
        original_rows,
        candidate,
        request.feature_names,
        abs_tol=abs_tol,
        rel_tol=rel_tol,
    )
