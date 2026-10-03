import { useEffect, useState } from 'react'
import { api } from '../api'
import { Kpi, PageHeader, Status } from '../components/UI'

const bytes = (value?: number) => value == null ? '—' : `${(value / 1024 / 1024 / 1024).toFixed(1)} GB`
const stamp = (value?: string) => value ? new Date(value).toLocaleString('en-IN') : '—'

export default function Diagnostics(){
  const [data,setData]=useState<any>(null); const [error,setError]=useState(''); const [busy,setBusy]=useState(false)
  async function load(){setBusy(true);setError('');try{setData(await api('/diagnostics'))}catch(e:any){setError(e.message)}finally{setBusy(false)}}
  useEffect(()=>{load()},[])
  return <>
    <PageHeader title="System Diagnostics" subtitle="One-place status for the web app, database, storage, backup and installed build." actions={<button onClick={load} disabled={busy}>{busy?'Checking…':'Run checks'}</button>}/>
    {error&&<div className="error">{error}</div>}
    {!data&&!error&&<div className="empty">Running diagnostics…</div>}
    {data&&<>
      <div className="kpi-grid">
        <Kpi label="Overall" value={data.status.toUpperCase()} tone={data.status==='ok'?'good':data.status==='warning'?'warn':'bad'} sub={`Checked ${stamp(data.checked_at)}`}/>
        <Kpi label="Web UI" value="OK" tone="good" sub={`v${__APP_VERSION__} bundle loaded`}/>
        <Kpi label="Backend" value={data.backend.status.toUpperCase()} tone={data.backend.status==='ok'?'good':'bad'} sub={`v${data.backend.version} • ${data.backend.environment}`}/>
        <Kpi label="Database" value={data.database.status.toUpperCase()} tone={data.database.status==='ok'?'good':'bad'} sub={`${data.database.dialect} • ${data.database.latency_ms??'—'} ms`}/>
      </div>
      <section className="panel"><div className="panel-title"><div><h2>Database and backup</h2><p>The restore-verification script performs the deeper isolated restore test.</p></div></div>
        <div className="table-wrap"><table><thead><tr><th>Check</th><th>Status</th><th>Version / File</th><th>Details</th></tr></thead><tbody>
          <tr><td>Database connection</td><td><Status value={data.database.status}/></td><td>{data.database.schema_version||'—'}</td><td>{data.database.detail||`${data.database.latency_ms} ms response`}</td></tr>
          <tr><td>Latest backup</td><td><Status value={data.backup.status}/></td><td>{data.backup.file_name||'—'}</td><td>{data.backup.detail}{data.backup.modified_at?` • ${stamp(data.backup.modified_at)} • ${(data.backup.size_bytes/1024/1024).toFixed(1)} MB`:''}</td></tr>
        </tbody></table></div>
      </section>
      <section className="panel"><h2>Persistent storage</h2><div className="table-wrap"><table><thead><tr><th>Area</th><th>Status</th><th>Available</th><th>Total</th><th>Writable</th></tr></thead><tbody>
        {data.storage.map((row:any)=><tr key={row.name}><td><b>{row.name}</b></td><td><Status value={row.status}/></td><td>{bytes(row.free_bytes)}</td><td>{bytes(row.total_bytes)}</td><td>{row.writable?'Yes':'No'}</td></tr>)}
      </tbody></table></div></section>
    </>}
  </>
}
