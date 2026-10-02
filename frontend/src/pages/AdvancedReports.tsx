import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { ScopeFilters, ScopeValues, appendScope } from '../components/ScopeFilters'
import { ComplianceLineChart, NamedComplianceBars, PercentTrendChart, PlanActualChart, ProcessFunnelChart, RankedBars, ValueTrendChart } from '../components/Charts'
import { Kpi, PageHeader, money, num, pct } from '../components/UI'
import { MultiSelect } from '../components/MultiSelect'

function today(){return new Date().toISOString().slice(0,10)}
function csvCell(v:any){const s=String(v??'');return `"${s.replaceAll('"','""')}"`}
function downloadCsv(name:string, rows:any[]){if(!rows.length)return;const keys=Object.keys(rows[0]);const csv=[keys.map(csvCell).join(','),...rows.map(r=>keys.map(k=>csvCell(r[k])).join(','))].join('\r\n');const blob=new Blob([csv],{type:'text/csv;charset=utf-8'});const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=name;a.click();URL.revokeObjectURL(a.href)}

type Tab='process'|'vendor'|'oee'|'actions'|'schedule'|'forecast'

export default function AdvancedReports(){
  const [tab,setTab]=useState<Tab>('process')
  const [asOf,setAsOf]=useState(today())
  const [scope,setScope]=useState<ScopeValues>({plant:[],productGroup:[],customerId:[],productId:[]})
  const [options,setOptions]=useState<any>({plants:[],product_groups:[],customers:[]})
  const [products,setProducts]=useState<any[]>([]);const [machines,setMachines]=useState<any[]>([]);const [vendors,setVendors]=useState<any[]>([])
  const [machineId,setMachineId]=useState<string[]>([]); const [vendorId,setVendorId]=useState<string[]>([])
  const [process,setProcess]=useState<any>(null);const [funnel,setFunnel]=useState<any>(null);const [vendor,setVendor]=useState<any>(null);const [oee,setOee]=useState<any>(null);const [loss,setLoss]=useState<any>(null);const [actions,setActions]=useState<any>(null);const [schedule,setSchedule]=useState<any>(null);const [forecast,setForecast]=useState<any>(null)
  const [busy,setBusy]=useState(false);const [err,setErr]=useState('')
  useEffect(()=>{api('/masters/filter-options').then(setOptions);api('/masters/products').then(setProducts);api('/masters/machines').then(setMachines);api('/masters/vendors').then(setVendors)},[])
  const selectedProduct=useMemo(()=>scope.productId.length===1?products.find(p=>String(p.id)===scope.productId[0]):null,[products,scope.productId])

  function scopeQs(base:URLSearchParams){appendScope(base,scope);return base}
  async function load(){setBusy(true);setErr('');try{
    if(tab==='process'){
      const q=scopeQs(new URLSearchParams({as_of:asOf}));setProcess(await api(`/reports/process-compliance?${q}`));
      if(scope.productId.length===1)setFunnel(await api(`/reports/process-funnel?report_date=${asOf}&product_id=${scope.productId[0]}`));else setFunnel(null)
    }else if(tab==='vendor'){
      const q=scopeQs(new URLSearchParams({as_of:asOf,months:'12'}));if(vendorId.length)q.set('vendor_id',vendorId.join(','));setVendor(await api(`/reports/vendor-performance?${q}`))
    }else if(tab==='oee'){
      const q=scopeQs(new URLSearchParams({as_of:asOf,months:'6'}));if(machineId.length)q.set('machine_id',machineId.join(','));const [a,b]=await Promise.all([api(`/reports/oee-trends?${q}`),api(`/reports/loss-pareto?${q}`)]);setOee(a);setLoss(b)
    }else if(tab==='actions'){
      const q=scopeQs(new URLSearchParams({as_of:asOf,months:'12'}));setActions(await api(`/reports/action-performance?${q}`))
    }else if(tab==='schedule'){
      const q=scopeQs(new URLSearchParams({as_of:asOf,months:'12'}));setSchedule(await api(`/reports/schedule-impact?${q}`))
    }else if(tab==='forecast'){
      const q=scopeQs(new URLSearchParams({as_of:asOf}));setForecast(await api(`/reports/month-end-forecast?${q}`))
    }
  }catch(e:any){setErr(e.message)}finally{setBusy(false)}}
  useEffect(()=>{load()},[tab,asOf,scope.plant,scope.productGroup,scope.customerId,scope.productId,machineId,vendorId])

  const pageActions=<div className="export-row"><input type="date" value={asOf} onChange={e=>setAsOf(e.target.value)}/><button className="secondary" onClick={()=>window.print()}>Print / Save PDF</button></div>
  return <><PageHeader title="Management Reports" subtitle="Process, vendor, OEE/loss, action effectiveness, schedule impact and month-end risk." actions={pageActions}/>
    <ScopeFilters value={scope} onChange={setScope} options={options} products={products}/>
    <div className="report-tabs">
      {([['process','Process & WIP'],['vendor','Vendor'],['oee','OEE & Loss'],['actions','Actions'],['schedule','Schedule Impact'],['forecast','Forecast']] as [Tab,string][]).map(([k,l])=><button key={k} className={tab===k?'active':''} onClick={()=>setTab(k)}>{l}</button>)}
    </div>
    {err&&<div className="error">{err}</div>}{busy&&<div className="notice">Refreshing report…</div>}
    {tab==='process'&&<ProcessReport data={process} funnel={funnel} product={selectedProduct} onExport={()=>downloadCsv('process_compliance.csv',process?.details||[])}/>} 
    {tab==='vendor'&&<VendorReport data={vendor} vendors={vendors} vendorId={vendorId} setVendorId={setVendorId} onExport={()=>downloadCsv('vendor_performance.csv',vendor?.movements||[])}/>} 
    {tab==='oee'&&<OeeReport data={oee} loss={loss} machines={machines} machineId={machineId} setMachineId={setMachineId} onExport={()=>downloadCsv('oee_shift_details.csv',oee?.entries||[])}/>}
    {tab==='actions'&&<ActionReport data={actions} onExport={()=>downloadCsv('action_owner_aging.csv',actions?.owners||[])}/>} 
    {tab==='schedule'&&<ScheduleImpact data={schedule} onExport={()=>downloadCsv('schedule_revisions.csv',schedule?.revisions||[])}/>} 
    {tab==='forecast'&&<ForecastReport data={forecast} onExport={()=>downloadCsv('month_end_forecast.csv',forecast?.products||[])}/>} 
  </>
}

