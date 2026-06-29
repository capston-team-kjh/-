
from __future__ import annotations

import csv
import json
import os
import time
import argparse
import statistics
import tempfile
import shutil
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import pymysql
import cv2
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

try:
    from .predict_state_model import load_state_classifier, predict_state_proba
except ImportError:
    from predict_state_model import load_state_classifier, predict_state_proba

try:
    from analyzer.focus_score import calculate_focus_score
except ImportError:
    import sys
    from pathlib import Path

    _AI_DIR = Path(__file__).resolve().parents[1]
    if str(_AI_DIR) not in sys.path:
        sys.path.insert(0, str(_AI_DIR))
    from analyzer.focus_score import calculate_focus_score

try:
    from .feedback_generator import build_feedback_evidence, generate_feedback, generate_personal_feedback_payload
except ImportError:
    from feedback_generator import build_feedback_evidence, generate_feedback, generate_personal_feedback_payload


_RULE_ONLY_STATE_DECISION_SOURCES = {
    "absent": "rule_absent",
    "bad_posture": "rule_bad_posture",
}
_RULE_ONLY_STATES = set(_RULE_ONLY_STATE_DECISION_SOURCES.keys())
_STATE_EVENT_SCORES = {
    "absent": 1.0,
    "sleep_suspect": 0.9,
    "drowsy": 0.9,
    "gaze_side": 0.7,
    "gaze_down": 0.5,
    "bad_posture": 0.3,
    "present_unknown": 0.0,
    "unknown": 0.0,
}
_RECENT_DROWSY_CONTEXT_FLAGS = {
    "head_down",
    "drowsy",
    "raw_drowsy",
    "eye_closed",
    "long_eye_closure",
    "gaze_down",
    "sleep_suspect",
}
_OVERHEAD_ACTIVITY_FLAGS = {
    "page_turn",
    "pen_fidget",
    "restless_hand",
}
_OVERHEAD_PERSON_TRACE_FLAGS = {
    "pose_seen",
    "hand_seen",
    "face_seen",
    "bad_posture",
    "head_down",
    "head_tilt",
}
_OVERHEAD_ACTIVITY_PATH_THRESHOLD = 0.03
_OVERHEAD_ACTIVITY_DISPLACEMENT_THRESHOLD = 0.02
_OVERHEAD_ACTIVITY_BBOX_THRESHOLD = 0.02


@dataclass
class AnalyzeConfig:
    sampling_fps: int = 1
    absent_threshold_sec: int = 5
    min_face_confidence: float = 0.5

    # 고개 기반 좌우 이탈 보조 판단
    away_ratio_threshold: float = 0.35

    # 자세 불량
    enable_bad_posture: bool = True
    posture_shoulder_threshold: float = 0.12
    posture_tilt_threshold: float = 0.18

    # 시선 판정
    gaze_side_left_threshold: float = 0.35
    gaze_side_right_threshold: float = 0.65
    gaze_down_threshold: float = 0.62

    # 손 행동
    enable_hand_actions: bool = True
    hand_min_visibility: float = 0.5

    page_turn_min_duration_sec: int = 1
    page_turn_min_path_len: float = 0.18
    page_turn_min_net_disp: float = 0.14
    page_turn_max_dir_changes: int = 2
    page_turn_min_x_span: float = 0.12
    page_turn_max_y_span: float = 0.10

    pen_fidget_min_duration_sec: int = 2
    pen_fidget_min_path_len: float = 0.18
    pen_fidget_max_bbox_diag: float = 0.12
    pen_fidget_min_dir_changes: int = 3

    restless_hand_min_duration_sec: int = 2
    restless_hand_min_path_len: float = 0.28
    restless_hand_min_bbox_diag: float = 0.18
    restless_hand_min_dir_changes: int = 2

    # 졸음 판정
    enable_drowsy: bool = True
    drowsy_ear_threshold: float = 0.16
    drowsy_head_drop_threshold: float = 0.75
    drowsy_head_tilt_threshold: float = 0.12
    drowsy_min_duration_sec: int = 10

    # baseline / 보정
    baseline_duration_sec: int = 30
    ear_baseline_ratio: float = 0.58
    ear_reopen_baseline_ratio: float = 0.72
    drowsy_ear_reopen_threshold: float = 0.20
    face_head_down_threshold: float = 0.72
    face_head_down_offset: float = 0.10
    pose_head_drop_margin: float = 0.10

    # blink / long eye closure
    blink_max_duration_sec: int = 1
    long_eye_closure_min_sec: int = 10
    drowsy_head_motion_window_sec: int = 3
    drowsy_head_motion_threshold: float = 0.035
    drowsy_activity_window_sec: int = 3

    # 상태 최소 지속 시간(초)
    gaze_side_min_duration_sec: int = 2
    gaze_down_min_duration_sec: int = 2
    bad_posture_min_duration_sec: int = 2
    enable_unknown_state: bool = True

    use_trained_classifier: bool = True
    classifier_model_path: str = "ai/models/state_classifier.pkl"
    classifier_confidence_threshold: float = 0.65

    version: str = "ai-0.2.5"


def _unique_keep_order(items: List[str]) -> List[str]:
    seen = set()
    result: List[str] = []

    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)

    return result


def _ensure_states_list(item: Dict[str, Any]) -> List[str]:
    states = item.get("states")
    if isinstance(states, list) and states:
        return [str(s) for s in states if s]
    state = item.get("state", "focus")
    return [state] if state else ["focus"]


def _state_label_ko(state: Optional[str]) -> str:
    labels = {
        "absent": "자리 이탈",
        "sleep_suspect": "수면 의심",
        "bad_posture": "자세 불량",
        "drowsy": "졸음",
        "gaze_down": "아래 시선",
        "gaze_side": "시선 이탈",
        "gaze_away": "시선 이탈",
        "page_turn": "페이지 넘김",
        "pen_fidget": "필기구 만지작거림",
        "restless_hand": "손 움직임",
        "unknown": "인식 불안정",
    }
    return labels.get(str(state), str(state)) if state else "문제 행동"


def _empty_time_patterns(interval_sec: int) -> Dict[str, Any]:
    return {
        "interval_sec": int(interval_sec),
        "segments": [],
        "best_segment": None,
        "worst_segment": None,
        "insights": ["시간대별 분석을 수행할 수 없습니다."],
    }


def _format_minute_range(start_sec: int, end_sec: int) -> str:
    start_min = start_sec // 60
    end_min = end_sec // 60
    return f"{start_min}~{end_min}분"


