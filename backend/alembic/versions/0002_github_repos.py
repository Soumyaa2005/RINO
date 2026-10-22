"""github installations, repos, repo test configs

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-22
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def _enum(name: str, *values: str) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, create_constraint=True, length=30)


def upgrade() -> None:
    op.create_table(
        "github_installations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("org_id", sa.Uuid(), sa.ForeignKey("orgs.id"), nullable=False),
        sa.Column("installation_id", sa.BigInteger(), nullable=False, unique=True),
        sa.Column("account_login", sa.String(100), nullable=False),
        sa.Column("account_type", sa.String(30), nullable=False),
        sa.Column("suspended", sa.Boolean(), nullable=False),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_github_installations_org_id", "github_installations", ["org_id"])

    op.create_table(
        "repos",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("org_id", sa.Uuid(), sa.ForeignKey("orgs.id"), nullable=False),
        sa.Column("installation_pk", sa.Uuid(), sa.ForeignKey("github_installations.id"), nullable=False),
        sa.Column("github_repo_id", sa.BigInteger(), nullable=False, unique=True),
        sa.Column("full_name", sa.String(200), nullable=False),
        sa.Column("default_branch", sa.String(255), nullable=False),
        sa.Column("private", sa.Boolean(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_repos_org_id", "repos", ["org_id"])
    op.create_index("ix_repos_installation_pk", "repos", ["installation_pk"])

    op.create_table(
        "repo_test_configs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("repo_id", sa.Uuid(), sa.ForeignKey("repos.id"), nullable=False, unique=True),
        sa.Column("runner", _enum("runner_type", "sandbox", "github_actions", "dev_instance"), nullable=False),
        sa.Column("workflow_file", sa.String(255), nullable=True),
        sa.Column("setup_command", sa.String(500), nullable=True),
        sa.Column("test_command", sa.String(300), nullable=True),
        sa.Column("python_version", sa.String(10), nullable=False),
        sa.Column("shared_instance", sa.Boolean(), nullable=False),
        sa.Column("status", _enum("config_status", "ready", "needs_attention"), nullable=False),
        sa.Column("problems", sa.JSON(), nullable=False),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_by_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("repo_test_configs")
    op.drop_index("ix_repos_installation_pk", table_name="repos")
    op.drop_index("ix_repos_org_id", table_name="repos")
    op.drop_table("repos")
    op.drop_index("ix_github_installations_org_id", table_name="github_installations")
    op.drop_table("github_installations")
