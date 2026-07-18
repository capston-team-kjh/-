from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from ai.training_scene_prep import (
    ReviewedScene,
    clip_filename,
    extract_clip,
    group_timeline_candidates,
    probe_video,
    sha256_file,
    shortage_rows,
    write_overview_sheets,
    write_scene_contact_sheet,
)


class TrainingScenePrepCoreTests(unittest.TestCase):
    def test_grouping_merges_two_second_gap_and_pads(self) -> None:
        timeline = [
            {"t": 10, "rule_state": "gaze_down", "flags": {"gaze_down": True}},
            {"t": 11, "rule_state": "gaze_down", "flags": {"gaze_down": True}},
            {"t": 14, "rule_state": "gaze_down", "flags": {"gaze_down": True}},
        ]

        rows = group_timeline_candidates("session54", timeline, duration_sec=100)

        self.assertEqual(
            [(row.start_sec, row.end_sec, row.suggested_label) for row in rows],
            [(8.0, 17.0, "gaze_down")],
        )

    def test_filename_is_traceable_ascii(self) -> None:
        scene = ReviewedScene(
            source_id="session54",
            start_sec=120,
            end_sec=134,
            label="focus",
            cue="writing_head_down",
            disposition="ready",
            notes="clear",
        )

        self.assertEqual(
            clip_filename(scene),
            "focus__writing-head-down__session54__000120-000134.mp4",
        )

    def test_shortage_uses_count_duration_and_source_minimums(self) -> None:
        scenes = [
            ReviewedScene(
                source_id="s1",
                start_sec=0,
                end_sec=10,
                label="gaze_down",
                cue="off_task",
                disposition="ready",
                notes="clear",
            )
        ]

        row = {item["label"]: item for item in shortage_rows(scenes)}["gaze_down"]

        self.assertTrue(row["is_shortage"])
        self.assertGreaterEqual(
            set(row["reasons"]),
            {"clips<20", "duration<180s", "sources<3"},
        )

    def test_long_candidates_are_split_to_thirty_seconds(self) -> None:
        timeline = [
            {"t": second, "rule_state": "focus", "flags": {"face_seen": True}}
            for second in range(70)
        ]

        rows = group_timeline_candidates("long", timeline, duration_sec=70)

        self.assertGreater(len(rows), 1)
        self.assertTrue(all(row.end_sec - row.start_sec <= 30 for row in rows))
        self.assertEqual(rows[0].start_sec, 0)
        self.assertEqual(rows[-1].end_sec, 70)

    def test_short_drowsy_candidate_expands_to_twelve_seconds(self) -> None:
        timeline = [
            {"t": second, "rule_state": "drowsy", "flags": {"eye_closed": True}}
            for second in range(20, 23)
        ]

        rows = group_timeline_candidates("sleep", timeline, duration_sec=60)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].end_sec - rows[0].start_sec, 12)

    def test_shortage_includes_ready_labels_with_no_scenes(self) -> None:
        labels = {row["label"] for row in shortage_rows([])}

        self.assertEqual(
            labels,
            {"focus", "drowsy", "gaze_down", "gaze_side", "unknown"},
        )


def _write_synthetic_video(
    path: Path,
    *,
    fps: int,
    seconds: int,
    width: int,
    height: int,
) -> None:
    writer = cv2.VideoWriter(
        str(path),
        cv2.VideoWriter_fourcc(*"MJPG"),
        fps,
        (width, height),
    )
    if not writer.isOpened():
        raise RuntimeError("could not create synthetic video")
    for index in range(fps * seconds):
        frame = np.full((height, width, 3), index % 255, dtype=np.uint8)
        writer.write(frame)
    writer.release()


class TrainingScenePrepMediaTests(unittest.TestCase):
    def test_extract_clip_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.avi"
            output = root / "clip.mp4"
            _write_synthetic_video(source, fps=10, seconds=5, width=64, height=48)

            extract_clip(source, output, start_sec=1.0, end_sec=4.0)
            meta = probe_video(output)

            self.assertTrue(meta.opened)
            self.assertLessEqual(abs(meta.duration_sec - 3.0), 0.2)
            self.assertEqual((meta.width, meta.height), (64, 48))

    def test_overview_sheet_is_readable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.avi"
            _write_synthetic_video(source, fps=10, seconds=12, width=64, height=48)

            pages = write_overview_sheets(
                source,
                root / "sheets",
                source_id="synthetic",
                every_sec=5,
                frames_per_page=3,
            )

            self.assertEqual(len(pages), 1)
            self.assertIsNotNone(cv2.imread(str(pages[0])))

    def test_scene_contact_sheet_is_readable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.avi"
            output = root / "candidate.jpg"
            _write_synthetic_video(source, fps=10, seconds=12, width=64, height=48)

            written = write_scene_contact_sheet(
                source,
                output,
                source_id="synthetic",
                start_sec=2,
                end_sec=10,
                sample_count=5,
            )

            self.assertEqual(written, output)
            self.assertIsNotNone(cv2.imread(str(output)))

    def test_sha256_file_matches_known_value(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "value.bin"
            path.write_bytes(b"abc")

            self.assertEqual(
                sha256_file(path),
                "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
            )


if __name__ == "__main__":
    unittest.main()
