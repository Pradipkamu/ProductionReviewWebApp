import { useEffect, useState } from 'react'
import { api } from '../api'
import { MultiSelect } from './MultiSelect'
import { num } from './UI'
type ProcessPoint={id:number,label:string,plan:number,actual:number,compliance:number|null,gap:number}

function ProcessPlanActualAchievementChart({rows,onSelect}:{rows:ProcessPoint[],onSelect?:(row:ProcessPoint)=>void}){
 if(!rows.length)return <div className="empty">No data for this period.</div>
 const labelDepth=Math.max(90,Math.ceil(Math.max(...rows.map(r=>r.label.length))*7)+24)
 const W=Math.max(820,rows.length*96),H=300+labelDepth-58,pad={l:58,r:68,t:22,b:labelDepth}
 const innerW=W-pad.l-pad.r,innerH=H-pad.t-pad.b
 const qtyMax=Math.max(1,...rows.flatMap(r=>[r.plan,r.actual]))
 const pctVals=rows.filter(r=>r.compliance!=null).map(r=>Number(r.compliance)*100)
 const rawPctMax=Math.max(...pctVals,100)
 const pctStep=rawPctMax<=125?25:Math.max(25,Math.ceil((rawPctMax/5)/25)*25)
 const pctMax=Math.max(125,Math.ceil(rawPctMax/pctStep)*pctStep)
 const pctTicks=Array.from({length:Math.floor(pctMax/pctStep)+1},(_,i)=>i*pctStep)
 if(!pctTicks.includes(100))pctTicks.push(100)
 pctTicks.sort((a,b)=>a-b)
 const group=innerW/rows.length,bw=Math.min(20,group*.3)
 const cx=(i:number)=>pad.l+group*i+group/2
 const yQty=(v:number)=>pad.t+innerH-(Math.max(0,v)/qtyMax)*innerH
 const yPct=(v:number)=>pad.t+innerH-(Math.max(0,Math.min(pctMax,v))/pctMax)*innerH
 const achievementRows=rows.map((r,i)=>({r,i})).filter(x=>x.r.compliance!=null)
 const pts=achievementRows.map(({r,i})=>`${cx(i)},${yPct(Number(r.compliance)*100)}`).join(' ')
 return <div className="svg-scroll"><svg className="report-svg" width={W} height={H} viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="xMidYMid meet" style={{width:W,height:H,minWidth:'100%'}}>
   {[0,.25,.5,.75,1].map(t=>{const yy=pad.t+innerH-t*innerH;return <g key={t}><line x1={pad.l} y1={yy} x2={W-pad.r} y2={yy} className="grid-line"/><text x={pad.l-8} y={yy+4} textAnchor="end" className="axis-text">{num(qtyMax*t)}</text></g>})}
   {pctTicks.map(v=><text key={`pct-${v}`} x={W-pad.r+10} y={yPct(v)+4} textAnchor="start" className="axis-text">{v}%</text>)}
   <line x1={pad.l} y1={yPct(100)} x2={W-pad.r} y2={yPct(100)} className="target-line"/>
   {rows.map((r,i)=>{const x=cx(i),ph=innerH*(r.plan/qtyMax),ah=innerH*(r.actual/qtyMax);return <g key={r.id} role="button" tabIndex={0} onClick={()=>onSelect?.(r)} onKeyDown={e=>{if(e.key==='Enter')onSelect?.(r)}} style={{cursor:'pointer'}}>
     <rect x={x-bw-2} y={yQty(r.plan)} width={bw} height={Math.max(0,ph)} rx="3" className="chart-plan"><title>{`${r.label} Plan: ${num(r.plan)}`}</title></rect>
     <rect x={x+2} y={yQty(r.actual)} width={bw} height={Math.max(0,ah)} rx="3" className="chart-actual"><title>{`${r.label} Actual: ${num(r.actual)}${r.compliance==null?'':` • Achievement: ${(Number(r.compliance)*100).toFixed(1)}%`}`}</title></rect>
     <text x={x-bw/2-2} y={Math.max(11,yQty(r.plan)-5)} textAnchor="middle" className="data-label">{num(r.plan)}</text>
     <text x={x+bw/2+2} y={Math.max(11,yQty(r.actual)-5)} textAnchor="middle" className="data-label">{num(r.actual)}</text>
     <text x={x} y={pad.t+innerH+14} transform={`rotate(-90 ${x} ${pad.t+innerH+14})`} textAnchor="end" className="axis-text"><title>{r.label}</title>{r.label}</text>
   </g>})}
   {pts&&<polyline points={pts} fill="none" className="compliance-line"/>}
   {achievementRows.map(({r,i})=>{const v=Number(r.compliance)*100;return <g key={`ach-${r.id}`} role="button" tabIndex={0} onClick={()=>onSelect?.(r)} onKeyDown={e=>{if(e.key==='Enter')onSelect?.(r)}} style={{cursor:'pointer'}}>
     <circle cx={cx(i)} cy={yPct(v)} r="4.5" className={v>=100?'dot-good':v>=90?'dot-watch':'dot-bad'}><title>{`${r.label}: ${v.toFixed(1)}%`}</title></circle>
     <text x={cx(i)} y={Math.max(11,yPct(v)-9)} textAnchor="middle" className="data-label">{v.toFixed(1)}%</text>
   </g>})}
   <line x1={pad.l} y1={pad.t+innerH} x2={W-pad.r} y2={pad.t+innerH} className="axis-line"/>
   <line x1={W-pad.r} y1={pad.t} x2={W-pad.r} y2={pad.t+innerH} className="axis-line"/>
   <text x={W-10} y={pad.t-7} textAnchor="end" className="axis-text">Achievement %</text>
 </svg></div>
}

