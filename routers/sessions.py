from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form, Request
from sqlalchemy.orm import Session
from typing import List
from datetime import datetime, timezone, timedelta
import boto3
import json
import models, schemas
from database import get_db
from time_utils import as_local_naive_datetime, calculate_duration_sec, normalize_session_end_time
# Adjust this import path depending on where your analyze.py is located!
from ai.focus_ai.analyze import _finalize_analysis_result
from ai.focus_ai.analyze import _create_events_from_states 
from ai.analyzer.focus_score import calculate_focus_score
from ai.focus_ai.feedback_generator import generate_personal_feedback_payload, generate_feedback
from dotenv import load_dotenv
load_dotenv() 

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
    session = db.query(models.FocusSession).filter(models.FocusSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="해당 세션을 찾을 수 없습니다.")
    
    try:
        # FIX: Ignore the frontend's UTC string. Use the perfectly synced EC2 KST clock, 
        # exactly matching the logic used in start_session!
        session.end_time = as_local_naive_datetime(datetime.now().astimezone())
        
        # FIX: Trust the highly accurate client-side stopwatch, fallback to backend calculation only if missing
        if getattr(session_data, "duration_sec", None) is not None:
            session.duration_sec = session_data.duration_sec
        else:
            session.duration_sec = calculate_duration_sec(session.start_time, session.end_time)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    session.status = session_data.status
    
    db.commit()
    db.refresh(session)
    
    return session

