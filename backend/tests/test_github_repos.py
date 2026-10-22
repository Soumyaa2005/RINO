import hashlib
import hmac
import json
from urllib.parse import parse_qs, urlparse

import pytest

from app.models import AuditLog, GithubInstallation, Repo, Role
from tests.conftest import CSRF, WEBHOOK_SECRET, login_as, make_user

INST = 777


# ---------------------------------------------------------------- helpers


def install(client, fake, inst_id: int = INST) -> None:
    """Run the full install flow: Rino -> GitHub -> setup URL."""
    start = client.get("/api/admin/github/install", follow_redirects=False)
    assert start.status_code == 303
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    done = client.get(f"/api/github/setup?installation_id={inst_id}&setup_action=install&state={state}", follow_redirects=False)
    assert done.headers["location"] == "/repositories?installed=1", done.headers["location"]


@pytest.fixture
def admin_with_repos(client, db, fake_github):
    make_user(db, "boss", Role.admin)
    make_user(db, "dev1", Role.developer)
    fake_github.add_installation(INST, "acme")
    fake_github.add_repo(INST, "acme/api", branches=["main", "feature/x", "dev"])
    fake_github.add_repo(INST, "acme/web", default_branch="trunk")
    login_as(client, "boss")
    install(client, fake_github)
    return fake_github


def repo_id(client, name: str) -> str:
    return next(r["id"] for r in client.get("/api/admin/repos").json() if r["full_name"] == name)


def webhook(client, event: str, payload: dict, secret: str = WEBHOOK_SECRET):
    body = json.dumps(payload).encode()
    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return client.post(
        "/api/webhooks/github",
        content=body,
        headers={"X-GitHub-Event": event, "X-Hub-Signature-256": sig, "Content-Type": "application/json"},
    )


# ---------------------------------------------------------------- install flow


def test_install_start_redirects_to_github_with_state(client, db, fake_github):
    make_user(db, "boss", Role.admin)
    login_as(client, "boss")
    resp = client.get("/api/admin/github/install", follow_redirects=False)
    url = urlparse(resp.headers["location"])
    assert url.netloc == "github.com" and url.path == "/apps/rino-test/installations/new"
    assert parse_qs(url.query)["state"][0]


def test_developer_cannot_start_install(client, db, fake_github):
    make_user(db, "boss", Role.admin)
    make_user(db, "dev1")
    login_as(client, "dev1")
    assert client.get("/api/admin/github/install", follow_redirects=False).status_code == 403


def test_install_saves_installation_and_syncs_all_repos_across_pages(client, db, fake_github):
    make_user(db, "boss", Role.admin)
    fake_github.add_installation(INST, "acme")
    for i in range(105):  # more than one page of 100
        fake_github.add_repo(INST, f"acme/repo-{i:03d}")
    login_as(client, "boss")
    install(client, fake_github)

    status = client.get("/api/admin/github/status").json()
    assert status["installations"][0]["account_login"] == "acme"
    assert status["installations"][0]["repo_count"] == 105
    assert len(client.get("/api/admin/repos").json()) == 105
    assert db.query(AuditLog).filter_by(action="github.installed").count() == 1


def test_install_without_matching_state_is_refused(client, db, fake_github):
    make_user(db, "boss", Role.admin)
    fake_github.add_installation(INST)
    login_as(client, "boss")
    client.get("/api/admin/github/install", follow_redirects=False)
    resp = client.get(f"/api/github/setup?installation_id={INST}&setup_action=install&state=forged", follow_redirects=False)
    assert resp.headers["location"] == "/repositories?error=invalid_state"
    assert db.query(GithubInstallation).count() == 0


def test_update_of_known_installation_needs_no_state(client, admin_with_repos):
    admin_with_repos.add_repo(INST, "acme/new-one")
    resp = client.get(f"/api/github/setup?installation_id={INST}&setup_action=update", follow_redirects=False)
    assert resp.headers["location"] == "/repositories?installed=1"
    assert any(r["full_name"] == "acme/new-one" for r in client.get("/api/admin/repos").json())


def test_install_of_unknown_installation_id_fails(client, db, fake_github):
    make_user(db, "boss", Role.admin)
    login_as(client, "boss")
    start = client.get("/api/admin/github/install", follow_redirects=False)
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    resp = client.get(f"/api/github/setup?installation_id=999&state={state}", follow_redirects=False)
    assert resp.headers["location"] == "/repositories?error=install_failed"


