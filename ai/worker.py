from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import sys
import time
from pathlib import Path, PurePosixPath
from typing import Any

import boto3
import requests
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
AI_DIR = PROJECT_ROOT / "ai"

LOGGER = logging.getLogger("ai.worker")

DEFAULT_AWS_REGION = "ap-northeast-2"
DEFAULT_DOWNLOAD_DIR = "/tmp/videos"
DEFAULT_CHUNK_RESULT_DIR = "ai/tmp"
DEFAULT_RECEIVE_WAIT_SECONDS = 20
DEFAULT_VISIBILITY_TIMEOUT_SECONDS = 900
DEFAULT_POST_TIMEOUT_SECONDS = 30
DEFAULT_RESULT_SINK = "rds"
DEFAULT_ANALYSIS_RESULT_TABLE = "analysis_summary"
DEFAULT_ANALYSIS_FEEDBACK_TABLE = "analysis_feedback"
FEEDBACK_VALIDATOR_VERSION = "feedback-validator-v1"

VALID_CAMERA_TYPES = {"front", "overhead", "merged"}
VALID_ANALYSIS_MODES = {"absent", "dummy", "focus_analysis"}
VALID_RESULT_SINKS = {"rds", "post"}

PLACEHOLDER_VALUES = {
    "키",
    "주소",
    "버킷명",
    "DB주소",
    "아이디",
    "비밀번호",
    "DB이름",
    "your-access-key-id",
    "your-secret-access-key",
    "your-sqs-queue-url",
    "your-rds-endpoint.amazonaws.com",
    "your-db-user",
    "your-db-password",
    "your-db-name",
}


class MessageValidationError(RuntimeError):
    pass


class AnalysisFailedError(RuntimeError):
    pass


def _configure_logging() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s [%(levelname)s] %(message)s",
    )


def _load_env() -> None:
    load_dotenv(PROJECT_ROOT / ".env")


def _required_env(name: str, *, reject_placeholder: bool = False) -> str:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        raise RuntimeError(f"missing required environment variable: {name}")

    value = value.strip()
    if reject_placeholder and value in PLACEHOLDER_VALUES:
        raise RuntimeError(f"environment variable {name} still has a placeholder value: {value}")

    return value


def _env_int(name: str, default_value: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None or raw_value.strip() == "":
        return default_value

    try:
        return int(raw_value)
    except ValueError:
        LOGGER.warning("invalid integer env %s=%r; using %s", name, raw_value, default_value)
        return default_value


def _resolve_path_env(name: str, default_value: str) -> Path:
    raw_value = os.getenv(name, default_value).strip() or default_value
    path = Path(raw_value).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    path.mkdir(parents=True, exist_ok=True)
    return path


def _resolve_download_dir() -> Path:
    return _resolve_path_env("S3_DOWNLOAD_DIR", DEFAULT_DOWNLOAD_DIR)


def _resolve_chunk_result_dir() -> Path:
    return _resolve_path_env("AI_CHUNK_RESULT_DIR", DEFAULT_CHUNK_RESULT_DIR)


def _safe_filename(value: Any) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value).strip())
    return safe.strip("._-") or "unknown"


def _json_loads_object(raw_body: str) -> dict[str, Any]:
    try:
        body = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise MessageValidationError(f"message Body is not valid JSON: {exc}") from exc

    if not isinstance(body, dict):
        raise MessageValidationError("message Body JSON must be an object")

    # Also tolerate SNS-wrapped JSON messages if the queue is subscribed to SNS.
    wrapped_message = body.get("Message")
    if isinstance(wrapped_message, str) and wrapped_message.strip().startswith("{"):
        try:
            unwrapped = json.loads(wrapped_message)
        except json.JSONDecodeError:
            return body
        if isinstance(unwrapped, dict):
            return unwrapped

    return body


def _parse_bool(value: Any, field_name: str) -> bool:
    if isinstance(value, bool):
        return value

    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered == "true":
            return True
        if lowered == "false":
            return False

    raise MessageValidationError(f"{field_name} must be a boolean")


def _parse_chunk_index(value: Any) -> int:
    if isinstance(value, bool):
        raise MessageValidationError("chunk_index must be an integer")

    try:
        chunk_index = int(value)
    except (TypeError, ValueError) as exc:
        raise MessageValidationError("chunk_index must be an integer") from exc

    if chunk_index < 0:
        raise MessageValidationError("chunk_index must be greater than or equal to 0")

    return chunk_index


def _parse_message_body(message: dict[str, Any]) -> dict[str, Any]:
    raw_body = message.get("Body")
    if not isinstance(raw_body, str) or raw_body.strip() == "":
        raise MessageValidationError("message Body is empty")

    body = _json_loads_object(raw_body)

    required_values = {
        "session_id": body.get("session_id"),
        "user_id": body.get("user_id"),
        "s3_bucket": body.get("s3_bucket"),
        "s3_key": body.get("s3_key"),
        "camera_type": body.get("camera_type"),
        "mode": body.get("mode"),
        "chunk_index": body.get("chunk_index"),
        "is_final_chunk": body.get("is_final_chunk"),
    }
    missing_fields = [
        field
        for field, value in required_values.items()
        if value is None or (isinstance(value, str) and value.strip() == "")
    ]
    if missing_fields:
        raise MessageValidationError(
            f"missing required field(s): {', '.join(missing_fields)}"
        )

    camera_type = str(required_values["camera_type"]).strip().lower()
    if camera_type not in VALID_CAMERA_TYPES:
        raise MessageValidationError(
            f"camera_type must be one of {sorted(VALID_CAMERA_TYPES)}"
        )

    mode = str(required_values["mode"]).strip().lower()
    if mode not in VALID_ANALYSIS_MODES:
        raise MessageValidationError(f"mode must be one of {sorted(VALID_ANALYSIS_MODES)}")

    return {
        "session_id": str(required_values["session_id"]).strip(),
        "user_id": str(required_values["user_id"]).strip(),
        "s3_bucket": str(required_values["s3_bucket"]).strip(),
        "s3_key": str(required_values["s3_key"]).strip(),
        "camera_type": camera_type,
        "mode": mode,
        "chunk_index": _parse_chunk_index(required_values["chunk_index"]),
        "is_final_chunk": _parse_bool(required_values["is_final_chunk"], "is_final_chunk"),
    }


