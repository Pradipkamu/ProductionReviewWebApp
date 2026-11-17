import crypto from 'node:crypto';
import express from 'express';
import { requireAuth } from './auth.js';
import { configurationChecksum } from './configuration-schema.js';

const keyHash = (value) => crypto.createHash('sha256').update(value).digest('hex');
const canonical = (value) => JSON.parse(JSON.stringify(value ?? {}));
const deviceStatuses = new Set(['DOWNLOADED', 'PENDING_WIFI_TEST', 'APPLIED', 'FAILED', 'CURRENT']);

function validateConfiguration(configuration) {
  const web = configuration?.communication?.afmsWeb ?? {};
  const google = configuration?.communication?.googleSheets ?? {};
  const telegram = configuration?.communication?.telegram ?? {};
  const sync = configuration?.communication?.configSync ?? {};
  if (configuration?.network?.wifi != null || configuration?.wifi != null ||
      configuration?.wifi_ssid != null || configuration?.wifi_password != null) {
    return 'WiFi credentials are device-local and must be configured in device.json';
  }
  if ((web.mode ?? 'EVENT') !== 'EVENT') return 'AFMS Web mode must be EVENT';
  for (const key of ['enabled','sendOnRunning','sendOnBreakdown','sendOnLossAccepted','sendOnShiftChange']) {
    if (web[key] != null && typeof web[key] !== 'boolean') return `afmsWeb.${key} must be boolean`;
  }
  if (google.uploadIntervalSeconds != null && (google.uploadIntervalSeconds < 60 || google.uploadIntervalSeconds > 86400)) return 'Google interval must be 60-86400 seconds';
  if (sync.enabled != null && typeof sync.enabled !== 'boolean') return 'configSync.enabled must be boolean';
  for (const key of ['enabled','sendMachineReady','sendLossAlerts','sendReports']) {
    if (telegram[key] != null && typeof telegram[key] !== 'boolean') return `telegram.${key} must be boolean`;
  }
  return null;
}

async function authenticateDevice(pool, req, res, next) {
  try {
    const supplied = req.get('x-afms-device-key') || '';
    if (!supplied) return res.status(401).json({ error: 'Device key required' });
    const result = await pool.query(`
      SELECT id,machine_id AS "machineId",device_id AS "deviceId",active
      FROM afms_devices WHERE api_key_hash=$1 AND active=TRUE
    `, [keyHash(supplied)]);
    if (!result.rowCount) return res.status(401).json({ error: 'Invalid or disabled device key' });
    req.device = result.rows[0];
    next();
  } catch (error) { next(error); }
}

async function currentConfiguration(pool, deviceId) {
  const result = await pool.query(`
    SELECT c.device_id,c.configuration_version AS "version",c.configuration_json AS configuration,
      c.checksum,c.requires_restart AS "requiresRestart",c.published,c.updated_by AS "updatedBy",
      c.updated_at AS "updatedAt",d.machine_id AS "machineId",d.device_id AS "hardwareDeviceId"
    FROM afms_device_configuration c JOIN afms_devices d ON d.id=c.device_id
    WHERE c.device_id=$1
  `, [deviceId]);
  return result.rows[0] || null;
}

async function markOracleSuccess(pool, deviceId) {
  await pool.query(`
    INSERT INTO afms_configuration_sync(device_id,oracle_connected,last_oracle_success_at,updated_at)
    VALUES($1,TRUE,NOW(),NOW())
    ON CONFLICT(device_id) DO UPDATE SET oracle_connected=TRUE,last_oracle_success_at=NOW(),updated_at=NOW()
  `, [deviceId]);
}

