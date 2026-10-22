"""Repos visible to every signed-in member (repo and branch picker)."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.git_providers.base import GitProvider, GitProviderError
from app.git_providers.github import get_git_provider
from app.models import GithubInstallation, Repo, User
from app.schemas import RepoOut
from app.security import require_member

router = APIRouter(prefix="/api/repos", tags=["repos"])


def _visible(org_id: uuid.UUID):
    return (
        select(Repo)
        .join(GithubInstallation, Repo.installation_pk == GithubInstallation.id)
        .where(
            Repo.org_id == org_id,
            Repo.enabled.is_(True),
            Repo.removed_at.is_(None),
            GithubInstallation.removed_at.is_(None),
            GithubInstallation.suspended.is_(False),
        )
    )


@router.get("", response_model=list[RepoOut])
def list_repos(user: User = Depends(require_member), db: Session = Depends(get_db)) -> list[RepoOut]:
    return [RepoOut.build(r) for r in db.scalars(_visible(user.org_id).order_by(Repo.full_name)).all()]


@router.get("/{repo_id}/branches", response_model=list[str])
def list_branches(
    repo_id: uuid.UUID,
    user: User = Depends(require_member),
    db: Session = Depends(get_db),
    provider: GitProvider = Depends(get_git_provider),
) -> list[str]:
    repo = db.scalars(_visible(user.org_id).where(Repo.id == repo_id)).first()
    if repo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Repository not found")
    try:
        branches = provider.list_branches(repo.installation.installation_id, repo.full_name)
    except GitProviderError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc))
    # Default branch first, the rest alphabetical.
    rest = sorted(b for b in branches if b != repo.default_branch)
    return ([repo.default_branch] if repo.default_branch in branches else []) + rest
