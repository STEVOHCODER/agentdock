"""Add execution runner id.

Separate revision because the initial execution migration had already been
applied before this column was introduced.
"""
import sqlalchemy as sa
from alembic import op


revision = "20261123_0002"
down_revision = "20261123_0001"
branch_labels = None
depends_on = None


def _tables(bind) -> set[str]:
    return set(sa.inspect(bind).get_table_names())


def upgrade() -> None:
    bind = op.get_bind()
    if "execution_jobs" not in _tables(bind):
        return
    columns = {column["name"] for column in sa.inspect(bind).get_columns("execution_jobs")}
    if "runner_id" not in columns:
        op.add_column("execution_jobs", sa.Column("runner_id", sa.String(length=120), nullable=False, server_default=""))
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("execution_jobs")}
    if "ix_execution_jobs_runner_id" not in indexes:
        op.create_index("ix_execution_jobs_runner_id", "execution_jobs", ["runner_id"])


def downgrade() -> None:
    pass
