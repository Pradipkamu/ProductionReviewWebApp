import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import { ScopeFilters, ScopeValues, appendScope } from '../components/ScopeFilters'
import { Kpi, PageHeader, Status, money, num, pct } from '../components/UI'
import { daysAgoIST } from '../time'

const emptyScope:ScopeValues={plant:[],productGroup:[],customerId:[],productId:[]}
export default function DispatchIntelligence(){
 const navigate=useNavigate()
 const [asOf,setAsOf]=useState(daysAgoIST()),[scope,setScope]=useState<ScopeValues>(emptyScope)
 const [options,setOptions]=useState<any>({}),[products,setProducts]=useState<any[]>([])
 const [trend,setTrend]=useState<any[]>([]),[exceptions,setExceptions]=useState<any[]>([]),[dailyDetail,setDailyDetail]=useState<any>({summary:{},rows:[]})
 const [busy,setBusy]=useState(false),[error,setError]=useState('')
 useEffect(()=>{Promise.all([api('/masters/filter-options'),api('/masters/products')]).then(([o,p])=>{setOptions(o);setProducts(p)}).catch((e:any)=>setError(e.message))},[])
 async function load(){
  setBusy(true)
  try{
   const q=appendScope(new URLSearchParams({end_month:asOf,months:'6'}),scope)
   const x=appendScope(new URLSearchParams({as_of:asOf}),scope)
   const fromDate=asOf.slice(0,7)+'-01'
   const d=appendScope(new URLSearchParams({from_date:fromDate,to_date:asOf}),scope)
   const [t,e,detail]=await Promise.all([api('/analytics/monthly?'+q),api('/insights/exceptions?'+x),api('/analytics/dispatch-detail?'+d)])
   setTrend(t||[]);setDailyDetail(detail||{summary:{},rows:[]});setExceptions((e?.exceptions||[]).filter((r:any)=>['low_compliance','dispatch_gap','low_dispatch'].includes(r.kind)))
   setError('')
  }catch(e:any){setError(e.message)}finally{setBusy(false)}
 }
 useEffect(()=>{load()},[asOf,scope.plant,scope.productGroup,scope.customerId,scope.productId])
 const latest=trend[trend.length-1]||{},plan=Number(latest.plan_qty||0),actual=Number(latest.actual_qty||0)
 const gap=actual-plan,achievement=plan?actual/plan:0
 return <><PageHeader title="Dispatch vs Actual Intelligence" subtitle="Six-month dispatch trend, plan attainment and source-linked exceptions." actions={<div className="button-row"><input aria-label="As-of month" type="date" value={asOf} onChange={e=>setAsOf(e.target.value)}/><button className="secondary" onClick={load} disabled={busy}>{busy?'Refreshing…':'Refresh'}</button></div>}/>
 <ScopeFilters value={scope} onChange={setScope} options={options} products={products}/>{error&&<div className="error">{error}</div>}
 <div className="kpi-grid"><Kpi label="Latest month plan" value={num(plan)}/><Kpi label="Latest month actual" value={num(actual)}/><Kpi label="Dispatch gap" value={num(gap)} tone={gap<0?'bad':'good'}/><Kpi label="Achievement" value={pct(achievement)} tone={achievement<.9?'bad':'good'}/><Kpi label="Sales plan" value={money(latest.plan_sales||0)}/><Kpi label="Actual sales" value={money(latest.actual_sales||0)}/></div>
 <section className="panel"><div className="panel-title"><div><h2>Monthly dispatch trend</h2><p>Revised dispatch requirements are used where available; otherwise MIS plan is retained.</p></div><button className="secondary small" onClick={()=>navigate('/mis')}>Open daily MIS</button></div>
 {trend.length===0?<div className="empty">No monthly dispatch data in this scope.</div>:<div className="table-wrap"><table><thead><tr><th>Month</th><th>Plan qty</th><th>Actual qty</th><th>Gap</th><th>Plan sales</th><th>Actual sales</th><th>Sales gap</th><th>Achievement</th></tr></thead><tbody>{trend.map((r:any)=><tr key={r.month}><td>{r.month}</td><td>{num(r.plan_qty)}</td><td>{num(r.actual_qty)}</td><td>{num(r.actual_qty-r.plan_qty)}</td><td>{money(r.plan_sales)}</td><td>{money(r.actual_sales)}</td><td>{money(r.sales_gap)}</td><td><Status value={pct(r.plan_qty? r.actual_qty/r.plan_qty:0)}/></td></tr>)}</tbody></table></div>}</section>
 <section className="panel"><div className="panel-title"><div><h2>Part-wise daily dispatch plan vs actual</h2><p>Selected month through {asOf}. Revised dispatch requirements take precedence per date; MIS plan is used only for dates without a revised requirement. Missing actual uploads are not treated as zero.</p></div><button className="secondary small" onClick={()=>navigate('/schedule')}>Open schedule</button></div><div className="kpi-grid"><Kpi label="Part/date rows" value={dailyDetail.summary?.rows||0}/><Kpi label="Products in scope" value={dailyDetail.summary?.products||0}/><Kpi label="Actual uploads pending" value={dailyDetail.summary?.missing_actual_rows||0} tone={Number(dailyDetail.summary?.missing_actual_rows||0)?'watch':'good'}/><Kpi label="Below plan rows" value={dailyDetail.summary?.below_plan_rows||0} tone={Number(dailyDetail.summary?.below_plan_rows||0)?'bad':'good'}/></div>{(dailyDetail.rows||[]).length===0?<div className="empty">No daily dispatch plan or actual rows in this selected period and scope.</div>:<div className="table-wrap"><table><thead><tr><th>Date</th><th>Plant</th><th>Product</th><th>Plan</th><th>Actual</th><th>Gap</th><th>Achievement</th><th>Plan source</th><th>Schedule revision</th><th>Status</th><th></th></tr></thead><tbody>{(dailyDetail.rows||[]).map((r:any)=><tr key={r.date+'-'+r.product_id}><td>{r.date}</td><td>{r.plant||'—'}</td><td><b>{r.product}</b><br/><span className="muted">{r.product_code}</span></td><td>{r.plan_qty==null?'—':num(r.plan_qty)}</td><td>{r.actual_qty==null?'Not uploaded':num(r.actual_qty)}</td><td>{r.gap_qty==null?'—':num(r.gap_qty)}</td><td>{r.achievement==null?'—':pct(r.achievement)}</td><td>{r.plan_source==='REVISED_REQUIREMENT'?'Revised schedule':r.plan_source==='DAILY_MIS_BASELINE'?'MIS baseline':'No plan'}</td><td>{r.schedule_revision_no!=null?'Rev '+r.schedule_revision_no+(r.schedule_effective_from?' · '+r.schedule_effective_from:''):r.schedule_revision_id!=null?'Revision #'+r.schedule_revision_id:'—'}</td><td><Status value={r.status}/></td><td>{r.status==='BELOW_PLAN'||r.status==='ACTUAL_PENDING'?<button className="small" onClick={()=>navigate('/actions?'+new URLSearchParams({date:r.date,product_id:String(r.product_id),problem:r.status==='ACTUAL_PENDING'?'Missing dispatch actual': 'Dispatch below plan'}))}>Raise action</button>:null}</td></tr>)}</tbody></table></div>}</section>
 <section className="panel"><div className="panel-title"><div><h2>Dispatch exceptions</h2><p>Exceptions generated by the existing compliance rules for the selected date.</p></div><button className="secondary small" onClick={()=>navigate('/insights')}>All exceptions</button></div>
 {exceptions.length===0?<div className="empty">No dispatch exceptions returned for this date.</div>:<div className="table-wrap"><table><thead><tr><th>Issue</th><th>Product</th><th>Evidence</th><th>Action</th></tr></thead><tbody>{exceptions.map((r:any,i:number)=><tr key={r.entity_id||i}><td>{r.kind.replaceAll('_',' ')}</td><td>{r.product||'—'}</td><td>{r.detail}</td><td><button className="small" onClick={()=>navigate('/actions?'+new URLSearchParams({date:asOf,product_id:String(r.product_id||''),problem:r.detail||r.kind}))}>Raise action</button></td></tr>)}</tbody></table></div>}</section></>
}
