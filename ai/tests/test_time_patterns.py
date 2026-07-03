from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


def _install_import_stubs() -> None:
    for name in ("pymysql", "cv2"):
        sys.modules.setdefault(name, types.ModuleType(name))

    mediapipe = types.ModuleType("mediapipe")
    mediapipe_tasks = types.ModuleType("mediapipe.tasks")
    mediapipe_tasks_python = types.ModuleType("mediapipe.tasks.python")
    mediapipe_vision = types.ModuleType("mediapipe.tasks.python.vision")

    mediapipe.tasks = mediapipe_tasks
    mediapipe_tasks.python = mediapipe_tasks_python
    mediapipe_tasks_python.vision = mediapipe_vision

    sys.modules.setdefault("mediapipe", mediapipe)
    sys.modules.setdefault("mediapipe.tasks", mediapipe_tasks)
    sys.modules.setdefault("mediapipe.tasks.python", mediapipe_tasks_python)
    sys.modules.setdefault("mediapipe.tasks.python.vision", mediapipe_vision)


_install_import_stubs()
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from focus_ai.analyze import (  # noqa: E402
    AnalyzeConfig,
    build_time_patterns,
    _create_events_from_states,
    _decide_hybrid_state,
    _eye_closed_with_hysteresis,
    _filter_segments_by_duration,
    _low_motion_for_segments,
    _open_eye_baseline,
    _predict_model_state,
    classify_missing_face_state,
    resolve_front_absence_with_overhead,
)