function ProcessReport({data,funnel,product,onExport}:{data:any,funnel:any,product:any,onExport:()=>void}){
  return <><div className="export-row"><button className="secondary" onClick={onExport}>Export CSV (Excel)</button></div>
    <section className="panel report-panel"><div className="panel-title"><div><h2>Operation Compliance — Daily</h2><p>Revised operation requirement vs actual.</p></div><span>Current report range</span></div><PlanActualChart rows={data?.daily||[]} metric="qty"/><ComplianceLineChart rows={data?.daily||[]}/></section>
    <section className="panel report-panel"><div className="panel-title"><div><h2>Operation Compliance — Weekly</h2><p>Weekly process execution trend.</p></div></div><PlanActualChart rows={data?.weekly||[]} metric="qty"/><ComplianceLineChart rows={data?.weekly||[]}/></section>
    <section className="panel report-panel"><div className="panel-title"><div><h2>Operation Compliance — Monthly</h2><p>Month-over-month operation compliance.</p></div></div><PlanActualChart rows={data?.monthly||[]} metric="qty"/><ComplianceLineChart rows={data?.monthly||[]}/></section>
    <section className="panel"><div className="panel-title"><div><h2>Operation Comparison</h2><p>Current month bottleneck view across selected scope.</p></div></div><NamedComplianceBars rows={data?.operations||[]} metric="qty"/></section>
    <section className="panel"><div className="panel-title"><div><h2>Process Funnel / WIP</h2><p>{product?`${product.name} • operation-by-operation flow`:'Select a single part to see its route funnel and WIP.'}</p></div></div><ProcessFunnelChart rows={funnel?.operations||[]}/></section>
  </>
}

