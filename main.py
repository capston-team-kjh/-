from fastapi import FastAPI
import uvicorn

# CORS 설정
from fastapi.middleware.cors import CORSMiddleware

# 작성한 models와 database 불러오기
import models
from database import engine

# 🌟 1. 우리가 만든 라우터 불러오기
from routers import users, sessions, logs # 🌟 sessions,logs 추가

# 🌟 핵심: 서버가 켜질 때 모델을 확인하고 데이터베이스에 테이블을 생성합니다.
# (이미 테이블이 존재하면 건너뛰고, 없으면 새로 만듭니다.)
models.Base.metadata.create_all(bind=engine)

# FastAPI 애플리케이션 객체 생성
app = FastAPI(
    title="FocusAI API",
    description="실시간 집중도 측정 및 로그 관리를 위한 백엔드 서버",
    version="1.0.0"
)

# CORS 설정
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