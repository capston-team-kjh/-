from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from sqlalchemy.orm import Session
from typing import List
from datetime import datetime, timezone, timedelta
import boto3
import json
import models, schemas
from database import get_db
from time_utils import as_local_naive_datetime, calculate_duration_sec, normalize_session_end_time
# Adjust this import path depending on where your analyze.py is located!
from ai.focus_ai.analyze import _finalize_analysis_result, _create_events_from_states

# 라우터 설정
router = APIRouter(
    prefix="/api/v1/sessions",
    tags=["Sessions (집중 세션 관리)"]
)

SQS_QUEUE_URL = "https://sqs.ap-northeast-2.amazonaws.com/003344631039/joljak-video-queue.fifo"
S3_BUCKET_NAME = "jolljak-storage-2026"

s3_client = boto3.client('s3', region_name='ap-northeast-2')
sqs_client = boto3.client('sqs', region_name='ap-northeast-2')

@router.post("/", response_model=schemas.SessionResponse, status_code=status.HTTP_201_CREATED)
def start_session(session_data: schemas.SessionCreate, db: Session = Depends(get_db)):
    """새로운 집중 세션을 시작합니다."""
    # 유저가 실제로 존재하는지 확인
    user = db.query(models.User).filter(models.User.id == session_data.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="해당 유저를 찾을 수 없습니다.")
    
    # 2. 새 세션 생성
    new_session = models.FocusSession(
        user_id=session_data.user_id,
        start_time=as_local_naive_datetime(datetime.now().astimezone()),
        duration_sec=None,
    )
    
    # DB에 저장
    db.add(new_session)
    db.commit()
    db.refresh(new_session)
    
    return new_session

@router.patch("/{session_id}", response_model=schemas.SessionResponse)
def update_session(session_id: int, session_data: schemas.SessionUpdate, db: Session = Depends(get_db)):
    """진행 중인 집중 세션을 종료하거나 상태를 업데이트합니다."""
    # 1. 업데이트할 세션 찾기
    session = db.query(models.FocusSession).filter(models.FocusSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="해당 세션을 찾을 수 없습니다.")
    
    # 2. 데이터 업데이트 (종료 시간 및 상태 반영)
    try:
        session.end_time = normalize_session_end_time(session.start_time, session_data.end_time)
        session.duration_sec = calculate_duration_sec(session.start_time, session.end_time)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    session.status = session_data.status
    
    db.commit()
    db.refresh(session)
    
    return session

