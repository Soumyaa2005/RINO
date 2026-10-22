import logging
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app import github_oauth
from app.config import get_settings
from app.db import get_db
from app.models import User
from app.schemas import AuthConfigOut, DevLoginIn, MeOut, UserOut
from app.security import clear_session_cookie, get_current_user, set_session_cookie
from app.services import AccessDenied, GithubIdentity, audit, is_valid_github_login, resolve_login

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])

STATE_COOKIE = "rino_oauth_state"
STATE_COOKIE_PATH = "/api/auth/github"


def _login_error(code: str) -> RedirectResponse:
    resp = RedirectResponse(f"/login?error={code}", status_code=status.HTTP_303_SEE_OTHER)
    resp.delete_cookie(STATE_COOKIE, path=STATE_COOKIE_PATH)
    return resp


@router.get("/config", response_model=AuthConfigOut)
def auth_config() -> AuthConfigOut:
    settings = get_settings()
    return AuthConfigOut(github_configured=settings.github_configured, dev_login=settings.dev_login_allowed)


@router.get("/github/login")
def github_login() -> RedirectResponse:
    settings = get_settings()
    if not settings.github_configured:
        return _login_error("github_not_configured")
    state = secrets.token_urlsafe(32)
    resp = RedirectResponse(github_oauth.authorize_url(state), status_code=status.HTTP_303_SEE_OTHER)
    resp.set_cookie(
        STATE_COOKIE,
        state,
        max_age=600,
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
        path=STATE_COOKIE_PATH,
    )
    return resp


@router.get("/github/callback")
def github_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    if error:
        return _login_error("github_cancelled")
    expected = request.cookies.get(STATE_COOKIE)
    if not code or not state or not expected or not secrets.compare_digest(state, expected):
        return _login_error("invalid_state")

    try:
        identity = github_oauth.fetch_identity(code)
    except Exception as exc:  # GitHub errors and network errors
        log.warning("GitHub login failed: %s", type(exc).__name__)
        return _login_error("github_failed")

    try:
        user = resolve_login(db, identity)
    except AccessDenied:
        return _login_error("no_access")

    resp = RedirectResponse("/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    resp.delete_cookie(STATE_COOKIE, path=STATE_COOKIE_PATH)
    set_session_cookie(resp, user.id)
    return resp


@router.post("/dev-login", status_code=status.HTTP_204_NO_CONTENT)
def dev_login(body: DevLoginIn, db: Session = Depends(get_db)) -> Response:
    """Local testing only. Disabled unless DEV_LOGIN_ENABLED=true, and never in production."""
    if not get_settings().dev_login_allowed:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    login = body.github_login.strip()
    if not is_valid_github_login(login):
        raise HTTPException(422, "Not a valid GitHub username")
    try:
        user = resolve_login(db, GithubIdentity(login=login))
    except AccessDenied:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No access. Ask your Admin to invite you.")
    resp = Response(status_code=status.HTTP_204_NO_CONTENT)
    set_session_cookie(resp, user.id)
    return resp


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, db: Session = Depends(get_db)) -> Response:
    resp = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_session_cookie(resp)
    try:
        user = get_current_user(request, db)
    except HTTPException:
        return resp
    audit(db, "auth.logout", org_id=user.org_id, actor=user)
    db.commit()
    return resp


@router.get("/me", response_model=MeOut)
def me(user: User = Depends(get_current_user)) -> MeOut:
    return MeOut(**UserOut.model_validate(user).model_dump(), org_name=user.org.name)
