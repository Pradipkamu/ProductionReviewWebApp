import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import { ScopeFilters, ScopeValues } from '../components/ScopeFilters'
import { PageHeader, num } from '../components/UI'
import { MultiSelect } from '../components/MultiSelect'

function monthNow(){return new Date().toISOString().slice(0,7)+'-01'}
function today(){return new Date().toISOString().slice(0,10)}
const emptyScope:ScopeValues={plant:[],productGroup:[],customerId:[],productId:[]}

export default function Schedule(){
 const [products,setProducts]=useState<any[]>([]); const [options,setOptions]=useState<any>({}); const [scope,setScope]=useState<ScopeValues>(emptyScope); const [pid,setPid]=useState(''); const [month,setMonth]=useState(monthNow()); const [rows,setRows]=useState<any[]>([]); const [calendar,setCalendar]=useState<any[]>([])
 const [eff,setEff]=useState(today()); const [target,setTarget]=useState(''); const [reason,setReason]=useState('Customer schedule revision'); const [preview,setPreview]=useState<any>(null); const [msg,setMsg]=useState('')
 const [correctImported,setCorrectImported]=useState(false); const [busy,setBusy]=useState(false)
 const [prices,setPrices]=useState<any[]>([]); const [priceEff,setPriceEff]=useState(today()); const [newPrice,setNewPrice]=useState(''); const [priceReason,setPriceReason]=useState('Customer price revision'); const [priceMsg,setPriceMsg]=useState('')
 const [calHistory,setCalHistory]=useState<any[]>([]); const [rangeStart,setRangeStart]=useState(today()); const [rangeEnd,setRangeEnd]=useState(today()); const [holiday,setHoliday]=useState(''); const [calReason,setCalReason]=useState('Plant calendar update')

 useEffect(()=>{Promise.all([api('/masters/products'),api('/masters/filter-options')]).then(([p,o]:any)=>{setProducts(p);setOptions(o);if(p[0])setPid(String(p[0].id))})},[])
 const eligible=useMemo(()=>products.filter(p=>(!scope.plant.length||scope.plant.includes(String(p.plant||'')))&&(!scope.productGroup.length||scope.productGroup.includes(String(p.product_group||'')))&&(!scope.customerId.length||scope.customerId.includes(String(p.customer_id)))),[products,scope])
 useEffect(()=>{if(scope.productId.length===1)setPid(scope.productId[0]);else if(!eligible.some(p=>String(p.id)===pid))setPid(eligible[0]?String(eligible[0].id):'')},[scope.productId,eligible])
 const selected=products.find(p=>String(p.id)===pid); const calendarPlant=selected?.plant||(scope.plant.length===1?scope.plant[0]:'Main Plant')

 async function load(){
   if(pid){
     const [s,p]=await Promise.all([api(`/schedules?product_id=${pid}&month=${month}`),api(`/masters/prices/${pid}`)])
     const scheduleRows=s as any[]
     setRows(scheduleRows); setPrices(p as any[])
     if(scheduleRows.length&&!target)setTarget(String(scheduleRows[scheduleRows.length-1].target??''))
   } else {setRows([]);setPrices([])}
   const [c,h]=await Promise.all([
     api(`/masters/calendar?month=${month}&plant=${encodeURIComponent(calendarPlant)}`),
     api(`/masters/calendar/history?month=${month}&plant=${encodeURIComponent(calendarPlant)}`),
   ])
   setCalendar(c as any[]);setCalHistory(h as any[])
 }
 useEffect(()=>{load()},[pid,month,calendarPlant])
 useEffect(()=>{setPreview(null);setMsg('')},[pid,month,eff,target,correctImported,reason])

 async function doPreview(){
   setPreview(null);setMsg('')
   if(eff.slice(0,7)!==month.slice(0,7)){setMsg('Effective date must be inside the selected month.');return}
   setBusy(true)
   try{setPreview(await api('/schedules/preview',{method:'POST',body:JSON.stringify({product_id:Number(pid),effective_from:eff,monthly_target_qty:Number(target),correct_imported_plans:correctImported})}))}
   catch(e){setMsg(e instanceof Error?e.message:String(e))}finally{setBusy(false)}
 }
 async function apply(){
   setBusy(true);setMsg('')
   try{const r:any=await api('/schedules',{method:'POST',body:JSON.stringify({product_id:Number(pid),month,effective_from:eff,monthly_target_qty:Number(target),reason,correct_imported_plans:correctImported})}); setMsg(`Revision R${r.revision_no} applied to ${r.applied_days} days from ${eff} using ${r.source||'schedule'}; ${r.corrected_imported_days} imported daily plans corrected.`);setPreview(null);await load()}
   catch(e){setMsg(e instanceof Error?e.message:String(e))}finally{setBusy(false)}
 }
 async function recalcAll(){const from=prompt('Recalculate future requirements from date',eff)||eff; const r:any=await api(`/schedules/recalculate-month?month=${month}&from_date=${from}`,{method:'POST'});setMsg(`${r.products_recalculated} products recalculated from ${from}. Disp_Done Stage Schedule is used as the customer schedule for products with an explicit process flow.`);load()}

 async function applyPrice(){
   if(!pid||!newPrice)return
   await api('/masters/prices',{method:'POST',body:JSON.stringify({product_id:Number(pid),effective_from:priceEff,price:Number(newPrice),reason:priceReason})})
   setPriceMsg(`Price revision applied from ${priceEff}. Earlier MIS and sales values keep the old price; existing MIS sales from the effective date were recalculated.`)
   setNewPrice(''); await load()
 }

 async function editDay(r:any){
   const nextWorking=!r.working
   const h=nextWorking?'':(prompt('Holiday / Off-day name',r.holiday||'Off day')??r.holiday??'Off day')
   const rs=prompt('Reason for calendar change',r.reason&&r.explicit?r.reason:'Calendar update')
   if(rs===null)return
   await api('/masters/calendar',{method:'POST',body:JSON.stringify({work_date:r.date,plant:calendarPlant,is_working_day:nextWorking,holiday_name:h||null,reason:rs})})
   await load()
 }
 async function bulk(mode:'SUNDAYS_OFF'|'SET_OFF'|'SET_WORKING'){
   if(rangeEnd<rangeStart){alert('End date must be after start date');return}
   const body={plant:calendarPlant,start_date:rangeStart,end_date:rangeEnd,mode,holiday_name:mode==='SET_WORKING'?null:(holiday||null),reason:calReason}
   const r:any=await api('/masters/calendar/bulk',{method:'POST',body:JSON.stringify(body)})
   setMsg(`${r.days_processed} calendar day(s) updated for ${calendarPlant}. Recalculate the month if schedule requirements must change.`)
   await load()
 }

 const currentPrice=prices.find((x:any)=>x.effective_from<=today()&&(!x.effective_to||x.effective_to>=today()))
 const latestSchedule=rows.length?rows[rows.length-1]:null
 return <><PageHeader title="Schedule, Price & Working Calendar" subtitle="Disp_Done Stage Schedule is the customer monthly schedule; revisions, prices and Plant calendars remain effective-dated with audit history." actions={<button className="secondary" onClick={recalcAll}>Recalculate month</button>}/>
 <ScopeFilters value={scope} onChange={setScope} options={options} products={products}/>
 <div className="filter-summary"><span className="filter-chip">Calendar Plant: {calendarPlant}</span>{selected?.product_group&&<span className="filter-chip">Group: {selected.product_group}</span>}{currentPrice&&<span className="filter-chip">Current Price: ₹{num(currentPrice.price)}</span>}{latestSchedule&&<span className="filter-chip">Current Schedule: {num(latestSchedule.target)}</span>}</div>

 <div className="two-col"><section className="panel"><div className="panel-title"><h2>Schedule history</h2><span>Source: parent dispatch / Disp_Done from Stage Schedule.</span></div><div className="form-row"><label>Product<MultiSelect singleSelect value={pid?[pid]:[]} onChange={v=>{setPid(v.at(-1)||'');setTarget('')}} placeholder="Select Product" options={eligible.map(p=>({value:String(p.id),label:p.name}))}/></label><label>Month<input type="date" value={month} onChange={e=>{setMonth(e.target.value);setTarget('')}}/></label></div>
 <div className="table-wrap"><table><thead><tr><th>Rev</th><th>Effective</th><th>Monthly target</th><th>Source</th><th>Reference</th><th>Reason</th></tr></thead><tbody>{rows.map(r=><tr key={`${r.source||'schedule'}-${r.id}`}><td>R{r.revision_no}</td><td>{r.effective_from}</td><td>{num(r.target)}</td><td>{r.source||'Schedule'}</td><td>{r.reference||'—'}</td><td>{r.reason||'—'}</td></tr>)}</tbody></table></div>{!rows.length&&<p className="muted">No Disp_Done Stage Schedule has been loaded for this product/month.</p>}</section>
 <section className="panel"><h2>Create schedule revision</h2><p className="muted">For products using the explicit process flow, this revises the same parent dispatch / Disp_Done Stage Schedule instead of creating a separate parallel schedule.</p><label>Effective from<input type="date" value={eff} onChange={e=>setEff(e.target.value)}/></label><label>New monthly target<input type="number" min="1" value={target} onChange={e=>setTarget(e.target.value)} /></label><label>Reason<textarea value={reason} onChange={e=>setReason(e.target.value)}/></label><label><input type="checkbox" checked={correctImported} onChange={e=>setCorrectImported(e.target.checked)}/> Correct imported historical plans</label><p className="muted">Select this for a historical month imported with missing or incorrect schedules. Only revised plans from the effective date change; original imported plans and actuals are retained with an audit trail. A closed month requires correction authorization or reopening.</p><div className="button-row"><button className="secondary" onClick={doPreview} disabled={busy||!pid||Number(target)<=0}>Preview</button><button onClick={apply} disabled={busy||!preview||preview.protected_days>0||(correctImported&&!reason.trim())}>Apply revision</button></div>{msg&&<div className="notice" role="status">{msg}</div>}
 {preview&&<><div className="preview"><b>Balance: {num(preview.balance_requirement)}</b><span>{preview.source?.includes('Disp_Done')?'Plan issued before date':'Actual before date'}: {num(preview.plan_before_effective_date??preview.actual_before_effective_date)}</span><span>Remaining working days ({calendarPlant}): {preview.remaining_working_days}</span><span>Avg/day: {num(preview.average_daily_requirement)}</span><span>Resulting plan from effective date: {num(preview.result_plan_qty)}</span></div>{preview.protected_days>0&&<p className="notice">{preview.protected_days} imported days are protected. Select “Correct imported historical plans” and preview again to apply your schedule.</p>}<div className="table-wrap"><table><thead><tr><th>Date</th><th>Current plan</th><th>Proposed plan</th><th>Resulting plan</th><th>Status</th></tr></thead><tbody>{preview.preview.map((r:any)=><tr key={r.date}><td>{r.date}</td><td>{num(r.current_qty)}</td><td>{num(r.qty)}</td><td>{num(r.result_qty)}</td><td>{r.protected?'Protected':'Will apply'}</td></tr>)}</tbody></table></div></>}</section></div>

 <div className="two-col"><section className="panel"><div className="panel-title"><h2>Sales price history</h2><span>Historical prices are never overwritten.</span></div><div className="table-wrap"><table><thead><tr><th>Effective from</th><th>Effective to</th><th>Price ₹/pc</th><th>Source</th><th>Reason</th></tr></thead><tbody>{prices.map((r:any)=><tr key={r.id}><td>{r.effective_from}</td><td>{r.effective_to||'Current'}</td><td>{num(r.price)}</td><td>{r.source}</td><td>{r.reason||'—'}</td></tr>)}</tbody></table></div></section>
 <section className="panel"><h2>Create sales price revision</h2><p className="muted">The new price applies only from its effective date. Earlier MIS and sales values keep the old price.</p><label>Effective from<input type="date" value={priceEff} onChange={e=>setPriceEff(e.target.value)}/></label><label>New price ₹ / pc<input type="number" step="0.01" min="0.01" value={newPrice} onChange={e=>setNewPrice(e.target.value)}/></label><label>Reason / reference<textarea value={priceReason} onChange={e=>setPriceReason(e.target.value)}/></label><button onClick={applyPrice} disabled={!pid||!newPrice||Number(newPrice)<=0}>Apply price revision</button>{priceMsg&&<div className="notice">{priceMsg}</div>}</section></div>

 <section className="panel"><div className="panel-title"><h2>Working calendar — {calendarPlant}</h2><span>Default: Mon–Sat working, Sunday off. Explicit changes are stored and audited.</span></div>
 <div className="form-row"><label>Range start<input type="date" value={rangeStart} onChange={e=>setRangeStart(e.target.value)}/></label><label>Range end<input type="date" value={rangeEnd} onChange={e=>setRangeEnd(e.target.value)}/></label><label>Holiday / off-day name<input value={holiday} onChange={e=>setHoliday(e.target.value)} placeholder="e.g. Diwali"/></label><label>Reason<input value={calReason} onChange={e=>setCalReason(e.target.value)}/></label></div>
 <div className="button-row"><button className="secondary" onClick={()=>bulk('SUNDAYS_OFF')}>Set Sundays off</button><button className="secondary" onClick={()=>bulk('SET_OFF')}>Mark range off</button><button className="secondary" onClick={()=>bulk('SET_WORKING')}>Mark range working</button></div>
 <div className="calendar-grid">{calendar.map(r=><button key={r.date} className={`day ${r.working?'working':'off'}`} title={`${r.holiday||''} ${r.reason||''}`} onClick={()=>editDay(r)}><b>{r.date.slice(-2)}</b><span>{r.working?'Working':'Off'}</span>{r.holiday&&<small>{r.holiday}</small>}</button>)}</div></section>

 <section className="panel"><div className="panel-title"><h2>Calendar change history</h2><span>Latest 100 changes in the selected month / Plant.</span></div><div className="table-wrap"><table><thead><tr><th>Date</th><th>Old</th><th>New</th><th>Holiday</th><th>Reason</th><th>Changed at</th></tr></thead><tbody>{calHistory.map((r:any)=><tr key={r.id}><td>{r.date}</td><td>{r.old_working==null?'Default':r.old_working?'Working':'Off'}</td><td>{r.new_working?'Working':'Off'}</td><td>{r.new_holiday||'—'}</td><td>{r.new_reason||'—'}</td><td>{String(r.changed_at).replace('T',' ').slice(0,19)}</td></tr>)}</tbody></table></div></section>
 </>
}
