from pathlib import Path
from alembic import command
from alembic.config import Config
from .db import engine

def upgrade_database():
    config = Config(str(Path(__file__).resolve().parents[1] / 'alembic.ini'))
    with engine.begin() as conn:
        if conn.dialect.name == 'postgresql':
            from sqlalchemy import text
            conn.execute(text('SELECT pg_advisory_xact_lock(2160001)'))
        config.attributes['connection'] = conn
        command.upgrade(config, 'head')

if __name__ == '__main__':
    upgrade_database()
