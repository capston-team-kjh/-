from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from time_utils import calculate_duration_sec, normalize_session_end_time  # noqa: E402


class SessionTimeUtilsTest(unittest.TestCase):
    def test_same_date_duration(self) -> None:
        started = datetime(2026, 6, 26, 10, 0, 0)
        ended = datetime(2026, 6, 26, 10, 25, 0)

        self.assertEqual(calculate_duration_sec(started, ended), 1500)

    def test_cross_midnight_time_is_moved_to_next_day(self) -> None:
        started = datetime(2026, 6, 26, 23, 50, 0)
        ended = datetime(2026, 6, 26, 0, 10, 0)

        normalized_end = normalize_session_end_time(started, ended)

        self.assertEqual(normalized_end, datetime(2026, 6, 27, 0, 10, 0))
        self.assertEqual(calculate_duration_sec(started, ended), 1200)


if __name__ == "__main__":
    unittest.main()
