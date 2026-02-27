# 🎯 FocusAI 실시간 집중도 측정 시스템 (FocusAI System)(준영이 스타일로 하나 만들었음)

**백엔드 API 및 인증 시스템 모듈**

프로젝트의 핵심 인증 시스템, 집중 세션 관리, 그리고 실시간 AI 집중도 로그 저장을 위한 백엔드 기반을 포함

---

## 🚨 시작 전 필수 체크사항 (Pre-requisites)
서버를 실행하기 전에 반드시 아래 설정을 완료해야 함

1. **MySQL 데이터베이스 생성**
   - MySQL Workbench를 열고 아래 명령어를 실행:
     ```sql
     CREATE DATABASE joljak_db DEFAULT CHARACTER SET utf8mb4;
     ```
   - *이 단계를 건너뛰면 FastAPI 서버 실행 시 데이터베이스 연결 에러가 발생.*

2. **환경 설정 (Environment)**
   - Python 버전: 3.9 이상 권장
   - Node.js 버전: 18.x 이상 권장 (프론트엔드 연동 시)

---

## 🛠️ 설치 및 실행 방법

### 1. 백엔드 (FastAPI & MySQL)
```terminal
# 1. 가상환경 생성 및 활성화
python -m venv venv
.\venv\Scripts\activate  # (Mac/Linux: source venv/bin/activate)

# 2. 필수 라이브러리 설치 (bcrypt 버전 충돌 방지 포함)
pip install fastapi uvicorn sqlalchemy pymysql passlib "bcrypt<4.0.0"

# 3. 서버 실행 (자동으로 데이터베이스 테이블이 생성됩니다)
uvicorn main:app --reload


 
