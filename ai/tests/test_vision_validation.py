from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

from ai.focus_ai.vision.correction import apply_vision_corrections
from ai.focus_ai.vision.cost_estimator import estimate_vision_cost
from ai.focus_ai.vision.frame_sampler import SampledFrame, select_sample_times
from ai.focus_ai.vision.openai_vision_client import (
    VisionNetworkError,
    VisionRateLimitError,
    VisionTimeoutError,
    build_responses_payload,
    validate_frames,
)
from ai.focus_ai.vision.validator import VisionConfig, merge_vision_validations, validate_analysis_with_vision


def _analysis(duration: int = 100) -> dict:
    return {
        "session_id": "VISION_TEST",
        "status": "success",
        "meta": {"duration_sec": duration},
        "summary": {
            "focus_score": 98,
            "focus_total_sec": duration - 2,
            "absent_total_sec": 2,
            "absent_count": 1,
        },
        "timeline": [
            {"t": t, "state": "absent" if 40 <= t < 42 else "focus", "states": ["absent" if 40 <= t < 42 else "focus"]}
            for t in range(duration)
        ],
        "events": [{"type": "absent", "start_sec": 40, "end_sec": 42}],
    }


class CostEstimatorTest(unittest.TestCase):
    def test_gpt_4o_mini_matches_official_low_detail_image_tokens(self) -> None:
        estimate = estimate_vision_cost(
            model="gpt-4o-mini",
            detail="low",
            frame_count=20,
            max_output_tokens=800,
        )
        self.assertEqual(estimate["estimated_input_tokens"], 56660)
        self.assertAlmostEqual(estimate["estimated_cost_usd"], 0.008979, places=6)

    def test_default_nano_estimates_recommended_and_dense_modes(self) -> None:
        recommended = estimate_vision_cost(
            model="gpt-5.4-nano", detail="low", frame_count=20, max_output_tokens=800
        )
        dense = estimate_vision_cost(
            model="gpt-5.4-nano", detail="low", frame_count=60, max_output_tokens=800
        )
        self.assertEqual(recommended["estimated_input_tokens"], 12600)
        self.assertAlmostEqual(recommended["estimated_cost_usd"], 0.00352, places=6)
        self.assertAlmostEqual(dense["estimated_cost_usd"], 0.00856, places=6)


class FrameSamplingTest(unittest.TestCase):
    def test_problem_interval_is_prioritized_but_session_coverage_is_kept(self) -> None:
        result = _analysis(100)
        times = select_sample_times(result, 20)
        self.assertEqual(len(times), 20)
        self.assertTrue(any(40 <= point <= 42 for point in times))
        self.assertTrue(any(point < 20 for point in times))
        self.assertTrue(any(point > 80 for point in times))


