from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from ai.browser_ml.legacy_sources import (
    HUMAN_DIRECT,
    VISUAL_DIRECT,
    load_blind_visual_labels,
    load_frame_segment_labels,
    load_human_point_labels,
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


if __name__ == "__main__":
    unittest.main()
