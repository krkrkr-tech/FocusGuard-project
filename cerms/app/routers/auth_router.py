from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, AuditLog
from app.schemas import TokenResponse, UserOut
from app.auth import verify_password, create_access_token, get_current_user

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/token", response_model=TokenResponse)
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == form.username).first()
    if not user or not verify_password(form.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    audit = AuditLog(
        user_id=user.id,
        username=user.username,
        action="auth.login",
        resource_type="user",
        resource_id=user.id,
        details="User logged in successfully",
    )
    db.add(audit)
    db.commit()

    token = create_access_token(data={"sub": user.username, "role": user.role.value})
    return TokenResponse(access_token=token)


@router.get("/me", response_model=UserOut)
def get_me(user: User = Depends(get_current_user)):
    return user
