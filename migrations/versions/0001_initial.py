"""Initial private case, identity, immutable revision and durable jobs schema."""
from alembic import op
from apps.api.db import Base
revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    Base.metadata.create_all(op.get_bind())


def downgrade():
    raise RuntimeError("Destructive downgrade requires a separate data migration plan; restore a compatible backup instead.")
