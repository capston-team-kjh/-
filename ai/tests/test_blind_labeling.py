from __future__ import annotations

import csv
import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import cv2
import numpy as np

from ai.blind_labeling import (
    BlindInterval,
    BlindLabelError,
    DirectLabel,
    blind_id_for,
    build_blind_intervals,
    freeze_review_workspace,
    read_direct_labels,
    validate_direct_labels,
    validate_manifest_columns,
    verify_review_workspace,
    write_blind_contact_sheet,
    write_review_workspace,
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


def _write_synthetic_video(path: Path, *, fps: int = 5, seconds: int = 12) -> None:
    writer = cv2.VideoWriter(
        str(path),
        cv2.VideoWriter_fourcc(*"MJPG"),
        fps,
        (96, 64),
    )
    if not writer.isOpened():
        raise RuntimeError("could not create synthetic video")
    for index in range(fps * seconds):
        frame = np.full((64, 96, 3), index % 255, dtype=np.uint8)
        writer.write(frame)
    writer.release()


class BlindWorkspaceTests(unittest.TestCase):
    def test_contact_sheet_has_five_tiles_without_source_caption(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "focus__leaking-name.avi"
            output = root / "sheet.jpg"
            _write_synthetic_video(source)
            interval = BlindInterval(
                blind_id="B123456789abc",
                source_group="S123456789abc",
                source_sha256="abc",
                source_path=source,
                start_sec=0.0,
                end_sec=10.0,
            )

            write_blind_contact_sheet(interval, output)

            sheet = cv2.imread(str(output))
            self.assertIsNotNone(sheet)
            self.assertGreaterEqual(sheet.shape[1], 5 * 200)

    def test_workspace_omits_previous_label_fields(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.avi"
            manifest = root / "clips_manifest.csv"
            output = root / "review"
            _write_synthetic_video(source)
            with manifest.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(
                    stream,
                    fieldnames=[
                        "clip_path",
                        "label",
                        "cue",
                        "disposition",
                        "source_id",
                        "source_path",
                        "source_sha256",
                        "start_sec",
                        "end_sec",
                        "duration_sec",
                        "notes",
                    ],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "clip_path": "train_ready/focus/leaking.mp4",
                        "label": "focus",
                        "cue": "writing",
                        "disposition": "ready",
                        "source_id": "source01",
                        "source_path": str(source),
                        "source_sha256": "abc",
                        "start_sec": "0",
                        "end_sec": "12",
                        "duration_sec": "12",
                        "notes": "old answer",
                    }
                )

            summary = write_review_workspace(manifest, output)

            with (output / "blind_review.csv").open(newline="", encoding="utf-8-sig") as stream:
                reader = csv.DictReader(stream)
                rows = list(reader)
                self.assertEqual(
                    reader.fieldnames,
                    [
                        "blind_id",
                        "sheet_path",
                        "direct_label",
                        "confidence",
                        "evidence",
                        "review_status",
                        "annotator",
                        "annotated_at",
                    ],
                )
            review_text = (output / "blind_review.csv").read_text(encoding="utf-8-sig")
            source_map_text = (output / "private" / "source_map.csv").read_text(encoding="utf-8-sig")
            self.assertEqual(len(rows), 2)
            self.assertNotIn("focus", review_text)
            self.assertNotIn(str(source), review_text)
            self.assertNotIn("focus", source_map_text)
            self.assertEqual(summary["input_clips"], 1)
            self.assertEqual(summary["interval_count"], 2)
            self.assertEqual(
                json.loads((output / "summary.json").read_text(encoding="utf-8"))["pending_count"],
                2,
            )

    def test_verify_rejects_pending_rows_unless_explicitly_allowed(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.avi"
            manifest = root / "clips_manifest.csv"
            output = root / "review"
            _write_synthetic_video(source, seconds=5)
            self._write_manifest(manifest, source, end_sec=5)
            write_review_workspace(manifest, output)

            self.assertEqual(verify_review_workspace(output, allow_pending=True)["pending_count"], 1)
            with self.assertRaises(BlindLabelError):
                verify_review_workspace(output)

    def test_freeze_writes_sanitized_labels_and_checksum(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.avi"
            manifest = root / "clips_manifest.csv"
            output = root / "review"
            labels_output = root / "committed" / "blind_labels.csv"
            summary_output = root / "committed" / "summary.json"
            _write_synthetic_video(source, seconds=5)
            self._write_manifest(manifest, source, end_sec=5)
            write_review_workspace(manifest, output)
            review_path = output / "blind_review.csv"
            with review_path.open(newline="", encoding="utf-8-sig") as stream:
                rows = list(csv.DictReader(stream))
            rows[0].update(
                {
                    "direct_label": "focus",
                    "confidence": "high",
                    "evidence": "writing throughout",
                    "review_status": "accepted",
                    "annotator": "codex_visual_direct",
                    "annotated_at": "2026-07-22T00:00:00+09:00",
                }
            )
            with review_path.open("w", newline="", encoding="utf-8-sig") as stream:
                writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)

            summary = freeze_review_workspace(output, labels_output, summary_output)

            labels_text = labels_output.read_text(encoding="utf-8-sig")
            self.assertNotIn(str(source), labels_text)
            self.assertNotIn("sheet_path", labels_text)
            self.assertEqual(summary["accepted_count"], 1)
            self.assertEqual(len(summary["label_freeze_sha256"]), 64)
            self.assertEqual(
                json.loads(summary_output.read_text(encoding="utf-8"))["label_source"],
                "codex_visual_direct",
            )

    def test_cli_help_lists_prepare_verify_and_freeze(self) -> None:
        script = Path(__file__).parents[2] / "scripts" / "prepare_focusai_blind_labels.py"

        result = subprocess.run(
            [sys.executable, "-B", str(script), "--help"],
            cwd=Path(__file__).parents[2],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("prepare", result.stdout)
        self.assertIn("verify", result.stdout)
        self.assertIn("freeze", result.stdout)

    @staticmethod
    def _write_manifest(path: Path, source: Path, *, end_sec: int) -> None:
        with path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(
                stream,
                fieldnames=[
                    "clip_path",
                    "label",
                    "cue",
                    "disposition",
                    "source_id",
                    "source_path",
                    "source_sha256",
                    "start_sec",
                    "end_sec",
                    "duration_sec",
                    "notes",
                ],
            )
            writer.writeheader()
            writer.writerow(
                {
                    "clip_path": "train_ready/focus/leaking.mp4",
                    "label": "focus",
                    "cue": "writing",
                    "disposition": "ready",
                    "source_id": "source01",
                    "source_path": str(source),
                    "source_sha256": "abc",
                    "start_sec": "0",
                    "end_sec": str(end_sec),
                    "duration_sec": str(end_sec),
                    "notes": "old answer",
                }
            )


if __name__ == "__main__":
    unittest.main()
