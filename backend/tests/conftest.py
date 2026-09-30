import os
test_url = os.environ.get("PMS_TEST_DATABASE_URL", "sqlite:///./test-pms.sqlite")
if test_url.startswith("postgresql") and not test_url.endswith("/pms_test"):
    raise RuntimeError("PostgreSQL tests require an isolated pms_test database")
os.environ["DATABASE_URL"] = test_url
os.environ["SECRET_KEY"] = "test-only-9Zk4Tsa47HL6mQv8Pj3Bd1oU2N5rE7xC"
import pytest

from app.db import Base, SessionLocal, engine
from app.seed import seed_defaults


@pytest.fixture(autouse=True)
def clean_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        seed_defaults(db)
        from app.models import User
        from sqlalchemy import select
        for user in db.scalars(select(User)):
            user.must_change_password = False
        db.commit()
    yield
