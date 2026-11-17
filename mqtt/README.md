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

The initial Dynamic Security bootstrap also creates a demo client in the default configuration. Before allowing production devices to connect, remove that demo client and provision least-privilege clients/roles/ACLs. Do not expose the broker administration credentials to devices.

## Start and verify (after TLS files and .env are ready)

```bash
docker compose config --services
docker compose up -d mqtt
docker compose ps mqtt
docker compose logs --tail=100 mqtt
```

Do not open TCP 1883 in the server firewall/security list. Allow TCP 8883 only. The application backend is not yet wired to broker lifecycle/telemetry in this infrastructure stage; that integration is a separate implementation step.

## Persistence and backups

Broker state and logs are stored in Docker-managed named volumes (`mqtt_data` and `mqtt_log`) so container UID/GID permissions do not depend on host bind-directory ownership. Include the `mqtt_data` volume in the server backup plan (for example, archive it using a temporary helper container). Never back up or publish private TLS keys or plaintext broker credentials to Git.
