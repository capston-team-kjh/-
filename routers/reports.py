# 기존에 작성했었던 Flask API를 FastAPI로 옮긴 것
# 데이터를 정리해서 페이지에 뿌려주는 역할을 함

import json
import os
import re

from fastapi import APIRouter, Depends, HTTPException, Header, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, text
from datetime import datetime, timedelta
from typing import Any, List, Optional

import models, schemas
from database import get_db
from time_utils import calculate_duration_sec

router = APIRouter(
    prefix="/api/v1/analytics",
    tags=["Reports (학습 리포트 및 통계)"]
)


def _session_duration_sec(session: models.FocusSession) -> Optional[int]:
    if session.duration_sec is not None:
        try:
            return max(0, int(session.duration_sec))
        except (TypeError, ValueError):
            pass

    if session.end_time is None:
        return None

    try:
        return calculate_duration_sec(session.start_time, session.end_time)
    except ValueError:
        return None


def _sanitize_sql_identifier(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value or ""):
        raise RuntimeError(f"invalid SQL identifier: {value!r}")
    return value


def _analysis_feedback_table() -> str:
    return _sanitize_sql_identifier(
        os.getenv("ANALYSIS_FEEDBACK_TABLE", "analysis_feedback").strip()
        or "analysis_feedback"
    )


def _parse_json_value(value: Any) -> Any:
    if value is None or isinstance(value, (dict, list)):
        return value
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8")
    if isinstance(value, str):
        text_value = value.strip()
        if not text_value:
            return None
        try:
            return json.loads(text_value)
        except json.JSONDecodeError:
            return None
    return value

@router.get("/summary")
def get_dashboard_summary(
    start_date: str = Query(...), 
    end_date: str = Query(...),   
    db: Session = Depends(get_db),
    x_user_id: int = Header(..., alias="X-User-Id")
):
    try:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
    except ValueError:
        raise HTTPException(status_code=400, detail="날짜 형식이 올바르지 않습니다.")

    sessions = db.query(models.FocusSession).filter(
        models.FocusSession.user_id == x_user_id,
        models.FocusSession.start_time >= start_dt,
        models.FocusSession.start_time <= end_dt,
        models.FocusSession.status == "completed"
    ).all()
    
    total_seconds = 0
    total_score_weight = 0
    weekly_breakdown = {}
    unique_days = set()

    for s in sessions:
        dur = _session_duration_sec(s) or 0
        if dur <= 0: continue
        
        # Group by Month/Day for the chart
        day_str = s.start_time.strftime("%m/%d")
        if day_str not in weekly_breakdown:
            weekly_breakdown[day_str] = 0.0
            
        total_seconds += dur
        weekly_breakdown[day_str] += (dur / 3600.0)
        unique_days.add(s.start_time.strftime("%Y-%m-%d"))
        
        # Pull the AI focus score from the edge database tables
        summary_row = db.execute(
            text("SELECT focus_ratio FROM analysis_summary WHERE session_id = :sid"),
            {"sid": str(s.id)}
        ).mappings().first()
        
        f_ratio = summary_row.get("focus_ratio", 0) if summary_row else 0
        f_score = f_ratio * 100
        total_score_weight += (f_score * dur)

    total_hours = round(total_seconds / 3600, 1)
    avg_score = round(total_score_weight / total_seconds) if total_seconds > 0 else 0
    
    chart_data = [{"day": day, "hours": round(hours, 1), "seconds": int(hours * 3600)} for day, hours in weekly_breakdown.items()]

    return {
        "total_hours": total_hours,
        "total_seconds": int(total_seconds),
        "avg_focus_score": avg_score,
        "active_days": len(unique_days),
        "weekly_chart_data": chart_data
    }

@router.get("/list")
def get_all_sessions_list(
    db: Session = Depends(get_db),
    x_user_id: int = Header(..., alias="X-User-Id")
):
    """React 프론트엔드의 대시보드와 리포트 페이지에 필요한 모든 세션 데이터를 제공합니다."""
    
    # 1. Get all completed sessions for this user chronologically
    sessions = db.query(models.FocusSession).filter(
        models.FocusSession.user_id == x_user_id,
        models.FocusSession.status == "completed"
    ).order_by(models.FocusSession.start_time.asc()).all()
    
    items = []
    
    for index, s in enumerate(sessions):
        session_key = str(s.id)
        
        # 2. Fetch the new Edge AI Summary
        summary = db.execute(
            text("SELECT * FROM analysis_summary WHERE session_id = :sid"),
            {"sid": session_key}
        ).mappings().first()
        
        # 3. Fetch the Edge AI Feedback for the Weekly Coaching Engine
        feedback = db.execute(
            text("SELECT personal_feedback FROM analysis_feedback WHERE session_id = :sid"),
            {"sid": session_key}
        ).mappings().first()
        
        duration_sec = _session_duration_sec(s) or 0
        
        # 4. Default values to prevent React from crashing
        focus_score = 0
        event_secs = {"gaze": 0, "posture": 0, "absent": 0, "fidget": 0}
        personal_feedback = None
        
        # 5. Map the edge AI data to the React expected format
        if summary:
            focus_score = summary.get("focus_ratio", 0) * 100
            event_secs["gaze"] = summary.get("away_total_sec", 0)
            event_secs["absent"] = summary.get("absent_total_sec", 0)
            
            # Convert the posture ratio back into seconds for the frontend
            posture_ratio = summary.get("bad_posture_ratio", 0)
            event_secs["posture"] = int(posture_ratio * duration_sec)
            
        if feedback and feedback.get("personal_feedback"):
            personal_feedback = _parse_json_value(feedback.get("personal_feedback"))
            
        items.append({
            "id": s.id,
            "session_id": s.id,
            "display_index": index + 1,
            "date": s.start_time.strftime("%b %d, %Y"),
            "date_raw": s.start_time.strftime("%Y-%m-%d"),
            "start_time": s.start_time.strftime("%H:%M"),
            "duration_min": duration_sec // 60,
            "duration_sec": duration_sec,
            "focus_score": int(focus_score),
            "eventSecs": event_secs,
            "personal_feedback": personal_feedback,
            "status": s.status
        })
        
    return {"items": items}


