from __future__ import annotations

import hashlib
import math
import os
import re
import csv
import json
import subprocess
from dataclasses import asdict, dataclass, replace
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


@dataclass(frozen=True)
class CandidateClassification:
    disposition: str
    reason: str


@dataclass(frozen=True)
class InventoryRecord:
    path: str
    extension: str
    size_bytes: int
    sha256: str
    opened: bool
    duration_sec: float
    fps: float
    width: int
    height: int
    disposition: str
    reason: str
    duplicate_of: str
    source_id: str
    analysis_json: str


VIDEO_EXTENSIONS = {
    ".mp4",
    ".mov",
    ".mkv",
    ".avi",
    ".webm",
    ".m4v",
    ".mpg",
    ".mpeg",
    ".wmv",
    ".flv",
    ".mts",
    ".m2ts",
    ".3gp",
    ".vob",
    ".ogv",
    ".asf",
    ".mxf",
}


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
    attempted: set[float] = set()
    for offset in (0.0, -1.0, 1.0, -2.0, 2.0, -5.0, 5.0, -10.0):
        target = max(0.0, float(timestamp) + offset)
        if target in attempted:
            continue
        attempted.add(target)
        capture.set(cv2.CAP_PROP_POS_MSEC, target * 1000.0)
        ok, frame = capture.read()
        if ok:
            return frame

    fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
    if fps > 0 and capture.set(cv2.CAP_PROP_POS_FRAMES, 0.0):
        target_frame = max(0, int(round(float(timestamp) * fps)))
        last_frame: np.ndarray | None = None
        for _ in range(target_frame + 1):
            ok, frame = capture.read()
            if not ok:
                break
            last_frame = frame
        if last_frame is not None:
            return last_frame
    raise RuntimeError(f"could not decode a nearby frame at {timestamp:.3f}s")


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
    duration_limit_sec: float | None = None,
) -> list[Path]:
    meta = probe_video(source_path)
    if not meta.opened or meta.duration_sec <= 0:
        raise ValueError(f"unreadable source video: {source_path}")
    if every_sec <= 0 or frames_per_page <= 0:
        raise ValueError("sampling interval and page size must be positive")

    review_duration = meta.duration_sec
    if duration_limit_sec is not None and duration_limit_sec > 0:
        review_duration = min(review_duration, float(duration_limit_sec))
    timestamps = [float(value) for value in np.arange(0.0, review_duration, every_sec)]
    capture = cv2.VideoCapture(str(source_path))
    output_dir.mkdir(parents=True, exist_ok=True)
    source_token = _ascii_token(source_id)
    for stale in output_dir.glob(f"{source_token}__overview_*.jpg"):
        stale.unlink()
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
            page_path = output_dir / f"{source_token}__overview_{len(pages) + 1:03d}.jpg"
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


def classify_candidate(path: Path, *, project_root: Path) -> CandidateClassification:
    suffix = path.suffix.lower()
    if suffix == ".mts":
        if "node_modules" in {part.lower() for part in path.parts}:
            return CandidateClassification("excluded", "typescript_mts")
        prefix = path.read_bytes()[:4096]
        text = prefix.decode("utf-8", errors="ignore").lstrip()
        code_markers = (
            "import ",
            "export ",
            "/// <reference",
            "#!/usr/bin/env node",
            "declare ",
        )
        if any(text.startswith(marker) for marker in code_markers):
            return CandidateClassification("excluded", "typescript_mts")

    resolved = path.resolve()
    project = project_root.resolve()
    focus_dirs = (
        project / "ai" / "tmp" / "videos",
        project / "ai" / "downloads",
    )
    if any(resolved.is_relative_to(directory) for directory in focus_dirs):
        return CandidateClassification("focusai", "focusai_project_source")
    if path.name.lower() == "session_54_full.webm":
        return CandidateClassification("focusai", "focusai_duplicate_candidate")
    return CandidateClassification("excluded", "non_focus_media_asset")


