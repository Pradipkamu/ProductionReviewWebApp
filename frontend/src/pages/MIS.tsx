import { daysAgoIST } from '../time'
import { useEffect, useState } from 'react'
import { api } from '../api'
import { ScopeFilters, ScopeValues, appendScope } from '../components/ScopeFilters'
import { PageHeader, money, num, pct } from '../components/UI'
const lastCompletedDay = daysAgoIST
const emptyScope:ScopeValues={plant:[],productGroup:[],customerId:[],productId:[]}
export default function MIS(){
  const [offProductIds,setOffProductIds]=useState<number[]>([]);const [offLoaded,setOffLoaded]=useState(false);
  const [adding,setAdding]=useState(false);const [newProduct,setNewProduct]=useState('');const [newQty,setNewQty]=useState('');const [newReason,setNewReason]=useState('');
  const [editing,setEditing]=useState<any>(null); const [actualEdit,setActualEdit]=useState(''); const [reasonEdit,setReasonEdit]=useState(''); const [saving,setSaving]=useState(false); const [d,setD]=useState(lastCompletedDay()); const [rows,setRows]=useState<any[]>([]); const [msg,setMsg]=useState('')
  const [scope,setScope]=useState<ScopeValues>(emptyScope); const [options,setOptions]=useState<any>({}); const [products,setProducts]=useState<any[]>([])
  useEffect(()=>{Promise.all([api('/masters/filter-options'),api('/masters/products')]).then(([o,p]:any)=>{setOptions(o);setProducts(p)})},[])
  async function load(){const q=appendScope(new URLSearchParams({mis_date:d}),scope);setRows(await api(`/mis?${q}`))}
  useEffect(()=>{load().catch(e=>setMsg(e.message))},[d,scope.plant,scope.productGroup,scope.customerId,scope.productId])
  useEffect(()=>{
    let active=true
    setOffLoaded(false);setAdding(false);setNewProduct('')
    api(`/mis/off-day-products?mis_date=${d}`).then((r:any)=>{
      if(active){setOffProductIds(r.off_product_ids||[]);setOffLoaded(true)}
    }).catch((e:any)=>{if(active){setOffProductIds([]);setOffLoaded(false);setMsg(e.message)}})
    return()=>{active=false}
  },[d])
  const filteredOffProducts=products.filter((p:any)=>
    offProductIds.includes(Number(p.id))&&
    (!scope.plant.length||scope.plant.includes(String(p.plant||'')))&&
    (!scope.productGroup.length||scope.productGroup.includes(String(p.product_group||'')))&&
    (!scope.customerId.length||scope.customerId.includes(String(p.customer_id||'')))&&
    (!scope.productId.length||scope.productId.includes(String(p.id)))&&
    !rows.some((r:any)=>String(r.product_id)===String(p.id)))
  useEffect(()=>{
    if(newProduct&&!filteredOffProducts.some((p:any)=>String(p.id)===newProduct)){
      setNewProduct('');setAdding(false)
    }
  },[newProduct,scope,offProductIds,rows])
  function edit(r:any){setEditing(r);setActualEdit(String(r.actual_qty??0));setReasonEdit('');setMsg('')}
  async function saveCorrection(){
    if(!editing||saving)return
    const quantity=Number(actualEdit)
    if(actualEdit.trim()===''||!Number.isFinite(quantity)||quantity<0){setMsg('Enter a non-negative actual quantity.');return}
    if(!reasonEdit.trim()){setMsg('A correction reason is required.');return}
    setSaving(true)
    try{
      await api(`/mis/${editing.id}`,{method:'PUT',body:JSON.stringify({actual_qty:quantity,reason:reasonEdit.trim()})})
      setEditing(null);setMsg('MIS corrected with audit history.');await load()
    }catch(e:any){setMsg(e.message)}finally{setSaving(false)}
  }
  async function saveUnscheduled(){
    const qty=Number(newQty)
    if(!newProduct||!newQty.trim()||!Number.isFinite(qty)||qty<=0||!newReason.trim()){
      setMsg('Choose a product, enter a positive dispatch quantity and a reason.');return
    }
    setSaving(true)
    try{
      const result:any=await api('/mis/dispatch-on-off-day',{method:'POST',body:JSON.stringify({
        mis_date:d,product_id:Number(newProduct),actual_qty:qty,reason:newReason.trim(),
      })})
      setMsg(result.price_missing?'Dispatch saved with zero plan, but no effective sales price was found; check the Sales Price Master.':'Unscheduled dispatch saved with zero plan and audit history.')
      setAdding(false);setNewQty('');setNewReason('');await load()
    }catch(e:any){setMsg(e.message)}finally{setSaving(false)}
  }
  return <><PageHeader title="MIS Entry / Historical Edit" subtitle="Plant/group filtered daily MIS. Baseline plan is preserved and all actual corrections are audited." actions={<input type="date" value={d} onChange={e=>setD(e.target.value)}/>}/>
    <ScopeFilters value={scope} onChange={setScope} options={options} products={products}/>
    {msg&&<div className="notice">{msg}</div>}
    {offLoaded&&filteredOffProducts.length>0&&<section className="panel"><div className="panel-title"><div><h2>Unscheduled / Holiday Dispatch</h2><p>Record actual dispatch on an OFF day without altering the holiday calendar or the approved plan.</p></div><button type="button" className="secondary" onClick={()=>setAdding(!adding)}>{adding?'Cancel':'Add unscheduled dispatch'}</button></div>
    {adding&&<div className="form-row"><label>Product / Part<select value={newProduct} onChange={e=>setNewProduct(e.target.value)}><option value="">Select product</option>{filteredOffProducts.map((p:any)=><option key={p.id} value={p.id}>{p.code} — {p.name}</option>)}</select></label><label>Actual dispatch qty<input type="number" min="0" step="1" value={newQty} onChange={e=>setNewQty(e.target.value)}/></label><label>Reason<input value={newReason} onChange={e=>setNewReason(e.target.value)} placeholder="Holiday dispatch / urgent customer requirement"/></label><button type="button" disabled={saving||!newProduct||!newReason.trim()} onClick={saveUnscheduled}>{saving?'Saving…':'Save unscheduled dispatch'}</button></div>}
    </section>}
    {editing&&<section className="panel"><div className="panel-title"><h2>Correct Actual — {editing.product}</h2><button className="secondary small" onClick={()=>setEditing(null)}>Cancel</button></div><p>Date: {d} • Previous actual: {num(editing.actual_qty)} • Baseline plan: {num(editing.baseline_plan_qty)}</p><div className="form-row"><label>Revised actual<input type="number" min="0" step="1" value={actualEdit} onChange={e=>setActualEdit(e.target.value)}/></label><label>Change reason<input required value={reasonEdit} onChange={e=>setReasonEdit(e.target.value)} placeholder="Reason for correction"/></label><button type="button" disabled={saving||!reasonEdit.trim()} onClick={saveCorrection}>{saving?'Saving…':'Save audited correction'}</button></div></section>}
    <section className="panel"><div className="table-wrap"><table><thead><tr><th>Plant</th><th>Group</th><th>Product</th><th>Baseline Plan</th><th>Current Req.</th><th>Actual</th><th>Gap</th><th>Tonnage MT</th><th>Price</th><th>Sales Gap</th><th>Ach.</th><th></th></tr></thead><tbody>
    {rows.map(r=><tr key={r.id}><td>{r.plant||'—'}</td><td>{r.product_group||'—'}</td><td><b>{r.product}</b></td><td>{num(r.baseline_plan_qty)}</td><td>{num(r.current_plan_qty)}</td><td>{num(r.actual_qty)}</td><td className={r.gap_qty<0?'neg':'pos'}>{num(r.gap_qty)}</td><td>{num(r.actual_tonnage_mt)}</td><td>{money(r.sales_price)}</td><td className={r.gap_sales<0?'neg':'pos'}>{money(r.gap_sales)}</td><td>{pct(r.achievement)}</td><td><button className="small" onClick={()=>edit(r)}>Edit actual</button></td></tr>)}
    </tbody></table></div></section></>
}
