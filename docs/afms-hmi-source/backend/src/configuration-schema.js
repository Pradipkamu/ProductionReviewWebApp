import crypto from 'node:crypto';

function checksum(configuration) {
  const normalized = JSON.stringify(configuration ?? {});
  return crypto.createHash('sha256').update(normalized).digest('hex');
}

/**
 * Commit 0031A / Phase 1
 *
 * Creates the durable per-device configuration, history and synchronization
 * tables. The existing afms_devices.configuration data is migrated once so
 * current installations keep their active configuration and version.
 */
export async function ensureConfigurationSchema(pool) {
  await pool.query(`
    CREATE TABLE IF NOT EXISTS afms_device_configuration (
      id BIGSERIAL PRIMARY KEY,
      device_id BIGINT NOT NULL UNIQUE REFERENCES afms_devices(id) ON DELETE CASCADE,
      configuration_version INTEGER NOT NULL DEFAULT 1 CHECK (configuration_version > 0),
      configuration_json JSONB NOT NULL DEFAULT '{}'::jsonb,
      checksum TEXT NOT NULL,
      published BOOLEAN NOT NULL DEFAULT TRUE,
      requires_restart BOOLEAN NOT NULL DEFAULT FALSE,
      updated_by TEXT,
      updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS afms_configuration_history (
      id BIGSERIAL PRIMARY KEY,
      device_id BIGINT NOT NULL REFERENCES afms_devices(id) ON DELETE CASCADE,
      configuration_version INTEGER NOT NULL CHECK (configuration_version > 0),
      configuration_json JSONB NOT NULL,
      checksum TEXT NOT NULL,
      requires_restart BOOLEAN NOT NULL DEFAULT FALSE,
      published_by TEXT,
      published_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      remarks TEXT,
      UNIQUE (device_id, configuration_version)
    );

    CREATE TABLE IF NOT EXISTS afms_configuration_sync (
      device_id BIGINT PRIMARY KEY REFERENCES afms_devices(id) ON DELETE CASCADE,
      running_version INTEGER NOT NULL DEFAULT 0,
      latest_version INTEGER NOT NULL DEFAULT 0,
      sync_status TEXT NOT NULL DEFAULT 'NEVER_SYNCED',
      last_check_at TIMESTAMPTZ,
      last_download_at TIMESTAMPTZ,
      last_ack_at TIMESTAMPTZ,
      last_error TEXT,
      firmware_version TEXT,
      ip_address INET,
      wifi_profile TEXT,
      oracle_connected BOOLEAN NOT NULL DEFAULT FALSE,
      last_oracle_success_at TIMESTAMPTZ,
      updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    ALTER TABLE afms_configuration_sync ADD COLUMN IF NOT EXISTS wifi_profile TEXT;
    ALTER TABLE afms_configuration_sync ADD COLUMN IF NOT EXISTS oracle_connected BOOLEAN NOT NULL DEFAULT FALSE;
    ALTER TABLE afms_configuration_sync ADD COLUMN IF NOT EXISTS last_oracle_success_at TIMESTAMPTZ;
    ALTER TABLE afms_configuration_sync DROP CONSTRAINT IF EXISTS afms_configuration_sync_sync_status_check;
    ALTER TABLE afms_configuration_sync ADD CONSTRAINT afms_configuration_sync_sync_status_check
      CHECK (sync_status IN ('NEVER_SYNCED','CURRENT','UPDATE_AVAILABLE','DOWNLOADED','PENDING_WIFI_TEST','APPLIED','FAILED'));

    CREATE TABLE IF NOT EXISTS afms_configuration_status_history (
      id BIGSERIAL PRIMARY KEY,
      device_id BIGINT NOT NULL REFERENCES afms_devices(id) ON DELETE CASCADE,
      configuration_version INTEGER NOT NULL DEFAULT 0,
      sync_status TEXT NOT NULL,
      success BOOLEAN NOT NULL DEFAULT TRUE,
      error_text TEXT,
      firmware_version TEXT,
      wifi_profile TEXT,
      ip_address INET,
      oracle_connected BOOLEAN NOT NULL DEFAULT FALSE,
      reported_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    ALTER TABLE afms_configuration_status_history
      ADD COLUMN IF NOT EXISTS oracle_connected BOOLEAN NOT NULL DEFAULT FALSE;

    CREATE OR REPLACE FUNCTION afms_preserve_transitional_config_status()
    RETURNS TRIGGER AS $$
    BEGIN
      IF OLD.sync_status IN ('DOWNLOADED','PENDING_WIFI_TEST')
         AND NEW.sync_status IN ('CURRENT','UPDATE_AVAILABLE') THEN
        NEW.sync_status := OLD.sync_status;
      END IF;
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;

    DROP TRIGGER IF EXISTS trg_afms_preserve_transitional_config_status
      ON afms_configuration_sync;
    CREATE TRIGGER trg_afms_preserve_transitional_config_status
      BEFORE UPDATE OF sync_status ON afms_configuration_sync
      FOR EACH ROW
      EXECUTE FUNCTION afms_preserve_transitional_config_status();

    CREATE INDEX IF NOT EXISTS idx_afms_config_published
      ON afms_device_configuration (published, updated_at DESC);
    CREATE INDEX IF NOT EXISTS idx_afms_config_history_device_version
      ON afms_configuration_history (device_id, configuration_version DESC);
    CREATE INDEX IF NOT EXISTS idx_afms_config_sync_status
      ON afms_configuration_sync (sync_status, updated_at DESC);
    CREATE INDEX IF NOT EXISTS idx_afms_config_sync_oracle
      ON afms_configuration_sync (oracle_connected, last_oracle_success_at DESC);
    CREATE INDEX IF NOT EXISTS idx_afms_config_status_history_device
      ON afms_configuration_status_history (device_id, reported_at DESC);
  `);

  const devices = await pool.query(`
    SELECT id, config_version, configuration
    FROM afms_devices
    ORDER BY id
  `);

  for (const device of devices.rows) {
    const configuration = device.configuration ?? {};
    const version = Math.max(1, Number(device.config_version) || 1);
    const digest = checksum(configuration);

    await pool.query(`
      INSERT INTO afms_device_configuration (
        device_id, configuration_version, configuration_json, checksum,
        published, requires_restart, updated_by
      ) VALUES ($1, $2, $3, $4, TRUE, FALSE, 'migration')
      ON CONFLICT (device_id) DO NOTHING
    `, [device.id, version, configuration, digest]);

    await pool.query(`
      INSERT INTO afms_configuration_history (
        device_id, configuration_version, configuration_json, checksum,
        requires_restart, published_by, remarks
      ) VALUES ($1, $2, $3, $4, FALSE, 'migration', 'Imported from afms_devices')
      ON CONFLICT (device_id, configuration_version) DO NOTHING
    `, [device.id, version, configuration, digest]);

    await pool.query(`
      INSERT INTO afms_configuration_sync (
        device_id, running_version, latest_version, sync_status
      ) VALUES ($1, 0, $2, 'NEVER_SYNCED')
      ON CONFLICT (device_id) DO UPDATE
      SET latest_version = GREATEST(afms_configuration_sync.latest_version, EXCLUDED.latest_version),
          updated_at = NOW()
    `, [device.id, version]);
  }
}

export function configurationChecksum(configuration) {
  return checksum(configuration);
}
