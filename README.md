✨ 주요 기능 (Key Features)
사용자 인증 (User Authentication): FastAPI와 MySQL을 연동한 안전한 회원가입 및 로그인 API 구현. Passlib(Bcrypt)를 사용한 강력한 비밀번호 해싱 적용.

집중 세션 관리 (Focus Session Tracking): 사용자의 학습/집중 시작 시간, 종료 시간, 그리고 현재 상태(active, completed 등)를 기록하는 '집중 시간표' 생성 및 관리.

실시간 집중도 로그 (Real-time Focus Logs): AI 모델(웹캠 등)이 측정한 1초/5초 단위의 집중 점수(0-100)와 현재 상태(focus, distracted, sleep 등)를 해당 세션에 종속시켜 차곡차곡 저장 및 조회.

프론트엔드 연동 준비 (CORS Configuration): React, Vue 등 외부 프론트엔드 애플리케이션과의 원활한 통신을 위해 CORS(Cross-Origin Resource Sharing) 미들웨어 설정 완료.

🛠️ 기술 스택 (Tech Stack)
Backend: FastAPI, Uvicorn (비동기 처리 및 빠른 API 응답 속도 자랑)

Database: MySQL

ORM & Security: SQLAlchemy, PyMySQL, Passlib(Bcrypt)

🚀 시작 가이드 (Getting Started)
백엔드 설정 (Backend Setup)

1. 프로젝트 폴더(예: joljak4)로 이동합니다.

2. 가상환경을 활성화합니다: .\venv\Scripts\activate (Windows PowerShell 기준).

3. 필수 라이브러리를 설치합니다:
 -> pip install fastapi uvicorn sqlalchemy pymysql passlib "bcrypt<4.0.0"

4. 데이터베이스 환경 세팅: MySQL 서버가 3306 포트에서 실행 중이어야 하며, joljak_db라는 이름의 데이터베이스가 미리 생성되어 있어야 합니다. (테이블은 서버 실행 시 SQLAlchemy가 자동으로 생성합니다.)

5. 서버를 실행합니다:
 -> uvicorn main:app --reload

6. 웹 브라우저에서 http://127.0.0.1:8000/docs로 접속하면 Swagger UI를 통해 모든 API를 즉시 테스트할 수 있습니다.

🗄️ 데이터베이스 모델 (Database Models)
users: 사용자 인증(이메일, 암호화된 비밀번호) 및 기본 프로필(이름, 가입일) 정보 저장.

focus_sessions: 유저와 1:N 관계로 연결되며, 특정 집중 구간의 시작 시간(start_time), 종료 시간(end_time), 세션 상태(status) 추적.

focus_logs: 세션과 1:N 관계로 연결되며, AI가 측정한 실시간 집중도 점수(focus_score), 상세 상태(state), 측정 시간(timestamp)을 밀리초 단위로 저장.
