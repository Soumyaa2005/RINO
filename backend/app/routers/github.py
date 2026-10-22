"""GitHub App: install flow, repo sync, webhooks, and per-repo test environment (Admin)."""

import logging
import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.git_providers.base import GitProvider, GitProviderError, InvalidWebhookSignature
from app.git_providers.github import get_git_provider
from app.models import ConfigStatus, GithubInstallation, Repo, RepoTestConfig, Role, User, utcnow
from app.repo_sync import mark_installation_removed, sync_installation
from app.schemas import (
    GithubStatusOut,
    InstallationOut,
    RepoOut,
    RepoPatch,
    SyncResultOut,
    WorkflowFileOut,
)
from app.security import get_current_user, require_admin
from app.services import audit
from app.repo_checks import TestConfigIn, check_test_env

log = logging.getLogger(__name__)
router = APIRouter(tags=["github"])

STATE_COOKIE = "rino_install_state"
SETUP_PATH = "/api/github/setup"


def _bad_gateway(exc: GitProviderError) -> HTTPException:
    return HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc))


def _to_repositories(query: str) -> RedirectResponse:
    resp = RedirectResponse(f"/repositories?{query}", status_code=status.HTTP_303_SEE_OTHER)
    resp.delete_cookie(STATE_COOKIE, path=SETUP_PATH)
    return resp


# ---------------------------------------------------------------- install flow


@router.get("/api/admin/github/install")
def start_install(admin: User = Depends(require_admin), provider: GitProvider = Depends(get_git_provider)) -> RedirectResponse:
    settings = get_settings()
    if not settings.github_app_configured:
        return _to_repositories("error=app_not_configured")
    state = secrets.token_urlsafe(32)
    resp = RedirectResponse(provider.install_url(state), status_code=status.HTTP_303_SEE_OTHER)
    resp.set_cookie(STATE_COOKIE, state, max_age=900, httponly=True, secure=settings.is_production, samesite="lax", path=SETUP_PATH)
    return resp


@router.get(SETUP_PATH)
def finish_install(
    request: Request,
    installation_id: int | None = None,
    setup_action: str | None = None,
    state: str | None = None,
    db: Session = Depends(get_db),
    provider: GitProvider = Depends(get_git_provider),
) -> RedirectResponse:
    """GitHub's "Setup URL": GitHub sends the Admin here after installing or updating the App."""
    try:
        user = get_current_user(request, db)
    except HTTPException:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    if user.role != Role.admin:
        return _to_repositories("error=forbidden")
    if setup_action == "request":
        return _to_repositories("error=install_requested")
    if installation_id is None:
        return _to_repositories("error=install_failed")

    inst = db.scalars(select(GithubInstallation).where(GithubInstallation.installation_id == installation_id)).first()
    if inst is not None and inst.org_id != user.org_id:
        return _to_repositories("error=install_failed")

    # A new installation is only bound to this org if this Admin started the
    # install from Rino (matching state). Updates to a known one can come
    # straight from GitHub's settings page, which sends no state.
    expected = request.cookies.get(STATE_COOKIE)
    state_ok = bool(state and expected and secrets.compare_digest(state, expected))
    if inst is None and not state_ok:
        return _to_repositories("error=invalid_state")

    try:
        info = provider.get_connection(installation_id)
    except GitProviderError as exc:
        log.warning("Install check failed: %s", exc)
        return _to_repositories("error=install_failed")

    created = inst is None
    if created:
        inst = GithubInstallation(
            org_id=user.org_id,
            installation_id=info.connection_id,
            account_login=info.account_login,
            account_type=info.account_type,
            suspended=info.suspended,
            created_by_id=user.id,
        )
        db.add(inst)
        db.flush()

    try:
        counts = sync_installation(db, provider, inst)
    except GitProviderError as exc:
        db.rollback()
        log.warning("Repo sync failed: %s", exc)
        return _to_repositories("error=sync_failed")

    audit(
        db,
        "github.installed" if created else "github.install_updated",
        org_id=user.org_id,
        actor=user,
        target_type="installation",
        target_id=str(inst.installation_id),
        details={"account": inst.account_login, **counts},
    )
    db.commit()
    return _to_repositories("installed=1")