@router.post("/{session_id}/timeline", status_code=status.HTTP_201_CREATED)
async def save_session_timeline(session_id: str, request: Request, db: Session = Depends(get_db)):
    # 1. Catch the full JSON payload
    payload = await request.json()
    timeline_data = payload.get("timeline", [])
    
    if not timeline_data:
        return {"message": "저장할 타임라인 데이터가 없습니다."}

    duration_sec = len(timeline_data)
    
    states = [item.get("state", "focus") for item in timeline_data]
    events = _create_events_from_states(states)

    def count_state(target_state):
        return sum(1 for s in states if s == target_state)
        
    def count_events(target_type):
        return sum(1 for e in events if e["type"] == target_type)

    # NEW: Helper function to accurately extract flags from the timeline array
    def count_flag(flag_name):
        return sum(1 for item in timeline_data if item.get("flags", {}).get(flag_name))

    # FIX: Helper function to count segments (events) rather than raw seconds
    def count_flag_segments(flag_name):
        count = 0
        in_seg = False
        for item in timeline_data:
            flag_val = item.get("flags", {}).get(flag_name, False)
            if flag_val and not in_seg:
                count += 1
                in_seg = True
            elif not flag_val:
                in_seg = False
        return count

    absent_sec = count_state("absent")

    # 2. Build the Raw Summary with ALL required metrics
    raw_summary = {
        "focus_total_sec": count_state("focus"),
        "bad_posture_total_sec": count_state("bad_posture"),
        "gaze_side_total_sec": count_state("gaze_side"),
        "gaze_down_total_sec": count_state("gaze_down"),
        "away_total_sec": count_state("gaze_side") + count_state("gaze_down") + count_state("gaze_away"),
        "drowsy_total_sec": count_state("drowsy"),
        "absent_total_sec": absent_sec,
        "unknown_total_sec": count_state("unknown"),
        "present_total_sec": duration_sec - absent_sec,
        "bad_posture_count": count_events("bad_posture"),
        "gaze_side_count": count_events("gaze_side"),
        "gaze_down_count": count_events("gaze_down"),
        "away_count": count_events("gaze_side") + count_events("gaze_down") + count_events("gaze_away"),
        "drowsy_count": count_events("drowsy"),
        "absent_count": count_events("absent"),
        "unknown_count": count_events("unknown"),
        
        # FIX: Ensure accurate flag tracking for the feedback generator
        "eye_closed_total_sec": count_flag("eye_closed"),
        "long_eye_closure_count": count_flag_segments("long_eye_closure"), # Now correctly counts events
        "head_down_total_sec": count_flag("head_down"),
        "head_tilt_total_sec": count_flag("head_tilt"),
        "sleep_suspect_total_sec": count_flag("sleep_suspect") # Added missing metric
    }

    # 3. EXPLICITLY EXECUTE THE AI ENGINES
    formatted_timeline = []
    for item in timeline_data:
        formatted_timeline.append({
            "t": int(item.get("t", 0)),
            "state": str(item.get("state", "focus")),
            "decision_source": str(item.get("decision_source", "rule")),
            "states": item.get("states", [item.get("state", "focus")]),
            "flags": item.get("flags", {})
        })

    # FIX: Added "status": "success" so the finalize logic knows it's safe to process
    raw_result = {
        "session_id": session_id,
        "status": "success", 
        "meta": {"duration_sec": duration_sec},
        "summary": raw_summary, 
        "timeline": formatted_timeline, 
        "events": events
    }

    # FIX: Route the raw data through the finalized pipeline!
    # This automatically generates the 5-minute time_patterns, scores the summary, and builds the feedback
    final_result = _finalize_analysis_result(raw_result)

    # Extract the properly processed dictionaries
    scored_summary = final_result.get("summary", {})
    pf_dict = final_result.get("personal_feedback")
    feedback_dict = final_result.get("feedback")
    
    # 4. Clear old records to prevent database locks
    db.query(models.AnalysisTimeline).filter(models.AnalysisTimeline.session_id == str(session_id)).delete()
    db.query(models.AnalysisEvent).filter(models.AnalysisEvent.session_id == str(session_id)).delete()
    db.query(models.AnalysisSummary).filter(models.AnalysisSummary.session_id == str(session_id)).delete()
    db.commit() 

    # 5. Insert Timeline
    timeline_records = [
        models.AnalysisTimeline(session_id=str(session_id), t=int(item["t"]), state=str(item["state"]))
        for item in timeline_data
    ]
    db.add_all(timeline_records)
    db.flush() 

    # 6. Insert Events
    event_records = [
        models.AnalysisEvent(
            session_id=str(session_id),
            event_type=e["type"],
            start_sec=e["start_sec"],
            end_sec=e["end_sec"],
            score=e["score"]
        )
        for e in events
    ]
    db.add_all(event_records)

    # 7. Insert Summary
    summary_record = models.AnalysisSummary(
        session_id=str(session_id),
        focus_ratio=scored_summary.get("focus_score", 0) / 100.0, 
        absent_count=scored_summary.get("absent_count", 0),
        absent_total_sec=scored_summary.get("absent_total_sec", 0),
        away_count=scored_summary.get("away_count", 0),
        away_total_sec=scored_summary.get("away_total_sec", 0),
        bad_posture_ratio=scored_summary.get("bad_posture_total_sec", 0) / max(duration_sec, 1),
        processing_time_sec=0,
        camera_type="edge_web",
        version="ai-edge-1.0"
    )
    db.add(summary_record)

    # 8. Format & Insert AI Feedback
    if not feedback_dict:
        feedback_dict = {}
        
    feedback_text = "\n".join(
        str(feedback_dict.get(key)).strip()
        for key in ("summary_text", "weak_point", "recommendation")
        if feedback_dict.get(key)
    )

    # FIX: Remove json.dumps. SQLAlchemy will automatically cast this python dictionary safely into the DB!
    existing_feedback = db.query(models.AnalysisFeedback).filter(models.AnalysisFeedback.session_id == str(session_id)).first()
    if existing_feedback:
        existing_feedback.feedback_text = feedback_text
        existing_feedback.personal_feedback = pf_dict 
        # FIX: Pull source and version directly from final_result instead of the deleted feedback_payload
        existing_feedback.feedback_source = final_result.get("feedback_source")
        existing_feedback.feedback_version = final_result.get("feedback_version")
    else:
        new_feedback = models.AnalysisFeedback(
            session_id=str(session_id),
            feedback_text=feedback_text,
            personal_feedback=pf_dict,
            # FIX: Pull source and version directly from final_result
            feedback_source=final_result.get("feedback_source"),
            feedback_version=final_result.get("feedback_version")
        )
        db.add(new_feedback)

    db.commit()

    return {"message": "Edge AI analysis processed and saved successfully!"}

@router.get("/user/{user_id}", response_model=List[schemas.SessionResponse])
def get_user_sessions(user_id: int, db: Session = Depends(get_db)):
    """특정 유저의 모든 집중 세션 기록을 조회합니다."""
    sessions = db.query(models.FocusSession).filter(models.FocusSession.user_id == user_id).all()
    return sessions
