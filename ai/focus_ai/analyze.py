
from __future__ import annotations

import csv
import os
import time
import argparse
import statistics
import tempfile
import shutil
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import pymysql
import cv2
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision


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
    drowsy_score_threshold: float = 0.90
    drowsy_min_duration_sec: int = 2

    # baseline / 보정
    baseline_duration_sec: int = 5
    ear_baseline_ratio: float = 0.72
    face_head_down_threshold: float = 0.72
    face_head_down_offset: float = 0.10
    pose_head_drop_margin: float = 0.10

    # blink / long eye closure
    blink_max_duration_sec: int = 1
    long_eye_closure_min_sec: int = 2

    # 상태 최소 지속 시간(초)
    gaze_side_min_duration_sec: int = 2
    gaze_down_min_duration_sec: int = 2
    bad_posture_min_duration_sec: int = 2
    enable_unknown_state: bool = True

    version: str = "ai-0.2.4"


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
        return {
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
        }

    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps is None or fps <= 0:
        fps = 30.0

    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    if width < 2 or height < 2:
        cap.release()
        shutil.rmtree(temp_dir, ignore_errors=True)
        return {
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
        }

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
        return {
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
        }

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
        return result

    front_timeline = {item["t"]: item for item in front_result.get("timeline", [])}
    overhead_timeline = {item["t"]: item for item in overhead_result.get("timeline", [])}

    duration_sec = max(
        int(front_result.get("meta", {}).get("duration_sec", 0)),
        int(overhead_result.get("meta", {}).get("duration_sec", 0)),
    )

    final_timeline = []
    for t in range(duration_sec):
        front_item = front_timeline.get(t, {"state": "focus", "states": ["focus"], "flags": {}})
        overhead_item = overhead_timeline.get(t, {"state": "focus", "states": ["focus"], "flags": {}})

        front_state = front_item.get("state", "focus")
        front_states = _ensure_states_list(front_item)

        front_flags = front_item.get("flags", {})
        overhead_flags = overhead_item.get("flags", {})

        if front_state == "absent":
            final_state = "absent"
        elif front_state == "drowsy":
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
            merged_states = ["absent"]
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

        final_timeline.append(
            {
                "t": t,
                "state": final_state,
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
                    "raw_drowsy": front_flags.get("raw_drowsy", False),
                    "drowsy": front_flags.get("drowsy", False),
                    "page_turn": overhead_flags.get("page_turn", False),
                    "pen_fidget": overhead_flags.get("pen_fidget", False),
                    "restless_hand": overhead_flags.get("restless_hand", False),
                    "unknown": front_flags.get("unknown", False),
                    "absent": front_flags.get("absent", False),
                },
            }
        )

    def _count_state(state_name: str) -> tuple[int, int]:
        flags = [item["state"] == state_name for item in final_timeline]
        return _count_segments(flags)

    focus_total_sec = sum(1 for item in final_timeline if item["state"] == "focus")
    focus_ratio = (focus_total_sec / duration_sec) if duration_sec > 0 else 0.0

    gaze_side_count, gaze_side_total_sec = _count_state("gaze_side")
    gaze_down_count, gaze_down_total_sec = _count_state("gaze_down")
    drowsy_count, drowsy_total_sec = _count_state("drowsy")
    absent_count, absent_total_sec = _count_state("absent")
    _, bad_posture_total_sec = _count_state("bad_posture")

    front_summary = front_result.get("summary", {})
    overhead_summary = overhead_result.get("summary", {})

    merged_events = []
    for event in front_result.get("events", []):
        e = dict(event)
        e["source"] = "front"
        merged_events.append(e)

    for event in overhead_result.get("events", []):
        e = dict(event)
        e["source"] = "overhead"
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
            "warnings": [],
        },
        "summary": {
            "focus_ratio": round(float(focus_ratio), 4),
            "focus_total_sec": int(focus_total_sec),
            "present_total_sec": int(front_summary.get("present_total_sec", duration_sec)),
            "gaze_side_count": int(gaze_side_count),
            "gaze_side_total_sec": int(gaze_side_total_sec),
            "gaze_down_count": int(gaze_down_count),
            "gaze_down_total_sec": int(gaze_down_total_sec),
            "drowsy_count": int(drowsy_count),
            "drowsy_total_sec": int(drowsy_total_sec),
            "eye_closed_total_sec": int(front_summary.get("eye_closed_total_sec", 0)),
            "blink_count": int(front_summary.get("blink_count", 0)),
            "blink_total_sec": int(front_summary.get("blink_total_sec", 0)),
            "long_eye_closure_count": int(front_summary.get("long_eye_closure_count", 0)),
            "long_eye_closure_total_sec": int(front_summary.get("long_eye_closure_total_sec", 0)),
            "head_down_total_sec": int(front_summary.get("head_down_total_sec", 0)),
            "head_tilt_total_sec": int(front_summary.get("head_tilt_total_sec", 0)),
            "away_count": int(gaze_side_count),
            "away_total_sec": int(gaze_side_total_sec),
            "unknown_count": int(front_summary.get("unknown_count", 0)),
            "unknown_total_sec": int(front_summary.get("unknown_total_sec", 0)),
            "absent_count": int(absent_count),
            "absent_total_sec": int(absent_total_sec),
            "bad_posture_ratio": round((bad_posture_total_sec / duration_sec), 4) if duration_sec > 0 else 0.0,
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
    return result


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
        return {
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
        }

    duration_sec: int = meta["duration_sec"]
    processed_frames = duration_sec * config.sampling_fps

    timeline = [
        {
            "t": t,
            "state": "focus",
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

    return {
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
    }


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


def _mark_absent_segments(
    face_seen_by_sec: List[bool],
    absent_threshold_sec: int,
) -> Dict[str, Any]:
    duration_sec = len(face_seen_by_sec)
    states = ["focus"] * duration_sec
    events: List[Dict[str, Any]] = []

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
                states[k] = "absent"
            events.append(
                {
                    "type": "absent",
                    "start_sec": start,
                    "end_sec": end,
                    "score": 1.0,
                }
            )

    absent_total_sec = sum(1 for s in states if s == "absent")
    absent_count = len(events)

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
        return {
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
        }

    fps: float = meta["video_fps"]
    duration_sec: int = meta["duration_sec"]

    use_hand_actions = (
        config.enable_hand_actions
        and str(camera_type).lower() in {"top", "overhead", "desk", "topdown"}
    )

    face_seen_by_sec = [False] * max(duration_sec, 0)
    gaze_side_seen_by_sec = [False] * max(duration_sec, 0)
    gaze_down_seen_by_sec = [False] * max(duration_sec, 0)
    bad_posture_seen_by_sec = [False] * max(duration_sec, 0)
    unknown_seen_by_sec = [False] * max(duration_sec, 0)

    eye_closed_seen_by_sec = [False] * max(duration_sec, 0)
    head_down_seen_by_sec = [False] * max(duration_sec, 0)
    head_tilt_seen_by_sec = [False] * max(duration_sec, 0)
    raw_drowsy_seen_by_sec = [False] * max(duration_sec, 0)
    drowsy_seen_by_sec = [False] * max(duration_sec, 0)

    avg_ear_by_sec: List[Optional[float]] = [None] * max(duration_sec, 0)
    face_head_down_ratio_by_sec: List[Optional[float]] = [None] * max(duration_sec, 0)
    face_head_tilt_ratio_by_sec: List[Optional[float]] = [None] * max(duration_sec, 0)
    pose_head_drop_ratio_by_sec: List[Optional[float]] = [None] * max(duration_sec, 0)
    pose_head_tilt_ratio_by_sec: List[Optional[float]] = [None] * max(duration_sec, 0)

    blink_seen_by_sec = [False] * max(duration_sec, 0)
    long_eye_closure_seen_by_sec = [False] * max(duration_sec, 0)

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

    model_path = _resolve_model_path()
    if not os.path.exists(model_path):
        return {
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
        }

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return {
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
        }

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
                            avg_ear_by_sec[sec] = drowsy_face["avg_ear"]
                            face_head_down_ratio_by_sec[sec] = drowsy_face["face_head_down_ratio"]
                            face_head_tilt_ratio_by_sec[sec] = drowsy_face["face_head_tilt_ratio"]

                    if pose_detector is not None:
                        pose_result = pose_detector.detect_for_video(mp_image, timestamp_ms)
                        if pose_result.pose_landmarks:
                            pose_landmarks = pose_result.pose_landmarks[0]

                            if use_hand_actions and 0 <= sec < duration_sec:
                                for wrist_idx, hand_key in ((15, "left"), (16, "right")):
                                    wrist = pose_landmarks[wrist_idx]
                                    if _landmark_visible(wrist, config.hand_min_visibility):
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
        return {
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
        }

    finally:
        cap.release()
        if face_detector is not None:
            face_detector.close()
        if pose_detector is not None:
            pose_detector.close()

    if config.enable_drowsy and duration_sec > 0:
        baseline_sec = min(int(config.baseline_duration_sec), duration_sec)

        ear_baseline = _median_valid(avg_ear_by_sec, baseline_sec)
        face_head_down_baseline = _median_valid(face_head_down_ratio_by_sec, baseline_sec)

        effective_ear_threshold = float(config.drowsy_ear_threshold)
        if ear_baseline is not None:
            effective_ear_threshold = min(
                float(config.drowsy_ear_threshold),
                float(ear_baseline) * float(config.ear_baseline_ratio),
            )

        effective_face_head_down_threshold = float(config.face_head_down_threshold)
        if face_head_down_baseline is not None:
            effective_face_head_down_threshold = max(
                float(config.face_head_down_threshold),
                float(face_head_down_baseline) + float(config.face_head_down_offset),
            )

        for t in range(duration_sec):
            avg_ear = avg_ear_by_sec[t]
            face_head_down_ratio = face_head_down_ratio_by_sec[t]
            face_head_tilt_ratio = face_head_tilt_ratio_by_sec[t]
            pose_head_drop_ratio = pose_head_drop_ratio_by_sec[t]
            pose_head_tilt_ratio = pose_head_tilt_ratio_by_sec[t]

            if avg_ear is not None and avg_ear <= effective_ear_threshold:
                eye_closed_seen_by_sec[t] = True

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

        for t in range(duration_sec):
            drowsy_score = 0.0

            if long_eye_closure_seen_by_sec[t]:
                drowsy_score += 0.55
            if head_down_seen_by_sec[t]:
                drowsy_score += 0.20
            if head_tilt_seen_by_sec[t]:
                drowsy_score += 0.10

            if (
                (long_eye_closure_seen_by_sec[t] and head_down_seen_by_sec[t])
                or drowsy_score >= float(config.drowsy_score_threshold)
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

    seg = _mark_absent_segments(face_seen_by_sec, int(config.absent_threshold_sec))
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

    events.extend(_flags_to_events(page_turn_seen_by_sec, "page_turn", 0.0))
    events.extend(_flags_to_events(pen_fidget_seen_by_sec, "pen_fidget", 0.25))
    events.extend(_flags_to_events(restless_hand_seen_by_sec, "restless_hand", 0.35))

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
                "gaze_side": gaze_side_seen_by_sec[t],
                "gaze_down": gaze_down_seen_by_sec[t],
                "bad_posture": bad_posture_seen_by_sec[t],
                "eye_closed": eye_closed_seen_by_sec[t],
                "blink": blink_seen_by_sec[t],
                "long_eye_closure": long_eye_closure_seen_by_sec[t],
                "head_down": head_down_seen_by_sec[t],
                "head_tilt": head_tilt_seen_by_sec[t],
                "raw_drowsy": raw_drowsy_seen_by_sec[t],
                "drowsy": drowsy_seen_by_sec[t],
                "page_turn": page_turn_seen_by_sec[t],
                "pen_fidget": pen_fidget_seen_by_sec[t],
                "restless_hand": restless_hand_seen_by_sec[t],
                "unknown": states[t] == "unknown",
                "absent": states[t] == "absent",
            },
        }
        for t in range(duration_sec)
    ]

    return {
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
    }


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
