from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from sqlalchemy.orm import Session
from typing import List
from datetime import datetime, timezone, timedelta
import boto3
import json
import models, schemas
from database import get_db

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
    
    # 새 세션 생성 (start_time과 status는 models.py에 설정된 기본값이 자동 적용됩니다)
    new_session = models.FocusSession(user_id=session_data.user_id)
    
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
    KST = timezone(timedelta(hours=9))
    session.end_time = datetime.now(KST)
    session.status = session_data.status
    
    db.commit()
    db.refresh(session)
    
    return session

@router.get("/user/{user_id}", response_model=List[schemas.SessionResponse])
def get_user_sessions(user_id: int, db: Session = Depends(get_db)):
    """특정 유저의 모든 집중 세션 기록을 조회합니다."""
    sessions = db.query(models.FocusSession).filter(models.FocusSession.user_id == user_id).all()
    return sessions

@router.post("/{session_id}/upload")
async def save_session_video(session_id: int, file: UploadFile = File(...), is_final_chunk: str = Form("false")):
    """가상 환경 내에서 S3 스트리밍 및 SQS FIFO 큐 토큰 발행을 동시 처리합니다."""
    try:
        filename_no_ext = file.filename.split(".")[0]
        chunk_index_str = filename_no_ext.split("_part")[-1]
        chunk_index = int(chunk_index_str)
        
        user_id_str = filename_no_ext.split("user_")[-1].split("_session")[0]
        user_id = int(user_id_str)
    except Exception:
        chunk_index = 1
        user_id = 0

    final_flag = True if is_final_chunk.lower() == "true" else False
    s3_file_key = f"uploads/session_{session_id}/chunk_{chunk_index}.webm"

    try:
        # Stream multipart chunks directly onto AWS S3
        s3_client.upload_fileobj(
            file.file,
            S3_BUCKET_NAME,
            s3_file_key,
            ExtraArgs={'ContentType': 'video/webm'}
        )
        
        # Dispatch metadata analysis ticket into SQS FIFO Queue
        message_payload = {
            "session_id": session_id,
            "user_id": user_id,
            "s3_bucket": S3_BUCKET_NAME,
            "s3_key": s3_file_key,
            "camera_type": "merged",
            "mode": "focus_analysis",
            "chunk_index": chunk_index,
            "is_final_chunk": final_flag
        }
        
        sqs_client.send_message(
            QueueUrl=SQS_QUEUE_URL,
            MessageBody=json.dumps(message_payload),
            MessageGroupId="video-analysis-group",
            MessageDeduplicationId=f"{session_id}-{chunk_index}"
        )
        
        return {"status": "success", "queued": True, "is_final_chunk": final_flag}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Cloud Pipeline Failure: {str(e)}")
    