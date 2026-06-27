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
def get_true_session_metrics(db: Session, session: models.FocusSession):
    """
    session-detail.tsx와 100% 동일한 기준으로 세션 시간과 집중도를 계산하는 마스터 함수입니다.
    DB의 단순 시작/종료 시간이 아닌, AI가 실제 분석한 타임라인(t_secs)을 절대적인 기준으로 사용합니다.
    """
    # 1. 기본 DB 시간 (Fallback용)
    db_duration = session.duration_sec or (int((session.end_time - session.start_time).total_seconds()) if session.end_time else 0)
    
    # 2. AI 데이터 조회
    timeline_len = db.query(models.AnalysisTimeline).filter(models.AnalysisTimeline.session_id == str(session.id)).count()
    events = db.query(models.AnalysisEvent).filter(models.AnalysisEvent.session_id == str(session.id)).all()
    
    # 3. AI 기반 실제 분석 시간 (t_secs) 추출
    t_secs = timeline_len if timeline_len > 0 else (max([int(e.end_sec) for e in events] + [0]) if events else db_duration)
    t_secs = max(t_secs, 1) # 0으로 나누기 방지
    
    # 4. 1초 단위 집중도 및 방해 요소 누적 계산
    second_by_second = [100] * t_secs
    event_secs = {"gaze": 0, "posture": 0, "absent": 0, "fidget": 0}
    
    for e in events:
        start = int(e.start_sec or 0)
        end = int(e.end_sec or 0)
        duration = end - start
        penalty = (e.score or 0) * 100
        
        if e.event_type == "gaze_side": event_secs["gaze"] += duration
        elif e.event_type == "bad_posture": event_secs["posture"] += duration
        elif e.event_type == "absent": event_secs["absent"] += duration
        elif e.event_type in ["fidgeting", "overhead_no_activity"]: event_secs["fidget"] += duration
        
        resulting_focus = max(0, 100 - penalty)
        for i in range(start, min(end, t_secs)):
            second_by_second[i] = min(second_by_second[i], resulting_focus)
            
    true_score = round(sum(second_by_second) / (t_secs * 100) * 100)
    
    return {
        "duration_sec": t_secs,
        "duration_min": max(t_secs // 60, 1),
        "focus_score": true_score,
        "event_secs": event_secs
    }

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

    if not sessions:
        return {
            "total_hours": 0.0,
            "total_seconds": 0,
            "avg_focus_score": 0,
            "active_days": 0,
            "weekly_chart_data": []
        }

    total_seconds = 0
    total_score_weight = 0
    unique_days = set([s.start_time.strftime("%Y-%m-%d") for s in sessions])
    
    weekday_map = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"}
    weekly_breakdown = {name: 0.0 for name in weekday_map.values()}

    for s in sessions:
        metrics = get_true_session_metrics(db, s)
        total_seconds += metrics["duration_sec"]
        total_score_weight += (metrics["focus_score"] * metrics["duration_sec"])
        
        day_name = weekday_map.get(s.start_time.weekday())
        if day_name in weekly_breakdown:
            weekly_breakdown[day_name] += (metrics["duration_sec"] / 3600)

    total_hours = round(total_seconds / 3600, 1)
    avg_score = round(total_score_weight / total_seconds) if total_seconds > 0 else 0
    chart_data = [{"day": day, "hours": round(hours, 1), "seconds": int(hours * 3600)}for day, hours in weekly_breakdown.items()]

    return {
        "total_hours": total_hours,
        "total_seconds": int(total_seconds),
        "avg_focus_score": avg_score,
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
    all_user_sessions = db.query(models.FocusSession).filter(
        models.FocusSession.user_id == x_user_id,
        models.FocusSession.status == "completed"
    ).order_by(models.FocusSession.start_time.asc()).all()
    
    display_index_map = {session_row.id: index + 1 for index, session_row in enumerate(all_user_sessions)}

    sessions = db.query(models.FocusSession).filter(
        models.FocusSession.user_id == x_user_id,
        models.FocusSession.status == "completed"
    ).order_by(models.FocusSession.start_time.desc()).limit(size).all()

    items = []
    for s in sessions:
        metrics = get_true_session_metrics(db, s)
        items.append({
            "session_id": s.id,
            "display_index": display_index_map.get(s.id, 1),
            "date": s.start_time.strftime("%b %d, %Y"),
            "date_raw": s.start_time.strftime("%Y-%m-%d"),
            "start_time": s.start_time.strftime("%H:%M"),
            "duration_min": metrics["duration_min"],
            "duration_sec": metrics["duration_sec"],
            "focus_score": metrics["focus_score"],
            "status": s.status
        })

    return {"items": items}

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

    # 2. Fetch Timeline Data
    timeline = db.query(models.AnalysisTimeline).filter(
        models.AnalysisTimeline.session_id == session_id
    ).order_by(models.AnalysisTimeline.t.asc()).all()

    # 3. Fetch Feedback (Grab the most recent one for this session)
    feedback_entry = db.query(models.AnalysisFeedback).filter(
        models.AnalysisFeedback.session_id == session_id
    ).order_by(models.AnalysisFeedback.id.desc()).first()

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
        "insights": [feedback_entry.feedback_text] if feedback_entry else [],
        "events": [
            {
                "event_type": e.event_type,
                "start_sec": e.start_sec,
                "end_sec": e.end_sec,
                "score": e.score
            } for e in events
        ],
        
        # Send the JSON and metadata straight to React
        "personal_feedback": feedback_entry.personal_feedback if feedback_entry else None,
        "feedback_source": feedback_entry.feedback_source if feedback_entry else None,
        "feedback_version": feedback_entry.feedback_version if feedback_entry else None,
        "feedback_created_at": feedback_entry.feedback_created_at if feedback_entry else None
    }

@router.get("/list")
def get_analytics_list(db: Session = Depends(get_db), user_id: int = Header(alias="X-User-Id")):
    sessions = db.query(models.FocusSession).filter(models.FocusSession.user_id == user_id).all()
    
    result_items = []
    for idx, session in enumerate(sessions):
        metrics = get_true_session_metrics(db, session)

        feedback_entry = db.query(models.AnalysisFeedback).filter(
            models.AnalysisFeedback.session_id == str(session.id)
        ).order_by(models.AnalysisFeedback.id.desc()).first()

        result_items.append({
            "id": session.id,
            "display_index": idx + 1,
            "date": session.start_time.strftime("%b %d, %Y"),
            "date_raw": session.start_time.strftime("%Y-%m-%d"),
            "duration_min": metrics["duration_min"],
            "duration_sec": metrics["duration_sec"],
            "focus_score": metrics["focus_score"],
            "eventSecs": metrics["event_secs"],
            "personal_feedback": feedback_entry.personal_feedback if feedback_entry else None
        })
        
    return {"items": result_items}

@router.delete("/session/{session_id}")
def delete_individual_session(session_id: str, db: Session = Depends(get_db)):
    """특정 세션과 관련된 모든 AI 분석 데이터 및 로그를 영구 삭제합니다."""
    # 1. Check if session exists
    session = db.query(models.FocusSession).filter(models.FocusSession.id == int(session_id)).first()
    if not session:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.")
    
    # 2. Manually delete all AI data tied to this session string
    db.query(models.AnalysisTimeline).filter(models.AnalysisTimeline.session_id == session_id).delete(synchronize_session=False)
    db.query(models.AnalysisEvent).filter(models.AnalysisEvent.session_id == session_id).delete(synchronize_session=False)
    db.query(models.AnalysisFeedback).filter(models.AnalysisFeedback.session_id == session_id).delete(synchronize_session=False)
    db.query(models.AnalysisSummary).filter(models.AnalysisSummary.session_id == session_id).delete(synchronize_session=False)
    
    # 3. Delete the core session
    db.delete(session)
    db.commit()
    
    return {"detail": "세션 및 관련 데이터가 성공적으로 삭제되었습니다."}