import { useEffect, useMemo, useState } from 'react'
import { api, downloadApi } from '../api'
import { PageHeader, Kpi } from '../components/UI'

type FtaNode = { id:string, label:string, type:string, gate?:string|null, logic_state?:string, children?:FtaNode[] }
type Finding = {
  id:number, node_id:string, node_label:string, node_type:string, investigation_status:string,
  observation?:string|null, measured_value?:string|null, expected_value?:string|null,
  verification_method?:string|null, verification_result?:string|null,
  is_root_cause:boolean, is_occurrence_cause:boolean, is_escape_cause:boolean
}

function TreeNode({node,findings,selected,onSelect,depth=0}:{node:FtaNode,findings:Finding[],selected:string,onSelect:(id:string)=>void,depth?:number}){
  const finding=findings.find(x=>x.node_id===node.id)
  const status=finding?.investigation_status||'NOT_INVESTIGATED'
  const tone=status==='CONFIRMED'?'success':status==='SUSPECTED'?'warning':status==='RULED_OUT'?'muted':''
  return <div className="fta-tree-node" style={{marginLeft:depth?18:0}}>
    <button type="button" className={`fta-node-button ${selected===node.id?'selected':''}`} onClick={()=>onSelect(node.id)}>
      <span className="fta-node-gate">{node.gate||node.type.replaceAll('_',' ')}</span>
      <strong>{node.label}</strong>
      <span className={`fta-node-status ${tone}`}>{status.replaceAll('_',' ')}</span><span className="fta-node-logic">{node.logic_state||'UNKNOWN'}</span>
    </button>
    {!!node.children?.length&&<div className="fta-tree-children">
      {node.children.map(child=><TreeNode key={child.id} node={child} findings={findings} selected={selected} onSelect={onSelect} depth={depth+1}/>)}
    </div>}
  </div>
}

