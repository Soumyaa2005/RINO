"""Session cookies, CSRF check and role guards.

Every request re-loads the user from the database, so a role change or
deactivation takes effect on the very next request.
"""

import uuid
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import Role, User

SESSION_COOKIE = "rino_session"
CSRF_HEADER = "x-rino-csrf"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def create_session_token(user_id: uuid.UUID) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {"sub": str(user_id), "iat": now, "exp": now + timedelta(days=settings.session_days)}
    return jwt.encode(payload, settings.session_secret, algorithm="HS256")


def set_session_cookie(response: Response, user_id: uuid.UUID) -> None:
    settings = get_settings()
    response.set_cookie(
        SESSION_COOKIE,
        create_session_token(user_id),
        max_age=settings.session_days * 86400,
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


def _user_id_from_cookie(request: Request) -> uuid.UUID | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    try:
        payload = jwt.decode(token, get_settings().session_secret, algorithms=["HS256"])
        return uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user_id = _user_id_from_cookie(request)
    user = db.get(User, user_id) if user_id else None
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in")
    return user


def require_role(*roles: Role):
    def checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You don't have permission to do this")
        return user

    return checker


require_admin = require_role(Role.admin)
require_member = require_role(Role.admin, Role.developer)


def csrf_ok(request: Request) -> bool:
    """State-changing API calls must carry a custom header.

    Browsers won't let another site add custom headers to a cross-site request
    without a CORS preflight, and Rino allows no cross-origin calls, so the
    header proves the request came from Rino's own frontend.
    """
    if request.method in SAFE_METHODS or not request.url.path.startswith("/api/"):
        return True
    # Webhooks come from GitHub, not a browser; they're authenticated by signature instead.
    if request.url.path.startswith("/api/webhooks/"):
        return True
    return request.headers.get(CSRF_HEADER) == "1"
