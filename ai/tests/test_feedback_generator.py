from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from focus_ai.feedback_generator import generate_feedback, generate_personal_feedback  # noqa: E402


class PersonalFeedbackTest(unittest.TestCase):
    def test_codex_correction_overrides_stale_raw_eye_and_posture_flags(self) -> None:
        timeline = [
            {
                "t": t,
                "state": "focus",
                "decision_source": "codex_manual_review" if 20 <= t < 30 else "rule",
                "flags": {"eye_closed": True, "head_down": True, "head_tilt": True},
            }
            for t in range(60)
        ]
        analysis_result = {
            "status": "success",
            "meta": {"duration_sec": 60},
            "summary": {
                "focus_score": 100,
                "focus_total_sec": 60,
                "drowsy_total_sec": 0,
                "eye_closed_total_sec": 60,
                "long_eye_closure_count": 3,
                "bad_posture_total_sec": 0,
                "head_down_total_sec": 60,
                "head_tilt_total_sec": 60,
            },
            "timeline": timeline,
            "events": [],
        }

        with patch.dict(os.environ, {}, clear=True):
            feedback = generate_personal_feedback(analysis_result)

        self.assertEqual(feedback["main_problem"], "집중 패턴 안정")

    def test_tiny_unknown_ratio_does_not_claim_recognition_is_high(self) -> None:
        feedback = generate_feedback(
            {
                "focus_score": 100,
                "duration_sec": 275,
                "focus_total_sec": 274,
                "present_total_sec": 275,
                "unknown_total_sec": 1,
            }
        )

        self.assertNotIn("비중이 높습니다", feedback["recommendation"])

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

    def test_overlapping_posture_flags_are_not_double_counted(self) -> None:
        timeline = [
            {
                "t": t,
                "state": "bad_posture" if t < 30 else "focus",
                "flags": {
                    "bad_posture": t < 30,
                    "head_down": t < 30,
                    "head_tilt": t < 30,
                },
            }
            for t in range(100)
        ]
        analysis_result = {
            "status": "success",
            "meta": {"duration_sec": 100},
            "summary": {
                "focus_score": 70,
                "focus_total_sec": 70,
                "bad_posture_total_sec": 30,
                "head_down_total_sec": 30,
                "head_tilt_total_sec": 30,
                "bad_posture_count": 1,
            },
            "timeline": timeline,
            "events": [],
        }

        with patch.dict(os.environ, {}, clear=True):
            feedback = generate_personal_feedback(analysis_result)

        self.assertEqual(feedback["main_problem"], "자세불량 또는 고개 숙임")
        self.assertIn("30초", feedback["reason"])
        self.assertNotIn("1분 30초", feedback["reason"])

if __name__ == "__main__":
    unittest.main()
