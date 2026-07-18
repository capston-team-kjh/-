from __future__ import annotations

import unittest

from ai.training_scene_prep import (
    ReviewedScene,
    clip_filename,
    group_timeline_candidates,
    shortage_rows,
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


if __name__ == "__main__":
    unittest.main()
