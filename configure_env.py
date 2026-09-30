"""Initialize a persistent secret; preserve every non-placeholder existing value."""
from pathlib import Path
import secrets
path=Path(__file__).resolve().parent/'.env'
if not path.exists():path.write_text(path.with_name('.env.example').read_text())
s=path.read_text()
lines=s.splitlines();seen=False
for i,line in enumerate(lines):
    if line.startswith('SECRET_KEY='):
        seen=True;value=line.split('=',1)[1].strip()
        if not value or 'CHANGE' in value.upper() or value=='dev-secret-change-me':lines[i]='SECRET_KEY='+secrets.token_urlsafe(48)
if not seen:lines.append('SECRET_KEY='+secrets.token_urlsafe(48))
path.write_text('\n'.join(lines)+'\n')
try:path.chmod(0o600)
except OSError:pass
print('Environment initialized. Existing non-placeholder secret and database settings preserved.')
