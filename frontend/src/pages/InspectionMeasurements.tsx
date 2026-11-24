import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'

const today = () => new Date().toISOString().slice(0,10)
const emptyCharacteristic = {product_id:'',operation_id:'',characteristic_code:'',name:'',nominal_value:'',lower_tolerance:'',upper_tolerance:'',unit:'mm',sample_size:'1',control_plan_reference:'',special_characteristic:''}
const emptyEntry = {inspection_date:today(),product_id:'',operation_id:'',characteristic_id:'',instrument_id:'',lot_reference:'',machine_reference:'',shift:'A',operator_name:'',measured_values:[''],remarks:''}
const blocked = new Set(['DUE','OVERDUE','OUT_FOR_CALIBRATION','OOT','FAILED','QUARANTINED','PENDING_APPROVAL','RETIRED','PENDING','IN_CALIBRATION'])

export default function InspectionMeasurements(){
 const [products,setProducts]=useState<any[]>([]),[operations,setOperations]=useState<any[]>([]),[gauges,setGauges]=useState<any[]>([])
 const [characteristics,setCharacteristics]=useState<any[]>([]),[records,setRecords]=useState<any[]>([])
 const [master,setMaster]=useState<any>(emptyCharacteristic),[entry,setEntry]=useState<any>(emptyEntry)
 const [fromDate,setFromDate]=useState(''),[toDate,setToDate]=useState(''),[filterProduct,setFilterProduct]=useState('')
 const [busy,setBusy]=useState(false),[error,setError]=useState(''),[message,setMessage]=useState('')
 const eligibleGauges=useMemo(()=>gauges.filter(g=>!blocked.has(String(g.status||'').toUpperCase())&&g.next_due_date&&String(g.next_due_date)>=today()),[gauges])
 const selectedCharacteristic=characteristics.find(c=>String(c.id)===String(entry.characteristic_id))
 const productOperations=operations
 async function loadMasters(){
  const [p,o,g,c]=await Promise.all([api('/masters/products'),api('/masters/operations'),api('/calibration/instruments'),api('/calibration/inspection/characteristics')])
  setProducts(p);setOperations(o);setGauges(g);setCharacteristics(c)
 }
 async function loadRecords(){
  const q=new URLSearchParams()
  if(fromDate)q.set('from_date',fromDate);if(toDate)q.set('to_date',toDate);if(filterProduct)q.set('product_id',filterProduct)
  const data=await api('/calibration/inspection/measurements'+(q.toString()?'?'+q.toString():''))
  setRecords(data)
 }
 useEffect(()=>{Promise.all([loadMasters(),loadRecords()]).catch((e:any)=>setError(e.message))},[])
 useEffect(()=>{setEntry((v:any)=>({...v,characteristic_id:''}))},[entry.product_id,entry.operation_id])
 useEffect(()=>{if(!selectedCharacteristic)return;setEntry((v:any)=>({...v,measured_values:Array.from({length:Number(selectedCharacteristic.sample_size)},(_,i)=>v.measured_values?.[i]??'')}))},[entry.characteristic_id])
 async function saveCharacteristic(){
  setBusy(true);setError('');setMessage('')
  try{
   const payload={...master,product_id:Number(master.product_id),operation_id:master.operation_id?Number(master.operation_id):null,nominal_value:Number(master.nominal_value),lower_tolerance:Number(master.lower_tolerance),upper_tolerance:Number(master.upper_tolerance),sample_size:Number(master.sample_size)}
   await api('/calibration/inspection/characteristics',{method:'POST',body:JSON.stringify(payload)})
   setMaster(emptyCharacteristic);await loadMasters();setMessage('Inspection characteristic created.')
  }catch(e:any){setError(e.message)}finally{setBusy(false)}
 }
 async function saveMeasurement(){
  setBusy(true);setError('');setMessage('')
  try{
   const payload={...entry,product_id:Number(entry.product_id),operation_id:entry.operation_id?Number(entry.operation_id):null,characteristic_id:Number(entry.characteristic_id),instrument_id:Number(entry.instrument_id),measured_values:entry.measured_values.map(Number)}
   const result:any=await api('/calibration/inspection/measurements',{method:'POST',body:JSON.stringify(payload)})
   setMessage('Measurement saved: '+result.result+' · '+result.out_of_tolerance_count+' out-of-tolerance sample(s).')
   setEntry({...emptyEntry,inspection_date:entry.inspection_date,product_id:entry.product_id,operation_id:entry.operation_id})
   await loadRecords()
  }catch(e:any){setError(e.message)}finally{setBusy(false)}
 }
 const setSample=(index:number,value:string)=>setEntry((v:any)=>({...v,measured_values:v.measured_values.map((x:string,i:number)=>i===index?value:x)}))
 return <div className="page">
  <header className="page-header"><div><h1>Inspection Measurements</h1><p>Record dimensional checks with controlled characteristics and calibration-verified gauges.</p></div><button className="secondary" onClick={()=>Promise.all([loadMasters(),loadRecords()]).catch((e:any)=>setError(e.message))}>Refresh</button></header>
  {error&&<div className="error">{error}</div>}{message&&<div className="success">{message}</div>}
  <section className="panel"><h2>Inspection Characteristic Master</h2><p>Define nominal size and permitted limits for each product and operation. Lower and upper tolerance are absolute measurement limits.</p>
   <div className="machine-field-grid">
    <label>Product<select value={master.product_id} onChange={e=>setMaster({...master,product_id:e.target.value})}><option value="">Select product</option>{products.map(p=><option key={p.id} value={p.id}>{p.code} — {p.name}</option>)}</select></label>
    <label>Operation<select value={master.operation_id} onChange={e=>setMaster({...master,operation_id:e.target.value})}><option value="">All / not operation-specific</option>{operations.map(o=><option key={o.id} value={o.id}>{o.code||o.operation_code} — {o.name||o.operation_name}</option>)}</select></label>
    <label>Characteristic Code<input value={master.characteristic_code} onChange={e=>setMaster({...master,characteristic_code:e.target.value})} placeholder="e.g. OD-01"/></label>
    <label>Characteristic Name<input value={master.name} onChange={e=>setMaster({...master,name:e.target.value})} placeholder="e.g. Outer diameter"/></label>
    <label>Nominal Value<input type="number" step="any" value={master.nominal_value} onChange={e=>setMaster({...master,nominal_value:e.target.value})}/></label>
    <label>Lower Limit<input type="number" step="any" value={master.lower_tolerance} onChange={e=>setMaster({...master,lower_tolerance:e.target.value})}/></label>
    <label>Upper Limit<input type="number" step="any" value={master.upper_tolerance} onChange={e=>setMaster({...master,upper_tolerance:e.target.value})}/></label>
    <label>Unit<input value={master.unit} onChange={e=>setMaster({...master,unit:e.target.value})} placeholder="mm"/></label>
    <label>Sample Size<input type="number" min="1" max="100" value={master.sample_size} onChange={e=>setMaster({...master,sample_size:e.target.value})}/></label>
    <label>Control Plan Reference<input value={master.control_plan_reference} onChange={e=>setMaster({...master,control_plan_reference:e.target.value})}/></label>
    <label>Special Characteristic<input value={master.special_characteristic} onChange={e=>setMaster({...master,special_characteristic:e.target.value})}/></label>
   </div><button onClick={saveCharacteristic} disabled={busy||!master.product_id||!master.characteristic_code||!master.name||master.nominal_value===''||master.lower_tolerance===''||master.upper_tolerance===''||!master.unit}>Save Characteristic</button>
   <div className="table-wrap"><table><thead><tr><th>Product</th><th>Operation</th><th>Code</th><th>Characteristic</th><th>Nominal</th><th>Limits</th><th>Unit</th><th>Samples</th></tr></thead><tbody>{characteristics.map(c=><tr key={c.id}><td>{c.product_code}</td><td>{c.operation_name||'All'}</td><td>{c.characteristic_code}</td><td>{c.name}</td><td>{c.nominal_value}</td><td>{c.lower_tolerance} – {c.upper_tolerance}</td><td>{c.unit}</td><td>{c.sample_size}</td></tr>)}{!characteristics.length&&<tr><td colSpan={8}>No inspection characteristics created yet.</td></tr>}</tbody></table></div>
  </section>
  <section className="panel"><h2>Capture Inspection Measurement</h2><p>Only gauges with an allowed calibration status and a future/current due date are selectable. The server rechecks gauge status and due date when saving.</p>
   <div className="machine-field-grid">
    <label>Inspection Date<input type="date" value={entry.inspection_date} onChange={e=>setEntry({...entry,inspection_date:e.target.value})}/></label>
    <label>Product<select value={entry.product_id} onChange={e=>setEntry({...entry,product_id:e.target.value,characteristic_id:'',operation_id:''})}><option value="">Select product</option>{products.map(p=><option key={p.id} value={p.id}>{p.code} — {p.name}</option>)}</select></label>
    <label>Operation<select value={entry.operation_id} onChange={e=>setEntry({...entry,operation_id:e.target.value,characteristic_id:''})}><option value="">Select operation</option>{operations.filter(o=>!entry.product_id||String(o.product_id)===String(entry.product_id)).map(o=><option key={o.id} value={o.id}>{o.code||o.operation_code} — {o.name||o.operation_name}</option>)}</select></label>
    <label>Characteristic<select value={entry.characteristic_id} onChange={e=>setEntry({...entry,characteristic_id:e.target.value})}><option value="">Select characteristic</option>{characteristics.filter(c=>String(c.product_id)===String(entry.product_id)&&(!c.operation_id||String(c.operation_id)===String(entry.operation_id))).map(c=><option key={c.id} value={c.id}>{c.characteristic_code} — {c.name} ({c.lower_tolerance}–{c.upper_tolerance} {c.unit})</option>)}</select></label>
    <label>Gauge / Instrument<select value={entry.instrument_id} onChange={e=>setEntry({...entry,instrument_id:e.target.value})}><option value="">Select calibrated gauge</option>{eligibleGauges.map(g=><option key={g.id} value={g.id}>{g.instrument_code} — {g.name} · {g.status} · Due {g.next_due_date}</option>)}</select></label>
    <label>Lot / Batch Reference<input value={entry.lot_reference} onChange={e=>setEntry({...entry,lot_reference:e.target.value})}/></label>
    <label>Machine Reference<input value={entry.machine_reference} onChange={e=>setEntry({...entry,machine_reference:e.target.value})}/></label>
    <label>Shift<select value={entry.shift} onChange={e=>setEntry({...entry,shift:e.target.value})}>{['A','B','C','General'].map(x=><option key={x}>{x}</option>)}</select></label>
    <label>Operator<input value={entry.operator_name} onChange={e=>setEntry({...entry,operator_name:e.target.value})}/></label>
   </div>
   {selectedCharacteristic&&<div className="panel"><h3>{selectedCharacteristic.name} · {selectedCharacteristic.sample_size} sample(s)</h3><p>Nominal: {selectedCharacteristic.nominal_value} {selectedCharacteristic.unit} · Allowed: {selectedCharacteristic.lower_tolerance} to {selectedCharacteristic.upper_tolerance} {selectedCharacteristic.unit}</p><div className="machine-field-grid">{entry.measured_values.map((v:string,i:number)=><label key={i}>Sample {i+1}<input type="number" step="any" value={v} onChange={e=>setSample(i,e.target.value)}/></label>)}</div></div>}
   <label>Remarks<textarea value={entry.remarks} onChange={e=>setEntry({...entry,remarks:e.target.value})}/></label>
   <button onClick={saveMeasurement} disabled={busy||!entry.product_id||!entry.characteristic_id||!entry.instrument_id||!entry.measured_values.length||entry.measured_values.some((v:string)=>v==='')}>Save Inspection Result</button>
  </section>
  <section className="panel"><h2>Inspection Measurement History</h2><div className="toolbar"><label>From<input type="date" value={fromDate} onChange={e=>setFromDate(e.target.value)}/></label><label>To<input type="date" value={toDate} onChange={e=>setToDate(e.target.value)}/></label><label>Product<select value={filterProduct} onChange={e=>setFilterProduct(e.target.value)}><option value="">All products</option>{products.map(p=><option key={p.id} value={p.id}>{p.code} — {p.name}</option>)}</select></label><button className="secondary" onClick={()=>loadRecords().catch((e:any)=>setError(e.message))}>Apply Filters</button></div>
   <div className="table-wrap"><table><thead><tr><th>Date</th><th>Product</th><th>Characteristic</th><th>Lot</th><th>Gauge Snapshot</th><th>Samples</th><th>Result</th><th>Quality Follow-up</th><th>Remarks</th></tr></thead><tbody>{records.map(r=><tr key={r.id}><td>{r.inspection_date}</td><td>{r.product_code} — {r.product_name}</td><td>{r.characteristic_code} — {r.characteristic_name}<div className="muted">{r.characteristic_snapshot?.lower_tolerance}–{r.characteristic_snapshot?.upper_tolerance} {r.characteristic_snapshot?.unit}</div></td><td>{r.lot_reference||'—'}</td><td>{r.gauge_snapshot?.instrument_code} — {r.gauge_snapshot?.name}<div className="muted">{r.gauge_snapshot?.status_at_measurement} · Due {r.gauge_snapshot?.calibration_due_date}</div></td><td>{(r.samples||[]).map((v:any)=><div key={v.sample_no}>#{v.sample_no}: {v.measured_value} {v.is_within_tolerance?'✓':'✕'}</div>)}</td><td><strong className={r.result==='PASS'?'success-text':'error-text'}>{r.result}</strong></td><td>{r.result==='FAIL'?<button className="secondary small" onClick={()=>{if(window.confirm('This measurement is out of tolerance. Open Quality / Rejection to review the defect and decide whether to create a rejection record?'))window.location.assign('/quality')}}>Review in Quality</button>:'—'}</td><td>{r.remarks||'—'}</td></tr>)}{!records.length&&<tr><td colSpan={9}>No measurement records found.</td></tr>}</tbody></table></div>
  </section>
 </div>
}
