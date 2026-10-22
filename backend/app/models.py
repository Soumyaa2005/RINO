"""Database models.

Step 1: orgs, users, audit log. Step 2: GitHub App installations, repos and
each repo's test environment. Runs, findings, fixes and PRs come later.
"""

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, Enum, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Role(str, enum.Enum):
    admin = "admin"
    developer = "developer"


class Org(Base):
    __tablename__ = "orgs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orgs.id"), index=True)
    # GitHub logins are case-insensitive, so we store the lowercase form for lookups.
    github_login: Mapped[str] = mapped_column(String(39))
    github_login_lower: Mapped[str] = mapped_column(String(39), unique=True)
    # Set on first real GitHub login; survives the user renaming their GitHub account.
    github_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, nullable=True)
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    role: Mapped[Role] = mapped_column(
        Enum(Role, name="user_role", native_enum=False, create_constraint=True, length=20)
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    invited_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    org: Mapped[Org] = relationship()


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("orgs.id"), index=True, nullable=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    # Free-form so denied logins (no user row) can still be recorded.
    actor_label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    action: Mapped[str] = mapped_column(String(100), index=True)
    target_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class RunnerType(str, enum.Enum):
    sandbox = "sandbox"
    github_actions = "github_actions"
    dev_instance = "dev_instance"


class ConfigStatus(str, enum.Enum):
    ready = "ready"
    needs_attention = "needs_attention"


def _enum(cls: type[enum.Enum], name: str) -> Enum:
    return Enum(cls, name=name, native_enum=False, create_constraint=True, length=30)


class GithubInstallation(Base):
    """One install of Rino's GitHub App on a GitHub user or organization."""

    __tablename__ = "github_installations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orgs.id"), index=True)
    installation_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    account_login: Mapped[str] = mapped_column(String(100))
    account_type: Mapped[str] = mapped_column(String(30))
    suspended: Mapped[bool] = mapped_column(Boolean, default=False)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @property
    def usable(self) -> bool:
        return self.removed_at is None and not self.suspended


class Repo(Base):
    __tablename__ = "repos"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orgs.id"), index=True)
    installation_pk: Mapped[uuid.UUID] = mapped_column(ForeignKey("github_installations.id"), index=True)
    github_repo_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    full_name: Mapped[str] = mapped_column(String(200))
    default_branch: Mapped[str] = mapped_column(String(255))
    private: Mapped[bool] = mapped_column(Boolean, default=True)
    # Admin switch: a disabled repo is hidden from Developers.
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # Set when the repo is no longer shared with the GitHub App.
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    installation: Mapped[GithubInstallation] = relationship()
    test_config: Mapped["RepoTestConfig | None"] = relationship(back_populates="repo", uselist=False)


class RepoTestConfig(Base):
    """Where a repo's tests run, and whether that setup checked out."""

    __tablename__ = "repo_test_configs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    repo_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("repos.id"), unique=True)
    runner: Mapped[RunnerType] = mapped_column(_enum(RunnerType, "runner_type"))
    workflow_file: Mapped[str | None] = mapped_column(String(255), nullable=True)
    setup_command: Mapped[str | None] = mapped_column(String(500), nullable=True)
    test_command: Mapped[str | None] = mapped_column(String(300), nullable=True)
    python_version: Mapped[str] = mapped_column(String(10), default="3.11")
    shared_instance: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[ConfigStatus] = mapped_column(_enum(ConfigStatus, "config_status"))
    problems: Mapped[list] = mapped_column(JSON, default=list)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    repo: Mapped[Repo] = relationship(back_populates="test_config")
