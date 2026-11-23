import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { api } from '../api'
import { PageHeader, Status } from '../components/UI'

function ReportTree({node,findings,depth=0}:{node:any,findings:any[],depth?:number}){
  const finding=findings.find(x=>x.node_id===node.id)
  return <div className="fta-report-tree-node" style={{marginLeft:depth*18}}>
    <div className="fta-report-tree-heading"><span>{node.gate||node.type?.replaceAll('_',' ')||'EVENT'}</span><b>{node.label}</b><Status value={finding?.investigation_status||'NOT_INVESTIGATED'}/></div>
    {finding&&<div className="fta-report-finding"><p>{finding.observation||'No observation recorded.'}</p>{finding.measured_value&&<small>Measured: {finding.measured_value} · Expected: {finding.expected_value||'—'}</small>}{finding.verification_method&&<p><b>Verification:</b> {finding.verification_method}</p>}{finding.verification_result&&<p><b>Result:</b> {finding.verification_result}</p>}{finding.is_root_cause&&<strong>Confirmed root cause</strong>}{finding.is_occurrence_cause&&<strong> · Occurrence cause</strong>}{finding.is_escape_cause&&<strong> · Escape cause</strong>}</div>}
    {(node.children||[]).map((child:any)=><ReportTree key={child.id} node={child} findings={findings} depth={depth+1}/>)}
  </div>
}

export default function FTAReport(){
  const {id}=useParams()
  const [data,setData]=useState<any>(null)
  const [error,setError]=useState('')
  const [busy,setBusy]=useState(true)
  useEffect(()=>{let live=true;api('/fta/investigations/'+id).then((x:any)=>{if(live)setData(x)}).catch((e:any)=>{if(live)setError(e.message||'Unable to load FTA report')}).finally(()=>{if(live)setBusy(false)});return()=>{live=false}},[id])
  const tree=data?.template_snapshot?.tree
  const confirmed=(data?.findings||[]).filter((x:any)=>x.investigation_status==='CONFIRMED'&&(x.is_root_cause||x.is_occurrence_cause||x.is_escape_cause))
  if(busy)return <div className="panel">Loading FTA report…</div>
  if(error||!data)return <div className="page"><div className="error">{error||'FTA report not found.'}</div><a href="/fta">Back to FTA</a></div>
  return <div className="page fta-report-page">
    <div className="fta-report-actions"><PageHeader title="FTA Investigation Report" subtitle="Complete fault tree, confirmed causes, action implementation and verification result." actions={<><button className="secondary" onClick={()=>window.print()}>Print / Save PDF</button><a className="button secondary" href="/fta?investigation_id={id}">Open investigation</a></>}/></div>
    <header className="fta-report-cover"><div><small>FAULT TREE ANALYSIS</small><h1>{data.investigation_no}</h1><p>{data.template_snapshot?.template_name||'Machining defect investigation'} · {data.status?.replaceAll('_',' ')}</p></div><div><b>Plant</b><span>{data.plant||'—'}</span><b>Operation</b><span>{data.operation_code||'—'}</span><b>Machine</b><span>{data.machine_id||'—'}</span><b>Rejection reference</b><span>#{data.rejection_id}</span></div></header>
    <section className="panel fta-report-section"><h2>1. Investigation summary</h2><p>{data.summary||'No initial summary recorded.'}</p><div className="fta-report-meta"><span><b>Investigation status:</b> {data.status}</span><span><b>Created:</b> {String(data.created_at||'').slice(0,10)}</span><span><b>Verified:</b> {data.verified_at?String(data.verified_at).slice(0,10):'Not verified'}</span><span><b>Closed:</b> {data.closed_at?String(data.closed_at).slice(0,10):'Not closed'}</span></div><h3>Occurrence cause analysis</h3><p>{data.occurrence_cause_summary||'Not recorded.'}</p><h3>Escape / detection cause analysis</h3><p>{data.escape_cause_summary||'Not recorded.'}</p></section>
    <section className="panel fta-report-section"><h2>2. Complete fault tree and investigation findings</h2>{tree?<ReportTree node={tree} findings={data.findings||[]}/>:<p>No fault-tree snapshot is available.</p>}</section>
    <section className="panel fta-report-section"><h2>3. Confirmed root-cause result</h2>{confirmed.length?confirmed.map((x:any)=><article className="fta-report-cause" key={x.id}><h3>{x.node_label}</h3><p>{x.observation||'No observation recorded.'}</p><p><b>Verification method:</b> {x.verification_method||'—'}</p><p><b>Verification result:</b> {x.verification_result||'—'}</p><small>{x.is_root_cause?'Root cause':''}{x.is_occurrence_cause?' · Occurrence cause':''}{x.is_escape_cause?' · Escape / detection cause':''}</small></article>):<p>No confirmed root cause has been recorded yet.</p>}</section>
    <section className="panel fta-report-section"><h2>4. Corrective / preventive action taken</h2><div className="table-wrap"><table><thead><tr><th>Action No.</th><th>Relationship</th><th>Action description</th><th>Owner ID</th><th>Due</th><th>Status</th></tr></thead><tbody>{(data.actions||[]).map((x:any)=><tr key={x.link_id}><td>{x.action_no}</td><td>{x.relationship_type}</td><td>{x.action_description}</td><td>{x.owner_id||'—'}</td><td>{x.due_at?String(x.due_at).replace('T',' ').slice(0,16):'—'}</td><td>{x.status}</td></tr>)}{!data.actions?.length&&<tr><td colSpan={6}>No linked actions.</td></tr>}</tbody></table></div></section>
    <section className="panel fta-report-section"><h2>5. Causes discovered during action implementation</h2>{(data.discovered_causes||[]).length?(data.discovered_causes||[]).map((x:any)=><article className="fta-report-cause" key={x.id}><h3>{x.cause_description}</h3><p><b>Source action:</b> {x.action_no} · <b>Status:</b> {x.status}</p><p><b>Evidence:</b> {x.evidence_reference||'—'}</p><p><b>Quality review:</b> {x.review_remarks||'Pending review'}</p><p><b>Verification method:</b> {x.verification_method||'—'}</p></article>):<p>No additional causes reported.</p>}</section>
    <section className="panel fta-report-section"><h2>6. Analysis result and closure</h2><p><b>Verification remarks:</b> {data.status_history?.find((x:any)=>x.new_status==='VERIFIED_PENDING_ACTIONS')?.remarks||'Not verified.'}</p><p><b>Final closure remarks:</b> {data.closure_remarks||'Not closed.'}</p><div className="table-wrap"><table><thead><tr><th>Date</th><th>From</th><th>To</th><th>Remarks</th></tr></thead><tbody>{(data.status_history||[]).map((x:any)=><tr key={x.id}><td>{String(x.created_at||'').replace('T',' ').slice(0,16)}</td><td>{x.old_status||'—'}</td><td>{x.new_status}</td><td>{x.remarks||'—'}</td></tr>)}</tbody></table></div></section>
    <footer className="fta-report-footer">Generated from the Production Review FTA record. The original investigation and action history remain the system of record.</footer>
  </div>
}
