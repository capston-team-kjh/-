from __future__ import annotations

import contextlib
import shutil
import statistics
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Optional

import cv2


MIN_DECODE_COVERAGE = 0.99
EARLY_EOF_TOLERANCE_SEC = 2.0
RECOVERY_SEEK_STEP_SEC = 1.0
RECOVERY_MAX_SEEK_SEC = 60.0


class VideoPreflightError(RuntimeError):
    def __init__(self, reason: str, details: dict[str, Any]) -> None:
        super().__init__(reason)
        self.reason = reason
        self.details = details


@dataclass
class PreparedVideo:
    source_path: Path
    analysis_path: Path
    validation: dict[str, Any]
    warnings: list[str]
    decoded_timing: dict[str, Any]


def _decoded_timing_from_scan(scan: dict[str, Any]) -> dict[str, Any]:
    """Adapt a completed preflight scan for merged-video timing reuse."""
    first_timestamp_sec = scan.get("first_timestamp_sec")
    last_timestamp_sec = scan.get("last_timestamp_sec")
    return {
        "decoded_frame_count": int(scan.get("decoded_frames") or 0),
        "effective_fps": float(scan.get("effective_fps") or 0.0),
        "first_timestamp_ms": (
            float(first_timestamp_sec) * 1000.0
            if first_timestamp_sec is not None
            else None
        ),
        "last_timestamp_ms": (
            float(last_timestamp_sec) * 1000.0
            if last_timestamp_sec is not None
            else None
        ),
    }


def _probe_video(path: Path) -> dict[str, Any]:
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        capture.release()
        raise VideoPreflightError(
            "VIDEO_OPEN_FAIL",
            {"video_path": str(path)},
        )

    fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
    frame_count = float(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0)
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    capture.release()

    if fps <= 0 or frame_count <= 0 or width <= 0 or height <= 0:
        raise VideoPreflightError(
            "VIDEO_META_INVALID",
            {
                "video_path": str(path),
                "reported_fps": fps,
                "reported_frame_count": frame_count,
                "width": width,
                "height": height,
            },
        )

    return {
        "reported_fps": fps,
        "reported_frame_count": frame_count,
        "duration_sec": frame_count / fps,
        "width": width,
        "height": height,
    }


def _recover_after_decode_failure(
    capture: cv2.VideoCapture,
    last_timestamp_sec: float,
    expected_duration_sec: float,
) -> tuple[bool, Optional[float]]:
    max_target = min(
        expected_duration_sec,
        last_timestamp_sec + RECOVERY_MAX_SEEK_SEC,
    )
    target = last_timestamp_sec + RECOVERY_SEEK_STEP_SEC

    while target < max_target:
        capture.set(cv2.CAP_PROP_POS_MSEC, target * 1000.0)
        recovered, _ = capture.read()
        if recovered:
            timestamp_sec = float(capture.get(cv2.CAP_PROP_POS_MSEC) or 0.0) / 1000.0
            if timestamp_sec > last_timestamp_sec:
                return True, timestamp_sec
        target += RECOVERY_SEEK_STEP_SEC

    return False, None


def _scan_video(path: Path, expected_duration_sec: float) -> dict[str, Any]:
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        capture.release()
        raise VideoPreflightError("VIDEO_OPEN_FAIL", {"video_path": str(path)})

    decoded_frames = 0
    first_timestamp_sec: Optional[float] = None
    last_timestamp_sec: Optional[float] = None
    timestamp_deltas: list[float] = []
    decode_gaps: list[dict[str, float]] = []
    early_eof = False

    try:
        while True:
            decoded, _ = capture.read()
            if not decoded:
                if (
                    last_timestamp_sec is None
                    or last_timestamp_sec >= expected_duration_sec - EARLY_EOF_TOLERANCE_SEC
                ):
                    break

                recovered, recovered_timestamp = _recover_after_decode_failure(
                    capture,
                    last_timestamp_sec,
                    expected_duration_sec,
                )
                if not recovered or recovered_timestamp is None:
                    early_eof = True
                    break

                decode_gaps.append(
                    {
                        "start_sec": round(last_timestamp_sec, 3),
                        "end_sec": round(recovered_timestamp, 3),
                        "duration_sec": round(recovered_timestamp - last_timestamp_sec, 3),
                    }
                )
                timestamp_sec = recovered_timestamp
            else:
                timestamp_sec = float(capture.get(cv2.CAP_PROP_POS_MSEC) or 0.0) / 1000.0

            if first_timestamp_sec is None:
                first_timestamp_sec = timestamp_sec
            if last_timestamp_sec is not None and timestamp_sec > last_timestamp_sec:
                delta = timestamp_sec - last_timestamp_sec
                if delta <= 1.0:
                    timestamp_deltas.append(delta)
            last_timestamp_sec = timestamp_sec
            decoded_frames += 1
    finally:
        capture.release()

    if first_timestamp_sec is None or last_timestamp_sec is None or decoded_frames <= 0:
        raise VideoPreflightError(
            "VIDEO_DECODE_FAIL",
            {"video_path": str(path), "decoded_frames": decoded_frames},
        )

    if timestamp_deltas:
        effective_fps = 1.0 / statistics.median(timestamp_deltas)
    else:
        effective_fps = 0.0

    frame_duration_sec = (1.0 / effective_fps) if effective_fps > 0 else 0.0
    decoded_duration_sec = max(
        0.0,
        last_timestamp_sec - first_timestamp_sec + frame_duration_sec,
    )
    coverage_ratio = (
        decoded_duration_sec / expected_duration_sec if expected_duration_sec > 0 else 0.0
    )

    return {
        "decoded_frames": decoded_frames,
        "first_timestamp_sec": round(first_timestamp_sec, 3),
        "last_timestamp_sec": round(last_timestamp_sec, 3),
        "decoded_duration_sec": round(decoded_duration_sec, 3),
        "effective_fps": round(effective_fps, 4),
        "coverage_ratio": round(coverage_ratio, 6),
        "decode_gaps": decode_gaps,
        "early_eof": early_eof,
    }


