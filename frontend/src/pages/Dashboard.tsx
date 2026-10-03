import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import ImportPreview from '../components/ImportPreview'
import { ScopeFilters, ScopeValues, appendScope } from '../components/ScopeFilters'
import { Kpi, PageHeader, Status, money, num, pct } from '../components/UI'

function today(){ return new Date().toISOString().slice(0,10) }
const emptyScope:ScopeValues={plant:[],productGroup:[],customerId:[],productId:[]}

export default function Dashboard(){
  const navigate=useNavigate()
  const [asOf,setAsOf]=useState(today()); const [data,setData]=useState<any>(null); const [control,setControl]=useState<any>(null); const [err,setErr]=useState(''); const [message,setMessage]=useState('')
  const [activeReview,setActiveReview]=useState<string|null>(null)
  const [scope,setScope]=useState<ScopeValues>(emptyScope); const [options,setOptions]=useState<any>({}); const [products,setProducts]=useState<any[]>([]); const [role,setRole]=useState('')
  useEffect(()=>{Promise.all([api('/masters/filter-options'),api('/masters/products'),api('/auth/me')]).then(([o,p,m]:any)=>{setOptions(o);setProducts(p);setRole(m.role)})},[])
  async function load(){
    try{
      const q=appendScope(new URLSearchParams({as_of:asOf}),scope)
      const [summary,dailyControl]=await Promise.all([api(`/dashboard/summary?${q}`),api(`/dashboard/daily-control?${q}`)])
      setData(summary);setControl(dailyControl);setErr('')
    }catch(e:any){setErr(e.message)}
  }
  async function syncReview(){
    try{
      const r:any=await api(`/reviews/active?review_date=${asOf}`)
      if(r?.id){localStorage.setItem('activeReview',String(r.id));setActiveReview(String(r.id))}
      else{localStorage.removeItem('activeReview');setActiveReview(null)}
    }catch(e:any){setErr(`Unable to check review session: ${e.message}`)}
  }
  useEffect(()=>{load()},[asOf,scope.plant,scope.productGroup,scope.customerId,scope.productId])
  useEffect(()=>{syncReview()},[asOf])

  async function startReview(){
    const participants=prompt('Participants / departments')||''
    try{
      const r:any=await api('/reviews',{method:'POST',body:JSON.stringify({review_date:asOf,participants,comments:'Daily sales/process review'})})
      localStorage.setItem('activeReview',String(r.id));setActiveReview(String(r.id));setErr('');setMessage(r.existing?`Review session #${r.id} was already active.`:`Review session #${r.id} started.`)
    }catch(e:any){setErr(`Unable to start review: ${e.message}`)}
  }
  async function closeReview(){
    if(!activeReview)return
    const comments=prompt('Review closing comments')
    if(comments===null)return
    try{
      await api(`/reviews/${activeReview}/close`,{method:'PATCH',body:JSON.stringify({comments})})
      localStorage.removeItem('activeReview');setActiveReview(null);setErr('');setMessage(`Review session #${activeReview} closed successfully.`);await load()
    }catch(e:any){
      setErr(`Unable to close review: ${e.message}`)
      // Re-read the server state. This also clears an old localStorage review ID
      // after a fresh database/app installation.
      await syncReview()
    }
  }
  function raiseAction(productId?:number,product?:string){
    const q=new URLSearchParams({date:asOf})
    if(productId)q.set('product_id',String(productId))
    if(product)q.set('problem',`Daily review exception: ${product}`)
    navigate(`/actions?${q.toString()}`)
  }
  function openUpload(){
    const node=document.getElementById('daily-upload') as HTMLDetailsElement|null
    if(node){node.open=true;node.scrollIntoView({behavior:'smooth',block:'start'})}
  }
  function handleAlert(row:any){
    if(row.action==='upload'){openUpload();return}
    if(row.action==='action'){raiseAction(row.product_id,row.product);return}
    if(row.action==='schedule'){navigate('/schedule');return}
    if(row.action==='process'){navigate(`/process?date=${asOf}${row.product_id?`&product_id=${row.product_id}`:''}`);return}
    if(row.action==='data-quality'){navigate('/insights');return}
    if(row.action==='actions'){navigate('/actions');return}
    if(row.action==='vendor'){navigate('/vendor');return}
  }
  const actionLabel=(action:string)=>({upload:'Upload',action:'Raise action',schedule:'Open schedules',process:'Open process', 'data-quality':'Fix master data',actions:'Open actions',vendor:'Open vendor WIP'} as any)[action]||'Review'
  const k=data?.kpis
  const workflow=control?.workflow||{}
  const alerts=control?.alerts||[]
  const canUpload=['ADMIN','PLANNING'].includes(role)
  return <>
    <PageHeader title="Daily Production Control" subtitle="Check readiness, upload once and act on the earliest production warnings." actions={<div className="button-row"><button onClick={()=>raiseAction()}>Raise action</button><input type="date" value={asOf} onChange={e=>setAsOf(e.target.value)}/>{activeReview?<button className="secondary" onClick={closeReview}>Close review</button>:<button className="secondary" onClick={startReview}>Start review</button>}</div>}/>
    <ScopeFilters value={scope} onChange={setScope} options={options} products={products}/>
    {err && <div className="error">{err}</div>}
    {message && <div className="notice">{message}</div>}
    {activeReview&&<div className="notice action-notice"><span>Review session #{activeReview} is active. Actions raised for {asOf} are automatically linked to this review and remain trackable after the review is closed.</span><button className="small" onClick={()=>raiseAction()}>Raise action</button></div>}
    <section className="panel daily-control"><div className="panel-title"><div><h2>Today in three steps</h2><p>Missing uploads are kept separate from reported zero production.</p></div><span>Next 7 days: {control?.upcoming?.planned_days||0} planned days • {control?.upcoming?.planned_products||0} products</span></div>
      <div className="daily-steps">
        <article className="daily-step"><div className="step-number">1</div><div><small>CHECK</small><h3>Schedule readiness</h3><Status value={workflow.schedule?.status||'LOADING'}/><p>{workflow.schedule?.planned_products||0} customer plans • {workflow.schedule?.planned_stages||0} stage plans</p><button className="secondary small" onClick={()=>navigate('/schedule')}>Open schedules</button></div></article>
        <article className="daily-step"><div className="step-number">2</div><div><small>UPLOAD ONCE</small><h3>Daily production</h3><Status value={workflow.upload?.status||'LOADING'}/><p>{workflow.upload?.reported_rows||0} of {workflow.upload?.expected_rows||0} planned rows reported</p>{canUpload?<button className="small" onClick={openUpload}>Upload workbook</button>:<span className="muted">Admin or Planning uploads the workbook.</span>}</div></article>
        <article className="daily-step"><div className="step-number">3</div><div><small>ACT</small><h3>Review exceptions</h3><Status value={workflow.review?.status||'LOADING'}/><p>{workflow.review?.blockers||0} blockers • {workflow.review?.critical||0} critical • {workflow.review?.warnings||0} warnings</p><button className="secondary small" onClick={()=>document.getElementById('daily-alerts')?.scrollIntoView({behavior:'smooth'})}>Review warnings</button></div></article>
      </div>
      {canUpload&&<details id="daily-upload" className="daily-upload"><summary>Daily Production Upload</summary><p>Select the approved workbook containing <b>Daily_Actuals</b> and <b>Historical_Daily_MIS_Import</b>. Preview first; one confirmation commits customer MIS and every stage actual together.</p><ImportPreview kind="daily-production" onComplete={()=>{setMessage('Daily production upload completed. Readiness and warnings have been refreshed.');load()}}/></details>}
    </section>
    <section className="panel" id="daily-alerts"><div className="panel-title"><div><h2>Early warnings requiring attention</h2><p>Blockers are missing information; critical items are reported production failures.</p></div><span>{alerts.length} item{alerts.length===1?'':'s'} in selected scope</span></div>
      {alerts.length===0?<div className="empty">No blocker, critical or warning is active for {asOf}.</div>:<div className="table-wrap"><table><thead><tr><th>Priority</th><th>Product</th><th>Warning</th><th>Plan</th><th>Actual / Value</th><th>Next step</th></tr></thead><tbody>
        {alerts.map((r:any,i:number)=><tr key={`${r.kind}-${r.product_id||0}-${i}`} className={`alert-row ${String(r.severity).toLowerCase()}`}><td><Status value={r.severity}/></td><td><b>{r.product||'Selected scope'}</b></td><td>{r.detail}</td><td>{r.plan_qty===null?'—':num(r.plan_qty)}</td><td>{r.actual_qty!==null?num(r.actual_qty):r.value!==null?num(r.value):'—'}</td><td><button className="small" onClick={()=>handleAlert(r)}>{actionLabel(r.action)}</button></td></tr>)}
      </tbody></table></div>}
    </section>
    <div className="section-label">Month-to-date sales position</div>
    {k && <><div className="kpi-grid">
      <Kpi label="Plan sales to date" value={money(k.plan_sales)}/><Kpi label="Actual sales to date" value={money(k.actual_sales)} tone="good"/>
      <Kpi label="Sales gap" value={money(k.sales_gap)} tone={k.sales_gap<0?'bad':'good'}/><Kpi label="Achievement" value={pct(k.achievement)} tone={k.achievement<.9?'bad':k.achievement<1?'warn':'good'}/>
      <Kpi label="Plan tonnage MT" value={num(k.plan_tonnage_mt)}/><Kpi label="Actual tonnage MT" value={num(k.actual_tonnage_mt)} tone="good"/><Kpi label="Tonnage gap MT" value={num(k.tonnage_gap_mt)} tone={k.tonnage_gap_mt<0?'bad':'good'}/>
      <Kpi label="Critical products" value={k.critical_products} tone="bad"/><Kpi label="Open actions" value={k.open_actions}/><Kpi label="Overdue actions" value={k.overdue_actions} tone={k.overdue_actions?'bad':'good'}/><Kpi label="Closed today" value={k.closed_today} tone="good"/>
    </div></>}
    <section className="panel"><div className="panel-title"><h2>Priority exceptions</h2><span>Critical, watch and no-plan products first</span></div>
      {(data?.exceptions||[]).length===0?<div className="empty">No priority dispatch exception in the selected scope.</div>:<div className="table-wrap"><table><thead><tr><th>Plant</th><th>Group</th><th>Product</th><th>Plan Qty</th><th>Actual</th><th>Qty Gap</th><th>Sales Gap</th><th>Tonnage Gap MT</th><th>Ach.</th><th>Recovery / Day</th><th>Status</th><th>Action</th></tr></thead><tbody>
        {(data?.exceptions||[]).map((r:any)=><tr key={r.product_id}><td>{r.plant||'—'}</td><td>{r.product_group||'—'}</td><td><b>{r.product}</b></td><td>{num(r.plan_qty)}</td><td>{num(r.actual_qty)}</td><td className={r.gap_qty<0?'neg':'pos'}>{num(r.gap_qty)}</td><td className={r.gap_sales<0?'neg':'pos'}>{money(r.gap_sales)}</td><td className={r.tonnage_gap_mt<0?'neg':'pos'}>{num(r.tonnage_gap_mt)}</td><td>{pct(r.achievement)}</td><td>{num(r.recovery_qty_per_day)}</td><td><Status value={r.status}/></td><td><button className="small" onClick={()=>raiseAction(r.product_id,r.product)}>Raise</button></td></tr>)}
      </tbody></table></div>}
    </section>
    <section className="panel"><div className="panel-title"><h2>OK / Running products</h2><span>All remaining dispatch products in the selected scope</span></div>
      {(data?.ok_products||[]).length===0?<div className="empty">No GOOD or DONE products are available for this period.</div>:<div className="table-wrap"><table><thead><tr><th>Plant</th><th>Group</th><th>Product</th><th>Plan Qty</th><th>Actual</th><th>Qty Gap</th><th>Sales Gap</th><th>Tonnage Gap MT</th><th>Ach.</th><th>Recovery / Day</th><th>Status</th><th>Action</th></tr></thead><tbody>
        {(data?.ok_products||[]).map((r:any)=><tr key={r.product_id}><td>{r.plant||'—'}</td><td>{r.product_group||'—'}</td><td><b>{r.product}</b></td><td>{num(r.plan_qty)}</td><td>{num(r.actual_qty)}</td><td className={r.gap_qty<0?'neg':'pos'}>{num(r.gap_qty)}</td><td className={r.gap_sales<0?'neg':'pos'}>{money(r.gap_sales)}</td><td className={r.tonnage_gap_mt<0?'neg':'pos'}>{num(r.tonnage_gap_mt)}</td><td>{pct(r.achievement)}</td><td>{num(r.recovery_qty_per_day)}</td><td><Status value={r.status}/></td><td><button className="small secondary" onClick={()=>raiseAction(r.product_id,r.product)}>Raise</button></td></tr>)}
      </tbody></table></div>}
    </section>
  </>
}
