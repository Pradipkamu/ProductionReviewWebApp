import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _values(path: Path) -> dict[str, str]:
    return {
        line.split('=', 1)[0]: line.split('=', 1)[1]
        for line in path.read_text(encoding='utf-8').splitlines()
        if '=' in line and not line.lstrip().startswith('#')
    }


def _copy_configurator(tmp_path: Path) -> Path:
    shutil.copy2(ROOT / 'configure_env.py', tmp_path / 'configure_env.py')
    shutil.copy2(ROOT / '.env.example', tmp_path / '.env.example')
    return tmp_path / 'configure_env.py'


def test_fresh_environment_generates_independent_secrets_and_keeps_oracle_http(tmp_path):
    script = _copy_configurator(tmp_path)
    subprocess.run([sys.executable, str(script)], cwd=tmp_path, check=True, capture_output=True, text=True)
    values = _values(tmp_path / '.env')
    assert len(values['SECRET_KEY']) >= 48
    assert len(values['POSTGRES_PASSWORD']) >= 48
    assert values['POSTGRES_PASSWORD'] in values['DATABASE_URL']
    assert values['ADMIN_PASSWORD'] != 'ChangeMe123!'
    assert values['REQUIRE_HTTPS'] == 'false'
    assert values['DB_BIND'] == '127.0.0.1'
    assert values['BACKEND_BIND'] == '127.0.0.1'


def test_existing_database_url_is_preserved_until_explicit_rotation(tmp_path):
    script = _copy_configurator(tmp_path)
    (tmp_path / '.env').write_text(
        'SECRET_KEY=existing-random-secret-value-1234567890-ABC\n'
        'DATABASE_URL=postgresql+psycopg://pms:pms@db:5432/pms\n'
        'ADMIN_PASSWORD=ExistingAdminPassword!9\n',
        encoding='utf-8',
    )
    subprocess.run([sys.executable, str(script)], cwd=tmp_path, check=True, capture_output=True, text=True)
    values = _values(tmp_path / '.env')
    assert values['POSTGRES_PASSWORD'] == 'pms'
    assert values['DATABASE_URL'].endswith('pms:pms@db:5432/pms')
