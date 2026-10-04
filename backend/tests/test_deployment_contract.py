from pathlib import Path

from app.auth import record_security_event
from app.main import app


ROOT = Path(__file__).resolve().parents[2]


def test_backend_auth_and_application_import_contract():
    assert callable(record_security_event)
    assert app.title


def test_updaters_run_import_preflight_before_stopping_application():
    windows = (ROOT / "update_in_place_windows.ps1").read_text(encoding="utf-8")
    linux = (ROOT / "update_in_place_linux.sh").read_text(encoding="utf-8")

    marker = "from app.auth import record_security_event; from app.main import app"
    assert marker in windows
    assert marker in linux
    assert windows.index(marker) < windows.index("'compose','stop','frontend','backend'")
    assert linux.index(marker) < linux.index("docker compose stop frontend backend")
