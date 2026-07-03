from __future__ import annotations

import unittest

try:
    from analyzer.focus_score import calculate_focus_score
    from focus_ai.feedback_generator import build_feedback_evidence, generate_feedback
except ModuleNotFoundError:
    from ai.analyzer.focus_score import calculate_focus_score
    from ai.focus_ai.feedback_generator import build_feedback_evidence, generate_feedback


class FocusScoreTest(unittest.TestCase):
    def test_requested_example_returns_74(self) -> None:
        summary = {
            "focus_time_sec": 2400,
            "bad_posture_total_sec": 600,
            "gaze_away_total_sec": 0,
            "drowsy_total_sec": 300,
            "absent_total_sec": 300,
            "bad_posture_count": 1,
            "gaze_away_count": 0,
            "drowsy_count": 1,
            "absent_count": 1,
        }

        result = calculate_focus_score(summary, total_time_sec=3600)

        self.assertEqual(result["weighted_base_score"], 78.3)
        self.assertEqual(result["event_penalty"], 4.0)
        self.assertEqual(result["focus_score"], 74)

    def test_zero_total_time_adds_warning_and_zero_score(self) -> None:
        result = calculate_focus_score({"focus_time_sec": 10}, total_time_sec=0)

        self.assertEqual(result["focus_score"], 0)
        self.assertIn("total_time_sec is missing or zero", result["warnings"][0])

    def test_overlapping_times_are_capped_by_priority(self) -> None:
        summary = {
            "focus_time_sec": 100,
            "bad_posture_total_sec": 100,
            "gaze_away_total_sec": 100,
            "drowsy_total_sec": 100,
            "absent_total_sec": 100,
        }

        result = calculate_focus_score(summary, total_time_sec=250)

        self.assertEqual(result["absent_total_sec"], 100)
        self.assertEqual(result["drowsy_total_sec"], 100)
        self.assertEqual(result["gaze_away_total_sec"], 50)
        self.assertEqual(result["bad_posture_total_sec"], 0)
        self.assertEqual(result["focus_time_sec"], 0)

    def test_unknown_time_uses_mid_weight_in_score(self) -> None:
        summary = {
            "focus_time_sec": 50,
            "unknown_total_sec": 50,
        }

        result = calculate_focus_score(summary, total_time_sec=100)

        self.assertEqual(result["weighted_base_score"], 75.0)
        self.assertEqual(result["focus_score"], 75)


class FeedbackGeneratorTest(unittest.TestCase):
    def test_feedback_uses_focus_score_and_largest_problem_time(self) -> None:
        feedback = generate_feedback(
            {
                "focus_score": 74,
                "absent_total_sec": 10,
                "drowsy_total_sec": 300,
                "gaze_away_total_sec": 0,
                "bad_posture_total_sec": 20,
            }
        )

        self.assertIn("74점", feedback["summary_text"])
        self.assertIn("양호", feedback["summary_text"])
        self.assertIn("졸음 의심", feedback["weak_point"])
        self.assertIn("5분", feedback["weak_point"])
        self.assertIn("25~30분", feedback["recommendation"])

    def test_feedback_evidence_explains_worst_segment(self) -> None:
        summary = {
            "focus_score": 26,
            "focus_total_sec": 10,
            "drowsy_total_sec": 20,
            "absent_total_sec": 30,
            "unknown_total_sec": 40,
        }
        time_patterns = {
            "segments": [
                {
                    "start_sec": 0,
                    "end_sec": 300,
                    "focus_ratio": 0.1,
                    "state_counts": {"focus": 30, "unknown": 120, "absent": 90, "drowsy": 60},
                    "dominant_state": "unknown",
                    "main_issue": "unknown",
                }
            ],
            "worst_segment": {"start_sec": 0, "end_sec": 300, "focus_ratio": 0.1},
            "best_segment": {"start_sec": 0, "end_sec": 300, "focus_ratio": 0.1},
        }
        events = [
            {"type": "unknown", "source": "final", "start_sec": 10, "end_sec": 80},
            {"type": "overhead_no_activity", "source": "overhead", "start_sec": 0, "end_sec": 300},
        ]
        timeline = (
            [{"t": t, "state": "focus"} for t in range(0, 10)]
            + [{"t": t, "state": "unknown"} for t in range(10, 20)]
            + [{"t": t, "state": "drowsy"} for t in range(20, 25)]
            + [{"t": t, "state": "focus"} for t in range(25, 30)]
        )

        evidence = build_feedback_evidence(summary, time_patterns, events, timeline)

        self.assertEqual(evidence["worst_segment"]["time_range"], "0:00-5:00")
        self.assertEqual(evidence["worst_segment"]["focus_percent"], 10)
        self.assertEqual(evidence["worst_segment"]["state_breakdown"][0]["state"], "unknown")
        self.assertEqual(evidence["worst_segment"]["supporting_events"][0]["type"], "unknown")
        self.assertIn("가장 낮은 집중률", evidence["lowest_focus_reason"])
        self.assertEqual(evidence["longest_problem_streak"]["time_range"], "0:10-0:25")
        self.assertEqual(evidence["longest_problem_streak"]["duration_sec"], 15)
        self.assertEqual(evidence["longest_problem_streak"]["dominant_state"], "unknown")


if __name__ == "__main__":
    unittest.main()
