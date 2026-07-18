from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Sequence


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
