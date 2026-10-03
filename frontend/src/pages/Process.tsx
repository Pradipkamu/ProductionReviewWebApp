import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import ProcessFlowMonitor from '../components/ProcessFlowMonitor'
import { ScopeFilters, ScopeValues } from '../components/ScopeFilters'
import { PageHeader, num } from '../components/UI'
function dateText(d:Date){return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`}
function today(){return dateText(new Date())}
function monthStart(){const d=new Date();return dateText(new Date(d.getFullYear(),d.getMonth(),1))}
const emptyScope:ScopeValues={plant:[],productGroup:[],customerId:[],productId:[]}
export default function Process(){
 const [products,setProducts]=useState<any[]>([]); const [options,setOptions]=useState<any>({}); const [scope,setScope]=useState<ScopeValues>(emptyScope); const [pid,setPid]=useState(''); const [from,setFrom]=useState(monthStart()); const [to,setTo]=useState(today()); const [flow,setFlow]=useState<any>(null); const [data,setData]=useState<any>(null); const [msg,setMsg]=useState('')
 useEffect(()=>{Promise.all([api('/masters/products'),api('/masters/filter-options')]).then(([p,o]:any)=>{setProducts(p);setOptions(o)})},[])
 const eligible=useMemo(()=>products.filter(p=>(!scope.plant.length||scope.plant.includes(String(p.plant||'')))&&(!scope.productGroup.length||scope.productGroup.includes(String(p.product_group||'')))&&(!scope.customerId.length||scope.customerId.includes(String(p.customer_id)))),[products,scope])
 useEffect(()=>{if(scope.productId.length===1){setPid(scope.productId[0])}else if(!eligible.some(p=>String(p.id)===pid)){setPid(eligible[0]?String(eligible[0].id):'')}},[scope.productId,eligible])
 const singleDay=from===to
 async function load(){
  if(!from||!to||from>to){setMsg('Select a From date on or before the To date.');setFlow(null);setData(null);return}
  setMsg('')
  try{if(pid){const q=new URLSearchParams({product_id:pid,monitor_date:to,from_date:from,to_date:to});const f:any=await api(`/flows/monitor?${q}`);setFlow(f);setData(f.flow?null:await api(`/process/monitor?${q}`))}else{setData(null);setFlow(null)}}catch(e:any){setFlow(null);setData(null);setMsg(e.message)}
 }
 useEffect(()=>{load()},[pid,from,to])
 async function enter(o:any){if(!singleDay)return;const actual=prompt(`Actual quantity for ${o.operation}`,String(o.actual_qty));if(actual==null)return;const reject=prompt('Reject quantity','0')||'0';await api('/process/entry',{method:'POST',body:JSON.stringify({summary_date:to,product_id:Number(pid),route_operation_id:o.route_operation_id,plan_qty:o.plan_qty,actual_qty:Number(actual),good_qty:Math.max(0,Number(actual)-Number(reject)),reject_qty:Number(reject),opening_wip:0,closing_wip:0,source:'MANUAL'})});setMsg(`${o.operation} updated.`);load()}
 return <><PageHeader title="Process Monitor" subtitle="Select dates to sum stage plan and actual quantities across the period." actions={<div className="form-row compact"><select value={pid} onChange={e=>setPid(e.target.value)}>{eligible.map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</select><label>From<input type="date" value={from} onChange={e=>setFrom(e.target.value)}/></label><label>To<input type="date" value={to} onChange={e=>setTo(e.target.value)}/></label></div>}/>
 <ScopeFilters value={scope} onChange={setScope} options={options} products={products}/>
 {msg&&<div className="notice">{msg}</div>}
 {!pid&&<div className="empty">No product matches the selected Plant / Customer / Product Group.</div>}
 {flow?.flow&&<ProcessFlowMonitor data={flow} date={to} canEdit={singleDay} productId={Number(pid)} onChange={load}/>}
 {data?.operations?.length>0&&<p className="muted">Totals for {from} to {to}. Plan and actual day counts show incomplete coverage. {singleDay?'':'Select the same From and To date to enter an actual.'}</p>}
 <section className="route-flow">{(data?.operations||[]).map((o:any,i:number)=><div className={`route-step ${o.gap_qty<0?'risk':''}`} key={o.route_operation_id}><div className="seq">{i+1}</div><h3>{o.operation}</h3><span>{o.operation_type.replaceAll('_',' ')}</span><div className="metric"><b>{num(o.actual_qty)}</b><small>Actual / Plan {num(o.plan_qty)}</small></div><small>Days: plan {o.plan_days}/{data.period_days}, actual {o.actual_days}/{data.period_days}</small><div className={o.gap_qty<0?'neg':'pos'}>Gap {num(o.gap_qty)}</div>{singleDay&&o.calculated_wip_from_previous!=null&&<div>WIP from previous {num(o.calculated_wip_from_previous)}</div>}<div>Open actions {o.open_actions}</div>{singleDay&&<button className="small secondary" onClick={()=>enter(o)}>Enter actual</button>}{i<(data?.operations?.length||0)-1&&<div className="arrow">→</div>}</div>)}</section></>
}