export default function FTA({me}:{me:any}){
  const [operations,setOperations]=useState<any[]>([])
  const [defects,setDefects]=useState<any[]>([])
  const [templates,setTemplates]=useState<any[]>([])
  const [rejections,setRejections]=useState<any[]>([])
  const [machines,setMachines]=useState<any[]>([])
  const [machineId,setMachineId]=useState('')
  const [investigations,setInvestigations]=useState<any[]>([])
  const [dashboard,setDashboard]=useState<any>({counts:{}})
  const [operationCode,setOperationCode]=useState('')
  const [defectCode,setDefectCode]=useState('')
  const [selectedTemplateId,setSelectedTemplateId]=useState('')
  const [rejectionId,setRejectionId]=useState('')
  const [selectedId,setSelectedId]=useState<number|null>(null)
  const [detail,setDetail]=useState<any>(null)
  const [selectedNode,setSelectedNode]=useState('')
  const [findingForm,setFindingForm]=useState<any>({})
  const [summary,setSummary]=useState('')
  const [occurrenceSummary,setOccurrenceSummary]=useState('')
  const [escapeSummary,setEscapeSummary]=useState('')
  const [availableActions,setAvailableActions]=useState<any[]>([])
  const [actionId,setActionId]=useState('')
  const [actionRelationship,setActionRelationship]=useState('CORRECTIVE')
  const [newActionDescription,setNewActionDescription]=useState('Implement corrective action for confirmed FTA root cause')
  const [evidenceFile,setEvidenceFile]=useState<File|null>(null)
  const [evidenceCaption,setEvidenceCaption]=useState('')
  const [baseTemplateId,setBaseTemplateId]=useState('')
  const [templateName,setTemplateName]=useState('')
  const [templateTreeText,setTemplateTreeText]=useState('')
  const [templateDraftId,setTemplateDraftId]=useState<number|null>(null)
  const [newOperationCode,setNewOperationCode]=useState('')
  const [newOperationName,setNewOperationName]=useState('')
  const [newDefectCode,setNewDefectCode]=useState('')
  const [newDefectCategory,setNewDefectCategory]=useState('Dimensional')
  const [newDefectName,setNewDefectName]=useState('')
  const [newTemplateCode,setNewTemplateCode]=useState('')
  const [newTemplateName,setNewTemplateName]=useState('')
  const [newTemplateOperation,setNewTemplateOperation]=useState('')
  const [newTemplateDefect,setNewTemplateDefect]=useState('')
  const [verificationRemarks,setVerificationRemarks]=useState('Root cause and investigation evidence reviewed.')
  const [closureRemarks,setClosureRemarks]=useState('Corrective action completed and effectiveness verified.')
  const canManageTemplates=['ADMIN','QUALITY'].includes(me?.role)
  const canWrite=['ADMIN','QUALITY','PRODUCTION'].includes(me?.role)
  const canVerify=['ADMIN','QUALITY'].includes(me?.role)
  const [busy,setBusy]=useState(false)
  const [error,setError]=useState('')
  const [message,setMessage]=useState('')

  const filteredTemplates=useMemo(()=>templates.filter(t=>t.status==='PUBLISHED'&&(!operationCode||t.operation_code===operationCode)&&(!defectCode||t.defect_code===defectCode)),[templates,operationCode,defectCode])
  const selectedTemplate=filteredTemplates.find(t=>String(t.id)===selectedTemplateId)||filteredTemplates[0]
  const selectedRejection=rejections.find(r=>String(r.id)===rejectionId)
  const plantMachines=machines.filter(m=>m.active!==false&&(!selectedRejection?.plant||m.plant===selectedRejection.plant))
  const currentFinding:Finding|undefined=detail?.findings?.find((f:Finding)=>f.node_id===selectedNode)
  const hasRequiredAction=(detail?.actions||[]).some((a:any)=>['CORRECTIVE','PREVENTIVE'].includes(a.relationship_type))

  async function load(){
    setBusy(true);setError('')
    try{
      const [o,d,t,r,i,stats,m]=await Promise.all([
        api('/fta/operations'),api('/fta/defects'),api('/fta/templates'+(canManageTemplates?'?include_drafts=true':'')),api('/fta/rejections?limit=200'),
        api('/fta/investigations'),api('/fta/dashboard'),api('/masters/machines')
      ])
      setOperations(o as any[]);setDefects(d as any[]);setTemplates(t as any[]);setRejections(r as any[]);setMachines(m as any[])
      setInvestigations(i as any[]);setDashboard(stats)
      const actionRows:any[]=await api('/actions');setAvailableActions(actionRows.filter(a=>a.status!=='CLOSED'&&(me?.role!=='PRODUCTION'||a.owner_id===me?.id)))
    }catch(e:any){setError(e.message||'Unable to load FTA workspace.')}
    finally{setBusy(false)}
  }
  async function loadDetail(id:number){
    setError('')
    try{
      const result:any=await api(`/fta/investigations/${id}`)
      setDetail(result);setSelectedId(id);setSelectedNode(result.template_snapshot?.tree?.id||'')
      setSummary(result.summary||'');setOccurrenceSummary(result.occurrence_cause_summary||'');setEscapeSummary(result.escape_cause_summary||'')
    }catch(e:any){setError(e.message||'Unable to load investigation.')}
  }
  useEffect(()=>{load()},[me?.role])
  useEffect(()=>{
    if(!currentFinding){setFindingForm({});return}
    setFindingForm({
      investigation_status:currentFinding.investigation_status||'NOT_INVESTIGATED',
      observation:currentFinding.observation||'',measured_value:currentFinding.measured_value||'',
      expected_value:currentFinding.expected_value||'',verification_method:currentFinding.verification_method||'',
      verification_result:currentFinding.verification_result||'',is_root_cause:!!currentFinding.is_root_cause,
      is_occurrence_cause:!!currentFinding.is_occurrence_cause,is_escape_cause:!!currentFinding.is_escape_cause
    })
  },[selectedNode,detail?.id,currentFinding?.updated_at])

  async function createInvestigation(){
    if(!rejectionId||!operationCode||!defectCode||!filteredTemplates.length){setError('Select a machining operation, defect, rejection and matching published template.');return}
    setBusy(true);setError('');setMessage('')
    try{
      const result:any=await api('/fta/investigations',{method:'POST',body:JSON.stringify({
        rejection_id:Number(rejectionId),template_id:Number(selectedTemplate.id),machine_id:machineId?Number(machineId):null,summary:summary||null
      })})
      await load();await loadDetail(result.id);setMessage(`Investigation ${result.investigation_no} created.`)
    }catch(e:any){setError(e.message||'Unable to create investigation.')}
    finally{setBusy(false)}
  }
  async function saveFinding(){
    if(!detail||!selectedNode)return
    setBusy(true);setError('');setMessage('')
    try{
      await api(`/fta/investigations/${detail.id}/findings/${encodeURIComponent(selectedNode)}`,{
        method:'PUT',body:JSON.stringify(findingForm)
      })
      await loadDetail(detail.id);setMessage('Investigation finding saved.')
    }catch(e:any){setError(e.message||'Unable to save finding.')}
    finally{setBusy(false)}
  }
  async function saveSummary(){
    if(!detail)return
    setBusy(true);setError('')
    try{await api(`/fta/investigations/${detail.id}`,{method:'PATCH',body:JSON.stringify({summary,occurrence_cause_summary:occurrenceSummary,escape_cause_summary:escapeSummary})});await loadDetail(detail.id);setMessage('Investigation details saved.')}
    catch(e:any){setError(e.message||'Unable to save investigation.')}finally{setBusy(false)}
  }
  const tree:FtaNode|undefined=detail?.template_snapshot?.tree
  const counts=dashboard.counts||{}

  return <div className="page fta-page">
    <PageHeader title="Fault Tree Analysis" subtitle="Machining defect investigation, verified root causes and corrective-action linkage."/>
    {error&&<div className="error" role="alert">{error}</div>}
    {message&&<div className="success" role="status">{message}</div>}
    <div className="kpi-grid">
      <Kpi label="Total investigations" value={counts.total||0}/>
      <Kpi label="Open / in progress" value={counts.open||0}/>
      <Kpi label="Verified / actions pending" value={counts.verified_pending_actions||0}/>
      <Kpi label="Closed" value={counts.closed||0}/>
    </div>

    <section className="panel">
      <div className="panel-title"><div><h2>Recurring defect intelligence</h2><p>Defects and verified causes from completed investigation findings.</p></div></div>
      <div className="fta-bottom-grid">
        <div><h3>Top defect categories</h3>{(dashboard.top_defects||[]).length?(dashboard.top_defects||[]).map((x:any)=><div className="master-row" key={x.defect}><b>{x.defect}</b><span>{x.investigations} investigations</span></div>):<p className="muted">No investigation history yet.</p>}</div>
        <div><h3>Top verified root causes</h3>{(dashboard.top_verified_causes||[]).length?(dashboard.top_verified_causes||[]).map((x:any)=><div className="master-row" key={x.cause}><b>{x.cause}</b><span>{x.occurrences} confirmed</span></div>):<p className="muted">No verified root causes yet.</p>}</div>
      </div>
    </section>

    <section className="panel">
      <div className="panel-title"><div><h2>Start investigation</h2><p>Link an existing Quality Rejection record. Rejection quantities and PPM are not modified by FTA.</p></div></div>
      <div className="fta-create-grid">
        <label>Machining operation
          <select value={operationCode} onChange={e=>setOperationCode(e.target.value)}>
            <option value="">Select operation</option>{operations.map(o=><option key={o.code} value={o.code}>{o.name}</option>)}
          </select>
        </label>
        <label>Defect
          <select value={defectCode} onChange={e=>setDefectCode(e.target.value)}>
            <option value="">Select defect</option>{defects.map(d=><option key={d.code} value={d.code}>{d.category} – {d.name}</option>)}
          </select>
        </label>
        <label>Quality rejection
          <select value={rejectionId} onChange={e=>{const value=e.target.value;setRejectionId(value);const selected=rejections.find(r=>String(r.id)===value);setMachineId(selected?.machine_id?String(selected.machine_id):'')}}>
            <option value="">Select rejection record</option>{rejections.map(r=><option key={r.id} value={r.id}>#{r.id} · {String(r.rejection_date).slice(0,10)} · {r.part_code} · {r.phenomenon} · Qty {r.reject_qty}</option>)}
          </select>
        </label>
        <label>Machine (optional)
          <select value={machineId} onChange={e=>setMachineId(e.target.value)} disabled={!canWrite||!rejectionId}>
            <option value="">Use machine from rejection / no machine</option>{plantMachines.map(m=><option key={m.id} value={m.id}>{m.code} — {m.name}</option>)}
          </select>
        </label>
        <label>Matching published template
          <select value={selectedTemplate?String(selectedTemplate.id):''} disabled={!canWrite||!filteredTemplates.length} onChange={e=>setSelectedTemplateId(e.target.value)}>
            {filteredTemplates.length?filteredTemplates.map(t=><option key={t.id} value={t.id}>{t.name} · v{t.version}</option>):<option value="">No matching template</option>}
          </select>
        </label>
      </div>
      <label>Investigation objective / initial observation
        <textarea value={summary} onChange={e=>setSummary(e.target.value)} rows={2} placeholder="Describe the defect, location, inspection result or immediate concern."/>
      </label>
      <div className="button-row"><button onClick={createInvestigation} disabled={!canWrite||busy||!rejectionId||!operationCode||!defectCode||!filteredTemplates.length}>Create investigation</button><button className="secondary" onClick={load} disabled={busy}>Refresh</button></div>
      <p className="muted small">Select the appropriate published template. Its version and tree are snapshotted when the investigation is created.</p>
    </section>


    {canManageTemplates&&<section className="panel">
      <div className="panel-title"><div><h2>FTA Template Master</h2><p>Published templates are immutable. Create a revision, review its tree and publish it for new investigations.</p></div></div>
      <div className="fta-bottom-grid">
        <div><h3>Add machining operation</h3>
          <label>Operation code<input value={newOperationCode} onChange={e=>setNewOperationCode(e.target.value.toUpperCase())} placeholder="LASER_TURN"/></label>
          <label>Operation name<input value={newOperationName} onChange={e=>setNewOperationName(e.target.value)} placeholder="Laser turning"/></label>
          <button className="secondary" disabled={!newOperationCode.trim()||!newOperationName.trim()||busy} onClick={async()=>{try{setBusy(true);await api('/fta/operations',{method:'POST',body:JSON.stringify({code:newOperationCode,name:newOperationName})});setNewOperationCode('');setNewOperationName('');await load();setMessage('Machining operation added.')}catch(e:any){setError(e.message)}finally{setBusy(false)}}}>Add operation</button>
        </div>
        <div><h3>Add defect type</h3>
          <label>Defect code<input value={newDefectCode} onChange={e=>setNewDefectCode(e.target.value.toUpperCase())} placeholder="THREAD-PITCH"/></label>
          <label>Category<input value={newDefectCategory} onChange={e=>setNewDefectCategory(e.target.value)} /></label>
          <label>Defect name<input value={newDefectName} onChange={e=>setNewDefectName(e.target.value)} placeholder="Incorrect thread pitch"/></label>
          <button className="secondary" disabled={!newDefectCode.trim()||!newDefectName.trim()||busy} onClick={async()=>{try{setBusy(true);await api('/fta/defects',{method:'POST',body:JSON.stringify({code:newDefectCode,category:newDefectCategory,name:newDefectName})});setNewDefectCode('');setNewDefectName('');await load();setMessage('Defect type added.')}catch(e:any){setError(e.message)}finally{setBusy(false)}}}>Add defect</button>
        </div>
      </div>
      <div className="fta-create-grid">
        <label>New template code<input value={newTemplateCode} onChange={e=>setNewTemplateCode(e.target.value.toUpperCase())} placeholder="LASER_TURN-THREAD-PITCH"/></label>
        <label>New template name<input value={newTemplateName} onChange={e=>setNewTemplateName(e.target.value)} placeholder="Laser turning – incorrect thread pitch"/></label>
        <label>New template operation<select value={newTemplateOperation} onChange={e=>setNewTemplateOperation(e.target.value)}><option value="">Select operation</option>{operations.map(o=><option key={o.code} value={o.code}>{o.name}</option>)}</select></label>
        <label>New template defect<select value={newTemplateDefect} onChange={e=>setNewTemplateDefect(e.target.value)}><option value="">Select defect</option>{defects.map(d=><option key={d.code} value={d.code}>{d.category} – {d.name}</option>)}</select></label>
      </div>
      <button className="secondary" disabled={!newTemplateCode||!newTemplateName||!newTemplateOperation||!newTemplateDefect||!templateTreeText||busy} onClick={async()=>{try{const tree=JSON.parse(templateTreeText);setBusy(true);const created:any=await api('/fta/templates',{method:'POST',body:JSON.stringify({code:newTemplateCode,name:newTemplateName,operation_code:newTemplateOperation,defect_code:newTemplateDefect,tree})});setTemplateDraftId(created.id);setBaseTemplateId(String(created.id));await load();setMessage('New FTA template created as draft. Review and publish it when ready.')}catch(e:any){setError(e instanceof SyntaxError?'Fault tree JSON is invalid.':e.message)}finally{setBusy(false)}}}>Create new template draft</button>
      <div className="fta-create-grid">
        <label>Base template
          <select value={baseTemplateId} onChange={e=>{setBaseTemplateId(e.target.value);setTemplateDraftId(null)}}>
            <option value="">Select template to revise</option>
            {templates.map(t=><option key={t.id} value={t.id}>{t.code} · v{t.version} · {t.status}</option>)}
          </select>
        </label>
        <label>Template name<input value={templateName} onChange={e=>setTemplateName(e.target.value)} placeholder="Machining defect fault tree"/></label>
      </div>
      <label>Fault tree JSON
        <textarea rows={8} value={templateTreeText} onChange={e=>setTemplateTreeText(e.target.value)} placeholder='Load a template first. Edit node labels, types, gates and children using JSON.'/>
      </label>
      <div className="button-row">
        <button className="secondary" disabled={!baseTemplateId||busy} onClick={async()=>{try{setBusy(true);const t:any=await api('/fta/templates/'+baseTemplateId);setTemplateName(t.name);setTemplateTreeText(JSON.stringify(t.tree,null,2));setTemplateDraftId(t.status==='DRAFT'?t.id:null)}catch(e:any){setError(e.message)}finally{setBusy(false)}}}>Load selected tree</button>
        <button disabled={!baseTemplateId||!templateTreeText||busy} onClick={async()=>{try{const tree=JSON.parse(templateTreeText);setBusy(true);let result:any;if(templateDraftId){result=await api('/fta/templates/'+templateDraftId,{method:'PUT',body:JSON.stringify({name:templateName,tree})})}else{result=await api('/fta/templates/'+baseTemplateId+'/revisions',{method:'POST',body:JSON.stringify({name:templateName||undefined,tree})});setTemplateDraftId(result.id)}await load();setMessage('Draft template saved. Review and publish it when ready.')}catch(e:any){setError(e instanceof SyntaxError?'Fault tree JSON is invalid.':e.message)}finally{setBusy(false)}}}>Save draft revision</button>
        <button className="secondary" disabled={!templateDraftId||busy} onClick={async()=>{try{setBusy(true);await api('/fta/templates/'+templateDraftId+'/publish',{method:'POST'});setTemplateDraftId(null);await load();setMessage('Template revision published. New investigations will use the published version.')}catch(e:any){setError(e.message)}finally{setBusy(false)}}}>Publish draft</button>
      </div>
      <p className="muted small">Node types: TOP_EVENT, INTERMEDIATE_EVENT, BASIC_EVENT, EXTERNAL_EVENT, UNDEVELOPED_EVENT. Nodes with children require an AND or OR gate. Each node ID must be unique.</p>
    </section>}

    <section className="panel">
      <div className="panel-title"><div><h2>Investigation register</h2><p>Latest 500 investigations. Select a record to continue the analysis.</p></div><span className="muted">{investigations.length} records</span></div>
      <div className="table-wrap"><table><thead><tr><th>FTA No.</th><th>Date</th><th>Part</th><th>Defect / Template</th><th>Plant</th><th>Status</th><th></th></tr></thead>
        <tbody>{investigations.map(i=><tr key={i.id}><td>{i.investigation_no}</td><td>{String(i.created_at||'').slice(0,10)}</td><td>{i.part_code} – {i.part_name}</td><td>{i.defect_name}<div className="muted small">{i.template_name}</div></td><td>{i.plant||'—'}</td><td><span className="status-pill">{i.status.replaceAll('_',' ')}</span></td><td><button className="small secondary" onClick={()=>loadDetail(i.id)}>Open</button></td></tr>)}
        {!investigations.length&&<tr><td colSpan={7} className="muted">No FTA investigations created yet.</td></tr>}</tbody>
      </table></div>
    </section>

    {detail&&tree&&<section className="panel fta-workspace">
      <div className="panel-title"><div><h2>{detail.investigation_no} – {detail.template_snapshot?.template_name}</h2><p>Rejection #{detail.rejection_id} · {detail.plant||'Plant not specified'} · {detail.status.replaceAll('_',' ')}</p></div><button className="secondary small" onClick={()=>{setDetail(null);setSelectedId(null)}}>Close workspace</button></div>
      <div className="fta-workspace-grid">
        <div className="fta-tree-panel">
          <h3>Fault tree</h3>
          <p className="muted small">Select a cause node to record evidence and investigation status. Gate labels describe logical relationships; they do not prove causality.</p>
          <TreeNode node={tree} findings={detail.findings||[]} selected={selectedNode} onSelect={setSelectedNode}/>
        </div>
        <div className="fta-finding-panel">
          <h3>Investigation finding</h3>
          {currentFinding?<>
            <strong>{currentFinding.node_label}</strong>
            <label>Investigation status
              <select value={findingForm.investigation_status||'NOT_INVESTIGATED'} disabled={!canWrite||!['OPEN','IN_PROGRESS'].includes(detail.status)} onChange={e=>setFindingForm((v:any)=>({...v,investigation_status:e.target.value}))}>
                {['NOT_INVESTIGATED','UNDER_INVESTIGATION','SUSPECTED','CONFIRMED','RULED_OUT','UNABLE_TO_DETERMINE'].map(x=><option key={x} value={x}>{x.replaceAll('_',' ')}</option>)}
              </select>
            </label>
            <label>Observation / evidence reference<textarea rows={3} value={findingForm.observation||''} disabled={!canWrite||!['OPEN','IN_PROGRESS'].includes(detail.status)} onChange={e=>setFindingForm((v:any)=>({...v,observation:e.target.value}))}/></label>
            <div className="fta-create-grid">
              <label>Measured value<input value={findingForm.measured_value||''} disabled={!canWrite||!['OPEN','IN_PROGRESS'].includes(detail.status)} onChange={e=>setFindingForm((v:any)=>({...v,measured_value:e.target.value}))}/></label>
              <label>Expected value<input value={findingForm.expected_value||''} disabled={!canWrite||!['OPEN','IN_PROGRESS'].includes(detail.status)} onChange={e=>setFindingForm((v:any)=>({...v,expected_value:e.target.value}))}/></label>
            </div>
            <label>Verification method<textarea rows={2} value={findingForm.verification_method||''} disabled={!canWrite||!['OPEN','IN_PROGRESS'].includes(detail.status)} onChange={e=>setFindingForm((v:any)=>({...v,verification_method:e.target.value}))}/></label>
            <label>Verification result<textarea rows={2} value={findingForm.verification_result||''} disabled={!canWrite||!['OPEN','IN_PROGRESS'].includes(detail.status)} onChange={e=>setFindingForm((v:any)=>({...v,verification_result:e.target.value}))}/></label>
            <details className="fta-finding-history"><summary>Finding change history ({(detail.finding_history||[]).filter((h:any)=>h.finding_id===currentFinding.id).length})</summary>
              {(detail.finding_history||[]).filter((h:any)=>h.finding_id===currentFinding.id).map((h:any)=><div className="fta-history-row" key={h.id}><strong>{h.old?.investigation_status||'NEW'} → {h.new?.investigation_status}</strong><span>{String(h.created_at||'').replace('T',' ').slice(0,19)}</span><p>{h.new?.observation||'No observation recorded'}</p></div>)}
            </details>
            <label className="fta-check"><input type="checkbox" checked={!!findingForm.is_root_cause} disabled={!canWrite||!['OPEN','IN_PROGRESS'].includes(detail.status)} onChange={e=>setFindingForm((v:any)=>({...v,is_root_cause:e.target.checked}))}/> Confirmed root cause</label>
            <label className="fta-check"><input type="checkbox" checked={!!findingForm.is_occurrence_cause} disabled={!canWrite||!['OPEN','IN_PROGRESS'].includes(detail.status)} onChange={e=>setFindingForm((v:any)=>({...v,is_occurrence_cause:e.target.checked}))}/> Occurrence cause</label>
            <label className="fta-check"><input type="checkbox" checked={!!findingForm.is_escape_cause} disabled={!canWrite||!['OPEN','IN_PROGRESS'].includes(detail.status)} onChange={e=>setFindingForm((v:any)=>({...v,is_escape_cause:e.target.checked}))}/> Escape / detection cause</label>
            <button onClick={saveFinding} disabled={!canWrite||busy||!['OPEN','IN_PROGRESS'].includes(detail.status)}>Save finding</button>
            <div className="fta-evidence-box">
              <strong>Evidence attachments</strong>
              <label>Photo, PDF or inspection document<input type="file" accept=".jpg,.jpeg,.png,.webp,.pdf,.xlsx,.csv,.txt" onChange={e=>setEvidenceFile(e.target.files?.[0]||null)}/></label>
              <label>Caption<input value={evidenceCaption} onChange={e=>setEvidenceCaption(e.target.value)} placeholder="Measurement report, tool condition, setup photo…"/></label>
              <button className="secondary" disabled={!canWrite||!evidenceFile||busy||!['OPEN','IN_PROGRESS'].includes(detail.status)} onClick={async()=>{try{setBusy(true);const form=new FormData();form.append('file',evidenceFile as File);form.append('finding_id',String(currentFinding.id));form.append('caption',evidenceCaption);await api('/fta/investigations/'+detail.id+'/evidence',{method:'POST',body:form});setEvidenceFile(null);setEvidenceCaption('');await loadDetail(detail.id);setMessage('Evidence uploaded securely.')}catch(e:any){setError(e.message)}finally{setBusy(false)}}}>Upload evidence</button>
              {(detail.evidence||[]).filter((x:any)=>x.finding_id===currentFinding.id).map((x:any)=><div className="fta-evidence-item" key={x.id}><span>{x.file_name}{x.caption?' · '+x.caption:''}</span><button className="small secondary" onClick={()=>downloadApi('/fta/investigations/'+detail.id+'/evidence/'+x.id,x.file_name)}>Download</button></div>)}
            </div>
          </>:<p className="muted">Select a node in the fault tree.</p>}
        </div>
      </div>
      <div className="fta-review-controls">
        <label>Verification remarks<textarea rows={2} value={verificationRemarks} onChange={e=>setVerificationRemarks(e.target.value)} disabled={!canVerify||!['OPEN','IN_PROGRESS'].includes(detail.status)}/></label>
        <button className="secondary" disabled={!canVerify||busy||detail.status!=='IN_PROGRESS'||!hasRequiredAction} onClick={async()=>{try{setBusy(true);await api('/fta/investigations/'+detail.id+'/verify',{method:'POST',body:JSON.stringify({remarks:verificationRemarks})});await loadDetail(detail.id);await load();setMessage('Investigation verified. Complete linked actions before closure.')}catch(e:any){setError(e.message)}finally{setBusy(false)}}}>Verify investigation</button>
        <label>Closure remarks<textarea rows={2} value={closureRemarks} onChange={e=>setClosureRemarks(e.target.value)} disabled={!canVerify||detail.status!=='VERIFIED_PENDING_ACTIONS'}/></label>
        <button disabled={!canVerify||busy||detail.status!=='VERIFIED_PENDING_ACTIONS'} onClick={async()=>{try{setBusy(true);await api('/fta/investigations/'+detail.id+'/close',{method:'POST',body:JSON.stringify({remarks:closureRemarks})});await loadDetail(detail.id);await load();setMessage('Investigation closed.')}catch(e:any){setError(e.message)}finally{setBusy(false)}}}>Close investigation</button>
      </div>
      <section className="fta-history">
        <h3>Investigation audit history</h3>
        {(detail.status_history||[]).map((h:any)=><div className="fta-history-row" key={h.id}><strong>{h.old_status||'NEW'} → {h.new_status}</strong><span>{String(h.created_at||'').replace('T',' ').slice(0,19)}</span><p>{h.remarks||'—'}</p></div>)}
      </section>
      <div className="fta-bottom-grid">
        <div><h3>Investigation summary</h3>
          <label>Initial defect / investigation summary<textarea rows={2} value={summary} onChange={e=>setSummary(e.target.value)} disabled={!canWrite||!['OPEN','IN_PROGRESS'].includes(detail.status)}/></label>
          <label>Occurrence cause summary<textarea rows={2} value={occurrenceSummary} onChange={e=>setOccurrenceSummary(e.target.value)} disabled={!canWrite||!['OPEN','IN_PROGRESS'].includes(detail.status)}/></label>
          <label>Escape / detection cause summary<textarea rows={2} value={escapeSummary} onChange={e=>setEscapeSummary(e.target.value)} disabled={!canWrite||!['OPEN','IN_PROGRESS'].includes(detail.status)}/></label>
          <button className="secondary" onClick={saveSummary} disabled={!canWrite||busy||!['OPEN','IN_PROGRESS'].includes(detail.status)}>Save investigation summaries</button></div>
        <div><h3>Link existing corrective action</h3>
          <label>Create new corrective / preventive action
            <textarea rows={2} value={newActionDescription} onChange={e=>setNewActionDescription(e.target.value)} disabled={!canWrite||!['OPEN','IN_PROGRESS'].includes(detail.status)}/>
          </label>
          <button className="secondary" disabled={!canWrite||!newActionDescription.trim()||busy||!['OPEN','IN_PROGRESS'].includes(detail.status)} onClick={async()=>{try{setBusy(true);const rejection=detail.template_snapshot?.rejection||{};const created:any=await api('/actions',{method:'POST',body:JSON.stringify({reference_date:String(rejection.rejection_date).slice(0,10),problem_category:'FTA',problem_description:'Fault Tree Analysis '+detail.investigation_no+': '+(detail.summary||'Machining defect root cause investigation'),action_description:newActionDescription,owner_id:me.id,contexts:[{context_date:String(rejection.rejection_date).slice(0,10),product_id:rejection.product_id||null,machine_id:detail.machine_id||null}]})});await api('/fta/investigations/'+detail.id+'/actions',{method:'POST',body:JSON.stringify({action_id:created.id,finding_id:currentFinding?.id||null,relationship_type:'CORRECTIVE'})});await loadDetail(detail.id);await load();setMessage('New action '+created.action_no+' created with its standard Why-Why plan and linked to FTA.')}catch(e:any){setError(e.message)}finally{setBusy(false)}}}>Create action with Why-Why plan</button>
          <div className="fta-action-link">
            <select value={actionId} disabled={!canWrite||!['OPEN','IN_PROGRESS'].includes(detail.status)} onChange={e=>setActionId(e.target.value)}><option value="">Select existing action</option>{availableActions.map(a=><option key={a.id} value={a.id}>{a.action_no} · {a.status} · {a.action_description}</option>)}</select>
            <select value={actionRelationship} disabled={!canWrite||!['OPEN','IN_PROGRESS'].includes(detail.status)} onChange={e=>setActionRelationship(e.target.value)}><option value="CORRECTIVE">Corrective</option><option value="PREVENTIVE">Preventive</option><option value="CONTAINMENT">Containment</option></select>
            <button className="secondary" disabled={!canWrite||!actionId||busy||!['OPEN','IN_PROGRESS'].includes(detail.status)} onClick={async()=>{try{setBusy(true);await api(`/fta/investigations/${detail.id}/actions`,{method:'POST',body:JSON.stringify({action_id:Number(actionId),finding_id:currentFinding?.id||null,relationship_type:actionRelationship})});await loadDetail(detail.id);setActionId('');setMessage('Existing action linked.')}catch(e:any){setError(e.message)}finally{setBusy(false)}}}>Link action</button>
          </div>
          {(detail.actions||[]).length?detail.actions.map((a:any)=><p key={a.link_id}>{a.action_no} · {a.status} · {a.action_description}</p>):<p className="muted">No existing actions linked yet.</p>}</div>
      </div>
    </section>}
  </div>
}
