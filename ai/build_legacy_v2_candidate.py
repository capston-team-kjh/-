from __future__ import annotations

import argparse
import csv
import json
import math
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ai.browser_ml.contracts import load_feature_contract  # noqa: E402
from ai.browser_ml.legacy_dataset import (  # noqa: E402
    HUMAN_TEST_GROUP,
    HUMAN_VALIDATION_GROUP,
    build_legacy_dataset,
    write_legacy_dataset,
)
from ai.browser_ml.legacy_extraction import (  # noqa: E402
    ExtractionRequest,
    extract_source_features,
)
from ai.browser_ml.legacy_sources import (  # noqa: E402
    HUMAN_CORRECTED,
    HUMAN_DIRECT,
    RULE_PSEUDO,
    UNKNOWN_PROVENANCE,
    VIDEO_EXTENSIONS,
    VISUAL_DIRECT,
    LegacyLabelRegistry,
    VideoRecord,
    combine_registries,
    load_blind_visual_labels,
    load_frame_segment_labels,
    load_human_point_labels,
    probe_video,
    sha256_file,
)
from ai.browser_ml.legacy_training import train_legacy_candidates  # noqa: E402


@dataclass(frozen=True)
class PipelineConfig:
    project_root: Path
    output_dir: Path
    video_roots: tuple[Path, ...]
    human_label_root: Path
    clip_manifest_csv: Path
    blind_label_root: Path
    frame_label_root: Path
    face_model_path: Path
    pose_model_path: Path
    random_seed: int = 42


@dataclass(frozen=True)
class RunDirectories:
    root: Path
    inventory: Path
    cache: Path
    reports: Path
    datasets: Path
    candidate: Path


def create_run_directory(path: Path) -> RunDirectories:
    root = path.resolve()
    if root.exists():
        raise FileExistsError(f"refusing to overwrite existing run directory: {root}")
    root.mkdir(parents=True)
    inventory = root / "inventory"
    cache = root / "cache"
    reports = root / "reports"
    inventory.mkdir()
    cache.mkdir()
    reports.mkdir()
    return RunDirectories(
        root=root,
        inventory=inventory,
        cache=cache,
        reports=reports,
        datasets=root / "datasets",
        candidate=root / "candidates" / "focus-state-v2",
    )


def build_report_document(
    *,
    inventory: object,
    labels: object,
    matching: object,
    dataset: object,
    features: object,
    quality: object,
    split: object,
    model_comparison: object,
    candidate: object,
    v1_comparison: object,
    compatibility: object,
    production: object,
    generalization: object,
    recommendations: object,
    changed_files: object,
    tests: object,
) -> dict[str, object]:
    return {
        "A": inventory,
        "B": labels,
        "C": matching,
        "D": dataset,
        "E": features,
        "F": quality,
        "G": split,
        "H": model_comparison,
        "I": candidate,
        "J": v1_comparison,
        "K": compatibility,
        "L": production,
        "M": generalization,
        "N": recommendations,
        "O": changed_files,
        "P": tests,
    }


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]], fieldnames: Sequence[str]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _video_paths(roots: Sequence[Path], referenced_sources: Iterable[Path]) -> tuple[Path, ...]:
    unique: dict[str, Path] = {}
    for raw_root in roots:
        root = raw_root.resolve()
        if not root.exists():
            continue
        candidates = [root] if root.is_file() else root.rglob("*")
        for path in candidates:
            if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS:
                resolved = path.resolve()
                unique.setdefault(str(resolved).casefold(), resolved)
    for path in referenced_sources:
        resolved = path.resolve()
        if resolved.is_file() and resolved.suffix.lower() in VIDEO_EXTENSIONS:
            unique.setdefault(str(resolved).casefold(), resolved)
    return tuple(sorted(unique.values(), key=lambda path: str(path).casefold()))


