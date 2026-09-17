from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections import Counter
from typing import Any, Optional

FEEDBACK_VERSION = "feedback-v1"


def _to_float(value: Any) -> float:
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return 0.0


def _to_int(value: Any) -> int:
    return int(round(_to_float(value)))


def _format_duration(seconds: float) -> str:
    total_sec = _to_int(seconds)
    minutes = total_sec // 60
    sec = total_sec % 60

    if minutes <= 0:
        return f"{sec}초"
    if sec == 0:
        return f"{minutes}분"
    return f"{minutes}분 {sec}초"


def _format_range(start_sec: Any, end_sec: Any) -> str:
    start = _to_int(start_sec)
    end = _to_int(end_sec)
    return f"{start // 60}:{start % 60:02d}-{end // 60}:{end % 60:02d}"


def _percent(seconds: float, total_seconds: float) -> int:
    if total_seconds <= 0:
        return 0
    return int(round((seconds / total_seconds) * 100))


def _get_gaze_away_time(summary: dict[str, Any]) -> float:
    explicit = _to_float(summary.get("gaze_away_total_sec"))
    if explicit > 0:
        return explicit

    return (
        _to_float(summary.get("away_total_sec"))
        + _to_float(summary.get("gaze_side_total_sec"))
        + _to_float(summary.get("gaze_down_total_sec"))
    )


def _problem_times(summary: dict[str, Any]) -> list[tuple[str, float]]:
    return [
        ("drowsy", _to_float(summary.get("drowsy_total_sec"))),
        ("absent", _to_float(summary.get("absent_total_sec"))),
        ("unknown", _to_float(summary.get("unknown_total_sec"))),
        ("bad_posture", _to_float(summary.get("bad_posture_total_sec"))),
        ("gaze_away", _get_gaze_away_time(summary)),
    ]


def _main_problem_state(summary: dict[str, Any]) -> str:
    state, seconds = max(_problem_times(summary), key=lambda item: item[1])
    return state if seconds > 0 else "none"


def _problem_label(state: str) -> str:
    labels = {
        "focus": "집중",
        "absent": "자리비움/미검출",
        "drowsy": "졸음 의심",
        "sleep_suspect": "수면 의심",
        "unknown": "인식 불안정",
        "gaze_away": "시선 이탈",
        "gaze_side": "시선 이탈",
        "gaze_down": "아래 시선",
        "bad_posture": "자세 불안정",
        "head_down": "고개 숙임",
        "head_tilt": "고개 기울어짐",
        "eye_closed": "눈 감김",
        "long_eye_closure": "긴 눈 감김",
        "none": "뚜렷한 문제 없음",
    }
    return labels.get(state, state)


def _risk_label(score: float) -> str:
    if score >= 85:
        return "매우 안정적"
    if score >= 70:
        return "양호"
    if score >= 50:
        return "보통"
    return "주의 필요"


def _top_problem_text(summary: dict[str, Any], total_seconds: float) -> str:
    ranked = [
        (state, seconds)
        for state, seconds in sorted(_problem_times(summary), key=lambda item: item[1], reverse=True)
        if seconds > 0
    ]

    if not ranked:
        return "뚜렷하게 반복된 방해 상태는 확인되지 않았습니다."

    parts = []
    for state, seconds in ranked[:3]:
        parts.append(
            f"{_problem_label(state)} {_format_duration(seconds)}"
            f"({_percent(seconds, total_seconds)}%)"
        )
    return ", ".join(parts)


def _segment_lookup(time_patterns: Optional[dict[str, Any]], key: str) -> Optional[dict[str, Any]]:
    if not isinstance(time_patterns, dict):
        return None

    segment = time_patterns.get(key)
    return segment if isinstance(segment, dict) else None


def _matching_segment(
    time_patterns: Optional[dict[str, Any]],
    segment_ref: Optional[dict[str, Any]],
) -> Optional[dict[str, Any]]:
    if not isinstance(time_patterns, dict) or not isinstance(segment_ref, dict):
        return None

    segments = time_patterns.get("segments")
    if not isinstance(segments, list):
        return None

    start_sec = _to_int(segment_ref.get("start_sec"))
    end_sec = _to_int(segment_ref.get("end_sec"))
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        if _to_int(segment.get("start_sec")) == start_sec and _to_int(segment.get("end_sec")) == end_sec:
            return segment
    return None


def _segment_text(time_patterns: Optional[dict[str, Any]], key: str) -> str:
    segment_ref = _segment_lookup(time_patterns, key)
    segment = _matching_segment(time_patterns, segment_ref) or segment_ref
    if not isinstance(segment, dict):
        return ""

    ratio = _to_float(segment.get("focus_ratio"))
    main_issue = str(segment.get("main_issue") or segment.get("dominant_state") or "unknown")
    return (
        f"{_format_range(segment.get('start_sec'), segment.get('end_sec'))}"
        f" 구간 집중률 {int(round(ratio * 100))}%"
        f", 주요 상태는 {_problem_label(main_issue)}"
    )


