from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import cv2


PROBLEM_PRIORITY = {
    "absent": 6,
    "sleep_suspect": 5,
    "drowsy": 5,
    "gaze_away": 4,
    "gaze_side": 4,
    "gaze_down": 3,
    "bad_posture": 2,
    "present_unknown": 1,
    "unknown": 1,
}


@dataclass(frozen=True)
class SampledFrame:
    index: int
    time_sec: float
    original_state: str
    path: Path
    width: int
    height: int

    def prompt_metadata(self) -> dict[str, Any]:
        return {
            "frame_index": self.index,
            "time_sec": round(self.time_sec, 3),
            "original_state": self.original_state,
        }


def analysis_duration_sec(analysis_result: dict[str, Any]) -> float:
    meta = analysis_result.get("meta") if isinstance(analysis_result.get("meta"), dict) else {}
    summary = analysis_result.get("summary") if isinstance(analysis_result.get("summary"), dict) else {}
    for value in (
        meta.get("duration_sec"),
        summary.get("duration_sec"),
        summary.get("total_time_sec"),
        summary.get("total_time"),
    ):
        try:
            duration = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(duration) and duration > 0:
            return duration

    timeline = analysis_result.get("timeline")
    if isinstance(timeline, list) and timeline:
        times = []
        for row in timeline:
            if not isinstance(row, dict):
                continue
            try:
                times.append(float(row.get("t", row.get("time", 0))))
            except (TypeError, ValueError):
                continue
        if times:
            return max(times) + 1.0
    return 0.0


def probe_video_duration_sec(video_path: str | Path) -> float:
    capture = cv2.VideoCapture(str(video_path))
    try:
        fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
        frames = float(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0)
        if fps > 0 and frames > 0:
            return frames / fps
        return 0.0
    finally:
        capture.release()


def _normalized_state(value: Any) -> str:
    state = str(value or "unknown").strip().lower()
    return "gaze_away" if state == "away" else state


def _state_at(analysis_result: dict[str, Any], time_sec: float) -> str:
    timeline = analysis_result.get("timeline")
    if not isinstance(timeline, list) or not timeline:
        return "unknown"

    closest: tuple[float, str] | None = None
    for row in timeline:
        if not isinstance(row, dict):
            continue
        try:
            row_time = float(row.get("t", row.get("time", 0)))
        except (TypeError, ValueError):
            continue
        state = _normalized_state(row.get("state"))
        distance = abs(row_time - time_sec)
        if closest is None or distance < closest[0]:
            closest = (distance, state)
    return closest[1] if closest else "unknown"


def _event_candidates(analysis_result: dict[str, Any], duration_sec: float) -> list[tuple[int, float]]:
    events = analysis_result.get("events")
    if not isinstance(events, list):
        return []

    candidates: list[tuple[int, float]] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        state = _normalized_state(event.get("type"))
        priority = PROBLEM_PRIORITY.get(state)
        if priority is None:
            continue
        try:
            start = max(0.0, float(event.get("start_sec", event.get("start_time", 0))))
            end = min(
                duration_sec,
                float(event.get("end_sec", event.get("end_time", start + 1))),
            )
        except (TypeError, ValueError):
            continue
        if end <= start:
            end = min(duration_sec, start + 1.0)
        span = max(0.0, end - start)
        points = [start + span / 2.0]
        if span >= 6.0:
            points.extend([start + span * 0.2, start + span * 0.8])
        for point in points:
            candidates.append((priority, min(max(point, 0.0), max(0.0, duration_sec - 0.001))))
    return candidates


