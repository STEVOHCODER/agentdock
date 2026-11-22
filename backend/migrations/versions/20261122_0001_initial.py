"""Initial AgentDock catalogue and access-control schema.

This migration is intentionally explicit rather than calling
``Base.metadata.create_all``. A migration must describe the schema at the
revision where it was written, otherwise future model changes silently rewrite
history and fresh installs diverge from upgraded installs.
"""
import sqlalchemy as sa
from alembic import op


revision = "20261122_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("password_hash", sa.String(length=256), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("role", sa.String(length=32), nullable=False, server_default="free"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_role", "users", ["role"])

    op.create_table(
        "sessions",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])
    op.create_index("ix_sessions_expires_at", "sessions", ["expires_at"])

    op.create_table(
        "api_keys",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False, server_default="AgentDock key"),
        sa.Column("prefix", sa.String(length=16), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False, unique=True),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_api_keys_user_id", "api_keys", ["user_id"])
    op.create_index("ix_api_keys_prefix", "api_keys", ["prefix"])

    op.create_table(
        "repositories",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("url", sa.String(length=300), nullable=False, unique=True),
        sa.Column("owner", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("community", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("default_branch", sa.String(length=200), nullable=False, server_default="main"),
        sa.Column("stars", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("forks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("license_id", sa.String(length=80), nullable=False, server_default="unknown"),
        sa.Column("last_commit_sha", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("last_push_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="discovered"),
        sa.Column("priority", sa.String(length=16), nullable=False, server_default="standard"),
        sa.Column("sync_interval_hours", sa.Integer(), nullable=False, server_default="24"),
        sa.Column("discovered_via", sa.String(length=40), nullable=False, server_default="manual"),
        sa.Column("last_error", sa.Text(), nullable=False, server_default=""),
        sa.Column("rights_status", sa.String(length=24), nullable=False, server_default="unknown"),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_repositories_status", "repositories", ["status"])

    op.create_table(
        "skills",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("repository_id", sa.String(length=36), sa.ForeignKey("repositories.id", ondelete="SET NULL"), nullable=True),
        sa.Column("slug", sa.String(length=160), nullable=False, unique=True),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("instructions", sa.Text(), nullable=False, server_default=""),
        sa.Column("path", sa.String(length=300), nullable=False, server_default=""),
        sa.Column("category", sa.String(length=80), nullable=False, server_default="Other"),
        sa.Column("creator", sa.String(length=160), nullable=False, server_default="Community"),
        sa.Column("community", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("license_id", sa.String(length=80), nullable=False, server_default="unknown"),
        sa.Column("source_url", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("stars", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending_review"),
        sa.Column("is_premium", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_featured", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("commercial_ok", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("security_status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("latest_version", sa.String(length=80), nullable=False, server_default=""),
        sa.Column("technologies", sa.JSON(), nullable=False),
        sa.Column("compatibility", sa.JSON(), nullable=False),
        sa.Column("dependencies", sa.JSON(), nullable=False),
        sa.Column("permissions", sa.JSON(), nullable=False),
        sa.Column("changelog", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    for name, columns in (("ix_skills_repository_id", ["repository_id"]),
                          ("ix_skills_slug", ["slug"]),
                          ("ix_skills_name", ["name"]),
                          ("ix_skills_category", ["category"]),
                          ("ix_skills_community", ["community"]),
                          ("ix_skills_status", ["status"]),
                          ("ix_skills_is_premium", ["is_premium"]),
                          ("ix_skills_is_featured", ["is_featured"])):
        op.create_index(name, "skills", columns)

    op.create_table(
        "skill_versions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("skill_id", sa.String(length=36), sa.ForeignKey("skills.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.String(length=80), nullable=False),
        sa.Column("source_commit", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("manifest", sa.JSON(), nullable=False),
        sa.Column("snapshot_path", sa.String(length=800), nullable=False),
        sa.Column("changelog", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("skill_id", "version", name="uq_skill_version"),
    )
    op.create_index("ix_skill_versions_skill_id", "skill_versions", ["skill_id"])
    op.create_index("ix_skill_versions_content_hash", "skill_versions", ["content_hash"])

    op.create_table(
        "security_scans",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("skill_id", sa.String(length=36), sa.ForeignKey("skills.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version_id", sa.String(length=36), sa.ForeignKey("skill_versions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="clear"),
        sa.Column("findings", sa.JSON(), nullable=False),
        sa.Column("scanner", sa.String(length=40), nullable=False, server_default="agentdock-static-v2"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_security_scans_skill_id", "security_scans", ["skill_id"])
    op.create_index("ix_security_scans_version_id", "security_scans", ["version_id"])
    op.create_index("ix_security_scans_status", "security_scans", ["status"])
    op.create_index("ix_security_scans_created_at", "security_scans", ["created_at"])

    op.create_table(
        "collections",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False, server_default="Favorites"),
        sa.Column("description", sa.String(length=300), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_collections_user_id", "collections", ["user_id"])

    op.create_table(
        "collection_items",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("collection_id", sa.String(length=36), sa.ForeignKey("collections.id", ondelete="CASCADE"), nullable=False),
        sa.Column("skill_id", sa.String(length=36), sa.ForeignKey("skills.id", ondelete="CASCADE"), nullable=False),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("collection_id", "skill_id", name="uq_collection_skill"),
    )
    op.create_index("ix_collection_items_collection_id", "collection_items", ["collection_id"])
    op.create_index("ix_collection_items_skill_id", "collection_items", ["skill_id"])

    op.create_table(
        "usage_events",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("skill_id", sa.String(length=36), sa.ForeignKey("skills.id", ondelete="SET NULL"), nullable=True),
        sa.Column("event", sa.String(length=40), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False, server_default="web"),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_usage_events_user_id", "usage_events", ["user_id"])
    op.create_index("ix_usage_events_skill_id", "usage_events", ["skill_id"])
    op.create_index("ix_usage_events_event", "usage_events", ["event"])
    op.create_index("ix_usage_events_created_at", "usage_events", ["created_at"])

    op.create_table(
        "admission_decisions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("skill_id", sa.String(length=36), sa.ForeignKey("skills.id", ondelete="CASCADE"), nullable=False),
        sa.Column("actor_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_admission_decisions_skill_id", "admission_decisions", ["skill_id"])

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("actor_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("target_type", sa.String(length=80), nullable=False, server_default=""),
        sa.Column("target_id", sa.String(length=80), nullable=False, server_default=""),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_logs_actor_id", "audit_logs", ["actor_id"])
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"])
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])

    op.create_table(
        "trusted_publishers",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("github_handle", sa.String(length=100), nullable=False, unique=True),
        sa.Column("kind", sa.String(length=20), nullable=False, server_default="user"),
        sa.Column("trust_level", sa.String(length=24), nullable=False, server_default="verified"),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_trusted_publishers_github_handle", "trusted_publishers", ["github_handle"], unique=True)

    op.create_table(
        "synchronization_jobs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("repository_id", sa.String(length=36), sa.ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="queued"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for name, columns in (("ix_synchronization_jobs_repository_id", ["repository_id"]),
                          ("ix_synchronization_jobs_status", ["status"]),
                          ("ix_synchronization_jobs_next_retry_at", ["next_retry_at"]),
                          ("ix_synchronization_jobs_created_at", ["created_at"])):
        op.create_index(name, "synchronization_jobs", columns)


def downgrade() -> None:
    for table in ("synchronization_jobs", "trusted_publishers", "audit_logs", "admission_decisions",
                  "usage_events", "collection_items", "collections", "security_scans",
                  "skill_versions", "skills", "repositories", "api_keys", "sessions", "users"):
        op.drop_table(table)
