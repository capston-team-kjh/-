from __future__ import annotations

import csv
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from ai.browser_ml.contracts import load_feature_contract
from ai.browser_ml.legacy_dataset import (
    LeakageError,
    join_source_labels,
    validate_split_leakage,
)
from ai.browser_ml.legacy_sources import (
    HUMAN_DIRECT,
    LegacyLabel,
    VISUAL_DIRECT,
    load_blind_visual_labels,
    load_frame_segment_labels,
    load_human_point_labels,
)


ROOT = Path(__file__).resolve().parents[2]
CONTRACT = load_feature_contract(ROOT)
from ai.browser_ml.legacy_extraction import (
    CacheIdentity,
    cache_key,
    choose_front_half,
    requested_seconds,
)


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


class LegacySourceTests(unittest.TestCase):
    def test_human_point_labels_are_category_a_and_keep_original_recording_group(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            clip = root / "2026-04-15 12-44-13__001__00000-00180s.mp4"
            clip.write_bytes(b"video-fixture")
            manifest = root / "manifest.csv"
            _write_csv(
                manifest,
                ["split", "source_file", "clip_file", "clip_name", "start_sec", "end_sec", "status"],
                [
                    {
                        "split": "train",
                        "source_file": "2026-04-15 12-44-13.mp4",
                        "clip_file": str(clip),
                        "clip_name": clip.name,
                        "start_sec": 0,
                        "end_sec": 180,
                        "status": "created",
                    }
                ],
            )
            labels = root / "human.csv"
            _write_csv(
                labels,
                ["frame_id", "source_video", "t", "human_label"],
                [
                    {
                        "frame_id": "R01_010s",
                        "source_video": clip.name,
                        "t": 10,
                        "human_label": "drowsy",
                    }
                ],
            )

            registry = load_human_point_labels(labels, manifest, split_hint="train")

            self.assertEqual(len(registry.labels), 1)
            label = registry.labels[0]
            self.assertEqual(label.category, HUMAN_DIRECT)
            self.assertEqual(label.source_group_id, "2026-04-15 12-44-13")
            self.assertEqual(label.timestamp_ms, 10_000)
            self.assertEqual(label.source_path, clip.resolve())
            self.assertTrue(label.eligible)


class LegacyExtractionTests(unittest.TestCase):
    def test_cache_key_changes_when_contract_or_source_identity_changes(self) -> None:
        identity = CacheIdentity(
            source_sha256="a" * 64,
            contract_sha256="b" * 64,
            face_model_sha256="c" * 64,
            pose_model_sha256="d" * 64,
            extractor_version="legacy-v2-extractor-1",
            sampling_fps=1,
            camera_half="left",
        )

        self.assertNotEqual(
            cache_key(identity),
            cache_key(replace(identity, contract_sha256="e" * 64)),
        )
        self.assertNotEqual(
            cache_key(identity),
            cache_key(replace(identity, source_sha256="f" * 64)),
        )

    def test_merged_camera_selection_requires_stronger_front_face_evidence(self) -> None:
        decision = choose_front_half(left_face_score=8.0, right_face_score=0.2)

        self.assertEqual(decision.role, "front")
        self.assertEqual(decision.half, "left")
        self.assertTrue(decision.confident)

        ambiguous = choose_front_half(left_face_score=0.2, right_face_score=0.1)
        self.assertFalse(ambiguous.confident)
        self.assertIsNone(ambiguous.half)

    def test_requested_timestamps_include_initial_calibration_and_temporal_history(self) -> None:
        label = type(
            "Label",
            (),
            {
                "eligible": True,
                "timestamp_ms": 60_000,
                "start_ms": None,
                "end_ms": None,
            },
        )()

        seconds = requested_seconds([label], duration_sec=180.0)

        self.assertTrue(set(range(30)).issubset(seconds))
        self.assertTrue(set(range(50, 61)).issubset(seconds))
        self.assertNotIn(61, seconds)


class LegacyAdditionalSourceTests(unittest.TestCase):
    def test_ambiguous_blind_rows_are_audited_but_not_eligible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "chunk.webm"
            source.write_bytes(b"video-fixture")
            review = root / "blind_review.csv"
            _write_csv(
                review,
                ["blind_id", "direct_label", "confidence", "review_status", "annotator"],
                [
                    {
                        "blind_id": "B1",
                        "direct_label": "focus",
                        "confidence": "high",
                        "review_status": "accepted",
                        "annotator": "codex_visual_direct",
                    },
                    {
                        "blind_id": "B2",
                        "direct_label": "",
                        "confidence": "",
                        "review_status": "ambiguous",
                        "annotator": "",
                    },
                ],
            )
            source_map = root / "source_map.csv"
            _write_csv(
                source_map,
                ["blind_id", "source_group", "source_id", "source_path", "start_sec", "end_sec"],
                [
                    {
                        "blind_id": "B1",
                        "source_group": "GROUP-A",
                        "source_id": "source-a",
                        "source_path": str(source),
                        "start_sec": 20,
                        "end_sec": 30,
                    },
                    {
                        "blind_id": "B2",
                        "source_group": "GROUP-A",
                        "source_id": "source-a",
                        "source_path": str(source),
                        "start_sec": 30,
                        "end_sec": 40,
                    },
                ],
            )

            registry = load_blind_visual_labels(review, source_map)

            self.assertEqual(len(registry.labels), 2)
            accepted, ambiguous = registry.labels
            self.assertEqual(accepted.category, VISUAL_DIRECT)
            self.assertTrue(accepted.eligible)
            self.assertEqual((accepted.start_ms, accepted.end_ms), (20_000, 30_000))
            self.assertFalse(ambiguous.eligible)
            self.assertEqual(ambiguous.exclusion_reason, "ambiguous")

    def test_frame_segments_require_manifest_source_and_preserve_provisional_status(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "recording.mp4"
            source.write_bytes(b"video-fixture")
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "videos": [
                            {
                                "video_id": "recording",
                                "source_path": str(source),
                                "sha256": "a" * 64,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            segments = root / "segments.csv"
            _write_csv(
                segments,
                ["video_id", "segment_id", "start_sec", "end_sec", "label", "confidence", "review_status"],
                [
                    {
                        "video_id": "recording",
                        "segment_id": "s1",
                        "start_sec": 1,
                        "end_sec": 3,
                        "label": "gaze_side",
                        "confidence": "medium",
                        "review_status": "provisional",
                    }
                ],
            )

            registry = load_frame_segment_labels(segments, manifest)

            self.assertEqual(len(registry.labels), 1)
            label = registry.labels[0]
            self.assertEqual(label.category, VISUAL_DIRECT)
            self.assertEqual(label.review_status, "provisional")
            self.assertEqual(label.source_sha256, "a" * 64)
            self.assertTrue(label.eligible)


class LegacyDatasetTests(unittest.TestCase):
    def _feature_row(self, timestamp_ms: int) -> dict[str, object]:
        row: dict[str, object] = {
            "timestamp_ms": timestamp_ms,
            "vector_ready": "True",
            "missing_features": "",
        }
        row.update({name: 0.25 for name in CONTRACT.feature_names})
        return row

    def _point_label(self) -> LegacyLabel:
        return LegacyLabel(
            label_id="H1",
            source_path=Path("source.mp4"),
            source_group_id="recording-a",
            source_id="source-a",
            source_sha256="a" * 64,
            label="focus",
            category=HUMAN_DIRECT,
            label_source="human.csv",
            review_status="accepted",
            confidence="human_direct",
            annotator="human",
            eligible=True,
            exclusion_reason=None,
            split_hint="train",
            timestamp_ms=10_000,
        )

    def test_point_label_selects_only_the_nearest_one_fps_row(self) -> None:
        rows, exclusions = join_source_labels(
            [self._feature_row(9_000), self._feature_row(10_000), self._feature_row(11_000)],
            [self._point_label()],
            CONTRACT,
        )

        self.assertEqual([row["timestamp_ms"] for row in rows], [10_000])
        self.assertEqual(rows[0]["label_id"], "H1")
        self.assertEqual(exclusions, ())

    def test_same_original_recording_or_hash_cannot_cross_splits(self) -> None:
        base = {
            "source_group_id": "recording-a",
            "session_id": "recording-a",
            "source_sha256": "a" * 64,
            "label_id": "H1",
            "timestamp_ms": 10_000,
        }

        with self.assertRaisesRegex(LeakageError, "source_group_id"):
            validate_split_leakage(
                [{**base, "split": "train"}, {**base, "split": "test", "label_id": "H2"}]
            )

    def test_rows_without_all_finite_contract_features_are_excluded(self) -> None:
        feature = self._feature_row(10_000)
        feature[CONTRACT.feature_names[3]] = ""

        rows, exclusions = join_source_labels([feature], [self._point_label()], CONTRACT)

        self.assertEqual(rows, ())
        self.assertEqual(exclusions[0].reason, "feature_row_not_model_ready")


if __name__ == "__main__":
    unittest.main()