def _recommendation_for(main_problem: str, summary: dict[str, Any], time_patterns: Optional[dict[str, Any]]) -> str:
    worst_text = _segment_text(time_patterns, "worst_segment")
    best_text = _segment_text(time_patterns, "best_segment")
    sleep_suspect_sec = _to_float(summary.get("sleep_suspect_total_sec"))

    if main_problem == "drowsy":
        extra = ""
        if sleep_suspect_sec > 0:
            extra = f" 얼굴 미검출 중 수면 의심으로 보정된 시간이 {_format_duration(sleep_suspect_sec)} 포함되어 있습니다."
        return (
            f"졸음 의심이 가장 크므로 25~30분 단위 휴식, 화면/책상 높이 조정, 조명 보강을 우선 권장합니다.{extra}"
            + (f" 특히 {worst_text}을 먼저 확인해 보세요." if worst_text else "")
        )

    if main_problem == "absent":
        return (
            "자리비움 또는 얼굴/몸 미검출 시간이 길어 점수 하락이 큽니다. 실제 이탈인지, 고개 숙임이나 화면 밖 얼굴 잘림인지 원본 구간을 확인하고 카메라 각도를 조정하는 것이 좋습니다."
            + (f" 우선 확인 구간은 {worst_text}입니다." if worst_text else "")
        )

    if main_problem == "unknown":
        unknown_sec = _to_float(summary.get("unknown_total_sec"))
        total_sec = _to_float(summary.get("duration_sec", summary.get("total_time_sec")))
        if total_sec > 0 and unknown_sec / total_sec < 0.05:
            return (
                "전체 집중 흐름은 안정적입니다. 짧은 인식 불안정 구간만 있었으므로 "
                "현재 카메라 위치를 유지하고 같은 문제가 반복될 때만 조명과 각도를 점검해 보세요."
            )
        return (
            "인식 불안정 비중이 높습니다. 얼굴이 화면 하단/가장자리로 벗어나지 않도록 전면 카메라 높이와 거리, 머리카락/안경 반사를 먼저 조정해 보세요."
            + (f" 비교적 나은 기준 구간은 {best_text}입니다." if best_text else "")
        )

    if main_problem == "bad_posture":
        return (
            "자세 불안정이 반복됩니다. 의자 높이와 책상 거리를 맞추고, 고개가 아래로 오래 떨어지지 않게 교재 위치를 올리는 것이 좋습니다."
            + (f" 자세가 흔들린 구간은 {worst_text}부터 확인하세요." if worst_text else "")
        )

    if main_problem == "gaze_away":
        return (
            "시선 이탈 시간이 확인됩니다. 휴대폰/주변 자극을 줄이고, 교재와 화면을 같은 시야 안에 배치하는 편이 좋습니다."
            + (f" 특히 {worst_text}을 확인해 보세요." if worst_text else "")
        )

    return "현재 패턴을 유지하되, 장시간 학습에서는 25~30분 단위로 짧은 휴식을 넣어 집중 저하를 예방하는 것이 좋습니다."


def _duration_from_segment(segment: dict[str, Any]) -> int:
    duration = _to_int(segment.get("end_sec")) - _to_int(segment.get("start_sec"))
    return max(0, duration)


