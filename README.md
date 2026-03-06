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
   - Node.js 버전: v24.x 이상 (LTS) -> Long-Term Support 버전이 제일 안정적인 버전들이라고 함

---

## 🛠️ 설치 및 실행 방법

### 1. 백엔드 (FastAPI / Flask / MySQL)
```terminal
# 1. 가상환경 생성 및 활성화
python -m venv venv
.\venv\Scripts\activate  # (Mac/Linux: source venv/bin/activate)

# 2. 필수 라이브러리 설치 (bcrypt 버전 충돌 방지 포함)
pip install -r requirements.txt

# 3. 서버 실행 (자동으로 데이터베이스 테이블이 생성됩니다)
uvicorn main:app --reload
```

### 2. 프론트엔드 ( React + Vite )

---
### 노드 패기지를 터미널로 설치하기 전에 node.js (v24.x LTS) 설치

1. **노드 페이지 방문하고 'Pre-built node.js'로 내려가서 운영체제 선택 이후 installer 설치.**
   - *필수 참고 사항: 설치할때 'Add to PATH' 옵션이 체크되어 있는지 확인하고 설치 실행할 것*
   - https://nodejs.org/en/download

2. **설치 이후, 터미널에서 node와 npm 버전 확인**
   ```terminal
   node -v  # v24.x 확인

   npm -v  # v11.x 확인
   ```
---
### 노드 패키지 설치
```terminal
# 1. 새로운 터미널에서 포론트엔드 다이렉토리로 이동 ( 여기서는 가상 환경 활성화 안함 )
cd frontend

# 2. 노드 패캐지 설치
npm install

# 3. 개발 환경 시작
npm run dev
```


 
