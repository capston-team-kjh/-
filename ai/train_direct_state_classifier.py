from __future__ import annotations

import argparse
import csv
import hashlib
import json
import pickle
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from ai.train_state_classifier import FEATURE_NAMES, _row_from_timeline_item
from ai.focus_ai.simple_state_classifier import SimpleStateClassifier
from ai.focus_ai.analyze import AnalyzeConfig, analyze_merged_video
from ai.focus_ai.video_preflight import _resolve_ffmpeg_executable


@dataclass(frozen=True)
class DirectTrainingInterval:
    blind_id: str
    source_group: str
    source_path: Path | str
    start_sec: float
    end_sec: float
    analysis_json: Path | str


def extract_interval_clip(
    source_path: Path,
    output_path: Path,
    *,
    start_sec: float,
    end_sec: float,
) -> None:
    """Extract an interval by timestamps so variable-rate sources keep full coverage."""
    if output_path.exists():
        raise FileExistsError(output_path)
    start = max(0.0, float(start_sec))
    duration = float(end_sec) - start
    if duration <= 0.0:
        raise ValueError(f"invalid clip range: {start_sec}-{end_sec}")
    ffmpeg = _resolve_ffmpeg_executable()
    if not ffmpeg:
        raise RuntimeError("FFmpeg is required for direct-label interval extraction")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(source_path),
        "-ss",
        f"{start:.6f}",
        "-t",
        f"{duration:.6f}",
        "-map",
        "0:v:0",
        "-an",
        "-vf",
        "fps=10",
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
    if (
        completed.returncode != 0
        or not output_path.is_file()
        or output_path.stat().st_size <= 0
    ):
        output_path.unlink(missing_ok=True)
        stderr_tail = (completed.stderr or "")[-2000:]
        raise RuntimeError(
            f"direct-label interval extraction failed ({completed.returncode}): "
            f"{stderr_tail}"
        )


def load_direct_intervals(
    labels_path: Path,
    source_map_path: Path,
) -> list[tuple[DirectTrainingInterval, str]]:
    with labels_path.open(newline="", encoding="utf-8-sig") as stream:
        label_rows = list(csv.DictReader(stream))
    accepted = {
        str(row["blind_id"]).strip(): str(row["direct_label"]).strip()
        for row in label_rows
        if str(row.get("review_status", "")).strip() == "accepted"
    }
    if len(accepted) != sum(
        str(row.get("review_status", "")).strip() == "accepted" for row in label_rows
    ):
        raise ValueError("accepted direct labels contain duplicate blind_id values")

    with source_map_path.open(newline="", encoding="utf-8-sig") as stream:
        source_rows = list(csv.DictReader(stream))
    source_by_id = {str(row["blind_id"]).strip(): row for row in source_rows}
    if len(source_by_id) != len(source_rows):
        raise ValueError("source map contains duplicate blind_id values")
    missing = sorted(set(accepted).difference(source_by_id))
    if missing:
        raise ValueError(f"accepted labels are missing from source map: {missing}")

    entries: list[tuple[DirectTrainingInterval, str]] = []
    for blind_id in sorted(accepted):
        row = source_by_id[blind_id]
        entries.append(
            (
                DirectTrainingInterval(
                    blind_id=blind_id,
                    source_group=str(row["source_group"]).strip(),
                    source_path=Path(str(row["source_path"])),
                    start_sec=float(row["start_sec"]),
                    end_sec=float(row["end_sec"]),
                    analysis_json=Path(str(row["analysis_json"])),
                ),
                accepted[blind_id],
            )
        )
    return entries


def _read_analysis_with_coverage(
    path: Path,
    *,
    start_sec: float,
    end_sec: float,
) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    streams: list[Mapping[str, Any]] = []
    for key in ("front_result", "overhead_result"):
        stream = result.get(key)
        if isinstance(stream, Mapping):
            streams.append(stream)
    if not streams:
        streams.append(result)
    required_last_timestamp = max(float(start_sec), float(end_sec) - 1.0)
    for stream in streams:
        timeline = stream.get("timeline")
        if not isinstance(timeline, list) or not timeline:
            return None
        last_timestamp = max(
            float(item.get("t", -1))
            for item in timeline
            if isinstance(item, Mapping)
        )
        if last_timestamp < required_last_timestamp:
            return None
    return result


