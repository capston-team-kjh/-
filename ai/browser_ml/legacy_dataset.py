from __future__ import annotations

import csv
import json
import math
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .contracts import FeatureContract
from .legacy_sources import (
    HUMAN_CORRECTED,
    HUMAN_DIRECT,
    LegacyLabel,
    LegacyLabelRegistry,
    RULE_PSEUDO,
    VISUAL_DIRECT,
)


HUMAN_TEST_GROUP = "2026-06-28 16-04-40"
HUMAN_VALIDATION_GROUP = "2026-05-27 12-55-27"
LABEL_PRIORITY = {
    HUMAN_DIRECT: 0,
    HUMAN_CORRECTED: 1,
    VISUAL_DIRECT: 2,
    RULE_PSEUDO: 3,
}


class LeakageError(ValueError):
    """Raised when one leakage identity appears in multiple dataset splits."""


@dataclass(frozen=True)
class FeatureExclusion:
    label_id: str
    source_path: str
    timestamp_ms: int | None
    reason: str
    detail: str = ""


@dataclass(frozen=True)
class LegacyDatasetResult:
    rows: tuple[dict[str, Any], ...]
    exclusions: tuple[FeatureExclusion, ...]
    summary: dict[str, Any]


def _timestamp(row: Mapping[str, Any]) -> int:
    try:
        value = float(row.get("timestamp_ms", ""))
    except (TypeError, ValueError) as error:
        raise ValueError("feature row timestamp_ms must be numeric") from error
    if not math.isfinite(value) or value < 0:
        raise ValueError("feature row timestamp_ms must be finite and non-negative")
    return int(round(value))


def _is_model_ready(row: Mapping[str, Any], contract: FeatureContract) -> bool:
    ready = row.get("vector_ready")
    if isinstance(ready, str):
        ready = ready.strip().lower() in {"true", "1", "yes"}
    if ready is not True:
        return False
    for name in contract.feature_names:
        try:
            value = float(row.get(name, ""))
        except (TypeError, ValueError):
            return False
        if not math.isfinite(value):
            return False
    return True


def _matching_rows(
    rows: Sequence[Mapping[str, Any]],
    label: LegacyLabel,
    *,
    point_tolerance_ms: int,
) -> tuple[Mapping[str, Any], ...]:
    if label.timestamp_ms is not None:
        if not rows:
            return ()
        nearest = min(rows, key=lambda row: abs(_timestamp(row) - label.timestamp_ms))
        return (nearest,) if abs(_timestamp(nearest) - label.timestamp_ms) <= point_tolerance_ms else ()
    if label.start_ms is None or label.end_ms is None:
        return ()
    return tuple(
        row for row in rows if label.start_ms <= _timestamp(row) < label.end_ms
    )


def _split_for(label: LegacyLabel) -> str:
    if label.source_group_id == HUMAN_TEST_GROUP:
        return "test"
    if label.source_group_id == HUMAN_VALIDATION_GROUP:
        return "validation"
    if label.split_hint == "test":
        return "test"
    return "train"


def _dataset_row(
    feature: Mapping[str, Any],
    label: LegacyLabel,
    contract: FeatureContract,
) -> dict[str, Any]:
    timestamp_ms = _timestamp(feature)
    row: dict[str, Any] = {
        "subject_id": "",
        "subject_id_known": False,
        "session_id": label.source_group_id,
        "source_id": label.source_id,
        "source_group_id": label.source_group_id,
        "source_path": str(label.source_path),
        "source_sha256": label.source_sha256,
        "camera_role": contract.camera_role,
        "environment_id": "",
        "environment_id_known": False,
        "camera_setup_id": "",
        "camera_setup_id_known": False,
        "timestamp_ms": timestamp_ms,
        "label": label.label,
        "label_id": label.label_id,
        "label_identity": f"{label.label_source}:{label.label_id}",
        "label_category": label.category,
        "label_source": label.label_source,
        "review_status": label.review_status,
        "label_confidence": label.confidence,
        "annotator": label.annotator,
        "label_interval_start_ms": label.start_ms if label.start_ms is not None else label.timestamp_ms,
        "label_interval_end_ms": label.end_ms if label.end_ms is not None else label.timestamp_ms,
        "split": _split_for(label),
    }
    row.update({name: float(feature[name]) for name in contract.feature_names})
    return row


