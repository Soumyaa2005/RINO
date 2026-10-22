"""Validate and check a repo's test environment ("Where do your tests run?").

Validation (on save) catches malformed input. The connection check reads the
repo through the GitHub App and reports problems (block runs) and warnings
(worth fixing). Nothing is executed here; running tests starts in step 3.
"""

import re
import shlex

import yaml
from pydantic import BaseModel, field_validator, model_validator

from app.git_providers.base import GitProvider, GitProviderError
from app.models import RunnerType

PYTHON_VERSIONS = ["3.9", "3.10", "3.11", "3.12", "3.13"]
WORKFLOW_RE = re.compile(r"^\.github/workflows/[A-Za-z0-9._-]+\.ya?ml$")
JUNIT_ARTIFACT = "rino-junit"
TEST_ROOT_MARKERS = {"tests", "test", "pytest.ini", "conftest.py", "pyproject.toml", "setup.cfg", "tox.ini"}
# The test command must be one pytest invocation; Rino appends --junitxml itself.
TEST_COMMAND_FORBIDDEN = re.compile(r"[;&|`<>$\\\n\r]")


class TestConfigIn(BaseModel):
    __test__ = False  # tells pytest this is not a test class
    runner: RunnerType
    workflow_file: str | None = None
    setup_command: str | None = None
    test_command: str | None = None
    python_version: str = "3.11"
    shared_instance: bool = False

    @field_validator("workflow_file", "setup_command", "test_command", mode="before")
    @classmethod
    def _strip(cls, v):
        if isinstance(v, str):
            v = v.strip()
            return v or None
        return v

    @model_validator(mode="after")
    def _check(self) -> "TestConfigIn":
        if self.python_version not in PYTHON_VERSIONS:
            raise ValueError(f"Python version must be one of {', '.join(PYTHON_VERSIONS)}")

        if self.runner == RunnerType.sandbox:
            if not self.test_command:
                raise ValueError("Test command is required")
            if TEST_COMMAND_FORBIDDEN.search(self.test_command):
                raise ValueError("Test command must be a single pytest command (no ; & | ` < > $ or line breaks)")
            try:
                parts = shlex.split(self.test_command)
            except ValueError as exc:
                raise ValueError("Test command has unbalanced quotes") from exc
            if not (parts[:1] == ["pytest"] or parts[:3] in (["python", "-m", "pytest"], ["python3", "-m", "pytest"])):
                raise ValueError("Test command must start with 'pytest' or 'python -m pytest'")
            if any(p.startswith("--junitxml") or p.startswith("--junit-xml") for p in parts):
                raise ValueError("Leave out --junitxml; Rino adds it")
            if self.setup_command and ("\n" in self.setup_command or "\r" in self.setup_command):
                raise ValueError("Setup command must be on one line")
            if self.setup_command and len(self.setup_command) > 500:
                raise ValueError("Setup command is too long (500 characters max)")
            if len(self.test_command) > 300:
                raise ValueError("Test command is too long (300 characters max)")
            self.workflow_file = None
            self.shared_instance = False
        else:
            if not self.workflow_file:
                raise ValueError("Choose the workflow file that runs your tests")
            if not WORKFLOW_RE.fullmatch(self.workflow_file):
                raise ValueError("Workflow file must look like .github/workflows/test.yml")
            self.setup_command = None
            self.test_command = None
            if self.runner == RunnerType.github_actions:
                self.shared_instance = False
        return self


def _workflow_triggers(doc: dict) -> set[str]:
    # YAML 1.1 reads a bare `on:` key as boolean True.
    on = doc.get("on", doc.get(True))
    if isinstance(on, str):
        return {on}
    if isinstance(on, list):
        return {str(x) for x in on}
    if isinstance(on, dict):
        return {str(k) for k in on}
    return set()


def _runs_on_self_hosted(doc: dict) -> bool:
    for job in (doc.get("jobs") or {}).values():
        if not isinstance(job, dict):
            continue
        runs_on = job.get("runs-on")
        labels = [runs_on] if isinstance(runs_on, str) else runs_on if isinstance(runs_on, list) else []
        if isinstance(runs_on, dict):
            labels = runs_on.get("labels") or []
            labels = [labels] if isinstance(labels, str) else labels
        if any(str(label) == "self-hosted" for label in labels):
            return True
    return False


def check_test_env(
    provider: GitProvider, connection_id: int, full_name: str, cfg: TestConfigIn
) -> tuple[list[str], list[str], str | None]:
    """Returns (problems, warnings, default_branch). Problems mean 'Needs attention'."""
    problems: list[str] = []
    warnings: list[str] = []

    try:
        info = provider.get_repo(connection_id, full_name)
    except GitProviderError as exc:
        return [f"Rino can't read this repository through the GitHub App. {exc}"], [], None
    ref = info.default_branch

    try:
        if cfg.runner == RunnerType.sandbox:
            root = set(provider.list_dir(connection_id, full_name, "", ref) or [])
            if cfg.setup_command and "requirements.txt" in cfg.setup_command and "requirements.txt" not in root:
                problems.append(f"The setup command uses requirements.txt, but there's no requirements.txt at the root of {ref}.")
            if not cfg.setup_command:
                warnings.append("No setup command: dependencies won't be installed before tests run.")
            if not root & TEST_ROOT_MARKERS:
                warnings.append(f"No tests/ folder or pytest config found at the root of {ref}; pytest may find no tests.")
        else:
            text = provider.get_file(connection_id, full_name, cfg.workflow_file or "", ref)
            if text is None:
                problems.append(f"{cfg.workflow_file} doesn't exist on {ref}.")
            else:
                try:
                    doc = yaml.safe_load(text)
                except yaml.YAMLError:
                    doc = None
                if not isinstance(doc, dict):
                    problems.append(f"{cfg.workflow_file} isn't valid workflow YAML.")
                else:
                    if "workflow_dispatch" not in _workflow_triggers(doc):
                        problems.append("Add `workflow_dispatch:` under `on:` in the workflow so Rino can start it.")
                    if cfg.runner == RunnerType.dev_instance and not _runs_on_self_hosted(doc):
                        problems.append("No job uses `runs-on: self-hosted`, so the tests won't run on your dev instance.")
                    if JUNIT_ARTIFACT not in text:
                        warnings.append(
                            f"Upload pytest's JUnit XML as an artifact named `{JUNIT_ARTIFACT}` so Rino can read the results (see README)."
                        )
            if cfg.runner == RunnerType.dev_instance and not cfg.shared_instance:
                warnings.append("If developers also use this dev instance, tick 'shared' so Rino runs one job at a time.")
    except GitProviderError as exc:
        problems.append(f"Couldn't read the repository contents. {exc}")

    return problems, warnings, ref
