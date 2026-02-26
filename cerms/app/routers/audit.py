"""
CERMS - Audit log router.

Endpoints:
  GET /audit/  – list audit log entries (admin & auditor only)
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AuditLog, User
from app.schemas import AuditLogOut
from app.auth import require_permissions

router = APIRouter(prefix="/audit", tags=["Audit Log"])


@router.get("/", response_model=List[AuditLogOut])
def list_audit_logs(
    action: Optional[str] = Query(None, description="Filter by action (e.g. incident.create)"),
    limit: int = Query(50, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(require_permissions("audit.read")),
):
    """Retrieve audit log entries (newest first). Only admin & auditor roles."""
    q = db.query(AuditLog)
    if action:
        q = q.filter(AuditLog.action == action)
    return q.order_by(AuditLog.timestamp.desc()).limit(limit).all()