def read_review_decisions(path: Path) -> list[ReviewedScene]:
    allowed_dispositions = {"ready", "rule_validation", "needs_review"}
    rows: list[ReviewedScene] = []
    with path.open("r", newline="", encoding="utf-8-sig") as file:
        for line_number, raw in enumerate(csv.DictReader(file), start=2):
            label = str(raw.get("label") or "").strip()
            disposition = str(raw.get("disposition") or "").strip()
            if label not in ALLOWED_LABELS:
                raise ValueError(f"line {line_number}: unknown label {label!r}")
            if disposition not in allowed_dispositions:
                raise ValueError(f"line {line_number}: unknown disposition {disposition!r}")
            if disposition == "ready" and label not in READY_LABELS:
                raise ValueError(f"line {line_number}: {label} cannot be ready")
            if disposition == "rule_validation" and label not in {"absent", "bad_posture"}:
                raise ValueError(f"line {line_number}: {label} is not a rule-validation label")
            try:
                start_sec = float(raw.get("start_sec") or 0)
                end_sec = float(raw.get("end_sec") or 0)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"line {line_number}: invalid time range") from exc
            if end_sec <= start_sec:
                raise ValueError(f"line {line_number}: invalid time range {start_sec}-{end_sec}")
            source_id = str(raw.get("source_id") or "").strip()
            cue = str(raw.get("cue") or "").strip()
            if not source_id or not cue:
                raise ValueError(f"line {line_number}: source_id and cue are required")
            rows.append(
                ReviewedScene(
                    source_id=source_id,
                    start_sec=start_sec,
                    end_sec=end_sec,
                    label=label,
                    cue=cue,
                    disposition=disposition,
                    notes=str(raw.get("notes") or "").strip(),
                )
            )
    return rows


