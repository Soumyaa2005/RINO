"""GitHub OAuth (user login) calls. Kept apart so tests can replace them."""

from urllib.parse import urlencode

import httpx

from app.config import get_settings
from app.services import GithubIdentity

AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
TOKEN_URL = "https://github.com/login/oauth/access_token"
USER_URL = "https://api.github.com/user"


class GithubOAuthError(Exception):
    pass


def authorize_url(state: str) -> str:
    settings = get_settings()
    query = urlencode(
        {
            "client_id": settings.github_client_id,
            "redirect_uri": settings.oauth_callback_url,
            "state": state,
            "allow_signup": "false",
        }
    )
    return f"{AUTHORIZE_URL}?{query}"


def fetch_identity(code: str) -> GithubIdentity:
    """Exchange the OAuth code for a token, read the user, and drop the token.

    Rino only needs to know who the person is at login, so the user token is
    never stored.
    """
    settings = get_settings()
    with httpx.Client(timeout=10) as client:
        token_resp = client.post(
            TOKEN_URL,
            headers={"Accept": "application/json"},
            data={
                "client_id": settings.github_client_id,
                "client_secret": settings.github_client_secret,
                "code": code,
                "redirect_uri": settings.oauth_callback_url,
            },
        )
        token = token_resp.json().get("access_token") if token_resp.status_code == 200 else None
        if not token:
            raise GithubOAuthError("GitHub did not return an access token")

        user_resp = client.get(
            USER_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        if user_resp.status_code != 200:
            raise GithubOAuthError("Could not read the GitHub user")
        data = user_resp.json()

    return GithubIdentity(
        login=data["login"],
        github_id=int(data["id"]),
        name=data.get("name"),
        avatar_url=data.get("avatar_url"),
    )