def _download_from_s3(s3_client: Any, job: dict[str, Any]) -> Path:
    download_dir = _resolve_download_dir()
    s3_key = str(job["s3_key"])
    suffix = PurePosixPath(s3_key).suffix or ".mp4"
    digest = hashlib.sha1(s3_key.encode("utf-8")).hexdigest()[:12]
    filename = (
        f"{_safe_filename(job['session_id'])}_"
        f"{_safe_filename(job['user_id'])}_"
        f"chunk_{job['chunk_index']}_"
        f"{digest}{suffix}"
    )
    download_path = download_dir / filename

    LOGGER.info(
        "downloading video: s3://%s/%s -> %s",
        job["s3_bucket"],
        s3_key,
        download_path,
    )
    s3_client.download_file(job["s3_bucket"], s3_key, str(download_path))
    LOGGER.info("video downloaded: %s", download_path)
    return download_path


def _ensure_ai_import_path() -> None:
    ai_dir = str(AI_DIR)
    if ai_dir not in sys.path:
        sys.path.insert(0, ai_dir)


def _run_existing_analysis(job: dict[str, Any], video_path: Path) -> dict[str, Any]:
    _ensure_ai_import_path()
    from run_local import DEFAULT_CONFIG_PATH, run_analysis

    LOGGER.info(
        "analysis started: session_id=%s, chunk_index=%s, camera_type=%s, mode=%s",
        job["session_id"],
        job["chunk_index"],
        job["camera_type"],
        job["mode"],
    )
    started_at = time.time()
    analysis_mode = "absent" if job["mode"] == "focus_analysis" else job["mode"]
    result = run_analysis(
        session_id=job["session_id"],
        video_path=video_path,
        camera_type=job["camera_type"],
        mode=analysis_mode,
        config_path=DEFAULT_CONFIG_PATH,
    )
    from codex_review import prepare_chunk_review, review_enabled

    if review_enabled():
        result = prepare_chunk_review(job, video_path, result)
    elapsed_sec = int(time.time() - started_at)
    LOGGER.info(
        "analysis finished: session_id=%s, chunk_index=%s, status=%s, elapsed_sec=%s",
        job["session_id"],
        job["chunk_index"],
        result.get("status") if isinstance(result, dict) else None,
        elapsed_sec,
    )
    return result


def _ensure_successful_analysis(analysis_result: dict[str, Any]) -> None:
    if not isinstance(analysis_result, dict):
        raise AnalysisFailedError("analysis did not return a JSON object")

    status = str(analysis_result.get("status") or "").lower()
    if status not in {"success", "completed"}:
        meta = analysis_result.get("meta") if isinstance(analysis_result.get("meta"), dict) else {}
        fail_reason = meta.get("fail_reason") or analysis_result.get("fail_reason") or status or "unknown"
        raise AnalysisFailedError(f"analysis failed: {fail_reason}")


