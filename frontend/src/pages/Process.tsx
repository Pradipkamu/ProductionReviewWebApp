import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import { ScopeFilters, ScopeValues } from '../components/ScopeFilters'
import { PageHeader, num } from '../components/UI'
function today(){return new Date().toISOString().slice(0,10)}
const emptyScope:ScopeValues={plant:[],productGroup:[],customerId:[],productId:[]}
export default function Process(){
 const [products,setProducts]=useState<any[]>([]); const [options,setOptions]=useState<any>({}); const [scope,setScope]=useState<ScopeValues>(emptyScope); const [pid,setPid]=useState(''); const [d,setD]=useState(today()); const [data,setData]=useState<any>(null); const [msg,setMsg]=useState('')
 useEffect(()=>{Promise.all([api('/masters/products'),api('/masters/filter-options')]).then(([p,o]:any)=>{setProducts(p);setOptions(o)})},[])
 const eligible=useMemo(()=>products.filter(p=>(!scope.plant.length||scope.plant.includes(String(p.plant||'')))&&(!scope.productGroup.length||scope.productGroup.includes(String(p.product_group||'')))&&(!scope.customerId.length||scope.customerId.includes(String(p.customer_id)))),[products,scope])
 useEffect(()=>{if(scope.productId.length===1){setPid(scope.productId[0])}else if(!eligible.some(p=>String(p.id)===pid)){setPid(eligible[0]?String(eligible[0].id):'')}},[scope.productId,eligible])
 async function load(){if(pid)setData(await api(`/process/monitor?product_id=${pid}&monitor_date=${d}`));else setData(null)}
 useEffect(()=>{load()},[pid,d])
 async function enter(o:any){const actual=prompt(`Actual quantity for ${o.operation}`,String(o.actual_qty));if(actual==null)return;const reject=prompt('Reject quantity','0')||'0';await api('/process/entry',{method:'POST',body:JSON.stringify({summary_date:d,product_id:Number(pid),route_operation_id:o.route_operation_id,plan_qty:o.plan_qty,actual_qty:Number(actual),good_qty:Math.max(0,Number(actual)-Number(reject)),reject_qty:Number(reject),opening_wip:0,closing_wip:0,source:'MANUAL'})});setMsg(`${o.operation} updated.`);load()}
 return <><PageHeader title="Process Monitor" subtitle="Plant and product-group filtered route monitoring from first operation to dispatch." actions={<div className="form-row compact"><select value={pid} onChange={e=>setPid(e.target.value)}>{eligible.map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</select><input type="date" value={d} onChange={e=>setD(e.target.value)}/></div>}/>
 <ScopeFilters value={scope} onChange={setScope} options={options} products={products}/>
 {msg&&<div className="notice">{msg}</div>}
 {!pid&&<div className="empty">No product matches the selected Plant / Customer / Product Group.</div>}
 <section className="route-flow">{(data?.operations||[]).map((o:any,i:number)=><div className={`route-step ${o.gap_qty<0?'risk':''}`} key={o.route_operation_id}><div className="seq">{i+1}</div><h3>{o.operation}</h3><span>{o.operation_type.replaceAll('_',' ')}</span><div className="metric"><b>{num(o.actual_qty)}</b><small>Actual / Plan {num(o.plan_qty)}</small></div><div className={o.gap_qty<0?'neg':'pos'}>Gap {num(o.gap_qty)}</div><div>WIP from previous {num(o.calculated_wip_from_previous)}</div><div>Open actions {o.open_actions}</div><button className="small secondary" onClick={()=>enter(o)}>Enter actual</button>{i<(data?.operations?.length||0)-1&&<div className="arrow">→</div>}</div>)}</section></>
}
