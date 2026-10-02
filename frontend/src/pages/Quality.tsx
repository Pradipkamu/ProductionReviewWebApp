import ImportPreview from '../components/ImportPreview'
import { useNavigate } from 'react-router-dom'
import { useEffect, useMemo, useState } from 'react'
import { api, downloadApi } from '../api'
import { Kpi, PageHeader, num } from '../components/UI'
import { RankedBars, ValueTrendChart } from '../components/Charts'
import { MultiSelect } from '../components/MultiSelect'

function iso(d:Date){ return d.toISOString().slice(0,10) }
function monthEnd(monthStart:string){
  const [y,m]=monthStart.slice(0,10).split('-').map(Number)
  return iso(new Date(y, m, 0))
}

export default function Quality(){
  const navigate=useNavigate()
  function drill(r:any){const month=r.month;const first=month||r.date||r.rejection_date||fromDate;const last=month?monthEnd(month):first;const q=new URLSearchParams({kind:'ppm',from_date:first,to_date:last});if(productId.length)q.set('product_id',productId.join(','));if(plant.length)q.set('plant',plant.join(','));if(phenomenonId.length)q.set('phenomenon_id',phenomenonId.join(','));if(machineId.length)q.set('machine_id',machineId.join(','));if(operationId.length)q.set('operation_id',operationId.join(','));if(shift.length)q.set('shift',shift.join(','));navigate(`/insights?${q}`)}
  const today=new Date(); const weekAgo=new Date(today); weekAgo.setDate(today.getDate()-7)
  const [fromDate,setFromDate]=useState(iso(weekAgo)); const [toDate,setToDate]=useState(iso(today))
  const [plant,setPlant]=useState<string[]>([]); const [productId,setProductId]=useState<string[]>([]); const [phenomenonId,setPhenomenonId]=useState<string[]>([])
  const [operationId,setOperationId]=useState<string[]>([]); const [machineId,setMachineId]=useState<string[]>([]); const [shift,setShift]=useState<string[]>([])
  const [products,setProducts]=useState<any[]>([]); const [filters,setFilters]=useState<any>({plants:[]}); const [phenomena,setPhenomena]=useState<any[]>([])
  const [operations,setOperations]=useState<any[]>([]); const [machines,setMachines]=useState<any[]>([])
  const [summary,setSummary]=useState<any>({}); const [rows,setRows]=useState<any[]>([]); const [trend,setTrend]=useState<any[]>([])
  const [monthlyTrend,setMonthlyTrend]=useState<any[]>([]); const [historyRows,setHistoryRows]=useState<any[]>([]); const [historyRange,setHistoryRange]=useState<any>({min_month:null,max_month:null,records:0})
  const [partPareto,setPartPareto]=useState<any[]>([]); const [phenPareto,setPhenPareto]=useState<any[]>([]); const [busy,setBusy]=useState(false); const [err,setErr]=useState('')
  const [dailyFile,setDailyFile]=useState<File|null>(null); const [historyFile,setHistoryFile]=useState<File|null>(null); const [importResult,setImportResult]=useState<any>(null)
  const [newPhen,setNewPhen]=useState('')

  const qs=useMemo(()=>{const p=new URLSearchParams({from_date:fromDate,to_date:toDate});if(plant.length)p.set('plant',plant.join(','));if(productId.length)p.set('product_id',productId.join(','));if(phenomenonId.length)p.set('phenomenon_id',phenomenonId.join(','));if(operationId.length)p.set('operation_id',operationId.join(','));if(machineId.length)p.set('machine_id',machineId.join(','));if(shift.length)p.set('shift',shift.join(','));return p.toString()},[fromDate,toDate,plant,productId,phenomenonId,operationId,machineId,shift])
  const historyQs=useMemo(()=>{const p=new URLSearchParams({from_date:fromDate,to_date:toDate});if(plant.length)p.set('plant',plant.join(','));if(productId.length)p.set('product_id',productId.join(','));if(phenomenonId.length)p.set('phenomenon_id',phenomenonId.join(','));return p.toString()},[fromDate,toDate,plant,productId,phenomenonId])
  const monthlyQs=useMemo(()=>{const p=new URLSearchParams({from_month:`${fromDate.slice(0,7)}-01`,to_month:`${toDate.slice(0,7)}-01`});if(plant.length)p.set('plant',plant.join(','));if(productId.length)p.set('product_id',productId.join(','));if(phenomenonId.length)p.set('phenomenon_id',phenomenonId.join(','));return p.toString()},[fromDate,toDate,plant,productId,phenomenonId])

  async function loadMasters(){
    const [p,f,ph,o,m,hr]=await Promise.all([api('/masters/products'),api('/masters/filter-options'),api('/quality/phenomena'),api('/masters/operations'),api('/masters/machines'),api('/quality/history-range')])
    setProducts(p as any[]);setFilters(f);setPhenomena(ph as any[]);setOperations(o as any[]);setMachines(m as any[]);setHistoryRange(hr)
  }
  async function load(){
    setBusy(true);setErr('')
    try{
      const [s,r,t,pp,dp,mt,hr]=await Promise.all([
        api(`/quality/dashboard?${qs}`),api(`/quality/daily?${qs}`),api(`/quality/trend?${qs}`),
        api(`/quality/pareto?group_by=product&${qs}`),api(`/quality/pareto?group_by=phenomenon&${qs}`),
        api(`/quality/monthly-trend?${monthlyQs}`),api(`/quality/history?${historyQs}`)
      ])
      setSummary(s);setRows(r as any[]);setTrend(t as any[]);setPartPareto(pp as any[]);setPhenPareto(dp as any[]);setMonthlyTrend(mt as any[]);setHistoryRows(hr as any[])
    }catch(e:any){setErr(e.message)}finally{setBusy(false)}
  }
  useEffect(()=>{loadMasters().catch(e=>setErr(e.message))},[])
  useEffect(()=>{load()},[qs,historyQs,monthlyQs])

  async function upload(file:File|null,type:'daily'|'history'){
    if(!file)return;setBusy(true);setErr('');const fd=new FormData();fd.append('file',file)
    location.href='/import';setBusy(false)
  }
  async function addPhenomenon(){if(!newPhen.trim())return;try{await api('/quality/phenomena',{method:'POST',body:JSON.stringify({name:newPhen,default_responsible_team:'Operation',criticality:'NORMAL'})});setNewPhen('');await loadMasters()}catch(e:any){setErr(e.message)}}
  async function raiseAction(id:number){try{const r:any=await api(`/quality/rejections/${id}/raise-action`,{method:'POST',body:JSON.stringify({priority:'HIGH',action_description:'Immediate containment and standard Why-Why analysis required'})});alert(`${r.action_no} ${r.status==='already_linked'?'already linked':'created'}`);await load()}catch(e:any){setErr(e.message)}}
  function showImportedHistory(){if(!historyRange?.min_month||!historyRange?.max_month)return;setFromDate(String(historyRange.min_month).slice(0,10));setToDate(monthEnd(String(historyRange.max_month)))}

  const ppm=(summary.ppm==null?'—':Math.round(summary.ppm).toLocaleString('en-IN'))
  const visibleHistory=historyRows.slice(0,500)
  const monthlyPpmRows=monthlyTrend.filter((x:any)=>x.ppm!=null).map((x:any)=>({...x,value:Number(x.ppm)}))
  const monthlyPpmPending=monthlyTrend.filter((x:any)=>x.ppm==null&&Number(x.reject_qty||0)>0).length
  return <>
    <PageHeader title="Quality / Rejection" subtitle="Daily rejection, historical monthly rejection, PPM, Pareto and Why-Why actions." actions={<div className="button-row"><button className="secondary" onClick={()=>downloadApi('/quality/template','Daily_Rejection_Upload_v0.4.6.xlsx')}>Download Daily Template</button>{historyRange?.records>0&&<button className="secondary" onClick={showImportedHistory}>Show Imported History</button>}<button onClick={()=>window.print()}>Print / PDF</button></div>}/>
    <section className="panel"><div className="filters quality-filters"><label>From<input type="date" value={fromDate} onChange={e=>setFromDate(e.target.value)}/></label><label>To<input type="date" value={toDate} onChange={e=>setToDate(e.target.value)}/></label><label>Plant<MultiSelect value={plant} onChange={setPlant} placeholder="All Plants" options={(filters.plants||[]).map((x:string)=>({value:String(x),label:String(x)}))}/></label><label>Product<MultiSelect value={productId} onChange={setProductId} placeholder="All Products" options={products.map(x=>({value:String(x.id),label:x.name}))}/></label><label>Phenomenon<MultiSelect value={phenomenonId} onChange={setPhenomenonId} placeholder="All Phenomena" options={phenomena.map(x=>({value:String(x.id),label:x.name}))}/></label><label>Process<MultiSelect value={operationId} onChange={setOperationId} placeholder="All Processes" options={operations.map(x=>({value:String(x.id),label:x.name}))}/></label><label>Machine<MultiSelect value={machineId} onChange={setMachineId} placeholder="All Machines" options={machines.map(x=>({value:String(x.id),label:x.name}))}/></label><label>Shift<MultiSelect value={shift} onChange={setShift} placeholder="All Shifts" searchable={false} options={['A','B','C','General'].map(x=>({value:x,label:x}))}/></label></div>{historyRange?.records>0&&<p className="muted">Imported history: {historyRange.min_month} to {historyRange.max_month} • {num(historyRange.records)} phenomenon rows. Historical PPM automatically uses matching Daily MIS Actual Qty as the Dispatch Done denominator when available; otherwise PPM stays Pending.</p>}{summary.history_note&&<div className="warning">{summary.history_note}</div>}{err&&<div className="error">{err}</div>}</section>

    <div className="kpi-grid"><Kpi label="Rejected Qty" value={num(summary.reject_qty||0)} tone={(summary.reject_qty||0)>0?'bad':'good'} sub={`${num(summary.daily_records||0)} daily + ${num(summary.historical_records||0)} historical rows`}/><Kpi label="PPM" value={ppm} tone={summary.ppm==null?'warn':'neutral'} sub={`${num(summary.denominator_qty||0)} Dispatch/denominator qty`}/><Kpi label="Rework" value={num(summary.rework_qty||0)}/><Kpi label="Scrap" value={num(summary.scrap_qty||0)} tone={(summary.scrap_qty||0)>0?'bad':'neutral'}/><Kpi label="Open Actions" value={summary.open_actions||0} tone={(summary.open_actions||0)>0?'warn':'good'}/><Kpi label="Overdue Actions" value={summary.overdue_actions||0} tone={(summary.overdue_actions||0)>0?'bad':'good'}/></div>

    <section className="panel"><div className="panel-title"><h2>Monthly Rejection Qty Trend</h2><span>Historical + daily roll-up • labels ON</span></div><ValueTrendChart onSelect={drill} rows={monthlyTrend.map(x=>({...x,value:x.reject_qty||0}))} keyName="value" label="Reject Qty"/></section>
    <section className="panel"><div className="panel-title"><h2>Monthly PPM Trend</h2><span>Historical + daily roll-up • labels ON</span></div><ValueTrendChart onSelect={drill} rows={monthlyPpmRows} keyName="value" label="PPM"/>{monthlyPpmPending>0&&<p className="muted">{monthlyPpmPending} month{monthlyPpmPending===1?'':'s'} not plotted because Dispatch/denominator Qty is still pending.</p>}</section>
    {trend.some((x:any)=>x.ppm!=null)&&<section className="panel"><div className="panel-title"><h2>Daily PPM Trend</h2><span>Daily rejection uploads • labels ON</span></div><ValueTrendChart onSelect={drill} rows={trend.filter((x:any)=>x.ppm!=null).map((x:any)=>({...x,value:Number(x.ppm)}))} keyName="value" label="PPM"/></section>}
    <div className="two-col"><section className="panel"><div className="panel-title"><h2>Phenomenon Pareto</h2><span>Daily + historical Reject Qty</span></div><RankedBars rows={phenPareto.slice(0,20)} valueKey="reject_qty" labelKey="name" valueLabel="Reject Qty"/></section><section className="panel"><div className="panel-title"><h2>Component Pareto</h2><span>Daily + historical Reject Qty</span></div><RankedBars rows={partPareto.slice(0,20)} valueKey="reject_qty" labelKey="name" valueLabel="Reject Qty"/></section></div>

    <section className="panel"><h2>Approved Phenomenon Master</h2><div className="form-row"><label>New Phenomenon<input value={newPhen} onChange={e=>setNewPhen(e.target.value)} placeholder="Add once, then re-download template"/></label><button onClick={addPhenomenon}>Add to Master</button></div><p className="muted">Daily uploads reject unknown typed phenomena. This prevents duplicate names such as “Bore O/S”, “Bore OS” and “Bore Oversize” being created accidentally.</p></section>

    <section className="panel"><h2>Excel Imports</h2><div className="two-col"><div><h3>Daily Rejection</h3><p>Download a fresh template after any Product, Process, Machine or Phenomenon master change. Orange headers and yellow cells are required; fixed master fields use dropdowns.</p><button className="secondary" onClick={()=>downloadApi('/quality/template','Daily_Rejection_Upload_v0.4.6.xlsx')}>Download Template</button><ImportPreview kind="quality-daily" onComplete={()=>{loadMasters();load()}}/></div><div><h3>Historical Rejection</h3><p>Matching historical MIS Dispatch Done quantity is used for calculated PPM.</p><ImportPreview kind="quality-history" onComplete={()=>{loadMasters();load()}}/></div></div></section>

    {historyRows.length>0&&<section className="panel"><div className="panel-title"><h2>Historical Monthly Rejection Detail</h2><span>{num(historyRows.length)} rows{historyRows.length>500?' • first 500 shown':''}</span></div><div className="table-wrap"><table><thead><tr><th>Month</th><th>Source</th><th>Plant</th><th>Product</th><th>Phenomenon</th><th>Reject</th><th>Dispatch Done</th><th>Calculated PPM</th><th>Source PPM</th></tr></thead><tbody>{visibleHistory.map(r=><tr key={r.id}><td>{String(r.month).slice(0,7)}</td><td>{r.source||'—'}</td><td>{r.plant||'—'}</td><td>{r.product}</td><td>{r.phenomenon}</td><td><b>{num(r.reject_qty)}</b></td><td>{r.dispatch_qty==null?'Pending':<>{num(r.dispatch_qty)}{r.dispatch_qty_source==='MIS_HISTORY'&&<span className="muted"> • MIS</span>}</>}</td><td>{r.ppm==null?'Pending':Math.round(r.ppm).toLocaleString('en-IN')}</td><td>{r.source_reported_ppm==null?'—':Math.round(r.source_reported_ppm).toLocaleString('en-IN')}</td></tr>)}</tbody></table></div></section>}

    <section className="panel"><div className="panel-title"><h2>Daily Rejection Detail</h2><span>{rows.length} rows</span></div><div className="table-wrap"><table><thead><tr><th>Date</th><th>Shift</th><th>Plant</th><th>Product</th><th>Detection Process</th><th>Responsible Process</th><th>Machine</th><th>Phenomenon</th><th>Reject</th><th>Denominator</th><th>PPM</th><th>Remark</th><th>Action</th></tr></thead><tbody>{rows.map(r=><tr key={r.id}><td>{r.date}</td><td>{r.shift}</td><td>{r.plant||'—'}</td><td>{r.product}</td><td>{r.detection_process||'—'}</td><td>{r.responsible_process||'—'}</td><td>{r.machine||'—'}</td><td>{r.phenomenon}</td><td><b>{num(r.reject_qty)}</b></td><td>{r.denominator_qty==null?'Pending':`${num(r.denominator_qty)} (${r.denominator_source})`}</td><td>{r.ppm==null?'Pending':Math.round(r.ppm).toLocaleString('en-IN')}</td><td>{r.remark||''}</td><td>{r.action?<a href="/actions">{r.action.action_no} • {r.action.status}</a>:<button className="small" onClick={()=>raiseAction(r.id)}>Raise Action</button>}</td></tr>)}</tbody></table></div></section>
  </>
}
