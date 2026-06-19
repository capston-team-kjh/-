# 기존에 작성했었던 Flask API를 FastAPI로 옮긴 것
# 데이터를 정리해서 페이지에 뿌려주는 역할을 함

from fastapi import APIRouter, Depends, HTTPException, Header, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timedelta
from typing import List, Optional

import models, schemas
from database import get_db

router = APIRouter(
    prefix="/api/v1/analytics",
    tags=["Reports (학습 리포트 및 통계)"]
)

@router.get("/summary")
def get_dashboard_summary(
    start_date: str = Query(...),  # Expected format: "YYYY-MM-DD"
    end_date: str = Query(...),    # Expected format: "YYYY-MM-DD"
    db: Session = Depends(get_db),
    x_user_id: int = Header(..., alias="X-User-Id")
):
    """지정된 맞춤 날짜 범위 내의 학습 시간, 평균 집중도 및 요일별 통계를 계산합니다."""
    try:
        # Parse text strings into true datetime objects for SQL parsing
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        # Extend end_dt to 23:59:59 to fully include the final chosen day
        end_dt = datetime.strptime(end_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
    except ValueError:
        raise HTTPException(status_code=400, detail="날짜 형식이 올바르지 않습니다. YYYY-MM-DD 형식을 사용하세요.")

    # Query completed sessions specifically falling inside the custom calendar frame
    sessions = db.query(models.FocusSession).filter(
        models.FocusSession.user_id == x_user_id,
        models.FocusSession.start_time >= start_dt,
        models.FocusSession.start_time <= end_dt,
        models.FocusSession.status == "completed"
    ).all()

    if not sessions:
        return {
            "total_hours": 0.0,
            "avg_focus_score": 0,
            "active_days": 0,
            "weekly_chart_data": []
        }

    # 1. Base Aggregations
    total_seconds = sum([(s.end_time - s.start_time).total_seconds() for s in sessions if s.end_time])
    total_hours = round(total_seconds / 3600, 1)

    session_ids = [str(s.id) for s in sessions]
    unique_days = set([s.start_time.strftime("%Y-%m-%d") for s in sessions])

    avg_score_res = db.query(func.avg(models.AnalysisSummary.focus_ratio)).filter(
        models.AnalysisSummary.session_id.in_(session_ids)
    ).scalar() or 0.0

    # 2. Daily Breakdown Mapping
    weekday_map = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"}
    weekly_breakdown = {name: 0.0 for name in weekday_map.values()}

    for s in sessions:
        if s.end_time:
            day_name = weekday_map.get(s.start_time.weekday())
            if day_name in weekly_breakdown:
                duration_hours = (s.end_time - s.start_time).total_seconds() / 3600
                weekly_breakdown[day_name] += duration_hours

    chart_data = [{"day": day, "hours": round(hours, 1)} for day, hours in weekly_breakdown.items()]

    return {
        "total_hours": total_hours,
        "avg_focus_score": round(float(avg_score_res * 100), 1),
        "active_days": len(unique_days),
        "weekly_chart_data": chart_data
    }

# Dashboard Recent Sessions Feed
@router.get("/recent")
def get_recent_results(
    size: int = 4,
    db: Session = Depends(get_db),
    x_user_id: int = Header(..., alias="X-User-Id")
):
    """최근 세션 목록과 함께 유저별 상대적 세션 회차 번호(display_index)를 계산하여 가져옵니다."""
    
    # fetch ALL completed session tuples for this user
    all_user_sessions = db.query(models.FocusSession).filter(
        models.FocusSession.user_id == x_user_id,
        models.FocusSession.status == "completed"
    ).order_by(models.FocusSession.start_time.asc()).all()
    
    # Loop through the rows using a clean variable name (session_row), then read its .id
    display_index_map = {
        session_row.id: index + 1 
        for index, session_row in enumerate(all_user_sessions)
    }

    # Fetch the standard limited subset size for display feed generation
    sessions = db.query(models.FocusSession).filter(
        models.FocusSession.user_id == x_user_id,
        models.FocusSession.status == "completed"
    ).order_by(models.FocusSession.start_time.desc()).limit(size).all()

    items = []
    for s in sessions:
        duration_min = 0
        if s.end_time:
            duration_min = int((s.end_time - s.start_time).total_seconds() / 60)
            
        analysis = db.query(models.AnalysisSummary).filter(
            models.AnalysisSummary.session_id == str(s.id)
        ).first()
        
        focus_score = round(float((analysis.focus_ratio or 0) * 100), 1) if analysis else 0.0

        items.append({
            "session_id": s.id,
            "display_index": display_index_map.get(s.id, 1),
            "date": s.start_time.strftime("%b %d, %Y"),
            "date_raw": s.start_time.strftime("%Y-%m-%d"),
            "start_time": s.start_time.strftime("%H:%M"),
            "duration_min": duration_min,
            "focus_score": focus_score,
            "status": s.status
        })

    return {"items": items}

# Detailed Report Endpoint for an Individual Session (/app/reports/:id)
@router.get("/session/{session_id}")
def get_individual_session_report(
    session_id: str,
    db: Session = Depends(get_db)
):
    """특정 세션의 요약 정보, 타임라인 차트 데이터, 피드백 문구 및 감지 이벤트를 통합 반환합니다."""
    # 1. Fetch High Level Summary
    summary = db.query(models.AnalysisSummary).filter(models.AnalysisSummary.session_id == session_id).first()
    if not summary:
        raise HTTPException(status_code=404, detail="해당 세션의 분석 리포트를 찾을 수 없습니다.")

    # 2. Fetch Timeline Data (Ordered chronologically)
    timeline = db.query(models.AnalysisTimeline).filter(
        models.AnalysisTimeline.session_id == session_id
    ).order_by(models.AnalysisTimeline.t.asc()).all()

    # 3. Fetch Feedback Lines
    feedbacks = db.query(models.AnalysisFeedback).filter(models.AnalysisFeedback.session_id == session_id).all()

    # 4. Fetch Event Logs
    events = db.query(models.AnalysisEvent).filter(models.AnalysisEvent.session_id == session_id).all()

    # Pack everything cleanly into a unified data contract response wrapper
    return {
        "summary": {
            "session_id": summary.session_id,
            "focus_ratio": summary.focus_ratio,
            "absent_count": summary.absent_count,
            "absent_total_sec": summary.absent_total_sec,
            "away_count": summary.away_count,
            "away_total_sec": summary.away_total_sec,
            "bad_posture_ratio": summary.bad_posture_ratio,
            "analyzed_at": summary.analyzed_at
        },
        "timeline": [{"t": t.t, "state": t.state} for t in timeline],
        "insights": [f.feedback_text for f in feedbacks],
        "events": [
            {
                "event_type": e.event_type,
                "start_sec": e.start_sec,
                "end_sec": e.end_sec,
                "score": e.score
            } for e in events
        ]
    }

@router.get("/list")
def get_all_historical_reports(
    db: Session = Depends(get_db),
    x_user_id: int = Header(..., alias="X-User-Id")
):
    """유저의 모든 완료된 세션 기록 리스트와 매칭되는 AI 분석 서머리 데이터를 가져옵니다."""
    # Fetch all matching sessions in reverse chronological order
    sessions = db.query(models.FocusSession).filter(
        models.FocusSession.user_id == x_user_id,
        models.FocusSession.status == "completed"
    ).order_by(models.FocusSession.start_time.desc()).all()

    # Get absolute timeline ordering to calculate true relative sequence display indices
    all_user_sessions = db.query(models.FocusSession.id).filter(
        models.FocusSession.user_id == x_user_id,
        models.FocusSession.status == "completed"
    ).order_by(models.FocusSession.start_time.asc()).all()
    
    display_index_map = {s_row.id: idx + 1 for idx, s_row in enumerate(all_user_sessions)}

    items = []
    for s in sessions:
        duration_min = 0
        if s.end_time:
            duration_min = int((s.end_time - s.start_time).total_seconds() / 60)
            
        analysis = db.query(models.AnalysisSummary).filter(
            models.AnalysisSummary.session_id == str(s.id)
        ).first()
        
        focus_score = round(float((analysis.focus_ratio or 0) * 100), 1) if analysis else 0.0

        items.append({
            "id": s.id,
            "display_index": display_index_map.get(s.id, 1),
            "date": s.start_time.strftime("%b %d, %Y"),
            "date_raw": s.start_time.strftime("%Y-%m-%d"),
            "duration_min": duration_min,
            "focus_score": focus_score
        })

    return {"items": items}