def discover_media_candidates(
    root: Path,
    *,
    runner: Any = subprocess.run,
) -> list[Path]:
    command = ["rg", "--files", "--hidden", "--no-ignore", "--no-messages", str(root)]
    for extension in sorted(VIDEO_EXTENSIONS):
        command.extend(["-g", f"*{extension}"])
    try:
        completed = runner(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except FileNotFoundError:
        completed = None
    if completed is not None:
        if completed.returncode not in {0, 1} and not completed.stdout.strip():
            raise RuntimeError(f"rg media discovery failed: {completed.stderr.strip()}")
        return sorted(
            {
                Path(line.strip())
                for line in completed.stdout.splitlines()
                if line.strip() and Path(line.strip()).suffix.lower() in VIDEO_EXTENSIONS
            },
            key=lambda path: str(path).lower(),
        )

    candidates: list[Path] = []

    def ignore_error(_: OSError) -> None:
        return None

    for directory, _, filenames in os.walk(root, topdown=True, onerror=ignore_error, followlinks=False):
        parent = Path(directory)
        for name in filenames:
            path = parent / name
            if path.suffix.lower() in VIDEO_EXTENSIONS:
                candidates.append(path)
    return sorted(candidates, key=lambda path: str(path).lower())


def source_id_for_path(path: Path) -> str:
    if path.name.lower() == "s002_test.mp4":
        return "S002_test"
    match = re.match(r"^(\d+)_\d+_chunk_(\d+)_", path.name, flags=re.IGNORECASE)
    if match:
        return f"session{match.group(1)}_chunk{match.group(2)}"
    return _ascii_token(path.stem)


def analysis_path_for_source(
    path: Path,
    *,
    project_root: Path,
    output_root: Path,
) -> Path:
    if path.name.lower() == "s002_test.mp4":
        return output_root / "analysis" / "S002_test.json"
    match = re.match(r"^(\d+)_\d+_chunk_(\d+)_", path.name, flags=re.IGNORECASE)
    if match:
        return (
            project_root
            / "ai"
            / "tmp"
            / f"session_{match.group(1)}"
            / f"chunk_{match.group(2)}_result.json"
        )
    return output_root / "analysis" / f"{_ascii_token(path.stem)}.json"


def build_inventory_records(
    paths: Iterable[Path],
    *,
    project_root: Path,
    output_root: Path,
) -> list[InventoryRecord]:
    records: list[InventoryRecord] = []
    for path in sorted(paths, key=lambda item: str(item).lower()):
        classification = classify_candidate(path, project_root=project_root)
        digest = sha256_file(path)
        meta = (
            VideoMeta(False, 0.0, 0.0, 0, 0, 0)
            if classification.reason == "typescript_mts"
            else probe_video(path)
        )
        disposition = classification.disposition
        reason = classification.reason
        duplicate_of = ""
        source_id = source_id_for_path(path)
        analysis_path = analysis_path_for_source(
            path,
            project_root=project_root,
            output_root=output_root,
        )
        records.append(
            InventoryRecord(
                path=str(path.resolve()),
                extension=path.suffix.lower(),
                size_bytes=path.stat().st_size,
                sha256=digest,
                opened=meta.opened,
                duration_sec=round(meta.duration_sec, 6),
                fps=round(meta.fps, 6),
                width=meta.width,
                height=meta.height,
                disposition=disposition,
                reason=reason,
                duplicate_of=duplicate_of,
                source_id=source_id,
                analysis_json=str(analysis_path.resolve()),
            )
        )

    focus_by_hash: dict[str, list[int]] = {}
    for index, record in enumerate(records):
        if record.disposition == "focusai":
            focus_by_hash.setdefault(record.sha256, []).append(index)
    reason_priority = {
        "focusai_project_source": 0,
        "focusai_duplicate_candidate": 1,
    }
    for indices in focus_by_hash.values():
        canonical_index = min(
            indices,
            key=lambda index: (
                reason_priority.get(records[index].reason, 9),
                records[index].path.lower(),
            ),
        )
        canonical_path = records[canonical_index].path
        for index in indices:
            if index == canonical_index:
                continue
            records[index] = replace(
                records[index],
                disposition="duplicate",
                reason="exact_duplicate",
                duplicate_of=canonical_path,
            )
    return records


INVENTORY_FIELDS = tuple(InventoryRecord.__dataclass_fields__)


def write_inventory_csv(records: Iterable[InventoryRecord], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=INVENTORY_FIELDS)
        writer.writeheader()
        for record in records:
            writer.writerow(asdict(record))
    return path


def read_inventory_csv(path: Path) -> list[InventoryRecord]:
    records: list[InventoryRecord] = []
    with path.open("r", newline="", encoding="utf-8-sig") as file:
        for raw in csv.DictReader(file):
            records.append(
                InventoryRecord(
                    path=str(raw["path"]),
                    extension=str(raw["extension"]),
                    size_bytes=int(raw["size_bytes"]),
                    sha256=str(raw["sha256"]),
                    opened=str(raw["opened"]).lower() == "true",
                    duration_sec=float(raw["duration_sec"]),
                    fps=float(raw["fps"]),
                    width=int(raw["width"]),
                    height=int(raw["height"]),
                    disposition=str(raw["disposition"]),
                    reason=str(raw["reason"]),
                    duplicate_of=str(raw["duplicate_of"]),
                    source_id=str(raw["source_id"]),
                    analysis_json=str(raw["analysis_json"]),
                )
            )
    return records


def ensure_safe_output_root(output_root: Path, *, project_root: Path) -> Path:
    output = output_root.resolve()
    project = project_root.resolve()
    if output == project or output.is_relative_to(project) or project.is_relative_to(output):
        raise ValueError(f"output root must be separate from the project root: {output}")
    return output


def run_inventory(
    *,
    computer_root: Path,
    project_root: Path,
    output_root: Path,
) -> dict[str, Any]:
    output = ensure_safe_output_root(output_root, project_root=project_root)
    candidates = [
        path
        for path in discover_media_candidates(computer_root)
        if not path.resolve().is_relative_to(output)
    ]
    records = build_inventory_records(
        candidates,
        project_root=project_root,
        output_root=output,
    )
    write_inventory_csv(records, output / "manifests" / "source_inventory.csv")
    unique_focus = [record for record in records if record.disposition == "focusai"]
    return {
        "candidate_count": len(records),
        "typescript_mts_count": sum(record.reason == "typescript_mts" for record in records),
        "focusai_path_count": sum(
            record.disposition in {"focusai", "duplicate"} for record in records
        ),
        "unique_focusai_count": len(unique_focus),
        "duplicate_count": sum(record.disposition == "duplicate" for record in records),
        "unique_duration_sec": round(sum(record.duration_sec for record in unique_focus), 3),
    }


def load_analysis_timeline(path: Path) -> tuple[float, list[dict[str, Any]]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data.get("analysis_result"), dict):
        data = data["analysis_result"]
    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    duration = float(meta.get("duration_sec") or meta.get("video_duration_sec") or 0)
    front = data.get("front_result") if isinstance(data.get("front_result"), dict) else {}
    timeline = front.get("timeline") if isinstance(front.get("timeline"), list) else None
    if timeline is None:
        timeline = data.get("timeline") if isinstance(data.get("timeline"), list) else []
    return duration, [item for item in timeline if isinstance(item, dict)]


CANDIDATE_FIELDS = (
    "source_id",
    "source_path",
    "start_sec",
    "end_sec",
    "suggested_label",
    "evidence_flags",
    "sheet_path",
    "analysis_json",
)


def run_sheets(
    *,
    project_root: Path,
    output_root: Path,
    every_sec: float = 10.0,
) -> dict[str, Any]:
    output = ensure_safe_output_root(output_root, project_root=project_root)
    inventory_path = output / "manifests" / "source_inventory.csv"
    records = [
        record
        for record in read_inventory_csv(inventory_path)
        if record.disposition == "focusai"
    ]
    candidate_rows: list[dict[str, Any]] = []
    overview_count = 0
    missing_analysis: list[str] = []
    for record in records:
        source_path = Path(record.path)
        analysis_path = Path(record.analysis_json)
        analysis_duration = 0.0
        timeline: list[dict[str, Any]] = []
        if analysis_path.is_file():
            analysis_duration, timeline = load_analysis_timeline(analysis_path)
        overview_pages = write_overview_sheets(
            source_path,
            output / "contact_sheets" / "overview" / record.source_id,
            source_id=record.source_id,
            every_sec=every_sec,
            duration_limit_sec=analysis_duration or record.duration_sec,
        )
        overview_count += len(overview_pages)

        if not analysis_path.is_file():
            missing_analysis.append(record.source_id)
            continue
        candidates = group_timeline_candidates(
            record.source_id,
            timeline,
            duration_sec=analysis_duration or record.duration_sec,
        )
        for candidate in candidates:
            if candidate.suggested_label == "focus":
                continue
            sheet_name = (
                f"{_ascii_token(record.source_id)}__{_ascii_token(candidate.suggested_label)}__"
                f"{int(candidate.start_sec):06d}-{int(candidate.end_sec):06d}.jpg"
            )
            sheet_path = output / "contact_sheets" / "candidates" / sheet_name
            existing_sheet = cv2.imread(str(sheet_path)) if sheet_path.is_file() else None
            if existing_sheet is None:
                write_scene_contact_sheet(
                    source_path,
                    sheet_path,
                    source_id=record.source_id,
                    start_sec=candidate.start_sec,
                    end_sec=candidate.end_sec,
                )
            candidate_rows.append(
                {
                    "source_id": record.source_id,
                    "source_path": record.path,
                    "start_sec": round(candidate.start_sec, 3),
                    "end_sec": round(candidate.end_sec, 3),
                    "suggested_label": candidate.suggested_label,
                    "evidence_flags": "|".join(candidate.evidence_flags),
                    "sheet_path": str(sheet_path.resolve()),
                    "analysis_json": record.analysis_json,
                }
            )

    candidate_manifest = output / "manifests" / "candidate_scenes.csv"
    candidate_manifest.parent.mkdir(parents=True, exist_ok=True)
    with candidate_manifest.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=CANDIDATE_FIELDS)
        writer.writeheader()
        writer.writerows(candidate_rows)
    return {
        "source_count": len(records),
        "overview_page_count": overview_count,
        "candidate_count": len(candidate_rows),
        "missing_analysis": missing_analysis,
    }