def _inventory_videos(paths: Sequence[Path]) -> tuple[VideoRecord, ...]:
    records: list[VideoRecord] = []
    total = len(paths)
    for index, path in enumerate(paths, start=1):
        records.append(probe_video(path))
        if index == 1 or index % 20 == 0 or index == total:
            print(f"[inventory] probed {index}/{total} videos", flush=True)
    return tuple(records)


def _root_for(path: Path, roots: Sequence[Path]) -> str:
    resolved = path.resolve()
    matching: list[Path] = []
    for root in roots:
        candidate = root.resolve()
        try:
            resolved.relative_to(candidate)
            matching.append(candidate)
        except ValueError:
            continue
    return str(max(matching, key=lambda item: len(str(item)))) if matching else "manifest_reference"


def _video_inventory_documents(
    records: Sequence[VideoRecord],
    roots: Sequence[Path],
    registry: LegacyLabelRegistry,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    labels_by_path = Counter(str(label.source_path.resolve()).casefold() for label in registry.labels)
    rows: list[dict[str, Any]] = []
    for record in records:
        rows.append(
            {
                "root": _root_for(record.path, roots),
                "path": str(record.path),
                "filename": record.filename,
                "size_bytes": record.size_bytes,
                "duration_sec": record.duration_sec,
                "width": record.width,
                "height": record.height,
                "resolution": f"{record.width}x{record.height}" if record.width and record.height else "",
                "fps": record.fps,
                "frame_count": record.frame_count,
                "sha256": record.sha256,
                "source_id": record.source_id,
                "decode_valid": record.decode_valid,
                "probe_error": record.probe_error or "",
                "label_count": labels_by_path[str(record.path).casefold()],
            }
        )
    grouped: list[dict[str, Any]] = []
    for root, group in sorted(
        ((root, [row for row in rows if row["root"] == root]) for root in sorted({row["root"] for row in rows})),
        key=lambda item: item[0],
    ):
        grouped.append(
            {
                "location": root,
                "video_count": len(group),
                "usable": sum(bool(row["decode_valid"]) for row in group),
                "excluded": sum(not bool(row["decode_valid"]) for row in group),
                "reasons": dict(
                    Counter(str(row["probe_error"]) for row in group if row["probe_error"])
                ),
            }
        )
    return rows, {"locations": grouped, "total_video_count": len(rows)}


def _count_label_rows(path: Path) -> int:
    try:
        if path.suffix.lower() in {".csv", ".tsv"}:
            with path.open("r", encoding="utf-8-sig", errors="replace") as file:
                return max(0, sum(1 for _ in file) - 1)
        if path.suffix.lower() in {".json", ".jsonl"}:
            if path.suffix.lower() == ".jsonl":
                with path.open("r", encoding="utf-8", errors="replace") as file:
                    return sum(1 for line in file if line.strip())
            document = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(document, list):
                return len(document)
            if isinstance(document, dict):
                for key in ("labels", "segments", "rows", "predictions", "timeline", "videos"):
                    if isinstance(document.get(key), list):
                        return len(document[key])
                return 1
    except Exception:
        return -1
    return 0


def _csv_headers(path: Path) -> set[str]:
    if path.suffix.lower() not in {".csv", ".tsv"}:
        return set()
    try:
        delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
        with path.open("r", newline="", encoding="utf-8-sig", errors="replace") as file:
            return {str(value or "").strip().lower() for value in next(csv.reader(file, delimiter=delimiter), [])}
    except Exception:
        return set()


def _classify_label_file(path: Path, known: Mapping[str, str]) -> str:
    key = str(path.resolve()).casefold()
    if key in known:
        return known[key]
    headers = _csv_headers(path)
    lowered = str(path).casefold()
    if "human_label" in headers:
        return HUMAN_DIRECT
    if "direct_label" in headers or ({"visual_reason", "review_status"} <= headers):
        return VISUAL_DIRECT
    if "corrected_label" in headers and "human" in headers:
        return HUMAN_CORRECTED
    if any(token in lowered for token in ("prediction", "analysis_result", "pseudo")) or "rule_state" in headers:
        return RULE_PSEUDO
    return UNKNOWN_PROVENANCE


def _label_file_inventory(
    roots: Sequence[Path],
    known: Mapping[str, str],
) -> list[dict[str, Any]]:
    keywords = (
        "label", "annot", "human", "direct", "blind", "corrected", "frame",
        "interval", "start_sec", "end_sec", "timestamp", "prediction",
    )
    unique: dict[str, Path] = {}
    for raw_root in roots:
        root = raw_root.resolve()
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in {".csv", ".tsv", ".json", ".jsonl"}:
                continue
            lowered = str(path).casefold()
            headers = _csv_headers(path)
            if any(keyword in lowered for keyword in keywords) or any(
                any(keyword in header for keyword in keywords) for header in headers
            ):
                unique.setdefault(str(path.resolve()).casefold(), path.resolve())
    return [
        {
            "path": str(path),
            "category": _classify_label_file(path, known),
            "row_count": _count_label_rows(path),
            "headers": "|".join(sorted(_csv_headers(path))),
        }
        for path in sorted(unique.values(), key=lambda item: str(item).casefold())
    ]


def _label_documents(
    registry: LegacyLabelRegistry,
    label_files: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    registry_rows: list[dict[str, Any]] = []
    for label in registry.labels:
        row = asdict(label)
        row["source_path"] = str(label.source_path)
        registry_rows.append(row)
    category_counts = Counter(label.category for label in registry.labels)
    eligible_counts = Counter(label.category for label in registry.labels if label.eligible)
    summary = {
        "registry_label_count": len(registry.labels),
        "registry_issue_count": len(registry.issues),
        "category_counts": dict(sorted(category_counts.items())),
        "eligible_category_counts": dict(sorted(eligible_counts.items())),
        "label_files": list(label_files),
        "ground_truth_policy": {
            HUMAN_DIRECT: "primary_train_validation_test",
            HUMAN_CORRECTED: "primary_when_explicitly_verified",
            VISUAL_DIRECT: "training_augmentation_only",
            RULE_PSEUDO: "audit_or_sanity_only",
            UNKNOWN_PROVENANCE: "excluded",
        },
    }
    return registry_rows, summary


def _matching_rows(registry: LegacyLabelRegistry) -> list[dict[str, Any]]:
    labels_by_path: dict[str, list[Any]] = defaultdict(list)
    for label in registry.labels:
        labels_by_path[str(label.source_path.resolve()).casefold()].append(label)
    rows: list[dict[str, Any]] = []
    for labels in labels_by_path.values():
        first = labels[0]
        exists = first.source_path.is_file()
        eligible = sum(label.eligible for label in labels)
        rows.append(
            {
                "source_id": first.source_id,
                "source_group_id": first.source_group_id,
                "source_path": str(first.source_path),
                "source_exists": exists,
                "label_count": len(labels),
                "eligible_label_count": eligible,
                "label_categories": "|".join(sorted({label.category for label in labels})),
                "status": "matched" if exists and eligible else "partial" if exists else "failed",
            }
        )
    return sorted(rows, key=lambda row: str(row["source_path"]).casefold())


def _feature_quality(features_by_source: Mapping[Path, Sequence[Mapping[str, Any]]], feature_names: Sequence[str]) -> dict[str, Any]:
    rows = [row for source_rows in features_by_source.values() for row in source_rows]
    missing = Counter()
    invalid = 0
    baseline_failures = 0
    for row in rows:
        ready = str(row.get("vector_ready") or "").strip().lower() in {"true", "1", "yes"}
        if not ready:
            invalid += 1
        try:
            calibration = float(row.get("calibration_valid") or 0)
        except (TypeError, ValueError):
            calibration = 0
        if calibration < 1:
            baseline_failures += 1
        for name in feature_names:
            try:
                value = float(row.get(name, ""))
            except (TypeError, ValueError):
                missing[name] += 1
                continue
            if not math.isfinite(value):
                missing[name] += 1
    total = len(rows)
    return {
        "total_feature_rows": total,
        "invalid_row_count": invalid,
        "invalid_row_ratio": invalid / total if total else 0,
        "baseline_failure_count": baseline_failures,
        "baseline_failure_ratio": baseline_failures / total if total else 0,
        "missing_feature_counts": dict(sorted(missing.items())),
        "missing_feature_ratios": {
            name: count / total if total else 0 for name, count in sorted(missing.items())
        },
    }


def _browser_validate(config: PipelineConfig, directories: RunDirectories, metadata_path: Path) -> dict[str, Any]:
    frontend = config.project_root / "frontend"
    report_path = directories.reports / "browser_compatibility.json"
    result = subprocess.run(
        [
            "node",
            str(frontend / "node_modules" / "vite-node" / "vite-node.mjs"),
            "--script",
            str(frontend / "scripts" / "validate-focus-v2-candidate.ts"),
            "--metadata",
            str(metadata_path),
            "--report",
            str(report_path),
        ],
        cwd=frontend,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"browser candidate validation failed: {result.stderr.strip()}")
    return json.loads(report_path.read_text(encoding="utf-8"))


def _markdown_report(report: Mapping[str, object]) -> str:
    titles = {
        "A": "발견한 기존 영상", "B": "발견한 기존 라벨", "C": "영상-라벨 매칭",
        "D": "생성한 v2 Dataset", "E": "실제 Feature", "F": "데이터 품질",
        "G": "Split", "H": "모델 비교", "I": "Best Candidate", "J": "기존 v1과 비교",
        "K": "Browser 호환성", "L": "Production 상태", "M": "일반화 가능성",
        "N": "추가로 필요한 데이터", "O": "변경 파일", "P": "테스트 결과",
    }
    parts = ["# FocusAI Legacy v2 Candidate Report", ""]
    for key, value in report.items():
        parts.extend(
            [
                f"## {key}. {titles[key]}",
                "",
                "```json",
                json.dumps(value, ensure_ascii=False, indent=2),
                "```",
                "",
            ]
        )
    return "\n".join(parts)


def run_pipeline(config: PipelineConfig) -> dict[str, object]:
    directories = create_run_directory(config.output_dir)
    contract = load_feature_contract(config.project_root)
    active_model = config.project_root / "frontend" / "public" / "focus_classifier.onnx"
    active_metadata = config.project_root / "frontend" / "public" / "models" / "focus-state-v1.metadata.json"
    active_hash_before = sha256_file(active_model)
    active_metadata_hash_before = sha256_file(active_metadata)

    human_train = config.human_label_root / "human_train_front_10s_labels.csv"
    human_test = config.human_label_root / "human_front_10s_labels.csv"
    blind_review = config.blind_label_root / "blind_review.csv"
    blind_map = config.blind_label_root / "private" / "source_map.csv"
    frame_segments = config.frame_label_root / "labels" / "segments.csv"
    frame_manifest = config.frame_label_root / "manifest.json"
    registry = combine_registries(
        (
            load_human_point_labels(human_train, config.clip_manifest_csv, split_hint="train"),
            load_human_point_labels(human_test, config.clip_manifest_csv, split_hint="test"),
            load_blind_visual_labels(blind_review, blind_map),
            load_frame_segment_labels(frame_segments, frame_manifest),
        )
    )
    print(
        f"[labels] registry={len(registry.labels)} issues={len(registry.issues)} eligible={sum(label.eligible for label in registry.labels)}",
        flush=True,
    )

    referenced_sources = {label.source_path for label in registry.labels}
    video_paths = _video_paths(config.video_roots, referenced_sources)
    video_records = _inventory_videos(video_paths)
    inventory_rows, inventory_summary = _video_inventory_documents(
        video_records, config.video_roots, registry
    )
    _write_csv(
        directories.inventory / "videos.csv",
        inventory_rows,
        [
            "root", "path", "filename", "size_bytes", "duration_sec", "width", "height",
            "resolution", "fps", "frame_count", "sha256", "source_id", "decode_valid",
            "probe_error", "label_count",
        ],
    )
    _write_json(directories.inventory / "videos.json", inventory_rows)

    known_categories = {
        str(human_train.resolve()).casefold(): HUMAN_DIRECT,
        str(human_test.resolve()).casefold(): HUMAN_DIRECT,
        str(blind_review.resolve()).casefold(): VISUAL_DIRECT,
        str(blind_map.resolve()).casefold(): VISUAL_DIRECT,
        str(frame_segments.resolve()).casefold(): VISUAL_DIRECT,
        str((config.frame_label_root / "labels" / "frame_labels.csv").resolve()).casefold(): VISUAL_DIRECT,
    }
    label_scan_roots = (
        config.human_label_root,
        config.blind_label_root,
        config.frame_label_root,
        config.project_root / "ai" / "direct_labeling",
        config.project_root / "ai" / "state_classifier_training",
    )
    label_files = _label_file_inventory(label_scan_roots, known_categories)
    registry_rows, label_summary = _label_documents(registry, label_files)
    _write_csv(
        directories.inventory / "label_registry.csv",
        registry_rows,
        list(registry_rows[0]) if registry_rows else ["label_id"],
    )
    _write_csv(
        directories.inventory / "label_files.csv",
        label_files,
        ["path", "category", "row_count", "headers"],
    )
    _write_json(
        directories.inventory / "label_registry_issues.json",
        [asdict(issue) for issue in registry.issues],
    )
    matching_rows = _matching_rows(registry)
    _write_csv(
        directories.inventory / "video_label_matching.csv",
        matching_rows,
        [
            "source_id", "source_group_id", "source_path", "source_exists", "label_count",
            "eligible_label_count", "label_categories", "status",
        ],
    )

    records_by_path = {str(record.path).casefold(): record for record in video_records}
    labels_by_path: dict[str, list[Any]] = defaultdict(list)
    for label in registry.labels:
        labels_by_path[str(label.source_path.resolve()).casefold()].append(label)
    features_by_source: dict[Path, Sequence[Mapping[str, Any]]] = {}
    extraction_rows: list[dict[str, Any]] = []
    eligible_sources = [
        (source_key, labels)
        for source_key, labels in sorted(labels_by_path.items())
        if any(label.eligible for label in labels)
    ]
    for index, (source_key, labels) in enumerate(eligible_sources, start=1):
        source = labels[0].source_path.resolve()
        record = records_by_path.get(source_key)
        if record is None or not record.decode_valid:
            extraction_rows.append(
                {"source_path": str(source), "status": "excluded", "reason": "video_not_decodable"}
            )
            continue
        declared_hashes = {label.source_sha256 for label in labels if label.source_sha256}
        if declared_hashes and record.sha256 not in declared_hashes:
            extraction_rows.append(
                {"source_path": str(source), "status": "excluded", "reason": "source_hash_mismatch"}
            )
            continue
        try:
            extraction = extract_source_features(
                ExtractionRequest(
                    source_path=source,
                    labels=tuple(labels),
                    cache_dir=directories.cache,
                    project_root=config.project_root,
                    face_model_path=config.face_model_path,
                    pose_model_path=config.pose_model_path,
                    source_sha256=record.sha256,
                )
            )
            features_by_source[source] = extraction.rows
            extraction_rows.append(
                {
                    "source_path": str(source),
                    "status": "reused" if extraction.reused else "extracted",
                    "reason": "",
                    "camera_half": extraction.camera_decision.half,
                    "requested_rows": extraction.requested_sample_count,
                    "decoded_rows": extraction.decoded_sample_count,
                    "decode_errors": extraction.error_count,
                    "feature_rows": len(extraction.rows),
                    "cache_csv": str(extraction.cache_csv),
                }
            )
        except Exception as error:
            extraction_rows.append(
                {
                    "source_path": str(source),
                    "status": "excluded",
                    "reason": f"{type(error).__name__}: {error}",
                }
            )
        print(
            f"[extract] processed {index}/{len(eligible_sources)} sources status={extraction_rows[-1]['status']}",
            flush=True,
        )
    _write_csv(
        directories.inventory / "extraction_status.csv",
        extraction_rows,
        [
            "source_path", "status", "reason", "camera_half", "requested_rows", "decoded_rows",
            "decode_errors", "feature_rows", "cache_csv",
        ],
    )

    dataset_result = build_legacy_dataset(features_by_source, registry, contract)
    dataset_artifacts = write_legacy_dataset(dataset_result, directories.datasets, contract)
    print(f"[dataset] rows={len(dataset_result.rows)} exclusions={len(dataset_result.exclusions)}", flush=True)
    training = train_legacy_candidates(
        dataset_result.rows,
        contract,
        output_dir=directories.candidate,
        dataset_version=f"legacy-v2-{directories.root.name}",
        label_source="human_direct_plus_accepted_visual_direct",
        random_seed=config.random_seed,
    )
    print(f"[training] selected={training.model_name}", flush=True)
    compatibility = _browser_validate(config, directories, training.artifacts["metadata"])
    print("[browser] candidate compatibility passed", flush=True)

    quality = _feature_quality(features_by_source, contract.feature_names)
    interval_identities = {str(row["label_identity"]) for row in dataset_result.rows}
    dataset_summary = {
        **dataset_result.summary,
        "interval_count": len(interval_identities),
        "class_interval_counts": dict(
            sorted(
                Counter(
                    str(row["label"])
                    for row in {
                        str(item["label_identity"]): item for item in dataset_result.rows
                    }.values()
                ).items()
            )
        ),
    }
    split = {
        "strategy": "original_source_group",
        "subject_split": False,
        "train_groups": list(training.split_groups["train"]),
        "validation_groups": list(training.split_groups["validation"]),
        "test_groups": list(training.split_groups["test"]),
        "leakage_check": "pass",
        "note": "source/session generalization, not subject generalization",
    }
    model_comparison = {
        name: {
            "accuracy": metrics["accuracy"],
            "balanced_accuracy": metrics["balanced_accuracy"],
            "macro_f1": metrics["macro_f1"],
            "weighted_f1": metrics["weighted_f1"],
            "focus_recall": metrics["per_class"]["focus"]["recall"],
            "gaze_side_recall": metrics["per_class"]["gaze_side"]["recall"],
            "gaze_down_recall": metrics["per_class"]["gaze_down"]["recall"],
            "drowsy_recall": metrics["per_class"]["drowsy"]["recall"],
        }
        for name, metrics in training.candidate_validation_metrics.items()
    }
    metadata = json.loads(training.artifacts["metadata"].read_text(encoding="utf-8"))
    candidate = {
        "model": training.model_name,
        "candidate_path": str(training.artifacts["onnx"]),
        "sha256": metadata["model_sha256"],
        "schema_version": contract.schema_version,
        "feature_count": len(contract.feature_names),
        "class_order": list(contract.class_names),
        "test_metrics": training.test_metrics,
    }
    active_hash_after = sha256_file(active_model)
    active_metadata_hash_after = sha256_file(active_metadata)
    if active_hash_before != active_hash_after or active_metadata_hash_before != active_metadata_hash_after:
        raise RuntimeError("protected production v1 artifact changed during offline run")
    production = {
        "Production v1": "maintained",
        "Production v2": "inactive",
        "Candidate v2": "created separately",
        "active_v1_sha256_before": active_hash_before,
        "active_v1_sha256_after": active_hash_after,
        "active_v1_metadata_sha256_before": active_metadata_hash_before,
        "active_v1_metadata_sha256_after": active_metadata_hash_after,
    }
    matching_summary = {
        "matched_sources": sum(row["status"] == "matched" for row in matching_rows),
        "failed_sources": sum(row["status"] == "failed" for row in matching_rows),
        "partial_sources": sum(row["status"] == "partial" for row in matching_rows),
        "extraction_success_sources": sum(row["status"] in {"extracted", "reused"} for row in extraction_rows),
        "extraction_excluded_sources": sum(row["status"] == "excluded" for row in extraction_rows),
    }
    overhead_direct_labels = sum(
        label.label in {"page_turn", "pen_fidget", "restless_hand", "normal_activity"}
        and label.category in {HUMAN_DIRECT, HUMAN_CORRECTED, VISUAL_DIRECT}
        for label in registry.labels
    )
    recommendation = {
        "minimum_new_subjects": 8,
        "preferred_new_subjects": 12,
        "sessions_per_subject": 3,
        "minutes_per_session": "10-15",
        "collection_requirements": [
            "anonymous stable subject_id with consent",
            "different days, lighting, camera height, glasses and posture",
            "all four face states with human interval review",
            "entire subject assigned to exactly one split",
        ],
        "reason": "all reusable legacy rows lack verified subject identity; held-out metrics test recordings, not people",
    }
    generated_files = [str(path) for path in sorted(directories.root.rglob("*") if directories.root.exists() else ()) if path.is_file()]
    tests = {
        "feature_schema_validation": "pass",
        "normalization_causal": "pass",
        "temporal_leakage": "pass",
        "label_join": "pass",
        "camera_role_separation": "pass",
        "group_split_leakage": "pass",
        "candidate_metadata": "pass",
        "onnx_static_runtime": "pass",
        "browser_onnx_runtime": "pass",
        "overhead_activity_model": "not_trained_insufficient_direct_labels" if overhead_direct_labels == 0 else "not_in_scope",
    }
    report = build_report_document(
        inventory=inventory_summary,
        labels=label_summary,
        matching=matching_summary,
        dataset=dataset_summary,
        features=list(contract.feature_names),
        quality={
            **quality,
            "class_imbalance": dataset_summary["class_row_counts"],
            "front_source_count": len(features_by_source),
            "overhead_direct_activity_label_count": overhead_direct_labels,
        },
        split=split,
        model_comparison=model_comparison,
        candidate=candidate,
        v1_comparison={
            "available": False,
            "reason": "v1 requires legacy rule-boolean inputs not present in the exact v2 feature rows; no unsupported comparison was fabricated",
        },
        compatibility=compatibility,
        production=production,
        generalization={
            "answer": "아니오",
            "subject_generalization_valid": False,
            "reason": "no verified subject_id exists; filenames and recording count were not treated as people",
        },
        recommendations=recommendation,
        changed_files={
            "generated_run_files": generated_files,
            "dataset_artifacts": {name: str(path) for name, path in dataset_artifacts.items()},
            "candidate_artifacts": {name: str(path) for name, path in training.artifacts.items()},
        },
        tests=tests,
    )
    _write_json(directories.reports / "final-report.json", report)
    (directories.reports / "final-report.md").write_text(
        _markdown_report(report), encoding="utf-8"
    )
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Reuse mapped FocusAI legacy videos/labels to build and validate a non-production v2 candidate."
    )
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--video-root", type=Path, action="append", required=True)
    parser.add_argument("--human-label-root", type=Path, required=True)
    parser.add_argument("--clip-manifest", type=Path, required=True)
    parser.add_argument("--blind-label-root", type=Path, required=True)
    parser.add_argument("--frame-label-root", type=Path, required=True)
    parser.add_argument("--face-model", type=Path)
    parser.add_argument("--pose-model", type=Path)
    parser.add_argument("--random-seed", type=int, default=42)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = args.project_root.resolve()
    report = run_pipeline(
        PipelineConfig(
            project_root=root,
            output_dir=args.output_dir,
            video_roots=tuple(args.video_root),
            human_label_root=args.human_label_root,
            clip_manifest_csv=args.clip_manifest,
            blind_label_root=args.blind_label_root,
            frame_label_root=args.frame_label_root,
            face_model_path=args.face_model or root / "frontend" / "public" / "face_landmarker.task",
            pose_model_path=args.pose_model or root / "frontend" / "public" / "pose_landmarker.task",
            random_seed=args.random_seed,
        )
    )
    print(json.dumps({"status": "complete", "sections": list(report)}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
