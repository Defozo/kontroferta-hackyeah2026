"""Content-free source deletion registry for restoring older backups safely."""
from alembic import op
from apps.api.db import DocumentTombstone

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    DocumentTombstone.__table__.create(op.get_bind(), checkfirst=True)


def downgrade():
    raise RuntimeError("Deletion registries must survive rollback; use a compatible application image.")
