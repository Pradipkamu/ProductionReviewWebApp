#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

APP_DIR="$(cd "$(dirname "\${BASH_SOURCE[0]}")" && pwd)"
EXPOSE=false

case "\${1:-}" in
  "") ;;
  --expose) EXPOSE=true ;;
  -h|--help)
    cat <<'EOF'
Usage:
  bash provision_mqtt.sh
  bash provision_mqtt.sh --expose

First-time AFMS MQTT commissioning:
  - Generates secrets only when creating a new .env.
  - Requires the MQTT TLS certificate and private key.
  - Starts the broker on loopback while Dynamic Security is provisioned.
  - Creates/verifies device, backend, and control roles/clients.
  - Removes the default broad democlient and disables bootstrap admin.
  - Runs a temporary device/backend ACL round-trip probe.
  - Leaves MQTT_ENABLED=false and does not restart the application backend.
  - --expose binds the already-secured TLS listener to 0.0.0.0:MQTT_PORT.
EOF
    exit 0
    ;;
  *)
    echo "Unsupported argument: $1" >&2
    exit 2
    ;;
esac

cd "$APP_DIR"
command -v docker >/dev/null 2>&1 || { echo "STOP: Docker is required." >&2; exit 1; }
command -v openssl >/dev/null 2>&1 || { echo "STOP: OpenSSL is required." >&2; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "STOP: Python 3 is required." >&2; exit 1; }

python3 configure_env.py

read_env() {
  python3 - "$APP_DIR/.env" "$1" <<'PY'
import sys
from pathlib import Path
path, name = Path(sys.argv[1]), sys.argv[2]
for line in path.read_text(encoding="utf-8").splitlines():
    if line.startswith(name + "="):
        print(line.split("=", 1)[1])
        break
PY
}

write_env() {
  python3 - "$APP_DIR/.env" "$1" "$2" <<'PY'
import os, sys, tempfile
from pathlib import Path
path, name, value = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
lines = path.read_text(encoding="utf-8").splitlines()
prefix = name + "="
found = False
for i, line in enumerate(lines):
    if line.startswith(prefix):
        lines[i] = prefix + value
        found = True
        break
if not found:
    lines.append(prefix + value)
fd, temp_name = tempfile.mkstemp(prefix=".env.", dir=str(path.parent), text=True)
try:
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temp_name, 0o600)
    os.replace(temp_name, path)
finally:
    if os.path.exists(temp_name):
        os.unlink(temp_name)
PY
}

MQTT_ENABLED="$(read_env MQTT_ENABLED)"
if [[ "\${MQTT_ENABLED,,}" == "true" ]]; then
  echo "STOP: MQTT_ENABLED is true. Disable backend MQTT during first-time broker commissioning." >&2
  exit 1
fi

MQTT_DOMAIN="$(read_env MQTT_DOMAIN)"
MQTT_PORT="$(read_env MQTT_PORT)"
MQTT_PORT="\${MQTT_PORT:-8883}"
MQTT_DYNSEC_PASSWORD="$(read_env MQTT_DYNSEC_PASSWORD)"
MQTT_CONTROL_PASSWORD="$(read_env MQTT_CONTROL_PASSWORD)"
MQTT_BACKEND_PASSWORD="$(read_env MQTT_BACKEND_PASSWORD)"

[[ -n "$MQTT_DOMAIN" ]] || { echo "STOP: Set MQTT_DOMAIN in .env." >&2; exit 1; }
[[ -n "$MQTT_DYNSEC_PASSWORD" ]] || { echo "STOP: MQTT_DYNSEC_PASSWORD is empty. For an existing broker, restore its original bootstrap password; do not generate a replacement." >&2; exit 1; }
[[ -n "$MQTT_CONTROL_PASSWORD" ]] || { echo "STOP: MQTT_CONTROL_PASSWORD is empty." >&2; exit 1; }
[[ -n "$MQTT_BACKEND_PASSWORD" ]] || { echo "STOP: MQTT_BACKEND_PASSWORD is empty." >&2; exit 1; }

CERT_FILE="$APP_DIR/mqtt/certs/tls.crt"
KEY_FILE="$APP_DIR/mqtt/certs/tls.key"
[[ -s "$CERT_FILE" ]] || { echo "STOP: Missing full-chain certificate: $CERT_FILE" >&2; exit 1; }
[[ -s "$KEY_FILE" ]] || { echo "STOP: Missing private key: $KEY_FILE" >&2; exit 1; }

openssl x509 -in "$CERT_FILE" -noout -checkhost "$MQTT_DOMAIN" >/dev/null 2>&1 ||
  { echo "STOP: TLS certificate SAN does not match MQTT_DOMAIN=$MQTT_DOMAIN." >&2; exit 1; }
openssl x509 -in "$CERT_FILE" -noout -checkend 0 >/dev/null 2>&1 ||
  { echo "STOP: MQTT TLS certificate is expired or not yet valid." >&2; exit 1; }

CERT_PUBLIC="$(openssl x509 -in "$CERT_FILE" -pubkey -noout | openssl pkey -pubin -outform DER 2>/dev/null | sha256sum | awk '{print $1}')"
KEY_PUBLIC="$(openssl pkey -in "$KEY_FILE" -pubout -outform DER 2>/dev/null | sha256sum | awk '{print $1}')"
[[ -n "$CERT_PUBLIC" && "$CERT_PUBLIC" == "$KEY_PUBLIC" ]] ||
  { echo "STOP: TLS certificate and private key do not match." >&2; exit 1; }

docker compose --profile mqtt config --quiet

echo "Starting Mosquitto with external port bound to loopback for secure bootstrap..."
write_env MQTT_BIND 127.0.0.1
docker compose --profile mqtt up -d --force-recreate mqtt

echo "Applying idempotent Dynamic Security roles, clients and ACLs..."
docker compose --profile mqtt --profile mqtt-setup run --rm --build mqtt-provision

if [[ "$EXPOSE" == true ]]; then
  FINAL_BIND="0.0.0.0"
else
  FINAL_BIND="127.0.0.1"
fi

write_env MQTT_BIND "$FINAL_BIND"

if [[ "$FINAL_BIND" != "127.0.0.1" ]]; then
  echo "All ACL checks passed. Publishing the TLS listener on $FINAL_BIND:$MQTT_PORT..."
  docker compose --profile mqtt up -d --no-deps --force-recreate mqtt
else
  echo "Broker remains loopback-only at 127.0.0.1:$MQTT_PORT."
fi

docker compose ps mqtt
echo
echo "MQTT broker provisioning completed."
echo "Bootstrap democlient removed; bootstrap admin disabled."
echo "Control identity: $(read_env MQTT_CONTROL_USERNAME)"
echo "Backend identity: $(read_env MQTT_BACKEND_USERNAME)"
echo "MQTT_ENABLED remains false. The backend was not restarted."
echo "Apply and verify Alembic migration 0027 through the approved deployment process before enabling MQTT_ENABLED."
if [[ "$EXPOSE" == true ]]; then
  echo "Allow inbound TCP $MQTT_PORT only. Do not expose TCP 1883."
else
  echo "To expose the secure TLS listener after commissioning, rerun: bash provision_mqtt.sh --expose"
fi