def build_time_patterns(
    timeline: List[Dict[str, Any]],
    interval_sec: int = 300,
    duration_sec: Optional[int] = None,
) -> Dict[str, Any]:
    if interval_sec <= 0 or not timeline:
        return _empty_time_patterns(interval_sec)

    grouped: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    max_seen_sec = 0

    for item in timeline:
        try:
            t = int(float(item.get("t", 0)))
        except (TypeError, ValueError):
            continue

        if t < 0:
            continue

        grouped[(t // interval_sec) * interval_sec].append(item)
        max_seen_sec = max(max_seen_sec, t)

    if not grouped:
        return _empty_time_patterns(interval_sec)

    try:
        effective_duration = int(duration_sec) if duration_sec is not None else None
    except (TypeError, ValueError):
        effective_duration = None

    if effective_duration is None or effective_duration <= 0:
        effective_duration = max_seen_sec + 1

    segments: List[Dict[str, Any]] = []

    for start_sec in range(0, effective_duration, interval_sec):
        rows = grouped.get(start_sec, [])
        if not rows:
            continue

        state_counts: Counter[str] = Counter()
        primary_counts: Counter[str] = Counter()

        for row in rows:
            states = _ensure_states_list(row)
            state_counts.update(states)
            primary_counts.update([str(row.get("state") or states[0] or "focus")])

        total_count = len(rows)
        focus_count = int(state_counts.get("focus", 0))
        focus_ratio = (focus_count / total_count) if total_count > 0 else 0.0
        dominant_state = primary_counts.most_common(1)[0][0] if primary_counts else None
        issue_counts = Counter({state: count for state, count in state_counts.items() if state != "focus"})
        main_issue = issue_counts.most_common(1)[0][0] if issue_counts else None

        if focus_ratio >= 0.8:
            risk_level = "good"
        elif focus_ratio >= 0.6:
            risk_level = "warning"
        else:
            risk_level = "risk"

        segments.append(
            {
                "start_sec": int(start_sec),
                "end_sec": int(min(start_sec + interval_sec, effective_duration)),
                "total_count": int(total_count),
                "state_counts": dict(state_counts),
                "focus_ratio": round(float(focus_ratio), 3),
                "dominant_state": dominant_state,
                "main_issue": main_issue,
                "risk_level": risk_level,
            }
        )

    if not segments:
        return _empty_time_patterns(interval_sec)

    best = max(segments, key=lambda segment: segment["focus_ratio"])
    worst = min(segments, key=lambda segment: segment["focus_ratio"])
    best_segment = {
        "start_sec": best["start_sec"],
        "end_sec": best["end_sec"],
        "focus_ratio": best["focus_ratio"],
    }
    worst_segment = {
        "start_sec": worst["start_sec"],
        "end_sec": worst["end_sec"],
        "focus_ratio": worst["focus_ratio"],
    }

    worst_range = _format_minute_range(worst["start_sec"], worst["end_sec"])
    insights = [f"학습 시작 후 {worst_range} 구간에서 집중률이 가장 낮았습니다."]
    if worst.get("main_issue"):
        insights.append(f"해당 구간에서는 {_state_label_ko(worst['main_issue'])}이 가장 많이 발생했습니다.")

    return {
        "interval_sec": int(interval_sec),
        "segments": segments,
        "best_segment": best_segment,
        "worst_segment": worst_segment,
        "insights": insights,
    }


def _with_time_patterns(result: Dict[str, Any]) -> Dict[str, Any]:
    result["time_patterns"] = build_time_patterns(
        timeline=result.get("timeline", []),
        interval_sec=300,
        duration_sec=result.get("meta", {}).get("duration_sec"),
    )
    return result


def _finalize_analysis_result(result: Dict[str, Any]) -> Dict[str, Any]:
    if result.get("status") != "success":
        return _with_time_patterns(result)

    meta = result.get("meta")
    if not isinstance(meta, dict):
        meta = {}
        result["meta"] = meta

    summary = result.get("summary")
    if not isinstance(summary, dict):
        summary = {}

    summary = calculate_focus_score(summary, meta.get("duration_sec"))
    score_warnings = summary.pop("warnings", [])
    if score_warnings:
        meta_warnings = meta.get("warnings")
        if not isinstance(meta_warnings, list):
            meta_warnings = [] if meta_warnings in (None, "") else [str(meta_warnings)]
            meta["warnings"] = meta_warnings

        for warning in score_warnings:
            if warning not in meta_warnings:
                meta_warnings.append(warning)

    summary["concentration_score"] = float(summary.get("focus_score", 0))
    result["summary"] = summary
    result["time_patterns"] = build_time_patterns(
        timeline=result.get("timeline", []),
        interval_sec=300,
        duration_sec=meta.get("duration_sec"),
    )
    result["feedback"] = generate_feedback(summary, result["time_patterns"])
    result["feedback_evidence"] = build_feedback_evidence(
        summary,
        result["time_patterns"],
        result.get("events", []),
        result.get("timeline", []),
    )
    feedback_payload = generate_personal_feedback_payload(result)
    result["personal_feedback"] = feedback_payload["personal_feedback"]
    result["feedback_source"] = feedback_payload["feedback_source"]
    result["feedback_version"] = feedback_payload["feedback_version"]

    return result


def _build_active_states_for_sec(
    t: int,
    primary_state: str,
    gaze_side_seen_by_sec: List[bool],
    gaze_down_seen_by_sec: List[bool],
    bad_posture_seen_by_sec: List[bool],
    drowsy_seen_by_sec: List[bool],
    page_turn_seen_by_sec: List[bool],
    pen_fidget_seen_by_sec: List[bool],
    restless_hand_seen_by_sec: List[bool],
) -> List[str]:
    active: List[str] = []

    if primary_state == "absent":
        return ["absent"]

    if primary_state == "unknown":
        active.append("unknown")

    if drowsy_seen_by_sec[t]:
        active.append("drowsy")
    if gaze_side_seen_by_sec[t]:
        active.append("gaze_side")
    if gaze_down_seen_by_sec[t]:
        active.append("gaze_down")
    if bad_posture_seen_by_sec[t]:
        active.append("bad_posture")
    if page_turn_seen_by_sec[t]:
        active.append("page_turn")
    if pen_fidget_seen_by_sec[t]:
        active.append("pen_fidget")
    if restless_hand_seen_by_sec[t]:
        active.append("restless_hand")

    if primary_state != "focus" and primary_state not in active:
        active.append(primary_state)

    if not active:
        active.append("focus")

    return _unique_keep_order(active)


def get_db_connection():
    return pymysql.connect(
        host="127.0.0.1",
        user="root",
        password="1234",
        database="joljak_db",
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
    )


def save_analysis_to_db(session_id: str, result: Dict[str, Any]) -> None:
    if result.get("status") != "success":
        print("분석 실패 상태라 DB 저장 생략")
        return

    summary = result.get("summary", {})
    meta = result.get("meta", {})
    timeline = result.get("timeline", [])
    events = result.get("events", [])
    feedback = result.get("feedback") if isinstance(result.get("feedback"), dict) else {}
    personal_feedback = result.get("personal_feedback") if isinstance(result.get("personal_feedback"), dict) else None
    personal_feedback_json = json.dumps(personal_feedback, ensure_ascii=False) if personal_feedback else None
    feedback_text = "\n".join(
        str(feedback.get(key)).strip()
        for key in ("summary_text", "weak_point", "recommendation")
        if feedback.get(key)
    )

    conn = get_db_connection()

    try:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM analysis_timeline WHERE session_id = %s", (session_id,))
            cursor.execute("DELETE FROM analysis_events WHERE session_id = %s", (session_id,))
            cursor.execute("DELETE FROM analysis_summary WHERE session_id = %s", (session_id,))

            cursor.execute(
                """
                INSERT INTO analysis_summary (
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
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    session_id,
                    summary.get("focus_ratio", 0),
                    summary.get("absent_count", 0),
                    summary.get("absent_total_sec", 0),
                    summary.get("away_count", 0),
                    summary.get("away_total_sec", 0),
                    summary.get("bad_posture_ratio", 0),
                    meta.get("processing_time_sec", 0),
                    meta.get("camera_type", "merged"),
                    meta.get("version", ""),
                ),
            )

            if timeline:
                timeline_values = []

                for row in timeline:
                    t = row.get("t", 0)
                    states = _ensure_states_list(row)

                    for state_name in states:
                        timeline_values.append(
                            (
                                session_id,
                                t,
                                state_name,
                            )
                        )

                cursor.executemany(
                    """
                    INSERT INTO analysis_timeline (session_id, t, state)
                    VALUES (%s, %s, %s)
                    """,
                    timeline_values,
                )

            if events:
                event_values = [
                    (
                        session_id,
                        row.get("type", "unknown"),
                        row.get("start_sec", 0),
                        row.get("end_sec", 0),
                        row.get("score", 0),
                    )
                    for row in events
                ]

                cursor.executemany(
                    """
                    INSERT INTO analysis_events (
                        session_id, event_type, start_sec, end_sec, score
                    ) VALUES (%s, %s, %s, %s, %s)
                    """,
                    event_values,
                )

            cursor.execute(
                """
                INSERT INTO analysis_feedback (
                    session_id,
                    feedback_text,
                    personal_feedback,
                    feedback_source,
                    feedback_version,
                    feedback_created_at
                ) VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                ON DUPLICATE KEY UPDATE
                    feedback_text = VALUES(feedback_text),
                    personal_feedback = VALUES(personal_feedback),
                    feedback_source = VALUES(feedback_source),
                    feedback_version = VALUES(feedback_version),
                    feedback_created_at = VALUES(feedback_created_at),
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    session_id,
                    feedback_text,
                    personal_feedback_json,
                    result.get("feedback_source", "rule_based"),
                    result.get("feedback_version", "feedback-v1"),
                ),
            )

        conn.commit()
        print(f"{session_id} 분석 결과 DB 저장 완료")

    except Exception as e:
        conn.rollback()
        print("DB 저장 실패:", e)
        raise

    finally:
        conn.close()


def _read_video_meta(video_path: str) -> Dict[str, Any]:
    if not os.path.exists(video_path):
        return {
            "ok": False,
            "reason": "VIDEO_NOT_FOUND",
            "video_fps": None,
            "frame_count": None,
            "duration_sec": None,
        }

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return {
            "ok": False,
            "reason": "VIDEO_OPEN_FAIL",
            "video_fps": None,
            "frame_count": None,
            "duration_sec": None,
        }

    fps = cap.get(cv2.CAP_PROP_FPS)
    frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    cap.release()

    if fps is None or fps <= 0 or frame_count is None or frame_count <= 0:
        return {
            "ok": False,
            "reason": "VIDEO_META_INVALID",
            "video_fps": float(fps) if fps else None,
            "frame_count": int(frame_count) if frame_count else None,
            "duration_sec": None,
        }

    duration_sec = frame_count / fps
    return {
        "ok": True,
        "reason": None,
        "video_fps": float(fps),
        "frame_count": int(frame_count),
        "duration_sec": int(duration_sec),
    }


def _fps_from_decoded_timing(
    decoded_frame_count: int,
    first_timestamp_ms: Optional[float],
    last_timestamp_ms: Optional[float],
    reported_fps: float,
    reported_frame_count: float,
) -> float:
    """Return the playback FPS represented by decoded frame timestamps.

    Browser-recorded WebM files can report a nominal 60 FPS even when their
    timestamps contain about 10 frames per second. Re-encoding those decoded
    frames at the nominal rate shortens the video. Prefer timestamps, then use
    the container duration as a fallback.
    """
    if (
        decoded_frame_count > 1
        and first_timestamp_ms is not None
        and last_timestamp_ms is not None
        and last_timestamp_ms > first_timestamp_ms
    ):
        timestamp_fps = (
            (decoded_frame_count - 1) * 1000.0
            / (last_timestamp_ms - first_timestamp_ms)
        )
        if 0.1 <= timestamp_fps <= 240.0:
            return float(timestamp_fps)

    if reported_fps > 0 and reported_frame_count > 0 and decoded_frame_count > 0:
        reported_duration_sec = reported_frame_count / reported_fps
        if reported_duration_sec > 0:
            decoded_fps = decoded_frame_count / reported_duration_sec
            if 0.1 <= decoded_fps <= 240.0:
                return float(decoded_fps)

    return float(reported_fps if reported_fps > 0 else 30.0)


def _measure_decoded_video_timing(
    video_path: str,
    reported_fps: float,
    reported_frame_count: float,
) -> Dict[str, Any]:
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return {
            "decoded_frame_count": 0,
            "effective_fps": float(reported_fps),
            "first_timestamp_ms": None,
            "last_timestamp_ms": None,
        }

    decoded_frame_count = 0
    first_timestamp_ms: Optional[float] = None
    last_timestamp_ms: Optional[float] = None

    try:
        while True:
            ret, _ = cap.read()
            if not ret:
                break

            timestamp_ms = float(cap.get(cv2.CAP_PROP_POS_MSEC))
            if timestamp_ms >= 0:
                if first_timestamp_ms is None:
                    first_timestamp_ms = timestamp_ms
                last_timestamp_ms = timestamp_ms
            decoded_frame_count += 1
    finally:
        cap.release()

    effective_fps = _fps_from_decoded_timing(
        decoded_frame_count,
        first_timestamp_ms,
        last_timestamp_ms,
        reported_fps,
        reported_frame_count,
    )
    return {
        "decoded_frame_count": decoded_frame_count,
        "effective_fps": effective_fps,
        "first_timestamp_ms": first_timestamp_ms,
        "last_timestamp_ms": last_timestamp_ms,
    }


def _face_seen_seconds(result: Dict[str, Any]) -> int:
    return sum(
        1
        for item in result.get("timeline", [])
        if bool(item.get("flags", {}).get("face_seen", False))
    )


def _detect_camera_role_assignment(
    left_result: Dict[str, Any],
    right_result: Dict[str, Any],
) -> Dict[str, Any]:
    """Detect a reversed merged-camera layout using strong face evidence only."""
    left_face_seen_sec = _face_seen_seconds(left_result)
    right_face_seen_sec = _face_seen_seconds(right_result)
    duration_sec = max(
        int(left_result.get("meta", {}).get("duration_sec", 0) or 0),
        int(right_result.get("meta", {}).get("duration_sec", 0) or 0),
    )

    minimum_face_sec = max(2, min(10, int(round(duration_sec * 0.02))))
    minimum_margin_sec = max(2, min(30, int(round(duration_sec * 0.05))))

    dominant_side: Optional[str] = None
    if (
        left_face_seen_sec >= minimum_face_sec
        and left_face_seen_sec - right_face_seen_sec >= minimum_margin_sec
        and left_face_seen_sec >= max(1, right_face_seen_sec) * 2
    ):
        dominant_side = "left"
    elif (
        right_face_seen_sec >= minimum_face_sec
        and right_face_seen_sec - left_face_seen_sec >= minimum_margin_sec
        and right_face_seen_sec >= max(1, left_face_seen_sec) * 2
    ):
        dominant_side = "right"

    return {
        "method": "face_seen_duration",
        "confident": dominant_side is not None,
        "swapped": dominant_side == "right",
        "face_camera_side": dominant_side or "left",
        "left_face_seen_sec": left_face_seen_sec,
        "right_face_seen_sec": right_face_seen_sec,
        "minimum_face_sec": minimum_face_sec,
        "minimum_margin_sec": minimum_margin_sec,
    }


def analyze_merged_video(
    session_id: str,
    video_path: str,
    config: AnalyzeConfig,
) -> Dict[str, Any]:
    started = time.time()
    temp_dir = tempfile.mkdtemp(prefix="merged_split_")

    left_path = os.path.join(temp_dir, f"{session_id}_front.mp4")
    right_path = os.path.join(temp_dir, f"{session_id}_overhead.mp4")

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        shutil.rmtree(temp_dir, ignore_errors=True)
        return _with_time_patterns({
            "session_id": session_id,
            "status": "failed",
            "meta": {
                "video_path": video_path,
                "processing_time_sec": int(time.time() - started),
                "version": config.version,
                "fail_reason": "VIDEO_OPEN_FAIL",
            },
            "summary": {},
            "timeline": [],
            "events": [],
        })

    reported_fps = cap.get(cv2.CAP_PROP_FPS)
    if reported_fps is None or reported_fps <= 0:
        reported_fps = 30.0
    reported_frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)

    decoded_timing = _measure_decoded_video_timing(
        video_path,
        float(reported_fps),
        float(reported_frame_count or 0.0),
    )
    fps = float(decoded_timing["effective_fps"])
    timing_warnings = []
    if abs(fps - float(reported_fps)) / float(reported_fps) >= 0.05:
        timing_warnings.append("SOURCE_FPS_NORMALIZED")

    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    if width < 2 or height < 2:
        cap.release()
        shutil.rmtree(temp_dir, ignore_errors=True)
        return _with_time_patterns({
            "session_id": session_id,
            "status": "failed",
            "meta": {
                "video_path": video_path,
                "processing_time_sec": int(time.time() - started),
                "version": config.version,
                "fail_reason": "VIDEO_META_INVALID",
            },
            "summary": {},
            "timeline": [],
            "events": [],
        })

    split_x = width // 2
    left_width = split_x
    right_width = width - split_x

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    left_writer = cv2.VideoWriter(left_path, fourcc, fps, (left_width, height))
    right_writer = cv2.VideoWriter(right_path, fourcc, fps, (right_width, height))

    if not left_writer.isOpened() or not right_writer.isOpened():
        cap.release()
        left_writer.release()
        right_writer.release()
        shutil.rmtree(temp_dir, ignore_errors=True)
        return _with_time_patterns({
            "session_id": session_id,
            "status": "failed",
            "meta": {
                "video_path": video_path,
                "processing_time_sec": int(time.time() - started),
                "version": config.version,
                "fail_reason": "VIDEO_WRITER_OPEN_FAIL",
            },
            "summary": {},
            "timeline": [],
            "events": [],
        })

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            left_frame = frame[:, :split_x]
            right_frame = frame[:, split_x:]

            left_writer.write(left_frame)
            right_writer.write(right_frame)

    finally:
        cap.release()
        left_writer.release()
        right_writer.release()

    front_result = analyze_absent(session_id, left_path, "front", config)
    overhead_result = analyze_absent(session_id, right_path, "overhead", config)

    if front_result.get("status") != "success" or overhead_result.get("status") != "success":
        result = {
            "session_id": session_id,
            "status": "failed",
            "meta": {
                "video_path": video_path,
                "processing_time_sec": int(time.time() - started),
                "version": config.version,
                "fail_reason": "SUB_ANALYSIS_FAILED",
            },
            "summary": {},
            "timeline": [],
            "events": [],
            "front_result": front_result,
            "overhead_result": overhead_result,
        }
        shutil.rmtree(temp_dir, ignore_errors=True)
        return _with_time_patterns(result)

    camera_role_detection = _detect_camera_role_assignment(front_result, overhead_result)
    if camera_role_detection["swapped"]:
        front_result = analyze_absent(session_id, right_path, "front", config)
        overhead_result = analyze_absent(session_id, left_path, "overhead", config)

        if front_result.get("status") != "success" or overhead_result.get("status") != "success":
            result = {
                "session_id": session_id,
                "status": "failed",
                "meta": {
                    "video_path": video_path,
                    "processing_time_sec": int(time.time() - started),
                    "version": config.version,
                    "fail_reason": "AUTO_CAMERA_ROLE_SUB_ANALYSIS_FAILED",
                    "camera_role_detection": camera_role_detection,
                },
                "summary": {},
                "timeline": [],
                "events": [],
                "front_result": front_result,
                "overhead_result": overhead_result,
            }
            shutil.rmtree(temp_dir, ignore_errors=True)
            return _with_time_patterns(result)

        timing_warnings.append("CAMERA_ROLES_AUTO_SWAPPED")
    elif not camera_role_detection["confident"]:
        timing_warnings.append("CAMERA_ROLE_AMBIGUOUS_USING_DEFAULT")

    front_timeline = {item["t"]: item for item in front_result.get("timeline", [])}
    overhead_timeline = {item["t"]: item for item in overhead_result.get("timeline", [])}

    duration_sec = max(
        int(front_result.get("meta", {}).get("duration_sec", 0)),
        int(overhead_result.get("meta", {}).get("duration_sec", 0)),
    )

    overhead_activity_by_sec = [
        has_overhead_activity(overhead_timeline.get(t))
        for t in range(duration_sec)
    ]

    def _has_nearby_overhead_activity(t: int) -> bool:
        window = max(0, int(config.drowsy_activity_window_sec))
        start = max(0, t - window)
        end = min(duration_sec, t + window + 1)
        return any(overhead_activity_by_sec[start:end])

    final_timeline = []
    for t in range(duration_sec):
        front_item = front_timeline.get(t, {"state": "focus", "states": ["focus"], "flags": {}})
        overhead_available = t in overhead_timeline
        overhead_item = overhead_timeline.get(t, {"state": "focus", "states": ["focus"], "flags": {}})

        front_state = front_item.get("state", "focus")
        front_states = _ensure_states_list(front_item)

        front_flags = front_item.get("flags", {})
        overhead_flags = overhead_item.get("flags", {})
        absence_resolution = {
            "state": front_state,
            "missing_face_state": front_state,
            "sleep_suspect": False,
            "overhead_activity": False,
            "overhead_person_trace": False,
        }
        drowsy_suppressed_by_activity = False

        if front_state == "absent":
            absence_resolution = resolve_front_absence_with_overhead(
                t=t,
                front_item=front_item,
                overhead_item=overhead_item if overhead_available else None,
                front_timeline=front_timeline,
                overhead_available=overhead_available,
            )
            final_state = absence_resolution["state"]
        elif front_state == "drowsy":
            drowsy_suppressed_by_activity = _has_nearby_overhead_activity(t)
            if drowsy_suppressed_by_activity:
                final_state = "bad_posture" if front_flags.get("head_down", False) else "focus"
            else:
                final_state = "drowsy"
        elif front_state == "gaze_side":
            final_state = "gaze_side"
        elif front_state == "gaze_down":
            final_state = "gaze_down"
        elif front_state == "bad_posture":
            final_state = "bad_posture"
        elif front_state == "unknown":
            final_state = "unknown"
        else:
            final_state = "focus"

        if "absent" in front_states:
            merged_states = [final_state]
        else:
            merged_states: List[str] = []

            non_focus_front_states = [s for s in front_states if s not in {"focus", "absent"}]
            if non_focus_front_states:
                merged_states.extend(non_focus_front_states)
            else:
                merged_states.append("focus")

            if overhead_flags.get("page_turn", False):
                merged_states.append("page_turn")
            if overhead_flags.get("pen_fidget", False):
                merged_states.append("pen_fidget")
            if overhead_flags.get("restless_hand", False):
                merged_states.append("restless_hand")

            merged_states = _unique_keep_order(merged_states)

        if drowsy_suppressed_by_activity:
            merged_states = [state for state in merged_states if state != "drowsy"]
            if final_state != "focus":
                merged_states.append(final_state)

        if final_state != "absent":
            if overhead_flags.get("page_turn", False):
                merged_states.append("page_turn")
            if overhead_flags.get("pen_fidget", False):
                merged_states.append("pen_fidget")
            if overhead_flags.get("restless_hand", False):
                merged_states.append("restless_hand")

        merged_states = _unique_keep_order(merged_states)
        sleep_suspect = bool(absence_resolution.get("sleep_suspect", False))
        decision_source = front_item.get("decision_source", "rule")
        if front_state == "absent" and final_state != "absent":
            decision_source = "rule_absence_resolved"
        elif drowsy_suppressed_by_activity:
            decision_source = "rule_drowsy_suppressed_by_activity"

        drowsy_evidence = dict(front_item.get("drowsy_evidence") or {})
        drowsy_evidence.update(
            {
                "overhead_activity_nearby": _has_nearby_overhead_activity(t),
                "low_hand_page_activity": not _has_nearby_overhead_activity(t),
                "activity_window_sec": int(config.drowsy_activity_window_sec),
                "suppressed_by_activity": drowsy_suppressed_by_activity,
            }
        )

        final_timeline.append(
            {
                "t": t,
                "state": final_state,
                "model_state": front_item.get("model_state") or overhead_item.get("model_state"),
                "model_confidence": front_item.get("model_confidence") or overhead_item.get("model_confidence"),
                "rule_state": front_item.get("rule_state", front_state),
                "decision_source": decision_source,
                "states": merged_states,
                "flags": {
                    "face_seen": front_flags.get("face_seen", False),
                    "gaze_side": front_flags.get("gaze_side", False),
                    "gaze_down": front_flags.get("gaze_down", False),
                    "bad_posture": front_flags.get("bad_posture", False),
                    "eye_closed": front_flags.get("eye_closed", False),
                    "blink": front_flags.get("blink", False),
                    "long_eye_closure": front_flags.get("long_eye_closure", False),
                    "head_down": front_flags.get("head_down", False),
                    "head_tilt": front_flags.get("head_tilt", False),
                    "raw_drowsy": front_flags.get("raw_drowsy", False) or sleep_suspect,
                    "drowsy": final_state == "drowsy" or sleep_suspect,
                    "page_turn": overhead_flags.get("page_turn", False),
                    "pen_fidget": overhead_flags.get("pen_fidget", False),
                    "restless_hand": overhead_flags.get("restless_hand", False),
                    "unknown": final_state == "unknown",
                    "absent": final_state == "absent",
                    "sleep_suspect": sleep_suspect,
                    "missing_face_resolved": front_state == "absent" and final_state != "absent",
                    "overhead_activity": bool(absence_resolution.get("overhead_activity", False)),
                    "overhead_person_trace": bool(absence_resolution.get("overhead_person_trace", False)),
                },
                "drowsy_evidence": drowsy_evidence,
            }
        )

    def _count_state(state_name: str) -> tuple[int, int]:
        flags = [item["state"] == state_name for item in final_timeline]
        return _count_segments(flags)

    def _count_flag(flag_name: str) -> tuple[int, int]:
        flags = [bool(item.get("flags", {}).get(flag_name, False)) for item in final_timeline]
        return _count_segments(flags)

    focus_total_sec = sum(1 for item in final_timeline if item["state"] == "focus")
    focus_ratio = (focus_total_sec / duration_sec) if duration_sec > 0 else 0.0

    gaze_side_count, gaze_side_total_sec = _count_state("gaze_side")
    gaze_down_count, gaze_down_total_sec = _count_state("gaze_down")
    drowsy_count, drowsy_total_sec = _count_state("drowsy")
    absent_count, absent_total_sec = _count_state("absent")
    unknown_count, unknown_total_sec = _count_state("unknown")
    bad_posture_count, bad_posture_total_sec = _count_state("bad_posture")
    sleep_suspect_count, sleep_suspect_total_sec = _count_flag("sleep_suspect")

    front_summary = front_result.get("summary", {})
    overhead_summary = overhead_result.get("summary", {})

    merged_events = []
    final_event_states = [
        "sleep_suspect" if item.get("flags", {}).get("sleep_suspect", False) else item["state"]
        for item in final_timeline
    ]
    for event in _create_events_from_states(final_event_states):
        e = dict(event)
        e["source"] = "final"
        merged_events.append(e)

    for event in overhead_result.get("events", []):
        e = dict(event)
        e["source"] = "overhead"
        if e.get("type") == "absent":
            e["type"] = "overhead_no_activity"
            e["score"] = 0.0
        merged_events.append(e)

    merged_events.sort(key=lambda x: (x.get("start_sec", 0), x.get("end_sec", 0)))

    result = {
        "session_id": session_id,
        "status": "success",
        "meta": {
            "video_path": video_path,
            "split_mode": "left-right",
            "camera_type": "merged",
            "duration_sec": duration_sec,
            "processing_time_sec": int(time.time() - started),
            "version": config.version,
            "warnings": timing_warnings,
            "source_reported_fps": round(float(reported_fps), 4),
            "source_effective_fps": round(float(fps), 4),
            "source_decoded_frames": int(decoded_timing["decoded_frame_count"]),
            "camera_role_detection": camera_role_detection,
            "drowsy_config": front_result.get("meta", {}).get("drowsy_config", {}),
        },
        "summary": {
            "focus_ratio": round(float(focus_ratio), 4),
            "focus_total_sec": int(focus_total_sec),
            "present_total_sec": int(duration_sec - absent_total_sec),
            "gaze_side_count": int(gaze_side_count),
            "gaze_side_total_sec": int(gaze_side_total_sec),
            "gaze_down_count": int(gaze_down_count),
            "gaze_down_total_sec": int(gaze_down_total_sec),
            "drowsy_count": int(drowsy_count),
            "drowsy_total_sec": int(drowsy_total_sec),
            "sleep_suspect_count": int(sleep_suspect_count),
            "sleep_suspect_total_sec": int(sleep_suspect_total_sec),
            "eye_closed_total_sec": int(front_summary.get("eye_closed_total_sec", 0)),
            "blink_count": int(front_summary.get("blink_count", 0)),
            "blink_total_sec": int(front_summary.get("blink_total_sec", 0)),
            "long_eye_closure_count": int(front_summary.get("long_eye_closure_count", 0)),
            "long_eye_closure_total_sec": int(front_summary.get("long_eye_closure_total_sec", 0)),
            "head_down_total_sec": int(front_summary.get("head_down_total_sec", 0)),
            "head_tilt_total_sec": int(front_summary.get("head_tilt_total_sec", 0)),
            "away_count": int(gaze_side_count),
            "away_total_sec": int(gaze_side_total_sec),
            "unknown_count": int(unknown_count),
            "unknown_total_sec": int(unknown_total_sec),
            "absent_count": int(absent_count),
            "absent_total_sec": int(absent_total_sec),
            "bad_posture_ratio": round((bad_posture_total_sec / duration_sec), 4) if duration_sec > 0 else 0.0,
            "bad_posture_count": int(bad_posture_count),
            "bad_posture_total_sec": int(bad_posture_total_sec),
            "concentration_score": float(front_summary.get("concentration_score", 0.0)),
            "page_turn_count": int(overhead_summary.get("page_turn_count", 0)),
            "page_turn_total_sec": int(overhead_summary.get("page_turn_total_sec", 0)),
            "pen_fidget_count": int(overhead_summary.get("pen_fidget_count", 0)),
            "pen_fidget_total_sec": int(overhead_summary.get("pen_fidget_total_sec", 0)),
            "restless_hand_count": int(overhead_summary.get("restless_hand_count", 0)),
            "restless_hand_total_sec": int(overhead_summary.get("restless_hand_total_sec", 0)),
        },
        "timeline": final_timeline,
        "events": merged_events,
        "front_result": front_result,
        "overhead_result": overhead_result,
    }

    shutil.rmtree(temp_dir, ignore_errors=True)
    return _finalize_analysis_result(result)


