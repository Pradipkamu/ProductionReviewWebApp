# AFMS MQTT broker (ProductionReviewWebApp)

This is a separate Mosquitto broker running as a Docker Compose service on Pradipweb. It does not connect to or reuse the Oracle AFMS broker.

## Hostname and ports

Set these values in the server's untracked `.env` file:

```dotenv
MQTT_DOMAIN=machineshop.duckdns.org
MQTT_BIND=0.0.0.0
MQTT_PORT=8883
MQTT_DYNSEC_PASSWORD=<unique-long-random-secret>
```

The hostname is deliberately independent of the website URL. Changing the website hostname later does not require changing this MQTT hostname. If the MQTT hostname itself changes, update DNS, the certificate and device configuration.

- External devices: `mqtts://machineshop.duckdns.org:8883`
- Trusted containers on the Compose network: `mqtt://mqtt:1883`
- Port 1883 is not published on the host.
- Port 8883 is TLS-only and requires a certificate whose SAN covers `MQTT_DOMAIN`.

## TLS certificate files

Before starting the broker, place the certificate and private key at:

- `mqtt/certs/tls.crt` — full certificate chain (PEM)
- `mqtt/certs/tls.key` — matching private key (PEM)

The certificate must be valid for the configured `MQTT_DOMAIN`. Keep the private key out of Git. The `mqtt/certs/` directory is intentionally ignored except for this README.

If using Certbot, copy or securely deploy the renewed full chain and private key to these paths and restart/reload the MQTT service after renewal. Do not commit certificate or key files.

## Dynamic Security bootstrap

Set a unique high-entropy `MQTT_DYNSEC_PASSWORD` in the server's `.env` before starting the service. Mosquitto 2.1 creates its Dynamic Security configuration on first startup and uses this value for its initial administration client. The Dynamic Security JSON and broker data are persisted under `mqtt/data/`.

The initial Dynamic Security bootstrap also creates a `democlient` with broad read/write access to `#`. Do not expose port 8883 or connect production devices until this demo client has been deleted and least-privilege device roles/ACLs have been provisioned. This is a required pre-production hardening step. Do not expose the broker administration credentials to devices.

## AFMS device role and backend control client

After starting the broker, use the bootstrap administrator interactively to create the device role and control client. The commands below prompt for the bootstrap password; do not put it in shell history:

```bash
docker compose exec mqtt mosquitto_ctrl -h localhost -p 1883 -u admin dynsec createRole afms-device-v1
docker compose exec mqtt mosquitto_ctrl -h localhost -p 1883 -u admin dynsec addRoleACL afms-device-v1 publishClientSend 'production/v1/devices/%u/heartbeat' allow
docker compose exec mqtt mosquitto_ctrl -h localhost -p 1883 -u admin dynsec addRoleACL afms-device-v1 publishClientSend 'production/v1/devices/%u/telemetry' allow
docker compose exec mqtt mosquitto_ctrl -h localhost -p 1883 -u admin dynsec addRoleACL afms-device-v1 subscribePattern 'production/v1/devices/%u/commands' allow
docker compose exec mqtt mosquitto_ctrl -h localhost -p 1883 -u admin dynsec addRoleACL afms-device-v1 subscribePattern 'production/v1/devices/%u/acks' allow
docker compose exec mqtt mosquitto_ctrl -h localhost -p 1883 -u admin dynsec addRoleACL afms-device-v1 publishClientReceive 'production/v1/devices/%u/commands' allow
docker compose exec mqtt mosquitto_ctrl -h localhost -p 1883 -u admin dynsec addRoleACL afms-device-v1 publishClientReceive 'production/v1/devices/%u/acks' allow
docker compose exec mqtt mosquitto_ctrl -h localhost -p 1883 -u admin dynsec createClient prw-afms-control
docker compose exec mqtt mosquitto_ctrl -h localhost -p 1883 -u admin dynsec addClientRole prw-afms-control dynsec-admin
```

Set a separate password for prw-afms-control when prompted, then store it in the server .env. The control client is highly privileged and must never be placed in device firmware or frontend code. Set MQTT_ENABLED=true only after the role and control client have been verified. Remove the default democlient before exposing the broker to external devices.

## Start and verify (after TLS files and .env are ready)

The broker is in the optional `mqtt` Compose profile. Normal `docker compose up -d` continues to start only the existing application services. The backend explicitly receives an empty `MQTT_DYNSEC_PASSWORD`; the broker bootstrap password is not passed into the application container. The backend uses a dedicated control client, separate from the bootstrap admin account. Before enabling MQTT_ENABLED, create the device role and the backend control client from inside the broker container. Store the control client's credentials in the server .env as MQTT_CONTROL_USERNAME and MQTT_CONTROL_PASSWORD. Keep MQTT_ENABLED=false until this is completed and verified.

```bash
docker compose config --services
docker compose up -d mqtt
docker compose ps mqtt
docker compose logs --tail=100 mqtt
```

Do not open TCP 1883 in the server firewall/security list. Allow TCP 8883 only. When MQTT_ENABLED=true, the backend uses two distinct broker identities:\n\n- `MQTT_CONTROL_USERNAME` / `MQTT_CONTROL_PASSWORD`: privileged Dynamic Security provisioning only.\n- `MQTT_BACKEND_USERNAME` / `MQTT_BACKEND_PASSWORD`: data-plane client assigned the least-privilege `afms-backend-v1` role. It subscribes to device heartbeat, telemetry and acknowledgement topics, and publishes device-specific commands.\n\nThe `afms-backend-v1` role must allow the backend to subscribe to and receive
`production/v1/devices/+/heartbeat` and `.../telemetry`, and to publish
application acknowledgements on `production/v1/devices/+/acks` plus commands on
`production/v1/devices/+/commands`. It does not need to subscribe to device ACK
topics. Add the backend ACK publish permission with the bootstrap administrator:

```bash
docker compose exec mqtt mosquitto_ctrl -h localhost -p 1883 -u admin dynsec addRoleACL afms-backend-v1 publishClientSend 'production/v1/devices/+/acks' allow
```

The device role publishes heartbeat and telemetry and subscribes to its own
`commands` and `acks` topics. Device topic ACLs must remain scoped to each
registered UID. The application validates each incoming UID against an active
AFMS device mapped to an active PRW machine. Heartbeats update device presence.
Telemetry is committed to `afms_telemetry_events` with a unique
(device_id, event_id) key before the backend sends an application ACK. Duplicate
QoS-1 deliveries receive a duplicate ACK and are not processed twice.

When the product code, effective route/machine mapping, ideal cycle time and shift
context resolve, cumulative AFMS counts update the matching AFMS-sourced
`machine_shift_production` row. Completed loss selections are mapped to
`machine_loss_events` when a PRW loss category can be identified. Unresolved
mapping or validation cases remain in the telemetry ledger with a processing
status and error; they are not silently discarded. The device retains queued
telemetry until it receives the application ACK. Backend command publishing is
guarded by the same active-device/machine mapping check.

The data-plane client reconnects automatically. Keep `MQTT_ENABLED=false`
until both broker identities and role ACLs have been verified. Migration
`0027_afms_telemetry_events` must be reviewed and applied separately; this
code change does not run the production migration.

## Persistence and backups

Broker state and logs are stored in Docker-managed named volumes (`mqtt_data` and `mqtt_log`) so container UID/GID permissions do not depend on host bind-directory ownership. Include the `mqtt_data` volume in the server backup plan (for example, archive it using a temporary helper container). Never back up or publish private TLS keys or plaintext broker credentials to Git.
