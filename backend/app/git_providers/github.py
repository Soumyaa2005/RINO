"""GitHub App implementation of GitProvider.

Auth: a short-lived JWT signed with the App's private key is exchanged for an
installation token (valid 1 hour), which is cached in memory and refreshed
5 minutes before it expires. Tokens are never logged or stored.
"""

import base64
import hashlib
import hmac
import json
import threading
import time
from datetime import datetime
from urllib.parse import quote

import httpx
import jwt

from app.config import Settings
from app.git_providers.base import (
    ConnectionInfo,
    GitProvider,
    GitProviderError,
    InvalidWebhookSignature,
    RepoInfo,
    WebhookEvent,
)

API_VERSION = "2022-11-28"
PER_PAGE = 100
MAX_PAGES = 50  # safety cap: 5,000 repos / branches


def _repo_info(data: dict) -> RepoInfo:
    return RepoInfo(
        provider_repo_id=int(data["id"]),
        full_name=data["full_name"],
        default_branch=data.get("default_branch") or "main",
        private=bool(data.get("private", True)),
    )


def _path(full_name: str, path: str = "") -> str:
    owner, _, name = full_name.partition("/")
    base = f"/repos/{quote(owner, safe='')}/{quote(name, safe='')}"
    return f"{base}/{path}" if path else base


class GitHubProvider(GitProvider):
    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None):
        self.settings = settings
        self._client = httpx.Client(
            base_url=settings.github_api_url,
            timeout=15,
            transport=transport,
            headers={"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": API_VERSION},
        )
        self._tokens: dict[int, tuple[str, float]] = {}
        self._lock = threading.Lock()

    # ---------- auth ----------

    def _app_jwt(self) -> str:
        if not self.settings.github_app_configured:
            raise GitProviderError("The GitHub App isn't configured on this server")
        now = int(time.time())
        payload = {"iat": now - 60, "exp": now + 540, "iss": str(self.settings.github_app_id)}
        return jwt.encode(payload, self.settings.load_github_app_private_key(), algorithm="RS256")

    def _installation_token(self, installation_id: int) -> str:
        with self._lock:
            cached = self._tokens.get(installation_id)
            if cached and cached[1] - time.time() > 300:
                return cached[0]
        resp = self._client.post(
            f"/app/installations/{installation_id}/access_tokens",
            headers={"Authorization": f"Bearer {self._app_jwt()}"},
        )
        self._raise_for(resp, "get an access token for this installation")
        data = resp.json()
        expires = datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00")).timestamp()
        with self._lock:
            self._tokens[installation_id] = (data["token"], expires)
        return data["token"]

    def forget_installation(self, installation_id: int) -> None:
        with self._lock:
            self._tokens.pop(installation_id, None)

    # ---------- http helpers ----------

    @staticmethod
    def _raise_for(resp: httpx.Response, doing: str) -> None:
        if resp.is_success:
            return
        try:
            detail = resp.json().get("message", "")
        except ValueError:
            detail = ""
        raise GitProviderError(f"GitHub refused to {doing} ({resp.status_code}{': ' + detail if detail else ''})", resp.status_code)

    def _get(self, installation_id: int, path: str, doing: str, params: dict | None = None, allow_404: bool = False):
        resp = self._client.get(
            path, params=params, headers={"Authorization": f"Bearer {self._installation_token(installation_id)}"}
        )
        if allow_404 and resp.status_code == 404:
            return None
        self._raise_for(resp, doing)
        return resp.json()

    def _paged(self, installation_id: int, path: str, doing: str, key: str | None = None) -> list[dict]:
        items: list[dict] = []
        for page in range(1, MAX_PAGES + 1):
            data = self._get(installation_id, path, doing, params={"per_page": PER_PAGE, "page": page})
            batch = data[key] if key else data
            items.extend(batch)
            if len(batch) < PER_PAGE:
                break
        return items

    # ---------- GitProvider ----------

    def install_url(self, state: str) -> str:
        return f"https://github.com/apps/{quote(self.settings.github_app_slug)}/installations/new?state={quote(state)}"

    def get_connection(self, connection_id: int) -> ConnectionInfo:
        resp = self._client.get(
            f"/app/installations/{connection_id}", headers={"Authorization": f"Bearer {self._app_jwt()}"}
        )
        self._raise_for(resp, "read this installation")
        data = resp.json()
        account = data.get("account") or {}
        return ConnectionInfo(
            connection_id=int(data["id"]),
            account_login=account.get("login", "unknown"),
            account_type=account.get("type", "unknown"),
            suspended=data.get("suspended_at") is not None,
        )

    def list_repos(self, connection_id: int) -> list[RepoInfo]:
        raw = self._paged(connection_id, "/installation/repositories", "list repositories", key="repositories")
        return [_repo_info(r) for r in raw]

    def get_repo(self, connection_id: int, full_name: str) -> RepoInfo:
        return _repo_info(self._get(connection_id, _path(full_name), "read this repository"))

    def list_branches(self, connection_id: int, full_name: str) -> list[str]:
        raw = self._paged(connection_id, _path(full_name, "branches"), "list branches")
        return [b["name"] for b in raw]

    def get_file(self, connection_id: int, full_name: str, path: str, ref: str) -> str | None:
        data = self._get(
            connection_id,
            _path(full_name, f"contents/{quote(path)}"),
            f"read {path}",
            params={"ref": ref},
            allow_404=True,
        )
        if data is None or isinstance(data, list) or data.get("type") != "file":
            return None
        if data.get("encoding") == "base64":
            return base64.b64decode(data.get("content", "")).decode("utf-8", errors="replace")
        return data.get("content")

    def list_dir(self, connection_id: int, full_name: str, path: str, ref: str) -> list[str] | None:
        suffix = f"contents/{quote(path)}" if path else "contents"
        data = self._get(connection_id, _path(full_name, suffix), f"list {path or 'the repo root'}", params={"ref": ref}, allow_404=True)
        if data is None or not isinstance(data, list):
            return None
        return [entry["name"] for entry in data]

    def parse_webhook(self, headers: dict[str, str], body: bytes) -> WebhookEvent:
        secret = self.settings.github_webhook_secret
        if not secret:
            raise InvalidWebhookSignature("No webhook secret configured")
        given = headers.get("x-hub-signature-256", "")
        expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(given, expected):
            raise InvalidWebhookSignature("Signature mismatch")

        event = headers.get("x-github-event", "")
        try:
            payload = json.loads(body)
        except ValueError as exc:
            raise InvalidWebhookSignature("Body is not JSON") from exc
        installation_id = (payload.get("installation") or {}).get("id")
        action = payload.get("action")

        if event == "installation":
            return WebhookEvent("installation", action, installation_id)
        if event == "installation_repositories":
            added = [
                RepoInfo(int(r["id"]), r["full_name"], r.get("default_branch") or "", bool(r.get("private", True)))
                for r in payload.get("repositories_added", [])
            ]
            removed = [int(r["id"]) for r in payload.get("repositories_removed", [])]
            return WebhookEvent("installation_repositories", action, installation_id, added, removed)
        return WebhookEvent("ignored", action, installation_id)

    def clone_url(self, connection_id: int, full_name: str) -> str:
        token = self._installation_token(connection_id)
        return f"https://x-access-token:{token}@github.com/{full_name}.git"


_provider: GitHubProvider | None = None
_provider_lock = threading.Lock()


def get_git_provider() -> GitProvider:
    """FastAPI dependency. One shared provider per process (keeps the token cache)."""
    global _provider
    from app.config import get_settings

    with _provider_lock:
        if _provider is None:
            _provider = GitHubProvider(get_settings())
        return _provider
