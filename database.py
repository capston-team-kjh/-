import os
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from dotenv import load_dotenv

load_dotenv()

# MySQL 연결 주소 (아이피, 포트, DB이름, 비밀번호 등은 본인 환경에 맞게 수정)
# 형식: mysql+pymysql://유저이름:비밀번호@호스트주소:포트/DB이름
LOCAL_DATABASE_URL = "mysql+pymysql://root:1234@127.0.0.1:3306/joljak_db"

SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL", LOCAL_DATABASE_URL)

# 데이터베이스 엔진 생성 (echo=True로 설정하면 터미널에 SQL 쿼리문이 출력되어 디버깅에 좋습니다)
engine = create_engine(SQLALCHEMY_DATABASE_URL, echo=True)

# 세션 팩토리 생성 (DB에 접근할 때마다 이 팩토리에서 세션을 하나씩 꺼내 씁니다)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 모든 ORM 모델의 기본이 되는 클래스
Base = declarative_base()

# API 호출 시 DB 세션을 열고 닫는 제너레이터 함수 (FastAPI 의존성 주입용)
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()