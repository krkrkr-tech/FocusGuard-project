"""
CERMS - Auth router: login / token endpoint.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, AuditLog
from app.schemas import TokenRequest, TokenResponse, UserOut
from app.auth import verify_password, create_access_token, get_current_user

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/token", response_model=TokenResponse)
def login(body: TokenRequest, db: Session = Depends(get_db)):
    """Authenticate user and return JWT access token."""
    user = db.query(User).filter(User.username == body.username).first()
    if not user or not verify_password(body.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    # Audit: login
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
    """Return details of the currently authenticated user."""
    return user
