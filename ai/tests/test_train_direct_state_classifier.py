from __future__ import annotations

import unittest
import csv
import json
import pickle
from pathlib import Path
from tempfile import TemporaryDirectory

from ai.train_direct_state_classifier import (
    DirectTrainingInterval,
    classification_metrics,
    fit_direct_classifier,
    load_or_analyze_interval,
    run_training,
    load_direct_intervals,
    samples_from_interval,
    split_source_groups,
)


def _timeline(*, rule_state: str) -> list[dict[str, object]]:
    return [
        {
            "t": second,
            "rule_state": rule_state,
            "flags": {
                "face_seen": True,
                "gaze_side": second == 2,
                "gaze_down": False,
                "drowsy": False,
            },
        }
        for second in range(5)
    ]


class DirectStateTrainingTests(unittest.TestCase):
    def test_run_training_writes_direct_artifacts_from_cached_analysis(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            labels_path = root / "labels.csv"
            source_map_path = root / "source_map.csv"
            model_path = root / "model.pkl"
            training_dir = root / "training"
            label_fields = [
                "blind_id",
                "direct_label",
                "confidence",
                "evidence",
                "review_status",
                "annotator",
                "annotated_at",
            ]
            source_fields = [
                "blind_id",
                "source_group",
                "source_path",
                "start_sec",
                "end_sec",
                "analysis_json",
            ]
            cases = [
                ("B1", "S_focus_a", "focus", False),
                ("B2", "S_focus_b", "focus", False),
                ("B3", "S_drowsy_a", "drowsy", True),
                ("B4", "S_drowsy_b", "drowsy", True),
            ]
            with labels_path.open("w", newline="", encoding="utf-8") as label_stream, source_map_path.open(
                "w", newline="", encoding="utf-8"
            ) as source_stream:
                label_writer = csv.DictWriter(label_stream, fieldnames=label_fields)
                source_writer = csv.DictWriter(source_stream, fieldnames=source_fields)
                label_writer.writeheader()
                source_writer.writeheader()
                for blind_id, source_group, label, drowsy in cases:
                    analysis_path = root / f"{blind_id}.json"
                    timeline = [
                        {
                            "t": second,
                            "flags": {
                                "face_seen": True,
                                "eye_closed": drowsy,
                                "long_eye_closure": drowsy,
                                "drowsy": drowsy,
                            },
                        }
                        for second in range(2)
                    ]
                    analysis_path.write_text(
                        json.dumps(
                            {
                                "front_result": {"timeline": timeline},
                                "overhead_result": {"timeline": timeline},
                            }
                        ),
                        encoding="utf-8",
                    )
                    label_writer.writerow(
                        {
                            "blind_id": blind_id,
                            "direct_label": label,
                            "confidence": "high",
                            "evidence": label,
                            "review_status": "accepted",
                            "annotator": "codex_visual_direct",
                            "annotated_at": "now",
                        }
                    )
                    source_writer.writerow(
                        {
                            "blind_id": blind_id,
                            "source_group": source_group,
                            "source_path": root / f"{source_group}.mp4",
                            "start_sec": 0,
                            "end_sec": 2,
                            "analysis_json": analysis_path,
                        }
                    )

            summary = run_training(
                labels_path=labels_path,
                source_map_path=source_map_path,
                analysis_dir=root / "analysis",
                output_model=model_path,
                training_dir=training_dir,
                test_fraction=0.5,
                sampling_fps=1,
            )

            self.assertTrue(model_path.is_file())
            self.assertTrue((training_dir / "test_predictions.csv").is_file())
            self.assertEqual(summary["label_source"], "codex_visual_direct_labels")
            self.assertEqual(summary["source_group_overlap"], [])
            with model_path.open("rb") as stream:
                bundle = pickle.load(stream)
            self.assertEqual(bundle["training"]["label_source"], "codex_visual_direct_labels")

    def test_existing_source_analysis_is_reused_with_original_offset(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache = root / "source.json"
            cache.write_text(
                json.dumps(
                    {
                        "front_result": {"timeline": _timeline(rule_state="focus")},
                        "overhead_result": {"timeline": _timeline(rule_state="focus")},
                    }
                ),
                encoding="utf-8",
            )
            interval = DirectTrainingInterval(
                blind_id="B123",
                source_group="S123",
                source_path=root / "source.mp4",
                start_sec=1.0,
                end_sec=4.0,
                analysis_json=cache,
            )

            result, timeline_start, cache_source = load_or_analyze_interval(
                interval,
                analysis_dir=root / "generated",
                config=object(),
                analyzer=lambda *_: self.fail("analyzer should not be called"),
                extractor=lambda *_args, **_kwargs: self.fail("extractor should not be called"),
            )

            self.assertIn("front_result", result)
            self.assertEqual(timeline_start, 1.0)
            self.assertEqual(cache_source, "source_analysis")

    def test_missing_source_analysis_creates_interval_cache(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            interval = DirectTrainingInterval(
                blind_id="B123",
                source_group="S123",
                source_path=root / "source.mp4",
                start_sec=10.0,
                end_sec=15.0,
                analysis_json=root / "missing.json",
            )

            def fake_extract(_source: Path, output: Path, **_kwargs: object) -> None:
                output.parent.mkdir(parents=True, exist_ok=True)
                output.touch()

            def fake_analyze(_session_id: str, _video: str, _config: object) -> dict[str, object]:
                return {
                    "status": "success",
                    "front_result": {"timeline": _timeline(rule_state="focus")},
                    "overhead_result": {"timeline": _timeline(rule_state="focus")},
                }

            result, timeline_start, cache_source = load_or_analyze_interval(
                interval,
                analysis_dir=root / "generated",
                config=object(),
                analyzer=fake_analyze,
                extractor=fake_extract,
            )

            self.assertEqual(result["status"], "success")
            self.assertEqual(timeline_start, 0.0)
            self.assertEqual(cache_source, "interval_analysis")
            self.assertTrue((root / "generated" / "intervals" / "B123.json").is_file())

    def test_load_direct_intervals_keeps_only_accepted_labels(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            labels_path = root / "labels.csv"
            source_map_path = root / "source_map.csv"
            with labels_path.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(
                    stream,
                    fieldnames=[
                        "blind_id",
                        "direct_label",
                        "confidence",
                        "evidence",
                        "review_status",
                        "annotator",
                        "annotated_at",
                    ],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "blind_id": "B1",
                        "direct_label": "focus",
                        "confidence": "high",
                        "evidence": "writing",
                        "review_status": "accepted",
                        "annotator": "codex_visual_direct",
                        "annotated_at": "now",
                    }
                )
                writer.writerow(
                    {
                        "blind_id": "B2",
                        "direct_label": "",
                        "confidence": "",
                        "evidence": "mixed",
                        "review_status": "ambiguous",
                        "annotator": "codex_visual_direct",
                        "annotated_at": "now",
                    }
                )
            with source_map_path.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(
                    stream,
                    fieldnames=[
                        "blind_id",
                        "source_group",
                        "source_path",
                        "start_sec",
                        "end_sec",
                        "analysis_json",
                    ],
                )
                writer.writeheader()
                for blind_id in ("B1", "B2"):
                    writer.writerow(
                        {
                            "blind_id": blind_id,
                            "source_group": "S1",
                            "source_path": "source.mp4",
                            "start_sec": "0",
                            "end_sec": "5",
                            "analysis_json": "analysis.json",
                        }
                    )

            entries = load_direct_intervals(labels_path, source_map_path)

            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0][0].blind_id, "B1")
            self.assertEqual(entries[0][1], "focus")

    def test_samples_use_direct_label_and_ignore_rule_state(self) -> None:
        interval = DirectTrainingInterval(
            blind_id="B123",
            source_group="S123",
            source_path="source.mp4",
            start_sec=1.0,
            end_sec=4.0,
            analysis_json="analysis.json",
        )
        result = {
            "front_result": {"timeline": _timeline(rule_state="focus")},
            "overhead_result": {"timeline": _timeline(rule_state="focus")},
        }

        samples = samples_from_interval(interval, "gaze_side", result)

        self.assertEqual(len(samples), 6)
        self.assertEqual({row["direct_label"] for row in samples}, {"gaze_side"})
        self.assertEqual({row["camera_type"] for row in samples}, {"front", "overhead"})
        self.assertNotIn("rule_state", samples[0])
        self.assertEqual({row["source_group"] for row in samples}, {"S123"})

    def test_source_group_split_has_no_overlap_and_keeps_class_coverage(self) -> None:
        group_counts = {
            "S_main": {"focus": 20, "drowsy": 10, "gaze_down": 8},
            "S_rare": {"focus": 3, "drowsy": 2, "gaze_down": 1},
            "S_side_main": {"gaze_side": 10},
            "S_side_test": {"gaze_side": 3},
            "S_unknown_main": {"unknown": 10},
            "S_unknown_test": {"unknown": 3},
        }

        train_groups, test_groups = split_source_groups(group_counts, test_fraction=0.25)

        self.assertFalse(train_groups.intersection(test_groups))
        self.assertEqual(train_groups.union(test_groups), set(group_counts))
        train_classes = {
            label for group in train_groups for label in group_counts[group]
        }
        test_classes = {
            label for group in test_groups for label in group_counts[group]
        }
        self.assertEqual(train_classes, set().union(*map(set, group_counts.values())))
        self.assertEqual(test_classes, train_classes)

    def test_classification_metrics_include_macro_f1_and_confusion(self) -> None:
        metrics = classification_metrics(
            ["focus", "focus", "drowsy", "drowsy"],
            ["focus", "drowsy", "drowsy", "drowsy"],
            classes=["drowsy", "focus"],
        )

        self.assertEqual(metrics["accuracy"], 0.75)
        self.assertEqual(metrics["confusion_matrix"]["focus"]["drowsy"], 1)
        self.assertEqual(metrics["per_class"]["drowsy"]["recall"], 1.0)
        self.assertAlmostEqual(metrics["macro_f1"], (0.8 + 2 / 3) / 2, places=6)

    def test_fit_bundle_records_direct_source_and_disjoint_groups(self) -> None:
        samples = []
        for group, label, value in (
            ("S_train_a", "focus", 0.0),
            ("S_train_b", "drowsy", 1.0),
            ("S_test_a", "focus", 0.0),
            ("S_test_b", "drowsy", 1.0),
        ):
            for second in range(2):
                samples.append(
                    {
                        "blind_id": f"B{group}{second}",
                        "source_group": group,
                        "camera_type": "front",
                        "t": second,
                        "direct_label": label,
                        "features": [value] * 16,
                    }
                )

        bundle, metrics = fit_direct_classifier(
            samples,
            train_groups={"S_train_a", "S_train_b"},
            test_groups={"S_test_a", "S_test_b"},
            label_freeze_sha256="abc123",
        )

        self.assertEqual(bundle["training"]["label_source"], "codex_visual_direct_labels")
        self.assertEqual(bundle["training"]["label_freeze_sha256"], "abc123")
        self.assertEqual(bundle["training"]["source_group_overlap"], [])
        self.assertEqual(metrics["test"]["accuracy"], 1.0)


if __name__ == "__main__":
    unittest.main()
