"""
CERMS - Authentication & Role-Based Access Control (RBAC)

Roles:
  admin      – full system access
  dispatcher – create/manage incidents, dispatch units
  responder  – view/update incidents in their assigned zone (ABAC)
  analyst    – read-only analytics & incident data
  auditor    – read-only audit logs

ABAC Rule:
  A responder can ONLY view/update incidents whose h3_index matches
  the responder's assigned_zone_h3 (or its k=1 neighbors).
"""

from datetime import datetime, timedelta, timezone
from typing import Optional, List

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.config import SECRET_KEY, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES
from app.database import get_db
from app.models import User, RoleEnum

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")


# ──────────── Password helpers ────────────

def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


# ──────────── JWT helpers ────────────

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])


# ──────────── Current user dependency ────────────

def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_token(token)
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = db.query(User).filter(User.username == username).first()
    if user is None or not user.is_active:
        raise credentials_exception
    return user


# ──────────── RBAC permission checker ────────────

# Permission matrix: role → set of allowed actions
PERMISSION_MATRIX = {
    RoleEnum.ADMIN: {
        "incident.create", "incident.read", "incident.update", "incident.delete",
        "unit.create", "unit.read", "unit.update",
        "dispatch.create", "dispatch.read",
        "zone.create", "zone.read", "zone.update",
        "analytics.read",
        "audit.read",
        "user.manage",
    },
    RoleEnum.DISPATCHER: {
        "incident.create", "incident.read", "incident.update",
        "unit.read", "unit.update",
        "dispatch.create", "dispatch.read",
        "zone.read",
        "analytics.read",
    },
    RoleEnum.RESPONDER: {
        "incident.read", "incident.update",  # ABAC: restricted to own zone
        "unit.read",
        "dispatch.read",
        "zone.read",
    },
    RoleEnum.ANALYST: {
        "incident.read",
        "unit.read",
        "dispatch.read",
        "zone.read",
        "analytics.read",
    },
    RoleEnum.AUDITOR: {
        "audit.read",
        "incident.read",
        "dispatch.read",
    },
}


def require_permissions(*permissions: str):
    """FastAPI dependency factory — checks if the current user has ALL listed permissions."""
    def checker(user: User = Depends(get_current_user)):
        user_perms = PERMISSION_MATRIX.get(user.role, set())
        for perm in permissions:
            if perm not in user_perms:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Permission denied: {perm}",
                )
        return user
    return checker
