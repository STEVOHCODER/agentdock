"""Add execution_jobs for the isolated skill execution bridge.

The revision is idempotent so both fresh databases and existing installations
upgrade cleanly.
"""
import sqlalchemy as sa
from alembic import op


revision = "20261123_0001"
down_revision = "20261122_0004"
branch_labels = None
depends_on = None


def _tables(bind) -> set[str]:
    return set(sa.inspect(bind).get_table_names())


def _indexes(bind, table: str) -> set[str]:
    if table not in _tables(bind):
        return set()
    return {index["name"] for index in sa.inspect(bind).get_indexes(table)}


def upgrade() -> None:
    bind = op.get_bind()
    if "execution_jobs" not in _tables(bind):
        op.create_table(
            "execution_jobs",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("team_id", sa.String(length=36), sa.ForeignKey("teams.id", ondelete="SET NULL"), nullable=True),
            sa.Column("skill_id", sa.String(length=36), sa.ForeignKey("skills.id", ondelete="CASCADE"), nullable=False),
            sa.Column("version", sa.String(length=120), nullable=False),
            sa.Column("version_hash", sa.String(length=128), nullable=False, server_default=""),
            sa.Column("command", sa.Text, nullable=False),
            sa.Column("arguments", sa.JSON, nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
            sa.Column("stdout", sa.Text, nullable=False, server_default=""),
            sa.Column("stderr", sa.Text, nullable=False, server_default=""),
            sa.Column("error", sa.Text, nullable=False, server_default=""),
            sa.Column("exit_code", sa.Integer, nullable=True),
            sa.Column("pid", sa.Integer, nullable=True),
            sa.Column("runner_id", sa.String(length=120), nullable=False, server_default=""),
            sa.Column("sandbox", sa.String(length=64), nullable=False, server_default="bubblewrap"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        )
    indexes = _indexes(bind, "execution_jobs")
    existing_columns = {column["name"] for column in sa.inspect(bind).get_columns("execution_jobs")}
    if "pid" not in existing_columns:
        op.add_column("execution_jobs", sa.Column("pid", sa.Integer, nullable=True))
    if "runner_id" not in existing_columns:
        op.add_column("execution_jobs", sa.Column("runner_id", sa.String(length=120), nullable=False, server_default=""))
        op.create_index("ix_execution_jobs_runner_id", "execution_jobs", ["runner_id"])
    for name, index_columns in {
        "ix_execution_jobs_user_id": ["user_id"],
        "ix_execution_jobs_team_id": ["team_id"],
        "ix_execution_jobs_skill_id": ["skill_id"],
        "ix_execution_jobs_status": ["status"],
        "ix_execution_jobs_runner_id": ["runner_id"],
    }.items():
        if name not in indexes:
            op.create_index(name, "execution_jobs", index_columns)


def downgrade() -> None:
    if "execution_jobs" in _tables(op.get_bind()):
        op.drop_table("execution_jobs")
