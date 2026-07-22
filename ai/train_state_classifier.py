from __future__ import annotations

import argparse
import csv
import json
import pickle
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

try:
    from focus_ai.analyze import AnalyzeConfig, analyze_absent, analyze_merged_video
    from focus_ai.simple_state_classifier import SimpleStateClassifier
except ModuleNotFoundError:
    from ai.focus_ai.analyze import AnalyzeConfig, analyze_absent, analyze_merged_video
    from ai.focus_ai.simple_state_classifier import SimpleStateClassifier


FEATURE_NAMES = [
    "is_front_camera",
    "is_overhead_camera",
    "face_seen",
    "gaze_side",
    "gaze_down",
    "bad_posture",
    "eye_closed",
    "blink",
    "long_eye_closure",
    "head_down",
    "head_tilt",
    "drowsy",
    "page_turn",
    "pen_fidget",
    "restless_hand",
    "unknown",
]
EXCLUDED_LABELS = {"absent", "bad_posture"}
DEFAULT_TRAINING_DIR_NAME = "state_classifier_training"


def _auto_data_root() -> Path:
    downloads = Path.home() / "Downloads"
    candidates = [
        path
        for path in downloads.iterdir()
        if path.is_dir()
        and path.name.startswith("AI ")
        and path.name.endswith("_3min_exact")
        and (path / "train").is_dir()
    ]
    if not candidates:
        raise FileNotFoundError("could not find AI *_3min_exact dataset under Downloads")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def _as_float(value: Any) -> float:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _row_from_timeline_item(item: dict[str, Any], camera_type: str) -> list[float]:
    flags = item.get("flags")
    if not isinstance(flags, dict):
        flags = {}
    source = {
        "is_front_camera": str(camera_type).lower() == "front",
        "is_overhead_camera": str(camera_type).lower() in {"top", "overhead", "desk", "topdown"},
        **flags,
    }
    return [_as_float(source.get(name)) for name in FEATURE_NAMES]


def _samples_from_timeline(
    result: dict[str, Any],
    *,
    source_video: Path,
    camera_type: str,
) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    timeline = result.get("timeline")
    if not isinstance(timeline, list):
        return samples

    for item in timeline:
        if not isinstance(item, dict):
            continue
        label = str(item.get("rule_state") or item.get("state") or "").strip()
        if not label or label in EXCLUDED_LABELS:
            continue
        samples.append(
            {
                "source_video": source_video.name,
                "camera_type": camera_type,
                "t": int(float(item.get("t", 0))),
                "label": label,
                "features": _row_from_timeline_item(item, camera_type),
            }
        )
    return samples


def _extract_samples(result: dict[str, Any], source_video: Path, camera_type: str) -> list[dict[str, Any]]:
    if camera_type == "merged":
        samples: list[dict[str, Any]] = []
        front_result = result.get("front_result")
        if isinstance(front_result, dict):
            samples.extend(_samples_from_timeline(front_result, source_video=source_video, camera_type="front"))
        overhead_result = result.get("overhead_result")
        if isinstance(overhead_result, dict):
            samples.extend(_samples_from_timeline(overhead_result, source_video=source_video, camera_type="overhead"))
        if samples:
            return samples

    return _samples_from_timeline(result, source_video=source_video, camera_type=camera_type)


def _analyze_video(
    video: Path,
    *,
    session_id: str,
    camera_type: str,
    config: AnalyzeConfig,
) -> dict[str, Any]:
    if camera_type == "merged":
        return analyze_merged_video(session_id, str(video), config)
    return analyze_absent(session_id, str(video), camera_type, config)


def _load_or_analyze(
    video: Path,
    *,
    result_path: Path,
    session_id: str,
    camera_type: str,
    config: AnalyzeConfig,
    reuse_analysis: bool,
) -> dict[str, Any]:
    if reuse_analysis and result_path.exists():
        return json.loads(result_path.read_text(encoding="utf-8"))

    started = time.time()
    result = _analyze_video(video, session_id=session_id, camera_type=camera_type, config=config)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    elapsed = time.time() - started
    print(f"[analysis] {video.name}: {result.get('status')} in {elapsed:.1f}s", flush=True)
    return result


