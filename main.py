from fastapi import FastAPI, UploadFile, File
from fastapi.staticfiles import StaticFiles
import shutil
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

# 1. 프로젝트 루트 경로에 'upload' 폴더를 정의하고, 없으면 자동으로 생성
UPLOAD_DIR = "upload"
if not os.path.exists(UPLOAD_DIR):
    os.makedirs(UPLOAD_DIR)

# 2. "StaticFiles"로 /upload 경로를 웹상에서 접근 가능하게 만듦
# 이제 브라우저나 워커에서 http://localhost:8000/upload/...webm으로 영상을 접근
app.mount("/upload", StaticFiles(directory=UPLOAD_DIR), name="upload")

# 3. 프론트엔드에서 보낸 영상을 실제 파일로 저장하는 API 엔드포인트 정의
@app.post("/api/v1/sessions/{session_id}/upload")
async def save_session_video(session_id: int, file: UploadFile = File(...)):
    # 저장될 전체 파일 경로를 생성 (예: upload/session_101.webm)
    file_path = os.path.join(UPLOAD_DIR, f"session_{session_id}.webm")
    
    # 전달받은 파일 객체의 내용을 한 바이트씩 버퍼를 통해 실제 디스크에 작성
    # shutil.copyfileobj는 메모리 효율적으로 대용량 파일을 복사
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    # 저장이 완료되면 접근 가능한 공개 URL을 반환
    return {"url": f"http://localhost:8000/upload/session_{session_id}.webm"}

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