def analyze_dummy(
    session_id: str,
    video_path: str,
    camera_type: str,
    config: AnalyzeConfig,
) -> Dict[str, Any]:
    started = time.time()
    meta = _read_video_meta(video_path)
    processing_time_sec = int(time.time() - started)

    if not meta["ok"]:
        return _with_time_patterns({
            "session_id": session_id,
            "status": "failed",
            "meta": {
                "camera_type": camera_type,
                "sampling_fps": config.sampling_fps,
                "video_fps": meta["video_fps"],
                "duration_sec": meta["duration_sec"],
                "processed_frames": 0,
                "processing_time_sec": processing_time_sec,
                "version": config.version,
                "warnings": [],
                "fail_reason": meta["reason"],
            },
            "summary": {},
            "timeline": [],
            "events": [],
        })

    duration_sec: int = meta["duration_sec"]
    processed_frames = duration_sec * config.sampling_fps

    timeline = [
        {
            "t": t,
            "state": "focus",
            "model_state": None,
            "model_confidence": None,
            "rule_state": "focus",
            "decision_source": "rule",
            "states": ["focus"],
            "flags": {
                "face_seen": True,
                "gaze_side": False,
                "gaze_down": False,
                "bad_posture": False,
                "eye_closed": False,
                "blink": False,
                "long_eye_closure": False,
                "head_down": False,
                "head_tilt": False,
                "raw_drowsy": False,
                "drowsy": False,
                "page_turn": False,
                "pen_fidget": False,
                "restless_hand": False,
                "unknown": False,
                "absent": False,
            },
        }
        for t in range(duration_sec)
    ]

    return _finalize_analysis_result({
        "session_id": session_id,
        "status": "success",
        "meta": {
            "camera_type": camera_type,
            "sampling_fps": config.sampling_fps,
            "video_fps": meta["video_fps"],
            "duration_sec": duration_sec,
            "processed_frames": processed_frames,
            "processing_time_sec": processing_time_sec,
            "version": config.version,
            "warnings": [],
        },
        "summary": {
            "focus_ratio": 1.0,
            "focus_total_sec": duration_sec,
            "present_total_sec": duration_sec,
            "gaze_side_count": 0,
            "gaze_side_total_sec": 0,
            "gaze_down_count": 0,
            "gaze_down_total_sec": 0,
            "drowsy_count": 0,
            "drowsy_total_sec": 0,
            "eye_closed_total_sec": 0,
            "blink_count": 0,
            "blink_total_sec": 0,
            "long_eye_closure_count": 0,
            "long_eye_closure_total_sec": 0,
            "head_down_total_sec": 0,
            "head_tilt_total_sec": 0,
            "away_count": 0,
            "away_total_sec": 0,
            "unknown_count": 0,
            "unknown_total_sec": 0,
            "absent_count": 0,
            "absent_total_sec": 0,
            "bad_posture_ratio": 0.0,
            "bad_posture_total_sec": 0,
            "concentration_score": 100.0,
        },
        "timeline": timeline,
        "events": [],
    })