def load_or_analyze_interval(
    interval: DirectTrainingInterval,
    *,
    analysis_dir: Path,
    config: Any,
    analyzer: Any = analyze_merged_video,
    extractor: Any = extract_interval_clip,
    memory_cache: dict[Path, dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], float, str]:
    source_analysis_path = Path(interval.analysis_json)
    source_analysis = None if memory_cache is None else memory_cache.get(source_analysis_path)
    if source_analysis is None:
        source_analysis = _read_analysis_with_coverage(
            source_analysis_path,
            start_sec=interval.start_sec,
            end_sec=interval.end_sec,
        )
    if source_analysis is not None:
        if memory_cache is not None:
            memory_cache[source_analysis_path] = source_analysis
        return source_analysis, interval.start_sec, "source_analysis"

    interval_analysis_path = analysis_dir / "intervals" / f"{interval.blind_id}.json"
    duration = interval.end_sec - interval.start_sec
    interval_analysis = _read_analysis_with_coverage(
        interval_analysis_path,
        start_sec=0.0,
        end_sec=duration,
    )
    if interval_analysis is not None:
        return interval_analysis, 0.0, "interval_analysis"

    clip_path = analysis_dir / "clips" / f"{interval.blind_id}.mp4"
    if not clip_path.exists():
        extractor(
            Path(interval.source_path),
            clip_path,
            start_sec=interval.start_sec,
            end_sec=interval.end_sec,
        )
    try:
        interval_analysis = analyzer(
            f"DIRECT_{interval.blind_id}",
            str(clip_path),
            config,
        )
        interval_analysis_path.parent.mkdir(parents=True, exist_ok=True)
        interval_analysis_path.write_text(
            json.dumps(interval_analysis, ensure_ascii=False),
            encoding="utf-8",
        )
    finally:
        clip_path.unlink(missing_ok=True)
    validated = _read_analysis_with_coverage(
        interval_analysis_path,
        start_sec=0.0,
        end_sec=duration,
    )
    if validated is None:
        raise ValueError(f"interval analysis is incomplete: {interval.blind_id}")
    return validated, 0.0, "interval_analysis"


def samples_from_interval(
    interval: DirectTrainingInterval,
    direct_label: str,
    result: Mapping[str, Any],
    *,
    timeline_start_sec: float | None = None,
) -> list[dict[str, Any]]:
    start_sec = interval.start_sec if timeline_start_sec is None else float(timeline_start_sec)
    duration = interval.end_sec - interval.start_sec
    end_sec = start_sec + duration
    streams: list[tuple[str, Mapping[str, Any]]] = []
    for camera_type, key in (("front", "front_result"), ("overhead", "overhead_result")):
        stream = result.get(key)
        if isinstance(stream, Mapping):
            streams.append((camera_type, stream))
    if not streams:
        camera_type = str(result.get("meta", {}).get("camera_type") or "merged")
        streams.append((camera_type, result))

    samples: list[dict[str, Any]] = []
    for camera_type, stream in streams:
        timeline = stream.get("timeline")
        if not isinstance(timeline, list):
            continue
        for item in timeline:
            if not isinstance(item, dict):
                continue
            timestamp = float(item.get("t", 0))
            if timestamp < start_sec or timestamp >= end_sec:
                continue
            samples.append(
                {
                    "blind_id": interval.blind_id,
                    "source_group": interval.source_group,
                    "camera_type": camera_type,
                    "t": timestamp,
                    "direct_label": str(direct_label),
                    "features": _row_from_timeline_item(item, camera_type),
                }
            )
    return samples


