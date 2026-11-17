
import { useEffect, useState } from 'react'
import { api } from '../api'
import { Kpi, PageHeader, Status } from '../components/UI'

type Overview = {
  machine_master: { total: number; active: number }
  devices: { registered: number; online: number }
  next_phase: string
}

export default function AFMS() {
  const [overview, setOverview] = useState<Overview | null>(null)
  const [machines, setMachines] = useState<any[]>([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let active = true
    Promise.all([api('/afms/overview'), api('/afms/machines')])
      .then(([summary, rows]: any[]) => {
        if (!active) return
        setOverview(summary)
        setMachines(rows)
      })
      .catch((err: any) => { if (active) setError(err.message || 'Unable to load AFMS workspace') })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [])

  return <>
    <PageHeader title="AFMS – Machine & HMI" subtitle="New FastAPI-based AFMS workspace inside Production Review. Device connectivity and telemetry will be added in controlled phases." />
    {error && <div className="warning-box">{error}</div>}
    {loading ? <div className="panel">Loading AFMS workspace…</div> : overview && <>
      <div className="kpi-grid">
        <Kpi label="PRW machines" value={overview.machine_master.total} sub="Existing machine master"/>
        <Kpi label="Active machines" value={overview.machine_master.active}/>
        <Kpi label="Registered devices" value={overview.devices.registered} sub="Device registry not yet enabled"/>
        <Kpi label="Online devices" value={overview.devices.online} sub="MQTT connection not yet enabled"/>
      </div>
      <section className="panel">
        <div className="section-heading"><div><h2>Integration readiness</h2><p>Initial module is connected to the existing PRW machine master. No AFMS device or telemetry records have been created.</p></div><Status value="In development"/></div>
        <div className="machine-field-grid">
          <div><small>Module</small><h3>FastAPI initialized</h3></div>
          <div><small>Device connectivity</small><h3>Not connected</h3></div>
          <div><small>Telemetry ingestion</small><h3>Not connected</h3></div>
          <div><small>Next implementation phase</small><h3>{overview.next_phase}</h3></div>
        </div>
      </section>
      <section className="panel">
        <h2>Machine master reference</h2>
        <p>These are existing PRW machines. Device registration will be a separate, explicit mapping step; machines will not be assumed to have an ESP32 device.</p>
        <div className="table-wrap"><table><thead><tr><th>Machine code</th><th>Machine</th><th>Plant</th><th>Department</th><th>Type</th><th>Machine status</th><th>AFMS device</th></tr></thead>
          <tbody>{machines.map(machine => <tr key={machine.id}><td><b>{machine.code}</b></td><td>{machine.name}</td><td>{machine.plant || '—'}</td><td>{machine.department || '—'}</td><td>{machine.machine_type || '—'}</td><td><Status value={machine.is_active ? 'Active' : 'Inactive'}/></td><td><Status value="Not registered"/></td></tr>)}
          {!machines.length && <tr><td colSpan={7}>No machines are available in the PRW machine master.</td></tr>}</tbody>
        </table></div>
      </section>
    </>}
  </>
}
