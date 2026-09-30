import { useNavigate } from 'react-router-dom'
import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import { ComplianceLineChart, NamedComplianceBars, PartComplianceBars, PlanActualChart } from '../components/Charts'
import { ScopeFilters, ScopeValues, appendScope } from '../components/ScopeFilters'
import { Kpi, PageHeader, money, num, pct } from '../components/UI'

function today(){return new Date().toISOString().slice(0,10)}
const emptyScope:ScopeValues={plant:[],productGroup:[],customerId:[],productId:[]}
type Metric='qty'|'sales'|'tonnage'

function DailyActionStrip({rows}:{rows:any[]}){
  if(!rows?.length) return null
  return <div className="daily-action-strip">
    <div className="daily-action-strip-head"><b>Actions Raised by Day</b><span>Counted by action reference date within the selected product scope.</span></div>
    <div className="daily-action-scroll">{rows.map((r:any)=>{const count=Number(r.action_count||0);return <div className={`daily-action-cell ${count>0?'has-actions':''}`} key={`act-${r.start||r.label}`} title={`${r.label}: ${count} action${count===1?'':'s'} raised`}>
      <span>{r.label}</span><strong>{count}</strong><small>{count===1?'action':'actions'}</small>
    </div>})}</div>
  </div>
}

export default function Reports(){
  const navigate=useNavigate()
  function drill(r:any){const q=appendScope(new URLSearchParams({kind:'compliance',from_date:r.start||asOf,to_date:r.end||r.start||asOf}),scope);navigate(`/insights?${q}`)}
  const [asOf,setAsOf]=useState(today()); const [metric,setMetric]=useState<Metric>('qty'); const [scope,setScope]=useState<ScopeValues>(emptyScope)
  const [products,setProducts]=useState<any[]>([]); const [options,setOptions]=useState<any>({}); const [data,setData]=useState<any>(null); const [err,setErr]=useState(''); const [busy,setBusy]=useState(false)
  useEffect(()=>{Promise.all([api('/masters/products'),api('/masters/filter-options')]).then(([p,o]:any)=>{setProducts(p);setOptions(o)})},[])
  useEffect(()=>{let alive=true;setBusy(true);const q=appendScope(new URLSearchParams({as_of:asOf,metric}),scope);api(`/reports/compliance?${q}`).then(x=>{if(alive){setData(x);setErr('')}}).catch(e=>{if(alive)setErr(e.message)}).finally(()=>{if(alive)setBusy(false)});return()=>{alive=false}},[asOf,metric,scope.plant,scope.productGroup,scope.customerId,scope.productId])
  const productName=useMemo(()=>scope.productId.length===0?'All Parts':scope.productId.length===1?(products.find(p=>String(p.id)===scope.productId[0])?.name||'Selected Part'):`${scope.productId.length} Parts Selected`,[scope.productId,products])
  const s=data?.summary
  const fmt=(v:number)=>metric==='sales'?money(v):metric==='tonnage'?`${num(v)} MT`:num(v)
  const metricName=metric==='sales'?'Sales value':metric==='tonnage'?'Finished weight / tonnage':'Quantity'
  return <>
    <PageHeader title="Compliance Reports" subtitle="Daily, weekly and monthly compliance with Plant, Customer, Type / Product Group and Part filters." actions={<div className="report-filters"><select value={metric} onChange={e=>setMetric(e.target.value as Metric)}><option value="qty">Quantity</option><option value="sales">Sales ₹</option><option value="tonnage">Tonnage MT</option></select><input type="date" value={asOf} onChange={e=>setAsOf(e.target.value)}/></div>}/>
    <ScopeFilters value={scope} onChange={setScope} options={options} products={products}/>
    {err&&<div className="error">{err}</div>}{busy&&<div className="notice">Refreshing compliance report…</div>}
    {(data?.missing_weight_products||[]).length>0&&metric==='tonnage'&&<div className="warning-box"><b>Finish Weight missing:</b> {(data.missing_weight_products||[]).join(', ')}. Their tonnage is treated as zero until the master is completed.</div>}
    {s&&<><div className="report-scope"><b>{productName||'Selected Part'}</b><span>{s.period} • {metricName} compliance</span></div><div className="kpi-grid"><Kpi label="Plan to date" value={fmt(s.plan)}/><Kpi label="Actual to date" value={fmt(s.actual)} tone="good"/><Kpi label="Gap" value={fmt(s.gap)} tone={s.gap<0?'bad':'good'}/><Kpi label="Compliance" value={pct(s.compliance)} tone={(s.compliance??0)<.9?'bad':(s.compliance??0)<1?'warn':'good'}/><Kpi label="Actions Raised" value={num(s.actions_raised||0)} tone={(s.actions_raised||0)>0?'warn':undefined}/></div></>}

    <section className="panel report-panel"><div className="panel-title"><div><h2>Daily Compliance</h2><p>Current month, day-wise Plan vs Actual through the selected date. Action counts highlight days where follow-up was initiated.</p></div><span>{productName}</span></div><PlanActualChart onSelect={drill} rows={data?.daily||[]} metric={metric}/><DailyActionStrip rows={data?.daily||[]}/><ComplianceLineChart onSelect={drill} rows={data?.daily||[]}/></section>
    <section className="panel report-panel"><div className="panel-title"><div><h2>Weekly Compliance</h2><p>Rolling 8 weeks. Current week stops at the selected date.</p></div><span>{productName}</span></div><PlanActualChart onSelect={drill} rows={data?.weekly||[]} metric={metric}/><ComplianceLineChart onSelect={drill} rows={data?.weekly||[]}/></section>
    <section className="panel report-panel"><div className="panel-title"><div><h2>Monthly Compliance</h2><p>Rolling 12 months with schedule revisions applied from their effective dates.</p></div><span>{productName}</span></div><PlanActualChart onSelect={drill} rows={data?.monthly||[]} metric={metric}/><ComplianceLineChart onSelect={drill} rows={data?.monthly||[]}/></section>

    {scope.productId.length===0&&<><section className="panel report-panel"><div className="panel-title"><div><h2>Plant-wise Current Month Compliance</h2><p>Compare all manufacturing plants inside the selected customer/group scope.</p></div><span>100% target</span></div><NamedComplianceBars rows={data?.plants||[]} metric={metric}/></section>
    <section className="panel report-panel"><div className="panel-title"><div><h2>Type / Product Group-wise Compliance</h2><p>Useful for cast iron / aluminium / other business group bifurcation.</p></div><span>Current month</span></div><NamedComplianceBars rows={data?.product_groups||[]} metric={metric}/></section>
    <section className="panel report-panel"><div className="panel-title"><div><h2>Customer-wise Compliance</h2><p>Customer roll-up within the selected plant and product group.</p></div><span>Current month</span></div><NamedComplianceBars rows={data?.customers||[]} metric={metric}/></section></>}

    <section className="panel report-panel"><div className="panel-title"><div><h2>Part-wise Current Month Compliance</h2><p>Plan vs Actual for each part inside the selected scope.</p></div><span>100% target marker</span></div><PartComplianceBars rows={data?.parts||[]} metric={metric}/><div className="table-wrap report-table"><table><thead><tr><th>Plant</th><th>Group</th><th>Customer</th><th>Part</th><th>Finish Wt.</th><th>Plan</th><th>Actual</th><th>Gap</th><th>Compliance</th></tr></thead><tbody>{(data?.parts||[]).map((r:any)=><tr key={r.product_id}><td>{r.plant||'—'}</td><td>{r.product_group||'—'}</td><td>{r.customer||'—'}</td><td><b>{r.product}</b></td><td>{r.finish_weight_kg==null?'—':`${num(r.finish_weight_kg)} kg`}</td><td>{fmt(r.plan)}</td><td>{fmt(r.actual)}</td><td className={r.gap<0?'neg':'pos'}>{fmt(r.gap)}</td><td className={(r.compliance??0)<.9?'neg':(r.compliance??0)>=1?'pos':''}>{pct(r.compliance)}</td></tr>)}</tbody></table></div></section>
  </>
}