class ResponsesPayloadTest(unittest.TestCase):
    def test_payload_uses_responses_input_image_and_low_detail(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            image = Path(temp_dir) / "frame.jpg"
            image.write_bytes(b"jpeg bytes")
            frame = SampledFrame(1, 40.0, "absent", image, 512, 512)
            payload = build_responses_payload(
                model="gpt-5.4-nano",
                detail="low",
                max_output_tokens=800,
                analysis_result=_analysis(),
                frames=[frame],
            )
        images = [item for item in payload["input"][0]["content"] if item["type"] == "input_image"]
        self.assertEqual(len(images), 1)
        self.assertEqual(images[0]["detail"], "low")
        self.assertTrue(images[0]["image_url"].startswith("data:image/jpeg;base64,"))
        self.assertEqual(payload["text"]["format"]["type"], "json_schema")

    def _call_with_error(self, error) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            image = Path(temp_dir) / "frame.jpg"
            image.write_bytes(b"jpeg bytes")
            frame = SampledFrame(1, 40.0, "absent", image, 512, 512)
            with patch("ai.focus_ai.vision.openai_vision_client.requests.post", side_effect=error):
                validate_frames(
                    api_key="test-key",
                    model="gpt-5.4-nano",
                    detail="low",
                    max_output_tokens=800,
                    timeout_sec=1,
                    analysis_result=_analysis(),
                    frames=[frame],
                )

    def test_timeout_is_classified(self) -> None:
        with self.assertRaises(VisionTimeoutError):
            self._call_with_error(requests.Timeout("timeout"))

    def test_network_failure_is_classified(self) -> None:
        with self.assertRaises(VisionNetworkError):
            self._call_with_error(requests.ConnectionError("offline"))

    def test_rate_limit_is_classified(self) -> None:
        class Response:
            status_code = 429
            text = "rate limited"

            @staticmethod
            def json():
                return {"error": {"message": "rate limited"}}

        with tempfile.TemporaryDirectory() as temp_dir:
            image = Path(temp_dir) / "frame.jpg"
            image.write_bytes(b"jpeg bytes")
            frame = SampledFrame(1, 40.0, "absent", image, 512, 512)
            with patch("ai.focus_ai.vision.openai_vision_client.requests.post", return_value=Response()):
                with self.assertRaises(VisionRateLimitError):
                    validate_frames(
                        api_key="test-key",
                        model="gpt-5.4-nano",
                        detail="low",
                        max_output_tokens=800,
                        timeout_sec=1,
                        analysis_result=_analysis(),
                        frames=[frame],
                    )


class ValidatorSafetyTest(unittest.TestCase):
    def _frames(self, directory: str) -> list[SampledFrame]:
        path = Path(directory) / "sample.jpg"
        path.write_bytes(b"frame")
        return [SampledFrame(1, 40.0, "absent", path, 512, 512)]

    def test_disabled_mode_never_extracts_or_calls_api(self) -> None:
        with patch("ai.focus_ai.vision.validator.extract_frames") as extract:
            result = validate_analysis_with_vision("missing.mp4", _analysis(), config=VisionConfig())
        extract.assert_not_called()
        self.assertEqual(result["vision_validation"]["status"], "disabled")
        self.assertEqual(result["vision_validation"]["estimated_cost_usd"], 0.0)

    def test_dry_run_estimates_without_api_call(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            frames = self._frames(temp_dir)
            config = VisionConfig(enabled=True, dry_run=True, api_key="must-not-be-used")
            with patch("ai.focus_ai.vision.validator.extract_frames", return_value=frames):
                with patch("ai.focus_ai.vision.validator.validate_frames") as api_call:
                    result = validate_analysis_with_vision("video.mp4", _analysis(), config=config)
        api_call.assert_not_called()
        self.assertEqual(result["vision_validation"]["status"], "dry_run")
        self.assertGreater(result["vision_validation"]["estimated_cost_usd"], 0)

    def test_missing_key_automatically_switches_to_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            frames = self._frames(temp_dir)
            config = VisionConfig(enabled=True, dry_run=False, api_key="")
            with patch("ai.focus_ai.vision.validator.extract_frames", return_value=frames):
                with patch("ai.focus_ai.vision.validator.validate_frames") as api_call:
                    result = validate_analysis_with_vision("video.mp4", _analysis(), config=config)
        api_call.assert_not_called()
        validation = result["vision_validation"]
        self.assertEqual(validation["status"], "dry_run_missing_api_key")
        self.assertEqual(validation["error"]["type"], "missing_api_key")

    def test_sampling_failure_keeps_rule_result_successful(self) -> None:
        result = _analysis()
        with patch("ai.focus_ai.vision.validator.extract_frames", side_effect=RuntimeError("decode failed")):
            validate_analysis_with_vision(
                "video.mp4",
                result,
                config=VisionConfig(enabled=True, dry_run=True),
            )
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["vision_validation"]["status"], "error")


class CorrectionAndMergeTest(unittest.TestCase):
    def test_correction_changes_score_only_when_explicitly_applied(self) -> None:
        result = _analysis(100)
        vision = {
            "confidence": 0.9,
            "corrections": [
                {
                    "time_sec": 40,
                    "original_state": "absent",
                    "vision_state": "present_head_down",
                    "reason": "present",
                    "confidence": 0.9,
                }
            ],
        }
        applied = apply_vision_corrections(result, vision)
        self.assertEqual(applied["applied_count"], 1)
        self.assertEqual(result["timeline"][40]["state"], "bad_posture")
        self.assertNotEqual(applied["score_before"], applied["score_after"])

    def test_chunk_merge_offsets_corrections_and_sums_estimates(self) -> None:
        merged = merge_vision_validations(
            [
                (1, 0.0, {"vision_enabled": True, "status": "completed", "model": "gpt-5.4-nano", "detail": "low", "sampled_frame_count": 20, "estimated_input_tokens": 12600, "estimated_output_tokens": 800, "estimated_cost_usd": 0.00352, "overall_verdict": "rule_result_valid", "confidence": 0.9, "corrections": []}),
                (2, 600.0, {"vision_enabled": True, "status": "completed", "model": "gpt-5.4-nano", "detail": "low", "sampled_frame_count": 20, "estimated_input_tokens": 12600, "estimated_output_tokens": 800, "estimated_cost_usd": 0.00352, "overall_verdict": "rule_result_needs_correction", "confidence": 0.8, "corrections": [{"time_sec": 10, "original_state": "absent", "vision_state": "present_head_down", "reason": "present", "confidence": 0.8}]}),
            ]
        )
        self.assertEqual(merged["sampled_frame_count"], 40)
        self.assertAlmostEqual(merged["estimated_cost_usd"], 0.00704)
        self.assertEqual(merged["corrections"][0]["time_sec"], 610.0)


if __name__ == "__main__":
    unittest.main()