def _collect_split_samples(
    split_dir: Path,
    *,
    split_name: str,
    analysis_dir: Path,
    camera_type: str,
    config: AnalyzeConfig,
    reuse_analysis: bool,
    max_clips: int | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    videos = sorted(split_dir.glob("*.mp4"))
    if max_clips is not None:
        videos = videos[:max_clips]

    samples: list[dict[str, Any]] = []
    clip_rows: list[dict[str, Any]] = []
    for index, video in enumerate(videos, start=1):
        session_id = f"TRAIN_{split_name.upper()}_{index:03d}"
        result_path = analysis_dir / split_name / f"{video.stem}.json"
        result = _load_or_analyze(
            video,
            result_path=result_path,
            session_id=session_id,
            camera_type=camera_type,
            config=config,
            reuse_analysis=reuse_analysis,
        )
        clip_samples = _extract_samples(result, video, camera_type)
        samples.extend(clip_samples)
        clip_rows.append(
            {
                "split": split_name,
                "video": video.name,
                "status": result.get("status"),
                "duration_sec": result.get("meta", {}).get("duration_sec"),
                "sample_count": len(clip_samples),
                "label_counts": dict(Counter(str(row["label"]) for row in clip_samples)),
                "analysis_json": str(result_path),
            }
        )
        print(
            f"[samples] {split_name} {index}/{len(videos)} {video.name}: {len(clip_samples)} samples",
            flush=True,
        )

    return samples, clip_rows


def _accuracy(bundle: dict[str, Any], samples: list[dict[str, Any]]) -> dict[str, Any]:
    model = bundle["model"]
    labels = [str(sample["label"]) for sample in samples]
    if not labels:
        return {"sample_count": 0, "accuracy": None, "confusion": {}}

    predictions = model.predict([sample["features"] for sample in samples])
    correct = sum(1 for pred, label in zip(predictions, labels) if pred == label)
    confusion: dict[str, Counter[str]] = {}
    for label, pred in zip(labels, predictions):
        confusion.setdefault(label, Counter())[pred] += 1

    return {
        "sample_count": len(samples),
        "accuracy": round(correct / len(samples), 4),
        "confusion": {label: dict(counter) for label, counter in sorted(confusion.items())},
    }


def _write_samples_csv(path: Path, samples: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["source_video", "camera_type", "t", "label", *FEATURE_NAMES]
    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for sample in samples:
            row = {
                "source_video": sample["source_video"],
                "camera_type": sample["camera_type"],
                "t": sample["t"],
                "label": sample["label"],
            }
            row.update({name: sample["features"][idx] for idx, name in enumerate(FEATURE_NAMES)})
            writer.writerow(row)


def _write_clip_report(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["split", "video", "status", "duration_sec", "sample_count", "label_counts", "analysis_json"]
    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            rendered = dict(row)
            rendered["label_counts"] = json.dumps(rendered["label_counts"], ensure_ascii=False, sort_keys=True)
            writer.writerow(rendered)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Train the optional FocusAI state classifier.")
    parser.add_argument("--data-root", type=Path, help="Dataset root with train/ and optional test/ folders.")
    parser.add_argument("--camera-type", choices=["front", "overhead", "merged"], default="merged")
    parser.add_argument("--sampling-fps", type=int, default=1)
    parser.add_argument("--output-model", type=Path, default=Path("ai/models/state_classifier.pkl"))
    parser.add_argument("--training-dir", type=Path, default=Path("ai") / DEFAULT_TRAINING_DIR_NAME)
    parser.add_argument("--reuse-analysis", action="store_true", help="Reuse existing analysis JSON files.")
    parser.add_argument("--max-clips", type=int, help="Limit clips per split for a quick smoke run.")
    parser.add_argument("--no-test", action="store_true", help="Skip pseudo-label evaluation on test clips.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    data_root = args.data_root or _auto_data_root()
    train_dir = data_root / "train"
    test_dir = data_root / "test"
    if not train_dir.is_dir():
        print(f"train directory not found: {train_dir}", file=sys.stderr)
        return 2

    config = AnalyzeConfig(
        sampling_fps=int(args.sampling_fps),
        use_trained_classifier=False,
    )
    analysis_dir = args.training_dir / "analysis_results"

    print(f"[data] root={data_root}", flush=True)
    print(f"[data] train={train_dir}", flush=True)
    print(f"[config] camera_type={args.camera_type}, sampling_fps={config.sampling_fps}", flush=True)

    train_samples, clip_rows = _collect_split_samples(
        train_dir,
        split_name="train",
        analysis_dir=analysis_dir,
        camera_type=args.camera_type,
        config=config,
        reuse_analysis=args.reuse_analysis,
        max_clips=args.max_clips,
    )
    if not train_samples:
        print("no train samples were produced", file=sys.stderr)
        return 3

    train_labels = [str(sample["label"]) for sample in train_samples]
    train_counts = Counter(train_labels)
    if len(train_counts) < 2:
        print(f"need at least two train classes; got {dict(train_counts)}", file=sys.stderr)
        return 4

    model = SimpleStateClassifier.fit(
        [sample["features"] for sample in train_samples],
        train_labels,
        balanced_priors=True,
    )
    bundle = {
        "model": model,
        "feature_names": FEATURE_NAMES,
        "classes": list(model.classes_),
        "training": {
            "data_root": str(data_root),
            "camera_type": args.camera_type,
            "sampling_fps": int(config.sampling_fps),
            "label_source": "rule_state pseudo-labels from FocusAI analysis",
            "excluded_labels": sorted(EXCLUDED_LABELS),
            "train_sample_count": len(train_samples),
            "train_label_counts": dict(sorted(train_counts.items())),
        },
    }

    metrics = {"train": _accuracy(bundle, train_samples)}
    test_samples: list[dict[str, Any]] = []
    if not args.no_test and test_dir.is_dir():
        test_samples, test_clip_rows = _collect_split_samples(
            test_dir,
            split_name="test",
            analysis_dir=analysis_dir,
            camera_type=args.camera_type,
            config=config,
            reuse_analysis=args.reuse_analysis,
            max_clips=args.max_clips,
        )
        clip_rows.extend(test_clip_rows)
        metrics["test"] = _accuracy(bundle, test_samples)

    bundle["training"]["metrics"] = metrics
    if test_samples:
        bundle["training"]["test_sample_count"] = len(test_samples)
        bundle["training"]["test_label_counts"] = dict(sorted(Counter(str(row["label"]) for row in test_samples).items()))

    args.output_model.parent.mkdir(parents=True, exist_ok=True)
    with args.output_model.open("wb") as file:
        pickle.dump(bundle, file)

    _write_samples_csv(args.training_dir / "train_samples.csv", train_samples)
    if test_samples:
        _write_samples_csv(args.training_dir / "test_samples.csv", test_samples)
    _write_clip_report(args.training_dir / "clip_report.csv", clip_rows)

    summary = {
        "model_path": str(args.output_model),
        "data_root": str(data_root),
        "feature_names": FEATURE_NAMES,
        "classes": list(model.classes_),
        "train_label_counts": dict(sorted(train_counts.items())),
        "metrics": metrics,
    }
    (args.training_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
