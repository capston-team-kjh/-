from __future__ import annotations

import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from focus_ai.analyze import (  # noqa: E402
    AnalyzeConfig,
    _analyze_split_videos,
    _detect_camera_role_assignment,
)


def _result(duration_sec: int, face_seen_seconds: int) -> dict:
    return {
        "meta": {"duration_sec": duration_sec},
        "timeline": [
            {"t": t, "flags": {"face_seen": t < face_seen_seconds}}
            for t in range(duration_sec)
        ],
    }


class CameraRoleDetectionTest(unittest.TestCase):
    def test_swaps_when_right_side_has_clear_face_evidence(self) -> None:
        decision = _detect_camera_role_assignment(
            _result(609, 3),
            _result(609, 472),
        )

        self.assertTrue(decision["confident"])
        self.assertTrue(decision["swapped"])
        self.assertEqual(decision["face_camera_side"], "right")

    def test_keeps_default_when_left_side_has_clear_face_evidence(self) -> None:
        decision = _detect_camera_role_assignment(
            _result(600, 480),
            _result(600, 4),
        )

        self.assertTrue(decision["confident"])
        self.assertFalse(decision["swapped"])
        self.assertEqual(decision["face_camera_side"], "left")

    def test_keeps_default_when_evidence_is_ambiguous(self) -> None:
        decision = _detect_camera_role_assignment(
            _result(600, 200),
            _result(600, 210),
        )

        self.assertFalse(decision["confident"])
        self.assertFalse(decision["swapped"])

    def test_split_camera_analyses_run_concurrently(self) -> None:
        barrier = threading.Barrier(2)

        def fake_analyze(session_id, video_path, camera_type, config):
            barrier.wait(timeout=2.0)
            return {"video_path": video_path, "camera_type": camera_type}

        with patch("focus_ai.analyze.analyze_absent", side_effect=fake_analyze):
            front, overhead = _analyze_split_videos(
                "S1",
                "front.mp4",
                "overhead.mp4",
                AnalyzeConfig(parallel_merged_analysis=True),
            )

        self.assertEqual(front, {"video_path": "front.mp4", "camera_type": "front"})
        self.assertEqual(
            overhead,
            {"video_path": "overhead.mp4", "camera_type": "overhead"},
        )


if __name__ == "__main__":
    unittest.main()