@router.get("/sessions/{session_id}")
def get_session_analysis_result(
    session_id: int,
    db: Session = Depends(get_db),
    x_user_id: Optional[int] = Header(None, alias="X-User-Id"),
):
    """세션 기본 정보와 AI 분석 결과를 함께 조회합니다."""

    query = db.query(models.FocusSession).filter(models.FocusSession.id == session_id)
    if x_user_id is not None:
        query = query.filter(models.FocusSession.user_id == x_user_id)

    session = query.first()
    if not session:
        raise HTTPException(status_code=404, detail="해당 세션을 찾을 수 없습니다.")

    session_key = str(session_id)
    summary_row = db.execute(
        text(
            """
            SELECT *
            FROM analysis_summary
            WHERE session_id = :session_id
            """
        ),
        {"session_id": session_key},
    ).mappings().first()

    timeline_rows = db.execute(
        text(
            """
            SELECT t, state
            FROM analysis_timeline
            WHERE session_id = :session_id
            ORDER BY t ASC
            """
        ),
        {"session_id": session_key},
    ).mappings().all()

    event_rows = db.execute(
        text(
            """
            SELECT event_type, start_sec, end_sec, score
            FROM analysis_events
            WHERE session_id = :session_id
            ORDER BY start_sec ASC, end_sec ASC
            """
        ),
        {"session_id": session_key},
    ).mappings().all()

    feedback_row = None
    feedback_table = _analysis_feedback_table()
    try:
        feedback_row = db.execute(
            text(
                f"""
                SELECT feedback_text, personal_feedback, feedback_source, feedback_version, feedback_created_at
                FROM {feedback_table}
                WHERE session_id = :session_id
                """
            ),
            {"session_id": session_key},
        ).mappings().first()
    except Exception:
        try:
            feedback_row = db.execute(
                text(
                    f"""
                    SELECT feedback_text
                    FROM {feedback_table}
                    WHERE session_id = :session_id
                    """
                ),
                {"session_id": session_key},
            ).mappings().first()
        except Exception:
            feedback_row = None

    duration_sec = _session_duration_sec(session)
    # --- FIX: Calculate focus score from the Edge AI summary, NOT FocusLog ---
    focus_score = 0.0
    if summary_row and summary_row.get("focus_ratio") is not None:
        focus_score = round(float(summary_row.get("focus_ratio")) * 100, 1)

    personal_feedback = None
    if feedback_row is not None:
        personal_feedback = _parse_json_value(feedback_row.get("personal_feedback"))

    return {
        "session_id": session.id,
        "user_id": session.user_id,
        "status": session.status,
        "start_time": session.start_time,
        "end_time": session.end_time,
        "duration_sec": duration_sec,
        "focus_score": focus_score, # Passed the edge AI score here!
        "summary": dict(summary_row) if summary_row else None,
        "timeline": [dict(row) for row in timeline_rows],
        "events": [
            {
                "type": row.get("event_type"),
                "start_sec": row.get("start_sec"),
                "end_sec": row.get("end_sec"),
                "score": row.get("score"),
            }
            for row in event_rows
        ],
        "feedback_text": feedback_row.get("feedback_text") if feedback_row else None,
        "personal_feedback": personal_feedback,
        "feedback_source": feedback_row.get("feedback_source") if feedback_row else None,
        "feedback_version": feedback_row.get("feedback_version") if feedback_row else None,
        "feedback_created_at": feedback_row.get("feedback_created_at") if feedback_row else None,
    }

@router.delete("/sessions/{session_id}")
def delete_session_data(
    session_id: int,
    db: Session = Depends(get_db),
    x_user_id: Optional[int] = Header(None, alias="X-User-Id")
):
    """세션과 관련된 모든 타임라인, 이벤트, 피드백 데이터를 완전히 삭제합니다."""
    
    # 1. Verify the session exists and belongs to the user
    session = db.query(models.FocusSession).filter(models.FocusSession.id == session_id).first()
    if not session or (x_user_id and session.user_id != x_user_id):
        raise HTTPException(status_code=404, detail="해당 세션을 찾을 수 없습니다.")

    # 2. Wipe all AI data associated with it
    session_key = str(session_id)
    db.execute(text("DELETE FROM analysis_timeline WHERE session_id = :sid"), {"sid": session_key})
    db.execute(text("DELETE FROM analysis_events WHERE session_id = :sid"), {"sid": session_key})
    db.execute(text("DELETE FROM analysis_summary WHERE session_id = :sid"), {"sid": session_key})
    db.execute(text("DELETE FROM analysis_feedback WHERE session_id = :sid"), {"sid": session_key})

    # 3. Delete the core session
    db.delete(session)
    db.commit()

    return {"message": "세션 및 모든 분석 데이터가 성공적으로 삭제되었습니다."}