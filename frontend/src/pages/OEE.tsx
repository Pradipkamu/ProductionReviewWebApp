import { useSearchParams } from 'react-router-dom'
import { dateIST } from '../time'
import { Link } from 'react-router-dom'
import { useEffect, useMemo, useState } from 'react'
import { api, downloadApi } from '../api'
import { Kpi, PageHeader, num, pct } from '../components/UI'
import { MultiSelect } from '../components/MultiSelect'

function today(){return dateIST()}
const emptyEntry={shift_duration_min:440,planned_break_min:45,downtime_min:0,good_count:0,reject_count:0,ideal_cycle_time_sec:0,remarks:''}
const emptyLoss={loss_category_id:'',duration_min:0,qty_loss:0,remark:''}

export default function OEE(){
 const [workspaceParams]=useSearchParams()
 const view=workspaceParams.get('view')||'entry'
 const views=[{key:'entry',label:'OEE Entry'},{key:'loss',label:'Loss Review'},{key:'reports',label:'OEE Reports'},{key:'history',label:'OEE History'}]

 const [allMachines,setAllMachines]=useState<any[]>([]),[machines,setMachines]=useState<any[]>([]),[mappingChecked,setMappingChecked]=useState(false),[products,setProducts]=useState<any[]>([]),[lossCategories,setLossCategories]=useState<any[]>([]),[routes,setRoutes]=useState<any[]>([]),[routesLoadedKey,setRoutesLoadedKey]=useState('')
 const [m,setM]=useState(workspaceParams.get('machine_id')||''),[p,setP]=useState(workspaceParams.get('product_id')||''),[op,setOp]=useState(workspaceParams.get('route_operation_id')||''),[d,setD]=useState(workspaceParams.get('date')||today()),[shift,setShift]=useState(workspaceParams.get('shift')||'A')
 const [sum,setSum]=useState<any>(null),[context,setContext]=useState<any>(null),[entryId,setEntryId]=useState<number|null>(null),[afmsLive,setAfmsLive]=useState<any>(null),[afmsLiveBusy,setAfmsLiveBusy]=useState(false)
 const [operators,setOperators]=useState<any[]>([]),[operatorName,setOperatorName]=useState(''),[operatorId,setOperatorId]=useState<number|null>(null),[operatorBusy,setOperatorBusy]=useState(false)
 const [entry,setEntry]=useState<any>(emptyEntry),[losses,setLosses]=useState<any[]>([emptyLoss]),[reason,setReason]=useState(''),[msg,setMsg]=useState(''),[error,setError]=useState(''),[lossDialog,setLossDialog]=useState<number|null>(null),[lossCorrectionReason,setLossCorrectionReason]=useState(''),[savedSummary,setSavedSummary]=useState<any>(null)
 const [mgmt,setMgmt]=useState<any>(null),[fromDate,setFromDate]=useState(today().slice(0,8)+'01'),[lossCategoryFilter,setLossCategoryFilter]=useState(''),[compliance,setCompliance]=useState<any>(null),[complianceBusy,setComplianceBusy]=useState(false),[complianceError,setComplianceError]=useState('')
 const [bulkFile,setBulkFile]=useState<File|null>(null),[bulkPreview,setBulkPreview]=useState<any>(null),[bulkBusy,setBulkBusy]=useState(false),[bulkResult,setBulkResult]=useState<any>(null)
 const selectedProduct=products.find(x=>String(x.id)===p),selectedMachine=machines.find(x=>String(x.id)===m),selectedRoute=routes.find(x=>String(x.route_operation_id)===op)

 useEffect(()=>{Promise.all([api('/masters/machines'),api('/masters/products'),api('/masters/loss-categories'),api('/personnel')]).then(([ms,ps,ls,ops]:any[])=>{setAllMachines(ms);setMachines([]);setProducts(ps);setLossCategories(ls);setOperators(ops);if(!workspaceParams.get('product_id')&&ps[0])setP(String(ps[0].id));setLosses([emptyLoss])}).catch((e:any)=>setError(e.message))},[])
 useEffect(()=>{setRoutesLoadedKey('');if(!p){setRoutes([]);setOp('');setMachines([]);setM('');setMappingChecked(false);return}let cancelled=false;setRoutes([]);setOp('');setMachines([]);setM('');setMappingChecked(false);setContext(null);setSum(null);(async()=>{try{const versions:any=await api(`/masters/routes/${p}?on_date=${d}`);const active=versions.find((v:any)=>v.effective_from<=d&&(!v.effective_to||v.effective_to>=d))||versions[0];const ops=active?.operations||[];if(cancelled)return;setRoutes(ops);setOp(workspaceParams.get('route_operation_id')&&ops.some((x:any)=>String(x.route_operation_id)===workspaceParams.get('route_operation_id'))?workspaceParams.get('route_operation_id')!:(ops[0]?String(ops[0].route_operation_id):''));setRoutesLoadedKey(`${p}:${d}`);if(!ops.length)setMappingChecked(true)}catch(e:any){if(!cancelled)setError(e.message)}})();return()=>{cancelled=true}},[p,d])
 useEffect(()=>{if(routesLoadedKey!==`${p}:${d}`||!op){setMachines([]);setM('');setMappingChecked(false);return}setMappingChecked(false);setMachines([]);setM('');setContext(null);setSum(null);api(`/oee/available-machines?route_operation_id=${op}&production_date=${d}`).then((r:any)=>{const available=r.mapped===true&&Array.isArray(r.machines)?r.machines.filter((x:any)=>x.active!==false):[];setMachines(available);setM(workspaceParams.get('machine_id')&&available.some((x:any)=>String(x.id)===workspaceParams.get('machine_id'))?workspaceParams.get('machine_id')!:(available[0]?String(available[0].id):''));setMappingChecked(true);if(!available.length){setContext(null);setSum(null)}}).catch((e:any)=>{setMachines([]);setM('');setMappingChecked(true);setError(e.message)})},[op,d,allMachines,routesLoadedKey,p])

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
    setEntry({...emptyEntry,planned_break_min:0,ideal_cycle_time_sec:r.ideal_cycle_time_sec||0})
    setLosses([{...emptyLoss}])
    setReason('')
   }
  }catch(e:any){setContext(null);setEntryId(null);setError(e.message)}
 }
 async function refresh(){if(!m)return;try{const q=new URLSearchParams({machine_id:m,summary_date:d,shift});if(p)q.set('product_id',p);if(op)q.set('route_operation_id',op);setSum(await api(`/oee/machine-summary?${q}`))}catch(e:any){setError(e.message)}}
 useEffect(()=>{if(routesLoadedKey!==`${p}:${d}`||!p||!op||!m||!machines.some((x:any)=>String(x.id)===String(m)))return;loadContext();refresh()},[m,p,op,d,shift,routesLoadedKey,machines])
 useEffect(()=>{loadAfmsLive()},[m,d,shift])

 async function loadAfmsLive(){
  if(!m){setAfmsLive(null);return}
  setAfmsLiveBusy(true)
  try{
   const q=new URLSearchParams({machine_id:m,production_date:d,shift})
   setAfmsLive(await api(`/afms/oee/live?${q}`))
  }catch(e:any){
   setAfmsLive({status:'UNAVAILABLE',message:e.message||'Unable to read AFMS live collection.'})
  }finally{setAfmsLiveBusy(false)}
 }
 async function previewBulkImport(){
  if(!bulkFile){setError('Select the completed OEE Excel workbook first.');return}
  setBulkBusy(true);setBulkResult(null);setBulkPreview(null);setError('')
  try{const form=new FormData();form.append('file',bulkFile);const result=await api('/oee/bulk-import/preview',{method:'POST',body:form});setBulkPreview(result)}
  catch(e:any){setError(e.message)}finally{setBulkBusy(false)}
 }
 async function confirmBulkImport(){
  if(!bulkPreview?.valid||!bulkPreview?.commit_payload?.length)return
  if(!window.confirm(`Import ${bulkPreview.entry_count} OEE entries and ${bulkPreview.loss_event_count} loss events? Existing records will not be overwritten.`))return
  setBulkBusy(true);setError('')
  try{const result=await api('/oee/bulk-import/commit',{method:'POST',body:JSON.stringify({entries:bulkPreview.commit_payload})});setBulkResult(result);setBulkPreview(null);setBulkFile(null);await refresh();await loadManagement()}
  catch(e:any){setError(e.message)}finally{setBulkBusy(false)}
 }
 async function loadManagement(){try{const q=new URLSearchParams({from_date:fromDate,to_date:d});if(p)q.set('product_id',p);if(op)q.set('route_operation_id',op);if(m)q.set('machine_id',m);if(lossCategoryFilter)q.set('loss_category_id',lossCategoryFilter);setMgmt(await api(`/oee/management-summary?${q}`))}catch(e:any){setError(e.message)}}
 async function loadCompliance(){
  if(!fromDate||!d||fromDate>d){setCompliance(null);setComplianceError('From date must be on or before To date.');return}
  setComplianceBusy(true);setComplianceError('')
  try{const q=new URLSearchParams({from_date:fromDate,to_date:d});if(p)q.set('product_id',p);if(op)q.set('route_operation_id',op);if(m)q.set('machine_id',m);setCompliance(await api('/oee/reporting-compliance?'+q))}
  catch(e:any){setCompliance(null);setComplianceError(e.message||'Unable to load OEE reporting compliance.')}
  finally{setComplianceBusy(false)}
 }

 useEffect(()=>{loadManagement();loadCompliance()},[fromDate,d,p,op,m,lossCategoryFilter])

 const dailyLossCategories=useMemo(()=>Array.from(new Set((mgmt?.daily_loss_trend||[]).flatMap((day:any)=>(day.categories||[]).map((x:any)=>x.category)))),[mgmt])
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
  <PageHeader title="Machine / OEE" subtitle="Capture one controlled record per machine, product, operation and shift; reconcile losses and raise standard action plans from the same page." actions={<div className="form-row compact"><input aria-label="Production date" type="date" value={d} onChange={e=>setD(e.target.value)}/>
<select aria-label="Shift" value={shift} onChange={e=>setShift(e.target.value)}><option>A</option><option>B</option><option>C</option></select></div>}/>
 <nav className="quality-view-nav" aria-label="Machine / OEE workspace">{views.map(v=><a key={v.key} href={v.key==='entry'?'/oee':`/oee?view=${v.key}`} aria-current={view===v.key?'page':undefined} className={view===v.key?'active':''}>{v.label}</a>)}</nav>
  <section className="panel oee-scope"><div className="filters"><label>Product<MultiSelect singleSelect value={p?[p]:[]} onChange={v=>{setP(v.at(-1)||'');setOp('');setM('');setMachines([]);setRoutes([]);setRoutesLoadedKey('');setContext(null);setSum(null);setMappingChecked(false)}} placeholder="Select Product" options={products.map(x=>({value:String(x.id),label:x.name}))}/></label>{!!p&&routesLoadedKey===`${p}:${d}`&&<label>Operation<MultiSelect singleSelect value={op?[op]:[]} onChange={v=>setOp(v.at(-1)||'')} placeholder={routes.length?"Select Operation":"No operations configured"} options={routes.map(x=>({value:String(x.route_operation_id),label:`${x.sequence_no}. ${x.operation}`}))}/></label>}{!!op&&<label>Mapped machine<MultiSelect singleSelect value={m?[m]:[]} onChange={v=>setM(v.at(-1)||'')} placeholder={mappingChecked?(machines.length?"Select Machine":"No mapped machines"):"Loading machines…"} options={machines.map(x=>({value:String(x.id),label:`${x.code} — ${x.name}`}))}/></label>}</div>{mappingChecked&&op&&machines.length===0&&<div className="warning-box" role="status">No active machine is mapped to this operation for the selected date. You can still select the part and operation; configure the operation-to-machine mapping before entering OEE.</div>}{!!p&&routesLoadedKey===`${p}:${d}`&&!routes.length&&<div className="warning-box" role="status">No operations are configured for this product on the selected date. Configure the product route to continue.</div>}{machines.length>0&&<><p className="muted">{selectedProduct?.name||'Product'} → {selectedRoute?.operation||'Operation'} → {selectedMachine?.code||'Machine'} • Effective ideal cycle: <b>{context?.ideal_cycle_time_sec??'missing'} sec/part</b></p>{context?.warnings?.map((x:string)=><div className="warning-box" key={x}>{x}</div>)}</>}</section>
    {error&&<div className="error" role="alert">{error}</div>}{msg&&<div className="notice" role="status">{msg}</div>}

  {view==='entry'&&<>
{p&&op&&m&&machines.length>0&&<section className="oee-live-hero" aria-live="polite"><div><small>LIVE ENTRY OEE</small><strong>{pct((()=>{const planned=Math.max(0,Number(entry.shift_duration_min||0)-Number(entry.planned_break_min||0));const loss=losses.reduce((n:number,x:any)=>n+(!x.saved&&lossCategories.find((z:any)=>String(z.id)===String(x.loss_category_id))?.component==='AVAILABILITY'?Number(x.duration_min||0):0),0);const run=Math.max(0,planned-loss);const total=Number(entry.good_count||0)+Number(entry.reject_count||0);return (planned?run/planned:0)*(run&&Number(entry.ideal_cycle_time_sec)>0?Math.min(1,Number(entry.ideal_cycle_time_sec)*total/60/run):0)*(total?Number(entry.good_count||0)/total:0)})())}</strong></div><div className="oee-live-metrics"><span>Availability <b>{pct((()=>{const p=Math.max(0,Number(entry.shift_duration_min||0)-Number(entry.planned_break_min||0));const l=losses.reduce((n:number,x:any)=>n+(!x.saved&&lossCategories.find((z:any)=>String(z.id)===String(x.loss_category_id))?.component==='AVAILABILITY'?Number(x.duration_min||0):0),0);return p?Math.max(0,p-l)/p:0})())}</b></span><span>Good / Reject <b>{num(entry.good_count)} / {num(entry.reject_count)}</b></span></div></section>}
  

  {m&&<section className="panel">
   <div className="panel-title"><div><h2>AFMS automatic OEE collection</h2><p>Read-only live calculation from ESP32 shift telemetry. Existing manual OEE entries are not modified.</p></div><button type="button" className="secondary small" onClick={loadAfmsLive} disabled={afmsLiveBusy}>{afmsLiveBusy?'Refreshing…':'Refresh AFMS'}</button></div>
   {afmsLiveBusy&&!afmsLive&&<div className="muted">Reading latest AFMS telemetry…</div>}
   {afmsLive?.status==='READY'&&<>
    <div className="kpi-grid">
     <Kpi label="AFMS provisional OEE" value={pct(afmsLive.oee?.oee_reported)}/>
     <Kpi label="Availability" value={pct(afmsLive.oee?.availability)}/>
     <Kpi label="Performance" value={pct(afmsLive.oee?.performance_raw)} tone={afmsLive.oee?.performance_master_warning?'warn':'neutral'}/>
     <Kpi label="Quality" value={pct(afmsLive.oee?.quality)}/>
     <Kpi label="Total / Good / Reject" value={`${num(afmsLive.total_count)} / ${num(afmsLive.good_count)} / ${num(afmsLive.reject_count)}`}/>
     <Kpi label="OEE run time" value={`${num(afmsLive.oee?.run_time_min)} min`}/>
    </div>
    <p className="muted">Part: <b>{afmsLive.part_code} — {afmsLive.part_name}</b> · Operation: <b>{afmsLive.operation_name||'—'}</b> · Operator: <b>{afmsLive.operator_name||'Unassigned'}</b> · Ideal cycle from PRW master: <b>{afmsLive.ideal_cycle_time_sec} sec</b></p>
    {p&&afmsLive.product_id&&String(afmsLive.product_id)!==p&&<div className="warning-box">The ESP32 active part does not match the product selected above. This preview belongs to the ESP32 part shown here; verify the HMI part selection before using it for the selected OEE scope.</div>}
    {op&&afmsLive.route_operation_id&&String(afmsLive.route_operation_id)!==op&&<div className="warning-box">The ESP32-mapped operation does not match the selected operation above. Verify the part-to-operation mapping before using this preview.</div>}
    <p className="muted">Unclassified idle time: <b>{num(afmsLive.unclassified_idle_min)} min</b>. Idle is kept separate from measured breakdown downtime and is not silently classified as an availability loss.</p>
    {(afmsLive.warnings||[]).map((w:string)=><div className="warning-box" key={w}>{w}</div>)}
   </>}
   {afmsLive&&afmsLive.status!=='READY'&&<div className="warning-box">{afmsLive.message||`AFMS collection status: ${afmsLive.status.replaceAll('_',' ')}`}</div>}
   {afmsLive?.status==='READY'&&<p className="muted">Source: {afmsLive.device_uid} · Last event: {afmsLive.event_type} · {afmsLive.event_timestamp?new Date(afmsLive.event_timestamp+'Z').toLocaleString():''} · {afmsLive.is_live?'Live':(d===today()?'Stale':'Historical')} · Preview only; it is not yet posted to the official OEE shift register.</p>}
  </section>}

  {s&&m&&machines.length>0&&<><div className="kpi-grid"><Kpi label="OEE" value={pct(s.oee_reported)} tone={s.oee_reported<.6?'bad':s.oee_reported<.85?'warn':'good'}/><Kpi label="Availability" value={pct(s.availability)}/><Kpi label="Performance" value={pct(s.performance_raw)} tone={s.performance_master_warning?'warn':'neutral'}/><Kpi label="Quality" value={pct(s.quality)}/><Kpi label="Availability loss classified" value={`${num(s.captured_loss_min)} min`}/><Kpi label="Downtime unclassified" value={`${num(s.unclassified_loss_min)} min`} tone={s.unclassified_loss_min>0?'bad':'good'}/></div>{s.overclassified_loss_min>0&&<div className="error">Availability loss events exceed entered downtime by {num(s.overclassified_loss_min)} minutes. Correct the entry or loss records.</div>}{s.shared_shift_time_conflict_count>0&&<div className="warning-box">Shared machine-shift time differs across product records in {s.shared_shift_time_conflict_count} shift group(s). The summary counts machine time once using the maximum recorded values; reconcile the product rows.</div>}</>}
  {p&&op&&m&&machines.length>0&&<section className="panel">
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
    {losses.map((x:any,i:number)=>{
      const category=lossCategories.find((z:any)=>String(z.id)===String(x.loss_category_id))
      const cycle=Number(context?.ideal_cycle_time_sec||entry.ideal_cycle_time_sec||0)
      const calculatedQty=x.saved?Number(x.qty_loss||0):(category?.component==='AVAILABILITY'&&cycle>0?Math.round(Number(x.duration_min||0)*60/cycle):0)
      return <button type="button" className="oee-loss-row" key={x.id||i} onClick={()=>setLossDialog(i)}>
       <span><b>{x.saved?`Recorded Loss Event #${x.id}`:`Loss Event ${i+1}`}</b><small>{x.saved?x.category:(category?.name||'Select loss reason')} · {num(x.duration_min)} min · Qty loss: {num(calculatedQty)} pcs</small></span><strong>{x.saved?'EDIT':'ADD / EDIT'} →</strong>
      </button>
    })}
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
  </section>}
  {savedSummary&&<div className="oee-dialog-backdrop" role="presentation"><section className="oee-dialog oee-success-dialog" role="dialog" aria-modal="true"><header><span>PRODUCTION REVIEW</span></header><div className="oee-dialog-body"><small>RECORD CONFIRMATION</small><h3>{savedSummary.title}</h3>{savedSummary.id&&<p>Production entry #{savedSummary.id}</p>}<div className="oee-success-score"><small>OVERALL OEE</small><strong>{pct(savedSummary.oee)}</strong></div><div className="oee-success-grid">{[['Availability',savedSummary.availability],['Performance',savedSummary.performance],['Quality',savedSummary.quality]].map(([label,value]:any)=><div key={label}><small>{label}</small><b>{pct(value)}</b></div>)}</div><p>Good: <b>{num(savedSummary.good)}</b> · Rejected: <b>{num(savedSummary.reject)}</b> · Total: <b>{num(savedSummary.total)}</b></p><p>Availability loss: <b>{num(savedSummary.loss)} min</b></p>{savedSummary.warnings.map((w:string)=><p className="warning-box" key={w}>{w}</p>)}<div className="oee-dialog-actions"><button onClick={()=>setSavedSummary(null)}>OK</button></div></div></section></div>}
  </>}
{view==='loss'&&<>
{m&&machines.length>0&&<section className="panel"><div className="panel-title"><div><h2>Loss reconciliation and actions</h2><p>Classify every downtime minute; raise an action for major or recurring losses.</p></div><Link to="/actions">Open action register</Link></div><div className="table-wrap"><table><thead><tr><th>Loss</th><th>OEE component</th><th>Minutes</th><th>Qty loss</th><th>Remark</th><th>Action</th></tr></thead><tbody>{(sum?.losses||[]).map((x:any)=><tr key={x.id}><td><b>{x.category}</b></td><td>{x.component}</td><td>{num(x.duration_min)}</td><td>{num(x.qty_loss)}</td><td>{x.remark||'—'}</td><td>{x.action_no?<Link to="/actions">{x.action_no} · {x.action_status}</Link>:<button className="small" onClick={()=>raiseLossAction(x.id)}>Raise action</button>}</td></tr>)}{!sum?.losses?.length&&<tr><td colSpan={6} className="muted">No loss events for this selected scope.</td></tr>}</tbody></table></div></section>}
  </>}
{view==='reports'&&<>
<section className="panel"><div className="panel-title"><div><h2>OEE Excel Bulk Upload</h2><p>Download the master-linked workbook, complete both sheets, validate and import up to 1,000 OEE entries per workbook.</p></div><button type="button" className="secondary" onClick={()=>downloadApi('/oee/bulk-template','OEE_Bulk_Upload_Template.xlsx')}>Download Excel Template</button></div>
   <div className="form-row"><label>Completed OEE workbook<input type="file" accept=".xlsx" onChange={e=>{setBulkFile(e.target.files?.[0]||null);setBulkPreview(null);setBulkResult(null)}}/></label><button type="button" onClick={previewBulkImport} disabled={!bulkFile||bulkBusy}>{bulkBusy?'Validating…':'Validate & Preview'}</button></div>
   {bulkPreview&&<><div className={bulkPreview.valid?'success-box':'error'}><b>{bulkPreview.valid?'Workbook validation passed':'Please correct the following errors'}</b><p>{bulkPreview.entry_count} entries · {bulkPreview.loss_event_count} loss events</p></div>
    {bulkPreview.preview?.length>0&&<div className="table-wrap"><table><thead><tr><th>Ref</th><th>Date</th><th>Shift</th><th>Good</th><th>Reject</th><th>Availability Loss</th><th>Calculated Qty Loss</th><th>Events</th></tr></thead><tbody>{bulkPreview.preview.map((x:any)=><tr key={x.entry_ref}><td>{x.entry_ref}</td><td>{x.date}</td><td>{x.shift}</td><td>{num(x.good_qty)}</td><td>{num(x.reject_qty)}</td><td>{num(x.availability_loss_min)} min</td><td>{num(x.calculated_loss_qty)} pcs</td><td>{x.loss_events}</td></tr>)}</tbody></table></div>}
    {bulkPreview.errors?.length>0&&<div className="table-wrap"><table><thead><tr><th>Sheet</th><th>Row</th><th>Entry Ref</th><th>Error</th></tr></thead><tbody>{bulkPreview.errors.map((x:any,i:number)=><tr key={i}><td>{x.sheet}</td><td>{x.row}</td><td>{x.entry_ref||'—'}</td><td className="neg">{x.error}</td></tr>)}</tbody></table></div>}
    <div className="button-row"><button type="button" onClick={confirmBulkImport} disabled={!bulkPreview.valid||bulkBusy}>Confirm & Import</button><button type="button" className="secondary" onClick={()=>setBulkPreview(null)}>Discard Preview</button></div>
   </>}
   {bulkResult&&<div className="success-box">Imported {bulkResult.entry_count} OEE entries and {bulkResult.loss_event_count} loss events. Entry IDs: {bulkResult.entry_ids?.join(', ')}</div>}
   <p className="muted">Maximum 1,000 OEE entries per workbook, with up to 30 loss events per entry. Planned break defaults to 0 and shift duration to 440 minutes. Machine mapping and active operator are checked again by the server. Availability loss quantity is calculated from the effective master cycle; it is not entered in Excel. Existing records are never overwritten.</p>
  </section>
  <section className="panel report-panel" id="oee-reporting-compliance">
   <div className="panel-title"><div><h2>OEE Reporting Compliance</h2><p>Expected reports use daily production plans, latest monthly machine allocation, effective process mapping, shift capacity and plant working calendar. Unplanned machines and off-days are excluded.</p></div><button type="button" className="secondary" onClick={loadCompliance} disabled={complianceBusy}>{complianceBusy?"Refreshing…":"Refresh status"}</button></div>
   {complianceError&&<div className="error" role="alert">{complianceError}</div>}
   {compliance&&<><div className="kpi-grid"><Kpi label="Expected" value={compliance.expected||0}/><Kpi label="Updated" value={compliance.updated||0} tone="good"/><Kpi label="Pending" value={compliance.pending||0} tone={compliance.pending?"bad":"good"}/><Kpi label="Incomplete" value={compliance.incomplete||0} tone={compliance.incomplete?"warn":"good"}/><Kpi label="Compliance" value={Number(compliance.compliance_percent||0).toFixed(1)+"%"} tone={Number(compliance.compliance_percent||0)<85?"warn":"good"}/></div>
   <div className="table-wrap"><h3>Shift-wise reporting status</h3><table><thead><tr><th>Shift</th><th>Expected</th><th>Updated</th><th>Pending</th><th>Incomplete</th></tr></thead><tbody>{(compliance.by_shift||[]).map((x:any)=><tr key={x.shift}><td>{x.shift}</td><td>{x.expected}</td><td>{x.updated}</td><td>{x.pending}</td><td>{x.incomplete}</td></tr>)}</tbody></table></div>
   <div className="table-wrap"><h3>Pending OEE entries</h3><table><thead><tr><th>Date</th><th>Shift</th><th>Machine</th><th>Part / Process</th><th>Planned Qty</th><th>Action</th></tr></thead><tbody>{(compliance.pending_entries||[]).map((x:any,i:number)=><tr key={i}><td>{x.date}</td><td>{x.shift}</td><td>{x.machine}<br/><small>{x.machine_name}</small></td><td>{x.product}<br/><small>Operation #{x.route_operation_id}</small></td><td>{num(x.planned_qty||0)}</td><td><Link className="button small" to={"/oee?date="+x.date+"&shift="+x.shift+"&product_id="+x.product_id+"&route_operation_id="+x.route_operation_id+"&machine_id="+x.machine_id+"#oee-entry"}>Start entry</Link></td></tr>)}{!compliance.pending_entries?.length&&<tr><td colSpan={6} className="muted">No pending planned OEE entries.</td></tr>}</tbody></table></div>
   <div className="table-wrap"><h3>Incomplete OEE entries</h3><table><thead><tr><th>Date</th><th>Shift</th><th>Machine</th><th>Part</th><th>Issues</th><th>Action</th></tr></thead><tbody>{(compliance.incomplete_entries||[]).map((x:any,i:number)=><tr key={i}><td>{x.date}</td><td>{x.shift}</td><td>{x.machine}</td><td>{x.product}</td><td className="neg">{(x.issues||[]).join("; ")}</td><td><Link className="button small secondary" to={"/oee?date="+x.date+"&shift="+x.shift+"&product_id="+x.product_id+"&route_operation_id="+x.route_operation_id+"&machine_id="+x.machine_id+"#oee-entry"}>Review entry</Link></td></tr>)}</tbody></table></div>
   {(compliance.configuration_issues||[]).length>0&&<div className="warning-box"><b>Planning configuration issues</b>{compliance.configuration_issues.map((x:any,i:number)=><p key={i}>{x.date} • {x.machine} • {x.issue}</p>)}</div>}</>}
  </section>
<section className="panel"><div className="panel-title"><div><h2>OEE Management — Trend & Loss Pareto</h2><p>Period performance and daily loss hours, following the selected machine, part, process and date filters.</p></div><div className="form-row compact"><input aria-label="OEE from date" type="date" value={fromDate} onChange={e=>setFromDate(e.target.value)}/><select aria-label="Loss category filter" value={lossCategoryFilter} onChange={e=>setLossCategoryFilter(e.target.value)}><option value="">All loss categories</option>{lossCategories.map((x:any)=><option key={x.id} value={String(x.id)}>{x.name}</option>)}</select><button className="secondary" onClick={loadManagement}>Refresh</button></div></div>
  {mgmt&&<><div className="kpi-grid"><Kpi label="Period OEE" value={pct(mgmt.overall?.oee_reported)}/><Kpi label="Availability" value={pct(mgmt.overall?.availability)}/><Kpi label="Performance" value={pct(mgmt.overall?.performance_raw)}/><Kpi label="Quality" value={pct(mgmt.overall?.quality)}/><Kpi label="Shift Records" value={mgmt.entry_count||0}/><Kpi label="Loss Events" value={mgmt.loss_event_count||0}/><Kpi label="Machines Below 85%" value={mgmt.below_target_machine_count||0} tone={mgmt.below_target_machine_count?'bad':'good'}/><Kpi label="Recurring Losses" value={mgmt.recurring_loss_count||0} tone={mgmt.recurring_loss_count?'warn':'good'}/></div>
  <div className="two-col"><div className="table-wrap"><table><thead><tr><th>Machine</th><th>Records</th><th>A</th><th>P</th><th>Q</th><th>OEE</th><th>Target status</th></tr></thead><tbody>{(mgmt.machines||[]).map((x:any)=><tr key={x.machine_id}><td><b>{x.machine}</b><br/><small className="muted">{allMachines.find((machine:any)=>String(machine.id)===String(x.machine_id))?.name||"Machine name unavailable"}</small></td><td>{x.entry_count}</td><td>{pct(x.availability)}</td><td>{pct(x.performance_raw)}</td><td>{pct(x.quality)}</td><td><b>{pct(x.oee_reported)}</b></td><td><b className={x.status==='BELOW TARGET'?'neg':''}>{x.status}</b>{x.gap_to_target>0&&<><br/><small>{pct(x.gap_to_target)} gap</small></>}</td></tr>)}{!mgmt.machines?.length&&<tr><td colSpan={7} className="muted">No OEE records in this period.</td></tr>}</tbody></table></div>
  {mgmt.recurring_losses?.length>0&&<div className="warning-box"><b>Recurring losses needing action:</b> {mgmt.recurring_losses.map((x:any)=>`${x.category} (${x.events} events)`).join(', ')}</div>}
  <div className="table-wrap"><h3>Daily machine loss (hours)</h3><p className="muted">Stacked by loss category. Each bar represents the total recorded loss hours for that date.</p>{(mgmt.daily_loss_trend||[]).length>0?<><div style={{display:"flex",alignItems:"flex-end",gap:12,height:250,overflowX:"auto",padding:"16px 8px 4px",borderBottom:"1px solid var(--border, #d7deea)"}}>{(mgmt.daily_loss_trend||[]).map((day:any)=>{const palette=["#2563eb","#0d9488","#d97706","#7c3aed","#dc2626","#0891b2","#65a30d","#c026d3"];const max=Math.max(0.1,...(mgmt.daily_loss_trend||[]).map((x:any)=>Number(x.total_hours||0)));return <div key={day.date} title={`${day.date}: ${num(day.total_hours)} hours`} style={{minWidth:34,flex:"1 0 34px",height:"100%",display:"flex",flexDirection:"column",justifyContent:"flex-end",alignItems:"center",gap:5}}><div style={{height:`${Math.max(0,Number(day.total_hours||0)/max*190)}px`,width:"75%",display:"flex",flexDirection:"column-reverse",justifyContent:"flex-start",borderRadius:"4px 4px 0 0",overflow:"hidden"}}>{(day.categories||[]).map((part:any)=>{const color=palette[dailyLossCategories.indexOf(part.category)%palette.length]||palette[0];return <div key={part.category} title={`${part.category}: ${num(part.hours)} h`} style={{height:`${Number(part.hours||0)/Math.max(0.001,Number(day.total_hours||0))*100}%`,backgroundColor:color,minHeight:part.hours>0?2:0}}/>})}</div><small style={{fontSize:10,whiteSpace:"nowrap",color:"var(--muted, #64748b)"}}>{String(day.date).slice(5)}</small></div>})}</div><div style={{display:"flex",flexWrap:"wrap",gap:"8px 16px",paddingTop:12}}>{dailyLossCategories.map((name:string,i:number)=><span key={name} style={{display:"inline-flex",alignItems:"center",gap:6,fontSize:12}}><span style={{width:10,height:10,borderRadius:2,backgroundColor:["#2563eb","#0d9488","#d97706","#7c3aed","#dc2626","#0891b2","#65a30d","#c026d3"][i%8]}}/>{name}</span>)}</div></>:<p className="muted">No loss events match the selected filters in this period.</p>}</div>
  <div className="table-wrap"><table><thead><tr><th>Loss</th><th>Component</th><th>Events</th><th>Minutes</th><th>Qty loss</th></tr></thead><tbody>{(mgmt.loss_pareto||[]).slice(0,10).map((x:any)=><tr key={x.category}><td><b>{x.category}</b></td><td>{x.component||'—'}</td><td>{x.events}</td><td>{num(x.minutes)}</td><td>{num(x.qty_loss)}</td></tr>)}{!mgmt.loss_pareto?.length&&<tr><td colSpan={5} className="muted">No classified losses in this period.</td></tr>}</tbody></table></div></div>
  <div className="table-wrap"><table><thead><tr><th>Date</th><th>A</th><th>P</th><th>Q</th><th>OEE</th></tr></thead><tbody>{(mgmt.trend||[]).map((x:any)=><tr key={x.date}><td>{x.date}</td><td>{pct(x.availability)}</td><td>{pct(x.performance_raw)}</td><td>{pct(x.quality)}</td><td><b>{pct(x.oee_reported)}</b></td></tr>)}</tbody></table></div>
  <div className="two-col">
   <div className="table-wrap"><h3>Part-wise OEE</h3><table><thead><tr><th>Product</th><th>Records</th><th>A</th><th>P</th><th>Q</th><th>OEE</th></tr></thead><tbody>{(mgmt.products||[]).map((x:any)=><tr key={x.product_id}><td>{x.product}</td><td>{x.entry_count}</td><td>{pct(x.availability)}</td><td>{pct(x.performance_raw)}</td><td>{pct(x.quality)}</td><td><b>{pct(x.oee_reported)}</b></td></tr>)}{!mgmt.products?.length&&<tr><td colSpan={6} className="muted">No product data.</td></tr>}</tbody></table></div>
   <div className="table-wrap"><h3>Operator-wise OEE</h3><table><thead><tr><th>Operator</th><th>Records</th><th>A</th><th>P</th><th>Q</th><th>OEE</th></tr></thead><tbody>{(mgmt.operators||[]).map((x:any)=><tr key={x.operator_id??'unassigned'}><td>{x.operator}</td><td>{x.entry_count}</td><td>{pct(x.availability)}</td><td>{pct(x.performance_raw)}</td><td>{pct(x.quality)}</td><td><b>{pct(x.oee_reported)}</b></td></tr>)}{!mgmt.operators?.length&&<tr><td colSpan={6} className="muted">No operator data.</td></tr>}</tbody></table></div>
  </div>
  <div className="table-wrap"><h3>Shift-wise OEE</h3><table><thead><tr><th>Shift</th><th>Records</th><th>A</th><th>P</th><th>Q</th><th>OEE</th></tr></thead><tbody>{(mgmt.shifts||[]).map((x:any)=><tr key={x.shift}><td>{x.shift}</td><td>{x.entry_count}</td><td>{pct(x.availability)}</td><td>{pct(x.performance_raw)}</td><td>{pct(x.quality)}</td><td><b>{pct(x.oee_reported)}</b></td></tr>)}{!mgmt.shifts?.length&&<tr><td colSpan={6} className="muted">No shift data.</td></tr>}</tbody></table></div></>}</section>
  </>}
{view==='history'&&<>
{m&&machines.length>0&&<section className="panel"><div className="panel-title"><div><h2>Saved OEE records</h2><p>One row per selected machine, product, operation and shift.</p></div><Link to={`/insights?kind=oee&from_date=${d}&to_date=${d}&machine_id=${m}`}>Open drill-down</Link></div><div className="table-wrap"><table><thead><tr><th>ID</th><th>Operator</th><th>Total</th><th>Good</th><th>Reject</th><th>Downtime</th><th>Cycle</th><th>A</th><th>P</th><th>Q</th><th>OEE</th><th>Action</th></tr></thead><tbody>{(sum?.entries||[]).map((x:any)=><tr key={x.id}><td>#{x.id}</td><td>{x.operator_name||'—'}</td><td>{num(x.total_count)}</td><td>{num(x.good_count)}</td><td>{num(x.reject_count)}</td><td>{num(x.downtime_min)} min</td><td>{num(x.ideal_cycle_time_sec)} sec</td><td>{pct(x.availability)}</td><td className={x.performance_master_warning?'neg':''}>{pct(x.performance_raw)}</td><td>{pct(x.quality)}</td><td><b>{pct(x.oee_reported)}</b></td><td><button type="button" className="small secondary" onClick={()=>loadContext(true)}>Edit</button></td></tr>)}{!sum?.entries?.length&&<tr><td colSpan={12} className="muted">No shift entry saved yet.</td></tr>}</tbody></table></div></section>}</>}

 </>
}
