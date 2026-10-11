import { daysAgoIST } from '../time'
import { useEffect, useState } from 'react'
import { api } from '../api'
import { ScopeFilters, ScopeValues, appendScope } from '../components/ScopeFilters'
import { PageHeader, money, num, pct } from '../components/UI'
const lastCompletedDay = daysAgoIST
const emptyScope:ScopeValues={plant:[],productGroup:[],customerId:[],productId:[]}
export default function MIS(){
  const [editing,setEditing]=useState<any>(null); const [actualEdit,setActualEdit]=useState(''); const [reasonEdit,setReasonEdit]=useState(''); const [saving,setSaving]=useState(false); const [d,setD]=useState(lastCompletedDay()); const [rows,setRows]=useState<any[]>([]); const [msg,setMsg]=useState('')
  const [scope,setScope]=useState<ScopeValues>(emptyScope); const [options,setOptions]=useState<any>({}); const [products,setProducts]=useState<any[]>([])
  useEffect(()=>{Promise.all([api('/masters/filter-options'),api('/masters/products')]).then(([o,p]:any)=>{setOptions(o);setProducts(p)})},[])
  async function load(){const q=appendScope(new URLSearchParams({mis_date:d}),scope);setRows(await api(`/mis?${q}`))}
  useEffect(()=>{load().catch(e=>setMsg(e.message))},[d,scope.plant,scope.productGroup,scope.customerId,scope.productId])
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
  return <><PageHeader title="MIS Entry / Historical Edit" subtitle="Plant/group filtered daily MIS. Baseline plan is preserved and all actual corrections are audited." actions={<input type="date" value={d} onChange={e=>setD(e.target.value)}/>}/>
    <ScopeFilters value={scope} onChange={setScope} options={options} products={products}/>
    {msg&&<div className="notice">{msg}</div>}
    {editing&&<section className="panel"><div className="panel-title"><h2>Correct Actual — {editing.product}</h2><button className="secondary small" onClick={()=>setEditing(null)}>Cancel</button></div><p>Date: {d} • Previous actual: {num(editing.actual_qty)} • Baseline plan: {num(editing.baseline_plan_qty)}</p><div className="form-row"><label>Revised actual<input type="number" min="0" step="1" value={actualEdit} onChange={e=>setActualEdit(e.target.value)}/></label><label>Change reason<input required value={reasonEdit} onChange={e=>setReasonEdit(e.target.value)} placeholder="Reason for correction"/></label><button type="button" disabled={saving||!reasonEdit.trim()} onClick={saveCorrection}>{saving?'Saving…':'Save audited correction'}</button></div></section>}
    <section className="panel"><div className="table-wrap"><table><thead><tr><th>Plant</th><th>Group</th><th>Product</th><th>Baseline Plan</th><th>Current Req.</th><th>Actual</th><th>Gap</th><th>Tonnage MT</th><th>Price</th><th>Sales Gap</th><th>Ach.</th><th></th></tr></thead><tbody>
    {rows.map(r=><tr key={r.id}><td>{r.plant||'—'}</td><td>{r.product_group||'—'}</td><td><b>{r.product}</b></td><td>{num(r.baseline_plan_qty)}</td><td>{num(r.current_plan_qty)}</td><td>{num(r.actual_qty)}</td><td className={r.gap_qty<0?'neg':'pos'}>{num(r.gap_qty)}</td><td>{num(r.actual_tonnage_mt)}</td><td>{money(r.sales_price)}</td><td className={r.gap_sales<0?'neg':'pos'}>{money(r.gap_sales)}</td><td>{pct(r.achievement)}</td><td><button className="small" onClick={()=>edit(r)}>Edit actual</button></td></tr>)}
    </tbody></table></div></section></>
}