class TimePatternsTest(unittest.TestCase):
    def test_drowsy_defaults_require_ten_seconds_and_personal_ear(self) -> None:
        config = AnalyzeConfig()

        self.assertEqual(config.long_eye_closure_min_sec, 10)
        self.assertEqual(config.drowsy_min_duration_sec, 10)
        self.assertAlmostEqual(config.ear_baseline_ratio, 0.58)

    def test_eye_closure_hysteresis_requires_both_eyes(self) -> None:
        right = _eye_closed_with_hysteresis([0.20, 0.10, 0.11, 0.18], 0.12, 0.15)
        left = _eye_closed_with_hysteresis([0.20, 0.10, None, 0.10], 0.12, 0.15)
        both = [right[index] and left[index] for index in range(len(right))]

        self.assertEqual(right, [False, True, True, False])
        self.assertEqual(left, [False, True, False, True])
        self.assertEqual(both, [False, True, False, False])

    def test_long_eye_closure_rejects_nine_seconds(self) -> None:
        self.assertFalse(any(_filter_segments_by_duration([True] * 9, min_duration_sec=10)))
        self.assertTrue(all(_filter_segments_by_duration([True] * 10, min_duration_sec=10)))

    def test_low_head_motion_is_required_for_closed_segment(self) -> None:
        closed = [True] * 10
        still = _low_motion_for_segments(closed, [None] + [0.01] * 9, 3, 0.035)
        moving = _low_motion_for_segments(closed, [None] + [0.08] * 9, 3, 0.035)

        self.assertTrue(all(still))
        self.assertFalse(any(moving))

    def test_open_eye_baseline_uses_upper_samples(self) -> None:
        baseline = _open_eye_baseline([0.08, 0.09, 0.10, 0.20, 0.21, 0.22])

        self.assertAlmostEqual(baseline, 0.215)

    def test_builds_segments_and_insights(self) -> None:
        timeline = (
            [{"t": t, "state": "focus", "states": ["focus"]} for t in range(0, 240)]
            + [{"t": t, "state": "gaze_side", "states": ["gaze_side"]} for t in range(240, 300)]
            + [{"t": t, "state": "focus", "states": ["focus"]} for t in range(300, 450)]
            + [{"t": t, "state": "bad_posture", "states": ["bad_posture"]} for t in range(450, 600)]
        )

        result = build_time_patterns(timeline, interval_sec=300, duration_sec=600)

        self.assertEqual(result["interval_sec"], 300)
        self.assertEqual(len(result["segments"]), 2)
        self.assertEqual(result["segments"][0]["focus_ratio"], 0.8)
        self.assertEqual(result["segments"][0]["risk_level"], "good")
        self.assertEqual(result["segments"][0]["main_issue"], "gaze_side")
        self.assertEqual(result["segments"][1]["focus_ratio"], 0.5)
        self.assertEqual(result["segments"][1]["risk_level"], "risk")
        self.assertEqual(result["segments"][1]["main_issue"], "bad_posture")
        self.assertEqual(result["best_segment"]["start_sec"], 0)
        self.assertEqual(result["worst_segment"]["start_sec"], 300)
        self.assertIn("5~10분", result["insights"][0])

    def test_empty_timeline_is_safe(self) -> None:
        result = build_time_patterns([], interval_sec=300, duration_sec=600)

        self.assertEqual(result["segments"], [])
        self.assertIsNone(result["best_segment"])
        self.assertIsNone(result["worst_segment"])
        self.assertEqual(result["insights"], ["시간대별 분석을 수행할 수 없습니다."])

    def test_hybrid_decision_priority(self) -> None:
        self.assertEqual(
            _decide_hybrid_state("absent", "focus", 0.99, 0.65),
            ("absent", "rule_absent"),
        )
        self.assertEqual(
            _decide_hybrid_state("bad_posture", "focus", 0.99, 0.65),
            ("bad_posture", "rule_bad_posture"),
        )
        self.assertEqual(
            _decide_hybrid_state("focus", "bad_posture", 0.99, 0.65),
            ("focus", "rule"),
        )
        self.assertEqual(
            _decide_hybrid_state("focus", "gaze_side", 0.8, 0.65),
            ("gaze_side", "model"),
        )
        self.assertEqual(
            _decide_hybrid_state("gaze_down", "focus", 0.3, 0.65),
            ("gaze_down", "rule"),
        )

    def test_model_prediction_excludes_rule_only_states(self) -> None:
        with patch(
            "focus_ai.analyze.predict_state_proba",
            return_value={"bad_posture": 0.9, "gaze_side": 0.7, "absent": 0.8},
        ):
            state, confidence = _predict_model_state(
                object(),
                {},
                [],
                excluded_states={"absent", "bad_posture"},
            )

        self.assertEqual(state, "gaze_side")
        self.assertEqual(confidence, 0.7)

    def test_create_events_from_final_states(self) -> None:
        states = [
            "focus",
            "focus",
            "gaze_side",
            "gaze_side",
            "gaze_side",
            "focus",
            "bad_posture",
            "bad_posture",
            "drowsy",
            "focus",
        ]

        events = _create_events_from_states(states)

        self.assertEqual(
            events,
            [
                {"type": "gaze_side", "start_sec": 2, "end_sec": 5, "score": 0.7},
                {"type": "bad_posture", "start_sec": 6, "end_sec": 8, "score": 0.3},
                {"type": "drowsy", "start_sec": 8, "end_sec": 9, "score": 0.9},
            ],
        )

    def test_missing_face_with_overhead_activity_becomes_unknown(self) -> None:
        front_timeline = {
            10: {"t": 10, "state": "absent", "flags": {"absent": True}},
        }
        overhead_item = {
            "t": 10,
            "state": "absent",
            "flags": {"hand_seen": True, "hand_path_len": 0.05},
        }

        self.assertEqual(
            classify_missing_face_state(10, front_timeline, overhead_item, True),
            "unknown",
        )

    def test_static_overhead_trace_with_recent_drowsy_becomes_sleep_suspect(self) -> None:
        front_timeline = {
            8: {"t": 8, "state": "focus", "flags": {"head_down": True}},
            10: {"t": 10, "state": "absent", "flags": {"absent": True}},
        }
        overhead_item = {
            "t": 10,
            "state": "absent",
            "flags": {"pose_seen": True, "hand_seen": True, "hand_path_len": 0.0},
        }

        resolved = resolve_front_absence_with_overhead(
            10,
            front_timeline[10],
            overhead_item,
            front_timeline,
            True,
        )

        self.assertEqual(resolved["missing_face_state"], "sleep_suspect")
        self.assertEqual(resolved["state"], "drowsy")
        self.assertTrue(resolved["sleep_suspect"])

    def test_missing_face_without_overhead_trace_stays_absent(self) -> None:
        front_timeline = {
            10: {"t": 10, "state": "absent", "flags": {"absent": True}},
        }
        overhead_item = {
            "t": 10,
            "state": "absent",
            "flags": {},
        }

        self.assertEqual(
            classify_missing_face_state(10, front_timeline, overhead_item, True),
            "absent",
        )


if __name__ == "__main__":
    unittest.main()
