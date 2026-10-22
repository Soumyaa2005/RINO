"""A small in-memory stand-in for the GitHub REST API, served through httpx.MockTransport.

It checks App JWTs against the test key and only lets an installation token
read repos that belong to that installation, like the real API.
"""

import base64
import json
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote

import httpx
import jwt


class FakeGitHub:
    def __init__(self, public_key_pem: str, app_id: str):
        self.public_key = public_key_pem
        self.app_id = app_id
        self.installations: dict[int, dict] = {}
        self.files: dict[tuple[str, str], str] = {}
        self.branches: dict[str, list[str]] = {}
        self.tokens: dict[str, int] = {}
        self.token_requests = 0
        self._next_repo_id = 1000

    # ---- setup helpers ----
    def add_installation(self, inst_id: int, login: str = "acme", kind: str = "Organization") -> None:
        self.installations[inst_id] = {"account": {"login": login, "type": kind}, "suspended_at": None, "repos": []}

    def add_repo(self, inst_id: int, full_name: str, default_branch: str = "main", private: bool = True, branches=None) -> dict:
        self._next_repo_id += 1
        repo = {"id": self._next_repo_id, "full_name": full_name, "default_branch": default_branch, "private": private}
        self.installations[inst_id]["repos"].append(repo)
        self.branches[full_name] = branches or [default_branch]
        return repo

    def remove_repo(self, inst_id: int, full_name: str) -> dict:
        repos = self.installations[inst_id]["repos"]
        repo = next(r for r in repos if r["full_name"] == full_name)
        repos.remove(repo)
        return repo

    def set_file(self, full_name: str, path: str, text: str) -> None:
        self.files[(full_name, path)] = text

    # ---- transport ----
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def _json(self, data, status: int = 200) -> httpx.Response:
        return httpx.Response(status, content=json.dumps(data).encode(), headers={"content-type": "application/json"})

    def _not_found(self) -> httpx.Response:
        return self._json({"message": "Not Found"}, 404)

    def _check_app_jwt(self, request: httpx.Request) -> bool:
        auth = request.headers.get("authorization", "")
        if not auth.startswith("Bearer "):
            return False
        try:
            claims = jwt.decode(auth[7:], self.public_key, algorithms=["RS256"])
        except jwt.PyJWTError:
            return False
        return claims.get("iss") == self.app_id

    def _installation_for_token(self, request: httpx.Request) -> int | None:
        auth = request.headers.get("authorization", "")
        return self.tokens.get(auth[7:]) if auth.startswith("Bearer ") else None

    def _page(self, items: list, request: httpx.Request) -> list:
        per_page = int(request.url.params.get("per_page", 30))
        page = int(request.url.params.get("page", 1))
        return items[(page - 1) * per_page : page * per_page]

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = unquote(request.url.path)
        parts = [p for p in path.split("/") if p]

        # App-level endpoints (JWT auth)
        if parts[:2] == ["app", "installations"]:
            if not self._check_app_jwt(request):
                return self._json({"message": "Bad credentials"}, 401)
            inst_id = int(parts[2])
            inst = self.installations.get(inst_id)
            if inst is None:
                return self._not_found()
            if len(parts) == 4 and parts[3] == "access_tokens" and request.method == "POST":
                self.token_requests += 1
                token = f"ghs_fake_{inst_id}_{self.token_requests}"
                self.tokens[token] = inst_id
                expires = (datetime.now(timezone.utc) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
                return self._json({"token": token, "expires_at": expires}, 201)
            if len(parts) == 3 and request.method == "GET":
                return self._json({"id": inst_id, "account": inst["account"], "suspended_at": inst["suspended_at"]})
            return self._not_found()

        # Installation-token endpoints
        inst_id = self._installation_for_token(request)
        if inst_id is None or inst_id not in self.installations:
            return self._json({"message": "Bad credentials"}, 401)
        inst = self.installations[inst_id]

        if parts == ["installation", "repositories"]:
            repos = inst["repos"]
            return self._json({"total_count": len(repos), "repositories": self._page(repos, request)})

        if parts[0] == "repos" and len(parts) >= 3:
            full_name = f"{parts[1]}/{parts[2]}"
            repo = next((r for r in inst["repos"] if r["full_name"] == full_name), None)
            if repo is None:
                return self._not_found()
            rest = parts[3:]
            if not rest:
                return self._json(repo)
            if rest == ["branches"]:
                return self._json(self._page([{"name": b} for b in self.branches.get(full_name, [])], request))
            if rest[0] == "contents":
                target = "/".join(rest[1:])
                if (full_name, target) in self.files:
                    text = self.files[(full_name, target)]
                    return self._json(
                        {"type": "file", "name": target.split("/")[-1], "encoding": "base64", "content": base64.b64encode(text.encode()).decode()}
                    )
                prefix = f"{target}/" if target else ""
                children = sorted({p[len(prefix):].split("/")[0] for (fn, p) in self.files if fn == full_name and p.startswith(prefix)})
                if children:
                    return self._json([{"name": c, "type": "dir"} for c in children])
                return self._not_found()
        return self._not_found()