export default function ProcessFlowMonitor({data,date,productId,onChange}:{data:any,date:string,productId:number,onChange:()=>void}){
 const [branches,setBranches]=useState<string[]>([]),[variants,setVariants]=useState<string[]>([]),[selected,setSelected]=useState<any>(null),[actual,setActual]=useState(''),[reject,setReject]=useState('0'),[reason,setReason]=useState(''),[error,setError]=useState(''),[busy,setBusy]=useState(false)
 useEffect(()=>{setSelected(null);setBranches([]);setVariants([])},[data.flow.id,date,data.period?.start])
 const isRange=Boolean(data.period?.is_range)
 const active=data.stages.filter((s:any)=>s.active)
 const options=(field:string)=>[...new Set<string>(active.map((s:any)=>String(s[field]||'')))].filter(Boolean).map(value=>({value,label:value}))
 const stages=active.filter((s:any)=>(!branches.length||branches.includes(s.branch))&&(!variants.length||variants.includes(s.variant)))
 const points=stages.filter((s:any)=>s.plan!=null&&s.actual!=null).map((s:any)=>({id:s.id,label:s.name,plan:s.plan,actual:s.actual,compliance:s.plan>0?s.actual/s.plan:null,gap:s.actual-s.plan}))
 function choose(s:any){setSelected(s);setActual(s.actual==null?'':String(s.actual));setReject(String(s.reject||0));setReason('');setError('')}
 function chooseGraph(s:any){if(isRange&&selected?.id===s?.id){setSelected(null);return}choose(s)}
 async function save(){setBusy(true);setError('');try{await api('/process/entry',{method:'POST',body:JSON.stringify({summary_date:date,product_id:productId,route_operation_id:selected.route_operation_id,plan_qty:selected.plan||0,actual_qty:Number(actual),good_qty:Number(actual)-Number(reject),reject_qty:Number(reject),opening_wip:0,closing_wip:0,remarks:reason,source:'MANUAL'})});setSelected(null);onChange()}catch(e:any){setError(e.message)}finally{setBusy(false)}}
 return <section className="panel"><h2>Approved process flow R{data.flow.revision}</h2><p>Effective {data.flow.effective_from}. {isRange?'Plan, actual and rejection are working-day averages for the selected period. OFF days and missing actual days are not treated as zero.':'Each stage has its own allocation. Parent dispatch alone feeds MIS. Blank plan or actual means missing data.'}</p>{data.period&&<div className="notice">{data.period.working_days} working day(s) included • {data.period.off_days} OFF day(s) excluded{data.period.truncated_to_flow?' • Period starts at this flow revision effective date':''}</div>}<div className="form-row"><MultiSelect value={branches} onChange={setBranches} options={options('branch')} placeholder="All branches"/><MultiSelect value={variants} onChange={setVariants} options={options('variant')} placeholder="All variants"/></div>
 <div className="panel-title"><h3>Process Plan vs Actual + Achievement %</h3><span>{isRange?'Working-day average':'Selected day'} • bars = Plan/Actual • line = Achievement % on right axis • target 100%</span></div>
 <PlanActualAchievementChart rows={points} metric="qty" verticalLabels onSelect={r=>chooseGraph(stages.find((s:any)=>s.id===r.id))}/>
 {selected&&isRange&&<div className="panel"><div className="panel-title"><div><h3>{selected.name} — Plan vs Actual</h3><p>{data.period?.start} to {data.period?.end} • working days only</p></div><button className="small secondary" onClick={()=>setSelected(null)}>Close</button></div>
 <div className="table-wrap" aria-label={`Plan versus actual by date for ${selected.name}`}><table><thead><tr><th>Quantity</th>{(selected.daily||[]).map((d:any)=><th key={d.date}>{new Date(d.date+'T00:00:00').toLocaleDateString('en-IN',{day:'2-digit',month:'short'})}</th>)}</tr></thead><tbody>
 <tr><th>Plan</th>{(selected.daily||[]).map((d:any)=><td key={`p-${d.date}`}>{d.plan==null?'Pending':num(d.plan)}</td>)}</tr>
 <tr><th>Actual</th>{(selected.daily||[]).map((d:any)=><td key={`a-${d.date}`}>{d.actual==null?'Missing':num(d.actual)}</td>)}</tr>
 </tbody></table></div></div>}
 <div className="table-wrap"><table><thead><tr><th>Stage / Source</th><th>Branch / Variant</th><th>Role / Vendor</th><th>Predecessors</th><th>Allocated</th><th>{isRange?'Avg plan':'Daily plan'}</th><th>{isRange?'Avg actual':'Actual'}</th><th>{isRange?'Avg reject':'Reject'}</th><th>Data days</th><th></th></tr></thead><tbody>{stages.map((s:any)=><tr key={s.id}><td><b>{s.name}</b><br/>{s.code} ({s.source_column}){s.parent_dispatch&&<small>Parent MIS dispatch</small>}</td><td>{s.branch}<br/>{s.variant}</td><td>{s.role}<br/>{s.vendor|| (s.role.startsWith('VENDOR')?'Vendor pending':'')}</td><td>{s.predecessors.join(', ')||'Start'}</td><td>{s.allocated_qty==null?'Pending':num(s.allocated_qty)}<br/>{s.allocation_reference}</td><td>{s.plan==null?'Pending':num(s.plan)}</td><td>{s.actual==null?'Missing':num(s.actual)}</td><td>{s.reject==null?'—':num(s.reject)}</td><td>{s.days_with_data??(s.actual==null?0:1)}{data.period?' / '+data.period.working_days:''}</td><td>{!isRange&&<button className="small secondary" onClick={()=>choose(s)}>Enter actual</button>}</td></tr>)}</tbody></table></div>
 {selected&&!isRange&&<div className="panel"><h3>{selected.name}: {date}</h3><div className="form-row"><label>Actual pieces<input type="number" min="0" step="1" value={actual} onChange={e=>setActual(e.target.value)}/></label><label>Rejected pieces<input type="number" min="0" step="1" value={reject} onChange={e=>setReject(e.target.value)}/></label><label>Correction reason<input value={reason} onChange={e=>setReason(e.target.value)}/></label><button disabled={busy||actual===''} onClick={save}>Save actual</button><button className="secondary" onClick={()=>setSelected(null)}>Cancel</button></div>{error&&<p className="error">{error}</p>}</div>}
 <details><summary>Deferred and reference columns</summary><ul>{data.stages.filter((s:any)=>!s.active).map((s:any)=><li key={s.id}>{s.source_column}: {s.name}{s.alias_of?` (alias of ${s.alias_of})`:''}</li>)}</ul></details></section>
}