async function publishConfiguration(pool, device, configuration, actor, remarks, requiresRestart = false) {
  const normalized = canonical(configuration);
  const invalid = validateConfiguration(normalized);
  if (invalid) throw Object.assign(new Error(invalid), { statusCode: 400 });
  const digest = configurationChecksum(normalized);
  const client = await pool.connect();
  try {
    await client.query('BEGIN');
    const locked = await client.query(`SELECT configuration_version FROM afms_device_configuration WHERE device_id=$1 FOR UPDATE`, [device.id]);
    const version = (Number(locked.rows[0]?.configuration_version) || 0) + 1;
    await client.query(`
      INSERT INTO afms_device_configuration(device_id,configuration_version,configuration_json,checksum,published,requires_restart,updated_by,updated_at)
      VALUES($1,$2,$3,$4,TRUE,$5,$6,NOW())
      ON CONFLICT(device_id) DO UPDATE SET configuration_version=EXCLUDED.configuration_version,
        configuration_json=EXCLUDED.configuration_json,checksum=EXCLUDED.checksum,published=TRUE,
        requires_restart=EXCLUDED.requires_restart,updated_by=EXCLUDED.updated_by,updated_at=NOW()
    `, [device.id, version, normalized, digest, Boolean(requiresRestart), actor]);
    await client.query(`
      INSERT INTO afms_configuration_history(device_id,configuration_version,configuration_json,checksum,requires_restart,published_by,remarks)
      VALUES($1,$2,$3,$4,$5,$6,$7)
    `, [device.id, version, normalized, digest, Boolean(requiresRestart), actor, remarks || 'Published from dashboard']);
    await client.query(`UPDATE afms_devices SET configuration=$2,config_version=$3,updated_at=NOW() WHERE id=$1`, [device.id, normalized, version]);
    await client.query(`
      INSERT INTO afms_configuration_sync(device_id,running_version,latest_version,sync_status,updated_at)
      VALUES($1,0,$2,'UPDATE_AVAILABLE',NOW())
      ON CONFLICT(device_id) DO UPDATE SET latest_version=$2,
        sync_status=CASE WHEN afms_configuration_sync.running_version=$2 THEN 'CURRENT' ELSE 'UPDATE_AVAILABLE' END,updated_at=NOW()
    `, [device.id, version]);
    await client.query('COMMIT');
    return { machineId: device.machineId, version, checksum: digest, configuration: normalized, requiresRestart: Boolean(requiresRestart) };
  } catch (error) {
    await client.query('ROLLBACK');
    throw error;
  } finally { client.release(); }
}

