import os
import tempfile

# Must be set before the app modules are imported (the engine is built at import).
_tmp = tempfile.mkdtemp()
os.environ.setdefault("DATABASE_URL", f"sqlite+pysqlite:///{_tmp}/rino_test.db")
os.environ["APP_ENV"] = "development"
os.environ["SESSION_SECRET"] = "test-secret-" + "x" * 40
os.environ["BOOTSTRAP_ADMIN_GITHUB_LOGIN"] = "octo-admin"
os.environ["GITHUB_CLIENT_ID"] = "test-client"
os.environ["GITHUB_CLIENT_SECRET"] = "test-secret"
os.environ["DEV_LOGIN_ENABLED"] = "true"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Role, User  # noqa: E402
from app.services import get_or_create_org  # noqa: E402

CSRF = {"X-Rino-CSRF": "1"}


@pytest.fixture(autouse=True)
def fresh_db():
    get_settings.cache_clear()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


@pytest.fixture
def db():
    with SessionLocal() as session:
        yield session


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def make_user(db, login: str, role: Role = Role.developer, active: bool = True, github_id: int | None = None) -> User:
    org = get_or_create_org(db)
    user = User(
        org_id=org.id,
        github_login=login,
        github_login_lower=login.lower(),
        github_id=github_id,
        role=role,
        is_active=active,
    )
    db.add(user)
    db.commit()
    return user


def login_as(client: TestClient, login: str) -> None:
    resp = client.post("/api/auth/dev-login", json={"github_login": login}, headers=CSRF)
    assert resp.status_code == 204, resp.text