# ---------------------------------------------------------------- webhooks


@router.post("/api/webhooks/github", status_code=status.HTTP_200_OK)
async def github_webhook(request: Request, db: Session = Depends(get_db), provider: GitProvider = Depends(get_git_provider)) -> dict:
    body = await request.body()
    try:
        event = provider.parse_webhook({k.lower(): v for k, v in request.headers.items()}, body)
    except InvalidWebhookSignature:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid signature")

    if event.kind == "ignored" or event.connection_id is None:
        return {"handled": False}
    inst = db.scalars(select(GithubInstallation).where(GithubInstallation.installation_id == event.connection_id)).first()
    if inst is None:
        # Installs are only linked through Rino's own install flow.
        return {"handled": False}

    if event.kind == "installation":
        if event.action == "deleted":
            mark_installation_removed(db, inst)
            if hasattr(provider, "forget_installation"):
                provider.forget_installation(inst.installation_id)
        elif event.action == "suspend":
            inst.suspended = True
        elif event.action == "unsuspend":
            inst.suspended = False
        else:
            return {"handled": False}
        audit(db, f"github.installation_{event.action}", org_id=inst.org_id, actor_label="github", target_type="installation", target_id=str(inst.installation_id))
        db.commit()
        return {"handled": True}

    if event.kind == "installation_repositories" and inst.removed_at is None:
        try:
            counts = sync_installation(db, provider, inst)
        except GitProviderError as exc:
            db.rollback()
            log.warning("Webhook repo sync failed: %s", exc)
            return {"handled": False}
        audit(db, "github.repos_synced", org_id=inst.org_id, actor_label="github", target_type="installation", target_id=str(inst.installation_id), details=counts)
        db.commit()
        return {"handled": True}

    return {"handled": False}


# ---------------------------------------------------------------- admin: installations


@router.get("/api/admin/github/status", response_model=GithubStatusOut)
def github_status(admin: User = Depends(require_admin), db: Session = Depends(get_db)) -> GithubStatusOut:
    settings = get_settings()
    counts = dict(
        db.execute(
            select(Repo.installation_pk, func.count()).where(Repo.removed_at.is_(None)).group_by(Repo.installation_pk)
        ).all()
    )
    installs = db.scalars(
        select(GithubInstallation).where(GithubInstallation.org_id == admin.org_id).order_by(GithubInstallation.created_at)
    ).all()
    return GithubStatusOut(
        app_configured=settings.github_app_configured,
        webhooks_configured=bool(settings.github_webhook_secret),
        app_slug=settings.github_app_slug or None,
        installations=[
            InstallationOut(
                id=i.id,
                installation_id=i.installation_id,
                account_login=i.account_login,
                account_type=i.account_type,
                suspended=i.suspended,
                removed=i.removed_at is not None,
                synced_at=i.synced_at,
                repo_count=counts.get(i.id, 0),
            )
            for i in installs
        ],
    )


@router.post("/api/admin/github/installations/{inst_id}/sync", response_model=SyncResultOut)
def sync_now(
    inst_id: uuid.UUID,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
    provider: GitProvider = Depends(get_git_provider),
) -> SyncResultOut:
    inst = db.get(GithubInstallation, inst_id)
    if inst is None or inst.org_id != admin.org_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Installation not found")
    try:
        counts = sync_installation(db, provider, inst)
    except GitProviderError as exc:
        db.rollback()
        if exc.status == 404:
            mark_installation_removed(db, inst)
            db.commit()
            raise HTTPException(status.HTTP_409_CONFLICT, "This installation was removed on GitHub. Install the App again.")
        raise _bad_gateway(exc)
    audit(db, "github.repos_synced", org_id=admin.org_id, actor=admin, target_type="installation", target_id=str(inst.installation_id), details=counts)
    db.commit()
    return SyncResultOut(**counts)


# ---------------------------------------------------------------- admin: repos and test environment


def _admin_repo(db: Session, admin: User, repo_id: uuid.UUID) -> Repo:
    repo = db.get(Repo, repo_id)
    if repo is None or repo.org_id != admin.org_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Repository not found")
    return repo


