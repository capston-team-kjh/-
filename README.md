이 모듈은 핵심 인증 루프, 사용자 설정, 그리고 학습 세션 추적을 위한 데이터베이스 스키마를 포함하고 있습니다.

## 주요 기능
- 인증 루프 (Full Auth Loop): Flask 및 MySQL과 연동된 로그인, 회원가입, 로그아웃 기능 구현.
- 세션 유지 (Session Persistence): `localStorage`를 사용하여 새로고침 시에도 로그인 상태와 현재 페이지 위치를 유지.
- 보안 설정 (Secure Settings): Bcrypt 해싱을 이용한 프로필 조회 및 비밀번호 변경 기능.
- 데이터베이스 스키마: 집중도 추적을 위한 `STUDY_SESSION` 및 `ANALYSIS_RESULT` 테이블 구현. ( Work in Progress )

## 기술 스택
- Frontend: React, TypeScript, Tailwind CSS.
- Backend: Flask, Flask-SQLAlchemy, Bcrypt.
- Database: MySQL.

## 시작 가이드

### 백엔드 설정 (Backend Setup)
1. `/backend` 폴더로 이동
2. 가상환경을 활성화: `source venv/bin/activate` (Windows의 경우 `venv\Scripts\activate`).
3. 필요한 라이브러리를 설치: `pip install flask flask-sqlalchemy pymysql bcrypt`.
4. 서버를 실행: `python app.py`.
   * *참고: MySQL 서버가 3306 포트에서 실행 중이어야 함함.*

### 프론트엔드 설정 (Frontend Setup)
1. `/frontend` 폴더로 이동합니다.
2. 종속성 라이브러리를 설치합니다: `npm install`.
3. 개발 서버를 실행합니다: `npm run dev`.

##  데이터베이스 모델 (Database Models) ## WIP (Work in Progress) ##
- `USER`: 사용자 인증 및 프로필 정보 저장.
- `STUDY_SESSION`: 학습 시작/종료 시간 및 기기 메타데이터 추적.
- `ANALYSIS_RESULT`: 세션과 연결된 집중도 점수(0-100) 저장.