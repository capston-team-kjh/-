from __future__ import annotations

import math
from typing import Any, Iterable


STATE_WEIGHTS = {
    "focus": 100.0,
    "bad_posture": 60.0,
    "gaze_away": 40.0,
    "unknown": 50.0,
    "present_unknown": 50.0,
    "drowsy": 20.0,
    "sleep_suspect": 20.0,
    "absent": 0.0,
}

EVENT_PENALTIES = {
    "absent": 2.0,
    "drowsy": 1.5,
    "sleep_suspect": 1.5,
    "gaze_away": 1.0,
    "bad_posture": 0.5,
}

PRIORITY_ORDER = (
    "absent",
    "drowsy",
    "sleep_suspect",
    "gaze_away",
    "bad_posture",
    "unknown",
    "present_unknown",
    "focus",
)
MAX_EVENT_PENALTY = 10.0


def _to_non_negative_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default

    try:
        number = float(value)
    except (TypeError, ValueError):
        return default

    if math.isnan(number) or math.isinf(number):
        return default

    return max(0.0, number)


def _get_number(summary: dict[str, Any], keys: Iterable[str]) -> float:
    for key in keys:
        if key in summary and summary[key] is not None:
            return _to_non_negative_float(summary[key])
    return 0.0


def _get_count(summary: dict[str, Any], keys: Iterable[str]) -> float:
    return _get_number(summary, keys)


def _get_gaze_away_time(summary: dict[str, Any]) -> float:
    explicit_time = _get_number(summary, ("gaze_away_total_sec", "gaze_away_time_sec"))
    if explicit_time > 0:
        return explicit_time

    return _get_number(
        summary,
        ("away_total_sec", "gaze_side_total_sec"),
    ) + _get_number(summary, ("gaze_down_total_sec", "gaze_down_time_sec"))


def _get_gaze_away_count(summary: dict[str, Any]) -> float:
    explicit_count = _get_count(summary, ("gaze_away_count",))
    if explicit_count > 0:
        return explicit_count

    return _get_count(
        summary,
        ("away_count", "gaze_side_count"),
    ) + _get_count(summary, ("gaze_down_count",))


def _get_sleep_suspect_time(summary: dict[str, Any]) -> float:
    sleep_suspect_time = _get_number(summary, ("sleep_suspect_total_sec",))
    drowsy_time = _get_number(summary, ("drowsy_total_sec",))

    # Merged analysis exposes sleep_suspect as a subset of drowsy for backward
    # compatibility. Avoid charging that same second twice in the scorer.
    if sleep_suspect_time > 0 and drowsy_time >= sleep_suspect_time:
        return 0.0

    return sleep_suspect_time


def _get_sleep_suspect_count(summary: dict[str, Any]) -> float:
    sleep_suspect_count = _get_count(summary, ("sleep_suspect_count",))
    drowsy_count = _get_count(summary, ("drowsy_count",))

    if sleep_suspect_count > 0 and drowsy_count >= sleep_suspect_count:
        return 0.0

    return sleep_suspect_count


def _round_seconds(value: float) -> int:
    return int(math.floor(value + 0.5))


def _round_score(value: float) -> int:
    return max(0, min(100, int(math.floor(value + 0.5))))


def _append_warning(summary: dict[str, Any], message: str) -> None:
    warnings = summary.get("warnings")
    if not isinstance(warnings, list):
        warnings = []
        summary["warnings"] = warnings

    if message not in warnings:
        warnings.append(message)


