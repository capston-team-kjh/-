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
    range_type: str = Query("weekly", enum=["weekly", "monthly"]),
    db: Session = Depends(get_db),
    x_user_id: int = Header(..., alias="X-User-Id")
):
    """주간/월간 학습 시간 및 평균 집중도를 계산합니다."""
    days_to_subtract = 7 if range_type == 'weekly' else 30
    start_date = datetime.now() - timedelta(days=days_to_subtract)

    # Query: 요약 정보 (활동 일수, 전체 평균 점수)
    stats = db.query(
        func.count(func.distinct(func.date(models.FocusSession.start_time))).label('active_days'),
        func.avg(models.FocusLog.focus_score).label('avg_score')
    ).join(models.FocusLog, models.FocusSession.id == models.FocusLog.session_id)\
     .filter(models.FocusSession.user_id == x_user_id)\
     .filter(models.FocusSession.start_time >= start_date).first()

    # Query: 총 학습 시간 계산 (초 단위 합산 후 시간으로 변환)
    # Note: MySQL/SQLite에 따라 func.sum 사용 방식이 다를 수 있어 단순화된 로직 적용
    sessions = db.query(models.FocusSession).filter(
        models.FocusSession.user_id == x_user_id,
        models.FocusSession.start_time >= start_date,
        models.FocusSession.end_time != None
    ).all()
    
    total_seconds = sum((_session_duration_sec(s) or 0) for s in sessions)
    total_hours = round(total_seconds / 3600, 1)

    return {
        "range": range_type,
        "total_hours": total_hours,
        "avg_focus_score": round(float(stats.avg_score or 0), 1),
        "active_days": stats.active_days or 0
    }

@router.get("/recent")
def get_recent_results(
    size: int = 4,
    db: Session = Depends(get_db),
    x_user_id: int = Header(..., alias="X-User-Id")
):
    """최근 세션 목록을 가져옵니다."""
    sessions = db.query(models.FocusSession).filter(
        models.FocusSession.user_id == x_user_id
    ).order_by(models.FocusSession.start_time.desc()).limit(size).all()

    items = []
    for s in sessions:
        duration_min = 0
        duration_sec = _session_duration_sec(s)
        if duration_sec is not None:
            duration_min = int(duration_sec / 60)
            
        avg_score = db.query(func.avg(models.FocusLog.focus_score)).filter(
            models.FocusLog.session_id == s.id
        ).scalar() or 0

        items.append({
            "session_id": s.id,
            "date": s.start_time.strftime("%Y-%m-%d"),
            "start_time": s.start_time.strftime("%H:%M"),
            "duration_min": duration_min,
            "focus_score": round(float(avg_score), 1),
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
    avg_score = db.query(func.avg(models.FocusLog.focus_score)).filter(
        models.FocusLog.session_id == session.id
    ).scalar()

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
        "focus_score": round(float(avg_score or 0), 1),
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
