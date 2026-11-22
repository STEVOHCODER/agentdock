"""Accounts, teams, subscriptions, marketplace and operations.

The revision also repairs columns that older development databases were missing
even though they reported the previous Alembic revision. All checks are
idempotent, so the migration is safe on both fresh and upgraded installations.
"""
import sqlalchemy as sa
from alembic import op


revision = "20261122_0004"
down_revision = "20261122_0003"
branch_labels = None
depends_on = None


def _tables(bind) -> set[str]:
    return set(sa.inspect(bind).get_table_names())


def _columns(bind, table: str) -> set[str]:
    if table not in _tables(bind):
        return set()
    return {column["name"] for column in sa.inspect(bind).get_columns(table)}


def _indexes(bind, table: str) -> set[str]:
    if table not in _tables(bind):
        return set()
    return {index["name"] for index in sa.inspect(bind).get_indexes(table)}


def _add_columns(bind, table: str, columns: list[sa.Column]) -> None:
    existing = _columns(bind, table)
    missing = [column for column in columns if column.name not in existing]
    if not missing:
        return
    if bind.dialect.name == "sqlite" and any(column.foreign_keys for column in missing):
        # SQLite cannot ALTER ADD a column that carries a foreign key. Batch
        # mode recreates the table while preserving its data and constraints.
        with op.batch_alter_table(table) as batch:
            for column in missing:
                batch.add_column(column)
        return
    for column in missing:
        op.add_column(table, column)


def _create_index(bind, name: str, table: str, columns: list[str], unique: bool = False) -> None:
    if name not in _indexes(bind, table):
        op.create_index(name, table, columns, unique=unique)


