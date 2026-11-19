# AFMS MQTT broker (ProductionReviewWebApp)

This is a separate Mosquitto broker running as a Docker Compose service on the ProductionReviewWebApp host. It does not connect to or reuse the Oracle AFMS broker.

## Hostname and ports

Set the server-specific hostname in the untracked `.env` file:

```dotenv
MQTT_DOMAIN=machineshop.duckdns.org
MQTT_BIND=127.0.0.1
MQTT_PORT=8883
```

- External devices: `mqtts://machineshop.duckdns.org:8883`
- Trusted containers on the Compose network: `mqtt://mqtt:1883`
- Port 1883 is not published on the host.
- The default host binding is loopback-only. Expose 8883 only after provisioning and TLS verification.

## TLS certificate files

Before provisioning, place the certificate and private key at:

- `mqtt/certs/tls.crt` — full certificate chain (PEM)
- `mqtt/certs/tls.key` — matching private key (PEM)

The certificate must be valid for `MQTT_DOMAIN`. Keep the private key out of Git. The `mqtt/certs/` directory is intentionally ignored except for this README.

The provisioning script validates the certificate hostname, validity dates and public/private key match before starting the broker.

## Fresh installation and automated Dynamic Security provisioning

Run the normal environment initializer first:

```bash
python3 configure_env.py
```

On a newly created `.env`, it generates and stores independent high-entropy values for:

- `MQTT_DYNSEC_PASSWORD` — initial Mosquitto Dynamic Security bootstrap administrator password
- `MQTT_CONTROL_PASSWORD` — privileged application control identity
- `MQTT_BACKEND_PASSWORD` — least-privilege data-plane identity

Existing `.env` files are preserved. The initializer does not silently rotate credentials for an already-initialized broker.

After DNS and the TLS certificate are ready, run:

```bash
bash provision_mqtt.sh
```

This first-time commissioning helper:

1. Requires `MQTT_ENABLED=false` and a valid matching TLS certificate/key.
2. Starts Mosquitto with the external listener bound to `127.0.0.1` while setup is in progress.
3. Runs the one-shot `mqtt-provision` container using the backend image's Paho MQTT library.
4. Creates or verifies the `afms-device-v1` and `afms-backend-v1` roles and their exact approved ACL sets.
5. Creates or verifies `prw-afms-control` with the built-in `dynsec-admin` role and `prw-afms-backend` with only `afms-backend-v1`.
6. Removes the broad bootstrap `democlient`, performs a temporary device/backend ACL round-trip probe, then disables the bootstrap `admin` account after the dedicated control identity has been verified.
7. Leaves `MQTT_ENABLED=false`, does not restart the application backend, and does not run or modify database migrations.

The role ACLs are:

| Role | Permission | Topic |
|---|---|---|
| `afms-device-v1` | publishClientSend | `production/v1/devices/%u/heartbeat` |
| `afms-device-v1` | publishClientSend | `production/v1/devices/%u/telemetry` |
| `afms-device-v1` | subscribePattern | `production/v1/devices/%u/commands` |
| `afms-device-v1` | subscribePattern | `production/v1/devices/%u/acks` |
| `afms-device-v1` | publishClientReceive | `production/v1/devices/%u/commands` |
| `afms-device-v1` | publishClientReceive | `production/v1/devices/%u/acks` |
| `afms-backend-v1` | subscribePattern | `production/v1/devices/+/heartbeat` |
| `afms-backend-v1` | subscribePattern | `production/v1/devices/+/telemetry` |
| `afms-backend-v1` | subscribePattern | `production/v1/devices/+/acks` |
| `afms-backend-v1` | publishClientSend | `production/v1/devices/+/commands` |
| `afms-backend-v1` | publishClientSend | `production/v1/devices/+/acks` |

The provisioner is idempotent: it adds missing approved ACLs, preserves existing credentials, and verifies role membership. It does not silently remove unexpected ACLs or re-enable disabled clients; it stops and requests manual review instead. Its temporary device identity is removed after the ACL round-trip check.

To expose the TLS listener after provisioning, explicitly run:

```bash
bash provision_mqtt.sh --expose
```

That binds the existing TLS listener to `0.0.0.0:MQTT_PORT`. Then allow inbound TCP 8883 in the server firewall/security group. Never expose TCP 1883.

## Backend activation

The provisioner intentionally leaves `MQTT_ENABLED=false`. After the approved application update has been installed and Alembic migration `0027_afms_telemetry_events` has been applied and verified, set `MQTT_ENABLED=true` in the server's `.env` and restart only the backend service. Do not enable the data plane before the telemetry ledger exists.

The backend uses two identities:

- `MQTT_CONTROL_USERNAME` / `MQTT_CONTROL_PASSWORD`: privileged Dynamic Security provisioning only.
- `MQTT_BACKEND_USERNAME` / `MQTT_BACKEND_PASSWORD`: data-plane subscriptions, device commands and telemetry acknowledgements.

The runtime backend container receives an empty `MQTT_DYNSEC_PASSWORD`; the broker bootstrap password is not passed into the normal backend service.

## Persistence and backups

Broker state and logs are stored in Docker-managed named volumes (`mqtt_data` and `mqtt_log`) so container UID/GID permissions do not depend on host bind-directory ownership. Include the `mqtt_data` volume in the server backup plan (for example, archive it using a temporary helper container). Never back up or publish private TLS keys or plaintext broker credentials to Git.
