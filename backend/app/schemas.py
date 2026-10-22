import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models import ConfigStatus, Role, RunnerType


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    github_login: str
    name: str | None
    avatar_url: str | None
    role: Role
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None


class MeOut(UserOut):
    org_name: str


class InviteIn(BaseModel):
    github_login: str
    role: Role = Role.developer


class UserPatch(BaseModel):
    role: Role | None = None
    is_active: bool | None = None


class AuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    actor_label: str | None
    action: str
    target_type: str | None
    target_id: str | None
    details: dict
    created_at: datetime


class AuthConfigOut(BaseModel):
    github_configured: bool
    dev_login: bool


class DevLoginIn(BaseModel):
    github_login: str


class TestConfigOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    runner: RunnerType
    workflow_file: str | None
    setup_command: str | None
    test_command: str | None
    python_version: str
    shared_instance: bool
    status: ConfigStatus
    problems: list[str]
    warnings: list[str]
    last_checked_at: datetime | None


class RepoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    full_name: str
    default_branch: str
    private: bool
    enabled: bool
    removed: bool
    installation_account: str
    installation_usable: bool
    test_config: TestConfigOut | None

    @classmethod
    def build(cls, repo) -> "RepoOut":
        return cls(
            id=repo.id,
            full_name=repo.full_name,
            default_branch=repo.default_branch,
            private=repo.private,
            enabled=repo.enabled,
            removed=repo.removed_at is not None,
            installation_account=repo.installation.account_login,
            installation_usable=repo.installation.usable,
            test_config=TestConfigOut.model_validate(repo.test_config) if repo.test_config else None,
        )


class InstallationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    installation_id: int
    account_login: str
    account_type: str
    suspended: bool
    removed: bool
    synced_at: datetime | None
    repo_count: int


class GithubStatusOut(BaseModel):
    app_configured: bool
    webhooks_configured: bool
    app_slug: str | None
    installations: list[InstallationOut]


class RepoPatch(BaseModel):
    enabled: bool


class SyncResultOut(BaseModel):
    added: int
    updated: int
    removed: int
    total: int


class WorkflowFileOut(BaseModel):
    path: str
