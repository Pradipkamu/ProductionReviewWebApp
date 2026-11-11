import { dateIST } from '../time'
import { Link } from 'react-router-dom'
import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import { Kpi, PageHeader, num, pct } from '../components/UI'
import { MultiSelect } from '../components/MultiSelect'

function today(){return dateIST()}
const emptyEntry={shift_duration_min:480,planned_break_min:45,downtime_min:0,good_count:0,reject_count:0,ideal_cycle_time_sec:0,remarks:''}
const emptyLoss={loss_category_id:'',duration_min:0,qty_loss:0,remark:''}

export default function OEE(){
 const [allMachines,setAllMachines]=useState<any[]>([]),[machines,setMachines]=useState<any[]>([]),[products,setProducts]=useState<any[]>([]),[lossCategories,setLossCategories]=useState<any[]>([]),[routes,setRoutes]=useState<any[]>([])
 const [m,setM]=useState(''),[p,setP]=useState(''),[op,setOp]=useState(''),[d,setD]=useState(today()),[shift,setShift]=useState('A')
 const [sum,setSum]=useState<any>(null),[context,setContext]=useState<any>(null),[entryId,setEntryId]=useState<number|null>(null)
 const [operators,setOperators]=useState<any[]>([]),[operatorName,setOperatorName]=useState(''),[operatorId,setOperatorId]=useState<number|null>(null),[operatorBusy,setOperatorBusy]=useState(false)
 const [entry,setEntry]=useState<any>(emptyEntry),[losses,setLosses]=useState<any[]>([emptyLoss]),[reason,setReason]=useState(''),[msg,setMsg]=useState(''),[error,setError]=useState(''),[lossDialog,setLossDialog]=useState<number|null>(null),[lossCorrectionReason,setLossCorrectionReason]=useState(''),[savedSummary,setSavedSummary]=useState<any>(null)
 const [mgmt,setMgmt]=useState<any>(null),[fromDate,setFromDate]=useState(today().slice(0,8)+'01')
 const selectedProduct=products.find(x=>String(x.id)===p),selectedMachine=machines.find(x=>String(x.id)===m),selectedRoute=routes.find(x=>String(x.route_operation_id)===op)

 useEffect(()=>{Promise.all([api('/masters/machines'),api('/masters/products'),api('/masters/loss-categories'),api('/personnel')]).then(([ms,ps,ls,ops]:any[])=>{setAllMachines(ms);setMachines(ms.filter((x:any)=>x.active));setProducts(ps);setLossCategories(ls);setOperators(ops);if(ps[0])setP(String(ps[0].id));setLosses([emptyLoss])}).catch((e:any)=>setError(e.message))},[])
 useEffect(()=>{if(!p)return;api(`/masters/routes/${p}?on_date=${d}`).then((versions:any)=>{const active=versions.find((v:any)=>v.effective_from<=d&&(!v.effective_to||v.effective_to>=d))||versions[0];const ops=active?.operations||[];setRoutes(ops);setOp(ops[0]?String(ops[0].route_operation_id):'')}).catch((e:any)=>setError(e.message))},[p,d])
 useEffect(()=>{if(!op)return;api(`/oee/available-machines?route_operation_id=${op}&production_date=${d}`).then((r:any)=>{const available=r.mapped===false?[]:(r.machines||[]);setMachines(available);setM(old=>available.some((x:any)=>String(x.id)===old)?old:(available[0]?String(available[0].id):''));if(r.warning)setMsg(r.warning);if(!available.length)setM('')}).catch((e:any)=>setError(e.message))},[op,d,allMachines])

 async function loadContext(editExisting=false){
  if(!p||!op||!m)return
  try{
   const r:any=await api(`/oee/entry-context?product_id=${p}&route_operation_id=${op}&machine_id=${m}&production_date=${d}&shift=${shift}`)
   setContext(r);setError('')
   if(editExisting&&r.existing_entry){
    const x=r.existing_entry
    setEntryId(x.id)
    setOperatorId(x.operator_id||null);setOperatorName(x.operator_name||'')
    setEntry({shift_duration_min:x.shift_duration_min,planned_break_min:x.planned_break_min,downtime_min:x.downtime_min,good_count:x.good_count,reject_count:x.reject_count,ideal_cycle_time_sec:x.ideal_cycle_time_sec,remarks:x.remarks||''})
    setLosses([...(r.existing_losses||[]).map((x:any)=>({...x,loss_category_id:String(x.loss_category_id),saved:true})),{...emptyLoss}])
    setReason('')
    setMsg(`Editing saved entry #${x.id}. Enter a correction reason before saving.`)
   }else{
    setEntryId(null)
    setOperatorId(null);setOperatorName('')
    setEntry({...emptyEntry,ideal_cycle_time_sec:r.ideal_cycle_time_sec||0})
    setLosses([{...emptyLoss}])
    setReason('')
   }
  }catch(e:any){setContext(null);setEntryId(null);setError(e.message)}
 }
 async function refresh(){if(!m)return;try{const q=new URLSearchParams({machine_id:m,summary_date:d,shift});if(p)q.set('product_id',p);if(op)q.set('route_operation_id',op);setSum(await api(`/oee/machine-summary?${q}`))}catch(e:any){setError(e.message)}}
 useEffect(()=>{loadContext();refresh()},[m,p,op,d,shift])
 async function loadManagement(){try{const q=new URLSearchParams({from_date:fromDate,to_date:d});if(p)q.set('product_id',p);setMgmt(await api(`/oee/management-summary?${q}`))}catch(e:any){setError(e.message)}}
 useEffect(()=>{loadManagement()},[fromDate,d,p])

 const clientWarnings=useMemo(()=>{
  const rows:string[]=[];if(Number(entry.good_count)<0||Number(entry.reject_count)<0)rows.push('Production quantities cannot be negative.');return rows
 },[entry,sum])
 async function save(){
  if(!p||!op||!m){setError('Select product, operation and machine.');return}
  if(!operatorId){setError('Select or add an operator name before saving.');return}
  if(entryId&&!reason.trim()){setError('Enter a correction reason to update the existing shift entry.');return}
  try{
   const completed=losses.filter((x:any)=>!x.saved&&x.loss_category_id&&Number(x.duration_min)>0);
   const lossPayload=completed.map((x:any)=>({loss_date:d,shift,product_id:Number(p),route_operation_id:Number(op),machine_id:Number(m),loss_category_id:Number(x.loss_category_id),duration_min:Number(x.duration_min),qty_loss:Number(x.qty_loss||0),remark:x.remark||''}));
   const body={entry:{...entry,downtime_min:0,production_date:d,shift,product_id:Number(p),route_operation_id:Number(op),machine_id:Number(m),operator_id:operatorId},losses:lossPayload,...(entryId?{entry_id:entryId,correction_reason:reason}:{})};
   const r:any=await api('/oee/machine-entry-with-losses',{method:'POST',body:JSON.stringify(body)});
   const good=Number(entry.good_count||0),reject=Number(entry.reject_count||0),total=good+reject;
   const planned=Math.max(0,Number(entry.shift_duration_min||0)-Number(entry.planned_break_min||0));
   const availabilityLoss=losses.reduce((n:number,x:any)=>n+(x.saved?0:(lossCategories.find((z:any)=>String(z.id)===String(x.loss_category_id))?.component==='AVAILABILITY'?Number(x.duration_min||0):0)),0);
   const run=Math.max(0,planned-availabilityLoss),availability=planned?run/planned:0;
   const performance=run&&Number(entry.ideal_cycle_time_sec)>0?Math.min(1,(Number(entry.ideal_cycle_time_sec)*total/60)/run):0;
   const quality=total?good/total:0;
   setSavedSummary({title:entryId?'Production correction saved':'Production entry saved',id:r.entry?.id||entryId,oee:availability*performance*quality,availability,performance,quality,good,reject,total,loss:availabilityLoss,warnings:r.warnings||[]});
   setEntryId(null);setReason('');setError('');setOperatorId(null);setOperatorName('');
   setEntry({...emptyEntry,planned_break_min:0,ideal_cycle_time_sec:context?.ideal_cycle_time_sec||0});setLosses([{...emptyLoss}]);
   await refresh();
  }catch(e:any){setError(e.message)}
 }
 async function addOperator(){
  const fullName=operatorName.trim().replace(/\s+/g,' ')
  if(fullName.split(' ').length<2){setError('Enter at least first name and surname.');return}
  setOperatorBusy(true)
  try{
   const r:any=await api('/personnel',{method:'POST',body:JSON.stringify({first_name:fullName.split(/\s+/)[0],last_name:fullName.split(/\s+/).slice(1).join(" ")})})
   setOperators(old=>old.some(x=>x.id===r.id)?old:[...old,{id:r.id,full_name:r.full_name}])
   setOperatorId(r.id);setOperatorName(r.full_name);setError('');setMsg(r.duplicate_warning?'A person with the same name already exists. Please verify identity before continuing. New record added.':'Operator added to the shared Personnel Master.')
  }catch(e:any){setError(e.message)}finally{setOperatorBusy(false)}
 }
 function startOperatorVoice(){
  const w=window as any;const Speech=w.SpeechRecognition||w.webkitSpeechRecognition
  if(!Speech){setError('Voice typing is not supported in this browser. Use your keyboard microphone instead.');return}
  const recognition=new Speech();recognition.lang='en-IN';recognition.interimResults=false;recognition.maxAlternatives=1
  recognition.onresult=(event:any)=>{const value=event.results?.[0]?.[0]?.transcript||'';setOperatorName(value);const match=operators.find(x=>x.full_name.toLowerCase()===value.trim().replace(/\s+/g,' ').toLowerCase());setOperatorId(match?.id||null)}
  recognition.onerror=()=>setError('Voice recognition failed. Please type the operator name.')
  recognition.start()
 }
 function updateLoss(index:number,patch:any){
  setLosses(old=>{const next=old.map((x,i)=>i===index?{...x,...patch}:x);const last=next[next.length-1];if(last&&!last.saved&&last.loss_category_id&&Number(last.duration_min)>0)next.push({...emptyLoss});return next})
 }
 async function saveLossDialog(){
  if(lossDialog===null)return
  const loss=losses[lossDialog];if(!loss)return
  if(!loss.loss_category_id||Number(loss.duration_min)<=0){setError('Select a loss reason and enter a duration greater than zero.');return}
  if(loss.saved){
   if(lossCorrectionReason.trim().length<5){setError('Enter a correction reason of at least 5 characters to update this saved loss.');return}
   const category=lossCategories.find((x:any)=>String(x.id)===String(loss.loss_category_id))
   const payload={loss_date:d,shift,product_id:Number(p),route_operation_id:Number(op),machine_id:Number(m),loss_category_id:Number(loss.loss_category_id),duration_min:Number(loss.duration_min),qty_loss:Number(loss.qty_loss||0),remark:loss.remark||''}
   try{sessionStorage.setItem('changeReason',lossCorrectionReason.trim());await api(`/oee/loss-events/${loss.id}`,{method:'PUT',body:JSON.stringify(payload)});setLosses(old=>old.map((x,i)=>i===lossDialog?{...x,category:category?.name||x.category,component:category?.component||x.component}:x));setLossCorrectionReason('');setError('');setMsg(`Loss event #${loss.id} updated with an audit reason.`);await refresh();setLossDialog(null)}
   catch(e:any){setError(e.message)}finally{sessionStorage.removeItem('changeReason')}
  }else{setLossDialog(null);setError('')}
 }
 async function raiseOeeAction(){try{const r:any=await api('/oee/raise-action',{method:'POST',body:JSON.stringify({production_date:d,shift,product_id:Number(p),route_operation_id:Number(op),machine_id:Number(m),target_oee:.85})});setMsg(`${r.action_no} ${r.status==='already_linked'?'is already open':'created with a standard Why-Why plan'}`);await refresh()}catch(e:any){setError(e.message)}}
 async function raiseLossAction(id:number){try{const r:any=await api(`/oee/loss-events/${id}/raise-action`,{method:'POST',body:JSON.stringify({priority:'HIGH'})});setMsg(`${r.action_no} ${r.status==='already_linked'?'is already linked':'created with a standard Why-Why plan'}`);await refresh()}catch(e:any){setError(e.message)}}
 const s=sum?.summary
 return <>
  <PageHeader title="Machine / OEE" subtitle="Capture one controlled record per machine, product, operation and shift; reconcile losses and raise standard action plans from the same page." actions={<div className="form-row compact"><input aria-label="Production date" type="date" value={d} onChange={e=>setD(e.target.value)}/><select aria-label="Shift" value={shift} onChange={e=>setShift(e.target.value)}><option>A</option><option>B</option><option>C</option></select></div>}/>
  <section className="panel oee-scope"><div className="filters"><label>Product<MultiSelect singleSelect value={p?[p]:[]} onChange={v=>setP(v.at(-1)||'')} placeholder="Select Product" options={products.map(x=>({value:String(x.id),label:x.name}))}/></label><label>Operation<MultiSelect singleSelect value={op?[op]:[]} onChange={v=>setOp(v.at(-1)||'')} placeholder="Select Operation" options={routes.map(x=>({value:String(x.route_operation_id),label:`${x.sequence_no}. ${x.operation}`}))}/></label><label>Mapped machine<MultiSelect singleSelect value={m?[m]:[]} onChange={v=>setM(v.at(-1)||'')} placeholder="Select Machine" options={machines.map(x=>({value:String(x.id),label:`${x.code} — ${x.name}`}))}/></label></div><p className="muted">{selectedProduct?.name||'Product'} → {selectedRoute?.operation||'Operation'} → {selectedMachine?.code||'Machine'} • Effective ideal cycle: <b>{context?.ideal_cycle_time_sec??'missing'} sec/part</b></p>{context?.warnings?.map((x:string)=><div className="warning-box" key={x}>{x}</div>)}</section>
  {error&&<div className="error" role="alert">{error}</div>}{msg&&<div className="notice" role="status">{msg}</div>}
  {p&&op&&m&&<section className="oee-live-hero"><div><small>LIVE ENTRY OEE</small><strong>{pct((()=>{const planned=Math.max(0,Number(entry.shift_duration_min||0)-Number(entry.planned_break_min||0));const loss=losses.reduce((n:number,x:any)=>n+(!x.saved&&lossCategories.find((z:any)=>String(z.id)===String(x.loss_category_id))?.component==='AVAILABILITY'?Number(x.duration_min||0):0),0);const run=Math.max(0,planned-loss);const total=Number(entry.good_count||0)+Number(entry.reject_count||0);return (planned?run/planned:0)*(run&&Number(entry.ideal_cycle_time_sec)>0?Math.min(1,Number(entry.ideal_cycle_time_sec)*total/60/run):0)*(total?Number(entry.good_count||0)/total:0)})())}</strong></div><div className="oee-live-metrics"><span>Availability <b>{pct((()=>{const p=Math.max(0,Number(entry.shift_duration_min||0)-Number(entry.planned_break_min||0));const l=losses.reduce((n:number,x:any)=>n+(!x.saved&&lossCategories.find((z:any)=>String(z.id)===String(x.loss_category_id))?.component==='AVAILABILITY'?Number(x.duration_min||0):0),0);return p?Math.max(0,p-l)/p:0})())}</b></span><span>Good / Reject <b>{num(entry.good_count)} / {num(entry.reject_count)}</b></span></div></section>}
  {s&&<><div className="kpi-grid"><Kpi label="OEE" value={pct(s.oee_reported)} tone={s.oee_reported<.6?'bad':s.oee_reported<.85?'warn':'good'}/><Kpi label="Availability" value={pct(s.availability)}/><Kpi label="Performance" value={pct(s.performance_raw)} tone={s.performance_master_warning?'warn':'neutral'}/><Kpi label="Quality" value={pct(s.quality)}/><Kpi label="Availability loss classified" value={`${num(s.captured_loss_min)} min`}/><Kpi label="Downtime unclassified" value={`${num(s.unclassified_loss_min)} min`} tone={s.unclassified_loss_min>0?'bad':'good'}/></div>{s.overclassified_loss_min>0&&<div className="error">Availability loss events exceed entered downtime by {num(s.overclassified_loss_min)} minutes. Correct the entry or loss records.</div>}{s.shared_shift_time_conflict_count>0&&<div className="warning-box">Shared machine-shift time differs across product records in {s.shared_shift_time_conflict_count} shift group(s). The summary counts machine time once using the maximum recorded values; reconcile the product rows.</div>}</>}
  <section className="panel">
   <div className="panel-title"><div><h2>Machine shift production</h2><p>{entryId?`Loaded entry #${entryId}. Saving requires an audited correction reason.`:'Enter good and rejected quantities; total output and availability downtime are calculated automatically.'}</p></div></div>
   <div className="oee-entry-grid">
    <label className="span-2">Operator name
     <input list="oee-operator-options" value={operatorName} onChange={e=>{const value=e.target.value;setOperatorName(value);const match=operators.find(x=>x.full_name.toLowerCase()===value.trim().replace(/\s+/g,' ').toLowerCase());setOperatorId(match?.id||null)}} placeholder="Type first name and surname"/>
     <datalist id="oee-operator-options">{operators.map(x=><option key={x.id} value={x.full_name}/>)}</datalist>
     <span className="button-row"><button type="button" className="secondary small" onClick={startOperatorVoice}>Voice type</button>{!operatorId&&operatorName.trim().split(/\s+/).filter(Boolean).length>=2&&<button type="button" className="small" onClick={addOperator} disabled={operatorBusy}>{operatorBusy?'Adding…':`Add “${operatorName.trim()}”`}</button>}</span>
     {operatorId&&<small className="muted">Registered operator selected</small>}
    </label>
    <label>Shift duration (min)<input type="number" min="1" value={entry.shift_duration_min} onChange={e=>setEntry({...entry,shift_duration_min:Number(e.target.value)})}/></label>
    <label>Planned break (min)<input type="number" min="0" value={entry.planned_break_min} onChange={e=>setEntry({...entry,planned_break_min:Number(e.target.value)})}/></label>
    <label>Good quantity<input type="number" min="0" value={entry.good_count} onChange={e=>setEntry({...entry,good_count:Number(e.target.value)})}/></label>
    <label>Rejected quantity<input type="number" min="0" value={entry.reject_count} onChange={e=>setEntry({...entry,reject_count:Number(e.target.value)})}/></label>
    <label>Total production (calculated)<input value={num(Number(entry.good_count||0)+Number(entry.reject_count||0))} readOnly/></label>
    <label>Ideal cycle (master)<input value={entry.ideal_cycle_time_sec} readOnly/></label>
    <label className="span-2">Shift remarks<textarea value={entry.remarks} onChange={e=>setEntry({...entry,remarks:e.target.value})}/></label>
    {entryId&&<label className="span-2">Correction reason<input value={reason} onChange={e=>setReason(e.target.value)} placeholder="Required when changing the saved entry"/></label>}
   </div>
   <div className="oee-loss-list">
    <div className="panel-title"><div><h3>Machine losses</h3><p>Add each loss reason and its duration. A new row appears after completing the current one.</p></div></div>
    {losses.map((x:any,i:number)=><button type="button" className="oee-loss-row" key={x.id||i} onClick={()=>setLossDialog(i)}>
      <span><b>{x.saved?`Recorded Loss Event #${x.id}`:`Loss Event ${i+1}`}</b><small>{x.saved?x.category:(lossCategories.find((z:any)=>String(z.id)===String(x.loss_category_id))?.name||'Select loss reason')} · {num(x.duration_min)} min</small></span><strong>{x.saved?'EDIT':'ADD / EDIT'} →</strong>
    </button>)}
    {lossDialog!==null&&losses[lossDialog]&&(()=>{const x=losses[lossDialog];return <div className="oee-dialog-backdrop" role="presentation" onMouseDown={e=>{if(e.target===e.currentTarget)setLossDialog(null)}}><section className="oee-dialog" role="dialog" aria-modal="true" aria-labelledby="loss-dialog-title">
      <header><span>PRODUCTION REVIEW</span><button type="button" aria-label="Close" onClick={()=>setLossDialog(null)}>×</button></header>
      <div className="oee-dialog-body"><small>MACHINE DOWNTIME CAPTURE</small><h3 id="loss-dialog-title">{x.saved?'EDIT MACHINE LOSS':'ADD MACHINE LOSS'}</h3>
      {x.saved&&<><p className="warning-box">Editing recorded loss #{x.id}. A correction reason is required.</p><label>Correction reason<input value={lossCorrectionReason} onChange={e=>setLossCorrectionReason(e.target.value)} placeholder="Explain why this loss is being corrected"/></label></>}
      <label>Loss reason<select value={x.loss_category_id} onChange={e=>updateLoss(lossDialog,{loss_category_id:e.target.value})}><option value="">Select loss reason</option>{lossCategories.map((v:any)=><option key={v.id} value={String(v.id)}>{v.name} — {v.component}</option>)}</select></label>
      <label>Duration (minutes)<input type="number" min="0" step="0.1" value={x.duration_min||''} onChange={e=>updateLoss(lossDialog,{duration_min:Number(e.target.value)})}/></label>
      <label>Reason / details<textarea value={x.remark||''} onChange={e=>updateLoss(lossDialog,{remark:e.target.value})} placeholder="Describe the breakdown or loss"/></label>
      <div className="oee-dialog-actions">{!x.saved&&losses.length>1&&<button type="button" className="secondary" onClick={()=>{setLosses(old=>old.filter((_,j)=>j!==lossDialog));setLossDialog(null)}}>REMOVE</button>}<button type="button" className="secondary" onClick={()=>setLossDialog(null)}>CANCEL</button><button type="button" onClick={saveLossDialog}>SAVE LOSS</button></div>
      </div></section></div>})()}
    <p className="muted">Availability-category loss minutes are used as machine downtime. Performance and Quality losses are recorded separately.</p>
    <p><b>Total Availability downtime:</b> {num(losses.reduce((n:number,x:any)=>n+(x.component==='AVAILABILITY'?Number(x.duration_min||0):(!x.saved&&lossCategories.find((z:any)=>String(z.id)===String(x.loss_category_id))?.component==='AVAILABILITY'?Number(x.duration_min||0):0)),0))} min</p>
   </div>
   {clientWarnings.map(x=><div className="warning-box" key={x}>{x}</div>)}
   <div className="button-row"><button onClick={save}>{entryId?'Save audited correction':'Save production and losses'}</button><button className="secondary" onClick={raiseOeeAction} disabled={!s}>Raise OEE action</button></div>
  </section>
  {savedSummary&&<div className="oee-dialog-backdrop" role="presentation"><section className="oee-dialog oee-success-dialog" role="dialog" aria-modal="true"><header><span>PRODUCTION REVIEW</span></header><div className="oee-dialog-body"><small>RECORD CONFIRMATION</small><h3>{savedSummary.title}</h3>{savedSummary.id&&<p>Production entry #{savedSummary.id}</p>}<div className="oee-success-score"><small>OVERALL OEE</small><strong>{pct(savedSummary.oee)}</strong></div><div className="oee-success-grid">{[['Availability',savedSummary.availability],['Performance',savedSummary.performance],['Quality',savedSummary.quality]].map(([label,value]:any)=><div key={label}><small>{label}</small><b>{pct(value)}</b></div>)}</div><p>Good: <b>{num(savedSummary.good)}</b> · Rejected: <b>{num(savedSummary.reject)}</b> · Total: <b>{num(savedSummary.total)}</b></p><p>Availability loss: <b>{num(savedSummary.loss)} min</b></p>{savedSummary.warnings.map((w:string)=><p className="warning-box" key={w}>{w}</p>)}<div className="oee-dialog-actions"><button onClick={()=>setSavedSummary(null)}>OK</button></div></div></section></div>}
  <section className="panel"><div className="panel-title"><div><h2>Loss reconciliation and actions</h2><p>Classify every downtime minute; raise an action for major or recurring losses.</p></div><Link to="/actions">Open action register</Link></div><div className="table-wrap"><table><thead><tr><th>Loss</th><th>OEE component</th><th>Minutes</th><th>Qty loss</th><th>Remark</th><th>Action</th></tr></thead><tbody>{(sum?.losses||[]).map((x:any)=><tr key={x.id}><td><b>{x.category}</b></td><td>{x.component}</td><td>{num(x.duration_min)}</td><td>{num(x.qty_loss)}</td><td>{x.remark||'—'}</td><td>{x.action_no?<Link to="/actions">{x.action_no} · {x.action_status}</Link>:<button className="small" onClick={()=>raiseLossAction(x.id)}>Raise action</button>}</td></tr>)}{!sum?.losses?.length&&<tr><td colSpan={6} className="muted">No loss events for this selected scope.</td></tr>}</tbody></table></div></section>
  <section className="panel"><div className="panel-title"><div><h2>OEE Management — Trend & Loss Pareto</h2><p>Period performance across machines using the same controlled shift records.</p></div><div className="form-row compact"><input aria-label="OEE from date" type="date" value={fromDate} onChange={e=>setFromDate(e.target.value)}/><button className="secondary" onClick={loadManagement}>Refresh</button></div></div>
  {mgmt&&<><div className="kpi-grid"><Kpi label="Period OEE" value={pct(mgmt.overall?.oee_reported)}/><Kpi label="Availability" value={pct(mgmt.overall?.availability)}/><Kpi label="Performance" value={pct(mgmt.overall?.performance_raw)}/><Kpi label="Quality" value={pct(mgmt.overall?.quality)}/><Kpi label="Shift Records" value={mgmt.entry_count||0}/><Kpi label="Loss Events" value={mgmt.loss_event_count||0}/><Kpi label="Machines Below 85%" value={mgmt.below_target_machine_count||0} tone={mgmt.below_target_machine_count?'bad':'good'}/><Kpi label="Recurring Losses" value={mgmt.recurring_loss_count||0} tone={mgmt.recurring_loss_count?'warn':'good'}/></div>
  <div className="two-col"><div className="table-wrap"><table><thead><tr><th>Machine</th><th>Records</th><th>A</th><th>P</th><th>Q</th><th>OEE</th><th>Target status</th></tr></thead><tbody>{(mgmt.machines||[]).map((x:any)=><tr key={x.machine_id}><td><b>{x.machine}</b></td><td>{x.entry_count}</td><td>{pct(x.availability)}</td><td>{pct(x.performance_raw)}</td><td>{pct(x.quality)}</td><td><b>{pct(x.oee_reported)}</b></td><td><b className={x.status==='BELOW TARGET'?'neg':''}>{x.status}</b>{x.gap_to_target>0&&<><br/><small>{pct(x.gap_to_target)} gap</small></>}</td></tr>)}{!mgmt.machines?.length&&<tr><td colSpan={7} className="muted">No OEE records in this period.</td></tr>}</tbody></table></div>
  {mgmt.recurring_losses?.length>0&&<div className="warning-box"><b>Recurring losses needing action:</b> {mgmt.recurring_losses.map((x:any)=>`${x.category} (${x.events} events)`).join(', ')}</div>}
  <div className="table-wrap"><table><thead><tr><th>Loss</th><th>Component</th><th>Events</th><th>Minutes</th><th>Qty loss</th></tr></thead><tbody>{(mgmt.loss_pareto||[]).slice(0,10).map((x:any)=><tr key={x.category}><td><b>{x.category}</b></td><td>{x.component||'—'}</td><td>{x.events}</td><td>{num(x.minutes)}</td><td>{num(x.qty_loss)}</td></tr>)}{!mgmt.loss_pareto?.length&&<tr><td colSpan={5} className="muted">No classified losses in this period.</td></tr>}</tbody></table></div></div>
  <div className="table-wrap"><table><thead><tr><th>Date</th><th>A</th><th>P</th><th>Q</th><th>OEE</th></tr></thead><tbody>{(mgmt.trend||[]).map((x:any)=><tr key={x.date}><td>{x.date}</td><td>{pct(x.availability)}</td><td>{pct(x.performance_raw)}</td><td>{pct(x.quality)}</td><td><b>{pct(x.oee_reported)}</b></td></tr>)}</tbody></table></div></>}</section>
  <section className="panel"><div className="panel-title"><div><h2>Saved OEE records</h2><p>One row per selected machine, product, operation and shift.</p></div><Link to={`/insights?kind=oee&from_date=${d}&to_date=${d}&machine_id=${m}`}>Open drill-down</Link></div><div className="table-wrap"><table><thead><tr><th>ID</th><th>Operator</th><th>Total</th><th>Good</th><th>Reject</th><th>Downtime</th><th>Cycle</th><th>A</th><th>P</th><th>Q</th><th>OEE</th><th>Action</th></tr></thead><tbody>{(sum?.entries||[]).map((x:any)=><tr key={x.id}><td>#{x.id}</td><td>{x.operator_name||'—'}</td><td>{num(x.total_count)}</td><td>{num(x.good_count)}</td><td>{num(x.reject_count)}</td><td>{num(x.downtime_min)} min</td><td>{num(x.ideal_cycle_time_sec)} sec</td><td>{pct(x.availability)}</td><td className={x.performance_master_warning?'neg':''}>{pct(x.performance_raw)}</td><td>{pct(x.quality)}</td><td><b>{pct(x.oee_reported)}</b></td><td><button type="button" className="small secondary" onClick={()=>loadContext(true)}>Edit</button></td></tr>)}{!sum?.entries?.length&&<tr><td colSpan={12} className="muted">No shift entry saved yet.</td></tr>}</tbody></table></div></section>
 </>
}
