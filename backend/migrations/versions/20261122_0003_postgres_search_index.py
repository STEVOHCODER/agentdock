"""Use an immutable expression for PostgreSQL skill full-text search."""
from alembic import op


revision = "20261122_0003"
down_revision = "20261122_0002"
branch_labels = None
depends_on = None


def upgrade():
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("DROP INDEX IF EXISTS ix_skills_search_document")
    op.execute("""CREATE INDEX ix_skills_search_document
        ON skills USING GIN (to_tsvector('simple'::regconfig,
            coalesce(name, '') || ' ' || coalesce(description, '') || ' ' ||
            coalesce(category, '') || ' ' || coalesce(creator, '') || ' ' ||
            coalesce(community, '')))""")


def downgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_skills_search_document")
