import React, { useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './styles.css';
import './downtime.css';

const NAV_ITEMS = [
  { label: 'Overview', view: 'Overview' },
  { label: 'Machines', view: 'Machines' },
  { label: 'Production', view: 'Production' },
  { label: 'Downtime', view: 'Downtime' },
  { label: 'OEE', view: 'OEE' },
  { label: 'Maintenance', href: '/maintenance.html' },
  { label: 'Reports', href: '/reports.html' },
  { label: 'Users', href: '/users.html' },
];
const FILTERS = ['All', 'Running', 'Attention', 'Offline'];
const CYCLE_IDLE_GRACE_MS = 10_000;
const OFFLINE_AFTER_MS = 1_800_000;
const round = (value) => Number(value || 0).toFixed(1);
const statusSlug = (status = '') => status.toLowerCase().replace(/[^a-z0-9]+/g, '-');
const statusClass = (status = '') => `status status-${statusSlug(status)}`;
const signalAgeMs = (machine, now = Date.now()) => Math.max(0, now - new Date(machine.recordedAt).getTime());
const effectiveStatus = (machine, now = Date.now()) => {
  const reported = String(machine.status || '').toUpperCase();
  const ageMs = signalAgeMs(machine, now);
  const cycleTimeMs = Math.max(0, Number(machine.cycleTimeMs) || 0);
  if (ageMs >= OFFLINE_AFTER_MS) return 'OFFLINE';
  if (reported === 'RUNNING' && cycleTimeMs > 0 && ageMs > cycleTimeMs + CYCLE_IDLE_GRACE_MS) return 'IDLE';
  return reported || 'UNKNOWN';
};
const isOffline = (machine, now = Date.now()) => effectiveStatus(machine, now) === 'OFFLINE';
const durationText = (seconds = 0) => { const s=Number(seconds)||0; const h=Math.floor(s/3600); const m=Math.floor((s%3600)/60); return h ? `${h}h ${m}m` : `${m}m`; };

function mergeMachine(current, incoming) {
  const index = current.findIndex((machine) => machine.machineId === incoming.machineId);
  if (index === -1) return [...current, incoming].sort((a, b) => a.machineId.localeCompare(b.machineId));
  const next = [...current]; next[index] = incoming; return next;
}
function mergeDowntime(current, incoming) {
  const normalized = { ...incoming, machineId: incoming.machineId || incoming.machine_id, lossCode: incoming.lossCode || incoming.loss_code, startedAt: incoming.startedAt || incoming.started_at, acknowledgedAt: incoming.acknowledgedAt || incoming.acknowledged_at, acknowledgedBy: incoming.acknowledgedBy || incoming.acknowledged_by, closedAt: incoming.closedAt || incoming.closed_at };
  const index = current.findIndex((item) => Number(item.id) === Number(normalized.id));
  if (index === -1) return [normalized, ...current];
  const next=[...current]; next[index]={...next[index],...normalized}; return next;
}
function Gauge({ label, value, target = 85 }) {
  const safe = Math.max(0, Math.min(100, Number(value) || 0));
  return <article className="oee-gauge-card"><div className="gauge" style={{ '--gauge-value': `${safe * 3.6}deg` }}><div><strong>{round(safe)}%</strong><span>{label}</span></div></div><small>Target {target}%</small></article>;
}

function Dashboard() {
  const [machines, setMachines] = useState([]);
  const [oee, setOee] = useState(null);
  const [downtime, setDowntime] = useState([]);
  const [error, setError] = useState('');
  const [activeView, setActiveView] = useState('Overview');
  const [lastUpdated, setLastUpdated] = useState(null);
  const [loading, setLoading] = useState(true);
  const [streamState, setStreamState] = useState('connecting');
  const [filter, setFilter] = useState('All');
  const [search, setSearch] = useState('');
  const [clock, setClock] = useState(Date.now());
  const [windowHours, setWindowHours] = useState(8);
  const [ackName, setAckName] = useState('Supervisor');
  const [ackNote, setAckNote] = useState('');

  async function getJson(url, options) { const response=await fetch(url, options); if(!response.ok) throw new Error(`${url} returned ${response.status}`); return response.json(); }
  async function refreshMachines() { setMachines(await getJson('/api/v1/machines/latest')); }
  async function refreshOee(hours = windowHours) { setOee(await getJson(`/api/v1/oee?windowHours=${hours}`)); }
  async function refreshDowntime() { setDowntime(await getJson('/api/v1/downtime?limit=200')); }
  async function refresh() {
    try { await Promise.all([refreshMachines(), refreshOee(), refreshDowntime()]); setLastUpdated(new Date()); setError(''); }
    catch (err) { setError(err.message); } finally { setLoading(false); }
  }
  async function acknowledge(id) {
    try { const item=await getJson(`/api/v1/downtime/${id}/acknowledge`, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({acknowledgedBy:ackName,note:ackNote||null})}); setDowntime((current)=>mergeDowntime(current,item)); setAckNote(''); }
    catch(err){ setError(err.message); }
  }
  async function closeDowntime(id) {
    try { const item=await getJson(`/api/v1/downtime/${id}/close`, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({note:ackNote||null})}); setDowntime((current)=>mergeDowntime(current,item)); }
    catch(err){ setError(err.message); }
  }

  useEffect(() => {
    refresh();
    const fallbackTimer = setInterval(refresh, 60_000);
    const clockTimer = setInterval(() => setClock(Date.now()), 10_000);
    const events = new EventSource('/api/v1/events');
    events.addEventListener('connected', () => setStreamState('live'));
    events.addEventListener('heartbeat', () => setStreamState('live'));
    events.addEventListener('telemetry', (event) => { try { setMachines((current) => mergeMachine(current, JSON.parse(event.data))); setLastUpdated(new Date()); setStreamState('live'); refreshOee(); } catch { setError('Received invalid live telemetry'); } });
    events.addEventListener('downtime', (event) => { try { setDowntime((current)=>mergeDowntime(current,JSON.parse(event.data))); } catch { setError('Received invalid downtime event'); } });
    events.onerror = () => setStreamState('reconnecting');
    return () => { clearInterval(fallbackTimer); clearInterval(clockTimer); events.close(); };
  }, []);
  useEffect(() => { refreshOee(windowHours).catch((err) => setError(err.message)); }, [windowHours]);

  const summary = useMemo(() => { const online=machines.filter((machine)=>!isOffline(machine,clock)); const running=online.filter((machine)=>effectiveStatus(machine,clock)==='RUNNING').length; return {total:machines.length,online:online.length,running,attention:online.length-running,offline:machines.length-online.length,production:machines.reduce((s,m)=>s+Number(m.productionCount||0),0),rejects:machines.reduce((s,m)=>s+Number(m.rejectCount||0),0)}; }, [machines,clock]);
  const visibleMachines = useMemo(() => { const query=search.trim().toLowerCase(); return machines.filter((machine)=>{ const status=effectiveStatus(machine,clock), offline=status==='OFFLINE'; return (filter==='All'||(filter==='Running'&&status==='RUNNING')||(filter==='Attention'&&!offline&&status!=='RUNNING')||(filter==='Offline'&&offline))&&(!query||machine.machineId.toLowerCase().includes(query)||String(machine.lossCode||'').toLowerCase().includes(query)); }); }, [machines,filter,search,clock]);
  const downtimeSummary = useMemo(() => ({open:downtime.filter(d=>d.status==='OPEN').length, acknowledged:downtime.filter(d=>d.status==='ACKNOWLEDGED').length, closed:downtime.filter(d=>d.status==='CLOSED').length, minutes:Math.round(downtime.reduce((s,d)=>s+Number(d.durationSeconds||0),0)/60)}), [downtime,clock]);
  const oeeSummary=oee?.summary||{};

  const machineView = <>
    <section className="summary-grid summary-grid-five"><article className="summary-card"><span>Total machines</span><strong>{summary.total}</strong><small>{summary.online} currently online</small></article><article className="summary-card accent-running"><span>Running</span><strong>{summary.running}</strong><small>Producing within cycle window</small></article><article className="summary-card accent-attention"><span>Needs attention</span><strong>{summary.attention}</strong><small>Idle, setup or stopped</small></article><article className="summary-card accent-offline"><span>Offline</span><strong>{summary.offline}</strong><small>No telemetry for 1800 seconds</small></article><article className="summary-card"><span>Total production</span><strong>{summary.production}</strong><small>{summary.rejects} rejects recorded</small></article></section>
    <section className="section-heading"><div><p className="eyebrow">Live floor status</p><h2>Machine dashboard</h2></div><span className={`live-badge ${streamState!=='live'?'reconnecting':''}`}><i /> {streamState==='live'?'Streaming live':'Reconnecting'}</span></section>
    <section className="machine-toolbar"><div className="filter-group">{FILTERS.map((item)=><button key={item} className={filter===item?'filter active':'filter'} onClick={()=>setFilter(item)}>{item}{item==='Offline'&&summary.offline>0?` (${summary.offline})`:''}</button>)}</div><input aria-label="Search machines" placeholder="Search machine or loss code" value={search} onChange={(e)=>setSearch(e.target.value)} /></section>
    <section className="machine-grid">{!loading&&machines.length===0&&<article className="empty-state"><div className="empty-icon">⌁</div><h2>No telemetry yet</h2><p>Waiting for an ESP8266 machine controller.</p></article>}{visibleMachines.map((machine)=>{const displayedStatus=effectiveStatus(machine,clock), good=Math.max(0,Number(machine.productionCount||0)-Number(machine.rejectCount||0)), quality=Number(machine.productionCount)>0?((good/Number(machine.productionCount))*100).toFixed(1):'100.0'; return <article className={`machine-card machine-${statusSlug(displayedStatus)}`} key={machine.machineId}><div className="machine-header"><div><p className="machine-label">Machine</p><h3>{machine.machineId}</h3></div><span className={statusClass(displayedStatus)}><i />{displayedStatus}</span></div><div className="metrics-grid"><div><span>Production</span><strong>{machine.productionCount}</strong></div><div><span>Good parts</span><strong>{good}</strong></div><div><span>Rejects</span><strong>{machine.rejectCount}</strong></div><div><span>Quality</span><strong>{quality}%</strong></div><div><span>Cycle time</span><strong>{(Number(machine.cycleTimeMs||0)/1000).toFixed(1)} s</strong></div><div><span>Signal age</span><strong>{Math.round(signalAgeMs(machine,clock)/1000)} s</strong></div></div><div className="machine-footer"><div><span>Current loss</span><strong>{machine.lossCode||'No active loss'}</strong></div><time>Updated {new Date(machine.recordedAt).toLocaleString()}</time></div></article>;})}</section>
  </>;

  return <div className="app-shell"><aside className="sidebar"><div className="brand"><div className="brand-mark">A</div><div><strong>AFMS</strong><span>Factory Intelligence</span></div></div><nav>{NAV_ITEMS.map((item)=>item.href?<a className="nav-item" key={item.label} href={item.href}><span className="nav-dot" />{item.label}</a>:<button className={activeView===item.view?'nav-item active':'nav-item'} key={item.label} onClick={()=>setActiveView(item.view)}><span className="nav-dot" />{item.label}</button>)}</nav><div className={`sidebar-footer stream-${streamState}`}><span className="system-dot" /> {streamState==='live'?'Live connection':'Reconnecting'}</div></aside>
  <main className="content"><header className="topbar"><div><p className="eyebrow">AFMS v4.0 · Commit 0032M</p><h1>{activeView}</h1><p className="subtitle">Real-time production, OEE and downtime control</p></div><div className="topbar-actions"><div className="updated">Last update<br/><strong>{lastUpdated?lastUpdated.toLocaleTimeString():'Waiting...'}</strong></div><button className="refresh-button" onClick={refresh} disabled={loading}>{loading?'Loading...':'Sync now'}</button></div></header>{error&&<div className="alert"><strong>Warning:</strong> {error}</div>}
  {activeView==='OEE'?<><section className="oee-toolbar"><div><p className="eyebrow">Current production window</p><h2>Overall Equipment Effectiveness</h2></div><label>Window<select value={windowHours} onChange={(e)=>setWindowHours(Number(e.target.value))}><option value="1">1 hour</option><option value="8">8 hours</option><option value="12">12 hours</option><option value="24">24 hours</option><option value="168">7 days</option></select></label></section><section className="oee-gauge-grid"><Gauge label="OEE" value={oeeSummary.oee}/><Gauge label="Availability" value={oeeSummary.availability} target={90}/><Gauge label="Performance" value={oeeSummary.performance} target={95}/><Gauge label="Quality" value={oeeSummary.quality} target={99}/></section><section className="oee-table-wrap"><table className="oee-table"><thead><tr><th>Machine</th><th>Availability</th><th>Performance</th><th>Quality</th><th>OEE</th></tr></thead><tbody>{(oee?.machines||[]).map(m=><tr key={m.machineId}><td><strong>{m.machineId}</strong></td><td>{round(m.availability)}%</td><td>{round(m.performance)}%</td><td>{round(m.quality)}%</td><td><span className={`oee-pill ${m.oee>=85?'good':m.oee>=60?'warning':'bad'}`}>{round(m.oee)}%</span></td></tr>)}</tbody></table></section></>
  :activeView==='Downtime'?<><section className="summary-grid"><article className="summary-card accent-attention"><span>Open losses</span><strong>{downtimeSummary.open}</strong><small>Awaiting acknowledgement</small></article><article className="summary-card"><span>Acknowledged</span><strong>{downtimeSummary.acknowledged}</strong><small>Action in progress</small></article><article className="summary-card accent-running"><span>Closed</span><strong>{downtimeSummary.closed}</strong><small>Resolved events</small></article><article className="summary-card"><span>Total downtime</span><strong>{downtimeSummary.minutes} min</strong><small>Loaded event history</small></article></section><section className="downtime-controls"><label>Acknowledged by<input value={ackName} onChange={(e)=>setAckName(e.target.value)} /></label><label>Action note<input value={ackNote} onChange={(e)=>setAckNote(e.target.value)} placeholder="Optional corrective action" /></label></section><section className="downtime-list">{downtime.map(d=><article className={`downtime-row downtime-${String(d.status).toLowerCase()}`} key={d.id}><div><span className="machine-label">{d.machineId}</span><h3>{d.lossCode}</h3><p>{d.category} · Started {new Date(d.startedAt).toLocaleString()}</p></div><div className="downtime-meta"><strong>{durationText(d.durationSeconds)}</strong><span className={statusClass(d.status)}>{d.status}</span></div><div className="downtime-actions">{d.status==='OPEN'&&<button onClick={()=>acknowledge(d.id)}>Acknowledge</button>}{d.status!=='CLOSED'&&<button className="secondary-button" onClick={()=>closeDowntime(d.id)}>Close</button>}</div>{(d.note||d.acknowledgedBy)&&<small>{d.acknowledgedBy?`By ${d.acknowledgedBy}. `:''}{d.note||''}</small>}</article>)}{!downtime.length&&<article className="empty-state"><h2>No downtime events</h2><p>Loss events will appear automatically from telemetry.</p></article>}</section></>:machineView}
  </main></div>;
}
createRoot(document.getElementById('root')).render(<Dashboard />);
