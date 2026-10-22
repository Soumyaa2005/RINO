"""Keep Rino's repo list in step with what the GitHub App can see."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.git_providers.base import GitProvider
from app.models import GithubInstallation, Repo, utcnow


def sync_installation(db: Session, provider: GitProvider, inst: GithubInstallation) -> dict:
    """Re-read the installation and its repos from GitHub. Commits nothing; caller commits.

    Repos no longer shared with the App are marked removed (kept for history).
    Returns counts for the audit log.
    """
    info = provider.get_connection(inst.installation_id)
    inst.account_login = info.account_login
    inst.account_type = info.account_type
    inst.suspended = info.suspended

    remote = {r.provider_repo_id: r for r in provider.list_repos(inst.installation_id)}
    existing = {r.github_repo_id: r for r in db.scalars(select(Repo).where(Repo.github_repo_id.in_(remote.keys()))).all()} if remote else {}
    current = db.scalars(select(Repo).where(Repo.installation_pk == inst.id)).all()

    added = updated = removed = 0
    now = utcnow()

    for repo_id, info_r in remote.items():
        repo = existing.get(repo_id)
        if repo is None:
            db.add(
                Repo(
                    org_id=inst.org_id,
                    installation_pk=inst.id,
                    github_repo_id=repo_id,
                    full_name=info_r.full_name,
                    default_branch=info_r.default_branch,
                    private=info_r.private,
                    enabled=True,
                )
            )
            added += 1
        else:
            if repo.org_id != inst.org_id:
                continue  # never move a repo between orgs
            if repo.removed_at is not None:
                added += 1
            else:
                updated += 1
            repo.installation_pk = inst.id
            repo.full_name = info_r.full_name
            repo.default_branch = info_r.default_branch
            repo.private = info_r.private
            repo.removed_at = None

    for repo in current:
        if repo.github_repo_id not in remote and repo.removed_at is None:
            repo.removed_at = now
            removed += 1

    inst.synced_at = now
    inst.removed_at = None
    return {"added": added, "updated": updated, "removed": removed, "total": len(remote)}


def mark_installation_removed(db: Session, inst: GithubInstallation) -> None:
    now = utcnow()
    inst.removed_at = now
    for repo in db.scalars(select(Repo).where(Repo.installation_pk == inst.id, Repo.removed_at.is_(None))).all():
        repo.removed_at = now