def test_setup_url_rejects_developers_and_signed_out(client, db, fake_github):
    make_user(db, "boss", Role.admin)
    make_user(db, "dev1")
    resp = client.get(f"/api/github/setup?installation_id={INST}", follow_redirects=False)
    assert resp.headers["location"] == "/login"
    login_as(client, "dev1")
    resp = client.get(f"/api/github/setup?installation_id={INST}", follow_redirects=False)
    assert resp.headers["location"] == "/repositories?error=forbidden"


def test_install_request_by_non_owner(client, db, fake_github):
    make_user(db, "boss", Role.admin)
    login_as(client, "boss")
    resp = client.get("/api/github/setup?setup_action=request", follow_redirects=False)
    assert resp.headers["location"] == "/repositories?error=install_requested"


def test_installation_tokens_are_cached(client, admin_with_repos):
    before = admin_with_repos.token_requests
    rid = repo_id(client, "acme/api")
    for _ in range(3):
        client.get(f"/api/repos/{rid}/branches")
    assert admin_with_repos.token_requests == before


# ---------------------------------------------------------------- webhooks


def test_webhook_rejects_bad_signature(client, admin_with_repos):
    resp = webhook(client, "installation", {"action": "deleted", "installation": {"id": INST}}, secret="wrong-secret-xxxxxxxxxx")
    assert resp.status_code == 401


def test_webhook_needs_no_csrf_header_but_other_posts_do(client, admin_with_repos):
    assert webhook(client, "ping", {"zen": "hi"}).status_code == 200
    rid = repo_id(client, "acme/api")
    assert client.post(f"/api/admin/repos/{rid}/test-config/check").status_code == 403  # no CSRF header


def test_webhook_repo_removed_and_added(client, admin_with_repos):
    gone = admin_with_repos.remove_repo(INST, "acme/web")
    resp = webhook(client, "installation_repositories", {"action": "removed", "installation": {"id": INST}, "repositories_removed": [gone]})
    assert resp.json() == {"handled": True}
    names = {r["full_name"] for r in client.get("/api/repos").json()}
    assert names == {"acme/api"}

    admin_with_repos.add_repo(INST, "acme/web")  # re-added (new id in the fake)
    admin_with_repos.add_repo(INST, "acme/docs")
    webhook(client, "installation_repositories", {"action": "added", "installation": {"id": INST}, "repositories_added": []})
    names = {r["full_name"] for r in client.get("/api/repos").json()}
    assert names == {"acme/api", "acme/web", "acme/docs"}


def test_webhook_installation_deleted_hides_everything(client, admin_with_repos):
    webhook(client, "installation", {"action": "deleted", "installation": {"id": INST}})
    assert client.get("/api/repos").json() == []
    assert client.get("/api/admin/github/status").json()["installations"][0]["removed"] is True


def test_webhook_suspend_and_unsuspend(client, admin_with_repos):
    webhook(client, "installation", {"action": "suspend", "installation": {"id": INST}})
    assert client.get("/api/repos").json() == []
    webhook(client, "installation", {"action": "unsuspend", "installation": {"id": INST}})
    assert len(client.get("/api/repos").json()) == 2


def test_webhook_for_unlinked_installation_is_ignored(client, admin_with_repos, db):
    resp = webhook(client, "installation", {"action": "deleted", "installation": {"id": 4242}})
    assert resp.json() == {"handled": False}


# ---------------------------------------------------------------- repo picker and roles


def test_developer_sees_enabled_repos_and_branches(client, admin_with_repos):
    rid = repo_id(client, "acme/web")
    client.patch(f"/api/admin/repos/{rid}", json={"enabled": False}, headers=CSRF)

    login_as(client, "dev1")
    repos = client.get("/api/repos").json()
    assert [r["full_name"] for r in repos] == ["acme/api"]
    api_id = repos[0]["id"]
    assert client.get(f"/api/repos/{api_id}/branches").json() == ["main", "dev", "feature/x"]
    assert client.get(f"/api/repos/{rid}/branches").status_code == 404  # disabled


