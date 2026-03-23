from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import cv2
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision


@dataclass
class AnalyzeConfig:
    sampling_fps: int = 5
    absent_threshold_sec: int = 5
    min_face_confidence: float = 0.5
    away_ratio_threshold: float = 0.35
    enable_bad_posture: bool = True
    posture_shoulder_threshold: float = 0.12
    posture_tilt_threshold: float = 0.18
    version: str = "ai-0.2.1"


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
    timeline = [{"t": t, "state": "focus"} for t in range(duration_sec)]

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
            "away_count": 0,
            "away_total_sec": 0,
            "absent_count": 0,
            "absent_total_sec": 0,
            "bad_posture_ratio": 0.0,
        },
        "timeline": timeline,
        "events": [],
    }

def _is_away_from_landmarks(landmarks: List[Any], away_ratio_threshold:float) -> bool:
    # MediaPipe face mesh의 대표 인덱스를 사용하는 간단 휴리스틱
    # nose tip: 1, left eye outer: 33, right eye outer: 263
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
        end = t  # exclusive

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

def _create_face_landmarker(model_path: str, min_conf: float)->vision.FaceLandmarker:
    with open(model_path, "rb") as f:
        model_bytes = f.read()
    try:
        base_options = python.BaseOptions(model_asset_buffer=model_bytes)
    except TypeError:
        base_options = python.BaseOptions(model_asset_path = model_path)
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

def _is_bad_posture_from_pose(landmarks:List[Any], shoulder_threshold: float, tilt_threshold:float) -> bool:
     # pose landmark index
    # 11: left shoulder, 12: right shoulder, 0: nose
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
    face_seen_by_sec = [False] * max(duration_sec, 0)
    away_seen_by_sec = [False] * max(duration_sec, 0)
    bad_posture_seen_by_sec = [False] * max(duration_sec, 0)

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
        if config.enable_bad_posture and os.path.exists(pose_model_path):
            pose_detector = _create_pose_landmarker(pose_model_path)
        else:
            if config.enable_bad_posture:
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
                    # 큰 영상이면 축소해서 속도 확보
                    h, w = frame.shape[:2]
                    if w > 960:
                        scale = 960 / w
                        frame = cv2.resize(frame, (int(w * scale), int(h * scale)))

                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)

                    timestamp_ms = int((frame_idx/fps)*1000) if fps > 0 else 0
                    detection_result = face_detector.detect_for_video(mp_image, timestamp_ms)
                    if detection_result.face_landmarks:
                        face_seen_by_sec[sec] = True

                        landmarks = detection_result.face_landmarks[0]
                        if _is_away_from_landmarks(landmarks, config.away_ratio_threshold):
                            away_seen_by_sec[sec] = True
                    if pose_detector is not None:
                        pose_result = pose_detector.detect_for_video(mp_image, timestamp_ms)
                        if pose_result.pose_landmarks:
                            pose_landmarks = pose_result.pose_landmarks[0]
                            if _is_bad_posture_from_pose(
                                pose_landmarks,
                                config.posture_shoulder_threshold,
                                config.posture_tilt_threshold,
                            ):
                                bad_posture_seen_by_sec[sec] = True

            frame_idx += 1

    except RuntimeError as e:
        # 모델 open 실패 같은 네이티브 에러가 여기로 들어옴
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

    seg = _mark_absent_segments(face_seen_by_sec, int(config.absent_threshold_sec))
    states = seg["states"]
    events = seg["events"]
    absent_total_sec = seg["absent_total_sec"]
    absent_count = seg["absent_count"]

    away_count = 0
    away_total_sec =0
    in_away=False
    away_start =0

    for t in range(duration_sec):
        if states[t] != "absent" and away_seen_by_sec[t]:
            states[t] = "away"
            away_total_sec +=1
            if not in_away:
                in_away= True
                away_start = t
        else:
            if in_away:
                events.append(
                    {
                        "type": "away",
                        "start_sec": away_start,
                        "end_sec": t,
                        "score": 0.7
                    }
                )
                away_count +=1
                in_away = False
    if in_away:
        events.append(
            {
                "type": "away",
                "start_sec": away_start,
                "end_sec": duration_sec,
                "score":0.7
            }
        )
        away_count +=1
    bad_posture_total_sec = 0

    for t in range(duration_sec):
        if states[t] == "focus" and bad_posture_seen_by_sec[t]:
            states[t] = "bad_posture"
            bad_posture_total_sec += 1

    bad_posture_ratio = 0.0
    if duration_sec > 0:
        bad_posture_ratio = bad_posture_total_sec/duration_sec

    timeline = [{"t": t, "state": states[t]} for t in range(duration_sec)]

    focus_ratio = 1.0
    if duration_sec > 0:
        distracted_total_sec = absent_total_sec + away_total_sec
        focus_ratio = max(0.0, 1.0 - (distracted_total_sec/duration_sec))

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
            "away_count": int(away_count),
            "away_total_sec": int(away_total_sec),
            "absent_count": int(absent_count),
            "absent_total_sec": int(absent_total_sec),
            "bad_posture_ratio": float(bad_posture_ratio),
        },
        "timeline": timeline,
        "events": events,
    }
if __name__ == "__main__":
    result = analyze_absent(
        "S001",
        "C:/Users/wkdgu/Videos/Captures/testaway.mp4",
        "front",
        AnalyzeConfig()
        )
    print(result)