def calculate_focus_score(summary: dict, total_time_sec: float) -> dict:
    """
    상태별 시간과 이벤트 횟수를 기반으로 집중도 점수를 계산한다.

    상태별 가중치:
    - focus: 100
    - bad_posture: 60
    - gaze_away: 40
    - unknown/present_unknown: 50
    - drowsy: 20
    - sleep_suspect: 20
    - absent: 0

    이벤트 패널티:
    - absent_count * 2
    - drowsy_count * 1.5
    - gaze_away_count * 1
    - bad_posture_count * 0.5
    - 최대 10점까지만 차감
    """
    result: dict[str, Any] = dict(summary or {})
    total_time = _to_non_negative_float(total_time_sec)

    raw_times = {
        "focus": _get_number(result, ("focus_time_sec", "focus_total_sec")),
        "bad_posture": _get_number(result, ("bad_posture_total_sec",)),
        "gaze_away": _get_gaze_away_time(result),
        "unknown": _get_number(result, ("unknown_total_sec",)),
        "present_unknown": _get_number(result, ("present_unknown_total_sec",)),
        "drowsy": _get_number(result, ("drowsy_total_sec",)),
        "sleep_suspect": _get_sleep_suspect_time(result),
        "absent": _get_number(result, ("absent_total_sec",)),
    }

    counts = {
        "bad_posture": _get_count(result, ("bad_posture_count",)),
        "gaze_away": _get_gaze_away_count(result),
        "drowsy": _get_count(result, ("drowsy_count",)),
        "sleep_suspect": _get_sleep_suspect_count(result),
        "absent": _get_count(result, ("absent_count",)),
    }

    if total_time <= 0:
        _append_warning(result, "total_time_sec is missing or zero; focus_score set to 0.")
        result.setdefault("focus_ratio", 0.0)
        result["focus_time_sec"] = 0
        result["focus_total_sec"] = 0
        result["bad_posture_count"] = _round_seconds(counts["bad_posture"])
        result["bad_posture_total_sec"] = 0
        result["gaze_away_count"] = _round_seconds(counts["gaze_away"])
        result["gaze_away_total_sec"] = 0
        result.setdefault("away_count", result["gaze_away_count"])
        result.setdefault("away_total_sec", 0)
        result["drowsy_count"] = _round_seconds(counts["drowsy"])
        result["drowsy_total_sec"] = 0
        result["sleep_suspect_count"] = _round_seconds(counts["sleep_suspect"])
        result.setdefault("sleep_suspect_total_sec", 0)
        result["unknown_total_sec"] = 0
        result.setdefault("unknown_count", 0)
        result.setdefault("present_unknown_total_sec", 0)
        result.setdefault("present_unknown_count", 0)
        result["absent_count"] = _round_seconds(counts["absent"])
        result["absent_total_sec"] = 0
        result["weighted_base_score"] = 0.0
        result["event_penalty"] = 0.0
        result["focus_score"] = 0
        return result

    corrected_times: dict[str, float] = {}
    remaining_time = total_time
    was_corrected = False

    for state in PRIORITY_ORDER:
        requested_time = raw_times[state]
        allowed_time = min(requested_time, remaining_time)
        corrected_times[state] = allowed_time
        remaining_time -= allowed_time

        if requested_time > allowed_time + 1e-9:
            was_corrected = True

    if was_corrected:
        _append_warning(
            result,
            "state durations exceeded total_time_sec and were capped by priority.",
        )

    weighted_base_score = (
        sum(corrected_times[state] * STATE_WEIGHTS[state] for state in PRIORITY_ORDER)
        / total_time
    )

    raw_event_penalty = (
        counts["absent"] * EVENT_PENALTIES["absent"]
        + counts["drowsy"] * EVENT_PENALTIES["drowsy"]
        + counts["sleep_suspect"] * EVENT_PENALTIES["sleep_suspect"]
        + counts["gaze_away"] * EVENT_PENALTIES["gaze_away"]
        + counts["bad_posture"] * EVENT_PENALTIES["bad_posture"]
    )
    event_penalty = min(raw_event_penalty, MAX_EVENT_PENALTY)
    focus_score = max(0.0, min(100.0, weighted_base_score - event_penalty))

    result["focus_time_sec"] = _round_seconds(corrected_times["focus"])
    result["focus_total_sec"] = result["focus_time_sec"]
    result["focus_ratio"] = round(corrected_times["focus"] / total_time, 4)
    result["bad_posture_count"] = _round_seconds(counts["bad_posture"])
    result["bad_posture_total_sec"] = _round_seconds(corrected_times["bad_posture"])
    result["gaze_away_count"] = _round_seconds(counts["gaze_away"])
    result["gaze_away_total_sec"] = _round_seconds(corrected_times["gaze_away"])
    result["away_count"] = result["gaze_away_count"]
    result["away_total_sec"] = result["gaze_away_total_sec"]
    result["drowsy_count"] = _round_seconds(counts["drowsy"])
    result["drowsy_total_sec"] = _round_seconds(corrected_times["drowsy"])
    result["sleep_suspect_count"] = _round_seconds(
        _get_count(result, ("sleep_suspect_count",))
    )
    result.setdefault("sleep_suspect_total_sec", 0)
    result["unknown_total_sec"] = _round_seconds(corrected_times["unknown"])
    result.setdefault("unknown_count", _round_seconds(_get_count(result, ("unknown_count",))))
    result["present_unknown_total_sec"] = _round_seconds(corrected_times["present_unknown"])
    result.setdefault(
        "present_unknown_count",
        _round_seconds(_get_count(result, ("present_unknown_count",))),
    )
    result["absent_count"] = _round_seconds(counts["absent"])
    result["absent_total_sec"] = _round_seconds(corrected_times["absent"])
    result["weighted_base_score"] = round(float(weighted_base_score), 1)
    result["event_penalty"] = round(float(event_penalty), 1)
    result["focus_score"] = _round_score(focus_score)

    return result
