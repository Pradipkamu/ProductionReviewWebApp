"""Regression checks for the safe feature revert, including installed v0.4.2 databases."""
from pathlib import Path
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from app.main import app


def test_capture_routes_removed():
    paths = app.openapi()['paths']
    assert not any(path.startswith('/api/shop-capture') for path in paths)
    assert '/api/oee/machine-entry' in paths
    assert '/api/import/preview/{kind}' in paths


def test_existing_capture_database_remains_compatible(tmp_path):
    engine = create_engine('sqlite:///' + str(tmp_path / 'installed-v042.sqlite'))
    config = Config(str(Path(__file__).resolve().parents[1] / 'alembic.ini'))
    with engine.begin() as conn:
        config.attributes['connection'] = conn
        command.upgrade(config, '0005_shop_capture')
        conn.execute(text("INSERT INTO users (id,username,password_hash,full_name,role,is_active,must_change_password,token_version,created_at,updated_at) VALUES (1,'keeper','hash','Keeper','ADMIN',1,0,0,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"))
        conn.execute(text("INSERT INTO shop_captures (id,owner_id,file_sha256,source_name,image_path,original_text,draft_json,history_json,receipt_json,revision,status,created_at,updated_at) VALUES (1,1,'abc','report.png','preserved.png','Original report','{}','[]','[]',1,'draft',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"))
    with engine.begin() as conn:
        config.attributes['connection'] = conn
        command.upgrade(config, 'head')
        assert conn.scalar(text('SELECT original_text FROM shop_captures WHERE id=1')) == 'Original report'
        assert conn.scalar(text('SELECT image_path FROM shop_captures WHERE id=1')) == 'preserved.png'
        assert conn.scalar(text('SELECT version_num FROM alembic_version')) == '0012_casting_customer_quality'
    engine.dispose()
