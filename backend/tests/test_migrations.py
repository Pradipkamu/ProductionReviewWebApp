from pathlib import Path
from alembic import command
from alembic.config import Config
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, text
from app.db import Base
from app import models


def test_new_database_and_legacy_adoption_preserve_rows(tmp_path):
    engine=create_engine('sqlite:///'+str(tmp_path/'legacy.sqlite'))
    config=Config(str(Path(__file__).resolve().parents[1]/'alembic.ini'))
    with engine.begin() as conn:
        config.attributes['connection']=conn
        command.upgrade(config,'0001_v0216')
        conn.execute(text("INSERT INTO users (id,username,password_hash,full_name,role,is_active,created_at,updated_at) VALUES (1,'legacy-admin','legacy-hash','Legacy Admin','ADMIN',1,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"))
        conn.execute(text("INSERT INTO products (id,code,name,sort_order,is_active,created_at,updated_at) VALUES (1,'P1','Original Part',999,1,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"))
        conn.execute(text('DROP TABLE alembic_version'))
    with engine.begin() as conn:
        config.attributes['connection']=conn;command.upgrade(config,'head')
        assert conn.scalar(text('SELECT name FROM products WHERE id=1'))=='Original Part'
        assert conn.scalar(text('SELECT password_hash FROM users WHERE id=1'))=='legacy-hash'
        assert conn.scalar(text('SELECT must_change_password FROM users WHERE id=1'))==1
        assert conn.scalar(text('SELECT version_num FROM alembic_version'))=='0010_security_sessions'
        assert conn.scalar(text('SELECT revision FROM business_data_revision WHERE id=1'))==0
        diffs=compare_metadata(MigrationContext.configure(conn),Base.metadata)
        assert not diffs,diffs
    with engine.begin() as conn:
        config.attributes['connection']=conn;command.upgrade(config,'head')
        assert conn.scalar(text('SELECT count(*) FROM products'))==1


def test_postgresql_migrations_when_service_available():
    import os
    import pytest
    from sqlalchemy.engine import make_url
    url=os.environ.get('PMS_TEST_DATABASE_URL','')
    if not url.startswith('postgresql'):
        pytest.skip('Disposable PostgreSQL service unavailable locally; CI runs this test')
    from sqlalchemy import create_engine
    from psycopg import sql
    admin=create_engine(url,isolation_level='AUTOCOMMIT')
    with admin.connect() as conn:
        conn.exec_driver_sql('CREATE DATABASE pms_migration_test')
    target=create_engine(make_url(url).set(database='pms_migration_test'))
    config=Config(str(Path(__file__).resolve().parents[1]/'alembic.ini'))
    try:
        with target.begin() as conn:
            config.attributes['connection']=conn;command.upgrade(config,'0001_v0216')
            conn.execute(text("INSERT INTO users (id,username,password_hash,full_name,role,is_active,created_at,updated_at) VALUES (1,'legacy-admin','legacy-hash','Legacy Admin','ADMIN',true,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"))
            conn.execute(text("INSERT INTO products (id,code,name,sort_order,is_active,created_at,updated_at) VALUES (1,'P1','Original Part',999,true,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"))
        with target.begin() as conn:
            config.attributes['connection']=conn;command.upgrade(config,'head')
            assert conn.scalar(text('SELECT name FROM products WHERE id=1'))=='Original Part'
            assert conn.scalar(text('SELECT must_change_password FROM users WHERE id=1')) is True
            assert not compare_metadata(MigrationContext.configure(conn),Base.metadata)
            initial=conn.scalar(text('SELECT revision FROM business_data_revision WHERE id=1'))
            conn.execute(text("UPDATE products SET name='Updated Part' WHERE id=1"))
            assert conn.scalar(text('SELECT revision FROM business_data_revision WHERE id=1'))>initial
        with target.begin() as conn:
            config.attributes['connection']=conn;command.upgrade(config,'head')
    finally:
        target.dispose()
        with admin.connect() as conn:conn.exec_driver_sql('DROP DATABASE pms_migration_test WITH (FORCE)')
        admin.dispose()
