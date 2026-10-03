import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import ProcessFlowMonitor from '../components/ProcessFlowMonitor'
import { ScopeFilters, ScopeValues } from '../components/ScopeFilters'
import { PageHeader, num } from '../components/UI'
function today(){return new Date().toISOString().slice(0,10)}
const emptyScope:ScopeValues={plant:[],productGroup:[],customerId:[],productId:[]}
export default function Process(){
 const [products,setProducts]=useState<any[]>([]); const [options,setOptions]=useState<any>({}); const [scope,setScope]=useState<ScopeValues>(emptyScope); const [pid,setPid]=useState(''); const [fromD,setFromD]=useState(today()); const [toD,setToD]=useState(today()); const [flow,setFlow]=useState<any>(null); const [data,setData]=useState<any>(null); const [msg,setMsg]=useState('')
 useEffect(()=>{Promise.all([api('/masters/products'),api('/masters/filter-options')]).then(([p,o]:any)=>{setProducts(p);setOptions(o)})},[])
 const eligible=useMemo(()=>products.filter(p=>(!scope.plant.length||scope.plant.includes(String(p.plant||'')))&&(!scope.productGroup.length||scope.productGroup.includes(String(p.product_group||'')))&&(!scope.customerId.length||scope.customerId.includes(String(p.customer_id)))),[products,scope])
 useEffect(()=>{if(scope.productId.length===1){setPid(scope.productId[0])}else if(!eligible.some(p=>String(p.id)===pid)){setPid(eligible[0]?String(eligible[0].id):'')}},[scope.productId,eligible])
 async function load(){try{if(fromD>toD){setMsg('From date must be on or before To date.');return}if(pid){const f:any=await api(`/flows/monitor?product_id=${pid}&monitor_date=${toD}&start_date=${fromD}&end_date=${toD}`);setFlow(f);setData(f.flow?null:await api(`/process/monitor?product_id=${pid}&monitor_date=${toD}&start_date=${fromD}`));setMsg('')}else{setData(null);setFlow(null)}}catch(e:any){setMsg(e.message)}}
 useEffect(()=>{load()},[pid,fromD,toD])
 const isRange=fromD!==toD
 async function enter(o:any){if(isRange){setMsg('Select a single date to enter or correct actual quantities.');return}const actual=prompt(`Actual quantity for ${o.operation}`,String(o.actual_qty));if(actual==null)return;const reject=prompt('Reject quantity','0')||'0';await api('/process/entry',{method:'POST',body:JSON.stringify({summary_date:toD,product_id:Number(pid),route_operation_id:o.route_operation_id,plan_qty:o.plan_qty,actual_qty:Number(actual),good_qty:Math.max(0,Number(actual)-Number(reject)),reject_qty:Number(reject),opening_wip:0,closing_wip:0,source:'MANUAL'})});setMsg(`${o.operation} updated.`);load()}
 return <><PageHeader title="Process Monitor" subtitle="Average stage performance across the selected working-day period; OFF days are excluded." actions={<div className="form-row compact"><select value={pid} onChange={e=>setPid(e.target.value)}>{eligible.map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</select><label>From<input type="date" value={fromD} onChange={e=>setFromD(e.target.value)}/></label><label>To<input type="date" value={toD} onChange={e=>setToD(e.target.value)}/></label></div>}/>
 <ScopeFilters value={scope} onChange={setScope} options={options} products={products}/>
 {msg&&<div className="notice">{msg}</div>}
 {!pid&&<div className="empty">No product matches the selected Plant / Customer / Product Group.</div>}
 {flow?.flow&&<ProcessFlowMonitor data={flow} date={toD} productId={Number(pid)} onChange={load}/>}
 {data?.period&&<div className="notice">{data.period.working_days} working day(s) in the selected period; {data.period.off_days} OFF day(s) excluded.</div>}
 <section className="route-flow">{(data?.operations||[]).map((o:any,i:number)=><div className={`route-step ${o.gap_qty<0?'risk':''}`} key={o.route_operation_id}><div className="seq">{i+1}</div><h3>{o.operation}</h3><span>{o.operation_type.replaceAll('_',' ')}</span><div className="metric"><b>{num(o.actual_qty)}</b><small>{isRange?'Average actual':'Actual'} / {isRange?'Avg plan':'Plan'} {num(o.plan_qty)}</small></div><div className={o.gap_qty<0?'neg':'pos'}>{isRange?'Average gap':'Gap'} {num(o.gap_qty)}</div><div>{isRange?'Avg reject':'Reject'} {num(o.reject_qty||0)}</div><div>Data days {o.days_with_data??(o.actual_qty!=null?1:0)} / {data?.period?.working_days??1}</div><div>WIP from previous {num(o.calculated_wip_from_previous)}</div><div>Open actions {o.open_actions}</div>{!isRange&&<button className="small secondary" onClick={()=>enter(o)}>Enter actual</button>}{i<(data?.operations?.length||0)-1&&<div className="arrow">→</div>}</div>)}</section></>
}
