"""Provider-neutral interface for git hosting (GitHub now; Bitbucket, Azure DevOps later).

Nothing outside app/git_providers should talk to a git host directly. The
`connection_id` is the provider's id for an installed connection (for GitHub,
the App installation id).
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


class GitProviderError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class InvalidWebhookSignature(Exception):
    pass


@dataclass
class ConnectionInfo:
    connection_id: int
    account_login: str
    account_type: str
    suspended: bool


@dataclass
class RepoInfo:
    provider_repo_id: int
    full_name: str
    default_branch: str
    private: bool


@dataclass
class WebhookEvent:
    """A webhook reduced to what Rino acts on."""

    kind: str  # e.g. "installation", "installation_repositories", "ignored"
    action: str | None
    connection_id: int | None
    repos_added: list[RepoInfo] = field(default_factory=list)
    repos_removed: list[int] = field(default_factory=list)  # provider repo ids


class GitProvider(ABC):
    # ---- connections and repos (step 2) ----
    @abstractmethod
    def install_url(self, state: str) -> str: ...

    @abstractmethod
    def get_connection(self, connection_id: int) -> ConnectionInfo: ...

    @abstractmethod
    def list_repos(self, connection_id: int) -> list[RepoInfo]: ...

    @abstractmethod
    def get_repo(self, connection_id: int, full_name: str) -> RepoInfo: ...

    @abstractmethod
    def list_branches(self, connection_id: int, full_name: str) -> list[str]: ...

    @abstractmethod
    def get_file(self, connection_id: int, full_name: str, path: str, ref: str) -> str | None:
        """File text, or None if it doesn't exist."""

    @abstractmethod
    def list_dir(self, connection_id: int, full_name: str, path: str, ref: str) -> list[str] | None:
        """Entry names in a folder ("" = repo root), or None if it doesn't exist."""

    @abstractmethod
    def parse_webhook(self, headers: dict[str, str], body: bytes) -> WebhookEvent:
        """Verify the signature (raise InvalidWebhookSignature) and parse the event."""

    # ---- used from later steps; filled in as each step lands ----
    def clone_url(self, connection_id: int, full_name: str) -> str:
        raise NotImplementedError("Build step 3")

    def push_branch(self, *args, **kwargs):
        raise NotImplementedError("Build step 7")

    def create_issue(self, *args, **kwargs):
        raise NotImplementedError("Build step 5")

    def find_issue_by_fingerprint(self, *args, **kwargs):
        raise NotImplementedError("Build step 5")

    def comment_on_issue(self, *args, **kwargs):
        raise NotImplementedError("Build step 6")

    def create_draft_pr(self, *args, **kwargs):
        raise NotImplementedError("Build step 7")

    def trigger_workflow(self, *args, **kwargs):
        raise NotImplementedError("Build step 8")

    def get_workflow_results(self, *args, **kwargs):
        raise NotImplementedError("Build step 8")
