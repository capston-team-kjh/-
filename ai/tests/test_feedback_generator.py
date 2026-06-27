from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from focus_ai.feedback_generator import generate_personal_feedback  # noqa: E402


class PersonalFeedbackTest(unittest.TestCase):
    def test_detects_late_study_focus_decline_without_api_key(self) -> None:
        segments = [
            {
                "start_sec": 0,
                "end_sec": 600,
                "focus_ratio": 0.9,
                "state_counts": {"focus": 540, "gaze_side": 20, "bad_posture": 20, "drowsy": 20},
                "main_issue": "gaze_side",
            },
            {
                "start_sec": 600,
                "end_sec": 1200,
                "focus_ratio": 0.85,
                "state_counts": {"focus": 510, "gaze_side": 30, "bad_posture": 30, "drowsy": 30},
                "main_issue": "bad_posture",
            },
            {
                "start_sec": 3600,
                "end_sec": 4200,
                "focus_ratio": 0.45,
                "state_counts": {"focus": 270, "gaze_side": 160, "bad_posture": 100, "drowsy": 70},
                "main_issue": "gaze_side",
            },
            {
                "start_sec": 4200,
                "end_sec": 4800,
                "focus_ratio": 0.35,
                "state_counts": {"focus": 210, "gaze_side": 200, "bad_posture": 130, "drowsy": 60},
                "main_issue": "gaze_side",
            },
        ]
        analysis_result = {
            "status": "success",
            "meta": {"duration_sec": 4800},
            "summary": {
                "focus_score": 72,
                "concentration_score": 72,
                "focus_total_sec": 1530,
                "gaze_away_total_sec": 410,
                "gaze_away_count": 12,
                "bad_posture_total_sec": 280,
                "drowsy_total_sec": 150,
            },
            "time_patterns": {"segments": segments},
            "events": [],
        }

        with patch.dict(os.environ, {}, clear=True):
            feedback = generate_personal_feedback(analysis_result)

        self.assertEqual(feedback["main_problem"], "후반부 집중 저하")
        self.assertIn("50분", feedback["next_action"])
        self.assertGreaterEqual(len(feedback["worst_segments"]), 1)
        self.assertLessEqual(len(feedback["worst_segments"]), 3)
        self.assertEqual(feedback["worst_segments"][0]["start_sec"], 4200)

    def test_api_failure_falls_back_to_rule_feedback(self) -> None:
        analysis_result = {
            "status": "success",
            "meta": {"duration_sec": 900},
            "summary": {
                "focus_score": 60,
                "gaze_away_total_sec": 180,
                "gaze_away_count": 7,
            },
            "timeline": [],
            "events": [],
        }

        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=True):
            with patch("focus_ai.feedback_generator._call_ai_feedback", side_effect=TimeoutError):
                feedback = generate_personal_feedback(analysis_result)

        self.assertEqual(feedback["main_problem"], "시선이탈 증가")
        self.assertIn("주변 방해 요소", feedback["feedback"])

if __name__ == "__main__":
    unittest.main()
