import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import AuditLog, Role, User
from app.schemas import AuditOut, InviteIn, UserOut, UserPatch
from app.security import require_admin
from app.services import active_admin_count, audit, is_valid_github_login

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/users", response_model=list[UserOut])
def list_users(admin: User = Depends(require_admin), db: Session = Depends(get_db)) -> list[User]:
    return list(
        db.scalars(select(User).where(User.org_id == admin.org_id).order_by(User.created_at)).all()
    )


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def invite_user(body: InviteIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)) -> User:
    login = body.github_login.strip().lstrip("@")
    if not is_valid_github_login(login):
        raise HTTPException(422, "Not a valid GitHub username")
    if db.scalars(select(User).where(User.github_login_lower == login.lower())).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "This GitHub user is already in Rino")

    user = User(
        org_id=admin.org_id,
        github_login=login,
        github_login_lower=login.lower(),
        role=body.role,
        is_active=True,
        invited_by_id=admin.id,
    )
    db.add(user)
    db.flush()
    audit(
        db,
        "user.invited",
        org_id=admin.org_id,
        actor=admin,
        target_type="user",
        target_id=str(user.id),
        details={"github_login": login, "role": body.role.value},
    )
    db.commit()
    return user


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(
    user_id: uuid.UUID,
    body: UserPatch,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> User:
    user = db.get(User, user_id)
    if user is None or user.org_id != admin.org_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")

    loses_admin = user.role == Role.admin and user.is_active and (
        (body.role is not None and body.role != Role.admin) or body.is_active is False
    )
    if loses_admin and active_admin_count(db, admin.org_id) <= 1:
        raise HTTPException(status.HTTP_409_CONFLICT, "Rino needs at least one active Admin")

    changes: dict = {}
    if body.role is not None and body.role != user.role:
        changes["role"] = {"from": user.role.value, "to": body.role.value}
        user.role = body.role
    if body.is_active is not None and body.is_active != user.is_active:
        changes["is_active"] = {"from": user.is_active, "to": body.is_active}
        user.is_active = body.is_active

    if changes:
        audit(
            db,
            "user.updated",
            org_id=admin.org_id,
            actor=admin,
            target_type="user",
            target_id=str(user.id),
            details={"github_login": user.github_login, **changes},
        )
        db.commit()
    return user


@router.get("/audit", response_model=list[AuditOut])
def list_audit(
    limit: int = Query(50, ge=1, le=200),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[AuditLog]:
    return list(
        db.scalars(
            select(AuditLog)
            .where(AuditLog.org_id == admin.org_id)
            .order_by(AuditLog.created_at.desc())
            .limit(limit)
        ).all()
    )