export function createConfigurationRouter(pool, broadcast = () => {}) {
  const router = express.Router();
  const admin = requireAuth(pool, ['ADMIN']);

  router.get('/', admin, async (_req, res, next) => {
    try {
      const result = await pool.query(`
        SELECT d.machine_id AS "machineId",d.device_id AS "deviceId",d.active,
          c.configuration_version AS "latestVersion",c.checksum,c.requires_restart AS "requiresRestart",
          c.updated_by AS "updatedBy",c.updated_at AS "updatedAt",
          COALESCE(s.running_version,0) AS "runningVersion",COALESCE(s.sync_status,'NEVER_SYNCED') AS "syncStatus",
          s.last_check_at AS "lastCheckAt",s.last_download_at AS "lastDownloadAt",s.last_ack_at AS "lastAckAt",
          s.last_error AS "lastError",s.firmware_version AS "firmwareVersion",s.ip_address::text AS "ipAddress",
          s.wifi_profile AS "wifiProfile",COALESCE(s.oracle_connected,FALSE) AS "oracleConnected",
          s.last_oracle_success_at AS "lastOracleSuccessAt",s.updated_at AS "statusUpdatedAt"
        FROM afms_devices d
        LEFT JOIN afms_device_configuration c ON c.device_id=d.id
        LEFT JOIN afms_configuration_sync s ON s.device_id=d.id
        ORDER BY d.machine_id
      `);
      res.json(result.rows);
    } catch (error) { next(error); }
  });

  router.get('/:machineId', admin, async (req, res, next) => {
    try {
      const device = await pool.query(`SELECT id,machine_id AS "machineId",device_id AS "deviceId" FROM afms_devices WHERE machine_id=$1`, [req.params.machineId]);
      if (!device.rowCount) return res.status(404).json({ error: 'Machine not found' });
      const current = await currentConfiguration(pool, device.rows[0].id);
      const history = await pool.query(`
        SELECT configuration_version AS "version",checksum,requires_restart AS "requiresRestart",
          published_by AS "publishedBy",published_at AS "publishedAt",remarks
        FROM afms_configuration_history WHERE device_id=$1 ORDER BY configuration_version DESC LIMIT 100
      `, [device.rows[0].id]);
      const sync = await pool.query(`
        SELECT running_version AS "runningVersion",latest_version AS "latestVersion",sync_status AS "syncStatus",
          last_check_at AS "lastCheckAt",last_download_at AS "lastDownloadAt",last_ack_at AS "lastAckAt",
          last_error AS "lastError",firmware_version AS "firmwareVersion",ip_address::text AS "ipAddress",
          wifi_profile AS "wifiProfile",oracle_connected AS "oracleConnected",
          last_oracle_success_at AS "lastOracleSuccessAt",updated_at AS "statusUpdatedAt"
        FROM afms_configuration_sync WHERE device_id=$1
      `, [device.rows[0].id]);
      const statusHistory = await pool.query(`
        SELECT configuration_version AS "version",sync_status AS "status",success,error_text AS "error",
          firmware_version AS "firmwareVersion",wifi_profile AS "wifiProfile",ip_address::text AS "ipAddress",
          oracle_connected AS "oracleConnected",reported_at AS "reportedAt"
        FROM afms_configuration_status_history WHERE device_id=$1 ORDER BY reported_at DESC LIMIT 50
      `, [device.rows[0].id]);
      res.json({ ...current, sync: sync.rows[0] || null, history: history.rows, statusHistory: statusHistory.rows });
    } catch (error) { next(error); }
  });

  router.put('/:machineId', admin, async (req, res, next) => {
    try {
      const result = await pool.query(`SELECT id,machine_id AS "machineId" FROM afms_devices WHERE machine_id=$1`, [req.params.machineId]);
      if (!result.rowCount) return res.status(404).json({ error: 'Machine not found' });
      const published = await publishConfiguration(pool, result.rows[0], req.body.configuration ?? req.body, req.user.username, req.body.remarks, req.body.requiresRestart);
      broadcast('configuration', { type: 'PUBLISHED', ...published });
      res.json(published);
    } catch (error) {
      if (error.statusCode) return res.status(error.statusCode).json({ error: error.message });
      next(error);
    }
  });

  router.get('/:machineId/history/:version', admin, async (req, res, next) => {
    try {
      const result = await pool.query(`
        SELECT h.configuration_version AS "version",h.configuration_json AS configuration,h.checksum,
          h.requires_restart AS "requiresRestart",h.published_by AS "publishedBy",h.published_at AS "publishedAt",h.remarks
        FROM afms_configuration_history h JOIN afms_devices d ON d.id=h.device_id
        WHERE d.machine_id=$1 AND h.configuration_version=$2
      `, [req.params.machineId, Number(req.params.version)]);
      if (!result.rowCount) return res.status(404).json({ error: 'Configuration version not found' });
      res.json(result.rows[0]);
    } catch (error) { next(error); }
  });

  router.post('/:machineId/rollback/:version', admin, async (req, res, next) => {
    try {
      const device = await pool.query(`SELECT id,machine_id AS "machineId" FROM afms_devices WHERE machine_id=$1`, [req.params.machineId]);
      if (!device.rowCount) return res.status(404).json({ error: 'Machine not found' });
      const historic = await pool.query(`SELECT configuration_json,requires_restart FROM afms_configuration_history WHERE device_id=$1 AND configuration_version=$2`, [device.rows[0].id, Number(req.params.version)]);
      if (!historic.rowCount) return res.status(404).json({ error: 'Configuration version not found' });
      const published = await publishConfiguration(pool, device.rows[0], historic.rows[0].configuration_json, req.user.username, `Rollback from version ${req.params.version}`, historic.rows[0].requires_restart);
      broadcast('configuration', { type: 'ROLLED_BACK', ...published, sourceVersion: Number(req.params.version) });
      res.json(published);
    } catch (error) { next(error); }
  });

  router.post('/:machineId/clone', admin, async (req, res, next) => {
    try {
      const source = await pool.query(`SELECT id,machine_id AS "machineId" FROM afms_devices WHERE machine_id=$1`, [req.params.machineId]);
      const target = await pool.query(`SELECT id,machine_id AS "machineId" FROM afms_devices WHERE machine_id=$1`, [req.body.targetMachineId]);
      if (!source.rowCount || !target.rowCount) return res.status(404).json({ error: 'Source or target machine not found' });
      const current = await currentConfiguration(pool, source.rows[0].id);
      if (!current) return res.status(404).json({ error: 'Source configuration not found' });
      const cloned = canonical(current.configuration);
      if (cloned.machine_id) cloned.machine_id = target.rows[0].machineId;
      if (cloned.machineId) cloned.machineId = target.rows[0].machineId;
      const published = await publishConfiguration(pool, target.rows[0], cloned, req.user.username, `Cloned from ${source.rows[0].machineId}`, current.requiresRestart);
      broadcast('configuration', { type: 'CLONED', ...published, sourceMachineId: source.rows[0].machineId });
      res.json(published);
    } catch (error) { next(error); }
  });

  router.get('/device/version/current', authenticateDevice.bind(null, pool), async (req, res, next) => {
    try {
      const current = await currentConfiguration(pool, req.device.id);
      if (!current) return res.status(404).json({ error: 'Published configuration not found' });
      await pool.query(`
        INSERT INTO afms_configuration_sync(device_id,running_version,latest_version,sync_status,last_check_at,oracle_connected,last_oracle_success_at,updated_at)
        VALUES($1,0,$2,'UPDATE_AVAILABLE',NOW(),TRUE,NOW(),NOW())
        ON CONFLICT(device_id) DO UPDATE SET latest_version=$2,last_check_at=NOW(),oracle_connected=TRUE,last_oracle_success_at=NOW(),
          sync_status=CASE
            WHEN afms_configuration_sync.sync_status IN ('DOWNLOADED','PENDING_WIFI_TEST') THEN afms_configuration_sync.sync_status
            WHEN afms_configuration_sync.running_version=$2 THEN 'CURRENT'
            ELSE 'UPDATE_AVAILABLE'
          END,updated_at=NOW()
      `, [req.device.id, current.version]);
      res.json({ machineId: current.machineId, version: current.version, checksum: current.checksum, requiresRestart: current.requiresRestart, updatedAt: current.updatedAt, oracleConnected: true });
    } catch (error) { next(error); }
  });

  router.get('/device/config/current', authenticateDevice.bind(null, pool), async (req, res, next) => {
    try {
      const current = await currentConfiguration(pool, req.device.id);
      if (!current) return res.status(404).json({ error: 'Published configuration not found' });
      await markOracleSuccess(pool, req.device.id);
      const requestedVersion = Number(req.query.currentVersion || 0);
      if (requestedVersion === current.version) return res.status(304).end();
      await pool.query(`UPDATE afms_configuration_sync SET latest_version=$2,sync_status='DOWNLOADED',last_download_at=NOW(),updated_at=NOW() WHERE device_id=$1`, [req.device.id, current.version]);
      await pool.query(`
        INSERT INTO afms_configuration_status_history(device_id,configuration_version,sync_status,success,oracle_connected)
        VALUES($1,$2,'DOWNLOADED',TRUE,TRUE)
      `, [req.device.id, current.version]);
      res.json({ machineId: current.machineId, configVersion: current.version, checksum: current.checksum, requiresRestart: current.requiresRestart, updatedAt: current.updatedAt, configuration: current.configuration, oracleConnected: true });
    } catch (error) { next(error); }
  });

  router.post('/device/config/ack', authenticateDevice.bind(null, pool), async (req, res, next) => {
    try {
      const version = Math.max(0, Number(req.body.version) || 0);
      const requestedStatus = String(req.body.status || (req.body.success === false ? 'FAILED' : 'APPLIED')).toUpperCase();
      const status = deviceStatuses.has(requestedStatus) ? requestedStatus : 'FAILED';
      const success = req.body.success !== false && status !== 'FAILED';
      const applied = status === 'APPLIED' || status === 'CURRENT';
      const errorText = success ? null : String(req.body.error || `Device reported ${status}`);
      const firmwareVersion = req.body.firmwareVersion || null;
      const wifiProfile = req.body.wifiProfile || null;
      const oracleConnected = req.body.oracleConnected !== false;
      const ip = req.ip?.replace('::ffff:', '') || null;
      const client = await pool.connect();
      try {
        await client.query('BEGIN');
        await client.query(`
          INSERT INTO afms_configuration_sync(device_id,running_version,latest_version,sync_status,last_ack_at,last_error,firmware_version,ip_address,wifi_profile,oracle_connected,last_oracle_success_at,updated_at)
          VALUES($1,$2,$3,$4,NOW(),$5,$6,$7,$8,$9,CASE WHEN $9 THEN NOW() ELSE NULL END,NOW())
          ON CONFLICT(device_id) DO UPDATE SET
            running_version=CASE WHEN $10 THEN $2 ELSE afms_configuration_sync.running_version END,
            latest_version=GREATEST(afms_configuration_sync.latest_version,$3),sync_status=$4,last_ack_at=NOW(),
            last_error=$5,firmware_version=$6,ip_address=$7,wifi_profile=$8,oracle_connected=$9,
            last_oracle_success_at=CASE WHEN $9 THEN NOW() ELSE afms_configuration_sync.last_oracle_success_at END,updated_at=NOW()
        `, [req.device.id, applied ? version : 0, version, status, errorText, firmwareVersion, ip, wifiProfile, oracleConnected, applied]);
        await client.query(`
          INSERT INTO afms_configuration_status_history(
            device_id,configuration_version,sync_status,success,error_text,firmware_version,wifi_profile,ip_address,oracle_connected
          ) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9)
        `, [req.device.id, version, status, success, errorText, firmwareVersion, wifiProfile, ip, oracleConnected]);
        await client.query('COMMIT');
      } catch (error) {
        await client.query('ROLLBACK');
        throw error;
      } finally { client.release(); }
      broadcast('configuration', { type: 'ACK', machineId: req.device.machineId, version, status, success, wifiProfile, oracleConnected });
      res.json({ machineId: req.device.machineId, version, status, success, wifiProfile, oracleConnected });
    } catch (error) { next(error); }
  });

  return router;
}
