from pydantic import BaseModel, EmailStr, Field
from datetime import datetime
from typing import Optional, List

# ==========================================
# 1. User (회원) 스키마
# ==========================================

# 클라이언트 -> 서버: 로그인 요청 시 사용하는 데이터
class UserLogin(BaseModel):
    email: EmailStr
    password: str

# 클라이언트 -> 서버: 회원가입 요청 시 사용하는 데이터
class UserCreate(BaseModel):
    email: EmailStr  # EmailStr을 사용하면 이메일 형식이 맞는지 자동으로 검사해 줍니다.
    password: str
    name: str

# 서버 -> 클라이언트: 정보 조회 응답 시 사용하는 데이터 (비밀번호 제외)
class UserResponse(BaseModel):
    id: int
    email: EmailStr
    name: str
    created_at: datetime

    class Config:
        from_attributes = True  # SQLAlchemy ORM 객체를 Pydantic 모델로 변환할 수 있게 해줍니다.

# 회원 정보 수정 요청 (이름, 이메일 등 선택적 수정)
class UserUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None

# 비밀번호 변경 요청 (현재 비밀번호 검증 포함)
class UserPasswordUpdate(BaseModel):
    current_password: str
    new_password: str

# ==========================================
# 2. FocusSession (집중 세션) 스키마
# ==========================================

# 세션 시작 요청
class SessionCreate(BaseModel):
    user_id: int

# 세션 종료/업데이트 요청
class SessionUpdate(BaseModel):
    end_time: datetime
    status: str

# 세션 정보 응답
class SessionResponse(BaseModel):
    id: int
    user_id: int
    start_time: datetime
    end_time: Optional[datetime] = None  # 아직 종료되지 않은 세션은 None일 수 있음
    status: str

    class Config:
        from_attributes = True

# ==========================================
# 3. FocusLog (실시간 집중도 로그) 스키마
# ==========================================

# 실시간 로그 데이터 기록 요청
class LogCreate(BaseModel):
    session_id: int
    focus_score: float
    state: str

# 로그 데이터 응답
class LogResponse(BaseModel):
    id: int
    session_id: int
    timestamp: datetime
    focus_score: float
    state: str

    class Config:
        from_attributes = True

# ==========================================
# 4. FocusAnalyzeCreate 조건 점수 스키마
# ==========================================

class FocusAnalyzeCreate(BaseModel):
    eye_score: float = Field(..., ge=0, le=100, description="눈동자 집중도 점수 (0~100)")
    head_score: float = Field(..., ge=0, le=100, description="안면 자세 점수 (0~100)")
    body_score: float = Field(..., ge=0, le=100, description="신체 움직임 점수 (0~100)")
    is_absent: bool = Field(..., description="자리 이탈 여부 (True: 이탈, False: 자리 있음)")

class FocusAnalyzeResponse(BaseModel):
    id: int
    eye_score: float
    head_score: float
    body_score: float
    is_absent: bool
    created_at: datetime

    class Config:
        from_attributes = True

#AI 
#=================================================

# 1. Event Tracking Log Data
class AnalysisEventResponse(BaseModel):
    id: int
    session_id: str
    event_type: Optional[str] = None
    start_sec: Optional[float] = None
    end_sec: Optional[float] = None
    score: Optional[float] = None

    class Config:
        from_attributes = True

# 2. Custom AI Feedback Insights
class AnalysisFeedbackResponse(BaseModel):
    id: int
    session_id: str
    feedback_text: str
    updated_at: datetime

    class Config:
        from_attributes = True

# 3. Macro Metrics Session Score Summary
class AnalysisSummaryResponse(BaseModel):
    id: int
    session_id: str
    focus_ratio: Optional[float] = None
    absent_count: Optional[int] = None
    absent_total_sec: Optional[float] = None
    away_count: Optional[int] = None
    away_total_sec: Optional[float] = None
    bad_posture_ratio: Optional[float] = None
    processing_time_sec: Optional[float] = None
    camera_type: Optional[str] = None
    version: Optional[str] = None
    analyzed_at: datetime

    class Config:
        from_attributes = True

# 4. Chronological Focus Trend Timeline Chart Array
class AnalysisTimelineResponse(BaseModel):
    id: int
    session_id: str
    t: Optional[float] = None
    state: Optional[str] = None

    class Config:
        from_attributes = True