def _needs_normalization(scan: dict[str, Any]) -> bool:
    return bool(
        scan.get("early_eof")
        or scan.get("decode_gaps")
        or float(scan.get("coverage_ratio") or 0.0) < MIN_DECODE_COVERAGE
    )


def _resolve_ffmpeg_executable() -> Optional[str]:
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        return system_ffmpeg

    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, RuntimeError):
        return None


def _normalize_with_ffmpeg(
    source_path: Path,
    output_path: Path,
    target_fps: float,
) -> dict[str, Any]:
    ffmpeg = _resolve_ffmpeg_executable()
    if not ffmpeg:
        raise VideoPreflightError(
            "FFMPEG_NOT_FOUND",
            {"video_path": str(source_path)},
        )

    safe_fps = min(max(float(target_fps or 10.0), 1.0), 60.0)
    command = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "warning",
        "-err_detect",
        "ignore_err",
        "-i",
        str(source_path),
        "-map",
        "0:v:0",
        "-an",
        "-vf",
        f"fps={safe_fps:.6f}",
        "-c:v",
        "mpeg4",
        "-q:v",
        "3",
        str(output_path),
    ]
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        errors="replace",
        check=False,
    )
    stderr_tail = (completed.stderr or "")[-4000:]
    if completed.returncode != 0 or not output_path.exists() or output_path.stat().st_size <= 0:
        raise VideoPreflightError(
            "VIDEO_NORMALIZATION_FAILED",
            {
                "video_path": str(source_path),
                "ffmpeg_exit_code": completed.returncode,
                "ffmpeg_stderr_tail": stderr_tail,
            },
        )

    return {
        "target_fps": round(safe_fps, 4),
        "decoder_warnings": bool(stderr_tail.strip()),
        "ffmpeg_stderr_tail": stderr_tail,
    }


def _duration_matches(expected_sec: float, actual_sec: float) -> bool:
    tolerance_sec = max(2.0, expected_sec * 0.002)
    return abs(expected_sec - actual_sec) <= tolerance_sec


@contextlib.contextmanager
def prepare_video_for_analysis(
    video_path: str | Path,
    expected_duration_sec: Optional[float] = None,
) -> Iterator[PreparedVideo]:
    source_path = Path(video_path).resolve()
    temp_dir: Optional[tempfile.TemporaryDirectory[str]] = None

    try:
        probe = _probe_video(source_path)
        container_duration_sec = float(probe["duration_sec"])
        external_duration_sec = float(expected_duration_sec or 0.0)
        if external_duration_sec > 0 and not _duration_matches(
            external_duration_sec,
            container_duration_sec,
        ):
            raise VideoPreflightError(
                "VIDEO_DURATION_MISMATCH",
                {
                    "video_path": str(source_path),
                    "recorded_duration_sec": round(external_duration_sec, 3),
                    "container_duration_sec": round(container_duration_sec, 3),
                },
            )

        authoritative_duration_sec = external_duration_sec or container_duration_sec
        source_scan = _scan_video(source_path, authoritative_duration_sec)
        validation: dict[str, Any] = {
            "container_duration_sec": round(container_duration_sec, 3),
            "expected_duration_sec": round(authoritative_duration_sec, 3),
            "source_scan": source_scan,
            "normalized": False,
        }
        warnings: list[str] = []
        analysis_path = source_path
        analysis_scan = source_scan

        if _needs_normalization(source_scan):
            warnings.append("SOURCE_DECODE_GAP_DETECTED")
            temp_dir = tempfile.TemporaryDirectory(prefix="focusai_normalized_")
            normalized_path = Path(temp_dir.name) / "normalized.mp4"
            target_fps = float(source_scan.get("effective_fps") or probe["reported_fps"] or 10.0)
            normalization = _normalize_with_ffmpeg(
                source_path,
                normalized_path,
                target_fps,
            )
            normalized_probe = _probe_video(normalized_path)
            normalized_scan = _scan_video(
                normalized_path,
                float(normalized_probe["duration_sec"]),
            )
            validation["normalization"] = normalization
            validation["normalized_duration_sec"] = round(
                float(normalized_probe["duration_sec"]),
                3,
            )
            validation["normalized_scan"] = normalized_scan

            if _needs_normalization(normalized_scan) or not _duration_matches(
                authoritative_duration_sec,
                float(normalized_probe["duration_sec"]),
            ):
                raise VideoPreflightError(
                    "VIDEO_DECODE_TRUNCATED",
                    validation,
                )

            analysis_path = normalized_path
            analysis_scan = normalized_scan
            validation["normalized"] = True
            warnings.append("SOURCE_VIDEO_NORMALIZED_FFMPEG")

        elif float(source_scan.get("coverage_ratio") or 0.0) < MIN_DECODE_COVERAGE:
            raise VideoPreflightError("VIDEO_DECODE_TRUNCATED", validation)

        yield PreparedVideo(
            source_path=source_path,
            analysis_path=analysis_path,
            validation=validation,
            warnings=warnings,
            decoded_timing=_decoded_timing_from_scan(analysis_scan),
        )
    finally:
        if temp_dir is not None:
            temp_dir.cleanup()
