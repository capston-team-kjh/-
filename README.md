## 시작 전 필수 체크사항 (Pre-requisites)
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
python -m venv .venv
.\venv\Scripts\activate  # (Mac/Linux: source venv/bin/activate)

# 2. 필수 라이브러리 설치 (bcrypt 버전 충돌 방지 포함)
pip install -r requirements.txt

# 3. 서버 실행 (자동으로 데이터베이스 테이블이 생성됩니다)
uvicorn main:app --reload
```

---


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
# 1. 새로운 터미널에서 포론트엔드 다이렉토리로 이동
cd frontend

# 2. 노드 패캐지 설치
npm install

# 3. 개발 환경 시작
npm run dev
```
---

### 3. env 설정

---

### 포론트 .env 설정 (로컬 주소)

1. frontend 폴더에 '.env.local' 파일 하나 만들기

2. 파일안에 로컬 주소 입력 후 저장
```terminal
VITE_API_BASE_URL = http://127.0.0.1:8000/api/v1 # <= 이 줄 입력하고 저장
```
 
### 백엔드 .env 설정 (OpenAI AI 피드백 기능)

백엔드 서버(루트 폴더)에서 AI 피드백 생성기를 사용하려면 OpenAI API 키가 필요

1. **프로젝트 최상위(루트) 폴더**에 `.env` 파일을 생성

2. 파일 안에 아래 내용을 입력하고 저장:

```env
# 필수: OpenAI API 키 입력
OPENAI_API_KEY=sk-본인의_API_키

# 선택: 테스트 중 API 비용을 절감하려면 아래 값을 true로 설정
# true로 설정 시 API 호출 없이 로컬 규칙 기반 피드백이 생성
AI_FEEDBACK_DISABLE_API=false