def _timeline_candidates(analysis_result: dict[str, Any], duration_sec: float) -> list[tuple[int, float]]:
    timeline = analysis_result.get("timeline")
    if not isinstance(timeline, list):
        return []

    points_by_state: dict[str, list[float]] = {}
    for row in timeline:
        if not isinstance(row, dict):
            continue
        state = _normalized_state(row.get("state"))
        priority = PROBLEM_PRIORITY.get(state)
        if priority is None:
            continue
        try:
            point = float(row.get("t", row.get("time", 0)))
        except (TypeError, ValueError):
            continue
        if 0 <= point < duration_sec:
            points_by_state.setdefault(state, []).append(point)

    candidates: list[tuple[int, float]] = []
    for state, points in points_by_state.items():
        ordered = sorted(set(points))
        indexes = {0, len(ordered) // 2, len(ordered) - 1}
        for index in sorted(indexes):
            candidates.append((PROBLEM_PRIORITY[state], ordered[index]))
    return candidates


def _low_focus_candidates(analysis_result: dict[str, Any], duration_sec: float) -> list[tuple[int, float]]:
    patterns = analysis_result.get("time_patterns")
    if not isinstance(patterns, dict):
        return []
    segments = patterns.get("segments")
    if not isinstance(segments, list):
        worst = patterns.get("worst_segment")
        segments = [worst] if isinstance(worst, dict) else []

    candidates: list[tuple[int, float]] = []
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        try:
            ratio = float(segment.get("focus_ratio", 1.0))
            start = float(segment.get("start_sec", 0.0))
            end = float(segment.get("end_sec", start + 1.0))
        except (TypeError, ValueError):
            continue
        if ratio < 0.6:
            candidates.append((1, min(max((start + end) / 2.0, 0.0), max(duration_sec - 0.001, 0.0))))
    return candidates


def select_sample_times(
    analysis_result: dict[str, Any],
    frame_count: int,
    *,
    duration_sec: float | None = None,
) -> list[float]:
    count = max(1, int(frame_count))
    duration = float(duration_sec or analysis_duration_sec(analysis_result))
    if duration <= 0:
        raise ValueError("video duration is missing or zero")

    ranked = _event_candidates(analysis_result, duration)
    ranked.extend(_timeline_candidates(analysis_result, duration))
    ranked.extend(_low_focus_candidates(analysis_result, duration))
    ranked.sort(key=lambda item: (-item[0], item[1]))

    selected: list[float] = []
    min_distance = min(1.0, max(0.05, duration / (count * 10.0)))

    def add(point: float) -> None:
        point = min(max(float(point), 0.0), max(duration - 0.001, 0.0))
        if all(abs(point - existing) >= min_distance for existing in selected):
            selected.append(point)

    problem_quota = count if not ranked else max(1, int(math.ceil(count * 0.7)))
    for _, point in ranked:
        add(point)
        if len(selected) >= problem_quota:
            break

    # Always retain broad session coverage after problem-first sampling.
    remaining = max(0, count - len(selected))
    for index in range(remaining):
        add((index + 0.5) * duration / max(1, remaining))

    while len(selected) < count:
        grid = [(index + 0.5) * duration / (count * 3) for index in range(count * 3)]
        point = max(grid, key=lambda candidate: min(abs(candidate - item) for item in selected))
        previous_size = len(selected)
        add(point)
        if len(selected) == previous_size:
            min_distance *= 0.5

    return sorted(selected[:count])


def _resize_for_upload(frame: Any, max_dimension: int) -> Any:
    height, width = frame.shape[:2]
    longest = max(width, height)
    if longest <= max_dimension:
        return frame
    scale = max_dimension / float(longest)
    return cv2.resize(
        frame,
        (max(1, int(round(width * scale))), max(1, int(round(height * scale)))),
        interpolation=cv2.INTER_AREA,
    )


def _decode_nearest_frame(video_path: Path, target_sec: float) -> tuple[bool, Any, float]:
    """Slow VFR-safe fallback used only when random seeking cannot read a frame."""
    capture = cv2.VideoCapture(str(video_path))
    best_frame = None
    best_time = 0.0
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            position = float(capture.get(cv2.CAP_PROP_POS_MSEC) or 0.0) / 1000.0
            if position <= target_sec or best_frame is None:
                best_frame = frame
                best_time = position
            if position >= target_sec:
                best_frame = frame
                best_time = position
                break
    finally:
        capture.release()
    return best_frame is not None, best_frame, best_time


def extract_frames(
    video_path: str | Path,
    analysis_result: dict[str, Any],
    output_dir: str | Path,
    frame_count: int,
    *,
    max_dimension: int = 1024,
    jpeg_quality: int = 82,
) -> list[SampledFrame]:
    path = Path(video_path)
    if not path.is_file():
        raise FileNotFoundError(f"video not found: {path}")

    duration = analysis_duration_sec(analysis_result) or probe_video_duration_sec(path)
    target_times = select_sample_times(analysis_result, frame_count, duration_sec=duration)
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)

    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        capture.release()
        raise RuntimeError(f"failed to open video: {path}")

    fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
    samples: list[SampledFrame] = []
    try:
        for index, time_sec in enumerate(target_times, start=1):
            sampled_time = time_sec
            capture.set(cv2.CAP_PROP_POS_MSEC, sampled_time * 1000.0)
            ok, frame = capture.read()
            if not ok and fps > 0:
                capture.set(cv2.CAP_PROP_POS_FRAMES, max(0, int(round(time_sec * fps))))
                ok, frame = capture.read()
            if not ok:
                # Some VFR WebM files cannot seek to their last GOP reliably.
                # Reopen and step slightly earlier instead of dropping the sample.
                for rewind_sec in (0.5, 2.0, 5.0):
                    capture.release()
                    capture = cv2.VideoCapture(str(path))
                    sampled_time = max(0.0, time_sec - rewind_sec)
                    capture.set(cv2.CAP_PROP_POS_MSEC, sampled_time * 1000.0)
                    ok, frame = capture.read()
                    if ok:
                        break
            if not ok:
                ok, frame, sampled_time = _decode_nearest_frame(path, time_sec)
            if not ok or frame is None:
                continue

            frame = _resize_for_upload(frame, max(256, int(max_dimension)))
            height, width = frame.shape[:2]
            file_path = destination / f"frame_{index:03d}_{int(round(sampled_time)):06d}s.jpg"
            encoded, buffer = cv2.imencode(
                ".jpg",
                frame,
                [int(cv2.IMWRITE_JPEG_QUALITY), max(40, min(95, int(jpeg_quality)))],
            )
            if not encoded:
                continue
            file_path.write_bytes(buffer.tobytes())
            samples.append(
                SampledFrame(
                    index=index,
                    time_sec=sampled_time,
                    original_state=_state_at(analysis_result, sampled_time),
                    path=file_path,
                    width=int(width),
                    height=int(height),
                )
            )
    finally:
        capture.release()

    if not samples:
        raise RuntimeError("no frames could be extracted from the video")
    return samples


def frame_dimensions(frames: Iterable[SampledFrame]) -> list[tuple[int, int]]:
    return [(frame.width, frame.height) for frame in frames]