function VendorReport({data,vendors,vendorId,setVendorId,onExport}:{data:any,vendors:any[],vendorId:string[],setVendorId:(x:string[])=>void,onExport:()=>void}){
  const s=data?.summary||{}
  const monthly=(data?.monthly||[]).map((r:any)=>({label:r.label,plan:r.sent,actual:r.received,gap:r.received-r.sent,compliance:r.compliance}))
  return <><div className="filters"><MultiSelect value={vendorId} onChange={setVendorId} placeholder="All Vendors" options={vendors.map(v=>({value:String(v.id),label:v.name}))}/><button className="secondary" onClick={onExport}>Export CSV (Excel)</button></div>
    <div className="kpi-grid"><Kpi label="Sent" value={num(s.sent||0)}/><Kpi label="Received" value={num(s.received||0)} tone="good"/><Kpi label="Pending" value={num(s.pending||0)} tone={(s.pending||0)>0?'warn':'good'}/><Kpi label="Receipt Compliance" value={pct(s.receipt_compliance)} /><Kpi label="Overdue Movements" value={s.overdue_movements||0} tone={(s.overdue_movements||0)>0?'bad':'good'}/></div>
    <section className="panel"><h2>Vendor Receipt Compliance</h2><NamedComplianceBars rows={data?.vendors||[]} metric="qty"/></section>
    <section className="panel report-panel"><h2>Monthly Sent vs Received</h2><PlanActualChart rows={monthly} metric="qty"/><PercentTrendChart rows={data?.monthly||[]} series={[{key:'compliance',label:'Receipt compliance'},{key:'on_time_ratio',label:'On-time return'}]} target={100}/></section>
    <section className="panel"><h2>Vendor Aging / Pending</h2><RankedBars rows={(data?.vendors||[]).map((r:any)=>({...r,sub:`${r.overdue_count} overdue • Avg ${r.average_age_days}d`}))} valueKey="pending" valueLabel="Pending" suffix=" pcs"/></section>
  </>
}

function OeeReport({data,loss,machines,machineId,setMachineId,onExport}:{data:any,loss:any,machines:any[],machineId:string[],setMachineId:(x:string[])=>void,onExport:()=>void}){
  const s=data?.summary||{}
  const selectedMachineNames=machines.filter((m:any)=>machineId.includes(String(m.id))).map((m:any)=>m.name)
  function pickMachine(row:any){
    const name=String(row?.name||row?.machine||'').trim().toLowerCase()
    const machine=machines.find((m:any)=>{
      const full=`${m.code} — ${m.name}`.trim().toLowerCase()
      return String(m.name).trim().toLowerCase()===name||String(m.code).trim().toLowerCase()===name||full===name
    })
    if(!machine)return
    const id=String(machine.id)
    setMachineId(machineId.length===1&&machineId[0]===id?[]:[id])
  }
  return <><div className="filters"><MultiSelect value={machineId} onChange={setMachineId} placeholder="All Machines" options={machines.map(m=>({value:String(m.id),label:`${m.code} — ${m.name}`}))}/><button className="secondary" onClick={onExport}>Export CSV (Excel)</button></div>
    {selectedMachineNames.length>0&&<div className="filter-summary">{selectedMachineNames.map((name:string)=><button key={name} className="filter-chip removable" onClick={()=>setMachineId([])}>Machine: {name} ×</button>)}</div>}
    <div className="kpi-grid"><Kpi label="OEE" value={pct(s.oee)} tone={(s.oee||0)<.6?'bad':(s.oee||0)<.75?'warn':'good'}/><Kpi label="Availability" value={pct(s.availability)}/><Kpi label="Performance" value={pct(s.performance_raw)} tone={s.performance_master_warning?'warn':'neutral'}/><Kpi label="Quality" value={pct(s.quality)}/><Kpi label="Downtime" value={`${num(s.downtime_min||0)} min`}/><Kpi label="Loss Hours" value={`${num(loss?.summary?.loss_hours||0)} h`} tone={(loss?.summary?.loss_hours||0)>0?'warn':'good'}/></div>
    <section className="panel report-panel"><h2>OEE / A / P / Q Daily Trend</h2><PercentTrendChart rows={data?.daily||[]} series={[{key:'oee',label:'OEE'},{key:'availability',label:'Availability'},{key:'performance',label:'Performance'},{key:'quality',label:'Quality'}]} target={85}/></section>
    <section className="panel"><div className="panel-title"><h2>Machine-wise OEE</h2><span>Click a machine to filter</span></div><RankedBars rows={(data?.machines||[]).map((r:any)=>({...r,oeePct:(r.oee||0)*100,sub:`${r.open_actions||0} open actions • ${r.overdue_actions||0} overdue`}))} valueKey="oeePct" suffix="%" onSelect={pickMachine} selectedName={selectedMachineNames.length===1?selectedMachineNames[0]:undefined}/></section>
    <div className="advanced-grid"><section className="panel"><h2>Loss Pareto</h2><RankedBars rows={loss?.pareto||[]} valueKey="minutes" suffix=" min"/></section><section className="panel"><div className="panel-title"><h2>Machine Loss Hours</h2><span>Click a machine to filter</span></div><RankedBars rows={loss?.machines||[]} valueKey="hours" suffix=" h" onSelect={pickMachine} selectedName={selectedMachineNames.length===1?selectedMachineNames[0]:undefined}/></section></div>
    <section className="panel report-panel"><h2>Monthly Loss Hours Trend</h2><ValueTrendChart rows={loss?.monthly||[]} keyName="hours" label="Loss hours" suffix=" h"/></section>
    <section className="panel"><div className="panel-title"><div><h2>Machine shift OEE details</h2><p>Exact records behind the trend; raw performance above 110% flags a cycle-time or quantity master check.</p></div></div><div className="table-wrap"><table><thead><tr><th>Date</th><th>Shift</th><th>Machine</th><th>Product / Operation</th><th>Run / Planned</th><th>Total / Good / Reject</th><th>A</th><th>P</th><th>Q</th><th>OEE</th></tr></thead><tbody>{(data?.entries||[]).map((r:any)=><tr key={r.id}><td>{r.date}</td><td>{r.shift}</td><td><b>{r.machine}</b></td><td>{r.product}<br/><small>{r.operation}</small></td><td>{num(r.run_min)} / {num(r.planned_min)} min</td><td>{num(r.total_count)} / {num(r.good_count)} / {num(r.reject_count)}</td><td>{pct(r.availability)}</td><td className={r.performance_master_warning?'neg':''}>{pct(r.performance_raw)}</td><td>{pct(r.quality)}</td><td><b>{pct(r.oee)}</b></td></tr>)}{!data?.entries?.length&&<tr><td colSpan={10} className="muted">No OEE shift entries in this range.</td></tr>}</tbody></table></div></section>
    <section className="panel"><div className="panel-title"><div><h2>Machine loss details and action linkage</h2><p>Loss Pareto totals can be traced to the original event and its action plan.</p></div><Link to="/actions">Open action register</Link></div><div className="table-wrap"><table><thead><tr><th>Date</th><th>Shift</th><th>Machine</th><th>Product / Operation</th><th>Loss</th><th>Component</th><th>Minutes</th><th>Remark</th><th>Action</th></tr></thead><tbody>{(loss?.events||[]).map((r:any)=><tr key={r.id}><td>{r.date}</td><td>{r.shift}</td><td><b>{r.machine}</b></td><td>{r.product||'—'}<br/><small>{r.operation||'—'}</small></td><td>{r.category}</td><td>{r.component}</td><td>{num(r.duration_min)}</td><td>{r.remark||'—'}</td><td>{r.action_no?<Link to="/actions">{r.action_no} · {r.action_status}</Link>:<span className="status watch">Action pending</span>}</td></tr>)}{!loss?.events?.length&&<tr><td colSpan={9} className="muted">No loss events in this range.</td></tr>}</tbody></table></div></section>
  </>
}

