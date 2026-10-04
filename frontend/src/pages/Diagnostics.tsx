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
    <PageHeader title="System Diagnostics" subtitle="Application, database, storage, backup integrity, restore verification, upload controls and secret/network hardening." actions={<button onClick={load} disabled={busy}>{busy?'Checking…':'Run checks'}</button>}/>
    {error&&<div className="error">{error}</div>}
    {!data&&!error&&<div className="empty">Running diagnostics…</div>}
    {data&&<>
      <div className="kpi-grid">
        <Kpi label="Overall" value={data.status.toUpperCase()} tone={data.status==='ok'?'good':data.status==='warning'?'warn':'bad'} sub={`Checked ${stamp(data.checked_at)}`}/>
        <Kpi label="Web UI" value="OK" tone="good" sub={`v${__APP_VERSION__} bundle loaded`}/>
        <Kpi label="Backend" value={data.backend.status.toUpperCase()} tone={data.backend.status==='ok'?'good':'bad'} sub={`v${data.backend.version} • ${data.backend.environment}`}/>
        <Kpi label="Database" value={data.database.status.toUpperCase()} tone={data.database.status==='ok'?'good':'bad'} sub={`${data.database.dialect} • ${data.database.latency_ms??'—'} ms`}/>
      </div>

      <section className="panel"><div className="panel-title"><div><h2>Backup & Restore Readiness</h2><p>Backups are now checked for freshness and SHA-256 integrity. Restore verification is recorded only after an isolated test restore succeeds.</p></div></div>
        <div className="table-wrap"><table><thead><tr><th>Check</th><th>Status</th><th>Version / File</th><th>Details</th></tr></thead><tbody>
          <tr><td>Database connection</td><td><Status value={data.database.status}/></td><td>{data.database.schema_version||'—'}</td><td>{data.database.detail||`${data.database.latency_ms} ms response`}</td></tr>
          <tr><td>Latest backup</td><td><Status value={data.backup.status}/></td><td>{data.backup.file_name||'—'}</td><td>{data.backup.detail}{data.backup.modified_at?` • ${stamp(data.backup.modified_at)} • ${(data.backup.size_bytes/1024/1024).toFixed(1)} MB • ${data.backup.format||''}`:''}{data.backup.count!=null?` • ${data.backup.count} backup(s)`:''}</td></tr>
          <tr><td>Isolated restore verification</td><td><Status value={data.restore_verification.status}/></td><td>{data.restore_verification.backup_file||'—'}</td><td>{data.restore_verification.detail}{data.restore_verification.verified_at?` • ${stamp(data.restore_verification.verified_at)} • schema ${data.restore_verification.schema_version||'—'}`:''}</td></tr>
        </tbody></table></div>
      </section>

      <section className="panel"><div className="panel-title"><div><h2>Security Configuration</h2><p>No secret values are displayed. This checks credential strength indicators and whether database/backend ports remain localhost-only.</p></div><Status value={data.security.status}/></div>
        <div className="table-wrap"><table><thead><tr><th>Control</th><th>Status</th><th>Detail</th></tr></thead><tbody>
          {data.security.checks.map((row:any)=><tr key={row.name}><td><b>{row.name}</b></td><td><Status value={row.status}/></td><td>{row.detail}</td></tr>)}
        </tbody></table></div>
      </section>

      <section className="panel"><div className="panel-title"><div><h2>Upload Protection</h2><p>Unsafe executable/web content is not accepted as Action evidence, and Excel imports must pass Office package validation before preview.</p></div><Status value={data.uploads.status}/></div>
        <div className="table-wrap"><table><tbody>
          <tr><th>Workbook upload limit</th><td>{data.uploads.import_max_mb} MB</td></tr>
          <tr><th>Action attachment limit</th><td>{data.uploads.attachment_max_mb} MB</td></tr>
          <tr><th>Office expanded-size limit</th><td>{data.uploads.office_max_uncompressed_mb} MB</td></tr>
          <tr><th>Allowed evidence types</th><td>{data.uploads.allowed_attachment_extensions.join(', ')}</td></tr>
          <tr><th>Validation</th><td>{data.uploads.detail}</td></tr>
        </tbody></table></div>
      </section>

      <section className="panel"><h2>Persistent Storage</h2><div className="table-wrap"><table><thead><tr><th>Area</th><th>Status</th><th>Available</th><th>Total</th><th>Writable</th></tr></thead><tbody>
        {data.storage.map((row:any)=><tr key={row.name}><td><b>{row.name}</b></td><td><Status value={row.status}/></td><td>{bytes(row.free_bytes)}</td><td>{bytes(row.total_bytes)}</td><td>{row.writable?'Yes':'No'}</td></tr>)}
      </tbody></table></div></section>
    </>}
  </>
}
