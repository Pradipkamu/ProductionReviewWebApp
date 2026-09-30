from alembic import context
from sqlalchemy import create_engine
from app.config import get_settings
from app.db import Base
from app import models

config = context.config
connection = config.attributes.get('connection')

def migrate(conn):
    context.configure(connection=conn, target_metadata=Base.metadata, compare_type=True, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()

if connection is not None:
    migrate(connection)
else:
    engine = create_engine(get_settings().database_url)
    with engine.connect() as conn:
        migrate(conn)