@router.post("/{session_id}/timeline", status_code=status.HTTP_201_CREATED)
def save_session_timeline(session_id: str, payload: schemas.TimelineBulkCreate, db: Session = Depends(get_db)):
    
    # 1. Strictly validated Pydantic data
    timeline_data = payload.timeline
    if not timeline_data:
        return {"message": "저장할 타임라인 데이터가 없습니다."}

    duration_sec = len(timeline_data)
    
    # Extract states using strict object notation instead of .get()
    states = [item.state for item in timeline_data]
    events = _create_events_from_states(states)

    def count_state(target_state):
        return sum(1 for s in states if s == target_state)
        
    def count_events(target_type):
        return sum(1 for e in events if e["type"] == target_type)

    absent_sec = count_state("absent")
    away_sec = count_state("gaze_side")
    bad_posture_sec = count_state("bad_posture")

    # Re-pack the timeline into dicts for your AI analysis engine
    raw_result = {
        "session_id": session_id,
        "status": "success",
        "meta": {
            "duration_sec": duration_sec,
            "camera_type": "edge_web",
            "version": "ai-edge-1.0",
            "processing_time_sec": 0
        },
        "summary": {
            "focus_total_sec": count_state("focus"),
            "bad_posture_total_sec": bad_posture_sec,
            "gaze_side_total_sec": count_state("gaze_side"),
            "gaze_down_total_sec": count_state("gaze_down"),
            "away_total_sec": away_sec,
            "drowsy_total_sec": count_state("drowsy"),
            "absent_total_sec": absent_sec,
            "unknown_total_sec": count_state("unknown"),
            "present_total_sec": duration_sec - absent_sec,
            "bad_posture_count": count_events("bad_posture"),
            "gaze_side_count": count_events("gaze_side"),
            "gaze_down_count": count_events("gaze_down"),
            "away_count": count_events("gaze_side"),
            "drowsy_count": count_events("drowsy"),
            "absent_count": count_events("absent"),
            "unknown_count": count_events("unknown")
        },
        "timeline": [item.model_dump() for item in timeline_data], 
        "events": events
    }

    finalized = _finalize_analysis_result(raw_result)
    final_summary = finalized.get("summary", {})
    feedback_dict = finalized.get("feedback", {})
    
    real_focus_score = final_summary.get("focus_score", 0)
    hybrid_focus_ratio = real_focus_score / 100.0
    
    # Delete old records
    db.query(models.AnalysisTimeline).filter(models.AnalysisTimeline.session_id == session_id).delete()
    db.query(models.AnalysisEvent).filter(models.AnalysisEvent.session_id == session_id).delete()
    db.query(models.AnalysisSummary).filter(models.AnalysisSummary.session_id == session_id).delete()

    # --- FIX 1: HIGH-SPEED BULK INSERT ---
    # Map data to ORM objects and bypass the heavy session tracking
    timeline_records = [
        models.AnalysisTimeline(session_id=session_id, t=item.t, state=item.state)
        for item in timeline_data
    ]
    db.bulk_save_objects(timeline_records)

    # Insert Events
    event_records = [
        models.AnalysisEvent(
            session_id=session_id,
            event_type=e["type"],
            start_sec=e["start_sec"],
            end_sec=e["end_sec"],
            score=e["score"]
        )
        for e in events
    ]
    db.add_all(event_records)

    # Insert Summary
    summary_record = models.AnalysisSummary(
        session_id=session_id,
        focus_ratio=hybrid_focus_ratio, 
        absent_count=final_summary.get("absent_count", 0),
        absent_total_sec=final_summary.get("absent_total_sec", 0),
        away_count=final_summary.get("away_count", 0),
        away_total_sec=final_summary.get("away_total_sec", 0),
        bad_posture_ratio=final_summary.get("bad_posture_ratio", 0),
        processing_time_sec=0,
        camera_type="edge_web",
        version="ai-edge-1.0"
    )
    db.add(summary_record)

    # Insert Feedback 
    feedback_text = "\n".join(
        str(feedback_dict.get(key)).strip()
        for key in ("summary_text", "weak_point", "recommendation")
        if feedback_dict.get(key)
    )

    existing_feedback = db.query(models.AnalysisFeedback).filter(models.AnalysisFeedback.session_id == session_id).first()
    if existing_feedback:
        existing_feedback.feedback_text = feedback_text
        existing_feedback.personal_feedback = finalized.get("personal_feedback")
        existing_feedback.feedback_source = finalized.get("feedback_source")
        existing_feedback.feedback_version = finalized.get("feedback_version")
    else:
        new_feedback = models.AnalysisFeedback(
            session_id=session_id,
            feedback_text=feedback_text,
            personal_feedback=finalized.get("personal_feedback"),
            feedback_source=finalized.get("feedback_source"),
            feedback_version=finalized.get("feedback_version")
        )
        db.add(new_feedback)

    db.commit()

    return {"message": "Edge AI analysis processed and saved successfully!"}

@router.get("/user/{user_id}", response_model=List[schemas.SessionResponse])
def get_user_sessions(user_id: int, db: Session = Depends(get_db)):
    """특정 유저의 모든 집중 세션 기록을 조회합니다."""
    sessions = db.query(models.FocusSession).filter(models.FocusSession.user_id == user_id).all()
    return sessions