def split_source_groups(
    group_label_counts: Mapping[str, Mapping[str, int]],
    *,
    test_fraction: float = 0.2,
) -> tuple[set[str], set[str]]:
    if not 0.0 < float(test_fraction) < 1.0:
        raise ValueError("test_fraction must be between zero and one")
    groups = set(group_label_counts)
    if len(groups) < 2:
        raise ValueError("at least two source groups are required")

    group_sizes = {
        group: sum(int(count) for count in counts.values())
        for group, counts in group_label_counts.items()
    }
    groups_by_class: dict[str, set[str]] = defaultdict(set)
    for group, counts in group_label_counts.items():
        for label, count in counts.items():
            if int(count) > 0:
                groups_by_class[str(label)].add(group)

    test_groups: set[str] = set()

    def can_add(group: str) -> bool:
        remaining = groups.difference(test_groups | {group})
        return all(not class_groups or class_groups.intersection(remaining) for class_groups in groups_by_class.values())

    for label in sorted(groups_by_class, key=lambda name: (len(groups_by_class[name]), name)):
        class_groups = groups_by_class[label]
        if len(class_groups) < 2 or class_groups.intersection(test_groups):
            continue
        candidates = [group for group in class_groups if can_add(group)]
        if not candidates:
            continue
        selected = min(
            candidates,
            key=lambda group: (
                int(group_label_counts[group].get(label, 0)),
                group_sizes[group],
                group,
            ),
        )
        test_groups.add(selected)

    target = max(1, round(sum(group_sizes.values()) * float(test_fraction)))
    for group in sorted(groups.difference(test_groups), key=lambda item: (group_sizes[item], item)):
        if sum(group_sizes[item] for item in test_groups) >= target:
            break
        if can_add(group):
            test_groups.add(group)

    train_groups = groups.difference(test_groups)
    if not train_groups or not test_groups:
        raise ValueError("could not create non-empty source-isolated splits")
    return train_groups, test_groups


def classification_metrics(
    expected: Sequence[str],
    predicted: Sequence[str],
    *,
    classes: Sequence[str],
) -> dict[str, Any]:
    if len(expected) != len(predicted):
        raise ValueError("expected and predicted must have the same length")
    ordered_classes = [str(label) for label in classes]
    confusion = {
        actual: {prediction: 0 for prediction in ordered_classes}
        for actual in ordered_classes
    }
    for actual, prediction in zip(expected, predicted):
        confusion.setdefault(str(actual), Counter())
        confusion[str(actual)][str(prediction)] += 1

    per_class: dict[str, dict[str, float | int]] = {}
    f1_values: list[float] = []
    for label in ordered_classes:
        true_positive = int(confusion.get(label, {}).get(label, 0))
        false_positive = sum(
            int(confusion.get(actual, {}).get(label, 0))
            for actual in ordered_classes
            if actual != label
        )
        false_negative = sum(
            int(count)
            for prediction, count in confusion.get(label, {}).items()
            if prediction != label
        )
        precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 0.0
        recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else 0.0
        f1 = 2.0 * precision * recall / (precision + recall) if precision + recall else 0.0
        f1_values.append(f1)
        per_class[label] = {
            "support": sum(int(value) for value in confusion.get(label, {}).values()),
            "precision": precision,
            "recall": recall,
            "f1": f1,
        }

    correct = sum(1 for actual, prediction in zip(expected, predicted) if actual == prediction)
    return {
        "sample_count": len(expected),
        "accuracy": correct / len(expected) if expected else 0.0,
        "macro_f1": sum(f1_values) / len(f1_values) if f1_values else 0.0,
        "per_class": per_class,
        "confusion_matrix": {
            actual: {prediction: int(confusion.get(actual, {}).get(prediction, 0)) for prediction in ordered_classes}
            for actual in ordered_classes
        },
    }


