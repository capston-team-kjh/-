from __future__ import annotations

import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from focus_ai.analyze import _fps_from_decoded_timing  # noqa: E402


class VideoTimingTest(unittest.TestCase):
    def test_webm_nominal_fps_is_replaced_by_timestamp_fps(self) -> None:
        fps = _fps_from_decoded_timing(
            decoded_frame_count=6096,
            first_timestamp_ms=0.0,
            last_timestamp_ms=609605.0,
            reported_fps=60.0,
            reported_frame_count=36576.0,
        )

        self.assertAlmostEqual(fps, 10.0, places=2)
        self.assertAlmostEqual(6096 / fps, 609.7, places=1)

    def test_constant_fps_video_keeps_its_rate(self) -> None:
        fps = _fps_from_decoded_timing(
            decoded_frame_count=300,
            first_timestamp_ms=0.0,
            last_timestamp_ms=9966.6667,
            reported_fps=30.0,
            reported_frame_count=300.0,
        )

        self.assertAlmostEqual(fps, 30.0, places=2)

    def test_container_duration_is_used_when_timestamps_are_missing(self) -> None:
        fps = _fps_from_decoded_timing(
            decoded_frame_count=6096,
            first_timestamp_ms=None,
            last_timestamp_ms=None,
            reported_fps=60.0,
            reported_frame_count=36576.0,
        )

        self.assertAlmostEqual(fps, 10.0, places=2)


if __name__ == "__main__":
    unittest.main()
