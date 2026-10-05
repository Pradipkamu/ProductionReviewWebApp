from pathlib import Path
import subprocess
import sys

from app.auth import record_security_event
from app.main import app


ROOT = Path(__file__).resolve().parents[2]


def test_backend_auth_and_application_import_contract():
    assert callable(record_security_event)
    assert app.title


def test_backend_preflight_module_runs_without_inline_command_quoting():
    result = subprocess.run(
        [sys.executable, "-m", "app.preflight"],
        cwd=ROOT / "backend",
        check=True,
        capture_output=True,
        text=True,
    )
    assert "Backend import preflight passed" in result.stdout


def test_updaters_run_import_preflight_before_stopping_application():
    windows = (ROOT / "update_in_place_windows.ps1").read_text(encoding="utf-8")
    linux = (ROOT / "update_in_place_linux.sh").read_text(encoding="utf-8")

    windows_marker = "'python','-m','app.preflight'"
    linux_marker = "python -m app.preflight"
    assert windows_marker in windows
    assert linux_marker in linux
    assert "'python','-c'" not in windows
    assert windows.index(windows_marker) < windows.index("'compose','stop','frontend','backend'")
    assert linux.index(linux_marker) < linux.index("docker compose stop frontend backend")
