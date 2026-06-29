from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any, Sequence

import requests

from .frame_sampler import SampledFrame


RESPONSES_API_URL = "https://api.openai.com/v1/responses"


class VisionAPIError(RuntimeError):
    error_type = "api_error"


class VisionMissingAPIKeyError(VisionAPIError):
    error_type = "missing_api_key"


class VisionTimeoutError(VisionAPIError):
    error_type = "timeout"


class VisionRateLimitError(VisionAPIError):
    error_type = "rate_limit"


class VisionNetworkError(VisionAPIError):
    error_type = "network"


VISION_RESULT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "overall_verdict": {
            "type": "string",
            "enum": [
                "rule_result_valid",
                "rule_result_mostly_valid",
                "rule_result_needs_correction",
                "insufficient_visual_evidence",
            ],
        },
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "corrections": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "time_sec": {"type": "number", "minimum": 0},
                    "original_state": {"type": "string"},
                    "vision_state": {
                        "type": "string",
                        "enum": [
                            "present_normal",
                            "present_head_down",
                            "present_occluded",
                            "present_side_view",
                            "absent",
                            "drowsy_possible",
                            "gaze_away_possible",
                            "bad_posture_possible",
                            "uncertain",
                        ],
                    },
                    "reason": {"type": "string"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": [
                    "time_sec",
                    "original_state",
                    "vision_state",
                    "reason",
                    "confidence",
                ],
            },
        },
        "notes": {"type": "string"},
    },
    "required": ["overall_verdict", "confidence", "corrections", "notes"],
}


def _compact_rule_context(analysis_result: dict[str, Any], frames: Sequence[SampledFrame]) -> dict[str, Any]:
    summary = analysis_result.get("summary") if isinstance(analysis_result.get("summary"), dict) else {}
    summary_keys = (
        "focus_score",
        "focus_ratio",
        "absent_total_sec",
        "drowsy_total_sec",
        "gaze_away_total_sec",
        "away_total_sec",
        "bad_posture_total_sec",
        "unknown_total_sec",
    )
    compact_summary = {key: summary.get(key) for key in summary_keys if key in summary}
    return {
        "summary": compact_summary,
        "sampled_frames_in_image_order": [frame.prompt_metadata() for frame in frames],
    }


def _build_prompt(analysis_result: dict[str, Any], frames: Sequence[SampledFrame]) -> str:
    context = _compact_rule_context(analysis_result, frames)
    return (
        "당신은 FocusAI 규칙 기반 학습 집중도 분석의 보조 영상 검증기입니다. "
        "첨부 이미지는 전체 영상이 아니라 시간순으로 추출한 일부 프레임입니다. "
        "프레임만으로 확실하지 않은 행동을 단정하지 마세요. 각 이미지의 순서는 "
        "sampled_frames_in_image_order와 같습니다. 사람이 실제 자리에 있는지, 얼굴 미검출이 "
        "자리이탈인지 고개 숙임·가림·측면 때문인지, 졸음·시선 이탈·자세 불량 가능성이 "
        "있는지 확인하고 기존 original_state와 명백히 충돌하는 경우에만 corrections에 넣으세요. "
        "단일 정지 프레임으로 눈 감김과 시선 방향을 확정하기 어려우면 uncertain 또는 낮은 "
        "confidence를 사용하세요. 비전 판단은 보조 검증이며 corrections가 없을 수도 있습니다.\n\n"
        f"규칙 기반 컨텍스트:\n{json.dumps(context, ensure_ascii=False, separators=(',', ':'))}"
    )


def _data_url(path: Path) -> str:
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def build_responses_payload(
    *,
    model: str,
    detail: str,
    max_output_tokens: int,
    analysis_result: dict[str, Any],
    frames: Sequence[SampledFrame],
) -> dict[str, Any]:
    content: list[dict[str, Any]] = [
        {"type": "input_text", "text": _build_prompt(analysis_result, frames)}
    ]
    content.extend(
        {
            "type": "input_image",
            "image_url": _data_url(frame.path),
            "detail": detail,
        }
        for frame in frames
    )

    payload: dict[str, Any] = {
        "model": model,
        "input": [{"role": "user", "content": content}],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "focusai_vision_validation",
                "strict": True,
                "schema": VISION_RESULT_SCHEMA,
            }
        },
        "max_output_tokens": max(1, int(max_output_tokens)),
    }
    if str(model).lower().startswith("gpt-5"):
        payload["reasoning"] = {"effort": "none"}
    return payload


def _error_message(response: Any) -> str:
    try:
        data = response.json()
    except Exception:
        return str(getattr(response, "text", "OpenAI API request failed"))[:500]
    error = data.get("error") if isinstance(data, dict) else None
    if isinstance(error, dict) and error.get("message"):
        return str(error["message"])[:500]
    return str(data)[:500]


def _output_text(response_body: dict[str, Any]) -> str:
    for output in response_body.get("output", []):
        if not isinstance(output, dict) or output.get("type") != "message":
            continue
        for item in output.get("content", []):
            if not isinstance(item, dict):
                continue
            if item.get("type") == "refusal":
                raise VisionAPIError(f"vision request refused: {item.get('refusal', '')}")
            if item.get("type") == "output_text" and isinstance(item.get("text"), str):
                return item["text"]
    raise VisionAPIError("OpenAI response did not contain output_text")


def validate_frames(
    *,
    api_key: str,
    model: str,
    detail: str,
    max_output_tokens: int,
    timeout_sec: float,
    analysis_result: dict[str, Any],
    frames: Sequence[SampledFrame],
) -> dict[str, Any]:
    if not str(api_key or "").strip():
        raise VisionMissingAPIKeyError("OPENAI_API_KEY is not configured")

    payload = build_responses_payload(
        model=model,
        detail=detail,
        max_output_tokens=max_output_tokens,
        analysis_result=analysis_result,
        frames=frames,
    )
    try:
        response = requests.post(
            RESPONSES_API_URL,
            headers={
                "Authorization": f"Bearer {api_key.strip()}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=max(1.0, float(timeout_sec)),
        )
    except requests.Timeout as exc:
        raise VisionTimeoutError("OpenAI vision request timed out") from exc
    except requests.ConnectionError as exc:
        raise VisionNetworkError("OpenAI vision network connection failed") from exc
    except requests.RequestException as exc:
        raise VisionNetworkError(f"OpenAI vision request failed: {exc}") from exc

    if response.status_code == 429:
        raise VisionRateLimitError(_error_message(response))
    if response.status_code >= 400:
        raise VisionAPIError(f"OpenAI API HTTP {response.status_code}: {_error_message(response)}")

    try:
        body = response.json()
        result = json.loads(_output_text(body))
    except json.JSONDecodeError as exc:
        raise VisionAPIError(f"OpenAI vision output was not valid JSON: {exc}") from exc
    if not isinstance(result, dict):
        raise VisionAPIError("OpenAI vision JSON output was not an object")

    usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
    result["api_response_id"] = body.get("id")
    result["actual_input_tokens"] = usage.get("input_tokens")
    result["actual_output_tokens"] = usage.get("output_tokens")
    return result
