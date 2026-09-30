import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import { ScopeFilters, ScopeValues, appendScope } from '../components/ScopeFilters'
import { Kpi, PageHeader, Status, money, num, pct } from '../components/UI'

function today(){ return new Date().toISOString().slice(0,10) }
const emptyScope:ScopeValues={plant:[],productGroup:[],customerId:[],productId:[]}

export default function Dashboard(){
  const navigate=useNavigate()
  const [asOf,setAsOf]=useState(today()); const [data,setData]=useState<any>(null); const [err,setErr]=useState(''); const [message,setMessage]=useState('')
  const [activeReview,setActiveReview]=useState<string|null>(null)
  const [scope,setScope]=useState<ScopeValues>(emptyScope); const [options,setOptions]=useState<any>({}); const [products,setProducts]=useState<any[]>([])
  useEffect(()=>{Promise.all([api('/masters/filter-options'),api('/masters/products')]).then(([o,p]:any)=>{setOptions(o);setProducts(p)})},[])
  async function load(){ try{const q=appendScope(new URLSearchParams({as_of:asOf}),scope);setData(await api(`/dashboard/summary?${q}`)); setErr('') }catch(e:any){setErr(e.message)} }
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
  const k=data?.kpis
  return <>
    <PageHeader title="Daily Sales Review" subtitle="Plant, product-group and customer wise quantity, sales, tonnage, recovery and actions." actions={<div className="button-row"><button onClick={()=>raiseAction()}>Raise action</button><input type="date" value={asOf} onChange={e=>setAsOf(e.target.value)}/>{activeReview?<button className="secondary" onClick={closeReview}>Close review</button>:<button className="secondary" onClick={startReview}>Start review</button>}</div>}/>
    <ScopeFilters value={scope} onChange={setScope} options={options} products={products}/>
    {err && <div className="error">{err}</div>}
    {message && <div className="notice">{message}</div>}
    {activeReview&&<div className="notice action-notice"><span>Review session #{activeReview} is active. Actions raised for {asOf} are automatically linked to this review and remain trackable after the review is closed.</span><button className="small" onClick={()=>raiseAction()}>Raise action</button></div>}
    {k && <><div className="kpi-grid">
      <Kpi label="Plan sales to date" value={money(k.plan_sales)}/><Kpi label="Actual sales to date" value={money(k.actual_sales)} tone="good"/>
      <Kpi label="Sales gap" value={money(k.sales_gap)} tone={k.sales_gap<0?'bad':'good'}/><Kpi label="Achievement" value={pct(k.achievement)} tone={k.achievement<.9?'bad':k.achievement<1?'warn':'good'}/>
      <Kpi label="Plan tonnage MT" value={num(k.plan_tonnage_mt)}/><Kpi label="Actual tonnage MT" value={num(k.actual_tonnage_mt)} tone="good"/><Kpi label="Tonnage gap MT" value={num(k.tonnage_gap_mt)} tone={k.tonnage_gap_mt<0?'bad':'good'}/>
      <Kpi label="Critical products" value={k.critical_products} tone="bad"/><Kpi label="Open actions" value={k.open_actions}/><Kpi label="Overdue actions" value={k.overdue_actions} tone={k.overdue_actions?'bad':'good'}/><Kpi label="Closed today" value={k.closed_today} tone="good"/>
    </div></>}
    <section className="panel"><div className="panel-title"><h2>Priority exceptions</h2><span>Sorted by sales gap inside the selected scope</span></div>
      <div className="table-wrap"><table><thead><tr><th>Plant</th><th>Group</th><th>Product</th><th>Plan Qty</th><th>Actual</th><th>Qty Gap</th><th>Sales Gap</th><th>Tonnage Gap MT</th><th>Ach.</th><th>Recovery / Day</th><th>Status</th><th>Action</th></tr></thead><tbody>
        {(data?.exceptions||[]).map((r:any)=><tr key={r.product_id}><td>{r.plant||'—'}</td><td>{r.product_group||'—'}</td><td><b>{r.product}</b></td><td>{num(r.plan_qty)}</td><td>{num(r.actual_qty)}</td><td className={r.gap_qty<0?'neg':'pos'}>{num(r.gap_qty)}</td><td className={r.gap_sales<0?'neg':'pos'}>{money(r.gap_sales)}</td><td className={r.tonnage_gap_mt<0?'neg':'pos'}>{num(r.tonnage_gap_mt)}</td><td>{pct(r.achievement)}</td><td>{num(r.recovery_qty_per_day)}</td><td><Status value={r.status}/></td><td><button className="small" onClick={()=>raiseAction(r.product_id,r.product)}>Raise</button></td></tr>)}
      </tbody></table></div>
    </section>
  </>
}
