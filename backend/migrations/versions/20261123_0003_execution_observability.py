"""Add execution observability, per-job limits and plan execution quotas.

Idempotent: safe on fresh databases and existing installations.
"""
import sqlalchemy as sa
from alembic import op


revision = "20261123_0003"
down_revision = "20261123_0002"
branch_labels = None
depends_on = None


def _tables(bind) -> set[str]:
    return set(sa.inspect(bind).get_table_names())


def _columns(bind, table: str) -> set[str]:
    if table not in _tables(bind):
        return set()
    return {column["name"] for column in sa.inspect(bind).get_columns(table)}


def _add(bind, table: str, name: str, column: sa.Column) -> None:
    if name not in _columns(bind, table):
        op.add_column(table, column)


def upgrade() -> None:
    bind = op.get_bind()
    _add(bind, "execution_jobs", "dependencies", sa.Column("dependencies", sa.JSON, nullable=False, server_default="{}"))
    _add(bind, "execution_jobs", "timeout_seconds", sa.Column("timeout_seconds", sa.Integer, nullable=False, server_default="120"))
    _add(bind, "execution_jobs", "max_memory_mb", sa.Column("max_memory_mb", sa.Integer, nullable=False, server_default="1024"))
    _add(bind, "execution_jobs", "max_cpu_millicores", sa.Column("max_cpu_millicores", sa.Integer, nullable=False, server_default="1000"))
    _add(bind, "execution_jobs", "network_enabled", sa.Column("network_enabled", sa.Boolean, nullable=False, server_default=sa.false()))
    _add(bind, "execution_jobs", "duration_ms", sa.Column("duration_ms", sa.Integer, nullable=True))
    _add(bind, "execution_jobs", "peak_memory_bytes", sa.Column("peak_memory_bytes", sa.BigInteger, nullable=True))
    _add(bind, "execution_jobs", "cpu_time_ms", sa.Column("cpu_time_ms", sa.Integer, nullable=True))
    _add(bind, "execution_jobs", "resource_stats", sa.Column("resource_stats", sa.JSON, nullable=False, server_default="{}"))
    _add(bind, "subscription_plans", "execution_quota", sa.Column("execution_quota", sa.Integer, nullable=False, server_default="20"))
    for code, quota in {"free": 20, "developer": 100, "duo": 250, "team": 600, "growth": 1500}.items():
        bind.execute(sa.text("UPDATE subscription_plans SET execution_quota = :quota WHERE code = :code"),
                     {"quota": quota, "code": code})


def downgrade() -> None:
    pass