@router.get("/api/admin/repos", response_model=list[RepoOut])
def admin_list_repos(admin: User = Depends(require_admin), db: Session = Depends(get_db)) -> list[RepoOut]:
    repos = db.scalars(select(Repo).where(Repo.org_id == admin.org_id).order_by(Repo.removed_at.is_not(None), Repo.full_name)).all()
    return [RepoOut.build(r) for r in repos]


@router.patch("/api/admin/repos/{repo_id}", response_model=RepoOut)
def admin_update_repo(repo_id: uuid.UUID, body: RepoPatch, admin: User = Depends(require_admin), db: Session = Depends(get_db)) -> RepoOut:
    repo = _admin_repo(db, admin, repo_id)
    if repo.enabled != body.enabled:
        repo.enabled = body.enabled
        audit(db, "repo.enabled" if body.enabled else "repo.disabled", org_id=admin.org_id, actor=admin, target_type="repo", target_id=str(repo.id), details={"repo": repo.full_name})
        db.commit()
    return RepoOut.build(repo)


@router.get("/api/admin/repos/{repo_id}/workflows", response_model=list[WorkflowFileOut])
def admin_list_workflows(
    repo_id: uuid.UUID,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
    provider: GitProvider = Depends(get_git_provider),
) -> list[WorkflowFileOut]:
    repo = _admin_repo(db, admin, repo_id)
    try:
        names = provider.list_dir(repo.installation.installation_id, repo.full_name, ".github/workflows", repo.default_branch) or []
    except GitProviderError as exc:
        raise _bad_gateway(exc)
    return [WorkflowFileOut(path=f".github/workflows/{n}") for n in sorted(names) if n.endswith((".yml", ".yaml"))]


def _apply_check(db: Session, provider: GitProvider, repo: Repo, cfg: TestConfigIn, row: RepoTestConfig) -> None:
    problems, warnings, default_branch = check_test_env(provider, repo.installation.installation_id, repo.full_name, cfg)
    if default_branch:
        repo.default_branch = default_branch
    row.problems = problems
    row.warnings = warnings
    row.status = ConfigStatus.needs_attention if problems else ConfigStatus.ready
    row.last_checked_at = utcnow()


@router.put("/api/admin/repos/{repo_id}/test-config", response_model=RepoOut)
def admin_save_test_config(
    repo_id: uuid.UUID,
    body: TestConfigIn,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
    provider: GitProvider = Depends(get_git_provider),
) -> RepoOut:
    repo = _admin_repo(db, admin, repo_id)
    if repo.removed_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This repository is no longer shared with the GitHub App")

    row = repo.test_config or RepoTestConfig(repo_id=repo.id, status=ConfigStatus.needs_attention, problems=[], warnings=[])
    for field in ("runner", "workflow_file", "setup_command", "test_command", "python_version", "shared_instance"):
        setattr(row, field, getattr(body, field))
    row.updated_by_id = admin.id
    if repo.test_config is None:
        db.add(row)
        repo.test_config = row

    _apply_check(db, provider, repo, body, row)
    audit(
        db,
        "repo.test_config_saved",
        org_id=admin.org_id,
        actor=admin,
        target_type="repo",
        target_id=str(repo.id),
        details={"repo": repo.full_name, "runner": body.runner.value, "status": row.status.value},
    )
    db.commit()
    return RepoOut.build(repo)


@router.post("/api/admin/repos/{repo_id}/test-config/check", response_model=RepoOut)
def admin_check_test_config(
    repo_id: uuid.UUID,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
    provider: GitProvider = Depends(get_git_provider),
) -> RepoOut:
    repo = _admin_repo(db, admin, repo_id)
    row = repo.test_config
    if row is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Save a test environment first")
    cfg = TestConfigIn.model_validate(
        {f: getattr(row, f) for f in ("runner", "workflow_file", "setup_command", "test_command", "python_version", "shared_instance")}
    )
    _apply_check(db, provider, repo, cfg, row)
    db.commit()
    return RepoOut.build(repo)
