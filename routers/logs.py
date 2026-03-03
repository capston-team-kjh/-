from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

import models, schemas
from database import get_db

# 라우터 설정
router = APIRouter(
    prefix="/api/v1/logs",
    tags=["Logs (실시간 집중도 로그)"]
)

@router.post("/", response_model=schemas.LogResponse, status_code=status.HTTP_201_CREATED)
def create_log(log_data: schemas.LogCreate, db: Session = Depends(get_db)):
    """AI가 측정한 실시간 집중도 로그를 저장합니다."""
    # 1. 로그를 넣을 세션(시간표)이 실제로 존재하는지 확인
    session = db.query(models.FocusSession).filter(models.FocusSession.id == log_data.session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="해당 세션을 찾을 수 없습니다. (세션이 먼저 생성되어야 합니다)")
    
    # 2. 새 로그 객체 생성 (timestamp는 models.py의 기본값으로 현재 시간이 자동 저장됨)
    new_log = models.FocusLog(
        session_id=log_data.session_id,
        focus_score=log_data.focus_score,
        state=log_data.state
    )
    
    # 3. DB에 저장
    db.add(new_log)
    db.commit()
    db.refresh(new_log)
    
    return new_log

@router.get("/session/{session_id}", response_model=List[schemas.LogResponse])
def get_session_logs(session_id: int, db: Session = Depends(get_db)):
    """특정 세션에 기록된 모든 집중도 로그를 시간순으로 조회합니다."""
    # 해당 세션의 로그들을 timestamp 오름차순(과거->최신)으로 정렬해서 가져옵니다.
    logs = db.query(models.FocusLog).filter(models.FocusLog.session_id == session_id).order_by(models.FocusLog.timestamp.asc()).all()
    return logs