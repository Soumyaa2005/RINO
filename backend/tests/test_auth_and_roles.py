from urllib.parse import parse_qs, urlparse

import pytest

from app import github_oauth
from app.config import Settings, get_settings
from app.models import AuditLog, Role, User
from app.services import GithubIdentity
from tests.conftest import CSRF, login_as, make_user


# ---------- sessions and roles ----------

def test_me_requires_login(client):
    assert client.get("/api/auth/me").status_code == 401


def test_bootstrap_admin_created_on_first_login(client, db):
    login_as(client, "octo-admin")
    me = client.get("/api/auth/me").json()
    assert me["github_login"] == "octo-admin"
    assert me["role"] == "admin"


def test_unknown_user_is_denied(client, db):
    resp = client.post("/api/auth/dev-login", json={"github_login": "stranger"}, headers=CSRF)
    assert resp.status_code == 403
    assert db.query(AuditLog).filter_by(action="auth.login_denied").count() == 1


def test_bootstrap_only_works_while_no_admin_exists(client, db):
    make_user(db, "existing-admin", Role.admin)
    resp = client.post("/api/auth/dev-login", json={"github_login": "octo-admin"}, headers=CSRF)
    assert resp.status_code == 403


def test_developer_cannot_use_admin_endpoints(client, db):
    make_user(db, "dev1", Role.developer)
    login_as(client, "dev1")
    assert client.get("/api/admin/users").status_code == 403
    assert client.get("/api/admin/audit").status_code == 403
    assert client.post("/api/admin/users", json={"github_login": "x"}, headers=CSRF).status_code == 403


def test_admin_invites_and_changes_role(client, db):
    make_user(db, "boss", Role.admin)
    login_as(client, "boss")

    resp = client.post("/api/admin/users", json={"github_login": "@New-Dev", "role": "developer"}, headers=CSRF)
    assert resp.status_code == 201
    new_id = resp.json()["id"]
    assert resp.json()["github_login"] == "New-Dev"

    # Same login in a different case is a duplicate.
    dup = client.post("/api/admin/users", json={"github_login": "new-dev"}, headers=CSRF)
    assert dup.status_code == 409

    patched = client.patch(f"/api/admin/users/{new_id}", json={"role": "admin"}, headers=CSRF)
    assert patched.status_code == 200 and patched.json()["role"] == "admin"

    actions = [a["action"] for a in client.get("/api/admin/audit").json()]
    assert "user.invited" in actions and "user.updated" in actions


def test_invalid_github_login_rejected(client, db):
    make_user(db, "boss", Role.admin)
    login_as(client, "boss")
    for bad in ["", "-bad", "bad-", "a--b", "x" * 40, "has space"]:
        resp = client.post("/api/admin/users", json={"github_login": bad}, headers=CSRF)
        assert resp.status_code == 422, bad


def test_cannot_remove_last_admin(client, db):
    boss = make_user(db, "boss", Role.admin)
    login_as(client, "boss")
    assert client.patch(f"/api/admin/users/{boss.id}", json={"role": "developer"}, headers=CSRF).status_code == 409
    assert client.patch(f"/api/admin/users/{boss.id}", json={"is_active": False}, headers=CSRF).status_code == 409


def test_role_change_applies_on_next_request(client, db):
    make_user(db, "boss", Role.admin)
    dev = make_user(db, "dev1", Role.developer)
    login_as(client, "dev1")
    assert client.get("/api/admin/users").status_code == 403

    dev.role = Role.admin
    db.commit()
    assert client.get("/api/admin/users").status_code == 200


def test_deactivated_user_loses_session(client, db):
    make_user(db, "boss", Role.admin)
    dev = make_user(db, "dev1", Role.developer)
    login_as(client, "dev1")
    assert client.get("/api/auth/me").status_code == 200

    dev.is_active = False
    db.commit()
    assert client.get("/api/auth/me").status_code == 401


def test_tampered_session_cookie_rejected(client, db):
    make_user(db, "dev1", Role.developer)
    login_as(client, "dev1")
    token = client.cookies.get("rino_session")
    client.cookies.set("rino_session", token[:-2] + ("AA" if token[-2:] != "AA" else "BB"))
    assert client.get("/api/auth/me").status_code == 401


