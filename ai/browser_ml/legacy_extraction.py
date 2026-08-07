from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

from .contracts import CONTRACT_RELATIVE_PATH, load_feature_contract
from .legacy_sources import LegacyLabel, sha256_file


EXTRACTOR_VERSION = "legacy-v2-extractor-1"


@dataclass(frozen=True)
class CacheIdentity:
    source_sha256: str
    contract_sha256: str
    face_model_sha256: str
    pose_model_sha256: str
    extractor_version: str
    sampling_fps: int
    camera_half: str


@dataclass(frozen=True)
class FrontCropDecision:
    role: str
    half: str | None
    confident: bool
    left_face_score: float
    right_face_score: float
    reason: str


@dataclass(frozen=True)
class ExtractionRequest:
    source_path: Path
    labels: tuple[LegacyLabel, ...]
    cache_dir: Path
    project_root: Path
    face_model_path: Path
    pose_model_path: Path
    camera_layout: str = "merged"
    sampling_fps: int = 1


@dataclass(frozen=True)
class ExtractionResult:
    source_path: Path
    source_sha256: str
    rows: tuple[dict[str, str], ...]
    cache_csv: Path
    cache_metadata: Path
    reused: bool
    camera_decision: FrontCropDecision
    requested_sample_count: int
    decoded_sample_count: int
    error_count: int


def cache_key(identity: CacheIdentity) -> str:
    payload = json.dumps(asdict(identity), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def choose_front_half(
    *,
    left_face_score: float,
    right_face_score: float,
    minimum_score: float = 0.75,
    minimum_ratio: float = 1.5,
    minimum_margin: float = 0.5,
) -> FrontCropDecision:
    if not math.isfinite(left_face_score) or not math.isfinite(right_face_score):
        return FrontCropDecision(
            "front", None, False, left_face_score, right_face_score, "non_finite_face_evidence"
        )
    strongest = max(left_face_score, right_face_score)
    weakest = min(left_face_score, right_face_score)
    ratio = strongest / max(weakest, 1e-9)
    margin = strongest - weakest
    if strongest < minimum_score:
        return FrontCropDecision(
            "front", None, False, left_face_score, right_face_score, "insufficient_face_evidence"
        )
    if ratio < minimum_ratio or margin < minimum_margin:
        return FrontCropDecision(
            "front", None, False, left_face_score, right_face_score, "ambiguous_face_evidence"
        )
    half = "left" if left_face_score > right_face_score else "right"
    return FrontCropDecision(
        "front", half, True, left_face_score, right_face_score, "stronger_face_evidence"
    )


def requested_seconds(
    labels: Iterable[Any],
    *,
    duration_sec: float,
    sampling_fps: int = 1,
) -> frozenset[int]:
    if sampling_fps != 1:
        raise ValueError("legacy browser parity extraction currently requires sampling_fps=1")
    if not math.isfinite(duration_sec) or duration_sec <= 0:
        return frozenset()
    latest_ms = -1
    for label in labels:
        if not bool(getattr(label, "eligible", False)):
            continue
        timestamp_ms = getattr(label, "timestamp_ms", None)
        end_ms = getattr(label, "end_ms", None)
        if timestamp_ms is not None:
            latest_ms = max(latest_ms, int(timestamp_ms))
        if end_ms is not None:
            latest_ms = max(latest_ms, int(end_ms) - 1)
    if latest_ms < 0:
        return frozenset()
    last_source_second = max(0, int(math.ceil(duration_sec)) - 1)
    last_label_second = int(math.floor(latest_ms / 1000))
    last_second = min(last_source_second, last_label_second)
    return frozenset(range(0, last_second + 1))


class BrowserFeatureStream:
    def __init__(self, project_root: Path):
        frontend = project_root.resolve() / "frontend"
        command = [
            "node",
            str(frontend / "node_modules" / "vite-node" / "vite-node.mjs"),
            "--script",
            str(frontend / "scripts" / "focus-v2-feature-stream.ts"),
        ]
        self._process = subprocess.Popen(
            command,
            cwd=frontend,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )

    def _request(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self._process.stdin is None or self._process.stdout is None:
            raise RuntimeError("browser feature stream pipes are unavailable")
        self._process.stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
        self._process.stdin.flush()
        line = self._process.stdout.readline()
        if not line:
            stderr = self._process.stderr.read() if self._process.stderr else ""
            raise RuntimeError(f"browser feature stream exited unexpectedly: {stderr.strip()}")
        response = json.loads(line)
        if not response.get("ok"):
            raise RuntimeError(f"browser feature stream rejected sample: {response.get('error')}")
        result = response.get("result")
        if not isinstance(result, dict):
            raise RuntimeError("browser feature stream returned a non-object result")
        return result

    def describe(self) -> dict[str, Any]:
        return self._request({"command": "describe"})

    def process(self, sample: dict[str, Any]) -> dict[str, Any]:
        return self._request(sample)

    def close(self) -> None:
        if self._process.stdin:
            self._process.stdin.close()
        try:
            return_code = self._process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self._process.terminate()
            return_code = self._process.wait(timeout=5)
        if return_code != 0:
            stderr = self._process.stderr.read() if self._process.stderr else ""
            raise RuntimeError(f"browser feature stream failed with {return_code}: {stderr.strip()}")

    def __enter__(self) -> "BrowserFeatureStream":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()


def _sparse_landmarks(landmarks: Sequence[Any], indices: Sequence[int]) -> dict[str, dict[str, float]]:
    sparse: dict[str, dict[str, float]] = {}
    for index in indices:
        if index >= len(landmarks):
            continue
        point = landmarks[index]
        values = {"x": float(point.x), "y": float(point.y)}
        for optional in ("z", "visibility", "presence"):
            value = getattr(point, optional, None)
            if value is not None and math.isfinite(float(value)):
                values[optional] = float(value)
        sparse[str(index)] = values
    return sparse


def _crop_half(frame: Any, half: str) -> Any:
    split_x = frame.shape[1] // 2
    return frame[:, :split_x] if half == "left" else frame[:, split_x:]


def _face_result_score(result: Any) -> float:
    groups = getattr(result, "face_landmarks", None) or []
    if not groups:
        return 0.0
    points = groups[0]
    xs = [float(point.x) for point in points if math.isfinite(float(point.x))]
    ys = [float(point.y) for point in points if math.isfinite(float(point.y))]
    if not xs or not ys:
        return 0.0
    area = max(0.0, (max(xs) - min(xs)) * (max(ys) - min(ys)))
    return 1.0 + min(area, 1.0) * 10.0


def _camera_probe_seconds(seconds: Sequence[int], maximum_samples: int = 12) -> tuple[int, ...]:
    if len(seconds) <= maximum_samples:
        return tuple(seconds)
    last_index = len(seconds) - 1
    indices = sorted({round(step * last_index / (maximum_samples - 1)) for step in range(maximum_samples)})
    return tuple(seconds[index] for index in indices)


def _verify_merged_front_half(
    source_path: Path,
    seconds: Sequence[int],
    face_model_path: Path,
) -> FrontCropDecision:
    import cv2
    import mediapipe as mp

    from ai.focus_ai.analyze import _create_face_landmarker

    left_detector = _create_face_landmarker(str(face_model_path), 0.5)
    right_detector = _create_face_landmarker(str(face_model_path), 0.5)
    capture = cv2.VideoCapture(str(source_path))
    left_score = 0.0
    right_score = 0.0
    try:
        for second in _camera_probe_seconds(seconds):
            capture.set(cv2.CAP_PROP_POS_MSEC, second * 1000)
            ok, frame = capture.read()
            if not ok or frame is None or frame.shape[1] < 2:
                continue
            timestamp_ms = second * 1000
            left_rgb = cv2.cvtColor(_crop_half(frame, "left"), cv2.COLOR_BGR2RGB)
            right_rgb = cv2.cvtColor(_crop_half(frame, "right"), cv2.COLOR_BGR2RGB)
            left_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=left_rgb)
            right_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=right_rgb)
            left_score += _face_result_score(left_detector.detect_for_video(left_image, timestamp_ms))
            right_score += _face_result_score(right_detector.detect_for_video(right_image, timestamp_ms))
    finally:
        capture.release()
        left_detector.close()
        right_detector.close()
    return choose_front_half(left_face_score=left_score, right_face_score=right_score)


