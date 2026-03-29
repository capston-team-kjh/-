from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from datetime import datetime

import models, schemas
from database import get_db

# 라우터 설정
router = APIRouter(
    prefix="/api/v1/sessions",
    tags=["Sessions (집중 세션 관리)"]
)

@router.post("/", response_model=schemas.SessionResponse, status_code=status.HTTP_201_CREATED)
def start_session(session_data: schemas.SessionCreate, db: Session = Depends(get_db)):
    """새로운 집중 세션을 시작합니다."""
    # 1. 유저가 실제로 존재하는지 확인
    user = db.query(models.User).filter(models.User.id == session_data.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="해당 유저를 찾을 수 없습니다.")
    
    # 2. 새 세션 생성 (start_time과 status는 models.py에 설정된 기본값이 자동 적용됩니다)
    new_session = models.FocusSession(user_id=session_data.user_id)
    
    # 3. DB에 저장
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
    session.end_time = session_data.end_time
    session.status = session_data.status
    
    db.commit()
    db.refresh(session)
    
    return session

@router.get("/user/{user_id}", response_model=List[schemas.SessionResponse])
def get_user_sessions(user_id: int, db: Session = Depends(get_db)):
    """특정 유저의 모든 집중 세션 기록을 조회합니다."""
    sessions = db.query(models.FocusSession).filter(models.FocusSession.user_id == user_id).all()
    return sessions