function ActionReport({data,onExport}:{data:any,onExport:()=>void}){
  const s=data?.summary||{}; const monthly=(data?.monthly||[]).map((r:any)=>({label:r.label,plan:r.raised,actual:r.closed,gap:r.closed-r.raised,compliance:r.closure_compliance}))
  return <><div className="export-row"><button className="secondary" onClick={onExport}>Export CSV (Excel)</button></div><div className="kpi-grid"><Kpi label="Actions Raised" value={s.raised||0}/><Kpi label="Closed" value={s.closed||0} tone="good"/><Kpi label="Open" value={s.open||0} tone={(s.open||0)>0?'warn':'good'}/><Kpi label="Overdue" value={s.overdue||0} tone={(s.overdue||0)>0?'bad':'good'}/><Kpi label="Closure Compliance" value={pct(s.closure_compliance)}/><Kpi label="Closed On Time" value={s.on_time_closed||0}/></div>
    <section className="panel report-panel"><h2>Monthly Action Closure Compliance</h2><PlanActualChart rows={monthly} metric="qty"/><ComplianceLineChart rows={monthly}/></section>
    <div className="advanced-grid"><section className="panel"><h2>Owner-wise Open Action Aging</h2><RankedBars rows={(data?.owners||[]).map((r:any)=>({...r,sub:`${r.open} open • ${r.overdue} overdue • Avg ${r.average_age_days}d`}))} valueKey="max_age" suffix=" d"/></section><section className="panel"><h2>Recurring Problem Pareto</h2><RankedBars rows={data?.categories||[]} valueKey="count" suffix=" actions"/></section></div>
    <section className="panel"><div className="table-wrap"><table><thead><tr><th>Owner</th><th>Open</th><th>Closed</th><th>Overdue</th><th>Avg Age</th><th>Max Age</th></tr></thead><tbody>{(data?.owners||[]).map((r:any)=><tr key={r.name}><td><b>{r.name}</b></td><td>{r.open}</td><td>{r.closed}</td><td className={r.overdue?'neg':''}>{r.overdue}</td><td>{r.average_age_days}d</td><td>{r.max_age}d</td></tr>)}</tbody></table></div></section>
  </>
}