def _as_number(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number != number or number in (float("inf"), float("-inf")):
        return default
    return number


def _as_int(value: Any, default: int = 0) -> int:
    return int(round(max(0.0, _as_number(value, float(default)))))


def _summary_number(summary: dict[str, Any], *keys: str) -> float:
    for key in keys:
        if key in summary and summary[key] is not None:
            return max(0.0, _as_number(summary[key]))
    return 0.0


def _normalized_scoring_summary(summary: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(summary or {})

    if "gaze_away_total_sec" not in normalized and "gaze_away_time_sec" not in normalized:
        normalized["gaze_away_total_sec"] = _summary_number(
            normalized,
            "away_total_sec",
            "gaze_side_total_sec",
        ) + _summary_number(normalized, "gaze_down_total_sec", "gaze_down_time_sec")

    if "gaze_away_count" not in normalized:
        normalized["gaze_away_count"] = _summary_number(
            normalized,
            "away_count",
            "gaze_side_count",
        ) + _summary_number(normalized, "gaze_down_count")

    if "focus_time_sec" not in normalized and "focus_total_sec" in normalized:
        normalized["focus_time_sec"] = normalized["focus_total_sec"]

    return normalized


def _infer_total_time(summary: dict[str, Any], meta: dict[str, Any]) -> float:
    total_time = _summary_number(meta, "duration_sec", "total_time", "total_time_sec")
    if total_time > 0:
        return total_time

    total_time = _summary_number(summary, "total_time_sec", "total_time", "duration_sec")
    if total_time > 0:
        return total_time

    return (
        _summary_number(summary, "focus_time_sec", "focus_total_sec")
        + _summary_number(summary, "bad_posture_total_sec", "bad_posture_time_sec")
        + _summary_number(summary, "gaze_away_total_sec", "gaze_away_time_sec")
        + _summary_number(summary, "drowsy_total_sec", "drowsy_time_sec")
        + _summary_number(summary, "absent_total_sec", "absence_time_sec")
    )


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, float) and (
        value != value or value in (float("inf"), float("-inf"))
    ):
        return None
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    return value


def _session_chunk_dir(session_id: Any) -> Path:
    return _resolve_chunk_result_dir() / f"session_{_safe_filename(session_id)}"


def _chunk_result_path(job: dict[str, Any]) -> Path:
    return _session_chunk_dir(job["session_id"]) / f"chunk_{job['chunk_index']}_result.json"


def _save_chunk_result(job: dict[str, Any], analysis_result: dict[str, Any]) -> Path:
    chunk_dir = _session_chunk_dir(job["session_id"])
    chunk_dir.mkdir(parents=True, exist_ok=True)
    output_path = _chunk_result_path(job)
    envelope = {
        "session_id": job["session_id"],
        "user_id": job["user_id"],
        "s3_bucket": job["s3_bucket"],
        "s3_key": job["s3_key"],
        "camera_type": job["camera_type"],
        "mode": job["mode"],
        "chunk_index": job["chunk_index"],
        "is_final_chunk": job["is_final_chunk"],
        "saved_at_unix": int(time.time()),
        "analysis_result": _json_safe(analysis_result),
    }
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(envelope, f, ensure_ascii=False, indent=2)
    LOGGER.info("chunk result saved: %s", output_path)
    return output_path


def _read_json_file(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise AnalysisFailedError(f"chunk result file must contain a JSON object: {path}")
    return data


def _load_session_chunk_results(
    session_id: Any,
    final_chunk_index: int | None = None,
) -> list[dict[str, Any]]:
    chunk_dir = _session_chunk_dir(session_id)
    if not chunk_dir.exists():
        raise AnalysisFailedError(f"chunk result directory does not exist: {chunk_dir}")

    chunks: list[dict[str, Any]] = []
    for path in chunk_dir.glob("chunk_*_result.json"):
        data = _read_json_file(path)
        try:
            chunk_index = _parse_chunk_index(data.get("chunk_index"))
        except MessageValidationError as exc:
            raise AnalysisFailedError(f"invalid chunk_index in {path}: {exc}") from exc

        analysis_result = data.get("analysis_result")
        if not isinstance(analysis_result, dict):
            analysis_result = data

        _ensure_successful_analysis(analysis_result)
        chunks.append(
            {
                "path": path,
                "chunk_index": chunk_index,
                "session_id": data.get("session_id", session_id),
                "user_id": data.get("user_id"),
                "camera_type": data.get("camera_type"),
                "mode": data.get("mode"),
                "analysis_result": analysis_result,
            }
        )

    if not chunks:
        raise AnalysisFailedError(f"no chunk result files found for session_id={session_id}")

    chunks.sort(key=lambda item: item["chunk_index"])
    if final_chunk_index is not None:
        _validate_chunk_sequence(chunks, final_chunk_index)

    return chunks


def _validate_chunk_sequence(chunks: list[dict[str, Any]], final_chunk_index: int) -> None:
    indexes = [int(chunk["chunk_index"]) for chunk in chunks]
    if final_chunk_index not in indexes:
        raise AnalysisFailedError(f"final chunk result is missing: chunk_index={final_chunk_index}")

    start_index = 0 if 0 in indexes else 1
    expected = list(range(start_index, final_chunk_index + 1))
    missing = sorted(set(expected) - set(indexes))
    if missing:
        raise AnalysisFailedError(f"missing chunk result file(s): {missing}")


def _chunk_duration_sec(analysis_result: dict[str, Any]) -> float:
    meta = analysis_result.get("meta") if isinstance(analysis_result.get("meta"), dict) else {}
    summary = analysis_result.get("summary") if isinstance(analysis_result.get("summary"), dict) else {}
    duration = _infer_total_time(summary, meta)
    if duration > 0:
        return duration

    timeline = analysis_result.get("timeline")
    if isinstance(timeline, list) and timeline:
        max_time = 0.0
        for row in timeline:
            if not isinstance(row, dict):
                continue
            if "t" in row:
                max_time = max(max_time, _as_number(row.get("t")))
            elif "time" in row:
                max_time = max(max_time, _as_number(row.get("time")))
        return max_time + 1

    return 0.0


def _should_sum_summary_key(key: str) -> bool:
    if key in {
        "focus_ratio",
        "bad_posture_ratio",
        "concentration_score",
        "focus_score",
        "weighted_base_score",
        "event_penalty",
    }:
        return False

    return (
        key in {"total_time", "total_time_sec", "duration_sec"}
        or key.endswith("_count")
        or key.endswith("_total_sec")
        or key.endswith("_time_sec")
        or key.endswith("_time")
    )


def _merge_summary(chunks: list[dict[str, Any]], total_time: float) -> dict[str, Any]:
    merged: dict[str, Any] = {}

    for chunk in chunks:
        result = chunk["analysis_result"]
        summary = result.get("summary")
        if not isinstance(summary, dict):
            continue

        for key, value in summary.items():
            if _should_sum_summary_key(str(key)):
                merged[str(key)] = _as_number(merged.get(str(key))) + _as_number(value)
            elif str(key) not in merged and str(key) not in {"warnings"}:
                merged[str(key)] = _json_safe(value)

    merged["total_time"] = int(round(total_time))
    merged["total_time_sec"] = int(round(total_time))
    merged["duration_sec"] = int(round(total_time))

    if "focus_total_sec" in merged:
        merged["focus_time_sec"] = int(round(_as_number(merged["focus_total_sec"])))
    elif "focus_time" in merged:
        merged["focus_time_sec"] = int(round(_as_number(merged["focus_time"])))

    scoring_summary = _normalized_scoring_summary(merged)
    _ensure_ai_import_path()
    from analyzer.focus_score import calculate_focus_score

    scored_summary = calculate_focus_score(scoring_summary, total_time)
    merged.update(scored_summary)

    if total_time > 0:
        bad_posture_time = _summary_number(merged, "bad_posture_total_sec", "bad_posture_time_sec")
        merged["bad_posture_ratio"] = round(bad_posture_time / total_time, 4)
        merged["focus_ratio"] = round(_summary_number(merged, "focus_total_sec", "focus_time_sec") / total_time, 4)
    else:
        merged["bad_posture_ratio"] = 0.0
        merged["focus_ratio"] = 0.0

    merged["focus_score"] = _as_int(merged.get("focus_score"))
    merged["concentration_score"] = float(merged["focus_score"])
    return _json_safe(merged)


def _offset_timeline(
    timeline: Any,
    offset_sec: float,
) -> list[dict[str, Any]]:
    if not isinstance(timeline, list):
        return []

    adjusted: list[dict[str, Any]] = []
    for item in timeline:
        if not isinstance(item, dict):
            continue
        row = _json_safe(item)
        if "t" in row:
            row["t"] = _as_number(row.get("t")) + offset_sec
        if "time" in row:
            row["time"] = _as_number(row.get("time")) + offset_sec
        adjusted.append(row)
    return adjusted


def _offset_events(events: Any, offset_sec: float) -> list[dict[str, Any]]:
    if not isinstance(events, list):
        return []

    adjusted: list[dict[str, Any]] = []
    for item in events:
        if not isinstance(item, dict):
            continue
        row = _json_safe(item)
        for key in ("start_sec", "end_sec", "start_time", "end_time"):
            if key in row:
                row[key] = _as_number(row.get(key)) + offset_sec
        adjusted.append(row)
    return adjusted


def _event_name(event: dict[str, Any]) -> str:
    return str(event.get("event_type") or event.get("type") or event.get("state") or "")


def _event_start(event: dict[str, Any]) -> float:
    return _as_number(event.get("start_sec", event.get("start_time")))


def _event_end(event: dict[str, Any]) -> float:
    return _as_number(event.get("end_sec", event.get("end_time")))


def _merge_contiguous_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not events:
        return []

    sorted_events = sorted(events, key=lambda item: (_event_start(item), _event_end(item), _event_name(item)))
    merged: list[dict[str, Any]] = []
    for event in sorted_events:
        if not merged:
            merged.append(event)
            continue

        previous = merged[-1]
        if _event_name(previous) == _event_name(event) and abs(_event_end(previous) - _event_start(event)) <= 1e-6:
            if "end_sec" in previous or "end_sec" in event:
                previous["end_sec"] = _event_end(event)
            if "end_time" in previous or "end_time" in event:
                previous["end_time"] = _event_end(event)
            if "score" in previous or "score" in event:
                previous["score"] = max(_as_number(previous.get("score")), _as_number(event.get("score")))
            continue

        merged.append(event)

    return merged


def _personal_feedback_from_result(result: dict[str, Any]) -> dict[str, Any]:
    personal_feedback = result.get("personal_feedback")
    if isinstance(personal_feedback, dict):
        result.setdefault("feedback_source", "rule_based")
        result.setdefault("feedback_version", "feedback-v1")
        return personal_feedback

    try:
        _ensure_ai_import_path()
        from focus_ai.feedback_generator import generate_personal_feedback_payload

        feedback_payload = generate_personal_feedback_payload(result)
        personal_feedback = feedback_payload.get("personal_feedback")
        result["feedback_source"] = feedback_payload.get("feedback_source", "rule_based")
        result["feedback_version"] = feedback_payload.get("feedback_version", "feedback-v1")
    except Exception as exc:
        LOGGER.warning("could not build personal feedback: %s", exc)
        personal_feedback = {}
        result.setdefault("feedback_source", "fallback")
        result.setdefault("feedback_version", "feedback-v1")

    if isinstance(personal_feedback, dict):
        result["personal_feedback"] = personal_feedback
        return personal_feedback

    return {}


def _feedback_fields_changed(
    current: Any,
    canonical: dict[str, Any],
    fields: tuple[str, ...],
) -> list[str]:
    if not isinstance(current, dict):
        return list(fields)

    return [
        field
        for field in fields
        if _json_safe(current.get(field)) != _json_safe(canonical.get(field))
    ]


def _validate_and_correct_feedback(result: dict[str, Any]) -> dict[str, Any]:
    """Rebuild feedback from final evidence and correct inconsistent fields."""
    summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
    timeline = result.get("timeline") if isinstance(result.get("timeline"), list) else []
    events = result.get("events") if isinstance(result.get("events"), list) else []
    meta = result.get("meta") if isinstance(result.get("meta"), dict) else {}
    duration_sec = _int_or_none(meta.get("duration_sec"))

    _ensure_ai_import_path()
    from focus_ai.analyze import build_time_patterns
    from focus_ai.feedback_generator import (
        _rule_based_personal_feedback,
        build_feedback_evidence,
        generate_feedback,
        generate_personal_feedback_payload,
    )

    canonical_time_patterns = build_time_patterns(
        timeline=timeline,
        interval_sec=300,
        duration_sec=duration_sec,
    )
    canonical_feedback = generate_feedback(summary, canonical_time_patterns)
    canonical_evidence = build_feedback_evidence(
        summary,
        canonical_time_patterns,
        events,
        timeline,
    )

    comparison_result = dict(result)
    comparison_result["time_patterns"] = canonical_time_patterns
    comparison_result["feedback"] = canonical_feedback
    comparison_result["feedback_evidence"] = canonical_evidence
    rule_personal_feedback = _rule_based_personal_feedback(comparison_result)
    generated_payload = generate_personal_feedback_payload(comparison_result)
    generated_personal = generated_payload.get("personal_feedback")

    validated_personal = dict(rule_personal_feedback)
    generated_source = str(generated_payload.get("feedback_source") or "rule_based")
    if (
        isinstance(generated_personal, dict)
        and generated_personal.get("main_problem") == rule_personal_feedback.get("main_problem")
    ):
        for field in ("feedback", "next_action"):
            value = generated_personal.get(field)
            if isinstance(value, str) and value.strip():
                validated_personal[field] = value.strip()
    else:
        generated_source = "rule_based"

    corrected_fields: list[str] = []
    issues: list[str] = []

    if _json_safe(result.get("time_patterns")) != _json_safe(canonical_time_patterns):
        corrected_fields.append("time_patterns")
        issues.append("time_patterns_not_based_on_final_timeline")

    feedback_changes = _feedback_fields_changed(
        result.get("feedback"),
        canonical_feedback,
        ("summary_text", "weak_point", "recommendation"),
    )
    if feedback_changes:
        corrected_fields.extend(f"feedback.{field}" for field in feedback_changes)
        issues.append("feedback_text_not_aligned_with_final_summary")

    personal_changes = _feedback_fields_changed(
        result.get("personal_feedback"),
        validated_personal,
        ("main_problem", "reason", "feedback", "next_action", "worst_segments"),
    )
    if personal_changes:
        corrected_fields.extend(f"personal_feedback.{field}" for field in personal_changes)
        issues.append("personal_feedback_not_aligned_with_evidence")

    result["time_patterns"] = canonical_time_patterns
    result["feedback"] = canonical_feedback
    result["feedback_evidence"] = canonical_evidence
    result["personal_feedback"] = validated_personal
    result["feedback_source"] = f"{generated_source}_validated"
    result["feedback_version"] = "feedback-v2-validated"
    result["feedback_validation"] = {
        "status": "corrected" if corrected_fields else "valid",
        "validator_version": FEEDBACK_VALIDATOR_VERSION,
        "issues": list(dict.fromkeys(issues)),
        "corrected_fields": list(dict.fromkeys(corrected_fields)),
        "validated_at_unix": int(time.time()),
        "evidence": {
            "duration_sec": duration_sec,
            "focus_score": _number_or_none(summary.get("focus_score")),
            "main_problem": canonical_evidence.get("main_problem"),
            "worst_segment": canonical_evidence.get("worst_segment"),
        },
    }

    LOGGER.info(
        "feedback validation complete: session_id=%s, status=%s, corrected_fields=%s",
        result.get("session_id"),
        result["feedback_validation"]["status"],
        len(result["feedback_validation"]["corrected_fields"]),
    )
    return result


def _merge_chunk_results(
    chunks: list[dict[str, Any]],
    final_job: dict[str, Any],
) -> dict[str, Any]:
    merged_timeline: list[dict[str, Any]] = []
    merged_events: list[dict[str, Any]] = []
    total_time = 0.0
    processing_time = 0.0
    version = ""
    chunk_vision_validations: list[tuple[int, float, dict[str, Any]]] = []
    chunk_codex_reviews: list[tuple[int, float, dict[str, Any]]] = []

    for chunk in chunks:
        result = chunk["analysis_result"]
        meta = result.get("meta") if isinstance(result.get("meta"), dict) else {}

        vision_validation = result.get("vision_validation")
        if isinstance(vision_validation, dict):
            chunk_vision_validations.append(
                (int(chunk["chunk_index"]), total_time, vision_validation)
            )

        codex_review = result.get("codex_manual_review")
        if isinstance(codex_review, dict):
            chunk_codex_reviews.append(
                (int(chunk["chunk_index"]), total_time, codex_review)
            )

        merged_timeline.extend(_offset_timeline(result.get("timeline"), total_time))
        merged_events.extend(_offset_events(result.get("events"), total_time))

        duration = _chunk_duration_sec(result)
        total_time += duration
        processing_time += _summary_number(meta, "processing_time_sec")
        if meta.get("version"):
            version = str(meta.get("version"))

    summary = _merge_summary(chunks, total_time)
    result = {
        "session_id": final_job["session_id"],
        "user_id": final_job["user_id"],
        "status": "success",
        "summary": summary,
        "timeline": merged_timeline,
        "events": _merge_contiguous_events(merged_events),
        "meta": {
            "duration_sec": int(round(total_time)),
            "processing_time_sec": int(round(processing_time)),
            "camera_type": final_job["camera_type"],
            "mode": final_job["mode"],
            "chunk_count": len(chunks),
            "chunk_indexes": [chunk["chunk_index"] for chunk in chunks],
            "version": version,
        },
    }
    _ensure_ai_import_path()
    from focus_ai.vision.validator import merge_vision_validations

    result["vision_validation"] = merge_vision_validations(chunk_vision_validations)
    if chunk_codex_reviews:
        from codex_review import merge_chunk_reviews

        result["codex_manual_review"] = merge_chunk_reviews(chunk_codex_reviews)
    LOGGER.info(
        "chunk results merged: session_id=%s, chunks=%s, duration_sec=%s",
        final_job["session_id"],
        len(chunks),
        result["meta"]["duration_sec"],
    )
    return result


def _build_backend_result_payload(
    analysis_result: dict[str, Any],
    job: dict[str, Any],
) -> dict[str, Any]:
    _ensure_successful_analysis(analysis_result)

    meta = analysis_result.get("meta")
    if not isinstance(meta, dict):
        meta = {}

    raw_summary = analysis_result.get("summary")
    if not isinstance(raw_summary, dict):
        raw_summary = {}

    scoring_summary = _normalized_scoring_summary(raw_summary)
    total_time = _infer_total_time(scoring_summary, meta)

    _ensure_ai_import_path()
    from analyzer.focus_score import calculate_focus_score

    scored_summary = calculate_focus_score(scoring_summary, total_time)

    payload = {
        "session_id": job["session_id"],
        "user_id": job["user_id"],
        "status": "completed",
        "focus_score": _as_int(scored_summary.get("focus_score")),
        "summary": {
            "total_time": _as_int(total_time),
            "focus_time": _as_int(scored_summary.get("focus_time_sec")),
            "bad_posture_time": _as_int(scored_summary.get("bad_posture_total_sec")),
            "gaze_away_time": _as_int(scored_summary.get("gaze_away_total_sec")),
            "drowsy_time": _as_int(scored_summary.get("drowsy_total_sec")),
            "absence_time": _as_int(scored_summary.get("absent_total_sec")),
            "absence_count": _as_int(scored_summary.get("absent_count")),
            "bad_posture_count": _as_int(scored_summary.get("bad_posture_count")),
            "gaze_away_count": _as_int(scored_summary.get("gaze_away_count")),
            "drowsy_count": _as_int(scored_summary.get("drowsy_count")),
        },
        "timeline": _json_safe(analysis_result.get("timeline") or []),
        "events": _json_safe(analysis_result.get("events") or []),
        "feedback": _json_safe(analysis_result.get("feedback") or {}),
        "time_patterns": _json_safe(analysis_result.get("time_patterns") or {}),
        "personal_feedback": _json_safe(_personal_feedback_from_result(analysis_result)),
        "feedback_source": str(analysis_result.get("feedback_source") or "rule_based"),
        "feedback_version": str(analysis_result.get("feedback_version") or "feedback-v1"),
        "feedback_validation": _json_safe(analysis_result.get("feedback_validation") or {}),
        "vision_validation": _json_safe(analysis_result.get("vision_validation") or {}),
    }
    return payload


def _post_result(backend_url: str, payload: dict[str, Any]) -> None:
    timeout_sec = _env_int("BACKEND_POST_TIMEOUT_SECONDS", DEFAULT_POST_TIMEOUT_SECONDS)
    LOGGER.info(
        "posting result: endpoint=%s, session_id=%s, user_id=%s",
        backend_url,
        payload["session_id"],
        payload["user_id"],
    )
    response = requests.post(backend_url, json=payload, timeout=timeout_sec)
    response.raise_for_status()
    LOGGER.info(
        "result posted: session_id=%s, http_status=%s",
        payload["session_id"],
        response.status_code,
    )


def _sanitize_sql_identifier(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value or ""):
        raise RuntimeError(f"invalid SQL identifier: {value!r}")
    return value


def _analysis_result_table() -> str:
    return _sanitize_sql_identifier(
        os.getenv("ANALYSIS_RESULT_TABLE", DEFAULT_ANALYSIS_RESULT_TABLE).strip()
        or DEFAULT_ANALYSIS_RESULT_TABLE
    )


def _analysis_feedback_table() -> str:
    return _sanitize_sql_identifier(
        os.getenv("ANALYSIS_FEEDBACK_TABLE", DEFAULT_ANALYSIS_FEEDBACK_TABLE).strip()
        or DEFAULT_ANALYSIS_FEEDBACK_TABLE
    )


def _rds_connection() -> Any:
    host = _required_env("RDS_HOST", reject_placeholder=True)
    port = _env_int("RDS_PORT", 3306)
    user = _required_env("RDS_USER", reject_placeholder=True)
    password = _required_env("RDS_PASSWORD", reject_placeholder=True)
    database = _required_env("RDS_DATABASE", reject_placeholder=True)

    import pymysql

    return pymysql.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        database=database,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
    )


def _number_or_none(value: Any) -> Any:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> Any:
    if value is None:
        return None
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def _summary_value(summary: dict[str, Any], *keys: str, default: Any = 0) -> Any:
    for key in keys:
        value = summary.get(key)
        if value is not None:
            return value
    return default


def _text_or_none(value: Any) -> str | None:
    if value is None:
        return None

    text = str(value).strip()
    return text or None


def _text_list(value: Any) -> list[str]:
    if isinstance(value, list):
        texts = []
        for item in value:
            if item is None:
                continue
            text = str(item).strip()
            if text:
                texts.append(text)
        return texts

    text = _text_or_none(value)
    return [text] if text else []


def _time_patterns_from_result(result: dict[str, Any]) -> dict[str, Any]:
    time_patterns = result.get("time_patterns")
    if isinstance(time_patterns, dict):
        return time_patterns

    timeline = result.get("timeline") if isinstance(result.get("timeline"), list) else []
    meta = result.get("meta") if isinstance(result.get("meta"), dict) else {}
    duration_sec = _number_or_none(meta.get("duration_sec"))

    try:
        _ensure_ai_import_path()
        from focus_ai.analyze import build_time_patterns

        return build_time_patterns(
            timeline=timeline,
            interval_sec=300,
            duration_sec=int(duration_sec) if duration_sec is not None else None,
        )
    except Exception as exc:
        LOGGER.warning("could not build time_patterns for feedback: %s", exc)
        return {
            "interval_sec": 300,
            "segments": [],
            "best_segment": None,
            "worst_segment": None,
            "insights": [],
        }


def _feedback_from_result(result: dict[str, Any]) -> dict[str, Any]:
    feedback = result.get("feedback")
    if isinstance(feedback, dict):
        return feedback

    summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
    try:
        _ensure_ai_import_path()
        from focus_ai.feedback_generator import generate_feedback

        return generate_feedback(summary)
    except Exception as exc:
        LOGGER.warning("could not build feedback text: %s", exc)
        return {}


def _feedback_lines_from_result(result: dict[str, Any]) -> list[str]:
    feedback = _feedback_from_result(result)
    lines: list[str] = []
    for key in ("summary_text", "weak_point", "recommendation"):
        lines.extend(_text_list(feedback.get(key)))

    personal_feedback = result.get("personal_feedback")
    if isinstance(personal_feedback, dict):
        for key in ("main_problem", "reason", "feedback", "next_action"):
            lines.extend(_text_list(personal_feedback.get(key)))

        worst_segments = personal_feedback.get("worst_segments")
        if isinstance(worst_segments, list):
            for segment in worst_segments[:3]:
                if not isinstance(segment, dict):
                    continue
                start_sec = _int_or_none(segment.get("start_sec"))
                end_sec = _int_or_none(segment.get("end_sec"))
                problem = _text_or_none(segment.get("problem"))
                feedback = _text_or_none(segment.get("feedback"))
                if start_sec is not None and end_sec is not None and problem:
                    prefix = f"{start_sec}-{end_sec}초: {problem}"
                    lines.append(f"{prefix} - {feedback}" if feedback else prefix)
                elif feedback:
                    lines.append(feedback)

    time_patterns = _time_patterns_from_result(result)
    lines.extend(_text_list(time_patterns.get("insights")))
    return list(dict.fromkeys(lines))


def _feedback_row_from_result(session_id: str, result: dict[str, Any]) -> dict[str, Any]:
    personal_feedback = _personal_feedback_from_result(result)
    personal_feedback_json = None
    if personal_feedback:
        personal_feedback_json = json.dumps(_json_safe(personal_feedback), ensure_ascii=False)

    validation = result.get("feedback_validation")
    if not isinstance(validation, dict):
        validation = {}

    return {
        "session_id": session_id,
        "feedback_text": "\n".join(_feedback_lines_from_result(result)),
        "personal_feedback": personal_feedback_json,
        "feedback_source": str(result.get("feedback_source") or "rule_based"),
        "feedback_version": str(result.get("feedback_version") or "feedback-v1"),
        "validation_status": str(validation.get("status") or "not_validated"),
        "validation_details": json.dumps(_json_safe(validation), ensure_ascii=False) if validation else None,
        "validator_version": str(validation.get("validator_version") or ""),
    }


def _save_result_to_rds(result: dict[str, Any]) -> None:
    session_id = str(result.get("session_id") or "").strip()
    if not session_id:
        raise RuntimeError("final result does not contain session_id")

    summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
    meta = result.get("meta") if isinstance(result.get("meta"), dict) else {}
    timeline = result.get("timeline") if isinstance(result.get("timeline"), list) else []
    events = result.get("events") if isinstance(result.get("events"), list) else []
    summary_table = _analysis_result_table()
    feedback_table = _analysis_feedback_table()

    summary_row = {
        "session_id": session_id,
        "focus_ratio": _number_or_none(summary.get("focus_ratio")) or 0,
        "absent_count": _int_or_none(summary.get("absent_count")) or 0,
        "absent_total_sec": _number_or_none(_summary_value(summary, "absent_total_sec", "absence_time")) or 0,
        "away_count": _int_or_none(_summary_value(summary, "away_count", "gaze_away_count")) or 0,
        "away_total_sec": _number_or_none(_summary_value(summary, "away_total_sec", "gaze_away_total_sec")) or 0,
        "bad_posture_ratio": _number_or_none(summary.get("bad_posture_ratio")) or 0,
        "processing_time_sec": _number_or_none(meta.get("processing_time_sec")) or 0,
        "camera_type": str(meta.get("camera_type") or "merged"),
        "version": str(meta.get("version") or ""),
    }
    feedback_row = _feedback_row_from_result(session_id, result)

    LOGGER.info(
        "saving final result to RDS: session_id=%s, summary_table=%s, feedback_table=%s",
        session_id,
        summary_table,
        feedback_table,
    )
    conn = _rds_connection()
    try:
        with conn.cursor() as cursor:
            _ensure_analysis_tables(cursor, summary_table, feedback_table)
            _replace_analysis_rows(
                cursor,
                summary_table,
                feedback_table,
                session_id,
                summary_row,
                feedback_row,
                timeline,
                events,
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    LOGGER.info("RDS save complete: session_id=%s", session_id)


def _ensure_analysis_tables(cursor: Any, summary_table: str, feedback_table: str) -> None:
    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {summary_table} (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            session_id VARCHAR(100) NOT NULL UNIQUE,
            focus_ratio FLOAT,
            absent_count INT,
            absent_total_sec FLOAT,
            away_count INT,
            away_total_sec FLOAT,
            bad_posture_ratio FLOAT,
            processing_time_sec FLOAT,
            camera_type VARCHAR(50),
            version VARCHAR(50),
            analyzed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS analysis_events (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            session_id VARCHAR(100) NOT NULL,
            event_type VARCHAR(50),
            start_sec FLOAT,
            end_sec FLOAT,
            score FLOAT,
            INDEX idx_analysis_events_session_id (session_id)
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS analysis_timeline (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            session_id VARCHAR(100) NOT NULL,
            t FLOAT,
            state VARCHAR(50),
            INDEX idx_analysis_timeline_session_id (session_id)
        )
        """
    )
    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {feedback_table} (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            session_id VARCHAR(100) NOT NULL UNIQUE,
            feedback_text LONGTEXT NOT NULL,
            personal_feedback JSON NULL,
            feedback_source VARCHAR(30) NULL,
            feedback_version VARCHAR(30) NULL,
            validation_status VARCHAR(30) NULL,
            validation_details JSON NULL,
            validator_version VARCHAR(40) NULL,
            feedback_created_at DATETIME NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        )
        """
    )
    _ensure_feedback_table_shape(cursor, feedback_table)


def _table_columns(cursor: Any, table_name: str) -> set[str]:
    cursor.execute(f"SHOW COLUMNS FROM {table_name}")
    return {str(row["Field"] if isinstance(row, dict) else row[0]) for row in cursor.fetchall()}


def _ensure_feedback_table_shape(cursor: Any, feedback_table: str) -> None:
    columns = _table_columns(cursor, feedback_table)
    if "feedback_text" not in columns:
        cursor.execute(f"ALTER TABLE {feedback_table} ADD COLUMN feedback_text LONGTEXT NULL AFTER session_id")
        columns.add("feedback_text")

    if "personal_feedback" not in columns:
        cursor.execute(f"ALTER TABLE {feedback_table} ADD COLUMN personal_feedback JSON NULL AFTER feedback_text")
        columns.add("personal_feedback")

    if "feedback_source" not in columns:
        cursor.execute(f"ALTER TABLE {feedback_table} ADD COLUMN feedback_source VARCHAR(30) NULL AFTER personal_feedback")
        columns.add("feedback_source")

    if "feedback_version" not in columns:
        cursor.execute(f"ALTER TABLE {feedback_table} ADD COLUMN feedback_version VARCHAR(30) NULL AFTER feedback_source")
        columns.add("feedback_version")

    if "feedback_created_at" not in columns:
        cursor.execute(f"ALTER TABLE {feedback_table} ADD COLUMN feedback_created_at DATETIME NULL AFTER feedback_version")
        columns.add("feedback_created_at")

    if "validation_status" not in columns:
        cursor.execute(f"ALTER TABLE {feedback_table} ADD COLUMN validation_status VARCHAR(30) NULL AFTER feedback_version")
        columns.add("validation_status")

    if "validation_details" not in columns:
        cursor.execute(f"ALTER TABLE {feedback_table} ADD COLUMN validation_details JSON NULL AFTER validation_status")
        columns.add("validation_details")

    if "validator_version" not in columns:
        cursor.execute(f"ALTER TABLE {feedback_table} ADD COLUMN validator_version VARCHAR(40) NULL AFTER validation_details")
        columns.add("validator_version")

    for legacy_text_column in ("insights_json", "summary_text", "weak_point", "recommendation"):
        if legacy_text_column in columns:
            cursor.execute(
                f"""
                UPDATE {feedback_table}
                SET feedback_text = COALESCE(NULLIF(feedback_text, ''), {legacy_text_column}, '')
                WHERE feedback_text IS NULL OR feedback_text = ''
                """
            )

    cursor.execute(f"UPDATE {feedback_table} SET feedback_text = '' WHERE feedback_text IS NULL")
    cursor.execute(f"ALTER TABLE {feedback_table} MODIFY feedback_text LONGTEXT NOT NULL")


def _replace_analysis_rows(
    cursor: Any,
    summary_table: str,
    feedback_table: str,
    session_id: str,
    summary_row: dict[str, Any],
    feedback_row: dict[str, Any],
    timeline: list[dict[str, Any]],
    events: list[dict[str, Any]],
) -> None:
    cursor.execute("DELETE FROM analysis_timeline WHERE session_id = %s", (session_id,))
    cursor.execute("DELETE FROM analysis_events WHERE session_id = %s", (session_id,))

    cursor.execute(
        f"""
        INSERT INTO {summary_table} (
            session_id,
            focus_ratio,
            absent_count,
            absent_total_sec,
            away_count,
            away_total_sec,
            bad_posture_ratio,
            processing_time_sec,
            camera_type,
            version
        ) VALUES (
            %(session_id)s,
            %(focus_ratio)s,
            %(absent_count)s,
            %(absent_total_sec)s,
            %(away_count)s,
            %(away_total_sec)s,
            %(bad_posture_ratio)s,
            %(processing_time_sec)s,
            %(camera_type)s,
            %(version)s
        )
        ON DUPLICATE KEY UPDATE
            focus_ratio = VALUES(focus_ratio),
            absent_count = VALUES(absent_count),
            absent_total_sec = VALUES(absent_total_sec),
            away_count = VALUES(away_count),
            away_total_sec = VALUES(away_total_sec),
            bad_posture_ratio = VALUES(bad_posture_ratio),
            processing_time_sec = VALUES(processing_time_sec),
            camera_type = VALUES(camera_type),
            version = VALUES(version),
            analyzed_at = CURRENT_TIMESTAMP
        """,
        summary_row,
    )

    cursor.execute(
        f"""
        INSERT INTO {feedback_table} (
            session_id,
            feedback_text,
            personal_feedback,
            feedback_source,
            feedback_version,
            validation_status,
            validation_details,
            validator_version,
            feedback_created_at
        ) VALUES (
            %(session_id)s,
            %(feedback_text)s,
            %(personal_feedback)s,
            %(feedback_source)s,
            %(feedback_version)s,
            %(validation_status)s,
            %(validation_details)s,
            %(validator_version)s,
            CURRENT_TIMESTAMP
        )
        ON DUPLICATE KEY UPDATE
            feedback_text = VALUES(feedback_text),
            personal_feedback = VALUES(personal_feedback),
            feedback_source = VALUES(feedback_source),
            feedback_version = VALUES(feedback_version),
            validation_status = VALUES(validation_status),
            validation_details = VALUES(validation_details),
            validator_version = VALUES(validator_version),
            feedback_created_at = VALUES(feedback_created_at),
            updated_at = CURRENT_TIMESTAMP
        """,
        feedback_row,
    )

    timeline_values = []
    for row in timeline:
        t = _number_or_none(row.get("t", row.get("time"))) or 0
        for state in _timeline_states(row):
            timeline_values.append((session_id, t, state))

    if timeline_values:
        cursor.executemany(
            """
            INSERT INTO analysis_timeline (session_id, t, state)
            VALUES (%s, %s, %s)
            """,
            timeline_values,
        )

    event_values = [
        (
            session_id,
            str(row.get("event_type") or row.get("type") or row.get("state") or "unknown"),
            _number_or_none(row.get("start_sec", row.get("start_time"))) or 0,
            _number_or_none(row.get("end_sec", row.get("end_time"))) or 0,
            _number_or_none(row.get("score")) or 0,
        )
        for row in events
    ]

    if event_values:
        cursor.executemany(
            """
            INSERT INTO analysis_events (
                session_id, event_type, start_sec, end_sec, score
            ) VALUES (%s, %s, %s, %s, %s)
            """,
            event_values,
        )


def _timeline_states(row: dict[str, Any]) -> list[str]:
    states = row.get("states")
    if isinstance(states, list):
        clean_states = [str(state) for state in states if state]
        if clean_states:
            return clean_states

    state = row.get("state")
    if state:
        return [str(state)]

    flags = row.get("flags") or {}
    if isinstance(flags, dict):
        active_flags = [str(name) for name, enabled in flags.items() if enabled]
        if active_flags:
            return active_flags

    return ["unknown"]


def _result_sink() -> str:
    raw_value = os.getenv("RESULT_SINK", DEFAULT_RESULT_SINK).strip().lower() or DEFAULT_RESULT_SINK
    aliases = {
        "backend": "post",
        "http": "post",
        "api": "post",
    }
    sink = aliases.get(raw_value, raw_value)
    if sink not in VALID_RESULT_SINKS:
        raise RuntimeError(f"RESULT_SINK must be one of {sorted(VALID_RESULT_SINKS)}")
    return sink


def _store_final_result(final_result: dict[str, Any], final_job: dict[str, Any], sink: str) -> None:
    _validate_and_correct_feedback(final_result)

    from codex_review import queue_final_review, review_enabled

    if review_enabled():
        review_path = queue_final_review(final_result, final_job, sink)
        LOGGER.info(
            "final result queued for Codex review; RDS save deferred: session_id=%s, path=%s",
            final_result.get("session_id"),
            review_path,
        )
        return

    if sink == "rds":
        _save_result_to_rds(final_result)
        return

    backend_url = _required_env("BACKEND_RESULT_API_URL")
    payload = _build_backend_result_payload(final_result, final_job)
    _post_result(backend_url, payload)


def _process_message(
    s3_client: Any,
    message: dict[str, Any],
    result_sink: str,
) -> bool:
    job = _parse_message_body(message)
    LOGGER.info(
        "message parsed: session_id=%s, user_id=%s, s3_bucket=%s, s3_key=%s, chunk_index=%s, is_final_chunk=%s",
        job["session_id"],
        job["user_id"],
        job["s3_bucket"],
        job["s3_key"],
        job["chunk_index"],
        job["is_final_chunk"],
    )

    video_path = _download_from_s3(s3_client, job)
    analysis_result = _run_existing_analysis(job, video_path)
    _ensure_successful_analysis(analysis_result)
    _save_chunk_result(job, analysis_result)

    if not job["is_final_chunk"]:
        LOGGER.info(
            "non-final chunk processed; RDS save is deferred: session_id=%s, chunk_index=%s",
            job["session_id"],
            job["chunk_index"],
        )
        return True

    chunks = _load_session_chunk_results(
        session_id=job["session_id"],
        final_chunk_index=job["chunk_index"],
    )
    final_result = _merge_chunk_results(chunks, job)
    _store_final_result(final_result, job, result_sink)
    return True


def _poll_loop(
    sqs_client: Any,
    s3_client: Any,
    queue_url: str,
    result_sink: str,
    run_once: bool,
) -> None:
    wait_seconds = _env_int("SQS_WAIT_TIME_SECONDS", DEFAULT_RECEIVE_WAIT_SECONDS)
    visibility_timeout = _env_int(
        "SQS_VISIBILITY_TIMEOUT_SECONDS",
        DEFAULT_VISIBILITY_TIMEOUT_SECONDS,
    )
    LOGGER.info("worker started: queue_url=%s, result_sink=%s", queue_url, result_sink)

    while True:
        try:
            response = sqs_client.receive_message(
                QueueUrl=queue_url,
                MaxNumberOfMessages=1,
                WaitTimeSeconds=wait_seconds,
                VisibilityTimeout=visibility_timeout,
            )
        except KeyboardInterrupt:
            LOGGER.info("worker stopped by user")
            return
        except Exception as exc:
            LOGGER.exception("SQS receive failed: %s", exc)
            time.sleep(5)
            if run_once:
                return
            continue

        messages = response.get("Messages", [])
        if not messages:
            if run_once:
                LOGGER.info("no SQS message received")
                return
            continue

        for message in messages:
            receipt_handle = message.get("ReceiptHandle")
            delete_message = False

            try:
                delete_message = _process_message(
                    s3_client=s3_client,
                    message=message,
                    result_sink=result_sink,
                )
            except Exception as exc:
                LOGGER.exception(
                    "message processing failed; SQS message will not be deleted: %s",
                    exc,
                )

            if not delete_message:
                continue

            try:
                sqs_client.delete_message(
                    QueueUrl=queue_url,
                    ReceiptHandle=receipt_handle,
                )
                LOGGER.info("SQS message deleted")
            except Exception as exc:
                LOGGER.exception("SQS delete failed: %s", exc)

        if run_once:
            return


def _load_sample_message(path: Path) -> dict[str, Any]:
    data = _read_json_file(path)
    if isinstance(data.get("Body"), str):
        return data
    return {"Body": json.dumps(data, ensure_ascii=False)}


def main() -> int:
    _configure_logging()
    _load_env()

    parser = argparse.ArgumentParser(description="Poll SQS and run the AI video analyzer.")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Poll once and exit. Useful for smoke tests.",
    )
    parser.add_argument(
        "--sample-message",
        help="Process one local sample JSON message without deleting an SQS message.",
    )
    args = parser.parse_args()

    try:
        aws_region = os.getenv("AWS_REGION", DEFAULT_AWS_REGION).strip() or DEFAULT_AWS_REGION
        result_sink = _result_sink()
        s3_client = boto3.client("s3", region_name=aws_region)

        if args.sample_message:
            sample_message = _load_sample_message(Path(args.sample_message))
            success = _process_message(
                s3_client=s3_client,
                message=sample_message,
                result_sink=result_sink,
            )
            return 0 if success else 1

        queue_url = _required_env("SQS_QUEUE_URL", reject_placeholder=True)
    except RuntimeError as exc:
        LOGGER.error("%s", exc)
        return 1

    sqs_client = boto3.client("sqs", region_name=aws_region)

    _poll_loop(
        sqs_client=sqs_client,
        s3_client=s3_client,
        queue_url=queue_url,
        result_sink=result_sink,
        run_once=args.once,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
