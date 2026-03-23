from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
import models, schemas
from database import get_db

router = APIRouter(
    prefix="/api/v1/analysis",
    tags=["Analysis (AI 집중도 분석)"]
)

@router.post("/", response_model=schemas.FocusAnalyzeResponse, status_code=201)
def analyze_focus(data: schemas.FocusAnalyzeCreate, db: Session = Depends(get_db)):
    """AI 생체 데이터와 자리 이탈 여부를 받아 개별 점수를 저장합니다."""
    
    # 1. 자리 이탈 판정: 자리를 비웠다면 모든 세부 점수를 0점으로 초기화
    if data.is_absent:
        data.eye_score = 0.0
        data.head_score = 0.0
        data.body_score = 0.0
    
    # 2. DB에 저장할 객체 생성 (final_score 제외)
    db_analysis = models.FocusAnalysis(
        eye_score=data.eye_score,
        head_score=data.head_score,
        body_score=data.body_score,
        is_absent=data.is_absent
    )
    
    # 3. DB에 밀어넣기
    db.add(db_analysis)
    db.commit()
    db.refresh(db_analysis)
    
    return db_analysis