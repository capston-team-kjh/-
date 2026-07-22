from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from sqlalchemy.orm import Session
from typing import List
from datetime import datetime, timezone, timedelta
import boto3
import json
import models, schemas
from database import get_db
from time_utils import as_local_naive_datetime, calculate_duration_sec, normalize_session_end_time

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
def save_session_timeline(session_id: str, payload: dict, db: Session = Depends(get_db)):
    """세션 종료 후 브라우저에서 분석된 타임라인 데이터를 일괄 저장합니다."""
    
    timeline_data = payload.get("timeline", [])
    if not timeline_data:
        return {"message": "저장할 타임라인 데이터가 없습니다."}
    
    # Extract the array and map it to the AnalysisTimeline database model
    db_records = [
        models.AnalysisTimeline(
            session_id=session_id,
            t=item["t"],
            state=item["state"]
        ) for item in timeline_data
    ]
    
    # Bulk save to the database for high performance
    db.add_all(db_records)
    db.commit()
    
    return {"message": f"{len(db_records)}개의 타임라인 데이터가 성공적으로 저장되었습니다."}

@router.get("/user/{user_id}", response_model=List[schemas.SessionResponse])
def get_user_sessions(user_id: int, db: Session = Depends(get_db)):
    """특정 유저의 모든 집중 세션 기록을 조회합니다."""
    sessions = db.query(models.FocusSession).filter(models.FocusSession.user_id == user_id).all()
    return sessions