def test_developer_cannot_use_admin_repo_endpoints(client, admin_with_repos):
    rid = repo_id(client, "acme/api")
    login_as(client, "dev1")
    assert client.get("/api/admin/repos").status_code == 403
    assert client.get("/api/admin/github/status").status_code == 403
    assert client.patch(f"/api/admin/repos/{rid}", json={"enabled": False}, headers=CSRF).status_code == 403
    body = {"runner": "sandbox", "test_command": "pytest"}
    assert client.put(f"/api/admin/repos/{rid}/test-config", json=body, headers=CSRF).status_code == 403


def test_manual_sync_marks_removed_repos(client, admin_with_repos):
    admin_with_repos.remove_repo(INST, "acme/web")
    inst_id = client.get("/api/admin/github/status").json()["installations"][0]["id"]
    result = client.post(f"/api/admin/github/installations/{inst_id}/sync", headers=CSRF).json()
    assert result["removed"] == 1
    removed = [r for r in client.get("/api/admin/repos").json() if r["removed"]]
    assert [r["full_name"] for r in removed] == ["acme/web"]


# ---------------------------------------------------------------- test environment: validation


@pytest.mark.parametrize(
    "body",
    [
        {"runner": "sandbox"},
        {"runner": "sandbox", "test_command": "pytest; rm -rf /"},
        {"runner": "sandbox", "test_command": "pytest && echo hi"},
        {"runner": "sandbox", "test_command": "make test"},
        {"runner": "sandbox", "test_command": "pytest --junitxml=out.xml"},
        {"runner": "sandbox", "test_command": "pytest $(whoami)"},
        {"runner": "sandbox", "test_command": "pytest", "python_version": "2.7"},
        {"runner": "sandbox", "test_command": "pytest", "setup_command": "pip install x\nrm -rf /"},
        {"runner": "github_actions"},
        {"runner": "github_actions", "workflow_file": "../../etc/passwd"},
        {"runner": "dev_instance", "workflow_file": ".github/workflows/../x.yml"},
    ],
)
def test_invalid_test_config_rejected(client, admin_with_repos, body):
    rid = repo_id(client, "acme/api")
    assert client.put(f"/api/admin/repos/{rid}/test-config", json=body, headers=CSRF).status_code == 422


# ---------------------------------------------------------------- test environment: checks


def save(client, name, body):
    rid = repo_id(client, name)
    resp = client.put(f"/api/admin/repos/{rid}/test-config", json=body, headers=CSRF)
    assert resp.status_code == 200, resp.text
    return resp.json()["test_config"]


def test_sandbox_ready_when_requirements_and_tests_exist(client, admin_with_repos):
    admin_with_repos.set_file("acme/api", "requirements.txt", "flask\n")
    admin_with_repos.set_file("acme/api", "tests/test_app.py", "def test_x(): pass\n")
    cfg = save(client, "acme/api", {"runner": "sandbox", "setup_command": "pip install -r requirements.txt", "test_command": "python -m pytest -q"})
    assert cfg["status"] == "ready" and cfg["problems"] == [] and cfg["warnings"] == []


def test_sandbox_missing_requirements_needs_attention(client, admin_with_repos):
    admin_with_repos.set_file("acme/api", "tests/test_app.py", "")
    cfg = save(client, "acme/api", {"runner": "sandbox", "setup_command": "pip install -r requirements.txt", "test_command": "pytest"})
    assert cfg["status"] == "needs_attention"
    assert "requirements.txt" in cfg["problems"][0]


def test_sandbox_warns_when_no_tests_found(client, admin_with_repos):
    admin_with_repos.set_file("acme/api", "requirements.txt", "")
    cfg = save(client, "acme/api", {"runner": "sandbox", "setup_command": "pip install -r requirements.txt", "test_command": "pytest"})
    assert cfg["status"] == "ready"
    assert any("tests" in w for w in cfg["warnings"])


GOOD_WORKFLOW = """
name: tests
on:
  push:
  workflow_dispatch:
jobs:
  test:
    runs-on: {runs_on}
    steps:
      - run: pytest --junitxml=junit.xml
      - uses: actions/upload-artifact@v4
        with:
          name: rino-junit
          path: junit.xml
"""


def test_actions_workflow_without_dispatch_needs_attention(client, admin_with_repos):
    admin_with_repos.set_file("acme/api", ".github/workflows/test.yml", "on: [push]\njobs:\n  t:\n    runs-on: ubuntu-latest\n")
    cfg = save(client, "acme/api", {"runner": "github_actions", "workflow_file": ".github/workflows/test.yml"})
    assert cfg["status"] == "needs_attention"
    assert "workflow_dispatch" in cfg["problems"][0]
    assert any("rino-junit" in w for w in cfg["warnings"])


