from __future__ import annotations

import csv
import hashlib
import json
import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

import cv2
import numpy as np

from ai.training_scene_prep import _contact_tile, _frame_at


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


def write_blind_contact_sheet(interval: BlindInterval, output_path: Path) -> Path:
    capture = cv2.VideoCapture(str(interval.source_path))
    if not capture.isOpened():
        raise BlindLabelError(f"could not open source video for {interval.blind_id}")
    duration = interval.end_sec - interval.start_sec
    timestamps = [
        interval.start_sec + duration * ratio
        for ratio in (0.0, 0.25, 0.5, 0.75, 0.999)
    ]
    try:
        tiles = [
            _contact_tile(
                _frame_at(capture, timestamp),
                f"{timestamp - interval.start_sec:.1f}s",
                tile_width=240,
            )
            for timestamp in timestamps
        ]
    finally:
        capture.release()

    sheet = np.hstack(tiles)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(output_path), sheet):
        raise BlindLabelError(f"could not write contact sheet for {interval.blind_id}")
    return output_path


def write_review_workspace(clips_manifest_path: Path, output_root: Path) -> dict[str, object]:
    if output_root.exists() and any(output_root.iterdir()):
        raise BlindLabelError(f"review workspace is not empty: {output_root}")

    with clips_manifest_path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        input_rows = list(reader)
    required = {"source_id", "source_path", "source_sha256", "start_sec", "end_sec"}
    missing = required.difference(input_rows[0].keys() if input_rows else set())
    if missing:
        names = ", ".join(sorted(missing))
        raise BlindLabelError(f"clips manifest is missing columns: {names}")

    safe_rows = [
        {
            "source_path": row["source_path"],
            "source_sha256": row["source_sha256"],
            "start_sec": row["start_sec"],
            "end_sec": row["end_sec"],
        }
        for row in input_rows
    ]
    intervals = build_blind_intervals(safe_rows)
    source_metadata = {
        str(row["source_sha256"]): {
            "source_id": str(row["source_id"]),
            "analysis_json": str(
                clips_manifest_path.parent.parent / "analysis" / f"{row['source_id']}.json"
            ),
        }
        for row in input_rows
    }

    contact_root = output_root / "contact_sheets"
    private_root = output_root / "private"
    contact_root.mkdir(parents=True, exist_ok=True)
    private_root.mkdir(parents=True, exist_ok=True)

    review_fields = [
        "blind_id",
        "sheet_path",
        "direct_label",
        "confidence",
        "evidence",
        "review_status",
        "annotator",
        "annotated_at",
    ]
    review_rows: list[dict[str, str]] = []
    source_rows: list[dict[str, object]] = []
    for interval in intervals:
        relative_sheet = Path("contact_sheets") / f"{interval.blind_id}.jpg"
        write_blind_contact_sheet(interval, output_root / relative_sheet)
        review_rows.append(
            {
                "blind_id": interval.blind_id,
                "sheet_path": relative_sheet.as_posix(),
                "direct_label": "",
                "confidence": "",
                "evidence": "",
                "review_status": "",
                "annotator": "",
                "annotated_at": "",
            }
        )
        metadata = source_metadata[interval.source_sha256]
        source_rows.append(
            {
                "blind_id": interval.blind_id,
                "source_group": interval.source_group,
                "source_sha256": interval.source_sha256,
                "source_id": metadata["source_id"],
                "source_path": str(interval.source_path),
                "start_sec": interval.start_sec,
                "end_sec": interval.end_sec,
                "analysis_json": metadata["analysis_json"],
                "sheet_path": str(output_root / relative_sheet),
            }
        )

    review_path = output_root / "blind_review.csv"
    with review_path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=review_fields)
        writer.writeheader()
        writer.writerows(review_rows)

    source_fields = [
        "blind_id",
        "source_group",
        "source_sha256",
        "source_id",
        "source_path",
        "start_sec",
        "end_sec",
        "analysis_json",
        "sheet_path",
    ]
    with (private_root / "source_map.csv").open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=source_fields)
        writer.writeheader()
        writer.writerows(source_rows)

    summary: dict[str, object] = {
        "input_clips": len(input_rows),
        "source_count": len({interval.source_group for interval in intervals}),
        "interval_count": len(intervals),
        "pending_count": len(intervals),
        "label_source": "codex_visual_direct",
    }
    (output_root / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return summary


def _read_workspace_intervals(output_root: Path) -> list[BlindInterval]:
    source_map_path = output_root / "private" / "source_map.csv"
    with source_map_path.open(newline="", encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    return [
        BlindInterval(
            blind_id=str(row["blind_id"]),
            source_group=str(row["source_group"]),
            source_sha256=str(row["source_sha256"]),
            source_path=Path(str(row["source_path"])),
            start_sec=float(row["start_sec"]),
            end_sec=float(row["end_sec"]),
        )
        for row in rows
    ]


def record_review_decisions(
    output_root: Path,
    decisions: Iterable[DirectLabel],
) -> dict[str, int]:
    decision_rows = list(decisions)
    decision_ids = [decision.blind_id for decision in decision_rows]
    if len(decision_ids) != len(set(decision_ids)):
        raise BlindLabelError("review decisions contain duplicate blind_id values")

    interval_by_id = {
        interval.blind_id: interval for interval in _read_workspace_intervals(output_root)
    }
    unknown = sorted(set(decision_ids).difference(interval_by_id))
    if unknown:
        raise BlindLabelError(f"review decisions contain unknown IDs: {unknown}")
    for decision in decision_rows:
        validate_direct_labels([interval_by_id[decision.blind_id]], [decision])

    review_path = output_root / "blind_review.csv"
    with review_path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        fields = list(reader.fieldnames or [])
        validate_manifest_columns(fields)
        rows = list(reader)
    row_by_id = {str(row["blind_id"]).strip(): row for row in rows}

    recorded_count = 0
    decision_fields = [
        "direct_label",
        "confidence",
        "evidence",
        "review_status",
        "annotator",
        "annotated_at",
    ]
    for decision in decision_rows:
        row = row_by_id[decision.blind_id]
        new_values = {field: str(getattr(decision, field)) for field in decision_fields}
        existing_values = {field: str(row[field]).strip() for field in decision_fields}
        if existing_values["review_status"]:
            if existing_values != new_values:
                raise BlindLabelError(
                    f"refusing to overwrite an existing review decision: {decision.blind_id}"
                )
            continue
        row.update(new_values)
        recorded_count += 1

    temporary_path = review_path.with_suffix(".csv.tmp")
    with temporary_path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    temporary_path.replace(review_path)
    remaining_count = sum(not str(row["review_status"]).strip() for row in rows)
    return {
        "recorded_count": recorded_count,
        "remaining_count": remaining_count,
    }


def verify_review_workspace(output_root: Path, *, allow_pending: bool = False) -> dict[str, object]:
    intervals = _read_workspace_intervals(output_root)
    review_path = output_root / "blind_review.csv"
    with review_path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        validate_manifest_columns(reader.fieldnames or [])
        rows = list(reader)

    interval_by_id = {interval.blind_id: interval for interval in intervals}
    row_ids = [str(row.get("blind_id", "")).strip() for row in rows]
    if len(row_ids) != len(set(row_ids)):
        raise BlindLabelError("blind review contains duplicate blind_id values")
    if set(row_ids) != set(interval_by_id):
        raise BlindLabelError("blind review IDs do not match private source map")

    completed: list[DirectLabel] = []
    pending_count = 0
    missing_sheets: list[str] = []
    for row in rows:
        blind_id = str(row["blind_id"]).strip()
        sheet_path = output_root / str(row["sheet_path"])
        if not sheet_path.is_file():
            missing_sheets.append(blind_id)
        review_status = str(row["review_status"]).strip()
        if not review_status:
            review_values = [
                str(row[field]).strip()
                for field in ("direct_label", "confidence", "evidence", "annotator", "annotated_at")
            ]
            if any(review_values):
                raise BlindLabelError(f"pending row is partially filled: {blind_id}")
            pending_count += 1
            continue
        completed.append(
            DirectLabel(
                blind_id=blind_id,
                direct_label=str(row["direct_label"]).strip(),
                confidence=str(row["confidence"]).strip(),
                evidence=str(row["evidence"]).strip(),
                review_status=review_status,
                annotator=str(row["annotator"]).strip(),
                annotated_at=str(row["annotated_at"]).strip(),
            )
        )

    if missing_sheets:
        raise BlindLabelError(f"missing contact sheets: {missing_sheets}")
    if completed:
        validate_direct_labels([interval_by_id[label.blind_id] for label in completed], completed)
    if pending_count and not allow_pending:
        raise BlindLabelError(f"blind review still has {pending_count} pending rows")

    return {
        "interval_count": len(intervals),
        "completed_count": len(completed),
        "pending_count": pending_count,
        "missing_sheet_count": len(missing_sheets),
    }


def freeze_review_workspace(
    output_root: Path,
    labels_output: Path,
    summary_output: Path,
) -> dict[str, object]:
    verification = verify_review_workspace(output_root)
    review_path = output_root / "blind_review.csv"
    labels = read_direct_labels(review_path)
    intervals = _read_workspace_intervals(output_root)
    validate_direct_labels(intervals, labels)

    labels_output.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "blind_id",
        "direct_label",
        "confidence",
        "evidence",
        "review_status",
        "annotator",
        "annotated_at",
    ]
    with labels_output.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for label in labels:
            writer.writerow({field: getattr(label, field) for field in fields})

    freeze_sha256 = hashlib.sha256(labels_output.read_bytes()).hexdigest()
    label_counts: dict[str, int] = defaultdict(int)
    accepted_count = 0
    ambiguous_count = 0
    for label in labels:
        if label.review_status == "accepted":
            accepted_count += 1
            label_counts[label.direct_label] += 1
        else:
            ambiguous_count += 1

    summary: dict[str, object] = {
        **verification,
        "accepted_count": accepted_count,
        "ambiguous_count": ambiguous_count,
        "label_counts": dict(sorted(label_counts.items())),
        "label_source": "codex_visual_direct",
        "label_freeze_sha256": freeze_sha256,
    }
    summary_output.parent.mkdir(parents=True, exist_ok=True)
    summary_output.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_root / "freeze.json").write_text(
        json.dumps(
            {
                "label_freeze_sha256": freeze_sha256,
                "labels_output": str(labels_output.resolve()),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return summary
