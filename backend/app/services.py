"""Small shared helpers: org bootstrap, audit logging, login resolution."""

import re
import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import AuditLog, Org, Role, User, utcnow

GITHUB_LOGIN_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}$")


def is_valid_github_login(login: str) -> bool:
    return bool(GITHUB_LOGIN_RE.fullmatch(login))


def get_or_create_org(db: Session) -> Org:
    """v1 runs a single organization per Rino install."""
    org = db.scalars(select(Org).order_by(Org.created_at).limit(1)).first()
    if org is None:
        org = Org(name=get_settings().org_name)
        db.add(org)
        db.commit()
    return org


def audit(
    db: Session,
    action: str,
    *,
    org_id: uuid.UUID | None,
    actor: User | None = None,
    actor_label: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    details: dict | None = None,
) -> None:
    db.add(
        AuditLog(
            org_id=org_id,
            actor_user_id=actor.id if actor else None,
            actor_label=actor_label or (actor.github_login if actor else None),
            action=action,
            target_type=target_type,
            target_id=target_id,
            details=details or {},
        )
    )


def active_admin_count(db: Session, org_id: uuid.UUID) -> int:
    return db.scalar(
        select(func.count())
        .select_from(User)
        .where(User.org_id == org_id, User.role == Role.admin, User.is_active.is_(True))
    ) or 0


@dataclass
class GithubIdentity:
    login: str
    github_id: int | None = None
    name: str | None = None
    avatar_url: str | None = None


class AccessDenied(Exception):
    """The person is not a Rino user (not invited, or deactivated)."""


def resolve_login(db: Session, ident: GithubIdentity) -> User:
    """Map a GitHub identity to a Rino user, or raise AccessDenied.

    Order: known GitHub id -> pending invite by login -> bootstrap admin.
    """
    org = get_or_create_org(db)
    login_lower = ident.login.lower()
    user: User | None = None
    by_login = db.scalars(select(User).where(User.github_login_lower == login_lower)).first()

    if ident.github_id is not None:
        user = db.scalars(select(User).where(User.github_id == ident.github_id)).first()

    if user is None:
        # Only claim a row by login if it isn't already bound to a different GitHub account.
        # (github_id is None only for dev login, which is disabled in production.)
        if by_login is not None and (
            by_login.github_id is None or ident.github_id is None or by_login.github_id == ident.github_id
        ):
            user = by_login

    if user is None:
        bootstrap = get_settings().bootstrap_admin_github_login.strip().lower()
        if bootstrap and login_lower == bootstrap and by_login is None and active_admin_count(db, org.id) == 0:
            user = User(
                org_id=org.id,
                github_login=ident.login,
                github_login_lower=login_lower,
                role=Role.admin,
                is_active=True,
            )
            db.add(user)
            db.flush()
            audit(db, "user.bootstrap_admin", org_id=org.id, actor=user, target_type="user", target_id=str(user.id))

    if user is None or not user.is_active:
        audit(
            db,
            "auth.login_denied",
            org_id=org.id,
            actor_label=ident.login,
            details={"reason": "deactivated" if user else "not_invited"},
        )
        db.commit()
        raise AccessDenied()

    # Keep the stored login in sync with renames, unless a different row already holds it.
    if by_login is None or by_login.id == user.id:
        user.github_login = ident.login
        user.github_login_lower = login_lower
    if ident.github_id is not None:
        user.github_id = ident.github_id
    if ident.name is not None:
        user.name = ident.name
    if ident.avatar_url is not None:
        user.avatar_url = ident.avatar_url
    user.last_login_at = utcnow()
    audit(db, "auth.login", org_id=user.org_id, actor=user, target_type="user", target_id=str(user.id))
    db.commit()
    return user
