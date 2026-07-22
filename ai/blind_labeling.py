from __future__ import annotations

import csv
import hashlib
import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping


class BlindLabelError(ValueError):
    pass


FORBIDDEN_COLUMNS = {
    "label",
    "suggested_label",
    "cue",
    "notes",
    "rule_state",
}
DIRECT_CLASSES = {"focus", "drowsy", "gaze_down", "gaze_side", "unknown"}
CONFIDENCE_LEVELS = {"high", "medium", "low"}


@dataclass(frozen=True)
class BlindInterval:
    blind_id: str
    source_group: str
    source_sha256: str
    source_path: Path
    start_sec: float
    end_sec: float


@dataclass(frozen=True)
class DirectLabel:
    blind_id: str
    direct_label: str
    confidence: str
    evidence: str
    review_status: str
    annotator: str
    annotated_at: str


def blind_id_for(source_sha256: str, start_sec: float, end_sec: float) -> str:
    payload = f"{source_sha256}|{start_sec:.3f}|{end_sec:.3f}".encode("utf-8")
    return "B" + hashlib.sha256(payload).hexdigest()[:12]


def _source_group_for(source_sha256: str) -> str:
    return "S" + hashlib.sha256(source_sha256.encode("utf-8")).hexdigest()[:12]


def validate_manifest_columns(columns: Iterable[str]) -> None:
    leaked = FORBIDDEN_COLUMNS.intersection(columns)
    if leaked:
        names = ", ".join(sorted(leaked))
        raise BlindLabelError(f"blind manifest contains forbidden columns: {names}")


def read_direct_labels(path: Path) -> list[DirectLabel]:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        required = {
            "blind_id",
            "direct_label",
            "confidence",
            "evidence",
            "review_status",
            "annotator",
            "annotated_at",
        }
        missing = required.difference(reader.fieldnames or [])
        if missing:
            names = ", ".join(sorted(missing))
            raise BlindLabelError(f"direct label file is missing columns: {names}")
        return [
            DirectLabel(
                blind_id=str(row["blind_id"]).strip(),
                direct_label=str(row["direct_label"]).strip(),
                confidence=str(row["confidence"]).strip(),
                evidence=str(row["evidence"]).strip(),
                review_status=str(row["review_status"]).strip(),
                annotator=str(row["annotator"]).strip(),
                annotated_at=str(row["annotated_at"]).strip(),
            )
            for row in reader
        ]


def validate_direct_labels(
    intervals: Iterable[BlindInterval],
    labels: Iterable[DirectLabel],
) -> None:
    interval_ids = {interval.blind_id for interval in intervals}
    label_rows = list(labels)
    label_ids = [label.blind_id for label in label_rows]
    if len(label_ids) != len(set(label_ids)):
        raise BlindLabelError("direct label file contains duplicate blind_id values")
    if set(label_ids) != interval_ids:
        missing = sorted(interval_ids.difference(label_ids))
        unknown = sorted(set(label_ids).difference(interval_ids))
        raise BlindLabelError(f"direct label IDs do not match intervals: missing={missing}, unknown={unknown}")

    for label in label_rows:
        if label.annotator != "codex_visual_direct":
            raise BlindLabelError(f"invalid annotator for {label.blind_id}")
        if not label.annotated_at:
            raise BlindLabelError(f"annotated_at is required for {label.blind_id}")
        if not label.evidence:
            raise BlindLabelError(f"evidence is required for {label.blind_id}")
        if label.review_status == "accepted":
            if label.direct_label not in DIRECT_CLASSES:
                raise BlindLabelError(f"invalid direct label for {label.blind_id}: {label.direct_label}")
            if label.confidence not in CONFIDENCE_LEVELS:
                raise BlindLabelError(f"invalid confidence for {label.blind_id}: {label.confidence}")
        elif label.review_status == "ambiguous":
            if label.direct_label or label.confidence:
                raise BlindLabelError(f"ambiguous item must not carry a label for {label.blind_id}")
        else:
            raise BlindLabelError(f"invalid review_status for {label.blind_id}: {label.review_status}")


def _split_interval(start_sec: float, end_sec: float) -> list[tuple[float, float]]:
    duration = end_sec - start_sec
    if duration <= 0:
        raise BlindLabelError("interval duration must be positive")

    full_chunks = int(math.floor(duration / 10.0))
    remainder = duration - (full_chunks * 10.0)
    intervals = [
        (start_sec + index * 10.0, start_sec + (index + 1) * 10.0)
        for index in range(full_chunks)
    ]
    cursor = start_sec + full_chunks * 10.0

    if remainder <= 1e-9:
        return intervals
    if remainder < 5.0 and intervals:
        previous_start, previous_end = intervals[-1]
        shift = 5.0 - remainder
        intervals[-1] = (previous_start, previous_end - shift)
        cursor -= shift
    intervals.append((cursor, end_sec))
    return intervals


def build_blind_intervals(rows: Iterable[Mapping[str, str]]) -> list[BlindInterval]:
    grouped: dict[str, list[tuple[float, float, Path]]] = defaultdict(list)
    for row in rows:
        source_sha256 = str(row["source_sha256"]).strip()
        source_path = Path(str(row["source_path"]))
        start_sec = float(row["start_sec"])
        end_sec = float(row["end_sec"])
        if not source_sha256:
            raise BlindLabelError("source_sha256 is required")
        if end_sec <= start_sec:
            raise BlindLabelError("end_sec must be greater than start_sec")
        grouped[source_sha256].append((start_sec, end_sec, source_path))

    intervals: list[BlindInterval] = []
    for source_sha256 in sorted(grouped):
        source_rows = sorted(grouped[source_sha256], key=lambda item: (item[0], item[1]))
        merged: list[list[object]] = []
        for start_sec, end_sec, source_path in source_rows:
            if not merged or start_sec > float(merged[-1][1]):
                merged.append([start_sec, end_sec, source_path])
                continue
            merged[-1][1] = max(float(merged[-1][1]), end_sec)

        source_group = _source_group_for(source_sha256)
        for start_sec_value, end_sec_value, source_path_value in merged:
            start_sec = float(start_sec_value)
            end_sec = float(end_sec_value)
            source_path = Path(source_path_value)
            for split_start, split_end in _split_interval(start_sec, end_sec):
                intervals.append(
                    BlindInterval(
                        blind_id=blind_id_for(source_sha256, split_start, split_end),
                        source_group=source_group,
                        source_sha256=source_sha256,
                        source_path=source_path,
                        start_sec=split_start,
                        end_sec=split_end,
                    )
                )

    return sorted(intervals, key=lambda item: (item.source_group, item.start_sec, item.end_sec))
