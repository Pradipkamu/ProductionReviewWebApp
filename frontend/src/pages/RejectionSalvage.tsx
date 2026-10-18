import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import { Kpi, PageHeader, num } from '../components/UI'
import { MultiSelect } from '../components/MultiSelect'
import { dateIST, daysAgoIST, formatIST } from '../time'

export default function RejectionSalvage({me}:{me:any}) {
  const navigate = useNavigate()
  const [fromDate,setFromDate] = useState(daysAgoIST(30))
  const [toDate,setToDate] = useState(dateIST())
  const [plant,setPlant] = useState('')
  const [productId,setProductId] = useState('')
  const [products,setProducts] = useState<any[]>([])
  const [filters,setFilters] = useState<any>({plants:[]})
  const [rows,setRows] = useState<any[]>([])
  const [requests,setRequests] = useState<any[]>([])
  const [selected,setSelected] = useState<any>(null)
  const [salvageQty,setSalvageQty] = useState('')
  const [reason,setReason] = useState('')
  const [reviewNotes,setReviewNotes] = useState<Record<number,string>>({})
  const [busy,setBusy] = useState(false)
  const [saving,setSaving] = useState(false)
  const [error,setError] = useState('')
  const [notice,setNotice] = useState('')
  const role = String(me?.role||'')
  const canSubmit = role === 'PRODUCTION' || role === 'ADMIN'
  const canReview = role === 'QUALITY' || role === 'ADMIN'

  const query = useMemo(() => {
    const p = new URLSearchParams({from_date:fromDate,to_date:toDate})
    if(plant) p.set('plant',plant)
    if(productId) p.set('product_id',productId)
    return p.toString()
  },[fromDate,toDate,plant,productId])

  const plantProducts = useMemo(
    () => products.filter(p=>!plant || String(p.plant||'').trim()===plant),
    [products,plant]
  )

  async function loadMasters() {
    const [allProducts,filterOptions] = await Promise.all([
      api<any[]>('/masters/products'),
      api<any>('/masters/filter-options')
    ])
    setProducts(allProducts)
    setFilters(filterOptions)
  }

  async function load() {
    setBusy(true); setError('')
    try {
      const [eligible,history] = await Promise.all([
        api<any[]>('/quality/salvage/rejections?' + query),
        api<any[]>('/quality/salvage/requests?' + new URLSearchParams({from_date:fromDate,to_date:toDate}).toString())
      ])
      setRows(eligible); setRequests(history)
      if(selected) {
        const latest = eligible.find(x=>x.rejection_id===selected.rejection_id)
        setSelected(latest && Number(latest.available_qty)>0 ? latest : null)
      }
    } catch(e:any) { setError(e.message) }
    finally { setBusy(false) }
  }

  useEffect(()=>{loadMasters().catch((e:any)=>setError(e.message))},[])
  useEffect(()=>{load()},[query])

  const pending = requests.filter(x=>x.status==='PENDING')
  const approved = requests.filter(x=>x.status==='APPROVED')
  const visibleRows = rows.filter(x=>Number(x.original_reject_qty)>0)

  async function submitRequest(e:React.FormEvent) {
    e.preventDefault()
    setError(''); setNotice('')
    if(!selected) return
    if(Number(salvageQty)<=0 || Number(salvageQty)>Number(selected.available_qty)) {
      setError('Enter a salvage quantity greater than zero and not more than ' + num(selected.available_qty) + '.')
      return
    }
    if(reason.trim().length<10) { setError('Please enter a reason of at least 10 characters.'); return }
    setSaving(true)
    try {
      const result:any = await api('/quality/salvage/requests',{method:'POST',body:JSON.stringify({
        rejection_id:selected.rejection_id,salvage_qty:Number(salvageQty),reason:reason.trim()
      })})
      setNotice('Salvage request #' + result.id + ' submitted for Quality approval.')
      setSelected(null); setSalvageQty(''); setReason('')
      await load()
    } catch(e:any) { setError(e.message) }
    finally { setSaving(false) }
  }

  async function reviewRequest(id:number,action:'APPROVE'|'REJECT') {
    setError(''); setNotice('')
    const note = reviewNotes[id]||''
    if(action==='REJECT' && note.trim().length<5) {
      setError('Enter a rejection reason of at least 5 characters before rejecting.')
      return
    }
    setSaving(true)
    try {
      const result:any = await api('/quality/salvage/requests/' + id + '/review',{
        method:'POST',body:JSON.stringify({action,note:note.trim()||null})
      })
      setNotice(action==='APPROVE'
        ? 'Request #' + id + ' approved. Net rejection is now ' + num(result.net_reject_qty) + '.'
        : 'Request #' + id + ' rejected. Rejection figures remain unchanged.')
      await load()
    } catch(e:any) { setError(e.message) }
    finally { setSaving(false) }
  }

  return <>
    <PageHeader title="Rejection Correction & Salvage" subtitle="Production requests salvage; Quality approves it. Original rejection entries remain unchanged." actions={<button className="secondary" onClick={()=>navigate('/quality')}>Back to Quality / Rejection</button>}/>
    <section className="panel">
      <p className="salvage-explainer">Only approved salvage reduces net rejected quantity and PPM. Pending or rejected requests never change reports. Every request retains its reason, requester, reviewer and before / after approved quantities.</p>
      <div className="filters salvage-filters">
        <label>From Date<input type="date" value={fromDate} onChange={e=>setFromDate(e.target.value)}/></label>
        <label>To Date<input type="date" value={toDate} onChange={e=>setToDate(e.target.value)}/></label>
        <label>Plant<MultiSelect singleSelect value={plant?[plant]:[]} onChange={v=>{setPlant(v.at(-1)||'');setProductId('')}} placeholder="All Plants" options={(filters.plants||[]).map((x:string)=>({value:String(x),label:String(x)}))}/></label>
        <label>Part Number / Name<MultiSelect singleSelect value={productId?[productId]:[]} onChange={v=>setProductId(v.at(-1)||'')} placeholder="All Parts" options={plantProducts.map((p:any)=>({value:String(p.id),label:`${p.code} — ${p.name}`}))}/></label>
      </div>
      {error&&<div className="error">{error}</div>}
      {notice&&<div className="notice">{notice}</div>}
    </section>
    <div className="kpi-grid">
      <Kpi label="Eligible Rejection Rows" value={visibleRows.length}/>
      <Kpi label="Pending Approval" value={pending.length} tone={pending.length?'warn':'good'}/>
      <Kpi label="Approved Salvage Qty" value={num(approved.reduce((n,x)=>n+Number(x.requested_qty||0),0))} tone="good"/>
    </div>
    {selected&&<section className="panel salvage-request-panel">
      <div className="panel-title"><div><h2>Submit Salvage Request</h2><p>{selected.product_code} • {selected.product} • {selected.date} • {selected.phenomenon}</p></div><button className="secondary" onClick={()=>setSelected(null)}>Close</button></div>
      <div className="salvage-quantity-summary">
        <div><span>Original Reject</span><b>{num(selected.original_reject_qty)}</b></div>
        <div><span>Already Approved</span><b>{num(selected.approved_salvage_qty)}</b></div>
        <div><span>Net Rejection</span><b>{num(selected.net_reject_qty)}</b></div>
        <div><span>Available to Request</span><b>{num(selected.available_qty)}</b></div>
      </div>
      <form onSubmit={submitRequest}>
        <div className="salvage-form-grid">
          <label>Salvage Quantity<input type="number" min="0.001" max={selected.available_qty} step="0.001" value={salvageQty} onChange={e=>setSalvageQty(e.target.value)} required/></label>
          <label className="salvage-reason">Reason / Evidence<textarea value={reason} onChange={e=>setReason(e.target.value)} minLength={10} maxLength={1000} placeholder="Explain how the rejected quantity was salvaged, reworked and accepted. Mention verification or inspection evidence." required/></label>
        </div>
        <div className="button-row"><button type="submit" disabled={saving}>{saving?'Submitting...':'Submit for Quality Approval'}</button><button type="button" className="secondary" onClick={()=>setSelected(null)}>Cancel</button></div>
      </form>
    </section>}
    <section className="panel">
      <div className="panel-title"><div><h2>Daily Rejection Records</h2><p>Select a part-wise rejection record to request salvage approval. Only daily rejection detail is eligible; monthly aggregate history is not editable at part / date level.</p></div><span>{visibleRows.length} records{busy?' • Refreshing...':''}</span></div>
      <div className="table-wrap"><table><thead><tr><th>Date / Shift</th><th>Plant</th><th>Part Number</th><th>Detection Process</th><th>Phenomenon</th><th>Original Reject</th><th>Approved Salvage</th><th>Net Reject</th><th>Pending</th><th>Available</th><th>Action</th></tr></thead><tbody>
        {visibleRows.map(row=><tr key={row.rejection_id}>
          <td>{row.date}<br/><small>{row.shift}</small></td><td>{row.plant||'—'}</td><td><b>{row.product_code}</b><br/>{row.product}</td><td>{row.detection_process||'—'}</td><td>{row.phenomenon}</td>
          <td>{num(row.original_reject_qty)}</td><td>{num(row.approved_salvage_qty)}</td><td><b>{num(row.net_reject_qty)}</b></td><td>{num(row.pending_salvage_qty)}</td><td>{num(row.available_qty)}</td>
          <td>{canSubmit?<button className="small" disabled={Number(row.available_qty)<=0||saving} onClick={()=>{setSelected(row);setSalvageQty('');setReason('')}}>Request Salvage</button>:<span className="muted">—</span>}</td>
        </tr>)}
        {!visibleRows.length&&<tr><td colSpan={11} className="empty">No daily rejection records found for the selected dates and filters.</td></tr>}
      </tbody></table></div>
    </section>
    <section className="panel">
      <div className="panel-title"><div><h2>Salvage Approval Register</h2><p>Complete request history, including rejected and approved requests.</p></div><span>{requests.length} requests</span></div>
      <div className="table-wrap"><table><thead><tr><th>Request / Date</th><th>Part / Phenomenon</th><th>Requested Qty</th><th>Reason</th><th>Status</th><th>Requested By / At</th><th>Reviewed By / At</th><th>Approval Quantity Before → After</th><th>Review Note / Decision</th></tr></thead><tbody>
        {requests.map(item=><tr key={item.id}>
          <td>#{item.id}<br/><small>{item.date} • {item.shift}</small></td><td><b>{item.product_code}</b><br/>{item.product}<br/><small>{item.phenomenon}</small></td><td>{num(item.requested_qty)}</td><td>{item.reason}</td>
          <td><span className={'status ' + String(item.status).toLowerCase()}>{item.status}</span></td>
          <td>{item.requested_by}<br/><small>{formatIST(item.requested_at)}</small></td><td>{item.reviewed_by||'—'}<br/><small>{formatIST(item.reviewed_at)}</small></td>
          <td>{item.approved_before_qty==null?'—':num(item.approved_before_qty) + ' → ' + num(item.approved_after_qty)}</td>
          <td>{item.review_note||'—'}{canReview&&item.status==='PENDING'&&<div className="salvage-review-controls"><textarea value={reviewNotes[item.id]||''} onChange={e=>setReviewNotes(v=>({...v,[item.id]:e.target.value}))} placeholder="Optional approval note; mandatory rejection reason" rows={2}/><div className="button-row"><button className="small" disabled={saving} onClick={()=>reviewRequest(item.id,'APPROVE')}>Approve</button><button className="small danger-button" disabled={saving} onClick={()=>reviewRequest(item.id,'REJECT')}>Reject</button></div></div>}</td>
        </tr>)}
        {!requests.length&&<tr><td colSpan={9} className="empty">No salvage requests in the selected date range.</td></tr>}
      </tbody></table></div>
    </section>
  </>
}