def _is_away_from_landmarks(landmarks: List[Any], away_ratio_threshold: float) -> bool:
    if len(landmarks) < 264:
        return False

    nose = landmarks[1]
    left_eye = landmarks[33]
    right_eye = landmarks[263]

    eye_width = abs(right_eye.x - left_eye.x)
    if eye_width < 1e-6:
        return False

    eye_mid_x = (left_eye.x + right_eye.x) / 2.0
    nose_offset_ratio = abs(nose.x - eye_mid_x) / eye_width

    return nose_offset_ratio >= away_ratio_threshold


def _mean_xy(landmarks: List[Any], indices: List[int]) -> Optional[tuple[float, float]]:
    xs: List[float] = []
    ys: List[float] = []

    for idx in indices:
        if idx >= len(landmarks):
            return None
        xs.append(float(landmarks[idx].x))
        ys.append(float(landmarks[idx].y))

    if not xs:
        return None

    return (sum(xs) / len(xs), sum(ys) / len(ys))


def _safe_ratio(value: float, start: float, end: float) -> Optional[float]:
    denom = end - start
    if abs(denom) < 1e-6:
        return None
    return (value - start) / denom


def _dist2d(p1: Any, p2: Any) -> float:
    dx = float(p1.x) - float(p2.x)
    dy = float(p1.y) - float(p2.y)
    return (dx * dx + dy * dy) ** 0.5


def _eye_aspect_ratio(
    landmarks: List[Any],
    horizontal_pair: tuple[int, int],
    vertical_pairs: List[tuple[int, int]],
) -> Optional[float]:
    max_idx = max(
        horizontal_pair[0],
        horizontal_pair[1],
        *[idx for pair in vertical_pairs for idx in pair],
    )
    if len(landmarks) <= max_idx:
        return None

    horizontal = _dist2d(
        landmarks[horizontal_pair[0]],
        landmarks[horizontal_pair[1]],
    )
    if horizontal < 1e-6:
        return None

    vertical_sum = 0.0
    for top_idx, bottom_idx in vertical_pairs:
        vertical_sum += _dist2d(landmarks[top_idx], landmarks[bottom_idx])

    return (vertical_sum / len(vertical_pairs)) / horizontal


def _median_valid(values: List[Optional[float]], max_sec: int) -> Optional[float]:
    valid = [v for v in values[:max_sec] if v is not None]
    if not valid:
        return None
    return float(statistics.median(valid))


def _open_eye_baseline(values: List[Optional[float]]) -> Optional[float]:
    """Estimate a personal open-eye EAR from the upper third of valid samples."""
    valid = sorted(float(v) for v in values if v is not None and float(v) > 0)
    if not valid:
        return None
    upper_count = max(1, int(round(len(valid) * 0.35)))
    return float(statistics.median(valid[-upper_count:]))


def _eye_closed_with_hysteresis(
    values: List[Optional[float]],
    close_threshold: float,
    reopen_threshold: float,
) -> List[bool]:
    closed = False
    result: List[bool] = []
    for value in values:
        if value is None:
            closed = False
        elif closed:
            closed = float(value) < float(reopen_threshold)
        else:
            closed = float(value) <= float(close_threshold)
        result.append(closed)
    return result


def _segment_duration_by_sec(flags_by_sec: List[bool]) -> List[int]:
    durations = [0] * len(flags_by_sec)
    t = 0
    while t < len(flags_by_sec):
        if not flags_by_sec[t]:
            t += 1
            continue
        start = t
        while t < len(flags_by_sec) and flags_by_sec[t]:
            t += 1
        duration = t - start
        for index in range(start, t):
            durations[index] = duration
    return durations


def _head_motion_by_sec(
    face_down: List[Optional[float]],
    face_tilt: List[Optional[float]],
    pose_drop: List[Optional[float]],
    pose_tilt: List[Optional[float]],
) -> List[Optional[float]]:
    result: List[Optional[float]] = [None] * len(face_down)
    previous: Optional[tuple[float, float]] = None
    for t in range(len(face_down)):
        primary = (face_down[t], face_tilt[t])
        fallback = (pose_drop[t], pose_tilt[t])
        values = primary if all(value is not None for value in primary) else fallback
        if not all(value is not None for value in values):
            previous = None
            continue
        current = (float(values[0]), float(values[1]))
        if previous is not None:
            result[t] = abs(current[0] - previous[0]) + abs(current[1] - previous[1])
        previous = current
    return result


def _low_motion_for_segments(
    segment_flags: List[bool],
    motion_by_sec: List[Optional[float]],
    minimum_samples: int,
    threshold: float,
) -> List[bool]:
    result = [False] * len(segment_flags)
    t = 0
    while t < len(segment_flags):
        if not segment_flags[t]:
            t += 1
            continue
        start = t
        while t < len(segment_flags) and segment_flags[t]:
            t += 1
        values = [value for value in motion_by_sec[start:t] if value is not None]
        if len(values) >= max(2, int(minimum_samples)) and (sum(values) / len(values)) <= float(threshold):
            for index in range(start, t):
                result[index] = True
    return result


def _filter_segments_by_duration(
    flags_by_sec: List[bool],
    min_duration_sec: Optional[int] = None,
    max_duration_sec: Optional[int] = None,
) -> List[bool]:
    result = [False] * len(flags_by_sec)
    t = 0

    while t < len(flags_by_sec):
        if not flags_by_sec[t]:
            t += 1
            continue

        start = t
        while t < len(flags_by_sec) and flags_by_sec[t]:
            t += 1
        end = t
        duration = end - start

        ok_min = (min_duration_sec is None) or (duration >= min_duration_sec)
        ok_max = (max_duration_sec is None) or (duration <= max_duration_sec)

        if ok_min and ok_max:
            for k in range(start, end):
                result[k] = True

    return result


def _count_segments(flags_by_sec: List[bool]) -> tuple[int, int]:
    total_sec = sum(1 for x in flags_by_sec if x)
    count = 0
    in_seg = False

    for flag in flags_by_sec:
        if flag and not in_seg:
            count += 1
            in_seg = True
        elif not flag:
            in_seg = False

    return count, total_sec


def _landmark_visible(lm: Any, min_visibility: float) -> bool:
    visibility = getattr(lm, "visibility", None)
    presence = getattr(lm, "presence", None)

    if visibility is not None and float(visibility) < min_visibility:
        return False
    if presence is not None and float(presence) < min_visibility:
        return False
    return True


def _flags_to_events(
    flags_by_sec: List[bool],
    event_type: str,
    score: float,
) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    t = 0

    while t < len(flags_by_sec):
        if not flags_by_sec[t]:
            t += 1
            continue

        start = t
        while t < len(flags_by_sec) and flags_by_sec[t]:
            t += 1
        end = t

        events.append(
            {
                "type": event_type,
                "start_sec": start,
                "end_sec": end,
                "score": score,
            }
        )

    return events


def _path_length(points: List[tuple[float, float]]) -> float:
    if len(points) < 2:
        return 0.0

    total = 0.0
    for i in range(1, len(points)):
        x1, y1 = points[i - 1]
        x2, y2 = points[i]
        total += ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
    return total


def _net_displacement(points: List[tuple[float, float]]) -> float:
    if len(points) < 2:
        return 0.0
    x1, y1 = points[0]
    x2, y2 = points[-1]
    return ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5


def _bbox_features(points: List[tuple[float, float]]) -> Dict[str, float]:
    if not points:
        return {"x_span": 0.0, "y_span": 0.0, "diag": 0.0}

    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    x_span = max(xs) - min(xs)
    y_span = max(ys) - min(ys)
    diag = (x_span * x_span + y_span * y_span) ** 0.5

    return {
        "x_span": x_span,
        "y_span": y_span,
        "diag": diag,
    }


def _direction_change_count(points: List[tuple[float, float]]) -> int:
    if len(points) < 3:
        return 0

    vectors: List[tuple[float, float]] = []
    for i in range(1, len(points)):
        x1, y1 = points[i - 1]
        x2, y2 = points[i]
        dx = x2 - x1
        dy = y2 - y1
        mag = (dx * dx + dy * dy) ** 0.5
        if mag > 1e-6:
            vectors.append((dx / mag, dy / mag))

    if len(vectors) < 2:
        return 0

    changes = 0
    for i in range(1, len(vectors)):
        vx1, vy1 = vectors[i - 1]
        vx2, vy2 = vectors[i]
        dot = vx1 * vx2 + vy1 * vy2
        if dot < 0.2:
            changes += 1

    return changes


def _hand_motion_features(points: List[tuple[float, float]]) -> Dict[str, float]:
    bbox = _bbox_features(points)
    return {
        "path_len": _path_length(points),
        "net_disp": _net_displacement(points),
        "x_span": bbox["x_span"],
        "y_span": bbox["y_span"],
        "bbox_diag": bbox["diag"],
        "dir_changes": float(_direction_change_count(points)),
    }


def _classify_hand_action(
    features: Dict[str, float],
    config: AnalyzeConfig,
) -> Optional[str]:
    path_len = features["path_len"]
    net_disp = features["net_disp"]
    x_span = features["x_span"]
    y_span = features["y_span"]
    bbox_diag = features["bbox_diag"]
    dir_changes = int(features["dir_changes"])

    if (
        path_len >= config.page_turn_min_path_len
        and net_disp >= config.page_turn_min_net_disp
        and x_span >= config.page_turn_min_x_span
        and y_span <= config.page_turn_max_y_span
        and dir_changes <= config.page_turn_max_dir_changes
    ):
        return "page_turn"

    if (
        path_len >= config.pen_fidget_min_path_len
        and bbox_diag <= config.pen_fidget_max_bbox_diag
        and dir_changes >= config.pen_fidget_min_dir_changes
    ):
        return "pen_fidget"

    if (
        path_len >= config.restless_hand_min_path_len
        and bbox_diag >= config.restless_hand_min_bbox_diag
        and dir_changes >= config.restless_hand_min_dir_changes
    ):
        return "restless_hand"

    return None


def _get_drowsy_face_features(landmarks: List[Any]) -> Dict[str, Any]:
    right_ear = _eye_aspect_ratio(
        landmarks,
        (33, 133),
        [(159, 145), (160, 144), (158, 153)],
    )
    left_ear = _eye_aspect_ratio(
        landmarks,
        (362, 263),
        [(386, 374), (385, 380), (387, 373)],
    )

    ear_values = [v for v in [right_ear, left_ear] if v is not None]
    avg_ear = sum(ear_values) / len(ear_values) if ear_values else None

    face_head_down_ratio = None
    face_head_tilt_ratio = None

    if len(landmarks) > 263 and len(landmarks) > 152:
        left_eye = landmarks[33]
        right_eye = landmarks[263]
        nose = landmarks[1]
        chin = landmarks[152]

        eye_mid_y = (float(left_eye.y) + float(right_eye.y)) / 2.0
        eye_width = abs(float(right_eye.x) - float(left_eye.x))

        if eye_width >= 1e-6:
            face_head_tilt_ratio = abs(float(left_eye.y) - float(right_eye.y)) / eye_width

        face_height = float(chin.y) - eye_mid_y
        if face_height >= 1e-6:
            face_head_down_ratio = (float(nose.y) - eye_mid_y) / face_height

    return {
        "right_ear": right_ear,
        "left_ear": left_ear,
        "avg_ear": avg_ear,
        "face_head_down_ratio": face_head_down_ratio,
        "face_head_tilt_ratio": face_head_tilt_ratio,
    }


