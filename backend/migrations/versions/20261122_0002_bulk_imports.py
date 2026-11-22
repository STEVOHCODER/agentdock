"""Add community attribution and persistent multi-source import jobs."""
from alembic import op
import sqlalchemy as sa


revision = "20261122_0002"
down_revision = "20261122_0001"
branch_labels = None
depends_on = None


def _columns(bind, table):
    return {column["name"]: column for column in sa.inspect(bind).get_columns(table)}


def _indexes(bind, table):
    return {index["name"] for index in sa.inspect(bind).get_indexes(table)}


def _foreign_keys(bind, table):
    return {key.get("name") for key in sa.inspect(bind).get_foreign_keys(table)}


def upgrade():
    bind = op.get_bind()
    if "community" not in _columns(bind, "repositories"):
        op.add_column("repositories", sa.Column("community", sa.String(length=120), nullable=False, server_default=""))
    if "community" not in _columns(bind, "skills"):
        op.add_column("skills", sa.Column("community", sa.String(length=120), nullable=False, server_default=""))

    if "import_batches" not in sa.inspect(bind).get_table_names():
        op.create_table(
            "import_batches",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("submitted_by", sa.String(length=36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("source_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("completed_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("status", sa.String(length=24), nullable=False, server_default="queued"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_import_batches_submitted_by", "import_batches", ["submitted_by"])
        op.create_index("ix_import_batches_status", "import_batches", ["status"])
        op.create_index("ix_import_batches_created_at", "import_batches", ["created_at"])

    columns = _columns(bind, "synchronization_jobs")
    needs_batch_alter = "repository_id" in columns and columns["repository_id"]["nullable"] is False
    new_columns = {
        "batch_id": sa.Column("batch_id", sa.String(length=36), nullable=True),
        "operation": sa.Column("operation", sa.String(length=16), nullable=False, server_default="sync"),
        "source_url": sa.Column("source_url", sa.String(length=500), nullable=False, server_default=""),
        "skill_paths": sa.Column("skill_paths", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        "community": sa.Column("community", sa.String(length=120), nullable=False, server_default=""),
        "progress_current": sa.Column("progress_current", sa.Integer(), nullable=False, server_default="0"),
        "progress_total": sa.Column("progress_total", sa.Integer(), nullable=False, server_default="0"),
        "result_count": sa.Column("result_count", sa.Integer(), nullable=False, server_default="0"),
        "lease_expires_at": sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    }
    missing = [column for name, column in new_columns.items() if name not in columns]
    if needs_batch_alter or missing:
        with op.batch_alter_table("synchronization_jobs") as batch:
            if needs_batch_alter:
                batch.alter_column("repository_id", existing_type=sa.String(length=36), nullable=True)
            for column in missing:
                batch.add_column(column)
            if "batch_id" in {column.name for column in missing}:
                batch.create_foreign_key("fk_sync_jobs_import_batch", "import_batches",
                                         ["batch_id"], ["id"], ondelete="CASCADE")

    bind = op.get_bind()
    if "ix_skills_community" not in _indexes(bind, "skills"):
        op.create_index("ix_skills_community", "skills", ["community"])
    job_indexes = _indexes(bind, "synchronization_jobs")
    for name, column in (("ix_synchronization_jobs_batch_id", "batch_id"),
                         ("ix_synchronization_jobs_operation", "operation"),
                         ("ix_synchronization_jobs_lease_expires_at", "lease_expires_at")):
        if name not in job_indexes:
            op.create_index(name, "synchronization_jobs", [column])
    for name, columns in (("ix_sync_jobs_claim", ["status", "next_retry_at", "created_at"]),
                          ("ix_sync_jobs_repository_status", ["repository_id", "status"])):
        if name not in _indexes(bind, "synchronization_jobs"):
            op.create_index(name, "synchronization_jobs", columns)
    if bind.dialect.name == "postgresql":
        op.execute("""CREATE INDEX IF NOT EXISTS ix_skills_search_document
            ON skills USING GIN (to_tsvector('simple'::regconfig,
                coalesce(name, '') || ' ' || coalesce(description, '') || ' ' ||
                coalesce(category, '') || ' ' || coalesce(creator, '') || ' ' ||
                coalesce(community, '')))""")


def downgrade():
    bind = op.get_bind()
    if "import_batches" not in sa.inspect(bind).get_table_names():
        return
    for name in ("ix_synchronization_jobs_batch_id", "ix_synchronization_jobs_operation",
                 "ix_synchronization_jobs_lease_expires_at", "ix_sync_jobs_claim",
                 "ix_sync_jobs_repository_status"):
        if name in _indexes(bind, "synchronization_jobs"):
            op.drop_index(name, table_name="synchronization_jobs")
    with op.batch_alter_table("synchronization_jobs") as batch:
        for name in ("batch_id", "operation", "source_url", "skill_paths", "community",
                     "progress_current", "progress_total", "result_count", "lease_expires_at"):
            if name in _columns(bind, "synchronization_jobs"):
                batch.drop_column(name)
    if "ix_skills_community" in _indexes(bind, "skills"):
        op.drop_index("ix_skills_community", table_name="skills")
    if bind.dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_skills_search_document")
    for name in ("created_at", "status", "submitted_by"):
        index_name = f"ix_import_batches_{name}"
        if index_name in _indexes(bind, "import_batches"):
            op.drop_index(index_name, table_name="import_batches")
    op.drop_table("import_batches")
    if "community" in _columns(bind, "skills"):
        op.drop_column("skills", "community")
    if "community" in _columns(bind, "repositories"):
        op.drop_column("repositories", "community")
