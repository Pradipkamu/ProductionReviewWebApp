import { useEffect, useState } from 'react'
import { api } from '../api'
import { ScopeFilters, ScopeValues, appendScope } from '../components/ScopeFilters'
import { PageHeader, money, num, pct } from '../components/UI'
function today(){return new Date().toISOString().slice(0,10)}
const emptyScope:ScopeValues={plant:[],productGroup:[],customerId:[],productId:[]}
export default function MIS(){
  const [d,setD]=useState(today()); const [rows,setRows]=useState<any[]>([]); const [msg,setMsg]=useState('')
  const [scope,setScope]=useState<ScopeValues>(emptyScope); const [options,setOptions]=useState<any>({}); const [products,setProducts]=useState<any[]>([])
  useEffect(()=>{Promise.all([api('/masters/filter-options'),api('/masters/products')]).then(([o,p]:any)=>{setOptions(o);setProducts(p)})},[])
  async function load(){const q=appendScope(new URLSearchParams({mis_date:d}),scope);setRows(await api(`/mis?${q}`))}
  useEffect(()=>{load().catch(e=>setMsg(e.message))},[d,scope.plant,scope.productGroup,scope.customerId,scope.productId])
  async function edit(r:any){ const val=prompt(`Actual qty for ${r.product}`,String(r.actual_qty)); if(val==null)return; const reason=prompt('Reason for correction / change'); if(!reason)return; await api(`/mis/${r.id}`,{method:'PUT',body:JSON.stringify({actual_qty:Number(val),reason})}); setMsg('MIS updated with audit history.'); load() }
  return <><PageHeader title="MIS Entry / Historical Edit" subtitle="Plant/group filtered daily MIS. Baseline plan is preserved and all actual corrections are audited." actions={<input type="date" value={d} onChange={e=>setD(e.target.value)}/>}/>
    <ScopeFilters value={scope} onChange={setScope} options={options} products={products}/>
    {msg&&<div className="notice">{msg}</div>}<section className="panel"><div className="table-wrap"><table><thead><tr><th>Plant</th><th>Group</th><th>Product</th><th>Baseline Plan</th><th>Current Req.</th><th>Actual</th><th>Gap</th><th>Tonnage MT</th><th>Price</th><th>Sales Gap</th><th>Ach.</th><th></th></tr></thead><tbody>
    {rows.map(r=><tr key={r.id}><td>{r.plant||'—'}</td><td>{r.product_group||'—'}</td><td><b>{r.product}</b></td><td>{num(r.baseline_plan_qty)}</td><td>{num(r.current_plan_qty)}</td><td>{num(r.actual_qty)}</td><td className={r.gap_qty<0?'neg':'pos'}>{num(r.gap_qty)}</td><td>{num(r.actual_tonnage_mt)}</td><td>{money(r.sales_price)}</td><td className={r.gap_sales<0?'neg':'pos'}>{money(r.gap_sales)}</td><td>{pct(r.achievement)}</td><td><button className="small" onClick={()=>edit(r)}>Edit actual</button></td></tr>)}
    </tbody></table></div></section></>
}