def fit_direct_classifier(
    samples: Sequence[Mapping[str, Any]],
    *,
    train_groups: set[str],
    test_groups: set[str],
    label_freeze_sha256: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    overlap = sorted(train_groups.intersection(test_groups))
    if overlap:
        raise ValueError(f"source groups overlap across splits: {overlap}")
    train_samples = [row for row in samples if str(row["source_group"]) in train_groups]
    test_samples = [row for row in samples if str(row["source_group"]) in test_groups]
    if not train_samples or not test_samples:
        raise ValueError("both train and test samples are required")
    train_labels = [str(row["direct_label"]) for row in train_samples]
    test_labels = [str(row["direct_label"]) for row in test_samples]
    classes = sorted(set(train_labels))
    if len(classes) < 2:
        raise ValueError("at least two training classes are required")
    missing_train_classes = sorted(set(test_labels).difference(classes))
    if missing_train_classes:
        raise ValueError(f"test classes are missing from training: {missing_train_classes}")

    model = SimpleStateClassifier.fit(
        [row["features"] for row in train_samples],
        train_labels,
        balanced_priors=True,
    )
    train_predictions = model.predict([row["features"] for row in train_samples])
    test_predictions = model.predict([row["features"] for row in test_samples])
    metrics = {
        "train": classification_metrics(train_labels, train_predictions, classes=classes),
        "test": classification_metrics(test_labels, test_predictions, classes=classes),
    }
    bundle = {
        "model": model,
        "feature_names": list(FEATURE_NAMES),
        "classes": list(model.classes_),
        "training": {
            "label_source": "codex_visual_direct_labels",
            "label_freeze_sha256": str(label_freeze_sha256),
            "train_source_groups": sorted(train_groups),
            "test_source_groups": sorted(test_groups),
            "source_group_overlap": overlap,
            "train_sample_count": len(train_samples),
            "test_sample_count": len(test_samples),
            "train_label_counts": dict(sorted(Counter(train_labels).items())),
            "test_label_counts": dict(sorted(Counter(test_labels).items())),
            "metrics": metrics,
        },
    }
    return bundle, metrics


def _write_samples_csv(path: Path, samples: Sequence[Mapping[str, Any]]) -> None:
    fields = [
        "blind_id",
        "source_group",
        "camera_type",
        "t",
        "direct_label",
        *FEATURE_NAMES,
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for sample in samples:
            row = {field: sample[field] for field in fields[:5]}
            row.update(
                {
                    name: sample["features"][index]
                    for index, name in enumerate(FEATURE_NAMES)
                }
            )
            writer.writerow(row)


def _write_predictions_csv(
    path: Path,
    samples: Sequence[Mapping[str, Any]],
    predictions: Sequence[str],
) -> None:
    fields = [
        "blind_id",
        "source_group",
        "camera_type",
        "t",
        "direct_label",
        "predicted_label",
        "correct",
    ]
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for sample, prediction in zip(samples, predictions):
            expected = str(sample["direct_label"])
            writer.writerow(
                {
                    "blind_id": sample["blind_id"],
                    "source_group": sample["source_group"],
                    "camera_type": sample["camera_type"],
                    "t": sample["t"],
                    "direct_label": expected,
                    "predicted_label": prediction,
                    "correct": prediction == expected,
                }
            )


def _write_interval_report(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    fields = [
        "blind_id",
        "source_group",
        "split",
        "direct_label",
        "sample_count",
        "analysis_source",
    ]
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def run_training(
    *,
    labels_path: Path,
    source_map_path: Path,
    analysis_dir: Path,
    output_model: Path,
    training_dir: Path,
    test_fraction: float = 0.2,
    sampling_fps: int = 1,
) -> dict[str, Any]:
    entries = load_direct_intervals(labels_path, source_map_path)
    if not entries:
        raise ValueError("no accepted direct labels were found")
    group_label_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for interval, direct_label in entries:
        group_label_counts[interval.source_group][direct_label] += 1
    train_groups, test_groups = split_source_groups(
        group_label_counts,
        test_fraction=test_fraction,
    )

    config = AnalyzeConfig(
        sampling_fps=int(sampling_fps),
        use_trained_classifier=False,
    )
    samples: list[dict[str, Any]] = []
    interval_reports: list[dict[str, Any]] = []
    memory_cache: dict[Path, dict[str, Any]] = {}
    for index, (interval, direct_label) in enumerate(entries, start=1):
        print(
            f"[direct-analysis] {index}/{len(entries)} {interval.blind_id} {direct_label}",
            flush=True,
        )
        result, timeline_start, analysis_source = load_or_analyze_interval(
            interval,
            analysis_dir=analysis_dir,
            config=config,
            memory_cache=memory_cache,
        )
        interval_samples = samples_from_interval(
            interval,
            direct_label,
            result,
            timeline_start_sec=timeline_start,
        )
        if not interval_samples:
            raise ValueError(f"no feature samples were produced for {interval.blind_id}")
        samples.extend(interval_samples)
        interval_reports.append(
            {
                "blind_id": interval.blind_id,
                "source_group": interval.source_group,
                "split": "train" if interval.source_group in train_groups else "test",
                "direct_label": direct_label,
                "sample_count": len(interval_samples),
                "analysis_source": analysis_source,
            }
        )

    label_freeze_sha256 = hashlib.sha256(labels_path.read_bytes()).hexdigest()
    bundle, metrics = fit_direct_classifier(
        samples,
        train_groups=train_groups,
        test_groups=test_groups,
        label_freeze_sha256=label_freeze_sha256,
    )
    train_samples = [row for row in samples if row["source_group"] in train_groups]
    test_samples = [row for row in samples if row["source_group"] in test_groups]
    test_predictions = bundle["model"].predict([row["features"] for row in test_samples])

    output_model.parent.mkdir(parents=True, exist_ok=True)
    with output_model.open("wb") as stream:
        pickle.dump(bundle, stream)
    training_dir.mkdir(parents=True, exist_ok=True)
    _write_samples_csv(training_dir / "train_samples.csv", train_samples)
    _write_samples_csv(training_dir / "test_samples.csv", test_samples)
    _write_predictions_csv(
        training_dir / "test_predictions.csv",
        test_samples,
        test_predictions,
    )
    _write_interval_report(training_dir / "interval_report.csv", interval_reports)
    (training_dir / "test_metrics_detailed.json").write_text(
        json.dumps(metrics["test"], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    summary: dict[str, Any] = {
        "model_path": str(output_model),
        "label_source": "codex_visual_direct_labels",
        "label_freeze_sha256": label_freeze_sha256,
        "feature_names": list(FEATURE_NAMES),
        "classes": list(bundle["classes"]),
        "accepted_interval_count": len(entries),
        "interval_label_counts": dict(
            sorted(Counter(label for _, label in entries).items())
        ),
        "train_source_groups": sorted(train_groups),
        "test_source_groups": sorted(test_groups),
        "source_group_overlap": sorted(train_groups.intersection(test_groups)),
        "train_sample_count": len(train_samples),
        "test_sample_count": len(test_samples),
        "metrics": metrics,
    }
    (training_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    report = [
        "# FocusAI Direct-Label State Classifier Report",
        "",
        "- Label source: `codex_visual_direct_labels`",
        f"- Accepted intervals: {len(entries)}",
        f"- Train samples: {len(train_samples)}",
        f"- Test samples: {len(test_samples)}",
        f"- Test accuracy: {metrics['test']['accuracy']:.6f}",
        f"- Test macro F1: {metrics['test']['macro_f1']:.6f}",
        f"- Source-group overlap: {summary['source_group_overlap']}",
        "- Evaluation split: source-isolated (no source appears in both train and test)",
        "",
        "## Per-class test metrics",
        "",
        "| Class | Support | Precision | Recall | F1 |",
        "|---|---:|---:|---:|---:|",
    ]
    for label, values in metrics["test"]["per_class"].items():
        report.append(
            f"| {label} | {values['support']} | {values['precision']:.6f} | "
            f"{values['recall']:.6f} | {values['f1']:.6f} |"
        )
    report.extend(
        [
            "",
            "## Interpretation",
            "",
            "These held-out direct-label metrics measure generalization across source videos.",
            "A loadable model artifact does not imply production readiness; low per-class "
            "recall should be addressed with more direct labels or stronger features.",
        ]
    )
    (training_dir / "test_report.md").write_text(
        "\n".join(report) + "\n",
        encoding="utf-8",
    )
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Train the FocusAI state classifier from frozen direct visual labels."
    )
    parser.add_argument(
        "--labels",
        type=Path,
        default=Path("ai/direct_labeling/blind_labels.csv"),
    )
    parser.add_argument("--source-map", type=Path, required=True)
    parser.add_argument(
        "--analysis-dir",
        type=Path,
        default=Path("ai/state_classifier_training/direct_analysis"),
    )
    parser.add_argument(
        "--output-model",
        type=Path,
        default=Path("ai/models/state_classifier.pkl"),
    )
    parser.add_argument(
        "--training-dir",
        type=Path,
        default=Path("ai/state_classifier_training"),
    )
    parser.add_argument("--test-fraction", type=float, default=0.2)
    parser.add_argument("--sampling-fps", type=int, default=1)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        summary = run_training(
            labels_path=args.labels,
            source_map_path=args.source_map,
            analysis_dir=args.analysis_dir,
            output_model=args.output_model,
            training_dir=args.training_dir,
            test_fraction=args.test_fraction,
            sampling_fps=args.sampling_fps,
        )
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


__all__ = [
    "FEATURE_NAMES",
    "DirectTrainingInterval",
    "classification_metrics",
    "extract_interval_clip",
    "fit_direct_classifier",
    "load_direct_intervals",
    "load_or_analyze_interval",
    "run_training",
    "samples_from_interval",
    "split_source_groups",
]


if __name__ == "__main__":
    raise SystemExit(main())
