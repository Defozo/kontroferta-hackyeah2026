from alembic import context
from apps.api.db import Base, engine
target_metadata = Base.metadata
with engine.connect() as connection:
    context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()
