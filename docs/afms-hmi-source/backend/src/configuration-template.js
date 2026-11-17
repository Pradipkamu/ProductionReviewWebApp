import express from 'express';
import { requireAuth } from './auth.js';

function serverConfigurationTemplate(machineId = '') {
  return {
    configVersion: 7,
    updatedAt: new Date().toISOString(),
    machineId: machineId || undefined,
    loss: { alarmDelaySeconds: 120 },
    uploads: { hourlyDelaySeconds: 0 },
    alarm: { activeHigh: true },
    cycleEnd: {
      enabled: false,
      activeHigh: true,
      debounceMs: 50,
      minimumMs: 50,
      timeoutSeconds: 180
    },
    shiftSchedule: {
      shifts: [
        { name: 'A', start: '08:00', end: '16:00' },
        { name: 'B', start: '16:00', end: '00:00' },
        { name: 'C', start: '00:00', end: '08:00' }
      ]
    },
    credentials: {
      googleSheets: { webAppUrl: '', apiToken: '' },
      telegram: { botToken: '', chatId: '' }
    },
    communication: {
      configSync: {
        enabled: true,
        checkOnBoot: true,
        checkOnShiftChange: true,
        periodicCheckEnabled: false,
        checkIntervalSeconds: 300,
        checkOnWifiReconnect: false
      },
      afmsWeb: {
        enabled: true,
        requireHttps: false,
        mode: 'EVENT',
        intervalSeconds: 0,
        heartbeatSeconds: 0,
        productionMilestone: 0,
        sendOnRunning: true,
        sendOnBreakdown: true,
        sendOnLossAccepted: true,
        sendOnShiftChange: true,
        includeLossDetails: true,
        includeProductionContext: true,
        includeDiagnostics: false
      },
      googleSheets: { enabled: false, uploadIntervalSeconds: 3600, sendBreakdownImmediately: true },
      telegram: { enabled: false, sendMachineReady: true, sendLossAlerts: true, sendReports: true }
    },
    policy: {
      wifiCredentialsSource: 'device.json',
      wifiFieldsForbidden: true,
      maintenanceWifiFullService: true,
      cycleEndOutputSupported: false
    }
  };
}

export function createConfigurationTemplateRouter(pool) {
  const router = express.Router();
  const admin = requireAuth(pool, ['ADMIN']);
  router.get('/server', admin, (req, res) => {
    const configuration = serverConfigurationTemplate(String(req.query.machineId || ''));
    res.setHeader('Content-Disposition', `attachment; filename="${configuration.machineId || 'server'}-server.json"`);
    res.json(configuration);
  });
  router.get('/server/:machineId', admin, async (req, res, next) => {
    try {
      const result = await pool.query('SELECT machine_id FROM afms_devices WHERE machine_id=$1', [req.params.machineId]);
      if (!result.rowCount) return res.status(404).json({ error: 'Machine not found' });
      const configuration = serverConfigurationTemplate(req.params.machineId);
      res.setHeader('Content-Disposition', `attachment; filename="${req.params.machineId}-server.json"`);
      res.json(configuration);
    } catch (error) { next(error); }
  });
  return router;
}

export { serverConfigurationTemplate };