# ---------- CSRF ----------

def test_state_changing_calls_need_csrf_header(client, db):
    make_user(db, "boss", Role.admin)
    login_as(client, "boss")
    assert client.post("/api/admin/users", json={"github_login": "someone"}).status_code == 403
    assert client.post("/api/auth/logout").status_code == 403
    assert client.post("/api/auth/logout", headers=CSRF).status_code == 204


# ---------- dev login safety ----------

def test_dev_login_off_by_default(client, db, monkeypatch):
    monkeypatch.setenv("DEV_LOGIN_ENABLED", "false")
    get_settings.cache_clear()
    make_user(db, "dev1")
    resp = client.post("/api/auth/dev-login", json={"github_login": "dev1"}, headers=CSRF)
    assert resp.status_code == 404
    assert client.get("/api/auth/config").json()["dev_login"] is False


def test_production_refuses_dev_login_and_weak_secret():
    with pytest.raises(ValueError):
        Settings(app_env="production", session_secret="x" * 40, dev_login_enabled=True)
    with pytest.raises(ValueError):
        Settings(app_env="production", session_secret="change-me")
    ok = Settings(app_env="production", session_secret="x" * 40, dev_login_enabled=False)
    assert ok.dev_login_allowed is False


# ---------- GitHub OAuth flow ----------

def _start_oauth(client) -> str:
    resp = client.get("/api/auth/github/login", follow_redirects=False)
    assert resp.status_code == 303
    location = urlparse(resp.headers["location"])
    assert location.netloc == "github.com"
    return parse_qs(location.query)["state"][0]


def test_oauth_rejects_bad_state(client):
    _start_oauth(client)
    resp = client.get("/api/auth/github/callback?code=abc&state=wrong", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login?error=invalid_state"


def test_oauth_invited_user_logs_in_and_github_id_is_bound(client, db, monkeypatch):
    make_user(db, "boss", Role.admin)
    make_user(db, "Invited-Dev", Role.developer)
    monkeypatch.setattr(
        github_oauth,
        "fetch_identity",
        lambda code: GithubIdentity(login="invited-dev", github_id=4242, name="Invited Dev", avatar_url="https://a/x.png"),
    )
    state = _start_oauth(client)
    resp = client.get(f"/api/auth/github/callback?code=abc&state={state}", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/dashboard"

    me = client.get("/api/auth/me").json()
    assert me["role"] == "developer" and me["name"] == "Invited Dev"
    db.expire_all()
    assert db.query(User).filter_by(github_login_lower="invited-dev").one().github_id == 4242


def test_oauth_uninvited_user_sent_to_no_access(client, db, monkeypatch):
    make_user(db, "boss", Role.admin)
    monkeypatch.setattr(github_oauth, "fetch_identity", lambda code: GithubIdentity(login="random", github_id=99))
    state = _start_oauth(client)
    resp = client.get(f"/api/auth/github/callback?code=abc&state={state}", follow_redirects=False)
    assert resp.headers["location"] == "/login?error=no_access"
    assert client.get("/api/auth/me").status_code == 401


def test_oauth_login_cannot_hijack_account_bound_to_other_github_id(client, db, monkeypatch):
    make_user(db, "boss", Role.admin)
    make_user(db, "taken", Role.developer, github_id=1)
    # A different GitHub account (id 2) now holds the login "taken".
    monkeypatch.setattr(github_oauth, "fetch_identity", lambda code: GithubIdentity(login="taken", github_id=2))
    state = _start_oauth(client)
    resp = client.get(f"/api/auth/github/callback?code=abc&state={state}", follow_redirects=False)
    assert resp.headers["location"] == "/login?error=no_access"


def test_oauth_github_failure_handled(client, monkeypatch):
    def boom(code):
        raise github_oauth.GithubOAuthError("nope")

    monkeypatch.setattr(github_oauth, "fetch_identity", boom)
    state = _start_oauth(client)
    resp = client.get(f"/api/auth/github/callback?code=abc&state={state}", follow_redirects=False)
    assert resp.headers["location"] == "/login?error=github_failed"
