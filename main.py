from fastapi import FastAPI, UploadFile, Request, Form, File
from fastapi.staticfiles import StaticFiles
import shutil
import json
import boto3
import os
import uvicorn

# CORS 설정
from fastapi.middleware.cors import CORSMiddleware

# 작성한 models와 database 불러오기
import models
from database import engine

# 🌟 1. 우리가 만든 라우터 불러오기
from routers import users, sessions, logs, analysis, reports # 🌟 sessions,logs, reports 추가

# 🌟 핵심: 서버가 켜질 때 모델을 확인하고 데이터베이스에 테이블을 생성합니다.
# (이미 테이블이 존재하면 건너뛰고, 없으면 새로 만듭니다.)
models.Base.metadata.create_all(bind=engine)

# FastAPI 애플리케이션 객체 생성
app = FastAPI(
    title="FocusAI API",
    description="실시간 집중도 측정 및 로그 관리를 위한 백엔드 서버",
    version="1.0.0"
)

# 🌟 2. 경비원(CORS)에게 문을 열어달라고 지시하는 코드를 추가합니다.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 🌟 2. FastAPI 앱에 라우터 등록하기
app.include_router(users.router)
app.include_router(sessions.router) # 🌟 세션 라우터 등록 추가
app.include_router(logs.router) # logs 라우터 추가
app.include_router(analysis.router) # 집중도 분석 라우터 추가
app.include_router(reports.router)

# 🌟 AWS SQS & S3 Configurations
SQS_QUEUE_URL = "https://sqs.ap-northeast-2.amazonaws.com/003344631039/joljak-video-queue.fifo"
S3_BUCKET_NAME = "jolljak-storage-2026" 

# Initialize the AWS Clients
sqs_client = boto3.client('sqs', region_name='ap-northeast-2')
s3_client = boto3.client('s3', region_name='ap-northeast-2')

@app.post("/api/v1/sessions/{session_id}/upload")
async def save_session_video(session_id: int, file: UploadFile = File(...), is_final_chunk: str = Form("false")):
    # 1. Parse chunk index out of the custom filename string (user_{uid}_session_{sid}_part{index}.webm)
    try:
        filename_no_ext = file.filename.split(".")[0]
        chunk_index_str = filename_no_ext.split("_part")[-1]
        chunk_index = int(chunk_index_str)
        
        # Extract the user_id integer from the filename prefix
        user_id_str = filename_no_ext.split("user_")[-1].split("_session")[0]
        user_id = int(user_id_str)
    except Exception:
        chunk_index = 1
        user_id = 0

    # Convert the string form data parameter ("true"/"false") into a real Python Boolean
    final_flag = True if is_final_chunk.lower() == "true" else False

    # Define the precise file path storage key matching their directory format
    s3_file_key = f"uploads/session_{session_id}/chunk_{chunk_index}.webm"

    try:
        # Upload raw data chunks up to the S3 bucket cloud layer
        s3_client.upload_fileobj(
            file.file,
            S3_BUCKET_NAME,
            s3_file_key,
            ExtraArgs={'ContentType': 'video/webm'}
        )
        
        # ALIGN PAYLOAD
        message_payload = {
            "session_id": session_id,
            "user_id": user_id,
            "s3_bucket": S3_BUCKET_NAME,
            "s3_key": s3_file_key,
            "camera_type": "merged",          # Side-by-side kiosk canvas video format
            "mode": "focus_analysis",         # Focus inference execution group label
            "chunk_index": chunk_index,
            "is_final_chunk": final_flag      # Python boolean matches strict JSON bool requirements
        }
        
        # Transmission: Ship the structured message ticket directly to SQS
        sqs_client.send_message(
            QueueUrl=SQS_QUEUE_URL,
            MessageBody=json.dumps(message_payload), # Converts dictionary keys into strict JSON format
            MessageGroupId="video-analysis-group",
            MessageDeduplicationId=f"{session_id}-{chunk_index}"
        )
        
        print(f"Perfect SQS message queued for Session {session_id} Part {chunk_index} (Final: {final_flag})")
        return {"status": "success", "queued": True, "is_final_chunk": final_flag}

    except Exception as e:
        print(f"Cloud Pipeline Failure: {str(e)}")
        return {"status": "failed", "detail": str(e)}

# 기본 루트 엔드포인트 (서버 접속 테스트용)
@app.get("/")
def read_root():
    return {"message": "FocusAI 백엔드 서버가 정상적으로 실행되었습니다!"}

# 상태 점검 엔드포인트 (헬스 체크)
@app.get("/api/health")
def health_check():
    return {"status": "ok", "db_connected": "True (Tables created or verified)"}

# 파이썬 스크립트 직접 실행 시 Uvicorn 서버 구동
if __name__ == "__main__":
    # reload=True 옵션은 코드가 수정될 때마다 서버를 자동으로 재시작해 줍니다.
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)