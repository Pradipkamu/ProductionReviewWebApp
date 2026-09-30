import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import { ScopeFilters, ScopeValues } from '../components/ScopeFilters'
import { PageHeader, num } from '../components/UI'

function monthNow(){return new Date().toISOString().slice(0,7)+'-01'}
function today(){return new Date().toISOString().slice(0,10)}
const emptyScope:ScopeValues={plant:[],productGroup:[],customerId:[],productId:[]}

export default function Schedule(){
 const [products,setProducts]=useState<any[]>([]); const [options,setOptions]=useState<any>({}); const [scope,setScope]=useState<ScopeValues>(emptyScope); const [pid,setPid]=useState(''); const [month,setMonth]=useState(monthNow()); const [rows,setRows]=useState<any[]>([]); const [calendar,setCalendar]=useState<any[]>([])
 const [eff,setEff]=useState(today()); const [target,setTarget]=useState(''); const [reason,setReason]=useState('Customer schedule revision'); const [preview,setPreview]=useState<any>(null); const [msg,setMsg]=useState('')
 const [prices,setPrices]=useState<any[]>([]); const [priceEff,setPriceEff]=useState(today()); const [newPrice,setNewPrice]=useState(''); const [priceReason,setPriceReason]=useState('Customer price revision'); const [priceMsg,setPriceMsg]=useState('')
 const [calHistory,setCalHistory]=useState<any[]>([]); const [rangeStart,setRangeStart]=useState(today()); const [rangeEnd,setRangeEnd]=useState(today()); const [holiday,setHoliday]=useState(''); const [calReason,setCalReason]=useState('Plant calendar update')

 useEffect(()=>{Promise.all([api('/masters/products'),api('/masters/filter-options')]).then(([p,o]:any)=>{setProducts(p);setOptions(o);if(p[0])setPid(String(p[0].id))})},[])
 const eligible=useMemo(()=>products.filter(p=>(!scope.plant.length||scope.plant.includes(String(p.plant||'')))&&(!scope.productGroup.length||scope.productGroup.includes(String(p.product_group||'')))&&(!scope.customerId.length||scope.customerId.includes(String(p.customer_id)))),[products,scope])
 useEffect(()=>{if(scope.productId.length===1)setPid(scope.productId[0]);else if(!eligible.some(p=>String(p.id)===pid))setPid(eligible[0]?String(eligible[0].id):'')},[scope.productId,eligible])
 const selected=products.find(p=>String(p.id)===pid); const calendarPlant=selected?.plant||(scope.plant.length===1?scope.plant[0]:'Main Plant')

 async function load(){
   if(pid){
     const [s,p]=await Promise.all([api(`/schedules?product_id=${pid}&month=${month}`),api(`/masters/prices/${pid}`)])
     setRows(s as any[]); setPrices(p as any[])
   } else {setRows([]);setPrices([])}
   const [c,h]=await Promise.all([
     api(`/masters/calendar?month=${month}&plant=${encodeURIComponent(calendarPlant)}`),
     api(`/masters/calendar/history?month=${month}&plant=${encodeURIComponent(calendarPlant)}`),
   ])
   setCalendar(c as any[]);setCalHistory(h as any[])
 }
 useEffect(()=>{load()},[pid,month,calendarPlant])

 async function doPreview(){setPreview(await api('/schedules/preview',{method:'POST',body:JSON.stringify({product_id:Number(pid),effective_from:eff,monthly_target_qty:Number(target)})}))}
 async function apply(){await api('/schedules',{method:'POST',body:JSON.stringify({product_id:Number(pid),month,effective_from:eff,monthly_target_qty:Number(target),reason})}); setMsg('Schedule revision applied from the effective date forward. Historical issued plans are preserved.'); setPreview(null); load()}
 async function recalcAll(){const from=prompt('Recalculate future requirements from date',eff)||eff; const r:any=await api(`/schedules/recalculate-month?month=${month}&from_date=${from}`,{method:'POST'});setMsg(`${r.products_recalculated} products recalculated from ${from}. Each product uses its own Plant calendar.`);load()}

 async function applyPrice(){
   if(!pid||!newPrice)return
   await api('/masters/prices',{method:'POST',body:JSON.stringify({product_id:Number(pid),effective_from:priceEff,price:Number(newPrice),reason:priceReason})})
   setPriceMsg(`Price revision applied from ${priceEff}. Earlier dates keep their historical price; existing MIS sales from the effective date were recalculated.`)
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
 return <><PageHeader title="Schedule, Price & Working Calendar" subtitle="Effective-dated schedule and sales-price revisions with Plant-specific working calendars and audit history." actions={<button className="secondary" onClick={recalcAll}>Recalculate month</button>}/>
 <ScopeFilters value={scope} onChange={setScope} options={options} products={products}/>
 <div className="filter-summary"><span className="filter-chip">Calendar Plant: {calendarPlant}</span>{selected?.product_group&&<span className="filter-chip">Group: {selected.product_group}</span>}{currentPrice&&<span className="filter-chip">Current Price: ₹{num(currentPrice.price)}</span>}</div>

 <div className="two-col"><section className="panel"><h2>Schedule history</h2><div className="form-row"><label>Product<select value={pid} onChange={e=>setPid(e.target.value)}>{eligible.map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</select></label><label>Month<input type="date" value={month} onChange={e=>setMonth(e.target.value)}/></label></div>
 <table><thead><tr><th>Rev</th><th>Effective</th><th>Monthly target</th><th>Reason</th></tr></thead><tbody>{rows.map(r=><tr key={r.id}><td>R{r.revision_no}</td><td>{r.effective_from}</td><td>{num(r.target)}</td><td>{r.reason}</td></tr>)}</tbody></table></section>
 <section className="panel"><h2>Create schedule revision</h2><label>Effective from<input type="date" value={eff} onChange={e=>setEff(e.target.value)}/></label><label>New monthly target<input type="number" value={target} onChange={e=>setTarget(e.target.value)} /></label><label>Reason<textarea value={reason} onChange={e=>setReason(e.target.value)}/></label><div className="button-row"><button className="secondary" onClick={doPreview}>Preview</button><button onClick={apply} disabled={!preview}>Apply revision</button></div>{msg&&<div className="notice">{msg}</div>}
 {preview&&<div className="preview"><b>Balance: {num(preview.balance_requirement)}</b><span>Actual before date: {num(preview.actual_before_effective_date)}</span><span>Remaining working days ({calendarPlant}): {preview.remaining_working_days}</span><span>Avg/day: {num(preview.average_daily_requirement)}</span></div>}</section></div>

 <div className="two-col"><section className="panel"><div className="panel-title"><h2>Sales price history</h2><span>Historical prices are never overwritten.</span></div><div className="table-wrap"><table><thead><tr><th>Effective from</th><th>Effective to</th><th>Price ₹/pc</th><th>Source</th><th>Reason</th></tr></thead><tbody>{prices.map((r:any)=><tr key={r.id}><td>{r.effective_from}</td><td>{r.effective_to||'Current'}</td><td>{num(r.price)}</td><td>{r.source}</td><td>{r.reason||'—'}</td></tr>)}</tbody></table></div></section>
 <section className="panel"><h2>Create sales price revision</h2><p className="muted">The new price applies only from its effective date. Earlier MIS and sales values keep the old price.</p><label>Effective from<input type="date" value={priceEff} onChange={e=>setPriceEff(e.target.value)}/></label><label>New price ₹ / pc<input type="number" step="0.01" min="0.01" value={newPrice} onChange={e=>setNewPrice(e.target.value)}/></label><label>Reason / reference<textarea value={priceReason} onChange={e=>setPriceReason(e.target.value)}/></label><button onClick={applyPrice} disabled={!pid||!newPrice||Number(newPrice)<=0}>Apply price revision</button>{priceMsg&&<div className="notice">{priceMsg}</div>}</section></div>

 <section className="panel"><div className="panel-title"><h2>Working calendar — {calendarPlant}</h2><span>Default: Mon–Sat working, Sunday off. Explicit changes are stored and audited.</span></div>
 <div className="form-row"><label>Range start<input type="date" value={rangeStart} onChange={e=>setRangeStart(e.target.value)}/></label><label>Range end<input type="date" value={rangeEnd} onChange={e=>setRangeEnd(e.target.value)}/></label><label>Holiday / off-day name<input value={holiday} onChange={e=>setHoliday(e.target.value)} placeholder="e.g. Diwali"/></label><label>Reason<input value={calReason} onChange={e=>setCalReason(e.target.value)}/></label></div>
 <div className="button-row"><button className="secondary" onClick={()=>bulk('SUNDAYS_OFF')}>Set Sundays off</button><button className="secondary" onClick={()=>bulk('SET_OFF')}>Mark range off</button><button className="secondary" onClick={()=>bulk('SET_WORKING')}>Mark range working</button></div>
 <div className="calendar-grid">{calendar.map(r=><button key={r.date} className={`day ${r.working?'working':'off'}`} title={`${r.holiday||''} ${r.reason||''}`} onClick={()=>editDay(r)}><b>{r.date.slice(-2)}</b><span>{r.working?'Working':'Off'}</span>{r.holiday&&<small>{r.holiday}</small>}</button>)}</div></section>

 <section className="panel"><div className="panel-title"><h2>Calendar change history</h2><span>Latest 100 changes in the selected month / Plant.</span></div><div className="table-wrap"><table><thead><tr><th>Date</th><th>Old</th><th>New</th><th>Holiday</th><th>Reason</th><th>Changed at</th></tr></thead><tbody>{calHistory.map((r:any)=><tr key={r.id}><td>{r.date}</td><td>{r.old_working==null?'Default':r.old_working?'Working':'Off'}</td><td>{r.new_working?'Working':'Off'}</td><td>{r.new_holiday||'—'}</td><td>{r.new_reason||'—'}</td><td>{String(r.changed_at).replace('T',' ').slice(0,19)}</td></tr>)}</tbody></table></div></section>
 </>
}