CLIP_FIELDS = (
    "clip_path",
    "label",
    "cue",
    "disposition",
    "source_id",
    "source_path",
    "source_sha256",
    "start_sec",
    "end_sec",
    "duration_sec",
    "notes",
)


def _scene_output_path(output_root: Path, scene: ReviewedScene) -> Path:
    if scene.disposition == "ready":
        directory = output_root / "train_ready" / scene.label
    elif scene.disposition == "rule_validation":
        directory = output_root / "rule_validation" / scene.label
    else:
        directory = output_root / "needs_review"
    return directory / clip_filename(scene)


def _write_balance_reports(output: Path, scenes: list[ReviewedScene]) -> None:
    rows = shortage_rows(scenes)
    cues_by_label: dict[str, set[str]] = {}
    for scene in scenes:
        if scene.disposition == "ready":
            cues_by_label.setdefault(scene.label, set()).add(scene.cue)

    balance_path = output / "manifests" / "scene_balance.csv"
    with balance_path.open("w", newline="", encoding="utf-8-sig") as file:
        fieldnames = (
            "label",
            "clip_count",
            "duration_sec",
            "source_count",
            "scene_cues",
            "is_shortage",
            "reasons",
        )
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            rendered = dict(row)
            rendered["scene_cues"] = "|".join(sorted(cues_by_label.get(row["label"], set())))
            rendered["reasons"] = "|".join(row["reasons"])
            writer.writerow(rendered)

    recommendations = {
        "focus": "화면 집중과 필기·독서 중 고개 숙임을 여러 조명과 안경 조건에서 촬영",
        "drowsy": "10초 이상 눈 감김·고개 떨굼·활동 중단이 함께 나타나는 장면 촬영",
        "gaze_down": "필기와 구분되도록 책상 아래나 휴대폰을 지속해서 보는 장면 촬영",
        "gaze_side": "짧은 주변 확인과 2초 이상 지속되는 좌우 시선 이탈을 각각 촬영",
        "unknown": "얼굴 가림·역광·저조도·부분 프레임 이탈 조건을 각각 촬영",
    }
    lines = ["# FocusAI 부족 장면 보고서", ""]
    for row in rows:
        status = "부족" if row["is_shortage"] else "최소 기준 충족"
        reasons = ", ".join(row["reasons"]) if row["reasons"] else "없음"
        lines.extend(
            [
                f"## {row['label']}",
                "",
                f"- 상태: {status}",
                f"- 확정 클립: {row['clip_count']}개",
                f"- 확정 길이: {row['duration_sec']:.1f}초",
                f"- 원본 세션: {row['source_count']}개",
                f"- 부족 근거: {reasons}",
                f"- 다음 촬영 권장: {recommendations[row['label']]}",
                "",
            ]
        )
    (output / "shortage_report.md").write_text("\n".join(lines), encoding="utf-8")


