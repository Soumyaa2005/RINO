import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models import Role


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
