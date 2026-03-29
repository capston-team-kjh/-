from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from passlib.context import CryptContext

# 최상위 경로에 있는 모듈들 불러오기
import models, schemas
from database import get_db

# 라우터 설정 (URL 앞부분과 API 문서에 표시될 카테고리 이름 지정)
router = APIRouter(
    prefix="/api/v1/users",
    tags=["Users (회원 관리)"]
)

# 비밀번호 암호화 도구 설정
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def get_password_hash(password: str):
    """비밀번호를 안전한 해시 문자열로 변환합니다."""
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str):
    """입력받은 비밀번호와 DB에 저장된 해시 비밀번호가 일치하는지 확인합니다."""
    return pwd_context.verify(plain_password, hashed_password)


@router.post("/register", response_model=schemas.UserResponse, status_code=status.HTTP_201_CREATED)
def register_user(user: schemas.UserCreate, db: Session = Depends(get_db)):
    """새로운 사용자를 등록합니다."""
    # 1. 이메일 중복 검사
    db_user = db.query(models.User).filter(models.User.email == user.email).first()
    if db_user:
        raise HTTPException(status_code=400, detail="이미 가입된 이메일입니다.")
    
    # 2. 비밀번호 암호화 및 새 유저 객체 생성
    hashed_password = get_password_hash(user.password)
    new_user = models.User(
        email=user.email,
        password_hash=hashed_password,
        name=user.name
    )
    
    # 3. 데이터베이스에 저장
    db.add(new_user)
    db.commit()
    db.refresh(new_user) # 저장 후 생성된 id 등의 정보를 다시 가져옵니다.
    
    return new_user


@router.post("/login")
def login_user(user_credentials: schemas.UserLogin, db: Session = Depends(get_db)):
    """이메일과 비밀번호로 로그인을 진행합니다."""
    # 1. 이메일로 유저 찾기
    user = db.query(models.User).filter(models.User.email == user_credentials.email).first()
    
    # 2. 유저가 없거나 비밀번호가 틀리면 에러 발생
    if not user or not verify_password(user_credentials.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="이메일 또는 비밀번호가 일치하지 않습니다."
        )
    
    # 3. 로그인 성공 시 응답 (나중에 여기에 JWT 토큰 발급 로직이 들어갈 수 있습니다)
    return {
        "message": f"환영합니다, {user.name}님! 로그인이 완료되었습니다.", 
        "user_id": user.id, 
        "name": user.name
    }