def join_source_labels(
    feature_rows: Sequence[Mapping[str, Any]],
    labels: Sequence[LegacyLabel],
    contract: FeatureContract,
    *,
    point_tolerance_ms: int = 500,
) -> tuple[tuple[dict[str, Any], ...], tuple[FeatureExclusion, ...]]:
    if point_tolerance_ms < 0:
        raise ValueError("point_tolerance_ms must be non-negative")
    sorted_features = sorted(feature_rows, key=_timestamp)
    candidates: dict[int, list[tuple[LegacyLabel, Mapping[str, Any]]]] = defaultdict(list)
    exclusions: list[FeatureExclusion] = []

    for label in labels:
        if not label.eligible or label.label not in contract.class_names:
            exclusions.append(
                FeatureExclusion(
                    label.label_id,
                    str(label.source_path),
                    label.timestamp_ms,
                    label.exclusion_reason or "label_not_model_eligible",
                )
            )
            continue
        matches = _matching_rows(sorted_features, label, point_tolerance_ms=point_tolerance_ms)
        if not matches:
            exclusions.append(
                FeatureExclusion(
                    label.label_id,
                    str(label.source_path),
                    label.timestamp_ms,
                    "label_has_no_aligned_feature_row",
                )
            )
            continue
        for feature in matches:
            candidates[_timestamp(feature)].append((label, feature))

    rows: list[dict[str, Any]] = []
    for timestamp_ms, assignments in sorted(candidates.items()):
        best_priority = min(LABEL_PRIORITY.get(label.category, 99) for label, _ in assignments)
        prioritized = [item for item in assignments if LABEL_PRIORITY.get(item[0].category, 99) == best_priority]
        labels_at_priority = {label.label for label, _ in prioritized}
        if len(labels_at_priority) != 1:
            for label, _ in prioritized:
                exclusions.append(
                    FeatureExclusion(
                        label.label_id,
                        str(label.source_path),
                        timestamp_ms,
                        "conflicting_labels_at_same_timestamp",
                        "|".join(sorted(labels_at_priority)),
                    )
                )
            continue
        selected_label, selected_feature = sorted(
            prioritized,
            key=lambda item: (item[0].label_source, item[0].label_id),
        )[0]
        if not _is_model_ready(selected_feature, contract):
            exclusions.append(
                FeatureExclusion(
                    selected_label.label_id,
                    str(selected_label.source_path),
                    timestamp_ms,
                    "feature_row_not_model_ready",
                    str(selected_feature.get("missing_features") or ""),
                )
            )
            continue
        rows.append(_dataset_row(selected_feature, selected_label, contract))
    return tuple(rows), tuple(exclusions)


def validate_split_leakage(rows: Sequence[Mapping[str, Any]]) -> None:
    identity_fields = (
        "source_group_id",
        "session_id",
        "source_sha256",
        "source_id",
        "label_identity",
    )
    for field in identity_fields:
        splits_by_value: dict[str, set[str]] = defaultdict(set)
        for row in rows:
            value = str(row.get(field) or "").strip()
            split = str(row.get("split") or "").strip()
            if value and split:
                splits_by_value[value].add(split)
        leaking = sorted(value for value, splits in splits_by_value.items() if len(splits) > 1)
        if leaking:
            raise LeakageError(f"{field} crosses dataset splits: {', '.join(leaking[:5])}")


def build_legacy_dataset(
    features_by_source: Mapping[Path, Sequence[Mapping[str, Any]]],
    registry: LegacyLabelRegistry,
    contract: FeatureContract,
) -> LegacyDatasetResult:
    labels_by_source: dict[str, list[LegacyLabel]] = defaultdict(list)
    for label in registry.labels:
        labels_by_source[str(label.source_path.resolve()).casefold()].append(label)

    rows: list[dict[str, Any]] = []
    exclusions: list[FeatureExclusion] = []
    for source_path, feature_rows in features_by_source.items():
        key = str(source_path.resolve()).casefold()
        joined, source_exclusions = join_source_labels(
            feature_rows,
            labels_by_source.get(key, ()),
            contract,
        )
        rows.extend(joined)
        exclusions.extend(source_exclusions)
    matched_sources = {str(path.resolve()).casefold() for path in features_by_source}
    for source_key, source_labels in labels_by_source.items():
        if source_key in matched_sources:
            continue
        exclusions.extend(
            FeatureExclusion(
                label.label_id,
                str(label.source_path),
                label.timestamp_ms,
                "feature_cache_missing_for_source",
            )
            for label in source_labels
        )

    validate_split_leakage(rows)
    class_counts = Counter(str(row["label"]) for row in rows)
    split_counts = Counter(str(row["split"]) for row in rows)
    label_category_counts = Counter(str(row["label_category"]) for row in rows)
    summary = {
        "row_count": len(rows),
        "source_count": len({str(row["source_sha256"]) for row in rows}),
        "session_count": len({str(row["session_id"]) for row in rows}),
        "known_subject_count": 0,
        "subject_generalization_valid": False,
        "evaluation_scope": "source_session_generalization",
        "class_row_counts": dict(sorted(class_counts.items())),
        "split_row_counts": dict(sorted(split_counts.items())),
        "label_category_row_counts": dict(sorted(label_category_counts.items())),
        "exclusion_count": len(exclusions),
        "exclusion_reason_counts": dict(
            sorted(Counter(item.reason for item in exclusions).items())
        ),
    }
    return LegacyDatasetResult(tuple(rows), tuple(exclusions), summary)


def write_legacy_dataset(result: LegacyDatasetResult, output_dir: Path, contract: FeatureContract) -> dict[str, Path]:
    output = output_dir.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite dataset output directory: {output}")
    output.mkdir(parents=True)
    dataset_path = output / "focus-state-v2-legacy.csv"
    exclusions_path = output / "excluded_rows.csv"
    summary_path = output / "dataset_summary.json"
    metadata_columns = [
        "subject_id", "subject_id_known", "session_id", "source_id", "source_group_id",
        "source_path", "source_sha256", "camera_role", "environment_id",
        "environment_id_known", "camera_setup_id", "camera_setup_id_known", "timestamp_ms",
        "label", "label_id", "label_identity", "label_category", "label_source",
        "review_status", "label_confidence", "annotator", "label_interval_start_ms",
        "label_interval_end_ms", "split",
    ]
    with dataset_path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=[*metadata_columns, *contract.feature_names])
        writer.writeheader()
        writer.writerows(result.rows)
    with exclusions_path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=list(asdict(FeatureExclusion("", "", None, ""))))
        writer.writeheader()
        writer.writerows(asdict(item) for item in result.exclusions)
    summary_path.write_text(json.dumps(result.summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"dataset": dataset_path, "exclusions": exclusions_path, "summary": summary_path}