def run_extract(
    *,
    project_root: Path,
    output_root: Path,
    decisions_path: Path,
    dry_run: bool = False,
) -> dict[str, Any]:
    output = ensure_safe_output_root(output_root, project_root=project_root)
    records = [
        record
        for record in read_inventory_csv(output / "manifests" / "source_inventory.csv")
        if record.disposition == "focusai"
    ]
    by_source = {record.source_id: record for record in records}
    scenes = read_review_decisions(decisions_path)
    errors: list[str] = []
    for scene in scenes:
        record = by_source.get(scene.source_id)
        if record is None:
            errors.append(f"unknown source_id: {scene.source_id}")
            continue
        if scene.start_sec < 0 or scene.end_sec > record.duration_sec + 0.05:
            errors.append(
                f"range outside source: {scene.source_id} {scene.start_sec}-{scene.end_sec}"
            )
        minimum = 12.0 if scene.label == "drowsy" else 4.0
        if scene.end_sec - scene.start_sec < minimum:
            errors.append(f"scene shorter than {minimum:.0f}s: {scene.source_id}")
    if errors:
        raise ValueError("; ".join(errors))
    if dry_run:
        return {"clip_count": len(scenes), "errors": []}

    manifest_rows: list[dict[str, Any]] = []
    for scene in scenes:
        record = by_source[scene.source_id]
        output_path = _scene_output_path(output, scene)
        if output_path.exists():
            clip_meta = probe_video(output_path)
            if not clip_meta.opened:
                raise RuntimeError(f"existing clip is unreadable: {output_path}")
        else:
            clip_meta = extract_clip(
                Path(record.path),
                output_path,
                start_sec=scene.start_sec,
                end_sec=scene.end_sec,
            )
        manifest_rows.append(
            {
                "clip_path": str(output_path.resolve()),
                "label": scene.label,
                "cue": scene.cue,
                "disposition": scene.disposition,
                "source_id": scene.source_id,
                "source_path": record.path,
                "source_sha256": record.sha256,
                "start_sec": scene.start_sec,
                "end_sec": scene.end_sec,
                "duration_sec": round(clip_meta.duration_sec, 6),
                "notes": scene.notes,
            }
        )

    manifest_path = output / "manifests" / "clips_manifest.csv"
    with manifest_path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=CLIP_FIELDS)
        writer.writeheader()
        writer.writerows(manifest_rows)
    _write_balance_reports(output, scenes)
    ready_count = sum(scene.disposition == "ready" for scene in scenes)
    review_count = sum(scene.disposition == "needs_review" for scene in scenes)
    readme_lines = [
        "# FocusAI 학습 장면 준비 결과",
        "",
        f"- 전체 클립: {len(scenes)}개",
        f"- 학습 준비 완료: {ready_count}개",
        f"- 추가 확인 필요: {review_count}개",
        "- 원본 영상은 수정하지 않았으며 모든 클립은 manifest에서 추적할 수 있습니다.",
    ]
    (output / "README.md").write_text("\n".join(readme_lines) + "\n", encoding="utf-8")
    return {
        "clip_count": len(scenes),
        "ready_count": ready_count,
        "needs_review_count": review_count,
        "errors": [],
    }