def _get_drowsy_pose_features(landmarks: List[Any]) -> Dict[str, Any]:
    if len(landmarks) < 13:
        return {
            "pose_head_drop_ratio": None,
            "pose_head_tilt_ratio": None,
        }

    nose = landmarks[0]
    left_shoulder = landmarks[11]
    right_shoulder = landmarks[12]

    shoulder_width = abs(float(right_shoulder.x) - float(left_shoulder.x))
    if shoulder_width < 1e-6:
        return {
            "pose_head_drop_ratio": None,
            "pose_head_tilt_ratio": None,
        }

    shoulder_mid_y = (float(left_shoulder.y) + float(right_shoulder.y)) / 2.0
    shoulder_mid_x = (float(left_shoulder.x) + float(right_shoulder.x)) / 2.0

    pose_head_drop_ratio = (shoulder_mid_y - float(nose.y)) / shoulder_width
    pose_head_tilt_ratio = abs(float(nose.x) - shoulder_mid_x) / shoulder_width

    return {
        "pose_head_drop_ratio": pose_head_drop_ratio,
        "pose_head_tilt_ratio": pose_head_tilt_ratio,
    }


def _classify_gaze_from_landmarks(
    landmarks: List[Any],
    away_ratio_threshold: float,
    side_left_threshold: float,
    side_right_threshold: float,
    down_threshold: float,
) -> str:
    if len(landmarks) < 478:
        if _is_away_from_landmarks(landmarks, away_ratio_threshold):
            return "gaze_side"
        return "focus"

    right_iris = _mean_xy(landmarks, [469, 470, 471, 472])
    left_iris = _mean_xy(landmarks, [474, 475, 476, 477])

    if right_iris is None or left_iris is None:
        if _is_away_from_landmarks(landmarks, away_ratio_threshold):
            return "gaze_side"
        return "focus"

    x_ratios: List[float] = []
    y_ratios: List[float] = []

    eye_specs = [
        ([33, 133], [159, 145], right_iris),
        ([362, 263], [386, 374], left_iris),
    ]

    for corner_ids, eyelid_ids, iris_center in eye_specs:
        c1 = landmarks[corner_ids[0]]
        c2 = landmarks[corner_ids[1]]

        eye_x_min = min(float(c1.x), float(c2.x))
        eye_x_max = max(float(c1.x), float(c2.x))
        x_ratio = _safe_ratio(float(iris_center[0]), eye_x_min, eye_x_max)
        if x_ratio is not None:
            x_ratios.append(x_ratio)

        upper = landmarks[eyelid_ids[0]]
        lower = landmarks[eyelid_ids[1]]
        eye_y_min = min(float(upper.y), float(lower.y))
        eye_y_max = max(float(upper.y), float(lower.y))
        y_ratio = _safe_ratio(float(iris_center[1]), eye_y_min, eye_y_max)
        if y_ratio is not None:
            y_ratios.append(y_ratio)

    if not x_ratios:
        if _is_away_from_landmarks(landmarks, away_ratio_threshold):
            return "gaze_side"
        return "focus"

    avg_x = sum(x_ratios) / len(x_ratios)
    avg_y = (sum(y_ratios) / len(y_ratios)) if y_ratios else None
    head_away = _is_away_from_landmarks(landmarks, away_ratio_threshold)

    if avg_y is not None and avg_y >= down_threshold:
        return "gaze_down"

    if avg_x <= side_left_threshold or avg_x >= side_right_threshold or head_away:
        return "gaze_side"

    return "focus"


def _mark_state_segments(
    states: List[str],
    flags_by_sec: List[bool],
    state_name: str,
    score: float,
) -> Dict[str, Any]:
    events: List[Dict[str, Any]] = []
    total_sec = 0
    count = 0
    in_seg = False
    start = 0

    for t in range(len(states)):
        should_mark = (states[t] == "focus") and flags_by_sec[t]

        if should_mark:
            states[t] = state_name
            total_sec += 1
            if not in_seg:
                in_seg = True
                start = t
        else:
            if in_seg:
                events.append(
                    {
                        "type": state_name,
                        "start_sec": start,
                        "end_sec": t,
                        "score": score,
                    }
                )
                count += 1
                in_seg = False

    if in_seg:
        events.append(
            {
                "type": state_name,
                "start_sec": start,
                "end_sec": len(states),
                "score": score,
            }
        )
        count += 1

    return {
        "states": states,
        "events": events,
        "total_sec": total_sec,
        "count": count,
    }


def _create_events_from_states(states: List[str]) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    current_state: Optional[str] = None
    start_sec = 0

    def close_event(end_sec: int) -> None:
        if current_state is None:
            return
        events.append(
            {
                "type": current_state,
                "start_sec": start_sec,
                "end_sec": end_sec,
                "score": _STATE_EVENT_SCORES.get(current_state, 0.0),
            }
        )

    for t, raw_state in enumerate(states):
        state = str(raw_state or "unknown")
        event_state = None if state == "focus" else state

        if event_state == current_state:
            continue

        close_event(t)
        current_state = event_state
        start_sec = t

    close_event(len(states))
    return events


def _timeline_item_at(timeline: Any, t: int) -> Optional[Dict[str, Any]]:
    if isinstance(timeline, dict):
        item = timeline.get(t)
        return item if isinstance(item, dict) else None

    if isinstance(timeline, list):
        if 0 <= t < len(timeline) and isinstance(timeline[t], dict):
            item = timeline[t]
            if int(item.get("t", t)) == t:
                return item

        for item in timeline:
            if isinstance(item, dict) and int(item.get("t", -1)) == t:
                return item

    return None


