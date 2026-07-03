from __future__ import annotations

import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from focus_ai.analyze import _detect_camera_role_assignment  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