def _segment_breakdown(segment: Optional[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(segment, dict):
        return []

    state_counts = segment.get("state_counts")
    if not isinstance(state_counts, dict):
        return []

    duration = _duration_from_segment(segment)
    rows = []
    for state, raw_seconds in sorted(
        state_counts.items(),
        key=lambda item: _to_float(item[1]),
        reverse=True,
    ):
        seconds = _to_float(raw_seconds)
        rows.append(
            {
                "state": str(state),
                "label": _problem_label(str(state)),
                "seconds": _to_int(seconds),
                "duration_text": _format_duration(seconds),
                "ratio": round(seconds / duration, 3) if duration > 0 else 0.0,
                "percent": _percent(seconds, duration),
            }
        )

    return rows


def _segment_reason(segment: Optional[dict[str, Any]]) -> str:
    if not isinstance(segment, dict):
        return "최저 집중률 구간을 계산할 수 있는 시간대 정보가 부족합니다."

    duration = _duration_from_segment(segment)
    state_counts = segment.get("state_counts")
    if not isinstance(state_counts, dict) or duration <= 0:
        return "최저 집중률 구간의 상태별 시간 정보가 부족합니다."

    focus_sec = _to_float(state_counts.get("focus"))
    problem_rows = [
        row
        for row in _segment_breakdown(segment)
        if row["state"] != "focus" and row["seconds"] > 0
    ][:3]
    problem_text = ", ".join(
        f"{row['label']} {row['duration_text']}({row['percent']}%)"
        for row in problem_rows
    )
    if not problem_text:
        problem_text = "뚜렷한 방해 상태는 확인되지 않았습니다"

    return (
        f"{_format_range(segment.get('start_sec'), segment.get('end_sec'))} 구간은 "
        f"총 {_format_duration(duration)} 중 집중 상태가 {_format_duration(focus_sec)}"
        f"({_percent(focus_sec, duration)}%)에 그쳤고, {problem_text}가 누적되어 "
        "가장 낮은 집중률 구간으로 판단했습니다."
    )


def _overlap_seconds(event: dict[str, Any], start_sec: int, end_sec: int) -> int:
    event_start = _to_int(event.get("start_sec"))
    event_end = _to_int(event.get("end_sec"))
    return max(0, min(event_end, end_sec) - max(event_start, start_sec))


def _supporting_events(
    events: Optional[list[dict[str, Any]]],
    segment: Optional[dict[str, Any]],
    limit: int = 8,
) -> list[dict[str, Any]]:
    if not isinstance(events, list) or not isinstance(segment, dict):
        return []

    start_sec = _to_int(segment.get("start_sec"))
    end_sec = _to_int(segment.get("end_sec"))
    rows = []

    for event in events:
        if not isinstance(event, dict):
            continue

        source = str(event.get("source", "final"))
        event_type = str(event.get("type", "unknown"))
        if source == "overhead" or event_type.startswith("overhead_"):
            continue

        overlap = _overlap_seconds(event, start_sec, end_sec)
        if overlap <= 0:
            continue

        rows.append(
            {
                "type": event_type,
                "label": _problem_label(event_type),
                "source": source,
                "start_sec": _to_int(event.get("start_sec")),
                "end_sec": _to_int(event.get("end_sec")),
                "time_range": _format_range(event.get("start_sec"), event.get("end_sec")),
                "overlap_sec": overlap,
                "overlap_text": _format_duration(overlap),
            }
        )

    rows.sort(key=lambda row: row["overlap_sec"], reverse=True)
    return rows[:limit]


def _timeline_problem_streaks(
    timeline: Optional[list[dict[str, Any]]],
    min_duration_sec: int = 5,
) -> list[dict[str, Any]]:
    if not isinstance(timeline, list):
        return []

    streaks: list[dict[str, Any]] = []
    current_start: Optional[int] = None
    current_states: list[str] = []

    def close_streak(end_sec: int) -> None:
        nonlocal current_start, current_states

        if current_start is None:
            return

        duration = end_sec - current_start
        if duration >= min_duration_sec:
            counts = Counter(current_states)
            breakdown = []
            for state, seconds in counts.most_common():
                breakdown.append(
                    {
                        "state": state,
                        "label": _problem_label(state),
                        "seconds": int(seconds),
                        "duration_text": _format_duration(seconds),
                        "ratio": round(seconds / duration, 3) if duration > 0 else 0.0,
                        "percent": _percent(seconds, duration),
                    }
                )

            dominant_state = breakdown[0]["state"] if breakdown else "unknown"
            streaks.append(
                {
                    "start_sec": current_start,
                    "end_sec": end_sec,
                    "time_range": _format_range(current_start, end_sec),
                    "duration_sec": duration,
                    "duration_text": _format_duration(duration),
                    "dominant_state": dominant_state,
                    "dominant_label": _problem_label(dominant_state),
                    "state_breakdown": breakdown,
                    "reason": (
                        f"{_format_range(current_start, end_sec)} 동안 "
                        f"{_format_duration(duration)} 연속으로 집중 상태가 아니었고, "
                        f"가장 많이 나타난 상태는 {_problem_label(dominant_state)}입니다."
                    ),
                }
            )

        current_start = None
        current_states = []

    for item in timeline:
        if not isinstance(item, dict):
            continue

        t = _to_int(item.get("t"))
        state = str(item.get("state") or "unknown")

        if state == "focus":
            close_streak(t)
            continue

        if current_start is None:
            current_start = t
            current_states = []

        current_states.append(state)

    if timeline:
        last_item = timeline[-1] if isinstance(timeline[-1], dict) else {}
        close_streak(_to_int(last_item.get("t")) + 1)

    streaks.sort(key=lambda row: row["duration_sec"], reverse=True)
    return streaks


def build_feedback_evidence(
    summary: dict[str, Any],
    time_patterns: Optional[dict[str, Any]] = None,
    events: Optional[list[dict[str, Any]]] = None,
    timeline: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    worst_ref = _segment_lookup(time_patterns, "worst_segment")
    best_ref = _segment_lookup(time_patterns, "best_segment")
    worst_segment = _matching_segment(time_patterns, worst_ref) or worst_ref
    best_segment = _matching_segment(time_patterns, best_ref) or best_ref

    main_problem = _main_problem_state(summary)
    problem_rank = [
        {
            "state": state,
            "label": _problem_label(state),
            "seconds": _to_int(seconds),
            "duration_text": _format_duration(seconds),
        }
        for state, seconds in sorted(_problem_times(summary), key=lambda item: item[1], reverse=True)
        if seconds > 0
    ]
    problem_streaks = _timeline_problem_streaks(timeline)
    longest_problem_streak = problem_streaks[0] if problem_streaks else None

    return {
        "usage": "최종 리포트에는 feedback를 사용하고, 이 객체는 결과 검증/설명용 근거로 사용합니다.",
        "main_problem": {
            "state": main_problem,
            "label": _problem_label(main_problem),
        },
        "problem_rank": problem_rank,
        "lowest_focus_reason": _segment_reason(worst_segment),
        "worst_segment": {
            "start_sec": _to_int(worst_segment.get("start_sec")) if isinstance(worst_segment, dict) else None,
            "end_sec": _to_int(worst_segment.get("end_sec")) if isinstance(worst_segment, dict) else None,
            "time_range": _format_range(worst_segment.get("start_sec"), worst_segment.get("end_sec")) if isinstance(worst_segment, dict) else None,
            "focus_ratio": _to_float(worst_segment.get("focus_ratio")) if isinstance(worst_segment, dict) else None,
            "focus_percent": int(round(_to_float(worst_segment.get("focus_ratio")) * 100)) if isinstance(worst_segment, dict) else None,
            "dominant_state": worst_segment.get("dominant_state") if isinstance(worst_segment, dict) else None,
            "main_issue": worst_segment.get("main_issue") if isinstance(worst_segment, dict) else None,
            "state_breakdown": _segment_breakdown(worst_segment),
            "supporting_events": _supporting_events(events, worst_segment),
        },
        "best_segment": {
            "start_sec": _to_int(best_segment.get("start_sec")) if isinstance(best_segment, dict) else None,
            "end_sec": _to_int(best_segment.get("end_sec")) if isinstance(best_segment, dict) else None,
            "time_range": _format_range(best_segment.get("start_sec"), best_segment.get("end_sec")) if isinstance(best_segment, dict) else None,
            "focus_ratio": _to_float(best_segment.get("focus_ratio")) if isinstance(best_segment, dict) else None,
            "focus_percent": int(round(_to_float(best_segment.get("focus_ratio")) * 100)) if isinstance(best_segment, dict) else None,
            "state_breakdown": _segment_breakdown(best_segment),
        },
        "longest_problem_streak": longest_problem_streak,
        "problem_streaks_top": problem_streaks[:5],
    }


def generate_feedback(
    summary: dict[str, Any],
    time_patterns: Optional[dict[str, Any]] = None,
) -> dict[str, str]:
    focus_score = _to_float(summary.get("focus_score"))
    total_seconds = _to_float(summary.get("duration_sec"))
    if total_seconds <= 0 and isinstance(time_patterns, dict):
        segments = time_patterns.get("segments")
        if isinstance(segments, list) and segments:
            total_seconds = max(
                _to_float(segment.get("end_sec"))
                for segment in segments
                if isinstance(segment, dict)
            )
    if total_seconds <= 0:
        total_seconds = (
            _to_float(summary.get("focus_total_sec"))
            + sum(seconds for _, seconds in _problem_times(summary))
        )

    focus_sec = _to_float(summary.get("focus_total_sec", summary.get("focus_time_sec")))
    present_sec = _to_float(summary.get("present_total_sec"))
    main_problem = _main_problem_state(summary)
    worst_text = _segment_text(time_patterns, "worst_segment")
    best_text = _segment_text(time_patterns, "best_segment")

    summary_text = (
        f"총 {_format_duration(total_seconds)} 분석 결과, 집중 점수는 {int(round(focus_score))}점으로 "
        f"{_risk_label(focus_score)} 수준입니다. "
        f"집중 시간은 {_format_duration(focus_sec)}({_percent(focus_sec, total_seconds)}%)"
    )
    if present_sec > 0:
        summary_text += f", 착석/감지 시간은 {_format_duration(present_sec)}({_percent(present_sec, total_seconds)}%)"
    summary_text += "입니다."

    weak_point = f"주요 저하 요인은 {_top_problem_text(summary, total_seconds)}입니다."
    if worst_text:
        weak_point += f" 가장 취약한 시간대는 {worst_text}입니다."
    if best_text:
        weak_point += f" 가장 나은 시간대는 {best_text}입니다."

    recommendation = _recommendation_for(main_problem, summary, time_patterns)

    return {
        "summary_text": summary_text,
        "weak_point": weak_point,
        "recommendation": recommendation,
    }


def _summary_metric(summary: dict[str, Any], *keys: str) -> float:
    for key in keys:
        if key in summary and summary[key] is not None:
            return _to_float(summary[key])
    return 0.0


def _get_gaze_away_count(summary: dict[str, Any]) -> float:
    explicit = _summary_metric(summary, "gaze_away_count")
    if explicit > 0:
        return explicit

    return (
        _summary_metric(summary, "away_count")
        + _summary_metric(summary, "gaze_side_count")
        + _summary_metric(summary, "gaze_down_count")
    )


def _get_total_seconds(analysis_result: dict[str, Any], summary: dict[str, Any]) -> float:
    meta = analysis_result.get("meta")
    if not isinstance(meta, dict):
        meta = {}

    total_seconds = _summary_metric(meta, "duration_sec", "total_time_sec", "total_time")
    if total_seconds > 0:
        return total_seconds

    total_seconds = _summary_metric(summary, "duration_sec", "total_time_sec", "total_time")
    if total_seconds > 0:
        return total_seconds

    time_patterns = analysis_result.get("time_patterns")
    if isinstance(time_patterns, dict):
        segments = time_patterns.get("segments")
        if isinstance(segments, list) and segments:
            total_seconds = max(
                _to_float(segment.get("end_sec"))
                for segment in segments
                if isinstance(segment, dict)
            )
            if total_seconds > 0:
                return total_seconds

    timeline = analysis_result.get("timeline")
    if isinstance(timeline, list) and timeline:
        max_time = 0.0
        for row in timeline:
            if not isinstance(row, dict):
                continue
            max_time = max(max_time, _to_float(row.get("t", row.get("time"))))
        if max_time > 0:
            return max_time + 1

    return (
        _summary_metric(summary, "focus_total_sec", "focus_time_sec", "focus_time")
        + _summary_metric(summary, "bad_posture_total_sec", "bad_posture_time_sec")
        + _get_gaze_away_time(summary)
        + _summary_metric(summary, "drowsy_total_sec", "drowsy_time_sec")
        + _summary_metric(summary, "absent_total_sec", "absence_time_sec")
    )


def _focus_score_from_result(analysis_result: dict[str, Any], summary: dict[str, Any]) -> float:
    score = _summary_metric(analysis_result, "focus_score")
    if score > 0 or analysis_result.get("focus_score") == 0:
        return score
    return _summary_metric(summary, "focus_score", "concentration_score")


def _timeline_states_for_feedback(item: dict[str, Any]) -> list[str]:
    states = item.get("states")
    if isinstance(states, list) and states:
        clean_states = [str(state) for state in states if state]
    else:
        state = item.get("state")
        clean_states = [str(state)] if state else []

    flags = item.get("flags")
    if isinstance(flags, dict):
        for flag_name in (
            "gaze_away",
            "gaze_side",
            "gaze_down",
            "drowsy",
            "sleep_suspect",
            "eye_closed",
            "long_eye_closure",
            "bad_posture",
            "head_down",
            "head_tilt",
            "absent",
        ):
            if flags.get(flag_name):
                clean_states.append(flag_name)

    if not clean_states:
        clean_states.append("focus")

    return list(dict.fromkeys(clean_states))


def _build_timeline_segments(
    timeline: list[dict[str, Any]],
    total_seconds: float,
    interval_sec: int = 600,
) -> list[dict[str, Any]]:
    if not timeline:
        return []

    grouped: dict[int, list[dict[str, Any]]] = {}
    for item in timeline:
        if not isinstance(item, dict):
            continue
        t = _to_int(item.get("t", item.get("time")))
        if t < 0:
            continue
        start_sec = (t // interval_sec) * interval_sec
        grouped.setdefault(start_sec, []).append(item)

    if total_seconds <= 0:
        total_seconds = max(grouped.keys()) + interval_sec if grouped else 0

    segments: list[dict[str, Any]] = []
    for start_sec in range(0, _to_int(total_seconds), interval_sec):
        rows = grouped.get(start_sec, [])
        if not rows:
            continue

        state_counts: Counter[str] = Counter()
        primary_counts: Counter[str] = Counter()
        for row in rows:
            states = _timeline_states_for_feedback(row)
            state_counts.update(states)
            primary_counts.update([str(row.get("state") or states[0])])

        total_count = len(rows)
        focus_count = int(state_counts.get("focus", 0))
        focus_ratio = focus_count / total_count if total_count > 0 else 0.0
        issue_counts = Counter({state: count for state, count in state_counts.items() if state != "focus"})

        segments.append(
            {
                "start_sec": int(start_sec),
                "end_sec": int(min(start_sec + interval_sec, _to_int(total_seconds))),
                "total_count": int(total_count),
                "state_counts": dict(state_counts),
                "focus_ratio": round(float(focus_ratio), 3),
                "dominant_state": primary_counts.most_common(1)[0][0] if primary_counts else None,
                "main_issue": issue_counts.most_common(1)[0][0] if issue_counts else None,
            }
        )

    return segments


def _segments_from_result(analysis_result: dict[str, Any], total_seconds: float) -> list[dict[str, Any]]:
    time_patterns = analysis_result.get("time_patterns")
    if isinstance(time_patterns, dict):
        segments = time_patterns.get("segments")
        if isinstance(segments, list) and segments:
            return [dict(segment) for segment in segments if isinstance(segment, dict)]

    timeline = analysis_result.get("timeline")
    if isinstance(timeline, list):
        return _build_timeline_segments(timeline, total_seconds)

    return []


def _problem_category(state: str) -> Optional[str]:
    normalized = str(state or "").lower()
    if normalized in {"gaze_away", "gaze_side", "gaze_down", "away"}:
        return "gaze_away"
    if normalized in {"drowsy", "sleep_suspect", "eye_closed", "long_eye_closure"}:
        return "drowsy"
    if normalized in {"bad_posture", "head_down", "head_tilt"}:
        return "bad_posture"
    if normalized == "absent":
        return "absent"
    if normalized == "unknown":
        return "unknown"
    return None


def _category_label(category: str) -> str:
    labels = {
        "gaze_away": "시선이탈 증가",
        "drowsy": "졸음/눈 감김 증가",
        "bad_posture": "자세불량 증가",
        "absent": "자리비움/미검출 증가",
        "unknown": "인식 불안정 증가",
        "focus_drop": "집중 저하",
    }
    return labels.get(category, category)


def _segment_category_counts(segment: dict[str, Any]) -> Counter[str]:
    counts: Counter[str] = Counter()
    state_counts = segment.get("state_counts")
    if not isinstance(state_counts, dict):
        return counts

    for state, raw_seconds in state_counts.items():
        category = _problem_category(str(state))
        if category:
            counts[category] += _to_float(raw_seconds)

    return counts


def _segment_duration(segment: dict[str, Any]) -> float:
    duration = _to_float(segment.get("end_sec")) - _to_float(segment.get("start_sec"))
    if duration > 0:
        return duration
    return _to_float(segment.get("total_count"))


def _build_worst_segments(segments: list[dict[str, Any]], limit: int = 3) -> list[dict[str, Any]]:
    scored: list[tuple[float, dict[str, Any], str, float]] = []

    for segment in segments:
        duration = _segment_duration(segment)
        if duration <= 0:
            continue

        category_counts = _segment_category_counts(segment)
        if category_counts:
            category, problem_seconds = category_counts.most_common(1)[0]
            focus_ratio = _to_float(segment.get("focus_ratio"))
            severity = problem_seconds + max(0.0, 1.0 - focus_ratio) * duration
        else:
            focus_ratio = _to_float(segment.get("focus_ratio"))
            if focus_ratio >= 0.8:
                continue
            category = "focus_drop"
            problem_seconds = max(0.0, 1.0 - focus_ratio) * duration
            severity = problem_seconds

        scored.append((severity, segment, category, problem_seconds))

    scored.sort(key=lambda item: item[0], reverse=True)

    worst_segments: list[dict[str, Any]] = []
    for _, segment, category, _problem_seconds in scored[:limit]:
        start_sec = _to_int(segment.get("start_sec"))
        end_sec = _to_int(segment.get("end_sec"))
        problem = _category_label(category)
        worst_segments.append(
            {
                "start_sec": start_sec,
                "end_sec": end_sec,
                "problem": problem,
                "feedback": f"{_format_range(start_sec, end_sec)} 구간에서 {problem} 패턴이 두드러져 집중이 가장 많이 흐트러졌습니다.",
            }
        )

    return worst_segments


def _weighted_focus_ratio(segments: list[dict[str, Any]]) -> float:
    total_duration = 0.0
    weighted_focus = 0.0
    for segment in segments:
        duration = _segment_duration(segment)
        if duration <= 0:
            continue
        total_duration += duration
        weighted_focus += _to_float(segment.get("focus_ratio")) * duration
    return weighted_focus / total_duration if total_duration > 0 else 0.0


def _category_seconds_in_window(
    segments: list[dict[str, Any]],
    categories: set[str],
    start_sec: float,
    end_sec: float,
) -> tuple[float, float]:
    total_duration = 0.0
    total_problem = 0.0
    for segment in segments:
        segment_start = _to_float(segment.get("start_sec"))
        segment_end = _to_float(segment.get("end_sec"))
        overlap = max(0.0, min(segment_end, end_sec) - max(segment_start, start_sec))
        duration = _segment_duration(segment)
        if overlap <= 0 or duration <= 0:
            continue

        ratio = overlap / duration
        category_counts = _segment_category_counts(segment)
        total_duration += overlap
        total_problem += sum(category_counts.get(category, 0.0) for category in categories) * ratio

    return total_problem, total_duration


def _late_decline_reason(segments: list[dict[str, Any]], total_seconds: float) -> Optional[str]:
    if total_seconds < 3600 or not segments:
        return None

    first_end = max(1.0, min(1800.0, total_seconds / 3))
    late_start = max(3600.0, total_seconds * 2 / 3)
    early_segments = [
        segment
        for segment in segments
        if _to_float(segment.get("start_sec")) < first_end
    ]
    late_segments = [
        segment
        for segment in segments
        if _to_float(segment.get("end_sec")) > late_start
    ]

    early_focus = _weighted_focus_ratio(early_segments)
    late_focus = _weighted_focus_ratio(late_segments)
    focus_drop_point = int(round((early_focus - late_focus) * 100))

    problem_categories = {"gaze_away", "bad_posture", "drowsy"}
    before_problem, before_duration = _category_seconds_in_window(
        segments,
        problem_categories,
        0.0,
        3600.0,
    )
    after_problem, after_duration = _category_seconds_in_window(
        segments,
        problem_categories,
        3600.0,
        total_seconds,
    )
    before_rate = before_problem / before_duration if before_duration > 0 else 0.0
    after_rate = after_problem / after_duration if after_duration > 0 else 0.0

    focus_declined = early_focus > 0 and focus_drop_point >= 10
    problems_increased = after_duration > 0 and after_rate >= max(before_rate + 0.05, before_rate * 1.25)

    if not focus_declined and not problems_increased:
        return None

    if focus_declined and problems_increased:
        return (
            f"초반 집중률보다 후반부 집중률이 약 {focus_drop_point}%p 낮고, "
            "60분 이후 시선이탈/자세불량/졸음 패턴이 증가했습니다."
        )
    if focus_declined:
        return f"초반 집중률보다 후반부 집중률이 약 {focus_drop_point}%p 낮았습니다."
    return "60분 이후 시선이탈, 자세불량, 졸음 관련 상태가 초반보다 더 자주 나타났습니다."


def _high_metric(seconds: float, count: float, total_seconds: float, ratio: float, min_seconds: float, min_count: float) -> bool:
    if total_seconds > 0 and seconds >= total_seconds * ratio:
        return True
    return seconds >= min_seconds or count >= min_count


def _timeline_union_seconds(
    analysis_result: dict[str, Any],
    states: set[str],
    flags: set[str],
) -> float:
    timeline = analysis_result.get("timeline")
    if not isinstance(timeline, list):
        return 0.0

    matched_seconds = 0
    for item in timeline:
        if not isinstance(item, dict):
            continue

        state = str(item.get("state") or "")
        item_flags = item.get("flags")
        if not isinstance(item_flags, dict):
            item_flags = {}

        if state in states or any(bool(item_flags.get(flag)) for flag in flags):
            matched_seconds += 1

    return float(matched_seconds)


def _rule_based_personal_feedback(analysis_result: dict[str, Any]) -> dict[str, Any]:
    summary = analysis_result.get("summary")
    if not isinstance(summary, dict):
        summary = {}

    total_seconds = _get_total_seconds(analysis_result, summary)
    segments = _segments_from_result(analysis_result, total_seconds)
    worst_segments = _build_worst_segments(segments)

    focus_score = _focus_score_from_result(analysis_result, summary)
    gaze_sec = _get_gaze_away_time(summary)
    gaze_count = _get_gaze_away_count(summary)
    drowsy_sec = _summary_metric(summary, "drowsy_total_sec", "drowsy_time_sec")
    eye_closed_sec = _summary_metric(summary, "eye_closed_total_sec")
    long_eye_closure_count = _summary_metric(summary, "long_eye_closure_count")
    bad_posture_sec = _summary_metric(summary, "bad_posture_total_sec", "bad_posture_time_sec")
    head_down_sec = _summary_metric(summary, "head_down_total_sec")
    head_tilt_sec = _summary_metric(summary, "head_tilt_total_sec")
    absent_sec = _summary_metric(summary, "absent_total_sec", "absence_time_sec")

    late_reason = _late_decline_reason(segments, total_seconds)
    if late_reason:
        return {
            "main_problem": "후반부 집중 저하",
            "reason": late_reason,
            "feedback": "학습 시간이 길어질수록 집중력이 떨어지는 패턴이 보입니다. 다음 학습에서는 50분 학습 후 10분 휴식을 권장합니다.",
            "next_action": "50분 학습 + 10분 휴식 모드를 사용해보세요.",
            "worst_segments": worst_segments,
        }

    candidates: list[tuple[float, str, str, str, str]] = []
    if _high_metric(gaze_sec, gaze_count, total_seconds, 0.08, 120.0, 5.0):
        severity = (gaze_sec / total_seconds if total_seconds > 0 else 0.0) + gaze_count * 0.01
        candidates.append(
            (
                severity,
                "시선이탈 증가",
                f"전체 학습 중 시선이탈이 {_format_duration(gaze_sec)} 발생했고, 관련 이벤트가 {_to_int(gaze_count)}회 감지되었습니다.",
                "학습 중 화면 또는 책상 외부를 보는 시간이 많았습니다. 주변 방해 요소를 줄이고 학습 자료를 정면에 배치하는 것이 좋습니다.",
                "휴대폰과 알림을 치우고, 교재와 화면을 같은 시야 안에 배치해보세요.",
            )
        )

    timeline = analysis_result.get("timeline")
    has_manual_review = isinstance(timeline, list) and any(
        isinstance(row, dict) and row.get("decision_source") == "codex_manual_review"
        for row in timeline
    )
    if has_manual_review:
        drowsy_total = _timeline_union_seconds(
            analysis_result,
            states={"drowsy", "sleep_suspect"},
            flags=set(),
        )
        closure_count_for_feedback = 0.0
    else:
        drowsy_total = max(drowsy_sec, eye_closed_sec)
        closure_count_for_feedback = long_eye_closure_count
    if _high_metric(drowsy_total, closure_count_for_feedback, total_seconds, 0.05, 60.0, 2.0):
        severity = (drowsy_total / total_seconds if total_seconds > 0 else 0.0) + long_eye_closure_count * 0.03
        candidates.append(
            (
                severity,
                "졸음 또는 눈 감김 반복",
                f"졸음 징후가 {_format_duration(drowsy_sec)}, 눈 감김이 {_format_duration(eye_closed_sec)} 감지되었습니다.",
                "눈 감김과 졸음 징후가 반복적으로 나타났습니다. 무리하게 학습을 지속하기보다 짧은 휴식이나 스트레칭 후 다시 시작하는 것이 좋습니다.",
                "5분 휴식, 물 마시기, 가벼운 스트레칭 후 학습을 다시 시작해보세요.",
            )
        )

    if has_manual_review:
        posture_total = _timeline_union_seconds(
            analysis_result,
            states={"bad_posture"},
            flags=set(),
        )
    else:
        posture_total = _timeline_union_seconds(
            analysis_result,
            states={"bad_posture"},
            flags={"bad_posture", "head_down", "head_tilt"},
        )
        if posture_total <= 0:
            posture_total = max(bad_posture_sec, head_down_sec, head_tilt_sec)
    if _high_metric(posture_total, _summary_metric(summary, "bad_posture_count"), total_seconds, 0.10, 180.0, 5.0):
        severity = posture_total / total_seconds if total_seconds > 0 else posture_total / 600.0
        candidates.append(
            (
                severity,
                "자세불량 또는 고개 숙임",
                f"자세불량/고개 숙임 관련 시간이 총 {_format_duration(posture_total)} 감지되었습니다.",
                "학습 중 고개가 아래로 향하거나 자세가 무너지는 시간이 많았습니다. 책상 높이와 의자 위치를 조정하고 교재를 눈높이에 맞추는 것을 권장합니다.",
                "교재를 눈높이에 가깝게 올리고, 의자와 책상 거리를 다시 맞춰보세요.",
            )
        )

    if candidates:
        _severity, main_problem, reason, feedback, next_action = max(candidates, key=lambda item: item[0])
        return {
            "main_problem": main_problem,
            "reason": reason,
            "feedback": feedback,
            "next_action": next_action,
            "worst_segments": worst_segments,
        }

    if absent_sec > 0 and total_seconds > 0 and absent_sec / total_seconds >= 0.15:
        return {
            "main_problem": "자리비움 또는 미검출 증가",
            "reason": f"전체 학습 중 자리비움/미검출 시간이 {_format_duration(absent_sec)}로 비교적 길게 나타났습니다.",
            "feedback": "카메라 밖으로 벗어나거나 얼굴/몸이 잘 감지되지 않는 시간이 점수 하락에 영향을 주었습니다. 실제 이탈인지 카메라 각도 문제인지 확인하는 것이 좋습니다.",
            "next_action": "학습 시작 전 얼굴과 상체가 화면 안에 안정적으로 들어오는지 확인해보세요.",
            "worst_segments": worst_segments,
        }

    return {
        "main_problem": "집중 패턴 안정",
        "reason": f"집중 점수는 {int(round(focus_score))}점이며, 특정 방해 요인이 두드러지게 반복되지는 않았습니다.",
        "feedback": "현재 학습 패턴을 유지하되, 장시간 학습에서는 짧은 휴식을 계획적으로 넣으면 집중 저하를 예방할 수 있습니다.",
        "next_action": "25~30분마다 1분 정도 시선과 자세를 점검해보세요.",
        "worst_segments": worst_segments[:1],
    }


def _events_summary(events: Any) -> dict[str, dict[str, int]]:
    if not isinstance(events, list):
        return {}

    summary: dict[str, dict[str, int]] = {}
    for event in events:
        if not isinstance(event, dict):
            continue
        event_type = str(event.get("type") or event.get("event_type") or event.get("state") or "unknown")
        row = summary.setdefault(event_type, {"count": 0, "total_sec": 0})
        row["count"] += 1
        row["total_sec"] += _to_int(_to_float(event.get("end_sec", event.get("end_time"))) - _to_float(event.get("start_sec", event.get("start_time"))))
    return summary


def _api_payload(analysis_result: dict[str, Any], rule_feedback: dict[str, Any]) -> dict[str, Any]:
    summary = analysis_result.get("summary") if isinstance(analysis_result.get("summary"), dict) else {}
    total_seconds = _get_total_seconds(analysis_result, summary)
    segments = _segments_from_result(analysis_result, total_seconds)

    selected_summary_keys = (
        "focus_score",
        "concentration_score",
        "focus_total_sec",
        "bad_posture_total_sec",
        "gaze_away_total_sec",
        "gaze_away_count",
        "away_total_sec",
        "away_count",
        "gaze_side_total_sec",
        "gaze_side_count",
        "gaze_down_total_sec",
        "gaze_down_count",
        "drowsy_total_sec",
        "drowsy_count",
        "eye_closed_total_sec",
        "long_eye_closure_count",
        "head_down_total_sec",
        "head_tilt_total_sec",
        "absent_total_sec",
        "absent_count",
    )
    summary_metrics = {
        key: summary.get(key)
        for key in selected_summary_keys
        if key in summary
    }

    return {
        "scores": {
            "focus_score": _focus_score_from_result(analysis_result, summary),
            "concentration_score": _summary_metric(summary, "concentration_score"),
        },
        "total_seconds": _to_int(total_seconds),
        "summary": summary_metrics,
        "segments": [
            {
                "start_sec": _to_int(segment.get("start_sec")),
                "end_sec": _to_int(segment.get("end_sec")),
                "focus_ratio": _to_float(segment.get("focus_ratio")),
                "main_issue": segment.get("main_issue"),
                "dominant_state": segment.get("dominant_state"),
                "state_counts": segment.get("state_counts"),
            }
            for segment in segments[:24]
        ],
        "events_summary": _events_summary(analysis_result.get("events")),
        "rule_feedback": rule_feedback,
    }


def _post_json(url: str, payload: dict[str, Any], api_key: str, timeout_sec: float) -> dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout_sec) as response:
        body = response.read().decode("utf-8")
    parsed = json.loads(body)
    return parsed if isinstance(parsed, dict) else {}


def _extract_json_from_text(text: str) -> Optional[dict[str, Any]]:
    cleaned = text.strip()
    if not cleaned:
        return None

    try:
        parsed = json.loads(cleaned)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end <= start:
        return None

    try:
        parsed = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _response_text(response: dict[str, Any]) -> str:
    output_text = response.get("output_text")
    if isinstance(output_text, str):
        return output_text

    choices = response.get("choices")
    if isinstance(choices, list) and choices:
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        if isinstance(message, dict) and isinstance(message.get("content"), str):
            return message["content"]

    output = response.get("output")
    if isinstance(output, list):
        chunks: list[str] = []
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if not isinstance(part, dict):
                    continue
                text = part.get("text")
                if isinstance(text, str):
                    chunks.append(text)
        return "".join(chunks)

    return ""


def _parse_ai_feedback_response(response: dict[str, Any]) -> Optional[dict[str, Any]]:
    personal_feedback = response.get("personal_feedback")
    if isinstance(personal_feedback, dict):
        return personal_feedback

    if all(key in response for key in ("main_problem", "reason", "feedback", "next_action")):
        return response

    text = _response_text(response)
    if text:
        parsed = _extract_json_from_text(text)
        if isinstance(parsed, dict):
            if isinstance(parsed.get("personal_feedback"), dict):
                return parsed["personal_feedback"]
            return parsed

    return None


def _ai_timeout_sec() -> float:
    timeout = _to_float(os.getenv("AI_FEEDBACK_TIMEOUT_SEC"))
    return timeout if timeout > 0 else 8.0


def _api_disabled() -> bool:
    return str(os.getenv("AI_FEEDBACK_DISABLE_API", "")).strip().lower() in {"1", "true", "yes", "on"}


def _call_ai_feedback(analysis_result: dict[str, Any], rule_feedback: dict[str, Any]) -> Optional[dict[str, Any]]:
    if _api_disabled():
        return None

    api_key = (os.getenv("OPENAI_API_KEY") or os.getenv("AI_API_KEY") or "").strip()
    if not api_key:
        return None

    timeout_sec = _ai_timeout_sec()
    payload = _api_payload(analysis_result, rule_feedback)
    external_url = (os.getenv("AI_FEEDBACK_API_URL") or os.getenv("AI_API_URL") or "").strip()

    if external_url:
        response = _post_json(external_url, payload, api_key, timeout_sec)
        return _parse_ai_feedback_response(response)

    model = (
        os.getenv("OPENAI_FEEDBACK_MODEL")
        or os.getenv("OPENAI_MODEL")
        or "gpt-5.5"
    ).strip()
    openai_payload = {
        "model": model,
        "instructions": (
            "You are refining Korean study-focus feedback. Return only JSON with keys "
            "main_problem, reason, feedback, next_action, worst_segments. "
            "Use the provided numeric metrics and segment data only. Do not invent video details, "
            "personal data, diagnoses, or exact causes that are not supported by the JSON."
        ),
        "input": json.dumps(payload, ensure_ascii=False),
        "text": {"format": {"type": "json_object"}},
        "store": False,
    }
    response = _post_json(
        "https://api.openai.com/v1/responses",
        openai_payload,
        api_key,
        timeout_sec,
    )
    return _parse_ai_feedback_response(response)


def _merge_ai_feedback(rule_feedback: dict[str, Any], ai_feedback: Optional[dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(ai_feedback, dict):
        return rule_feedback

    merged = dict(rule_feedback)
    for key in ("main_problem", "reason", "feedback", "next_action"):
        value = ai_feedback.get(key)
        if isinstance(value, str) and value.strip():
            merged[key] = value.strip()

    rule_segments = rule_feedback.get("worst_segments")
    ai_segments = ai_feedback.get("worst_segments")
    if isinstance(rule_segments, list) and isinstance(ai_segments, list):
        merged_segments: list[dict[str, Any]] = []
        for index, rule_segment in enumerate(rule_segments[:3]):
            if not isinstance(rule_segment, dict):
                continue
            segment = dict(rule_segment)
            if index < len(ai_segments) and isinstance(ai_segments[index], dict):
                for key in ("problem", "feedback"):
                    value = ai_segments[index].get(key)
                    if isinstance(value, str) and value.strip():
                        segment[key] = value.strip()
            merged_segments.append(segment)
        merged["worst_segments"] = merged_segments
    elif isinstance(rule_segments, list):
        merged["worst_segments"] = rule_segments[:3]
    else:
        merged["worst_segments"] = []

    return merged


def generate_personal_feedback(analysis_result: dict[str, Any]) -> dict[str, Any]:
    """Build personal study feedback from analysis JSON, with AI text refinement fallback."""

    return generate_personal_feedback_payload(analysis_result)["personal_feedback"]


def generate_personal_feedback_payload(analysis_result: dict[str, Any]) -> dict[str, Any]:
    """Build personal feedback plus metadata for DB/API persistence."""

    if not isinstance(analysis_result, dict):
        analysis_result = {}

    rule_feedback = _rule_based_personal_feedback(analysis_result)
    api_key = (os.getenv("OPENAI_API_KEY") or os.getenv("AI_API_KEY") or "").strip()
    api_available = bool(api_key) and not _api_disabled()

    try:
        ai_feedback = _call_ai_feedback(analysis_result, rule_feedback)
    except (OSError, TimeoutError, urllib.error.URLError, json.JSONDecodeError, ValueError):
        ai_feedback = None
    except Exception:
        ai_feedback = None

    source = "ai_api" if ai_feedback else ("fallback" if api_available else "rule_based")
    return {
        "personal_feedback": _merge_ai_feedback(rule_feedback, ai_feedback),
        "feedback_source": source,
        "feedback_version": FEEDBACK_VERSION,
    }
