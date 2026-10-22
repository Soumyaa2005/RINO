import os
import tempfile

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

# Throwaway RSA key standing in for the GitHub App's private key.
_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
APP_PRIVATE_KEY = _key.private_bytes(
    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
).decode()
APP_PUBLIC_KEY = _key.public_key().public_bytes(
    serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
).decode()
APP_ID = "123456"
WEBHOOK_SECRET = "test-webhook-secret-0123456789"

# Must be set before the app modules are imported (the engine is built at import).
_tmp = tempfile.mkdtemp()
os.environ.setdefault("DATABASE_URL", f"sqlite+pysqlite:///{_tmp}/rino_test.db")
os.environ["APP_ENV"] = "development"
os.environ["SESSION_SECRET"] = "test-secret-" + "x" * 40
os.environ["BOOTSTRAP_ADMIN_GITHUB_LOGIN"] = "octo-admin"
os.environ["GITHUB_CLIENT_ID"] = "test-client"
os.environ["GITHUB_CLIENT_SECRET"] = "test-secret"
os.environ["DEV_LOGIN_ENABLED"] = "true"
os.environ["GITHUB_APP_ID"] = APP_ID
os.environ["GITHUB_APP_SLUG"] = "rino-test"
os.environ["GITHUB_APP_PRIVATE_KEY"] = APP_PRIVATE_KEY.replace("\n", "\\n")
os.environ["GITHUB_APP_PRIVATE_KEY_PATH"] = ""
os.environ["GITHUB_WEBHOOK_SECRET"] = WEBHOOK_SECRET

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.git_providers.github import GitHubProvider, get_git_provider  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Role, User  # noqa: E402
from app.services import get_or_create_org  # noqa: E402
from tests.fake_github import FakeGitHub  # noqa: E402

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
def fake_github():
    """The real GitHubProvider, talking to an in-memory GitHub."""
    fake = FakeGitHub(APP_PUBLIC_KEY, APP_ID)
    provider = GitHubProvider(get_settings(), transport=fake.transport())
    app.dependency_overrides[get_git_provider] = lambda: provider
    yield fake
    app.dependency_overrides.pop(get_git_provider, None)


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