function ScheduleImpact({data,onExport}:{data:any,onExport:()=>void}){
  const s=data?.summary||{};return <><div className="export-row"><button className="secondary" onClick={onExport}>Export CSV (Excel)</button></div><div className="kpi-grid"><Kpi label="Schedule Revisions" value={s.revisions||0}/><Kpi label="Net Qty Change" value={num(s.qty_delta||0)} tone={(s.qty_delta||0)>0?'warn':'neutral'}/><Kpi label="Net Sales Impact" value={money(s.sales_delta||0)} tone={(s.sales_delta||0)>0?'warn':'neutral'}/></div>
    <div className="advanced-grid"><section className="panel"><h2>Monthly Quantity Impact</h2><RankedBars rows={(data?.monthly||[]).map((r:any)=>({...r,name:r.label}))} valueKey="qty_delta" suffix=" pcs"/></section><section className="panel"><h2>Monthly Sales Impact</h2><RankedBars rows={(data?.monthly||[]).map((r:any)=>({...r,name:r.label}))} valueKey="sales_delta" prefix="₹"/></section></div>
    <section className="panel"><h2>Schedule Revision History & Impact</h2><div className="table-wrap"><table><thead><tr><th>Effective</th><th>Plant</th><th>Product</th><th>Rev</th><th>Previous</th><th>New</th><th>Qty Δ</th><th>Sales Δ</th><th>Remaining Days</th><th>New Req/Day</th><th>Reason</th></tr></thead><tbody>{(data?.revisions||[]).map((r:any,i:number)=><tr key={i}><td>{r.effective_from}</td><td>{r.plant||'—'}</td><td><b>{r.product}</b></td><td>R{r.revision_no}</td><td>{num(r.previous_target)}</td><td>{num(r.new_target)}</td><td className={r.qty_delta<0?'neg':r.qty_delta>0?'pos':''}>{num(r.qty_delta)}</td><td>{money(r.sales_delta)}</td><td>{r.remaining_working_days}</td><td>{num(r.new_avg_required_per_day)}</td><td>{r.reason||'—'}</td></tr>)}</tbody></table></div></section>
  </>
}

function ForecastReport({data,onExport}:{data:any,onExport:()=>void}){
  const s=data?.summary||{}
  const comparison=(data?.products||[]).map((r:any)=>({name:r.product,plan:r.target_qty,actual:r.projected_qty,gap:r.projected_gap_qty,compliance:r.projected_compliance}))
  return <><div className="export-row"><button className="secondary" onClick={onExport}>Export CSV (Excel)</button></div><div className="kpi-grid"><Kpi label="Monthly Target Qty" value={num(s.target_qty||0)}/><Kpi label="Actual Qty" value={num(s.actual_qty||0)}/><Kpi label="Projected Month End" value={num(s.projected_qty||0)}/><Kpi label="Critical" value={s.critical||0} tone={(s.critical||0)>0?'bad':'good'}/><Kpi label="Watch" value={s.watch||0} tone={(s.watch||0)>0?'warn':'good'}/><Kpi label="On Track" value={s.on_track||0} tone="good"/></div>
    <section className="panel"><h2>Projected Month-end Compliance by Part</h2><NamedComplianceBars rows={comparison} metric="qty"/></section>
    <section className="panel"><h2>Month-end Risk & Recovery Requirement</h2><div className="table-wrap"><table><thead><tr><th>Plant</th><th>Customer</th><th>Part</th><th>Target</th><th>Actual</th><th>Projected</th><th>Projected %</th><th>Recovery / Day</th><th>Remaining Days</th><th>Projected Sales Gap</th><th>Risk</th></tr></thead><tbody>{(data?.products||[]).map((r:any)=><tr key={r.product_id}><td>{r.plant||'—'}</td><td>{r.customer||'—'}</td><td><b>{r.product}</b></td><td>{num(r.target_qty)}</td><td>{num(r.actual_qty)}</td><td>{num(r.projected_qty)}</td><td>{pct(r.projected_compliance)}</td><td>{num(r.recovery_required_per_day)}</td><td>{r.remaining_working_days}</td><td className={r.projected_gap_sales<0?'neg':'pos'}>{money(r.projected_gap_sales)}</td><td className={`risk-${String(r.risk).toLowerCase()}`}>{r.risk.replaceAll('_',' ')}</td></tr>)}</tbody></table></div></section>
  </>
}