def _flag_float(flags: Dict[str, Any], name: str) -> float:
    try:
        return float(flags.get(name, 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def has_overhead_activity(overhead_item: Optional[Dict[str, Any]]) -> bool:
    if not isinstance(overhead_item, dict):
        return False

    flags = overhead_item.get("flags", {})
    if not isinstance(flags, dict):
        flags = {}

    states = set(_ensure_states_list(overhead_item))
    if states.intersection(_OVERHEAD_ACTIVITY_FLAGS):
        return True

    if any(bool(flags.get(name, False)) for name in _OVERHEAD_ACTIVITY_FLAGS):
        return True

    return (
        _flag_float(flags, "hand_path_len") >= _OVERHEAD_ACTIVITY_PATH_THRESHOLD
        or _flag_float(flags, "hand_net_disp") >= _OVERHEAD_ACTIVITY_DISPLACEMENT_THRESHOLD
        or _flag_float(flags, "hand_bbox_diag") >= _OVERHEAD_ACTIVITY_BBOX_THRESHOLD
    )


def _has_overhead_person_trace(overhead_item: Optional[Dict[str, Any]]) -> bool:
    if not isinstance(overhead_item, dict):
        return False

    flags = overhead_item.get("flags", {})
    if not isinstance(flags, dict):
        flags = {}

    if any(bool(flags.get(name, False)) for name in _OVERHEAD_PERSON_TRACE_FLAGS):
        return True

    return (
        _flag_float(flags, "hand_path_len") > 0.0
        or _flag_float(flags, "hand_net_disp") > 0.0
        or _flag_float(flags, "hand_bbox_diag") > 0.0
    )


def has_recent_drowsy_context(
    front_timeline: Any,
    t: int,
    window_sec: int = 10,
) -> bool:
    start = max(0, int(t) - max(1, int(window_sec)))

    for sec in range(start, int(t) + 1):
        item = _timeline_item_at(front_timeline, sec)
        if not isinstance(item, dict):
            continue

        state = str(item.get("state", ""))
        if state in {"drowsy", "gaze_down", "sleep_suspect"}:
            return True

        flags = item.get("flags", {})
        if not isinstance(flags, dict):
            continue

        if any(bool(flags.get(name, False)) for name in _RECENT_DROWSY_CONTEXT_FLAGS):
            return True

    return False


def classify_missing_face_state(
    t: int,
    front_timeline: Any,
    overhead_item: Optional[Dict[str, Any]] = None,
    overhead_available: bool = False,
    recent_window_sec: int = 10,
) -> str:
    recent_drowsy = has_recent_drowsy_context(front_timeline, t, recent_window_sec)

    if overhead_available and overhead_item is not None:
        if has_overhead_activity(overhead_item):
            return "unknown"

        if _has_overhead_person_trace(overhead_item):
            return "sleep_suspect" if recent_drowsy else "unknown"

        return "absent"

    return "sleep_suspect" if recent_drowsy else "absent"


def resolve_front_absence_with_overhead(
    t: int,
    front_item: Dict[str, Any],
    overhead_item: Optional[Dict[str, Any]],
    front_timeline: Any,
    overhead_available: bool = True,
) -> Dict[str, Any]:
    missing_face_state = classify_missing_face_state(
        t=t,
        front_timeline=front_timeline,
        overhead_item=overhead_item,
        overhead_available=overhead_available,
    )

    final_state = "drowsy" if missing_face_state == "sleep_suspect" else missing_face_state

    return {
        "state": final_state,
        "missing_face_state": missing_face_state,
        "sleep_suspect": missing_face_state == "sleep_suspect",
        "overhead_activity": has_overhead_activity(overhead_item),
        "overhead_person_trace": _has_overhead_person_trace(overhead_item),
    }


def _mark_absent_segments(
    face_seen_by_sec: List[bool],
    absent_threshold_sec: int,
    missing_face_state_by_sec: Optional[List[str]] = None,
) -> Dict[str, Any]:
    duration_sec = len(face_seen_by_sec)
    states = ["focus"] * duration_sec

    t = 0
    while t < duration_sec:
        if face_seen_by_sec[t]:
            t += 1
            continue

        start = t
        while t < duration_sec and (not face_seen_by_sec[t]):
            t += 1
        end = t

        if (end - start) >= absent_threshold_sec:
            for k in range(start, end):
                state = "absent"
                if missing_face_state_by_sec is not None and k < len(missing_face_state_by_sec):
                    state = str(missing_face_state_by_sec[k] or "absent")
                states[k] = state

    events = _create_events_from_states(states)
    absent_count, absent_total_sec = _count_segments([s == "absent" for s in states])

    return {
        "states": states,
        "events": events,
        "absent_total_sec": absent_total_sec,
        "absent_count": absent_count,
    }


def _resolve_model_path() -> str:
    ai_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    return os.path.join(ai_root, "models", "face_landmarker.task")


def _resolve_pose_model_path() -> str:
    ai_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    return os.path.join(ai_root, "models", "pose_landmarker.task")


def _resolve_classifier_model_path(config: AnalyzeConfig) -> str:
    model_path = str(config.classifier_model_path)
    if os.path.isabs(model_path):
        return model_path

    ai_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    project_root = os.path.abspath(os.path.join(ai_root, ".."))

    if model_path.replace("\\", "/").startswith("ai/"):
        return os.path.join(project_root, model_path)

    return os.path.join(ai_root, model_path)


def _bool_feature(value: bool) -> float:
    return 1.0 if value else 0.0


def _none_to_zero(value: Optional[float]) -> float:
    return float(value) if value is not None else 0.0


def _build_state_feature_dict(
    t: int,
    camera_type: str,
    face_seen_by_sec: List[bool],
    gaze_side_seen_by_sec: List[bool],
    gaze_down_seen_by_sec: List[bool],
    bad_posture_seen_by_sec: List[bool],
    eye_closed_seen_by_sec: List[bool],
    blink_seen_by_sec: List[bool],
    long_eye_closure_seen_by_sec: List[bool],
    head_down_seen_by_sec: List[bool],
    head_tilt_seen_by_sec: List[bool],
    drowsy_seen_by_sec: List[bool],
    page_turn_seen_by_sec: List[bool],
    pen_fidget_seen_by_sec: List[bool],
    restless_hand_seen_by_sec: List[bool],
    avg_ear_by_sec: List[Optional[float]],
    face_head_down_ratio_by_sec: List[Optional[float]],
    face_head_tilt_ratio_by_sec: List[Optional[float]],
    pose_head_drop_ratio_by_sec: List[Optional[float]],
    pose_head_tilt_ratio_by_sec: List[Optional[float]],
    hand_features_by_sec: List[Dict[str, float]],
) -> Dict[str, float]:
    hand_features = hand_features_by_sec[t] if t < len(hand_features_by_sec) else {}

    return {
        "t": float(t),
        "is_front_camera": _bool_feature(str(camera_type).lower() == "front"),
        "is_overhead_camera": _bool_feature(str(camera_type).lower() in {"top", "overhead", "desk", "topdown"}),
        "face_seen": _bool_feature(face_seen_by_sec[t]),
        "gaze_side": _bool_feature(gaze_side_seen_by_sec[t]),
        "gaze_down": _bool_feature(gaze_down_seen_by_sec[t]),
        "bad_posture": _bool_feature(bad_posture_seen_by_sec[t]),
        "eye_closed": _bool_feature(eye_closed_seen_by_sec[t]),
        "blink": _bool_feature(blink_seen_by_sec[t]),
        "long_eye_closure": _bool_feature(long_eye_closure_seen_by_sec[t]),
        "head_down": _bool_feature(head_down_seen_by_sec[t]),
        "head_tilt": _bool_feature(head_tilt_seen_by_sec[t]),
        "drowsy": _bool_feature(drowsy_seen_by_sec[t]),
        "page_turn": _bool_feature(page_turn_seen_by_sec[t]),
        "pen_fidget": _bool_feature(pen_fidget_seen_by_sec[t]),
        "restless_hand": _bool_feature(restless_hand_seen_by_sec[t]),
        "avg_ear": _none_to_zero(avg_ear_by_sec[t]),
        "face_head_down_ratio": _none_to_zero(face_head_down_ratio_by_sec[t]),
        "face_head_tilt_ratio": _none_to_zero(face_head_tilt_ratio_by_sec[t]),
        "pose_head_drop_ratio": _none_to_zero(pose_head_drop_ratio_by_sec[t]),
        "pose_head_tilt_ratio": _none_to_zero(pose_head_tilt_ratio_by_sec[t]),
        "hand_path_len": float(hand_features.get("path_len", 0.0)),
        "hand_net_disp": float(hand_features.get("net_disp", 0.0)),
        "hand_x_span": float(hand_features.get("x_span", 0.0)),
        "hand_y_span": float(hand_features.get("y_span", 0.0)),
        "hand_bbox_diag": float(hand_features.get("bbox_diag", 0.0)),
        "hand_dir_changes": float(hand_features.get("dir_changes", 0.0)),
    }


def _load_optional_classifier(config: AnalyzeConfig, warnings: List[str]) -> Optional[Any]:
    if not config.use_trained_classifier:
        return None

    classifier_path = _resolve_classifier_model_path(config)
    if not os.path.exists(classifier_path):
        warnings.append("CLASSIFIER_MODEL_NOT_FOUND")
        return None

    try:
        return load_state_classifier(classifier_path)
    except Exception as e:
        warnings.append(f"CLASSIFIER_LOAD_FAILED:{type(e).__name__}")
        return None


def _predict_model_state(
    classifier_bundle: Optional[Any],
    feature_dict: Dict[str, float],
    warnings: List[str],
    excluded_states: Optional[set[str]] = None,
) -> tuple[Optional[str], Optional[float]]:
    if classifier_bundle is None:
        return None, None

    try:
        probabilities = predict_state_proba(classifier_bundle, feature_dict)
    except Exception as e:
        warning = f"CLASSIFIER_PREDICT_FAILED:{type(e).__name__}"
        if warning not in warnings:
            warnings.append(warning)
        return None, None

    if not probabilities:
        return None, None

    if excluded_states:
        excluded = {str(state) for state in excluded_states}
        probabilities = {
            str(state): float(confidence)
            for state, confidence in probabilities.items()
            if str(state) not in excluded
        }

    if not probabilities:
        return None, None

    state, confidence = max(probabilities.items(), key=lambda item: item[1])
    return str(state), round(float(confidence), 4)


def _decide_hybrid_state(
    rule_state: str,
    model_state: Optional[str],
    model_confidence: Optional[float],
    threshold: float,
) -> tuple[str, str]:
    if rule_state in _RULE_ONLY_STATE_DECISION_SOURCES:
        return rule_state, _RULE_ONLY_STATE_DECISION_SOURCES[rule_state]

    if model_state in _RULE_ONLY_STATES:
        model_state = None
        model_confidence = None

    if model_state and model_confidence is not None and model_confidence >= threshold:
        return model_state, "model"

    if rule_state:
        return rule_state, "rule"

    return "unknown", "unknown"


def _create_pose_landmarker(model_path: str) -> vision.PoseLandmarker:
    with open(model_path, "rb") as f:
        model_bytes = f.read()

    try:
        base_options = python.BaseOptions(model_asset_buffer=model_bytes)
    except TypeError:
        base_options = python.BaseOptions(model_asset_path=model_path)

    options = vision.PoseLandmarkerOptions(
        base_options=base_options,
        running_mode=vision.RunningMode.VIDEO,
        num_poses=1,
        min_pose_detection_confidence=0.5,
        min_pose_presence_confidence=0.5,
        min_tracking_confidence=0.5,
        output_segmentation_masks=False,
    )
    return vision.PoseLandmarker.create_from_options(options)


def _create_face_landmarker(model_path: str, min_conf: float) -> vision.FaceLandmarker:
    with open(model_path, "rb") as f:
        model_bytes = f.read()

    try:
        base_options = python.BaseOptions(model_asset_buffer=model_bytes)
    except TypeError:
        base_options = python.BaseOptions(model_asset_path=model_path)

    options = vision.FaceLandmarkerOptions(
        base_options=base_options,
        running_mode=vision.RunningMode.VIDEO,
        num_faces=1,
        min_face_detection_confidence=float(min_conf),
        min_face_presence_confidence=float(min_conf),
        min_tracking_confidence=0.5,
        output_face_blendshapes=False,
        output_facial_transformation_matrixes=False,
    )
    return vision.FaceLandmarker.create_from_options(options)


def _is_bad_posture_from_pose(
    landmarks: List[Any],
    shoulder_threshold: float,
    tilt_threshold: float,
) -> bool:
    if len(landmarks) < 13:
        return False

    nose = landmarks[0]
    left_shoulder = landmarks[11]
    right_shoulder = landmarks[12]

    shoulder_width = abs(right_shoulder.x - left_shoulder.x)
    if shoulder_width < 1e-6:
        return False

    shoulder_slope = abs(left_shoulder.y - right_shoulder.y)
    shoulder_mid_x = (left_shoulder.x + right_shoulder.x) / 2.0
    head_tilt = abs(nose.x - shoulder_mid_x) / shoulder_width

    return shoulder_slope >= shoulder_threshold or head_tilt >= tilt_threshold


def _write_summary_csv(result: Dict[str, Any], csv_path: str) -> None:
    summary = result.get("summary", {})
    meta = result.get("meta", {})

    row = {
        "session_id": result.get("session_id"),
        "status": result.get("status"),
        **meta,
        **summary,
    }

    fieldnames = list(row.keys())

    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow(row)


def _write_timeline_csv(result: Dict[str, Any], csv_path: str) -> None:
    timeline = result.get("timeline", [])
    if not timeline:
        with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["session_id", "t", "state", "states"])
        return

    rows: List[Dict[str, Any]] = []
    for item in timeline:
        row = {
            "session_id": result.get("session_id"),
            "t": item.get("t"),
            "state": item.get("state"),
            "states": "|".join(_ensure_states_list(item)),
            "model_state": item.get("model_state"),
            "model_confidence": item.get("model_confidence"),
            "rule_state": item.get("rule_state"),
            "decision_source": item.get("decision_source"),
        }

        flags = item.get("flags", {})
        for k, v in flags.items():
            row[f"flag_{k}"] = v

        rows.append(row)

    fieldnames: List[str] = []
    seen = set()
    for row in rows:
        for key in row.keys():
            if key not in seen:
                seen.add(key)
                fieldnames.append(key)

    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_events_csv(result: Dict[str, Any], csv_path: str) -> None:
    events = result.get("events", [])
    if not events:
        with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["session_id", "type", "start_sec", "end_sec", "score"])
        return

    rows = []
    for event in events:
        row = {
            "session_id": result.get("session_id"),
            **event,
        }
        rows.append(row)

    fieldnames: List[str] = []
    seen = set()
    for row in rows:
        for key in row.keys():
            if key not in seen:
                seen.add(key)
                fieldnames.append(key)

    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def analyze_absent(
    session_id: str,
    video_path: str,
    camera_type: str,
    config: AnalyzeConfig,
) -> Dict[str, Any]:
    started = time.time()
    meta = _read_video_meta(video_path)

    if not meta["ok"]:
        return _with_time_patterns({
            "session_id": session_id,
            "status": "failed",
            "meta": {
                "camera_type": camera_type,
                "sampling_fps": config.sampling_fps,
                "video_fps": meta["video_fps"],
                "duration_sec": meta["duration_sec"],
                "processed_frames": 0,
                "processing_time_sec": int(time.time() - started),
                "version": config.version,
                "warnings": [],
                "fail_reason": meta["reason"],
            },
            "summary": {},
            "timeline": [],
            "events": [],
        })

    fps: float = meta["video_fps"]
    duration_sec: int = meta["duration_sec"]

    use_hand_actions = (
        config.enable_hand_actions
        and str(camera_type).lower() in {"top", "overhead", "desk", "topdown"}
    )

    face_seen_by_sec = [False] * max(duration_sec, 0)
    pose_seen_by_sec = [False] * max(duration_sec, 0)
    hand_seen_by_sec = [False] * max(duration_sec, 0)
    gaze_side_seen_by_sec = [False] * max(duration_sec, 0)
    gaze_down_seen_by_sec = [False] * max(duration_sec, 0)
    bad_posture_seen_by_sec = [False] * max(duration_sec, 0)
    unknown_seen_by_sec = [False] * max(duration_sec, 0)

    eye_closed_seen_by_sec = [False] * max(duration_sec, 0)
    head_down_seen_by_sec = [False] * max(duration_sec, 0)
    head_tilt_seen_by_sec = [False] * max(duration_sec, 0)
    raw_drowsy_seen_by_sec = [False] * max(duration_sec, 0)
    drowsy_seen_by_sec = [False] * max(duration_sec, 0)

    right_ear_by_sec: List[Optional[float]] = [None] * max(duration_sec, 0)
    left_ear_by_sec: List[Optional[float]] = [None] * max(duration_sec, 0)
    avg_ear_by_sec: List[Optional[float]] = [None] * max(duration_sec, 0)
    face_head_down_ratio_by_sec: List[Optional[float]] = [None] * max(duration_sec, 0)
    face_head_tilt_ratio_by_sec: List[Optional[float]] = [None] * max(duration_sec, 0)
    pose_head_drop_ratio_by_sec: List[Optional[float]] = [None] * max(duration_sec, 0)
    pose_head_tilt_ratio_by_sec: List[Optional[float]] = [None] * max(duration_sec, 0)

    blink_seen_by_sec = [False] * max(duration_sec, 0)
    long_eye_closure_seen_by_sec = [False] * max(duration_sec, 0)
    eye_closure_duration_by_sec = [0] * max(duration_sec, 0)
    head_motion_by_sec: List[Optional[float]] = [None] * max(duration_sec, 0)
    low_head_motion_seen_by_sec = [False] * max(duration_sec, 0)
    right_ear_baseline: Optional[float] = None
    left_ear_baseline: Optional[float] = None
    right_close_threshold: Optional[float] = None
    left_close_threshold: Optional[float] = None
    right_reopen_threshold: Optional[float] = None
    left_reopen_threshold: Optional[float] = None

    raw_page_turn_seen_by_sec = [False] * max(duration_sec, 0)
    page_turn_seen_by_sec = [False] * max(duration_sec, 0)

    raw_pen_fidget_seen_by_sec = [False] * max(duration_sec, 0)
    pen_fidget_seen_by_sec = [False] * max(duration_sec, 0)

    raw_restless_hand_seen_by_sec = [False] * max(duration_sec, 0)
    restless_hand_seen_by_sec = [False] * max(duration_sec, 0)

    wrist_points_by_sec = [
        {"left": [], "right": []}
        for _ in range(max(duration_sec, 0))
    ]
    hand_features_by_sec: List[Dict[str, float]] = [
        {
            "path_len": 0.0,
            "net_disp": 0.0,
            "x_span": 0.0,
            "y_span": 0.0,
            "bbox_diag": 0.0,
            "dir_changes": 0.0,
        }
        for _ in range(max(duration_sec, 0))
    ]

    model_path = _resolve_model_path()
    if not os.path.exists(model_path):
        return _with_time_patterns({
            "session_id": session_id,
            "status": "failed",
            "meta": {
                "camera_type": camera_type,
                "sampling_fps": config.sampling_fps,
                "video_fps": fps,
                "duration_sec": duration_sec,
                "processed_frames": 0,
                "processing_time_sec": int(time.time() - started),
                "version": config.version,
                "warnings": [],
                "fail_reason": "MODEL_NOT_FOUND",
                "model_path": model_path,
            },
            "summary": {},
            "timeline": [],
            "events": [],
        })

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return _with_time_patterns({
            "session_id": session_id,
            "status": "failed",
            "meta": {
                "camera_type": camera_type,
                "sampling_fps": config.sampling_fps,
                "video_fps": fps,
                "duration_sec": duration_sec,
                "processed_frames": 0,
                "processing_time_sec": int(time.time() - started),
                "version": config.version,
                "warnings": [],
                "fail_reason": "VIDEO_OPEN_FAIL",
            },
            "summary": {},
            "timeline": [],
            "events": [],
        })

    step = max(int(round(fps / max(config.sampling_fps, 1))), 1)
    processed_frames = 0
    warnings: List[str] = []

    if config.sampling_fps > fps:
        warnings.append("SAMPLING_FPS_GT_VIDEO_FPS")

    face_detector: Optional[vision.FaceLandmarker] = None
    pose_detector: Optional[vision.PoseLandmarker] = None

    try:
        face_detector = _create_face_landmarker(model_path, config.min_face_confidence)

        pose_model_path = _resolve_pose_model_path()
        if (config.enable_bad_posture or config.enable_drowsy) and os.path.exists(pose_model_path):
            pose_detector = _create_pose_landmarker(pose_model_path)
        else:
            if config.enable_bad_posture or config.enable_drowsy:
                warnings.append("POSE_MODEL_NOT_FOUND")

        frame_idx = 0
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            if frame_idx % step == 0:
                processed_frames += 1

                sec = int(frame_idx / fps) if fps > 0 else 0
                if 0 <= sec < duration_sec:
                    h, w = frame.shape[:2]
                    if w > 960:
                        scale = 960 / w
                        frame = cv2.resize(frame, (int(w * scale), int(h * scale)))

                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                    timestamp_ms = int((frame_idx / fps) * 1000) if fps > 0 else 0

                    detection_result = face_detector.detect_for_video(mp_image, timestamp_ms)
                    if detection_result.face_landmarks:
                        face_seen_by_sec[sec] = True
                        landmarks = detection_result.face_landmarks[0]

                        gaze_state = _classify_gaze_from_landmarks(
                            landmarks,
                            config.away_ratio_threshold,
                            config.gaze_side_left_threshold,
                            config.gaze_side_right_threshold,
                            config.gaze_down_threshold,
                        )

                        if gaze_state == "gaze_side":
                            gaze_side_seen_by_sec[sec] = True
                        elif gaze_state == "gaze_down":
                            gaze_down_seen_by_sec[sec] = True

                        if config.enable_drowsy:
                            drowsy_face = _get_drowsy_face_features(landmarks)
                            right_ear_by_sec[sec] = drowsy_face["right_ear"]
                            left_ear_by_sec[sec] = drowsy_face["left_ear"]
                            avg_ear_by_sec[sec] = drowsy_face["avg_ear"]
                            face_head_down_ratio_by_sec[sec] = drowsy_face["face_head_down_ratio"]
                            face_head_tilt_ratio_by_sec[sec] = drowsy_face["face_head_tilt_ratio"]

                    if pose_detector is not None:
                        pose_result = pose_detector.detect_for_video(mp_image, timestamp_ms)
                        if pose_result.pose_landmarks:
                            pose_seen_by_sec[sec] = True
                            pose_landmarks = pose_result.pose_landmarks[0]

                            if use_hand_actions and 0 <= sec < duration_sec:
                                for wrist_idx, hand_key in ((15, "left"), (16, "right")):
                                    wrist = pose_landmarks[wrist_idx]
                                    if _landmark_visible(wrist, config.hand_min_visibility):
                                        hand_seen_by_sec[sec] = True
                                        wrist_points_by_sec[sec][hand_key].append((float(wrist.x), float(wrist.y)))

                            if _is_bad_posture_from_pose(
                                pose_landmarks,
                                config.posture_shoulder_threshold,
                                config.posture_tilt_threshold,
                            ):
                                bad_posture_seen_by_sec[sec] = True

                            if config.enable_drowsy:
                                drowsy_pose = _get_drowsy_pose_features(pose_landmarks)
                                pose_head_drop_ratio_by_sec[sec] = drowsy_pose["pose_head_drop_ratio"]
                                pose_head_tilt_ratio_by_sec[sec] = drowsy_pose["pose_head_tilt_ratio"]

            frame_idx += 1

    except RuntimeError as e:
        return _with_time_patterns({
            "session_id": session_id,
            "status": "failed",
            "meta": {
                "camera_type": camera_type,
                "sampling_fps": config.sampling_fps,
                "video_fps": fps,
                "duration_sec": duration_sec,
                "processed_frames": processed_frames,
                "processing_time_sec": int(time.time() - started),
                "version": config.version,
                "warnings": warnings,
                "fail_reason": "MEDIAPIPE_RUNTIME_ERROR",
                "error": str(e),
                "model_path": model_path,
            },
            "summary": {},
            "timeline": [],
            "events": [],
        })

    finally:
        cap.release()
        if face_detector is not None:
            face_detector.close()
        if pose_detector is not None:
            pose_detector.close()

    if config.enable_drowsy and duration_sec > 0:
        baseline_sec = min(int(config.baseline_duration_sec), duration_sec)

        right_ear_baseline = _open_eye_baseline(right_ear_by_sec)
        left_ear_baseline = _open_eye_baseline(left_ear_by_sec)
        face_head_down_baseline = _median_valid(face_head_down_ratio_by_sec, baseline_sec)

        right_close_threshold = float(config.drowsy_ear_threshold)
        left_close_threshold = float(config.drowsy_ear_threshold)
        right_reopen_threshold = float(config.drowsy_ear_reopen_threshold)
        left_reopen_threshold = float(config.drowsy_ear_reopen_threshold)
        if right_ear_baseline is not None:
            right_close_threshold = min(
                right_close_threshold,
                float(right_ear_baseline) * float(config.ear_baseline_ratio),
            )
            right_reopen_threshold = min(
                right_reopen_threshold,
                float(right_ear_baseline) * float(config.ear_reopen_baseline_ratio),
            )
        if left_ear_baseline is not None:
            left_close_threshold = min(
                left_close_threshold,
                float(left_ear_baseline) * float(config.ear_baseline_ratio),
            )
            left_reopen_threshold = min(
                left_reopen_threshold,
                float(left_ear_baseline) * float(config.ear_reopen_baseline_ratio),
            )
        right_reopen_threshold = max(right_reopen_threshold, right_close_threshold + 0.01)
        left_reopen_threshold = max(left_reopen_threshold, left_close_threshold + 0.01)

        right_eye_closed_by_sec = _eye_closed_with_hysteresis(
            right_ear_by_sec,
            right_close_threshold,
            right_reopen_threshold,
        )
        left_eye_closed_by_sec = _eye_closed_with_hysteresis(
            left_ear_by_sec,
            left_close_threshold,
            left_reopen_threshold,
        )

        effective_face_head_down_threshold = float(config.face_head_down_threshold)
        if face_head_down_baseline is not None:
            effective_face_head_down_threshold = max(
                float(config.face_head_down_threshold),
                float(face_head_down_baseline) + float(config.face_head_down_offset),
            )

        for t in range(duration_sec):
            face_head_down_ratio = face_head_down_ratio_by_sec[t]
            face_head_tilt_ratio = face_head_tilt_ratio_by_sec[t]
            pose_head_drop_ratio = pose_head_drop_ratio_by_sec[t]
            pose_head_tilt_ratio = pose_head_tilt_ratio_by_sec[t]

            eye_closed_seen_by_sec[t] = (
                right_eye_closed_by_sec[t] and left_eye_closed_by_sec[t]
            )

            face_head_down = (
                face_head_down_ratio is not None
                and face_head_down_ratio >= effective_face_head_down_threshold
            )

            pose_head_down = (
                pose_head_drop_ratio is not None
                and pose_head_drop_ratio <= (
                    float(config.drowsy_head_drop_threshold) - float(config.pose_head_drop_margin)
                )
            )

            if face_head_down or (eye_closed_seen_by_sec[t] and pose_head_down):
                head_down_seen_by_sec[t] = True

            face_head_tilt = (
                face_head_tilt_ratio is not None
                and face_head_tilt_ratio >= float(config.drowsy_head_tilt_threshold)
            )
            pose_head_tilt = (
                pose_head_tilt_ratio is not None
                and pose_head_tilt_ratio >= float(config.drowsy_head_tilt_threshold)
            )

            if face_head_tilt or pose_head_tilt:
                head_tilt_seen_by_sec[t] = True

        blink_seen_by_sec = _filter_segments_by_duration(
            eye_closed_seen_by_sec,
            max_duration_sec=int(config.blink_max_duration_sec),
        )
        long_eye_closure_seen_by_sec = _filter_segments_by_duration(
            eye_closed_seen_by_sec,
            min_duration_sec=int(config.long_eye_closure_min_sec),
        )
        eye_closure_duration_by_sec = _segment_duration_by_sec(eye_closed_seen_by_sec)
        head_motion_by_sec = _head_motion_by_sec(
            face_head_down_ratio_by_sec,
            face_head_tilt_ratio_by_sec,
            pose_head_drop_ratio_by_sec,
            pose_head_tilt_ratio_by_sec,
        )
        low_head_motion_seen_by_sec = _low_motion_for_segments(
            long_eye_closure_seen_by_sec,
            head_motion_by_sec,
            int(config.drowsy_head_motion_window_sec),
            float(config.drowsy_head_motion_threshold),
        )

        for t in range(duration_sec):
            if (
                long_eye_closure_seen_by_sec[t]
                and head_down_seen_by_sec[t]
                and low_head_motion_seen_by_sec[t]
            ):
                raw_drowsy_seen_by_sec[t] = True

        drowsy_seen_by_sec = _filter_segments_by_duration(
            raw_drowsy_seen_by_sec,
            min_duration_sec=int(config.drowsy_min_duration_sec),
        )

    if use_hand_actions:
        for t in range(duration_sec):
            left_points = wrist_points_by_sec[t]["left"]
            right_points = wrist_points_by_sec[t]["right"]

            left_features = _hand_motion_features(left_points)
            right_features = _hand_motion_features(right_points)

            selected = left_features if left_features["path_len"] >= right_features["path_len"] else right_features
            hand_features_by_sec[t] = selected
            label = _classify_hand_action(selected, config)

            if label == "page_turn":
                raw_page_turn_seen_by_sec[t] = True
            elif label == "pen_fidget":
                raw_pen_fidget_seen_by_sec[t] = True
            elif label == "restless_hand":
                raw_restless_hand_seen_by_sec[t] = True

    gaze_side_seen_by_sec = _filter_segments_by_duration(
        gaze_side_seen_by_sec,
        min_duration_sec=int(config.gaze_side_min_duration_sec),
    )
    gaze_down_seen_by_sec = _filter_segments_by_duration(
        gaze_down_seen_by_sec,
        min_duration_sec=int(config.gaze_down_min_duration_sec),
    )
    bad_posture_seen_by_sec = _filter_segments_by_duration(
        bad_posture_seen_by_sec,
        min_duration_sec=int(config.bad_posture_min_duration_sec),
    )
    page_turn_seen_by_sec = _filter_segments_by_duration(
        raw_page_turn_seen_by_sec,
        min_duration_sec=int(config.page_turn_min_duration_sec),
    )
    pen_fidget_seen_by_sec = _filter_segments_by_duration(
        raw_pen_fidget_seen_by_sec,
        min_duration_sec=int(config.pen_fidget_min_duration_sec),
    )
    restless_hand_seen_by_sec = _filter_segments_by_duration(
        raw_restless_hand_seen_by_sec,
        min_duration_sec=int(config.restless_hand_min_duration_sec),
    )

    sleep_suspect_seen_by_sec = [False] * max(duration_sec, 0)
    missing_face_state_by_sec: Optional[List[str]] = None
    if str(camera_type).lower() == "front":
        drowsy_context_timeline = [
            {
                "t": t,
                "state": "drowsy" if drowsy_seen_by_sec[t] else "focus",
                "flags": {
                    "head_down": head_down_seen_by_sec[t],
                    "drowsy": drowsy_seen_by_sec[t],
                    "raw_drowsy": raw_drowsy_seen_by_sec[t],
                    "eye_closed": eye_closed_seen_by_sec[t],
                    "long_eye_closure": long_eye_closure_seen_by_sec[t],
                    "gaze_down": gaze_down_seen_by_sec[t],
                },
            }
            for t in range(duration_sec)
        ]
        missing_face_state_by_sec = ["absent"] * max(duration_sec, 0)
        for t in range(duration_sec):
            if face_seen_by_sec[t]:
                continue
            missing_state = classify_missing_face_state(
                t=t,
                front_timeline=drowsy_context_timeline,
                overhead_item=None,
                overhead_available=False,
            )
            if missing_state == "sleep_suspect":
                missing_face_state_by_sec[t] = "drowsy"
                sleep_suspect_seen_by_sec[t] = True

    seg = _mark_absent_segments(
        face_seen_by_sec,
        int(config.absent_threshold_sec),
        missing_face_state_by_sec=missing_face_state_by_sec,
    )
    states = seg["states"]
    events = seg["events"]
    absent_total_sec = seg["absent_total_sec"]
    absent_count = seg["absent_count"]

    gaze_side_seg = _mark_state_segments(
        states,
        gaze_side_seen_by_sec,
        "gaze_side",
        0.7,
    )
    states = gaze_side_seg["states"]
    events.extend(gaze_side_seg["events"])
    gaze_side_total_sec = gaze_side_seg["total_sec"]
    gaze_side_count = gaze_side_seg["count"]

    drowsy_seg = _mark_state_segments(
        states,
        drowsy_seen_by_sec,
        "drowsy",
        0.9,
    )
    states = drowsy_seg["states"]
    events.extend(drowsy_seg["events"])
    drowsy_total_sec = drowsy_seg["total_sec"]
    drowsy_count = drowsy_seg["count"]

    gaze_down_seg = _mark_state_segments(
        states,
        gaze_down_seen_by_sec,
        "gaze_down",
        0.5,
    )
    states = gaze_down_seg["states"]
    events.extend(gaze_down_seg["events"])
    gaze_down_total_sec = gaze_down_seg["total_sec"]
    gaze_down_count = gaze_down_seg["count"]

    bad_posture_total_sec = 0
    for t in range(duration_sec):
        if states[t] == "focus" and bad_posture_seen_by_sec[t]:
            states[t] = "bad_posture"
            bad_posture_total_sec += 1

    unknown_total_sec = 0
    unknown_count = 0
    if config.enable_unknown_state:
        for t in range(duration_sec):
            if states[t] == "focus" and (not face_seen_by_sec[t]):
                unknown_seen_by_sec[t] = True

        unknown_seg = _mark_state_segments(
            states,
            unknown_seen_by_sec,
            "unknown",
            0.0,
        )
        states = unknown_seg["states"]
        events.extend(unknown_seg["events"])
        unknown_total_sec = unknown_seg["total_sec"]
        unknown_count = unknown_seg["count"]

    rule_states = list(states)
    classifier_bundle = _load_optional_classifier(config, warnings)
    model_state_by_sec: List[Optional[str]] = [None] * max(duration_sec, 0)
    model_confidence_by_sec: List[Optional[float]] = [None] * max(duration_sec, 0)
    decision_source_by_sec: List[str] = ["rule"] * max(duration_sec, 0)
    final_states = list(rule_states)

    for t in range(duration_sec):
        feature_dict = _build_state_feature_dict(
            t,
            camera_type,
            face_seen_by_sec,
            gaze_side_seen_by_sec,
            gaze_down_seen_by_sec,
            bad_posture_seen_by_sec,
            eye_closed_seen_by_sec,
            blink_seen_by_sec,
            long_eye_closure_seen_by_sec,
            head_down_seen_by_sec,
            head_tilt_seen_by_sec,
            drowsy_seen_by_sec,
            page_turn_seen_by_sec,
            pen_fidget_seen_by_sec,
            restless_hand_seen_by_sec,
            avg_ear_by_sec,
            face_head_down_ratio_by_sec,
            face_head_tilt_ratio_by_sec,
            pose_head_drop_ratio_by_sec,
            pose_head_tilt_ratio_by_sec,
            hand_features_by_sec,
        )
        model_state, model_confidence = _predict_model_state(
            classifier_bundle,
            feature_dict,
            warnings,
            excluded_states=_RULE_ONLY_STATES,
        )
        final_state, decision_source = _decide_hybrid_state(
            rule_states[t],
            model_state,
            model_confidence,
            float(config.classifier_confidence_threshold),
        )

        model_state_by_sec[t] = model_state
        model_confidence_by_sec[t] = model_confidence
        final_states[t] = final_state
        decision_source_by_sec[t] = decision_source

    states = final_states
    events = _create_events_from_states(states)
    events.extend(_flags_to_events(page_turn_seen_by_sec, "page_turn", 0.0))
    events.extend(_flags_to_events(pen_fidget_seen_by_sec, "pen_fidget", 0.25))
    events.extend(_flags_to_events(restless_hand_seen_by_sec, "restless_hand", 0.35))
    events.sort(key=lambda x: (x.get("start_sec", 0), x.get("end_sec", 0), x.get("type", "")))

    def _count_final_state(state_name: str) -> tuple[int, int]:
        return _count_segments([state == state_name for state in states])

    gaze_side_count, gaze_side_total_sec = _count_final_state("gaze_side")
    gaze_down_count, gaze_down_total_sec = _count_final_state("gaze_down")
    drowsy_count, drowsy_total_sec = _count_final_state("drowsy")
    absent_count, absent_total_sec = _count_final_state("absent")
    unknown_count, unknown_total_sec = _count_final_state("unknown")
    bad_posture_count, bad_posture_total_sec = _count_final_state("bad_posture")
    sleep_suspect_count, sleep_suspect_total_sec = _count_segments(
        [
            sleep_suspect_seen_by_sec[t] and states[t] == "drowsy"
            for t in range(duration_sec)
        ]
    )

    bad_posture_ratio = 0.0
    if duration_sec > 0:
        bad_posture_ratio = bad_posture_total_sec / duration_sec

    focus_total_sec = sum(1 for s in states if s == "focus")
    present_total_sec = duration_sec - absent_total_sec

    concentration_score = 100.0
    if duration_sec > 0:
        weighted_distracted_sec = (
            absent_total_sec * 1.0
            + gaze_side_total_sec * 0.8
            + drowsy_total_sec * 0.9
            + gaze_down_total_sec * 0.5
            + bad_posture_total_sec * 0.3
            + unknown_total_sec * 0.15
        )
        concentration_score = max(
            0.0,
            100.0 * (1.0 - (weighted_distracted_sec / duration_sec))
        )

    focus_ratio = 1.0
    if duration_sec > 0:
        focus_ratio = focus_total_sec / duration_sec

    away_count = gaze_side_count
    away_total_sec = gaze_side_total_sec

    blink_count, blink_total_sec = _count_segments(blink_seen_by_sec)
    long_eye_closure_count, long_eye_closure_total_sec = _count_segments(long_eye_closure_seen_by_sec)

    timeline = [
        {
            "t": t,
            "state": states[t],
            "model_state": model_state_by_sec[t],
            "model_confidence": model_confidence_by_sec[t],
            "rule_state": rule_states[t],
            "decision_source": decision_source_by_sec[t],
            "states": _build_active_states_for_sec(
                t,
                states[t],
                gaze_side_seen_by_sec,
                gaze_down_seen_by_sec,
                bad_posture_seen_by_sec,
                drowsy_seen_by_sec,
                page_turn_seen_by_sec,
                pen_fidget_seen_by_sec,
                restless_hand_seen_by_sec,
            ),
            "flags": {
                "face_seen": face_seen_by_sec[t],
                "pose_seen": pose_seen_by_sec[t],
                "hand_seen": hand_seen_by_sec[t],
                "hand_path_len": round(float(hand_features_by_sec[t].get("path_len", 0.0)), 4),
                "hand_net_disp": round(float(hand_features_by_sec[t].get("net_disp", 0.0)), 4),
                "hand_bbox_diag": round(float(hand_features_by_sec[t].get("bbox_diag", 0.0)), 4),
                "hand_dir_changes": round(float(hand_features_by_sec[t].get("dir_changes", 0.0)), 4),
                "gaze_side": gaze_side_seen_by_sec[t],
                "gaze_down": gaze_down_seen_by_sec[t],
                "bad_posture": bad_posture_seen_by_sec[t],
                "eye_closed": eye_closed_seen_by_sec[t],
                "blink": blink_seen_by_sec[t],
                "long_eye_closure": long_eye_closure_seen_by_sec[t],
                "head_down": head_down_seen_by_sec[t],
                "head_tilt": head_tilt_seen_by_sec[t],
                "raw_drowsy": raw_drowsy_seen_by_sec[t] or sleep_suspect_seen_by_sec[t],
                "drowsy": drowsy_seen_by_sec[t] or sleep_suspect_seen_by_sec[t],
                "sleep_suspect": sleep_suspect_seen_by_sec[t] and states[t] == "drowsy",
                "page_turn": page_turn_seen_by_sec[t],
                "pen_fidget": pen_fidget_seen_by_sec[t],
                "restless_hand": restless_hand_seen_by_sec[t],
                "unknown": states[t] == "unknown",
                "absent": states[t] == "absent",
            },
            "drowsy_evidence": {
                "right_ear": round(float(right_ear_by_sec[t]), 5) if right_ear_by_sec[t] is not None else None,
                "left_ear": round(float(left_ear_by_sec[t]), 5) if left_ear_by_sec[t] is not None else None,
                "avg_ear": round(float(avg_ear_by_sec[t]), 5) if avg_ear_by_sec[t] is not None else None,
                "right_open_baseline": round(float(right_ear_baseline), 5) if right_ear_baseline is not None else None,
                "left_open_baseline": round(float(left_ear_baseline), 5) if left_ear_baseline is not None else None,
                "right_close_threshold": round(float(right_close_threshold), 5) if right_close_threshold is not None else None,
                "left_close_threshold": round(float(left_close_threshold), 5) if left_close_threshold is not None else None,
                "right_reopen_threshold": round(float(right_reopen_threshold), 5) if right_reopen_threshold is not None else None,
                "left_reopen_threshold": round(float(left_reopen_threshold), 5) if left_reopen_threshold is not None else None,
                "both_eyes_closed": eye_closed_seen_by_sec[t],
                "continuous_eye_closed_sec": int(eye_closure_duration_by_sec[t]),
                "head_motion": round(float(head_motion_by_sec[t]), 5) if head_motion_by_sec[t] is not None else None,
                "low_head_motion": low_head_motion_seen_by_sec[t],
                "minimum_eye_closed_sec": int(config.long_eye_closure_min_sec),
                "rule": "both_eyes_closed_10s_and_low_head_motion",
            },
        }
        for t in range(duration_sec)
    ]

    return _finalize_analysis_result({
        "session_id": session_id,
        "status": "success",
        "meta": {
            "camera_type": camera_type,
            "sampling_fps": config.sampling_fps,
            "video_fps": fps,
            "duration_sec": duration_sec,
            "processed_frames": processed_frames,
            "processing_time_sec": int(time.time() - started),
            "version": config.version,
            "warnings": warnings,
            "model_path": model_path,
            "drowsy_config": {
                "both_eyes_required": True,
                "minimum_eye_closed_sec": int(config.long_eye_closure_min_sec),
                "ear_baseline_ratio": float(config.ear_baseline_ratio),
                "ear_reopen_baseline_ratio": float(config.ear_reopen_baseline_ratio),
                "head_motion_threshold": float(config.drowsy_head_motion_threshold),
                "activity_window_sec": int(config.drowsy_activity_window_sec),
                "reading_state_enabled": False,
            },
        },
        "summary": {
            "focus_ratio": float(focus_ratio),
            "focus_total_sec": int(focus_total_sec),
            "present_total_sec": int(present_total_sec),
            "gaze_side_count": int(gaze_side_count),
            "gaze_side_total_sec": int(gaze_side_total_sec),
            "gaze_down_count": int(gaze_down_count),
            "gaze_down_total_sec": int(gaze_down_total_sec),
            "drowsy_count": int(drowsy_count),
            "drowsy_total_sec": int(drowsy_total_sec),
            "sleep_suspect_count": int(sleep_suspect_count),
            "sleep_suspect_total_sec": int(sleep_suspect_total_sec),
            "eye_closed_total_sec": int(sum(1 for x in eye_closed_seen_by_sec if x)),
            "blink_count": int(blink_count),
            "blink_total_sec": int(blink_total_sec),
            "long_eye_closure_count": int(long_eye_closure_count),
            "long_eye_closure_total_sec": int(long_eye_closure_total_sec),
            "head_down_total_sec": int(sum(1 for x in head_down_seen_by_sec if x)),
            "head_tilt_total_sec": int(sum(1 for x in head_tilt_seen_by_sec if x)),
            "away_count": int(away_count),
            "away_total_sec": int(away_total_sec),
            "unknown_count": int(unknown_count),
            "unknown_total_sec": int(unknown_total_sec),
            "absent_count": int(absent_count),
            "absent_total_sec": int(absent_total_sec),
            "bad_posture_ratio": float(bad_posture_ratio),
            "bad_posture_count": int(bad_posture_count),
            "bad_posture_total_sec": int(bad_posture_total_sec),
            "concentration_score": round(float(concentration_score), 1),
            "page_turn_count": int(_count_segments(page_turn_seen_by_sec)[0]),
            "page_turn_total_sec": int(_count_segments(page_turn_seen_by_sec)[1]),
            "pen_fidget_count": int(_count_segments(pen_fidget_seen_by_sec)[0]),
            "pen_fidget_total_sec": int(_count_segments(pen_fidget_seen_by_sec)[1]),
            "restless_hand_count": int(_count_segments(restless_hand_seen_by_sec)[0]),
            "restless_hand_total_sec": int(_count_segments(restless_hand_seen_by_sec)[1]),
        },
        "timeline": timeline,
        "events": events,
    })


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("video_path", help="좌측 얼굴 + 우측 손/책상 합본 영상 경로")
    parser.add_argument("--session-id", default="S001", help="세션 ID")
    args = parser.parse_args()

    print("RUNNING VERSION:", AnalyzeConfig().version)
    print("VIDEO PATH:", args.video_path)
    print("SESSION ID:", args.session_id)

    result = analyze_merged_video(
        args.session_id,
        args.video_path,
        AnalyzeConfig(),
    )

    save_analysis_to_db(args.session_id, result)
    print(result["summary"])
