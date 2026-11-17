import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { dateIST } from '../time'
import { api } from '../api'
import { ScopeFilters, ScopeValues, appendScope } from '../components/ScopeFilters'
import { PercentTrendChart, RankedBars, ValueTrendChart } from '../components/Charts'
import { Kpi, PageHeader, num, pct } from '../components/UI'
import { MultiSelect } from '../components/MultiSelect'

function firstDaySixMonthsAgo(){
  const d=new Date(dateIST()+'T00:00:00')
  d.setMonth(d.getMonth()-5,1)
  return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-01`
}
function csvCell(v:any){const s=String(v??'');return `"${s.replaceAll('"','""')}"`}
function downloadCsv(name:string,rows:any[]){
  if(!rows.length){window.alert('There are no rows to export for the selected filters.');return}
  const keys=Object.keys(rows[0])
  const csv=[keys.map(csvCell).join(','),...rows.map(r=>keys.map(k=>csvCell(r[k])).join(','))].join('\r\n')
  const blob=new Blob([csv],{type:'text/csv;charset=utf-8'})
  const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=name;a.click();URL.revokeObjectURL(url)
}

export default function OEEReports(){
  const [fromDate,setFromDate]=useState(firstDaySixMonthsAgo)
  const [toDate,setToDate]=useState(dateIST())
  const [scope,setScope]=useState<ScopeValues>({plant:[],productGroup:[],customerId:[],productId:[]})
  const [options,setOptions]=useState<any>({plants:[],product_groups:[],customers:[]})
  const [products,setProducts]=useState<any[]>([])
  const [machines,setMachines]=useState<any[]>([])
  const [operators,setOperators]=useState<any[]>([])
  const [machineId,setMachineId]=useState<string[]>([])
  const [operatorId,setOperatorId]=useState('')
  const [shift,setShift]=useState('')
  const [data,setData]=useState<any>(null)
  const [loss,setLoss]=useState<any>(null)
  const [busy,setBusy]=useState(false)
  const [error,setError]=useState('')

  useEffect(()=>{
    let active=true
    Promise.all([api('/masters/filter-options'),api('/masters/products'),api('/masters/machines'),api('/personnel')])
      .then(([o,p,m,people]:any[])=>{if(active){setOptions(o);setProducts(p);setMachines(m);setOperators(people)}})
      .catch((e:any)=>{if(active)setError(e.message)})
    return()=>{active=false}
  },[])

  const selectedMachineNames=useMemo(()=>machines.filter(m=>machineId.includes(String(m.id))).map(m=>m.name),[machines,machineId])

  useEffect(()=>{
    if(!fromDate||!toDate||fromDate>toDate){setError('From date must be on or before To date.');setData(null);setLoss(null);return}
    let active=true
    setBusy(true);setError('')
    const q=new URLSearchParams({as_of:toDate,from_date:fromDate,months:'24'})
    appendScope(q,scope)
    if(machineId.length)q.set('machine_id',machineId.join(','))
    if(operatorId)q.set('operator_id',operatorId)
    if(shift)q.set('shift',shift)
    Promise.all([api(`/reports/oee-trends?${q}`),api(`/reports/loss-pareto?${q}`)])
      .then(([a,b]:any[])=>{if(active){setData(a);setLoss(b)}})
      .catch((e:any)=>{if(active)setError(e.message)})
      .finally(()=>{if(active)setBusy(false)})
    return()=>{active=false}
  },[fromDate,toDate,scope.plant,scope.productGroup,scope.customerId,scope.productId,machineId,operatorId,shift])

  const summary=data?.summary||{}
  const filteredEntries=data?.entries||[]
  const selectedMachineLabel=selectedMachineNames.join(', ')
  const machineOptions=machines.map(m=>({value:String(m.id),label:`${m.code} — ${m.name}`}))
  const pageActions=<div className="export-row"><label>From <input aria-label="From date" type="date" value={fromDate} max={toDate} onChange={e=>setFromDate(e.target.value)}/></label><label>To <input aria-label="To date" type="date" value={toDate} min={fromDate} onChange={e=>setToDate(e.target.value)}/></label><button className="secondary" onClick={()=>window.print()}>Print / Save PDF</button></div>

  function pickMachine(row:any){
    const name=String(row?.name||row?.machine||'').trim().toLowerCase()
    const machine=machines.find(m=>String(m.code).trim().toLowerCase()===name||String(m.name).trim().toLowerCase()===name)
    if(machine)setMachineId(old=>old.length===1&&old[0]===String(machine.id)?[]:[String(machine.id)])
  }

  return <>
    <PageHeader title="OEE Reports" subtitle="Machine, product, shift and operator performance with availability, performance, quality and loss analysis." actions={pageActions}/>
    <ScopeFilters value={scope} onChange={setScope} options={options} products={products}/>
    <div className="filters">
      <MultiSelect value={machineId} onChange={setMachineId} placeholder="All Machines" options={machineOptions}/>
      <label className="inline-filter">Shift <select value={shift} onChange={e=>setShift(e.target.value)}><option value="">All Shifts</option><option value="A">A</option><option value="B">B</option><option value="C">C</option></select></label>
      <label className="inline-filter">Operator <select value={operatorId} onChange={e=>setOperatorId(e.target.value)}><option value="">All Operators</option>{operators.map(p=><option key={p.id} value={p.id}>{p.full_name}</option>)}</select></label>
      <button className="secondary" onClick={()=>downloadCsv('oee_shift_details.csv',filteredEntries)}>Export OEE CSV</button>
      <button className="secondary" onClick={()=>downloadCsv('oee_loss_details.csv',loss?.events||[])}>Export Loss CSV</button>
    </div>
    {selectedMachineLabel&&<div className="filter-summary"><button className="filter-chip removable" onClick={()=>setMachineId([])}>Machine: {selectedMachineLabel} ×</button></div>}
    {error&&<div className="error" role="alert">{error}</div>}
    {busy&&<div className="notice">Refreshing OEE report…</div>}
    <div className="kpi-grid">
      <Kpi label="OEE" value={pct(summary.oee)} tone={(summary.oee||0)<.6?'bad':(summary.oee||0)<.75?'warn':'good'}/>
      <Kpi label="Availability" value={pct(summary.availability)}/>
      <Kpi label="Performance" value={pct(summary.performance_raw)} tone={summary.performance_master_warning?'warn':'neutral'}/>
      <Kpi label="Quality" value={pct(summary.quality)}/>
      <Kpi label="Downtime" value={`${num(summary.downtime_min||0)} min`}/>
      <Kpi label="Loss Hours" value={`${num(loss?.summary?.loss_hours||0)} h`} tone={(loss?.summary?.loss_hours||0)>0?'warn':'good'}/>
    </div>
    <section className="panel report-panel"><div className="panel-title"><div><h2>OEE / Availability / Performance / Quality Trend</h2><p>Daily trend for the selected date range and filters.</p></div></div><PercentTrendChart rows={data?.daily||[]} series={[{key:'oee',label:'OEE'},{key:'availability',label:'Availability'},{key:'performance',label:'Performance'},{key:'quality',label:'Quality'}]} target={85}/></section>
    <section className="panel"><div className="panel-title"><h2>Machine-wise OEE</h2><span>Click a machine to filter</span></div><RankedBars rows={(data?.machines||[]).map((r:any)=>({...r,oeePct:(r.oee||0)*100,sub:`${r.open_actions||0} open actions • ${r.overdue_actions||0} overdue`}))} valueKey="oeePct" suffix="%" onSelect={pickMachine} selectedName={selectedMachineNames.length===1?selectedMachineNames[0]:undefined}/></section>
    <div className="advanced-grid"><section className="panel"><h2>Loss Pareto</h2><RankedBars rows={loss?.pareto||[]} valueKey="minutes" suffix=" min"/></section><section className="panel"><div className="panel-title"><h2>Machine Loss Hours</h2><span>Click a machine to filter</span></div><RankedBars rows={loss?.machines||[]} valueKey="hours" suffix=" h" onSelect={pickMachine} selectedName={selectedMachineNames.length===1?selectedMachineNames[0]:undefined}/></section></div>
    <section className="panel report-panel"><h2>Monthly Loss Hours Trend</h2><ValueTrendChart rows={loss?.monthly||[]} keyName="hours" label="Loss hours" suffix=" h"/></section>
    <section className="panel"><div className="panel-title"><div><h2>Machine Shift OEE Details</h2><p>Raw performance above 110% flags a cycle-time or quantity master check.</p></div></div><div className="table-wrap"><table><thead><tr><th>Date</th><th>Shift</th><th>Machine</th><th>Product / Operation</th><th>Operator</th><th>Run / Planned</th><th>Total / Good / Reject</th><th>A</th><th>P</th><th>Q</th><th>OEE</th></tr></thead><tbody>{filteredEntries.map((r:any)=><tr key={r.id}><td>{r.date}</td><td>{r.shift}</td><td><b>{r.machine}</b></td><td>{r.product}<br/><small>{r.operation}</small></td><td>{r.operator||'—'}</td><td>{num(r.run_min)} / {num(r.planned_min)} min</td><td>{num(r.total_count)} / {num(r.good_count)} / {num(r.reject_count)}</td><td>{pct(r.availability)}</td><td className={r.performance_master_warning?'neg':''}>{pct(r.performance_raw)}</td><td>{pct(r.quality)}</td><td><b>{pct(r.oee)}</b></td></tr>)}{!filteredEntries.length&&<tr><td colSpan={11} className="muted">No OEE shift entries in this date range and filter scope.</td></tr>}</tbody></table></div></section>
    <section className="panel"><div className="panel-title"><div><h2>Machine Loss Details and Action Linkage</h2><p>Loss records are linked to their action plans where an action has been raised.</p></div><Link to="/actions">Open action register</Link></div><div className="table-wrap"><table><thead><tr><th>Date</th><th>Shift</th><th>Machine</th><th>Product / Operation</th><th>Loss</th><th>Component</th><th>Minutes</th><th>Remark</th><th>Action</th></tr></thead><tbody>{(loss?.events||[]).map((r:any)=><tr key={r.id}><td>{r.date}</td><td>{r.shift}</td><td><b>{r.machine}</b></td><td>{r.product||'—'}<br/><small>{r.operation||'—'}</small></td><td>{r.category}</td><td>{r.component}</td><td>{num(r.duration_min)}</td><td>{r.remark||'—'}</td><td>{r.action_no?<Link to="/actions">{r.action_no} · {r.action_status}</Link>:<span className="status watch">Action pending</span>}</td></tr>)}{!(loss?.events||[]).length&&<tr><td colSpan={9} className="muted">No loss events in this date range and filter scope.</td></tr>}</tbody></table></div></section>
  </>
}
