from alembic import context
from app.db import engine
from app.models import Base

# Only the application engine may be passed to migrations.
with engine().connect() as connection:
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()
