from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from focus_ai import video_preflight  # noqa: E402


class _RecoverableGapCapture:
    def __init__(self) -> None:
        self.current_sec = -1.0
        self.next_sec = 0.0
        self.failed_at_gap = False
        self.seek_target: float | None = None

    def isOpened(self) -> bool:
        return True

    def read(self):
        if self.seek_target is not None:
            target = self.seek_target
            self.seek_target = None
            if target < 5.0:
                return False, None
            self.current_sec = target
            self.next_sec = target + 1.0
            return True, object()

        if self.next_sec == 3.0 and not self.failed_at_gap:
            self.failed_at_gap = True
            return False, None
        if self.next_sec > 10.0:
            return False, None

        self.current_sec = self.next_sec
        self.next_sec += 1.0
        return True, object()

    def get(self, prop: int) -> float:
        if prop == video_preflight.cv2.CAP_PROP_POS_MSEC:
            return self.current_sec * 1000.0
        return 0.0

    def set(self, prop: int, value: float) -> bool:
        if prop == video_preflight.cv2.CAP_PROP_POS_MSEC:
            self.seek_target = value / 1000.0
            return True
        return False

    def release(self) -> None:
        return None


class VideoPreflightTest(unittest.TestCase):
    def test_scan_recovers_a_midstream_decode_gap(self) -> None:
        with patch.object(
            video_preflight.cv2,
            "VideoCapture",
            return_value=_RecoverableGapCapture(),
        ):
            scan = video_preflight._scan_video(Path("sample.webm"), 11.0)

        self.assertFalse(scan["early_eof"])
        self.assertEqual(len(scan["decode_gaps"]), 1)
        self.assertEqual(scan["decode_gaps"][0]["start_sec"], 2.0)
        self.assertEqual(scan["decode_gaps"][0]["end_sec"], 5.0)
        self.assertTrue(video_preflight._needs_normalization(scan))

    def test_clean_full_coverage_does_not_require_normalization(self) -> None:
        scan = {
            "early_eof": False,
            "decode_gaps": [],
            "coverage_ratio": 0.999,
        }
        self.assertFalse(video_preflight._needs_normalization(scan))

    def test_duration_match_uses_small_rounding_tolerance(self) -> None:
        self.assertTrue(video_preflight._duration_matches(3600.0, 3599.7))
        self.assertFalse(video_preflight._duration_matches(3600.0, 3500.0))

    def test_scan_timing_is_reusable_by_merged_analysis(self) -> None:
        timing = video_preflight._decoded_timing_from_scan({
            "decoded_frames": 6096,
            "effective_fps": 9.9983,
            "first_timestamp_sec": 0.0,
            "last_timestamp_sec": 609.605,
        })

        self.assertEqual(timing["decoded_frame_count"], 6096)
        self.assertAlmostEqual(timing["effective_fps"], 9.9983, places=4)
        self.assertEqual(timing["first_timestamp_ms"], 0.0)
        self.assertAlmostEqual(timing["last_timestamp_ms"], 609605.0, places=3)


if __name__ == "__main__":
    unittest.main()
