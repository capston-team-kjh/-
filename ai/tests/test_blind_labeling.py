from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from ai.blind_labeling import (
    BlindInterval,
    BlindLabelError,
    DirectLabel,
    blind_id_for,
    build_blind_intervals,
    read_direct_labels,
    validate_direct_labels,
    validate_manifest_columns,
)


class BlindLabelingTests(unittest.TestCase):
    def test_blind_id_is_stable_and_contains_no_source_name(self) -> None:
        value = blind_id_for("abc123", 10.0, 20.0)

        self.assertEqual(value, blind_id_for("abc123", 10.0, 20.0))
        self.assertTrue(value.startswith("B"))
        self.assertNotIn("abc123", value)

    def test_overlaps_become_non_overlapping_ten_second_intervals(self) -> None:
        rows = [
            {
                "source_sha256": "abc",
                "source_path": "source.mp4",
                "start_sec": "0",
                "end_sec": "15",
            },
            {
                "source_sha256": "abc",
                "source_path": "source.mp4",
                "start_sec": "10",
                "end_sec": "25",
            },
        ]

        intervals = build_blind_intervals(rows)

        self.assertEqual(
            [(row.start_sec, row.end_sec) for row in intervals],
            [(0.0, 10.0), (10.0, 20.0), (20.0, 25.0)],
        )

    def test_existing_label_columns_are_rejected(self) -> None:
        with self.assertRaises(BlindLabelError):
            validate_manifest_columns(["blind_id", "suggested_label"])

    def test_reads_and_validates_an_accepted_direct_label(self) -> None:
        interval = BlindInterval(
            blind_id="B123456789abc",
            source_group="S123456789abc",
            source_sha256="abc",
            source_path=Path("source.mp4"),
            start_sec=0.0,
            end_sec=10.0,
        )
        with TemporaryDirectory() as temp_dir:
            labels_path = Path(temp_dir) / "labels.csv"
            labels_path.write_text(
                "blind_id,direct_label,confidence,evidence,review_status,annotator,annotated_at\n"
                "B123456789abc,focus,high,continuous writing,accepted,codex_visual_direct,2026-07-22T00:00:00+09:00\n",
                encoding="utf-8",
            )

            labels = read_direct_labels(labels_path)
            validate_direct_labels([interval], labels)

        self.assertEqual(labels[0].direct_label, "focus")
        self.assertEqual(labels[0].review_status, "accepted")

    def test_rejects_a_label_outside_the_runtime_classes(self) -> None:
        interval = BlindInterval(
            blind_id="B123456789abc",
            source_group="S123456789abc",
            source_sha256="abc",
            source_path=Path("source.mp4"),
            start_sec=0.0,
            end_sec=10.0,
        )
        label = DirectLabel(
            blind_id=interval.blind_id,
            direct_label="absent",
            confidence="high",
            evidence="empty chair",
            review_status="accepted",
            annotator="codex_visual_direct",
            annotated_at="2026-07-22T00:00:00+09:00",
        )

        with self.assertRaises(BlindLabelError):
            validate_direct_labels([interval], [label])


if __name__ == "__main__":
    unittest.main()