@pytest.mark.parametrize("on", ["workflow_dispatch", "[push, workflow_dispatch]"])
def test_actions_dispatch_trigger_short_forms(client, admin_with_repos, on):
    admin_with_repos.set_file("acme/api", ".github/workflows/t.yaml", f"on: {on}\njobs:\n  t:\n    runs-on: ubuntu-latest\n")
    cfg = save(client, "acme/api", {"runner": "github_actions", "workflow_file": ".github/workflows/t.yaml"})
    assert cfg["problems"] == []


def test_actions_ready(client, admin_with_repos):
    admin_with_repos.set_file("acme/api", ".github/workflows/test.yml", GOOD_WORKFLOW.format(runs_on="ubuntu-latest"))
    cfg = save(client, "acme/api", {"runner": "github_actions", "workflow_file": ".github/workflows/test.yml"})
    assert cfg["status"] == "ready" and cfg["warnings"] == []


def test_missing_workflow_file(client, admin_with_repos):
    cfg = save(client, "acme/api", {"runner": "github_actions", "workflow_file": ".github/workflows/nope.yml"})
    assert cfg["status"] == "needs_attention" and "doesn't exist" in cfg["problems"][0]


def test_dev_instance_requires_self_hosted_runner(client, admin_with_repos):
    admin_with_repos.set_file("acme/api", ".github/workflows/test.yml", GOOD_WORKFLOW.format(runs_on="ubuntu-latest"))
    cfg = save(client, "acme/api", {"runner": "dev_instance", "workflow_file": ".github/workflows/test.yml", "shared_instance": True})
    assert cfg["status"] == "needs_attention" and "self-hosted" in cfg["problems"][0]

    admin_with_repos.set_file("acme/api", ".github/workflows/test.yml", GOOD_WORKFLOW.format(runs_on="[self-hosted, linux]"))
    cfg = save(client, "acme/api", {"runner": "dev_instance", "workflow_file": ".github/workflows/test.yml", "shared_instance": True})
    assert cfg["status"] == "ready" and cfg["warnings"] == []


def test_dev_instance_warns_if_not_marked_shared(client, admin_with_repos):
    admin_with_repos.set_file("acme/api", ".github/workflows/test.yml", GOOD_WORKFLOW.format(runs_on="self-hosted"))
    cfg = save(client, "acme/api", {"runner": "dev_instance", "workflow_file": ".github/workflows/test.yml"})
    assert cfg["status"] == "ready" and any("shared" in w for w in cfg["warnings"])


def test_recheck_picks_up_fixed_repo(client, admin_with_repos):
    cfg = save(client, "acme/api", {"runner": "github_actions", "workflow_file": ".github/workflows/test.yml"})
    assert cfg["status"] == "needs_attention"
    admin_with_repos.set_file("acme/api", ".github/workflows/test.yml", GOOD_WORKFLOW.format(runs_on="ubuntu-latest"))
    rid = repo_id(client, "acme/api")
    cfg = client.post(f"/api/admin/repos/{rid}/test-config/check", headers=CSRF).json()["test_config"]
    assert cfg["status"] == "ready"


def test_list_workflow_files(client, admin_with_repos):
    admin_with_repos.set_file("acme/api", ".github/workflows/test.yml", "")
    admin_with_repos.set_file("acme/api", ".github/workflows/lint.yaml", "")
    admin_with_repos.set_file("acme/api", ".github/workflows/README.md", "")
    rid = repo_id(client, "acme/api")
    paths = [w["path"] for w in client.get(f"/api/admin/repos/{rid}/workflows").json()]
    assert paths == [".github/workflows/lint.yaml", ".github/workflows/test.yml"]


def test_repo_lookup_is_scoped_to_installation(client, admin_with_repos, db):
    # A repo the fake GitHub doesn't share with this installation can't be read.
    repo = db.query(Repo).filter_by(full_name="acme/web").one()
    admin_with_repos.remove_repo(INST, "acme/web")
    cfg = save(client, "acme/web", {"runner": "sandbox", "test_command": "pytest"})
    assert cfg["status"] == "needs_attention" and "can't read" in cfg["problems"][0]
    assert repo.full_name == "acme/web"
