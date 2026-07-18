from __future__ import annotations

import hashlib
import math
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

import cv2
import numpy as np


ALLOWED_LABELS = (
    "focus",
    "drowsy",
    "gaze_down",
    "gaze_side",
    "unknown",
    "absent",
    "bad_posture",
)
READY_LABELS = ("focus", "drowsy", "gaze_down", "gaze_side", "unknown")


@dataclass(frozen=True)
class SceneCandidate:
    source_id: str
    start_sec: float
    end_sec: float
    suggested_label: str
    evidence_flags: tuple[str, ...]


@dataclass(frozen=True)
class ReviewedScene:
    source_id: str
    start_sec: float
    end_sec: float
    label: str
    cue: str
    disposition: str
    notes: str


@dataclass(frozen=True)
class VideoMeta:
    opened: bool
    duration_sec: float
    fps: float
    width: int
    height: int
    frame_count: int


def _ascii_token(value: str) -> str:
    token = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(value).strip())
    return token.strip("-_").lower() or "scene"


def clip_filename(scene: ReviewedScene) -> str:
    label = _ascii_token(scene.label)
    cue = _ascii_token(scene.cue).replace("_", "-")
    source = _ascii_token(scene.source_id)
    return (
        f"{label}__{cue}__{source}__"
        f"{int(scene.start_sec):06d}-{int(scene.end_sec):06d}.mp4"
    )


def group_timeline_candidates(
    source_id: str,
    timeline: Sequence[dict[str, Any]],
    *,
    duration_sec: float,
    max_gap_sec: float = 2.0,
    context_sec: float = 2.0,
) -> list[SceneCandidate]:
    points: list[tuple[float, str, dict[str, Any]]] = []
    for item in timeline:
        label = str(item.get("rule_state") or item.get("state") or "").strip()
        if label not in ALLOWED_LABELS:
            continue
        try:
            timestamp = float(item.get("t", 0))
        except (TypeError, ValueError):
            continue
        points.append((timestamp, label, item))

    points.sort(key=lambda row: row[0])
    if not points:
        return []

    grouped: list[list[tuple[float, str, dict[str, Any]]]] = []
    current = [points[0]]
    for point in points[1:]:
        previous = current[-1]
        internal_gap = point[0] - previous[0] - 1.0
        if point[1] == previous[1] and internal_gap <= max_gap_sec:
            current.append(point)
        else:
            grouped.append(current)
            current = [point]
    grouped.append(current)

    candidates: list[SceneCandidate] = []
    for group in grouped:
        flags = {
            str(name)
            for _, _, item in group
            for name, enabled in (item.get("flags") or {}).items()
            if enabled
        }
        label = group[0][1]
        start_sec = max(0.0, group[0][0] - context_sec)
        end_sec = min(float(duration_sec), group[-1][0] + 1.0 + context_sec)
        minimum = 12.0 if label == "drowsy" else 4.0
        available = min(float(duration_sec), minimum)
        if end_sec - start_sec < available:
            center = (start_sec + end_sec) / 2.0
            start_sec = min(max(0.0, center - available / 2.0), float(duration_sec) - available)
            end_sec = start_sec + available

        chunk_start = start_sec
        while end_sec - chunk_start > 30.0:
            candidates.append(
                SceneCandidate(
                    source_id=source_id,
                    start_sec=chunk_start,
                    end_sec=chunk_start + 30.0,
                    suggested_label=label,
                    evidence_flags=tuple(sorted(flags)),
                )
            )
            chunk_start += 30.0
        candidates.append(
            SceneCandidate(
                source_id=source_id,
                start_sec=chunk_start,
                end_sec=end_sec,
                suggested_label=label,
                evidence_flags=tuple(sorted(flags)),
            )
        )
    return candidates


def shortage_rows(scenes: Iterable[ReviewedScene]) -> list[dict[str, Any]]:
    grouped: dict[str, list[ReviewedScene]] = {}
    for scene in scenes:
        if scene.disposition != "ready":
            continue
        grouped.setdefault(scene.label, []).append(scene)

    rows: list[dict[str, Any]] = []
    for label in READY_LABELS:
        label_scenes = grouped.get(label, [])
        duration = sum(max(0.0, scene.end_sec - scene.start_sec) for scene in label_scenes)
        source_count = len({scene.source_id for scene in label_scenes})
        reasons: list[str] = []
        if len(label_scenes) < 20:
            reasons.append("clips<20")
        if duration < 180.0:
            reasons.append("duration<180s")
        if source_count < 3:
            reasons.append("sources<3")
        rows.append(
            {
                "label": label,
                "clip_count": len(label_scenes),
                "duration_sec": round(duration, 3),
                "source_count": source_count,
                "is_shortage": bool(reasons),
                "reasons": reasons,
            }
        )
    return rows


def probe_video(path: Path) -> VideoMeta:
    capture = cv2.VideoCapture(str(path))
    opened = capture.isOpened()
    fps = float(capture.get(cv2.CAP_PROP_FPS)) if opened else 0.0
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT)) if opened else 0
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)) if opened else 0
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)) if opened else 0
    capture.release()
    duration = frame_count / fps if fps > 0 else 0.0
    return VideoMeta(opened, duration, fps, width, height, frame_count)


def sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        while chunk := file.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def extract_clip(
    source_path: Path,
    output_path: Path,
    *,
    start_sec: float,
    end_sec: float,
) -> VideoMeta:
    source_meta = probe_video(source_path)
    if not source_meta.opened or source_meta.fps <= 0 or source_meta.frame_count <= 0:
        raise ValueError(f"unreadable source video: {source_path}")
    if output_path.exists():
        raise FileExistsError(output_path)
    start = max(0.0, float(start_sec))
    end = min(float(end_sec), source_meta.duration_sec)
    if end <= start:
        raise ValueError(f"invalid clip range: {start_sec}-{end_sec}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output_path.with_name(f".{output_path.stem}.partial{output_path.suffix}")
    capture = cv2.VideoCapture(str(source_path))
    writer = cv2.VideoWriter(
        str(temp_path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        source_meta.fps,
        (source_meta.width, source_meta.height),
    )
    try:
        if not capture.isOpened() or not writer.isOpened():
            raise RuntimeError(f"could not initialize clip extraction: {source_path}")
        start_frame = max(0, int(math.floor(start * source_meta.fps)))
        end_frame = min(source_meta.frame_count, int(math.ceil(end * source_meta.fps)))
        capture.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
        for _ in range(start_frame, end_frame):
            ok, frame = capture.read()
            if not ok:
                break
            writer.write(frame)
    finally:
        capture.release()
        writer.release()

    output_meta = probe_video(temp_path)
    if not output_meta.opened or output_meta.frame_count <= 0:
        temp_path.unlink(missing_ok=True)
        raise RuntimeError(f"clip verification failed: {temp_path}")
    os.replace(temp_path, output_path)
    return output_meta


def _frame_at(capture: cv2.VideoCapture, timestamp: float) -> np.ndarray:
    capture.set(cv2.CAP_PROP_POS_MSEC, max(0.0, timestamp) * 1000.0)
    ok, frame = capture.read()
    if not ok:
        raise RuntimeError(f"could not decode frame at {timestamp:.3f}s")
    return frame


def _contact_tile(frame: np.ndarray, caption: str, *, tile_width: int = 320) -> np.ndarray:
    height, width = frame.shape[:2]
    image_height = max(1, int(round(height * tile_width / max(width, 1))))
    resized = cv2.resize(frame, (tile_width, image_height), interpolation=cv2.INTER_AREA)
    tile = np.zeros((image_height + 32, tile_width, 3), dtype=np.uint8)
    tile[:image_height] = resized
    cv2.putText(
        tile,
        caption,
        (6, image_height + 22),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.48,
        (255, 255, 255),
        1,
        cv2.LINE_AA,
    )
    return tile


def write_overview_sheets(
    source_path: Path,
    output_dir: Path,
    *,
    source_id: str,
    every_sec: float = 10.0,
    frames_per_page: int = 30,
) -> list[Path]:
    meta = probe_video(source_path)
    if not meta.opened or meta.duration_sec <= 0:
        raise ValueError(f"unreadable source video: {source_path}")
    if every_sec <= 0 or frames_per_page <= 0:
        raise ValueError("sampling interval and page size must be positive")

    timestamps = [float(value) for value in np.arange(0.0, meta.duration_sec, every_sec)]
    capture = cv2.VideoCapture(str(source_path))
    output_dir.mkdir(parents=True, exist_ok=True)
    pages: list[Path] = []
    try:
        for page_index in range(0, len(timestamps), frames_per_page):
            batch = timestamps[page_index : page_index + frames_per_page]
            tiles = [
                _contact_tile(_frame_at(capture, timestamp), f"{source_id}  t={timestamp:.1f}s")
                for timestamp in batch
            ]
            columns = min(5, len(tiles))
            rows = int(math.ceil(len(tiles) / columns))
            tile_height, tile_width = tiles[0].shape[:2]
            page = np.zeros((rows * tile_height, columns * tile_width, 3), dtype=np.uint8)
            for index, tile in enumerate(tiles):
                row, column = divmod(index, columns)
                page[
                    row * tile_height : (row + 1) * tile_height,
                    column * tile_width : (column + 1) * tile_width,
                ] = tile
            page_path = output_dir / f"{_ascii_token(source_id)}__overview_{len(pages) + 1:03d}.jpg"
            if not cv2.imwrite(str(page_path), page, [cv2.IMWRITE_JPEG_QUALITY, 88]):
                raise RuntimeError(f"could not write contact sheet: {page_path}")
            pages.append(page_path)
    finally:
        capture.release()
    return pages


def write_scene_contact_sheet(
    source_path: Path,
    output_path: Path,
    *,
    source_id: str,
    start_sec: float,
    end_sec: float,
    sample_count: int = 5,
) -> Path:
    meta = probe_video(source_path)
    if not meta.opened or meta.duration_sec <= 0:
        raise ValueError(f"unreadable source video: {source_path}")
    start = max(0.0, float(start_sec))
    end = min(float(end_sec), meta.duration_sec)
    if end <= start or sample_count <= 0:
        raise ValueError("candidate range and sample count must be positive")

    last_decodable = max(start, end - 1.0 / max(meta.fps, 1.0))
    timestamps = np.linspace(start, last_decodable, sample_count).tolist()
    capture = cv2.VideoCapture(str(source_path))
    try:
        tiles = [
            _contact_tile(_frame_at(capture, timestamp), f"{source_id}  t={timestamp:.1f}s")
            for timestamp in timestamps
        ]
    finally:
        capture.release()

    columns = min(5, len(tiles))
    rows = int(math.ceil(len(tiles) / columns))
    tile_height, tile_width = tiles[0].shape[:2]
    page = np.zeros((rows * tile_height, columns * tile_width, 3), dtype=np.uint8)
    for index, tile in enumerate(tiles):
        row, column = divmod(index, columns)
        page[
            row * tile_height : (row + 1) * tile_height,
            column * tile_width : (column + 1) * tile_width,
        ] = tile

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(output_path), page, [cv2.IMWRITE_JPEG_QUALITY, 90]):
        raise RuntimeError(f"could not write contact sheet: {output_path}")
    return output_path
