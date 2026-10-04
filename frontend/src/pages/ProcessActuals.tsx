import { useEffect, useState } from 'react'
import { api } from '../api'
import { ScopeFilters, ScopeValues, appendScope } from '../components/ScopeFilters'
import { PageHeader, num } from '../components/UI'

function isoLocal(d:Date){
  const y=d.getFullYear(),m=String(d.getMonth()+1).padStart(2,'0'),day=String(d.getDate()).padStart(2,'0')
  return `${y}-${m}-${day}`
}
function lastCompletedDay(){
  const d=new Date()
  d.setDate(d.getDate()-1)
  return isoLocal(d)
}

const emptyScope:ScopeValues={plant:[],productGroup:[],customerId:[],productId:[]}

export default function ProcessActuals(){
  const [actualDate,setActualDate]=useState(lastCompletedDay())
  const [missingOnly,setMissingOnly]=useState(true)
  const [scope,setScope]=useState<ScopeValues>(emptyScope)
  const [options,setOptions]=useState<any>({})
  const [products,setProducts]=useState<any[]>([])
  const [data,setData]=useState<any>({counts:{rows:0,missing:0,entered:0},rows:[],products_without_route:[]})
  const [selected,setSelected]=useState<any>(null)
  const [actual,setActual]=useState('')
  const [reject,setReject]=useState('0')
  const [reason,setReason]=useState('')
  const [history,setHistory]=useState<any[]>([])
  const [busy,setBusy]=useState(false)
  const [msg,setMsg]=useState('')
  const [err,setErr]=useState('')

  useEffect(()=>{
    Promise.all([api('/masters/filter-options'),api('/masters/products')])
      .then(([o,p]:any)=>{setOptions(o);setProducts(p)})
      .catch((e:any)=>setErr(e.message))
  },[])

  async function load(){
    setBusy(true);setErr('')
    try{
      const q=appendScope(new URLSearchParams({actual_date:actualDate,missing_only:String(missingOnly)}),scope)
      setData(await api(`/process/actuals?${q}`))
    }catch(e:any){setErr(e.message)}
    finally{setBusy(false)}
  }
  useEffect(()=>{load()},[actualDate,missingOnly,scope.plant,scope.productGroup,scope.customerId,scope.productId])

  function edit(row:any){
    setSelected(row)
    setActual(row.actual_qty==null?'':String(row.actual_qty))
    setReject(row.reject_qty==null?'0':String(row.reject_qty))
    setReason(row.status==='MISSING'?'Missing process actual entered':'')
    setHistory([])
    setMsg('')
    setErr('')
  }

  async function save(){
    if(!selected)return
    const a=Number(actual),r=Number(reject)
    if(actual.trim()===''||!Number.isFinite(a)||a<0){setErr('Enter a valid non-negative actual quantity.');return}
    if(!Number.isFinite(r)||r<0||r>a){setErr('Reject quantity must be between 0 and Actual.');return}
    if(reason.trim().length<2){setErr('Correction / entry reason is required.');return}
    setBusy(true);setErr('')
    try{
      const saved:any=await api('/process/actuals',{method:'PUT',body:JSON.stringify({
        summary_date:actualDate,
        product_id:selected.product_id,
        route_operation_id:selected.route_operation_id,
        actual_qty:a,
        reject_qty:r,
        reason:reason.trim(),
      })})
      setMsg(`${selected.product} / ${selected.stage_name} saved. Good Qty = ${num(saved.good_qty)}.`)
      setSelected(null);setHistory([])
      await load()
    }catch(e:any){setErr(e.message)}
    finally{setBusy(false)}
  }

  async function showHistory(row:any){
    if(!row.id)return
    setSelected(row)
    setActual(row.actual_qty==null?'':String(row.actual_qty))
    setReject(row.reject_qty==null?'0':String(row.reject_qty))
    setReason('')
    setBusy(true);setErr('')
    try{setHistory(await api(`/process/actuals/${row.id}/history`))}
    catch(e:any){setErr(e.message)}
    finally{setBusy(false)}
  }

  return <>
    <PageHeader title="Process Actuals / Historical Edit" subtitle="Find missing process actuals or correct entered quantities. Zero is treated as a valid entered value; only an absent record is Missing." actions={<label>Date<input type="date" value={actualDate} onChange={e=>setActualDate(e.target.value)}/></label>}/>
    <ScopeFilters value={scope} onChange={setScope} options={options} products={products}/>
    <section className="panel">
      <div className="panel-title">
        <div><h2>Process Actual Status</h2><p>Use Missing only for daily completion checks; switch it off to correct an existing process actual.</p></div>
        <label><input type="checkbox" checked={missingOnly} onChange={e=>setMissingOnly(e.target.checked)}/> Missing only</label>
      </div>
      {busy&&<div className="notice">Refreshing process actuals…</div>}
      {err&&<div className="error">{err}</div>}
      {msg&&<div className="notice">{msg}</div>}
      <div className="kpi-grid">
        <div className="kpi"><span>Rows shown</span><strong>{data?.counts?.rows||0}</strong></div>
        <div className="kpi"><span>Missing</span><strong>{data?.counts?.missing||0}</strong></div>
        <div className="kpi"><span>Entered</span><strong>{data?.counts?.entered||0}</strong></div>
      </div>
      {(data?.products_without_route||[]).length>0&&<div className="warning-box"><b>No effective process route:</b> {(data.products_without_route||[]).join(', ')}</div>}
      <div className="table-wrap">
        <table>
          <thead><tr><th>Plant</th><th>Product</th><th>Stage / Process</th><th>Role</th><th>Plan</th><th>Actual</th><th>Good</th><th>Reject</th><th>Status</th><th>Source / Updated</th><th></th></tr></thead>
          <tbody>
            {(data?.rows||[]).map((r:any)=><tr key={`${r.product_id}-${r.route_operation_id}`} className={r.status==='MISSING'?'row-overdue':''}>
              <td>{r.plant||'—'}</td>
              <td><b>{r.product}</b><br/><small>{r.product_group||'—'}</small></td>
              <td><b>{r.stage_name}</b><br/><small>{r.stage_code}</small></td>
              <td>{String(r.role||'').replaceAll('_',' ')}</td>
              <td>{r.plan_missing?<span className="status watch">Plan missing</span>:num(r.plan_qty)}</td>
              <td>{r.actual_qty==null?'Missing':num(r.actual_qty)}</td>
              <td>{r.good_qty==null?'—':num(r.good_qty)}</td>
              <td>{r.reject_qty==null?'—':num(r.reject_qty)}</td>
              <td><span className={`status ${r.status==='MISSING'?'bad':'good'}`}>{r.status}</span></td>
              <td>{r.source||'—'}<br/><small>{r.updated_at?String(r.updated_at).replace('T',' ').slice(0,16):'—'}</small></td>
              <td><div className="form-row compact"><button className="small" onClick={()=>edit(r)}>{r.status==='MISSING'?'Enter':'Edit'}</button>{r.id&&<button className="small secondary" onClick={()=>showHistory(r)}>History</button>}</div></td>
            </tr>)}
            {!data?.rows?.length&&<tr><td colSpan={11} className="muted">{missingOnly?'No missing process actuals for this date and filter.':'No process stages are available for this date and filter.'}</td></tr>}
          </tbody>
        </table>
      </div>
    </section>

    {selected&&<section className="panel">
      <div className="panel-title"><div><h2>{selected.status==='MISSING'?'Enter':'Correct'} Process Actual</h2><p>{selected.product} • {selected.stage_name} • {actualDate}</p></div><button className="small secondary" onClick={()=>{setSelected(null);setHistory([])}}>Close</button></div>
      <div className="form-row">
        <label>Plan<input value={selected.plan_qty==null?'Missing':String(selected.plan_qty)} disabled/></label>
        <label>Actual Qty<input type="number" min="0" step="1" value={actual} onChange={e=>setActual(e.target.value)}/></label>
        <label>Reject Qty<input type="number" min="0" step="1" value={reject} onChange={e=>setReject(e.target.value)}/></label>
        <label>Good Qty<input value={actual.trim()===''?'—':String(Math.max(0,Number(actual||0)-Number(reject||0)))} disabled/></label>
      </div>
      <label>Entry / correction reason<textarea value={reason} onChange={e=>setReason(e.target.value)} placeholder="Why was the process actual missing or why is the old value being corrected?"/></label>
      <div className="form-row"><button onClick={save} disabled={busy}>Save Process Actual</button>{selected.id&&<button className="secondary" onClick={()=>showHistory(selected)} disabled={busy}>Refresh History</button>}</div>

      {history.length>0&&<div className="table-wrap"><table><thead><tr><th>Changed</th><th>By</th><th>Type</th><th>Actual Old → New</th><th>Reject Old → New</th><th>Good Old → New</th><th>Reason</th></tr></thead><tbody>
        {history.map((h:any)=><tr key={h.id}><td>{String(h.changed_at||'').replace('T',' ').slice(0,16)}</td><td>{h.changed_by||'—'}</td><td>{h.change_type}</td><td>{h.old_actual_qty==null?'—':num(h.old_actual_qty)} → {num(h.new_actual_qty)}</td><td>{h.old_reject_qty==null?'—':num(h.old_reject_qty)} → {num(h.new_reject_qty)}</td><td>{h.old_good_qty==null?'—':num(h.old_good_qty)} → {num(h.new_good_qty)}</td><td>{h.reason}</td></tr>)}
      </tbody></table></div>}
    </section>}
  </>
}
