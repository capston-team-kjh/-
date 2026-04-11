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
    
    total_seconds = sum([(s.end_time - s.start_time).total_seconds() for s in sessions])
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
        if s.end_time:
            duration_min = int((s.end_time - s.start_time).total_seconds() / 60)
            
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