def run_verify(*, project_root: Path, output_root: Path) -> dict[str, Any]:
    output = ensure_safe_output_root(output_root, project_root=project_root)
    inventory = read_inventory_csv(output / "manifests" / "source_inventory.csv")
    focus_records = [
        record for record in inventory if record.disposition in {"focusai", "duplicate"}
    ]
    errors: list[str] = []
    for record in focus_records:
        source = Path(record.path)
        if not source.is_file():
            errors.append(f"source missing: {source}")
        elif sha256_file(source) != record.sha256:
            errors.append(f"source hash changed: {source}")

    manifest_path = output / "manifests" / "clips_manifest.csv"
    clip_rows: list[dict[str, str]] = []
    if not manifest_path.is_file():
        errors.append(f"clip manifest missing: {manifest_path}")
    else:
        with manifest_path.open("r", newline="", encoding="utf-8-sig") as file:
            clip_rows = list(csv.DictReader(file))

    seen_clip_hashes: dict[str, str] = {}
    for row in clip_rows:
        clip = Path(row["clip_path"])
        if not clip.is_file():
            errors.append(f"clip missing: {clip}")
            continue
        meta = probe_video(clip)
        if not meta.opened or meta.frame_count <= 0:
            errors.append(f"clip unreadable: {clip}")
        scene = ReviewedScene(
            source_id=row["source_id"],
            start_sec=float(row["start_sec"]),
            end_sec=float(row["end_sec"]),
            label=row["label"],
            cue=row["cue"],
            disposition=row["disposition"],
            notes=row["notes"],
        )
        if clip.name != clip_filename(scene):
            errors.append(f"clip filename mismatch: {clip}")
        if scene.disposition in {"ready", "rule_validation"} and clip.parent.name != scene.label:
            errors.append(f"clip folder label mismatch: {clip}")
        digest = sha256_file(clip)
        if digest in seen_clip_hashes:
            errors.append(f"duplicate clip: {clip} matches {seen_clip_hashes[digest]}")
        else:
            seen_clip_hashes[digest] = str(clip)
    return {"source_count": len(focus_records), "clip_count": len(clip_rows), "errors": errors}