def _read_cache(csv_path: Path) -> tuple[dict[str, str], ...]:
    with csv_path.open("r", newline="", encoding="utf-8-sig") as file:
        return tuple(dict(row) for row in csv.DictReader(file))


def _write_new_cache(
    *,
    csv_path: Path,
    metadata_path: Path,
    rows: Sequence[dict[str, Any]],
    fieldnames: Sequence[str],
    metadata: dict[str, Any],
) -> None:
    if csv_path.exists() or metadata_path.exists():
        raise FileExistsError(f"refusing to overwrite feature cache: {csv_path}")
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    csv_temp = csv_path.with_name(f"{csv_path.name}.{os.getpid()}.tmp")
    metadata_temp = metadata_path.with_name(f"{metadata_path.name}.{os.getpid()}.tmp")
    try:
        with csv_temp.open("w", newline="", encoding="utf-8-sig") as file:
            writer = csv.DictWriter(file, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        metadata_temp.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(csv_temp, csv_path)
        os.replace(metadata_temp, metadata_path)
    finally:
        csv_temp.unlink(missing_ok=True)
        metadata_temp.unlink(missing_ok=True)


def extract_source_features(request: ExtractionRequest) -> ExtractionResult:
    if request.sampling_fps != 1:
        raise ValueError("Browser v2 production currently samples at exactly 1 FPS")
    source = request.source_path.resolve()
    source_hash = sha256_file(source)
    contract_path = request.project_root.resolve() / CONTRACT_RELATIVE_PATH
    contract = load_feature_contract(request.project_root)

    import cv2

    metadata_capture = cv2.VideoCapture(str(source))
    try:
        fps = float(metadata_capture.get(cv2.CAP_PROP_FPS))
        frame_count = float(metadata_capture.get(cv2.CAP_PROP_FRAME_COUNT))
    finally:
        metadata_capture.release()
    if fps <= 0 or frame_count <= 0:
        raise ValueError(f"video has invalid FPS/frame count: {source}")
    duration_sec = frame_count / fps
    seconds = sorted(requested_seconds(request.labels, duration_sec=duration_sec))
    if not seconds:
        raise ValueError(f"source has no eligible labeled timestamps: {source}")

    if request.camera_layout == "merged":
        decision = _verify_merged_front_half(source, seconds, request.face_model_path)
        if not decision.confident or decision.half is None:
            raise ValueError(f"merged camera role is ambiguous: {decision.reason}")
    elif request.camera_layout == "front":
        decision = FrontCropDecision("front", "full", True, 0.0, 0.0, "manifest_front_role")
    else:
        raise ValueError(f"unsupported camera layout: {request.camera_layout}")

    identity = CacheIdentity(
        source_sha256=source_hash,
        contract_sha256=sha256_file(contract_path),
        face_model_sha256=sha256_file(request.face_model_path),
        pose_model_sha256=sha256_file(request.pose_model_path),
        extractor_version=EXTRACTOR_VERSION,
        sampling_fps=request.sampling_fps,
        camera_half=decision.half,
    )
    key = cache_key(identity)
    csv_path = request.cache_dir.resolve() / f"{key}.csv"
    metadata_path = request.cache_dir.resolve() / f"{key}.metadata.json"
    if csv_path.exists() and metadata_path.exists():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if metadata.get("identity") != asdict(identity):
            raise ValueError(f"cache identity mismatch: {metadata_path}")
        rows = _read_cache(csv_path)
        return ExtractionResult(
            source, source_hash, rows, csv_path, metadata_path, True, decision,
            len(seconds), int(metadata.get("decoded_sample_count", len(rows))),
            int(metadata.get("error_count", 0)),
        )
    if csv_path.exists() or metadata_path.exists():
        raise FileExistsError(f"partial cache collision: {csv_path}")

    import mediapipe as mp

    from ai.focus_ai.analyze import _create_face_landmarker, _create_pose_landmarker

    capture = cv2.VideoCapture(str(source))
    face_detector = _create_face_landmarker(str(request.face_model_path), 0.5)
    pose_detector = _create_pose_landmarker(str(request.pose_model_path))
    output_rows: list[dict[str, Any]] = []
    decoded_count = 0
    error_count = 0
    try:
        with BrowserFeatureStream(request.project_root) as stream:
            description = stream.describe()
            if tuple(description.get("feature_names", ())) != contract.feature_names:
                raise ValueError("browser feature stream contract order mismatch")
            face_indices = tuple(int(value) for value in description["face_landmark_indices"])
            pose_indices = tuple(int(value) for value in description["pose_landmark_indices"])
            for second in seconds:
                timestamp_ms = second * 1000
                capture.set(cv2.CAP_PROP_POS_MSEC, timestamp_ms)
                ok, frame = capture.read()
                if not ok or frame is None:
                    error_count += 1
                    continue
                decoded_count += 1
                front_frame = frame if decision.half == "full" else _crop_half(frame, decision.half)
                rgb = cv2.cvtColor(front_frame, cv2.COLOR_BGR2RGB)
                image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                face_result = face_detector.detect_for_video(image, timestamp_ms)
                pose_result = pose_detector.detect_for_video(image, timestamp_ms)
                face_groups = getattr(face_result, "face_landmarks", None) or []
                pose_groups = getattr(pose_result, "pose_landmarks", None) or []
                response = stream.process(
                    {
                        "timestamp_ms": timestamp_ms,
                        "face_landmarks": _sparse_landmarks(face_groups[0], face_indices) if face_groups else None,
                        "pose_landmarks": _sparse_landmarks(pose_groups[0], pose_indices) if pose_groups else None,
                    }
                )
                values = response.get("values") or {}
                output_rows.append(
                    {
                        "timestamp_ms": timestamp_ms,
                        **{name: values.get(name) for name in contract.feature_names},
                        "missing_features": "|".join(response.get("missingFeatures") or ()),
                        "vector_ready": response.get("vector") is not None,
                    }
                )
    finally:
        capture.release()
        face_detector.close()
        pose_detector.close()

    fieldnames = ["timestamp_ms", *contract.feature_names, "missing_features", "vector_ready"]
    cache_metadata = {
        "identity": asdict(identity),
        "source_path": str(source),
        "schema_version": contract.schema_version,
        "feature_names": list(contract.feature_names),
        "camera_decision": asdict(decision),
        "requested_sample_count": len(seconds),
        "decoded_sample_count": decoded_count,
        "error_count": error_count,
    }
    _write_new_cache(
        csv_path=csv_path,
        metadata_path=metadata_path,
        rows=output_rows,
        fieldnames=fieldnames,
        metadata=cache_metadata,
    )
    return ExtractionResult(
        source,
        source_hash,
        tuple({name: str(value) if value is not None else "" for name, value in row.items()} for row in output_rows),
        csv_path,
        metadata_path,
        False,
        decision,
        len(seconds),
        decoded_count,
        error_count,
    )
