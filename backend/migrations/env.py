from alembic import context
from app.db import engine

# Only the application engine may be passed to migrations.
with engine().connect() as connection:
    context.configure(connection=connection, target_metadata=None)
    with context.begin_transaction():
        context.run_migrations()
