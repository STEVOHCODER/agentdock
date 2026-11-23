"""Update execution quotas to the adoption-friendly policy.

Also refreshes existing plans; administrator edits to other fields are preserved.
"""
import sqlalchemy as sa
from alembic import op


revision = "20261123_0004"
down_revision = "20261123_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    for code, quota in {"free": 100, "developer": 250, "duo": 500, "team": 1000, "growth": 2500}.items():
        bind.execute(sa.text("UPDATE subscription_plans SET execution_quota = :quota WHERE code = :code"),
                     {"quota": quota, "code": code})


def downgrade() -> None:
    pass