def _ensure_base_repairs(bind) -> None:
    """Repair tables and columns missing from pre-release development databases."""
    if "security_scans" not in _tables(bind):
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
        for name, columns in (("ix_security_scans_skill_id", ["skill_id"]),
                              ("ix_security_scans_version_id", ["version_id"]),
                              ("ix_security_scans_status", ["status"]),
                              ("ix_security_scans_created_at", ["created_at"])):
            op.create_index(name, "security_scans", columns)
    if "admission_decisions" not in _tables(bind):
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

    _add_columns(bind, "users", [
        sa.Column("name", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
    ])
    _add_columns(bind, "repositories", [
        sa.Column("last_commit_sha", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("priority", sa.String(length=16), nullable=False, server_default="standard"),
        sa.Column("sync_interval_hours", sa.Integer(), nullable=False, server_default="24"),
        sa.Column("discovered_via", sa.String(length=40), nullable=False, server_default="manual"),
        sa.Column("last_error", sa.Text(), nullable=False, server_default=""),
        sa.Column("rights_status", sa.String(length=24), nullable=False, server_default="unknown"),
        sa.Column("community", sa.String(length=120), nullable=False, server_default=""),
    ])
    _add_columns(bind, "skills", [
        sa.Column("is_featured", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("commercial_ok", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("technologies", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("compatibility", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("dependencies", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("permissions", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("changelog", sa.Text(), nullable=False, server_default=""),
        sa.Column("community", sa.String(length=120), nullable=False, server_default=""),
    ])
    _add_columns(bind, "skill_versions", [
        sa.Column("changelog", sa.Text(), nullable=False, server_default=""),
    ])
    _add_columns(bind, "collections", [
        sa.Column("description", sa.String(length=300), nullable=False, server_default=""),
    ])
    _add_columns(bind, "usage_events", [
        sa.Column("details", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    ])
    _create_index(bind, "ix_skills_community", "skills", ["community"])
    _create_index(bind, "ix_skills_is_featured", "skills", ["is_featured"])


def upgrade():
    bind = op.get_bind()
    _ensure_base_repairs(bind)
    tables = _tables(bind)

    if "email_tokens" not in tables:
        op.create_table(
            "email_tokens",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("purpose", sa.String(length=32), nullable=False),
            sa.Column("token_hash", sa.String(length=64), nullable=False, unique=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        for name, columns in (("ix_email_tokens_user_id", ["user_id"]),
                              ("ix_email_tokens_purpose", ["purpose"]),
                              ("ix_email_tokens_expires_at", ["expires_at"])):
            op.create_index(name, "email_tokens", columns)

    if "subscription_plans" not in tables:
        op.create_table(
            "subscription_plans",
            sa.Column("code", sa.String(length=40), primary_key=True),
            sa.Column("name", sa.String(length=80), nullable=False),
            sa.Column("description", sa.String(length=300), nullable=False, server_default=""),
            sa.Column("price_cents", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("annual_price_cents", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("currency", sa.String(length=3), nullable=False, server_default="USD"),
            sa.Column("member_limit", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("features", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_subscription_plans_is_active", "subscription_plans", ["is_active"])

    if "teams" not in tables:
        op.create_table(
            "teams",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("name", sa.String(length=120), nullable=False),
            sa.Column("slug", sa.String(length=140), nullable=False, unique=True),
            sa.Column("owner_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("plan_code", sa.String(length=40), nullable=False, server_default="free"),
            sa.Column("seat_limit", sa.Integer(), nullable=False, server_default="2"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_teams_slug", "teams", ["slug"], unique=True)
        op.create_index("ix_teams_owner_id", "teams", ["owner_id"])

    if "team_members" not in tables:
        op.create_table(
            "team_members",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("team_id", sa.String(length=36), sa.ForeignKey("teams.id", ondelete="CASCADE"), nullable=False),
            sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("role", sa.String(length=16), nullable=False, server_default="member"),
            sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("team_id", "user_id", name="uq_team_member"),
        )
        op.create_index("ix_team_members_team_id", "team_members", ["team_id"])
        op.create_index("ix_team_members_user_id", "team_members", ["user_id"])

    if "team_invitations" not in tables:
        op.create_table(
            "team_invitations",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("team_id", sa.String(length=36), sa.ForeignKey("teams.id", ondelete="CASCADE"), nullable=False),
            sa.Column("email", sa.String(length=254), nullable=False),
            sa.Column("role", sa.String(length=16), nullable=False, server_default="member"),
            sa.Column("token_hash", sa.String(length=64), nullable=False, unique=True),
            sa.Column("invited_by", sa.String(length=36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        for name, columns in (("ix_team_invitations_team_id", ["team_id"]),
                              ("ix_team_invitations_email", ["email"]),
                              ("ix_team_invitations_expires_at", ["expires_at"])):
            op.create_index(name, "team_invitations", columns)

    if "subscriptions" not in tables:
        op.create_table(
            "subscriptions",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
            sa.Column("team_id", sa.String(length=36), sa.ForeignKey("teams.id", ondelete="CASCADE"), nullable=True),
            sa.Column("plan_code", sa.String(length=40), sa.ForeignKey("subscription_plans.code"), nullable=False),
            sa.Column("status", sa.String(length=24), nullable=False, server_default="pending"),
            sa.Column("interval", sa.String(length=16), nullable=False, server_default="month"),
            sa.Column("provider", sa.String(length=32), nullable=False, server_default="manual"),
            sa.Column("provider_ref", sa.String(length=200), nullable=False, server_default=""),
            sa.Column("current_period_start", sa.DateTime(timezone=True), nullable=True),
            sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
            sa.Column("cancel_at_period_end", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        for name, columns in (("ix_subscriptions_user_id", ["user_id"]),
                              ("ix_subscriptions_team_id", ["team_id"]),
                              ("ix_subscriptions_plan_code", ["plan_code"]),
                              ("ix_subscriptions_status", ["status"]),
                              ("ix_subscriptions_provider_ref", ["provider_ref"]),
                              ("ix_subscriptions_owner", ["user_id", "team_id", "status"])):
            op.create_index(name, "subscriptions", columns)

    if "creator_profiles" not in tables:
        op.create_table(
            "creator_profiles",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True),
            sa.Column("display_name", sa.String(length=120), nullable=False, server_default=""),
            sa.Column("bio", sa.Text(), nullable=False, server_default=""),
            sa.Column("website", sa.String(length=300), nullable=False, server_default=""),
            sa.Column("status", sa.String(length=24), nullable=False, server_default="pending"),
            sa.Column("revenue_share_bps", sa.Integer(), nullable=False, server_default="8500"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_creator_profiles_user_id", "creator_profiles", ["user_id"], unique=True)
        op.create_index("ix_creator_profiles_status", "creator_profiles", ["status"])

    if "marketplace_listings" not in tables:
        op.create_table(
            "marketplace_listings",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("skill_id", sa.String(length=36), sa.ForeignKey("skills.id", ondelete="CASCADE"), nullable=False, unique=True),
            sa.Column("creator_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("title", sa.String(length=160), nullable=False),
            sa.Column("summary", sa.Text(), nullable=False, server_default=""),
            sa.Column("price_cents", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("currency", sa.String(length=3), nullable=False, server_default="USD"),
            sa.Column("status", sa.String(length=24), nullable=False, server_default="draft"),
            sa.Column("commission_bps", sa.Integer(), nullable=False, server_default="1500"),
            sa.Column("featured", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        for name, columns in (("ix_marketplace_listings_skill_id", ["skill_id"]),
                              ("ix_marketplace_listings_creator_id", ["creator_id"]),
                              ("ix_marketplace_listings_status", ["status"]),
                              ("ix_marketplace_listings_featured", ["featured"])):
            op.create_index(name, "marketplace_listings", columns, unique=(name.endswith("skill_id")))

    if "payments" not in tables:
        op.create_table(
            "payments",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("team_id", sa.String(length=36), sa.ForeignKey("teams.id", ondelete="SET NULL"), nullable=True),
            sa.Column("purpose", sa.String(length=24), nullable=False, server_default="subscription"),
            sa.Column("reference", sa.String(length=80), nullable=False, unique=True),
            sa.Column("provider", sa.String(length=32), nullable=False, server_default="manual"),
            sa.Column("provider_ref", sa.String(length=200), nullable=False, server_default=""),
            sa.Column("amount_cents", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("currency", sa.String(length=3), nullable=False, server_default="USD"),
            sa.Column("status", sa.String(length=24), nullable=False, server_default="pending"),
            sa.Column("metadata", sa.JSON(), nullable=False),
            sa.Column("checkout_url", sa.String(length=1000), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        )
        for name, columns in (("ix_payments_user_id", ["user_id"]),
                              ("ix_payments_team_id", ["team_id"]),
                              ("ix_payments_purpose", ["purpose"]),
                              ("ix_payments_reference", ["reference"]),
                              ("ix_payments_provider", ["provider"]),
                              ("ix_payments_provider_ref", ["provider_ref"]),
                              ("ix_payments_status", ["status"]),
                              ("ix_payments_created_at", ["created_at"])):
            op.create_index(name, "payments", columns, unique=(name.endswith("reference")))

    if "payment_events" not in tables:
        op.create_table(
            "payment_events",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("provider", sa.String(length=32), nullable=False),
            sa.Column("event_id", sa.String(length=200), nullable=False, unique=True),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_payment_events_provider", "payment_events", ["provider"])
        op.create_index("ix_payment_events_event_id", "payment_events", ["event_id"], unique=True)

    if "purchases" not in tables:
        op.create_table(
            "purchases",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("team_id", sa.String(length=36), sa.ForeignKey("teams.id", ondelete="SET NULL"), nullable=True),
            sa.Column("listing_id", sa.String(length=36), sa.ForeignKey("marketplace_listings.id", ondelete="CASCADE"), nullable=False),
            sa.Column("payment_id", sa.String(length=36), sa.ForeignKey("payments.id", ondelete="SET NULL"), nullable=True),
            sa.Column("amount_cents", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("currency", sa.String(length=3), nullable=False, server_default="USD"),
            sa.Column("status", sa.String(length=24), nullable=False, server_default="pending"),
            sa.Column("provider", sa.String(length=32), nullable=False, server_default="manual"),
            sa.Column("provider_ref", sa.String(length=200), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        )
        for name, columns in (("ix_purchases_user_id", ["user_id"]),
                              ("ix_purchases_team_id", ["team_id"]),
                              ("ix_purchases_listing_id", ["listing_id"]),
                              ("ix_purchases_payment_id", ["payment_id"]),
                              ("ix_purchases_status", ["status"]),
                              ("ix_purchases_created_at", ["created_at"])):
            op.create_index(name, "purchases", columns)

    if "creator_earnings" not in tables:
        op.create_table(
            "creator_earnings",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("creator_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("purchase_id", sa.String(length=36), sa.ForeignKey("purchases.id", ondelete="CASCADE"), nullable=False, unique=True),
            sa.Column("amount_cents", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("status", sa.String(length=24), nullable=False, server_default="pending"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_creator_earnings_creator_id", "creator_earnings", ["creator_id"])
        op.create_index("ix_creator_earnings_purchase_id", "creator_earnings", ["purchase_id"], unique=True)
        op.create_index("ix_creator_earnings_status", "creator_earnings", ["status"])

    if "reviews" not in tables:
        op.create_table(
            "reviews",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("listing_id", sa.String(length=36), sa.ForeignKey("marketplace_listings.id", ondelete="CASCADE"), nullable=False),
            sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("rating", sa.Integer(), nullable=False, server_default="5"),
            sa.Column("body", sa.Text(), nullable=False, server_default=""),
            sa.Column("status", sa.String(length=16), nullable=False, server_default="published"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("listing_id", "user_id", name="uq_review_listing_user"),
        )
        op.create_index("ix_reviews_listing_id", "reviews", ["listing_id"])
        op.create_index("ix_reviews_user_id", "reviews", ["user_id"])
        op.create_index("ix_reviews_status", "reviews", ["status"])

    if "system_settings" not in tables:
        op.create_table(
            "system_settings",
            sa.Column("key", sa.String(length=100), primary_key=True),
            sa.Column("value", sa.JSON(), nullable=False),
            sa.Column("updated_by", sa.String(length=36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )

    if "notifications" not in tables:
        op.create_table(
            "notifications",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
            sa.Column("audience", sa.String(length=16), nullable=False, server_default="user"),
            sa.Column("kind", sa.String(length=40), nullable=False, server_default="system"),
            sa.Column("title", sa.String(length=200), nullable=False),
            sa.Column("body", sa.Text(), nullable=False, server_default=""),
            sa.Column("link", sa.String(length=300), nullable=False, server_default=""),
            sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_notifications_user_id", "notifications", ["user_id"])
        op.create_index("ix_notifications_audience", "notifications", ["audience"])
        op.create_index("ix_notifications_created_at", "notifications", ["created_at"])

    if "rights_requests" not in tables:
        op.create_table(
            "rights_requests",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("requester_name", sa.String(length=120), nullable=False),
            sa.Column("requester_email", sa.String(length=254), nullable=False),
            sa.Column("skill_id", sa.String(length=36), sa.ForeignKey("skills.id", ondelete="SET NULL"), nullable=True),
            sa.Column("repository_url", sa.String(length=500), nullable=False, server_default=""),
            sa.Column("claim_type", sa.String(length=40), nullable=False, server_default="takedown"),
            sa.Column("details", sa.Text(), nullable=False),
            sa.Column("status", sa.String(length=24), nullable=False, server_default="open"),
            sa.Column("resolution", sa.Text(), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        )
        for name, columns in (("ix_rights_requests_requester_email", ["requester_email"]),
                              ("ix_rights_requests_skill_id", ["skill_id"]),
                              ("ix_rights_requests_status", ["status"]),
                              ("ix_rights_requests_created_at", ["created_at"])):
            op.create_index(name, "rights_requests", columns)

    if "discovery_runs" not in tables:
        op.create_table(
            "discovery_runs",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("triggered_by", sa.String(length=36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("source", sa.String(length=40), nullable=False, server_default="github"),
            sa.Column("query", sa.String(length=500), nullable=False, server_default=""),
            sa.Column("candidates_found", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("status", sa.String(length=24), nullable=False, server_default="running"),
            sa.Column("error", sa.Text(), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_discovery_runs_status", "discovery_runs", ["status"])
        op.create_index("ix_discovery_runs_created_at", "discovery_runs", ["created_at"])

    # Team-aware collections and usage need the teams table to exist first.
    _add_columns(bind, "collections", [
        sa.Column("team_id", sa.String(length=36),
                  sa.ForeignKey("teams.id", ondelete="CASCADE", name="fk_collections_team_id"),
                  nullable=True),
    ])
    _add_columns(bind, "usage_events", [
        sa.Column("team_id", sa.String(length=36),
                  sa.ForeignKey("teams.id", ondelete="SET NULL", name="fk_usage_events_team_id"),
                  nullable=True),
    ])
    _create_index(bind, "ix_collections_team_id", "collections", ["team_id"])
    _create_index(bind, "ix_usage_events_team_id", "usage_events", ["team_id"])


def downgrade():
    bind = op.get_bind()
    tables = _tables(bind)
    for table in ("discovery_runs", "rights_requests", "notifications", "system_settings", "reviews",
                  "creator_earnings", "purchases", "payment_events", "payments", "marketplace_listings",
                  "creator_profiles", "subscriptions", "team_invitations", "team_members", "teams",
                  "subscription_plans", "email_tokens"):
        if table in tables:
            op.drop_table(table)
    # Compatibility columns are intentionally left in place: they belong to the
    # base tables and may also have been created by revision 0001.
