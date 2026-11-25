import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api, downloadApi } from '../api'
import { PageHeader, Kpi, Status } from '../components/UI'

type FtaNode = { id:string, label:string, type:string, gate?:string|null, logic_state?:string, requirement?:string|null, children?:FtaNode[] }
function nodeConnectorColor(type:string){return ({TOP_EVENT:'#7c3aed',INTERMEDIATE_EVENT:'#2563eb',BASIC_EVENT:'#059669',EXTERNAL_EVENT:'#d97706',UNDEVELOPED_EVENT:'#64748b'} as Record<string,string>)[type]||'#94a3b8'}
function findTemplateNode(node:FtaNode|undefined,id:string):FtaNode|undefined{if(!node)return undefined;if(node.id===id)return node;for(const child of node.children||[]){const found=findTemplateNode(child,id);if(found)return found}return undefined}
function newTemplateNode(type='BASIC_EVENT'):FtaNode{
  return {id:`node_${Date.now().toString(36)}_${Math.random().toString(36).slice(2,7)}`,label:'New cause',type,gate:type==='INTERMEDIATE_EVENT'?'OR':undefined,children:type==='INTERMEDIATE_EVENT'?[newTemplateNode('BASIC_EVENT')]:undefined}
}

function countTemplateNodes(node:FtaNode):number{return 1+(node.children||[]).reduce((sum,child)=>sum+countTemplateNodes(child),0)}

function TemplateNodeEditor({node,onChange,onRemove,onRemoveDisabled=false,depth=0,root=false}:{node:FtaNode,onChange:(node:FtaNode)=>void,onRemove?:()=>void,onRemoveDisabled?:boolean,depth?:number,root?:boolean}){
  const isBranch=node.type==='TOP_EVENT'||node.type==='INTERMEDIATE_EVENT'
  const children=node.children||[]
  function changeType(type:string){
    const branch=type==='TOP_EVENT'||type==='INTERMEDIATE_EVENT'
    onChange({...node,type,gate:branch?(node.gate||'OR'):undefined,children:branch?(children.length?children:[newTemplateNode('BASIC_EVENT')]):undefined})
  }
  function updateChild(index:number,child:FtaNode){
    onChange({...node,children:children.map((item,i)=>i===index?child:item)})
  }
  function addChild(){
    if(children.length>=20||depth>=7)return
    onChange({...node,gate:node.gate||'OR',children:[...children,newTemplateNode('BASIC_EVENT')]})
  }
  function removeChild(index:number){
    onChange({...node,children:children.filter((_,i)=>i!==index)})
  }
  const eventLabel=node.type.replaceAll('_',' ')
  return <div className="fta-template-node-editor" style={{marginLeft:depth?18:0,borderLeft:depth?`3px solid ${nodeConnectorColor(node.type)}`:'none',paddingLeft:depth?14:0,marginTop:12}}>
    <div style={{border:'1px solid var(--border, #d8dee8)',borderRadius:10,overflow:'hidden',background:'var(--panel, #fff)'}}>
      <div style={{display:'flex',alignItems:'center',justifyContent:'space-between',gap:10,flexWrap:'wrap',padding:'9px 12px',background:'var(--panel-soft, #f5f8fc)',borderBottom:'1px solid var(--border, #d8dee8)'}}>
        <span style={{display:'flex',alignItems:'center',gap:8}}><i style={{width:9,height:9,borderRadius:3,background:nodeConnectorColor(node.type)}}/><strong style={{fontSize:12,letterSpacing:'.04em'}}>{root?'ROOT EVENT':eventLabel}</strong>{isBranch&&<span className="status-pill">{node.gate||'OR'} GATE</span>}</span>
        {!root&&<button type="button" className="secondary small" onClick={onRemove} disabled={onRemoveDisabled}>Remove event</button>}
      </div>
      <div style={{padding:13,display:'grid',gridTemplateColumns:'minmax(0, 2fr) minmax(0, 3fr)',gap:14,alignItems:'stretch'}}>
        <div style={{minWidth:0,display:'flex',flexDirection:'column',justifyContent:'flex-start'}}>
          <label>Event / cause description<input value={node.label} maxLength={240} onChange={e=>onChange({...node,label:e.target.value})} placeholder="Describe the event clearly"/></label>
          <div className="muted small" style={{marginTop:7}}>Keep the event name short and specific.</div>
        </div>
        <div style={{minWidth:0,display:'grid',gridTemplateColumns:'minmax(150px, 0.8fr) minmax(0, 1.6fr)',gap:12,alignItems:'start'}}>
          <div style={{display:'grid',gap:10,alignContent:'start'}}>
            <label>Event type<select value={node.type} disabled={root} onChange={e=>changeType(e.target.value)}>
              {root&&<option value="TOP_EVENT">TOP EVENT</option>}
              <option value="INTERMEDIATE_EVENT">INTERMEDIATE EVENT</option>
              <option value="BASIC_EVENT">BASIC EVENT</option>
              <option value="EXTERNAL_EVENT">EXTERNAL EVENT</option>
              <option value="UNDEVELOPED_EVENT">UNDEVELOPED EVENT</option>
            </select></label>
            {isBranch&&<label>Logic relationship<select value={node.gate||'OR'} onChange={e=>onChange({...node,gate:e.target.value})}><option value="OR">OR — any child can cause it</option><option value="AND">AND — all children required</option></select></label>}
          </div>
          <label><span style={{display:'flex',alignItems:'baseline',gap:6,flexWrap:'nowrap'}}>Requirement / Specification <span className="muted small" style={{whiteSpace:'nowrap'}}>(Optional)</span></span><textarea rows={3} maxLength={1200} value={node.requirement||''} onChange={e=>onChange({...node,requirement:e.target.value})} placeholder="Expected condition, drawing tolerance, process parameter or standard…"/></label>
        </div>
      </div>
    </div>
    {isBranch&&<div className="fta-template-children" style={{marginLeft:12,paddingLeft:12,borderLeft:'1px dashed var(--border, #cbd5e1)',marginTop:10}}>
      <div className="muted small" style={{fontWeight:700,marginBottom:5}}>CHILD EVENTS · {children.length}</div>
      {children.map((child,index)=><TemplateNodeEditor key={child.id} node={child} depth={depth+1} onChange={updated=>updateChild(index,updated)} onRemove={()=>removeChild(index)} onRemoveDisabled={isBranch&&children.length<=1}/>)}
      <button type="button" className="secondary small" disabled={children.length>=20||depth>=7||countTemplateNodes(node)>=300} onClick={addChild}>＋ Add child event</button>
    </div>}
  </div>
}

type Finding = {
  id:number, node_id:string, node_label:string, node_type:string, investigation_status:string,
  priority?:string, observation?:string|null, measured_value?:string|null, expected_value?:string|null,
  verification_method?:string|null, verification_result?:string|null,
  is_root_cause:boolean, is_occurrence_cause:boolean, is_escape_cause:boolean, updated_at?:string
}

function historyRemark(value:any){
  if(!value)return '—'
  try{
    const parsed=JSON.parse(value)
    if(parsed?.event==='FTA_TEMPLATE_VERSION_UPGRADED'){
      return `Template upgraded V${parsed.old_template_version} → V${parsed.new_template_version}. Reason: ${parsed.reason||'Not recorded'}`
    }
  }catch{}
  return value
}

function TreeNode({node,findings,selected,onSelect,depth=0}:{node:FtaNode,findings:Finding[],selected:string,onSelect:(id:string)=>void,depth?:number}){
  const [expanded,setExpanded]=useState(depth<2)
  const finding=findings.find(x=>x.node_id===node.id)
  const status=finding?.investigation_status||'NOT_INVESTIGATED'
  const tone=status==='CONFIRMED'?'success':status==='SUSPECTED'?'warning':status==='RULED_OUT'||status==='NOT_APPLICABLE'?'muted':''
  const statusColor=status==='CONFIRMED'?'#16a34a':status==='SUSPECTED'?'#d97706':status==='RULED_OUT'||status==='NOT_APPLICABLE'?'#64748b':'#94a3b8'
  return <div className="fta-tree-node" style={{marginLeft:depth?18:0,borderLeft:`3px solid ${statusColor}`,paddingLeft:8}}>
    <div style={{display:'flex',alignItems:'stretch',gap:6}}>
      {!!node.children?.length&&<button type="button" className="secondary small" aria-label={expanded?'Collapse cause group':'Expand cause group'} onClick={()=>setExpanded(v=>!v)}>{expanded?'−':'+'}</button>}
      <button type="button" className={`fta-node-button ${selected===node.id?'selected':''}`} style={{flex:1,minWidth:0}} onClick={()=>onSelect(node.id)}>
        <span className="fta-node-gate">{node.gate||node.type.replaceAll('_',' ')}</span>
        <strong>{node.label}</strong>
        <span className={`fta-node-status ${tone}`}>{status.replaceAll('_',' ')}</span><span className="fta-node-logic">{node.logic_state||'UNKNOWN'}</span>
      </button>
    </div>
    {!!node.children?.length&&expanded&&<div className="fta-tree-children">
      {node.children.map(child=><TreeNode key={child.id} node={child} findings={findings} selected={selected} onSelect={onSelect} depth={depth+1}/>)}
    </div>}
  </div>
}

export default function FTA({me}:{me:any}){
  const [operations,setOperations]=useState<any[]>([])
  const [defects,setDefects]=useState<any[]>([])
  const [templates,setTemplates]=useState<any[]>([])
  const [rejections,setRejections]=useState<any[]>([])
  const [rejectionSearch,setRejectionSearch]=useState('')
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
  const [recurrenceCandidates,setRecurrenceCandidates]=useState<any[]>([])
  const [recurrenceSuggestionsLoading,setRecurrenceSuggestionsLoading]=useState(false)
  const [defectHistory,setDefectHistory]=useState<any>(null)
  const [defectHistoryLoading,setDefectHistoryLoading]=useState(false)
  const [recurrenceRejectionId,setRecurrenceRejectionId]=useState('')
  const [recurrenceReason,setRecurrenceReason]=useState('')
  const [recurrenceContainment,setRecurrenceContainment]=useState('')
  const [recurrenceEvidence,setRecurrenceEvidence]=useState('')
  const [relatedTemplateId,setRelatedTemplateId]=useState<Record<number,string>>({})
  const [upgradeTemplateId,setUpgradeTemplateId]=useState('')
  const [actionId,setActionId]=useState('')
  const [actionRelationship,setActionRelationship]=useState('CORRECTIVE')
  const [newActionDescription,setNewActionDescription]=useState('Implement corrective action for confirmed FTA root cause')
  const [evidenceFile,setEvidenceFile]=useState<File|null>(null)
  const [evidenceCaption,setEvidenceCaption]=useState('')
  const [baseTemplateId,setBaseTemplateId]=useState('')
  const [templateName,setTemplateName]=useState('')
  const [templateTree,setTemplateTree]=useState<FtaNode>(()=>({id:'top_event',label:'Top event',type:'TOP_EVENT',gate:'OR',children:[{id:'cause_1',label:'Main cause',type:'INTERMEDIATE_EVENT',gate:'OR',children:[{id:'cause_1_1',label:'Basic cause',type:'BASIC_EVENT'}]}]}))
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

  const filteredTemplates=useMemo(()=>operationCode&&defectCode?templates.filter(t=>t.status==='PUBLISHED'&&t.operation_code===operationCode&&t.defect_code===defectCode):[],[templates,operationCode,defectCode])
  const selectedTemplate=filteredTemplates.find(t=>String(t.id)===selectedTemplateId)||filteredTemplates[0]
  const rejectionOptionLabel=(r:any)=>`#${r.id} · ${String(r.rejection_date||'').slice(0,10)} · ${r.part_code||''} · ${r.part_name||''} · ${r.phenomenon||r.defect_name||''} · ${r.machine_code||''} · Qty ${r.reject_qty??''}`
  const normalizedRejectionSearch=rejectionSearch.trim().toLowerCase()
  const filteredRejections=useMemo(()=>rejections.filter(r=>[r.id,r.rejection_no,r.rejection_date,r.part_code,r.part_name,r.phenomenon,r.defect_name,r.machine_code].some(v=>String(v??'').toLowerCase().includes(normalizedRejectionSearch))),[rejections,normalizedRejectionSearch])
  const selectedRejection=rejections.find(r=>String(r.id)===rejectionId)
  const plantMachines=machines.filter(m=>m.active!==false&&(!selectedRejection?.plant||m.plant===selectedRejection.plant))
  const currentFinding:Finding|undefined=detail?.findings?.find((f:Finding)=>f.node_id===selectedNode)
  const currentNodeTemplate=findTemplateNode(detail?.template_snapshot?.tree,selectedNode)
  const hasRequiredAction=(detail?.actions||[]).some((a:any)=>['CORRECTIVE','PREVENTIVE'].includes(a.relationship_type))

  async function load(){
    setBusy(true);setError('')
    try{
      const [o,d,t,r,i,stats,m]=await Promise.all([
        api('/fta/operations'),api('/fta/defects'),api('/fta/templates'+(canManageTemplates?'?include_drafts=true':'')),api('/fta/rejections?limit=200'),
        api('/fta/investigations'),api('/fta/dashboard'),api('/masters/machines').catch(()=>[])
      ])
      setOperations(o as any[]);setDefects(d as any[]);setTemplates(t as any[]);setRejections(r as any[]);setMachines(m as any[])
      setInvestigations(i as any[]);setDashboard(stats)
      const actionRows:any[]=await api('/actions');setAvailableActions(actionRows.filter(a=>a.status!=='CLOSED'&&(me?.role!=='PRODUCTION'||a.owner_id===me?.id)))
    }catch(e:any){setError(e.message||'Unable to load FTA workspace.')}
    finally{setBusy(false)}
  }
  async function loadDetail(id:number,preserveNode=false){
    setError('')
    try{
      const result:any=await api(`/fta/investigations/${id}`)
      if(!Array.isArray(result.recurrences))result.recurrences=await api(`/fta/investigations/${id}/recurrences`).catch(()=>[])
      setRecurrenceSuggestionsLoading(true)
      result.recurrence_suggestions=await api(`/fta/investigations/${id}/recurrence-suggestions`).catch(()=>({suggestions:[]}))
      setRecurrenceSuggestionsLoading(false)
      setDetail(result);setSelectedId(id);setSelectedNode(preserveNode&&selectedNode&&result.findings?.some((f:Finding)=>f.node_id===selectedNode)?selectedNode:(result.template_snapshot?.tree?.id||''))
      setSummary(result.summary||'');setOccurrenceSummary(result.occurrence_cause_summary||'');setEscapeSummary(result.escape_cause_summary||'')
    }catch(e:any){setError(e.message||'Unable to load investigation.')}
  }
  useEffect(()=>{load()},[me?.role])
  const [searchParams,setSearchParams]=useSearchParams()
  const view=searchParams.get('view')||'dashboard'
  const views=[{key:'dashboard',label:'Dashboard'},{key:'start',label:'Start Investigation'},{key:'register',label:'Investigation Register'},{key:'templates',label:'Template Master'}]
  useEffect(()=>{
    let active=true
    if(!defectCode){
      setDefectHistory(null)
      setDefectHistoryLoading(false)
      return ()=>{active=false}
    }
    setDefectHistoryLoading(true)
    const suffix=rejectionId?('?rejection_id='+encodeURIComponent(rejectionId)):''
    api('/fta/defect-history/'+encodeURIComponent(defectCode)+suffix)
      .then((result:any)=>{if(active)setDefectHistory(result)})
      .catch(()=>{if(active)setDefectHistory(null)})
      .finally(()=>{if(active)setDefectHistoryLoading(false)})
    return ()=>{active=false}
  },[defectCode,rejectionId])

  useEffect(()=>{
    const id=Number(searchParams.get('investigation_id')||0)
    const recurrenceId=searchParams.get('recurrence_rejection_id')||''
    if(recurrenceId){setRecurrenceRejectionId(recurrenceId);setRecurrenceReason('Possible recurrence identified from the rejection register. Confirm the relationship and add investigation details.')}
    if(id>0)loadDetail(id)
  },[searchParams])
  useEffect(()=>{
    if(!currentFinding){setFindingForm({});return}
    setFindingForm({
      investigation_status:currentFinding.investigation_status||'NOT_INVESTIGATED',priority:currentFinding.priority||'MEDIUM',
      observation:currentFinding.observation||'',measured_value:currentFinding.measured_value||'',
      expected_value:currentFinding.expected_value||findTemplateNode(detail?.template_snapshot?.tree,selectedNode)?.requirement||'',verification_method:currentFinding.verification_method||'',
      verification_result:currentFinding.verification_result||'',is_root_cause:!!currentFinding.is_root_cause,
      is_occurrence_cause:!!currentFinding.is_occurrence_cause,is_escape_cause:!!currentFinding.is_escape_cause
    })
  },[selectedNode,detail?.id,currentFinding?.updated_at])

  async function linkDetectedRecurrence(suggestion:any){
    if(!detail)return
    const detectedReason=`Automatically detected: Quality defect "${detail.recurrence_suggestions?.phenomenon_name||'selected defect'}" was recorded again on ${String(suggestion.rejection_date||'').slice(0,10)} for part ${suggestion.part_code}. Quality review is required to confirm whether it is related to ${detail.investigation_no}.`
    setBusy(true);setError('');setMessage('')
    try{
      await api('/fta/investigations/'+detail.id+'/recurrences',{method:'POST',body:JSON.stringify({
        rejection_id:Number(suggestion.rejection_id),
        recurrence_reason:detectedReason,
        containment_action:null,
        new_evidence:suggestion.remark||null
      })})
      await loadDetail(detail.id,true)
      await load()
      setMessage(`Quality Rejection #${suggestion.rejection_id} was linked as a detected recurrence and sent for Quality review.`)
    }catch(e:any){setError(e.message||'Unable to link detected recurrence.')}
    finally{setBusy(false)}
  }

  async function linkSelectedRejectionToPreviousFta(candidate:any){
    if(!selectedRejection||!rejectionId||!candidate?.same_part)return
    const detectedReason=`Automatically detected recurrence: Quality defect "${defectHistory?.phenomenon_name||selectedRejection.phenomenon||defectCode}" was rejected again on ${String(selectedRejection.rejection_date||'').slice(0,10)} for part ${selectedRejection.part_code}. This is linked to the latest prior FTA ${candidate.investigation_no} dated ${String(candidate.fta_date||'').slice(0,10)} and is awaiting Quality review.`
    setBusy(true);setError('');setMessage('')
    try{
      await api('/fta/investigations/'+candidate.investigation_id+'/recurrences',{method:'POST',body:JSON.stringify({
        rejection_id:Number(rejectionId),
        recurrence_reason:detectedReason,
        containment_action:null,
        new_evidence:selectedRejection.remark||null
      })})
      setRejectionId('');setRejectionSearch('');setMachineId('')
      setRecurrenceCandidates([])
      await load()
      setSearchParams({view:'register',investigation_id:String(candidate.investigation_id)})
      setMessage(`Quality Rejection #${selectedRejection.id} was automatically linked to ${candidate.investigation_no} as a recurrence pending Quality review.`)
    }catch(e:any){setError(e.message||'Unable to link the detected recurrence.')}
    finally{setBusy(false)}
  }

  async function createInvestigation(){
    if(!rejectionId||!operationCode||!defectCode||!filteredTemplates.length){setError('Select a machining operation, defect, rejection and matching published template.');return}
    setBusy(true);setError('');setMessage('')
    try{
      const result:any=await api('/fta/investigations',{method:'POST',body:JSON.stringify({
        rejection_id:Number(rejectionId),template_id:Number(selectedTemplate.id),machine_id:machineId?Number(machineId):null,summary:summary||null
      })})
      await load();await loadDetail(result.id);setSearchParams({view:'register',investigation_id:String(result.id)});setMessage(`Investigation ${result.investigation_no} created. You can now continue the FTA analysis.`)
    }catch(e:any){setError(e.message||'Unable to create investigation.')}
    finally{setBusy(false)}
  }
  async function upgradeTemplateVersion(targetId?:string){
    const selectedTargetId=targetId||upgradeTemplateId
    if(!detail||!selectedTargetId)return
    const target=templates.find((t:any)=>String(t.id)===selectedTargetId)
    if(!target)return
    const reason=window.prompt(`Upgrade ${detail.template_snapshot?.template_code||''} from V${detail.template_version||detail.template_snapshot?.template_version||'?'} to V${target.version}. Enter the reason (required):`)
    if(!reason||reason.trim().length<5)return
    setBusy(true);setError('');setMessage('')
    try{
      await api(`/fta/investigations/${detail.id}/template-version`,{
        method:'POST',body:JSON.stringify({template_id:Number(selectedTargetId),reason:reason.trim()})
      })
      setUpgradeTemplateId('')
      await loadDetail(detail.id,true)
      await load()
      setMessage(`FTA template upgraded to version ${target.version}. Existing findings and the previous template snapshot are retained in the audit history.`)
    }catch(e:any){setError(e.message||'Unable to upgrade FTA template version.')}
    finally{setBusy(false)}
  }
  async function saveFinding(){
    if(!detail||!selectedNode)return
    setBusy(true);setError('');setMessage('')
    try{
      await api(`/fta/investigations/${detail.id}/findings/${encodeURIComponent(selectedNode)}`,{
        method:'PUT',body:JSON.stringify(findingForm)
      })
      await loadDetail(detail.id,true);setMessage('Investigation finding saved.')
    }catch(e:any){setError(e.message||'Unable to save finding.')}
    finally{setBusy(false)}
  }
  async function saveSummary(){
    if(!detail)return
    setBusy(true);setError('')
    try{await api(`/fta/investigations/${detail.id}`,{method:'PATCH',body:JSON.stringify({summary,occurrence_cause_summary:occurrenceSummary,escape_cause_summary:escapeSummary})});await loadDetail(detail.id,true);setMessage('Investigation details saved.')}
    catch(e:any){setError(e.message||'Unable to save investigation.')}finally{setBusy(false)}
  }
  const tree:FtaNode|undefined=detail?.template_snapshot?.tree
  const counts=dashboard.counts||{}
  const recurrenceCounts=dashboard.recurrence_counts||{}
  const findings:any[]=detail?.findings||[]
  const linkedActions:any[]=detail?.actions||[]
  const requiredActions=linkedActions.filter((a:any)=>['CORRECTIVE','PREVENTIVE'].includes(a.relationship_type))
  const confirmedRootCause=findings.some((f:any)=>f.investigation_status==='CONFIRMED'&&f.is_root_cause)||(detail?.discovered_causes||[]).some((cause:any)=>cause.status==='CONFIRMED')
  const treeNodes=(node:any):any[]=>node?[node,...(node.children||[]).flatMap((child:any)=>treeNodes(child))]:[]
  const allTreeNodes=treeNodes(tree)
  const investigationLeaves=allTreeNodes.filter((node:any)=>!node.children?.length&&['BASIC_EVENT','EXTERNAL_EVENT','UNDEVELOPED_EVENT'].includes(node.type))
  const completedTreeNodes=investigationLeaves.filter((node:any)=>findings.some((f:any)=>f.node_id===node.id&&['CONFIRMED','RULED_OUT','UNABLE_TO_DETERMINE','NOT_APPLICABLE'].includes(f.investigation_status))).length
  const treeStarted=findings.length>0
  const treeComplete=investigationLeaves.length>0&&completedTreeNodes===investigationLeaves.length
  const actionsComplete=requiredActions.length>0&&requiredActions.every((a:any)=>a.status==='CLOSED')
  const unresolvedDiscovered=(detail?.discovered_causes||[]).some((x:any)=>['PROPOSED','ACCEPTED'].includes(x.status))
  const closed=detail?.status==='CLOSED'
  const flowSteps=[
    {title:'Investigation creation',description:'Quality Rejection linked and investigation details created.',done:!!detail?.source_rejection,started:!!detail?.id},
    {title:'Fault Tree Analysis (optional review)',description:`${completedTreeNodes} of ${investigationLeaves.length} basic causes reviewed. Remaining nodes do not block verification.`,done:treeComplete,started:treeStarted},
    {title:'Root cause confirmation',description:'At least one root cause is confirmed in the findings.',done:confirmedRootCause,started:findings.some((f:any)=>f.investigation_status==='CONFIRMED')},
    {title:'Corrective / preventive actions',description:requiredActions.length?`${requiredActions.length} corrective / preventive action(s) linked.`:'No corrective or preventive action linked yet.',done:requiredActions.length>0,started:requiredActions.length>0},
    {title:'Action implementation & review',description:requiredActions.length?`${requiredActions.filter((a:any)=>a.status==='CLOSED').length} of ${requiredActions.length} linked actions closed${unresolvedDiscovered?' · discovered causes still need review':''}.`:'Waiting for linked actions.',done:actionsComplete&&!unresolvedDiscovered,started:requiredActions.length>0||!!(detail?.discovered_causes||[]).length},
    {title:'Investigation closure',description:closed?'Investigation closed and recorded in audit history.':detail?.status==='VERIFIED_PENDING_ACTIONS'?'Verified; awaiting action completion and final closure.':'Final closure is pending.',done:closed,started:detail?.status==='VERIFIED_PENDING_ACTIONS'}
  ]
  let flowHasPending=false
  const flowRows=flowSteps.map((step:any)=>{
    const state=step.done?'completed':!flowHasPending&&step.started?'in-progress':!flowHasPending&&!step.started?'pending':(flowHasPending?'pending':'in-progress')
    if(!step.done)flowHasPending=true
    return {...step,state}
  })

  return <div className="page fta-page">
    <PageHeader title="Fault Tree Analysis" subtitle="Machining defect investigation, verified root causes and corrective-action linkage."/>
    <nav className="fta-view-nav" aria-label="FTA workspace">{views.filter(v=>v.key!=='templates'||canManageTemplates).map(v=><a key={v.key} href={v.key==='dashboard'?'/fta':`/fta?view=${v.key}`} aria-current={view===v.key?'page':undefined} className={view===v.key?'active':''}>{v.label}</a>)}</nav>
    {error&&<div className="error" role="alert">{error}</div>}
    {message&&<div className="success" role="status">{message}</div>}
    {view==='dashboard'&&<>
    <div className="kpi-grid">
      <Kpi label="Total investigations" value={counts.total||0}/>
      <Kpi label="Open / in progress" value={counts.open||0}/>
      <Kpi label="Verified / actions pending" value={counts.verified_pending_actions||0}/>
      <Kpi label="Closed" value={counts.closed||0}/>
    </div>

    <div className="kpi-grid">
      <Kpi label="Linked recurrence events" value={recurrenceCounts.total||0}/>
      <Kpi label="Awaiting Quality review" value={recurrenceCounts.pending_review||0}/>
      <Kpi label="Same root cause" value={recurrenceCounts.same_root_cause||0}/>
      <Kpi label="Different root cause" value={recurrenceCounts.different_root_cause||0}/>
      <Kpi label="Unrelated occurrences" value={recurrenceCounts.unrelated||0}/>
    </div>

    <section className="panel">
      <div className="panel-title"><div><h2>Recurring defect intelligence</h2><p>Defects and verified causes from completed investigation findings.</p></div></div>
      <div className="fta-bottom-grid">
        <div><h3>Top defect categories</h3>{(dashboard.top_defects||[]).length?(dashboard.top_defects||[]).map((x:any)=><div className="master-row" key={x.defect}><b>{x.defect}</b><span>{x.investigations} investigations</span></div>):<p className="muted">No investigation history yet.</p>}</div>
        <div><h3>Top verified root causes</h3>{(dashboard.top_verified_causes||[]).length?(dashboard.top_verified_causes||[]).map((x:any)=><div className="master-row" key={x.cause}><b>{x.cause}</b><span>{x.occurrences} confirmed</span></div>):<p className="muted">No verified root causes yet.</p>}</div>
      </div>
    </section>
    </>}

    {view==='start'&&<section className="panel">
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
        <label>Search and select Quality rejection
          <input type="search" list="fta-rejection-options" value={rejectionSearch} onChange={e=>{const value=e.target.value;setRejectionSearch(value);const selected=rejections.find(r=>rejectionOptionLabel(r)===value);if(selected){setRejectionId(String(selected.id));setMachineId(selected.machine_id?String(selected.machine_id):'');const matchingDefect=defects.find(d=>Number(d.phenomenon_id)===Number(selected.phenomenon_id));setDefectCode(matchingDefect?.code||'');setRecurrenceCandidates([]);api('/fta/recurrence-candidates/'+selected.id).then((rows:any)=>setRecurrenceCandidates(rows)).catch(()=>setRecurrenceCandidates([]))}else{setRejectionId('');setMachineId('');setDefectCode('');setRecurrenceCandidates([])}}} placeholder="Type rejection ID, part, date, defect or machine..." aria-label="Search and select Quality rejection"/>
          <datalist id="fta-rejection-options">{filteredRejections.map(r=><option key={r.id} value={rejectionOptionLabel(r)}/>)}</datalist>
          {rejectionId&&selectedRejection&&<small className="muted">Selected rejection: #{selectedRejection.id} · {selectedRejection.part_code} · {selectedRejection.phenomenon||selectedRejection.defect_name||'—'} <button type="button" className="secondary small" onClick={()=>{setRejectionId('');setRejectionSearch('');setMachineId('')}}>Change</button></small>}
          {recurrenceCandidates.length>0&&<div className="fta-recurrence-candidates"><strong>Possible recurrence matches</strong><p className="muted small">Same part and shared phenomenon found in earlier FTA investigations. Open the original investigation to register this rejection as a recurrence instead of creating another FTA.</p>{recurrenceCandidates.map((candidate:any)=><div className="master-row" key={candidate.investigation_id}><span><b>{candidate.investigation_no}</b> · {candidate.status} · {candidate.original_rejection_date} · Previous actions: {candidate.previous_action_status||'None'}</span><button type="button" className="small secondary" onClick={()=>setSearchParams({view:'register',investigation_id:String(candidate.investigation_id),recurrence_rejection_id:String(rejectionId)})}>Open original FTA</button></div>)}</div>}
          {!filteredRejections.length&&normalizedRejectionSearch&&<small className="muted">No rejection records match this search.</small>}
        </label>
        <label>Machine (optional)
          <select value={machineId} onChange={e=>setMachineId(e.target.value)} disabled={!canWrite||!rejectionId}>
            <option value="">Use machine from rejection / no machine</option>{plantMachines.map(m=><option key={m.id} value={m.id}>{m.code} — {m.name}</option>)}
          </select>
        </label>
        <label>Matching published template
          <select value={selectedTemplate?String(selectedTemplate.id):''} disabled={!canWrite||!filteredTemplates.length} onChange={e=>setSelectedTemplateId(e.target.value)}>
            {filteredTemplates.length?filteredTemplates.map(t=><option key={t.id} value={t.id}>{t.name} · v{t.version}</option>):<option value="">{!operationCode||!defectCode?'Select operation and defect first':'No published template for this operation and defect'}</option>}
          </select>
        </label>
      </div>
      {defectCode&&<section className="fta-defect-history">
        <div className="panel-title">
          <div><h3>Automatic previous FTA detection</h3><p>History is matched by the selected shared Quality defect. Select a previous FTA to inspect the linkage and register this rejection as a recurrence.</p></div>
          {defectHistoryLoading&&<span className="muted small">Checking history…</span>}
        </div>
        {defectHistory&&!defectHistoryLoading&&<>
          <div className="fta-defect-history-summary">
            <div><span>Selected Quality defect</span><strong>{defectHistory.phenomenon_name||defectCode}</strong></div>
            <div><span>Last previous FTA date</span><strong>{defectHistory.last_fta_date?String(defectHistory.last_fta_date).slice(0,10):'No previous FTA'}</strong><small>{defectHistory.last_investigation_no||'No linked investigation found'}</small></div>
            <div><span>Previous investigations</span><strong>{defectHistory.total_previous_investigations||0}</strong></div>
          </div>
          {defectHistory.matches?.length>0?<>
            <div className="fta-defect-history-notice">
              <strong>Previous FTA found for this Quality defect</strong>
              <span>{rejectionId?'Showing FTAs dated before the selected Quality Rejection.':'Showing the latest recorded FTAs for this defect.'} Review the records before deciding whether this is a recurrence.</span>
            </div>
            <div className="table-wrap fta-defect-history-table">
              <table><thead><tr><th>FTA Date</th><th>FTA No.</th><th>Part</th><th>Operation / Machine</th><th>FTA Status</th><th>Linked Actions</th><th>Relationship</th><th></th></tr></thead>
                <tbody>{defectHistory.matches.map((item:any)=><tr key={item.investigation_id}>
                  <td>{String(item.fta_date||'').slice(0,10)}</td>
                  <td><b>{item.investigation_no}</b></td>
                  <td>{item.part_code}<div className="muted small">{item.part_name}</div></td>
                  <td>{item.operation_code}<div className="muted small">{item.machine_name||'Machine not recorded'}</div></td>
                  <td><Status value={item.status}/></td>
                  <td>{item.linked_action_status||'No linked action'}</td>
                  <td>{item.same_part?<span className="fta-match-tag same">Same part</span>:<span className="fta-match-tag">Same defect</span>}</td>
                  <td><div className="button-row">
                    <a className="button secondary small" href={`/fta?view=register&investigation_id=${item.investigation_id}`}>Open FTA</a>
                    {rejectionId&&item.same_part&&item.investigation_id===defectHistory.matches.find((match:any)=>match.same_part)?.investigation_id&&<button type="button" className="small" disabled={!canWrite||busy} onClick={()=>linkSelectedRejectionToPreviousFta(item)}>Register detected recurrence</button>}
                    {rejectionId&&item.same_part&&item.investigation_id!==defectHistory.matches.find((match:any)=>match.same_part)?.investigation_id&&<span className="muted small">Earlier FTA — use latest matching FTA</span>}
                    {rejectionId&&!item.same_part&&<span className="muted small">Different part — history only</span>}
                  </div></td>
                </tr>)}</tbody>
              </table>
            </div>
          </>:<p className="muted small">No earlier FTA has been recorded for this Quality defect.</p>}
        </>}
      </section>}
      <label>Investigation objective / initial observation
        <textarea value={summary} onChange={e=>setSummary(e.target.value)} rows={2} placeholder="Describe the defect, location, inspection result or immediate concern."/>
      </label>
      <div className="button-row"><button onClick={createInvestigation} disabled={!canWrite||busy||!rejectionId||!operationCode||!defectCode||!filteredTemplates.length}>Create investigation</button><button className="secondary" onClick={load} disabled={busy}>Refresh</button></div>
      <p className="muted small">Select the appropriate published template. Its version and tree are snapshotted when the investigation is created.</p>
    </section>}


    {view==='templates'&&canManageTemplates&&<section className="fta-template-master">
      <div className="panel-title" style={{padding:'18px 20px',border:'1px solid var(--border, #d8dee8)',borderRadius:12,background:'var(--panel-soft, #f5f8fc)',marginBottom:16}}>
        <div><div className="muted small" style={{fontWeight:800,letterSpacing:'.08em'}}>FAULT TREE ANALYSIS · CONFIGURATION</div><h2 style={{margin:'5px 0'}}>FTA Template Studio</h2><p style={{margin:0}}>Create, structure and publish reusable fault-tree templates for machining investigations.</p></div><span className="status-pill">{templates.filter((t:any)=>t.status==='PUBLISHED').length} published templates</span>
      </div>
      <div style={{display:'grid',gridTemplateColumns:'repeat(auto-fit,minmax(min(100%,180px),1fr))',gap:10,marginBottom:16}}>
        {[['01','Define masters','Set up machining operations and defect types.'],['02','Build the template','Describe events, relationships and specifications.'],['03','Review & publish','Save a draft, validate the tree and publish a version.']].map(([n,title,desc])=><div key={n} style={{border:'1px solid var(--border, #d8dee8)',borderRadius:9,padding:12,background:'var(--panel, #fff)',display:'flex',gap:10}}><strong style={{fontSize:18,color:'#2563eb'}}>{n}</strong><div><b style={{fontSize:13}}>{title}</b><p className="muted small" style={{margin:'3px 0 0'}}>{desc}</p></div></div>)}
      </div>
      <div className="fta-bottom-grid">
        <div className="panel"><div className="panel-title"><div><h3>Machining operations</h3><p>Maintain the process operations used by FTA templates.</p></div></div>
          <label>Operation code<input value={newOperationCode} onChange={e=>setNewOperationCode(e.target.value.toUpperCase())} placeholder="LASER_TURN"/></label>
          <label>Operation name<input value={newOperationName} onChange={e=>setNewOperationName(e.target.value)} placeholder="Laser turning"/></label>
          <button className="secondary" disabled={!newOperationCode.trim()||!newOperationName.trim()||busy} onClick={async()=>{try{setBusy(true);await api('/fta/operations',{method:'POST',body:JSON.stringify({code:newOperationCode,name:newOperationName})});setNewOperationCode('');setNewOperationName('');await load();setMessage('Machining operation added.')}catch(e:any){setError(e.message)}finally{setBusy(false)}}}>Add operation</button>
        </div>
        <div className="panel"><div className="panel-title"><div><h3>Defect types</h3><p>Maintain the defect classifications available to templates.</p></div></div>
          <label>Defect code<input value={newDefectCode} onChange={e=>setNewDefectCode(e.target.value.toUpperCase())} placeholder="THREAD-PITCH"/></label>
          <label>Category<input value={newDefectCategory} onChange={e=>setNewDefectCategory(e.target.value)} /></label>
          <label>Defect name<input value={newDefectName} onChange={e=>setNewDefectName(e.target.value)} placeholder="Incorrect thread pitch"/></label>
          <button className="secondary" disabled={!newDefectCode.trim()||!newDefectName.trim()||busy} onClick={async()=>{try{setBusy(true);await api('/fta/defects',{method:'POST',body:JSON.stringify({code:newDefectCode,category:newDefectCategory,name:newDefectName})});setNewDefectCode('');setNewDefectName('');await load();setMessage('Defect type added.')}catch(e:any){setError(e.message)}finally{setBusy(false)}}}>Add defect</button>
        </div>
      </div>
      <div className="panel" style={{marginBottom:16}}><div className="panel-title"><div><h3>New template</h3><p>Define the identity and scope of this fault-tree template.</p></div><span className="status-pill">Step 1 · Details</span></div>
      <div className="fta-create-grid">
        <label>New template code<input value={newTemplateCode} onChange={e=>setNewTemplateCode(e.target.value.toUpperCase())} placeholder="LASER_TURN-THREAD-PITCH"/></label>
        <label>New template name<input value={newTemplateName} onChange={e=>setNewTemplateName(e.target.value)} placeholder="Laser turning – incorrect thread pitch"/></label>
        <label>New template operation<select value={newTemplateOperation} onChange={e=>setNewTemplateOperation(e.target.value)}><option value="">Select operation</option>{operations.map(o=><option key={o.code} value={o.code}>{o.name}</option>)}</select></label>
        <label>New template defect<select value={newTemplateDefect} onChange={e=>setNewTemplateDefect(e.target.value)}><option value="">Select defect</option>{defects.map(d=><option key={d.code} value={d.code}>{d.category} – {d.name}</option>)}</select></label>
      </div>
      <button className="secondary" disabled={!newTemplateCode||!newTemplateName||!newTemplateOperation||!newTemplateDefect||!templateTree||busy} onClick={async()=>{try{const tree=templateTree;setBusy(true);const created:any=await api('/fta/templates',{method:'POST',body:JSON.stringify({code:newTemplateCode,name:newTemplateName,operation_code:newTemplateOperation,defect_code:newTemplateDefect,tree})});setTemplateDraftId(created.id);setBaseTemplateId(String(created.id));await load();setMessage('New FTA template created as draft. Review and publish it when ready.')}catch(e:any){setError(e instanceof SyntaxError?'Visual fault-tree builder is invalid.':e.message)}finally{setBusy(false)}}}>Create new template draft</button>
      </div>
      <details className="fta-event-help" style={{margin:'18px 0',border:'1px solid var(--border, #d8dee8)',borderRadius:12,background:'var(--panel, #fff)',overflow:'hidden'}}>
        <summary style={{listStyle:'none',cursor:'pointer',padding:'16px 18px',display:'flex',alignItems:'center',justifyContent:'space-between',gap:12,background:'var(--panel-soft, #f5f8fc)'}}>
          <span style={{display:'flex',alignItems:'center',gap:12}}>
            <span style={{width:38,height:38,display:'grid',placeItems:'center',borderRadius:10,background:'#e8efff',color:'#2457a7',fontSize:19,fontWeight:800}}>i</span>
            <span><strong style={{display:'block',fontSize:15}}>FTA Event Type Reference</strong><small className="muted">Definitions, machining examples and guidance for building a fault tree</small></span>
          </span>
          <span className="muted small">Open guide ▾</span>
        </summary>
        <div style={{padding:18}}>
          <div style={{display:'flex',flexWrap:'wrap',gap:7,marginBottom:16}}>
            <span className="status-pill">5 event types</span><span className="status-pill">Machining examples</span><span className="status-pill">AND / OR logic</span>
          </div>
          <p className="muted small" style={{marginTop:0}}>Select an event type based on the role it plays in the failure sequence. The examples below are illustrative; a suspected cause must still be verified with evidence.</p>
          <div style={{display:'grid',gridTemplateColumns:'repeat(auto-fit,minmax(min(100%,260px),1fr))',gap:12}}>
            {[
              {type:'TOP EVENT',color:'#7c3aed',tag:'Failure under analysis',meaning:'The unwanted failure or defect that the investigation is trying to explain.',example:'Incorrect thread pitch detected during final inspection.',use:'Start the tree with one clearly described top event.'},
              {type:'INTERMEDIATE EVENT',color:'#2563eb',tag:'Cause group',meaning:'A contributing event that can be broken down into more specific events.',example:'Tooling issue; machine setting issue; incorrect program or offset.',use:'Add child events and choose an AND or OR gate to describe their relationship.'},
              {type:'BASIC EVENT',color:'#059669',tag:'Specific cause',meaning:'A specific cause at the end of a branch in the current fault tree.',example:'Worn threading insert; wrong insert pitch; incorrect offset value.',use:'Use when the cause is specific enough to investigate and record evidence against.'},
              {type:'EXTERNAL EVENT',color:'#d97706',tag:'Outside system boundary',meaning:'An event originating outside the system being analysed, but capable of contributing to its failure.',example:'Factory power interruption; central compressed-air failure; incorrect drawing revision received from outside the production process.',use:'Use for an outside influence. Define the system boundary clearly.'},
              {type:'UNDEVELOPED EVENT',color:'#64748b',tag:'Not expanded in this analysis',meaning:'An event intentionally not broken down further in the current tree.',example:'Servo drive internal failure when detailed electrical analysis is outside the investigation scope.',use:'Use when details are unavailable or outside scope. Record why it was not developed; it may be expanded in a later controlled revision.'}
            ].map(item=><div key={item.type} style={{border:'1px solid var(--border, #d8dee8)',borderTop:'3px solid '+item.color,borderRadius:10,padding:14,background:'var(--panel, #fff)',display:'flex',flexDirection:'column',gap:8}}>
              <div style={{display:'flex',alignItems:'center',justifyContent:'space-between',gap:8,flexWrap:'wrap'}}><strong style={{fontSize:13,letterSpacing:'.02em'}}>{item.type}</strong><span style={{fontSize:10,fontWeight:700,color:item.color,background:item.color+'14',padding:'4px 7px',borderRadius:20}}>{item.tag}</span></div>
              <div><small className="muted" style={{fontWeight:700}}>MEANING</small><div style={{fontSize:13,lineHeight:1.5,marginTop:3}}>{item.meaning}</div></div>
              <div style={{padding:'9px 10px',borderRadius:7,background:'var(--panel-soft, #f5f8fc)'}}><small className="muted" style={{fontWeight:700}}>MACHINING EXAMPLE</small><div style={{fontSize:13,lineHeight:1.5,marginTop:3}}>{item.example}</div></div>
              <div><small className="muted" style={{fontWeight:700}}>WHEN TO USE</small><div style={{fontSize:13,lineHeight:1.5,marginTop:3}}>{item.use}</div></div>
            </div>)}
          </div>
          <div style={{marginTop:20}}>
            <div style={{marginBottom:10}}><h4 style={{margin:'0 0 3px'}}>Worked example · Incorrect thread pitch</h4><p className="muted small" style={{margin:0}}>Illustrative structure showing how different event types can appear in one analysis.</p></div>
            <div style={{border:'1px solid var(--border, #d8dee8)',borderRadius:10,padding:14,background:'var(--panel-soft, #f8fafc)',display:'grid',gap:9}}>
              <div style={{maxWidth:520,width:'100%',margin:'0 auto',padding:'11px 14px',borderRadius:8,borderLeft:'4px solid #7c3aed',background:'var(--panel, #fff)',boxShadow:'0 1px 3px #0000000a'}}><small style={{color:'#7c3aed',fontWeight:800}}>TOP EVENT</small><div style={{fontWeight:700,fontSize:14}}>Incorrect thread pitch detected</div></div>
              <div style={{textAlign:'center',fontSize:12,fontWeight:700,color:'var(--muted, #64748b)'}}>↓ OR · any one contributing path may lead to the top event</div>
              <div style={{display:'grid',gridTemplateColumns:'repeat(auto-fit,minmax(min(100%,190px),1fr))',gap:9}}>
                <div style={{padding:11,borderRadius:8,borderLeft:'4px solid #2563eb',background:'var(--panel, #fff)'}}><small style={{color:'#2563eb',fontWeight:800}}>INTERMEDIATE EVENT</small><div style={{fontWeight:700,fontSize:13}}>Tooling / setting / program issue</div><div style={{fontSize:12,marginTop:5}}>OR gate → worn insert, wrong insert pitch, incorrect offset</div></div>
                <div style={{padding:11,borderRadius:8,borderLeft:'4px solid #d97706',background:'var(--panel, #fff)'}}><small style={{color:'#d97706',fontWeight:800}}>EXTERNAL EVENT</small><div style={{fontWeight:700,fontSize:13}}>Incorrect drawing revision supplied</div><div style={{fontSize:12,marginTop:5}}>Originates outside the production process being analysed</div></div>
                <div style={{padding:11,borderRadius:8,borderLeft:'4px solid #64748b',background:'var(--panel, #fff)'}}><small style={{color:'#64748b',fontWeight:800}}>UNDEVELOPED EVENT</small><div style={{fontWeight:700,fontSize:13}}>CNC controller internal fault</div><div style={{fontSize:12,marginTop:5}}>Refer to specialist analysis; not expanded in this tree</div></div>
              </div>
              <div style={{padding:'9px 11px',borderRadius:8,background:'#05966912',borderLeft:'4px solid #059669',fontSize:12}}><b style={{color:'#059669'}}>BASIC EVENT examples:</b> Worn threading insert · Incorrect pitch insert selected · Wrong offset entered</div>
            </div>
            <p className="muted small" style={{margin:'8px 0 0'}}>The example does not assert that any listed cause is responsible. Investigate and confirm causes using actual measurements, records and evidence.</p>
          </div>
          <div style={{marginTop:16,display:'grid',gridTemplateColumns:'repeat(auto-fit,minmax(min(100%,220px),1fr))',gap:10}}>
            <div style={{padding:12,border:'1px solid var(--border, #d8dee8)',borderRadius:8}}><strong style={{fontSize:13}}>OR gate</strong><p className="muted small" style={{margin:'5px 0 0'}}>Any one of the child events is sufficient to cause the parent event.</p></div>
            <div style={{padding:12,border:'1px solid var(--border, #d8dee8)',borderRadius:8}}><strong style={{fontSize:13}}>AND gate</strong><p className="muted small" style={{margin:'5px 0 0'}}>All listed child events must occur together to cause the parent event.</p></div>
          </div>
          <p className="muted small" style={{margin:'14px 0 0'}}>Tip: Use Basic Events for specific investigable causes. Use Undeveloped Events only when you intentionally stop the analysis at that point and document the reason.</p>
        </div>
      </details>
      <div className="panel" style={{marginBottom:14}}><div className="panel-title"><div><h3>Revise an existing template</h3><p>Select a published template to load its tree and create the next controlled version.</p></div><span className="status-pill">Step 2 · Revision</span></div>
      <div className="fta-create-grid">
        <label>Base template
          <select value={baseTemplateId} onChange={e=>{setBaseTemplateId(e.target.value);setTemplateDraftId(null)}}>
            <option value="">Select template to revise</option>
            {templates.map(t=><option key={t.id} value={t.id}>{t.code} · v{t.version} · {t.status}</option>)}
          </select>
        </label>
        <label>Template name<input value={templateName} onChange={e=>setTemplateName(e.target.value)} placeholder="Machining defect fault tree"/></label>
      </div>
      <div className="button-row" style={{marginTop:12,marginBottom:12,justifyContent:'flex-start'}}>
        <button className="secondary" disabled={!baseTemplateId||busy} onClick={async()=>{try{setBusy(true);const t:any=await api('/fta/templates/'+baseTemplateId);setTemplateName(t.name);setTemplateTree(t.tree);setTemplateDraftId(t.status==='DRAFT'?t.id:null)}catch(e:any){setError(e.message)}finally{setBusy(false)}}}>Load selected tree</button>
      </div>
      <div className="panel" style={{marginTop:12}}>
        <div className="panel-title"><div><h3>Visual fault-tree designer</h3><p>Build the cause hierarchy using event cards. No JSON editing is required.</p></div><span className="status-pill">Step 3 · Design</span><button type="button" className="secondary small" onClick={()=>setTemplateTree({id:'top_event',label:'Top event',type:'TOP_EVENT',gate:'OR',children:[{id:'cause_1',label:'Main cause',type:'INTERMEDIATE_EVENT',gate:'OR',children:[{id:'cause_1_1',label:'Basic cause',type:'BASIC_EVENT'}]}]})}>Reset tree</button></div>
        <TemplateNodeEditor node={templateTree} root onChange={setTemplateTree}/>
        <div className="fta-node-colour-legend" style={{display:'flex',flexWrap:'wrap',gap:12,marginTop:10,fontSize:12}}>{[['TOP_EVENT','Top event'],['INTERMEDIATE_EVENT','Intermediate'],['BASIC_EVENT','Basic cause'],['EXTERNAL_EVENT','External'],['UNDEVELOPED_EVENT','Undeveloped']].map(([type,label])=><span key={type} style={{display:'inline-flex',alignItems:'center',gap:5}}><i style={{display:'inline-block',width:18,height:4,borderRadius:4,background:nodeConnectorColor(type)}}/>{label}</span>)}</div>
        <p className="muted small">Maximum 8 levels and 300 nodes. Top and intermediate events need child causes. Basic, external and undeveloped events are leaf nodes. Each node receives a unique ID automatically.</p>
      </div>
      <div className="button-row">
        <button disabled={!baseTemplateId||!templateTree||busy} onClick={async()=>{try{const tree=templateTree;setBusy(true);let result:any;if(templateDraftId){result=await api('/fta/templates/'+templateDraftId,{method:'PUT',body:JSON.stringify({name:templateName,tree})})}else{result=await api('/fta/templates/'+baseTemplateId+'/revisions',{method:'POST',body:JSON.stringify({name:templateName||undefined,tree})});setTemplateDraftId(result.id)}await load();setMessage('Draft template saved. Review and publish it when ready.')}catch(e:any){setError(e instanceof SyntaxError?'Fault tree JSON is invalid.':e.message)}finally{setBusy(false)}}}>Save draft revision</button>
        <button className="secondary" disabled={!templateDraftId||busy} onClick={async()=>{try{setBusy(true);await api('/fta/templates/'+templateDraftId+'/publish',{method:'POST'});setTemplateDraftId(null);await load();setMessage('Template revision published. New investigations will use the published version.')}catch(e:any){setError(e.message)}finally{setBusy(false)}}}>Publish draft</button>
      </div>
      <p className="muted small">Node types: TOP_EVENT, INTERMEDIATE_EVENT, BASIC_EVENT, EXTERNAL_EVENT, UNDEVELOPED_EVENT. Nodes with children require an AND or OR gate. Each node ID must be unique.</p>
      </div>
    </section>}

    {view==='register'&&<section className="panel">
      <div className="panel-title"><div><h2>Investigation register</h2><p>Latest 500 investigations. Select a record to continue the analysis.</p></div><span className="muted">{investigations.length} records</span></div>
      <div className="table-wrap"><table><thead><tr><th>FTA No.</th><th>Date</th><th>Part</th><th>Defect / Template</th><th>Plant</th><th>Status</th><th></th></tr></thead>
        <tbody>{investigations.map(i=><tr key={i.id}><td>{i.investigation_no}</td><td>{String(i.created_at||'').slice(0,10)}</td><td>{i.part_code} – {i.part_name}</td><td>{i.defect_name}<div className="muted small">{i.template_name}</div></td><td>{i.plant||'—'}</td><td><span className="status-pill">{i.status.replaceAll('_',' ')}</span></td><td><button className="small secondary" onClick={()=>loadDetail(i.id)}>Open</button></td></tr>)}
        {!investigations.length&&<tr><td colSpan={7} className="muted">No FTA investigations created yet.</td></tr>}</tbody>
      </table></div>
    </section>}

    {view==='register'&&detail&&tree&&<section className="panel fta-workspace">
      <div className="panel-title"><div><h2>{detail.investigation_no} – {detail.template_snapshot?.template_name}</h2><p>Rejection #{detail.rejection_id} · {detail.plant||'Plant not specified'} · {detail.status.replaceAll('_',' ')}</p>{detail.template_snapshot?.related_to_investigation_id&&<p className="muted small">Related to original FTA <a href={`/fta?view=register&investigation_id=${detail.template_snapshot.related_to_investigation_id}`}>{detail.template_snapshot.related_to_investigation_no||('#'+detail.template_snapshot.related_to_investigation_id)}</a></p>}</div><div className="button-row"><a className="button secondary" href={'/fta/report/'+detail.id}>FTA report</a><button className="secondary small" onClick={()=>{setDetail(null);setSelectedId(null)}}>Close workspace</button></div></div>
      <div className="fta-workspace-grid">
        <div className="fta-tree-panel" id="fta-section-fault-tree">
          <div style={{display:'flex',alignItems:'center',justifyContent:'space-between',gap:10,flexWrap:'wrap',marginBottom:8}}>
            <h3 style={{margin:0}}>Fault tree</h3>
            {['OPEN','IN_PROGRESS'].includes(detail.status)&&!confirmedRootCause&&(()=>{
              const currentVersion=Number(detail.template_version||detail.template_snapshot?.template_version||0)
              const newer=templates.filter((t:any)=>t.status==='PUBLISHED'&&t.code===detail.template_snapshot?.template_code&&Number(t.version)>currentVersion).sort((a:any,b:any)=>Number(b.version)-Number(a.version))
              const latest=newer[0]
              return latest?<button type="button" className="secondary small" disabled={busy} onClick={()=>upgradeTemplateVersion(String(latest.id))}>Revise Template to New Version · V{latest.version}</button>:null
            })()}
          </div>
          <p className="muted small">Select a cause node to record evidence and investigation status. Gate labels describe logical relationships; they do not prove causality.</p>
          <TreeNode node={tree} findings={detail.findings||[]} selected={selectedNode} onSelect={setSelectedNode}/>
        </div>
        <div className="fta-finding-panel" id="fta-section-root-cause">
          <h3>Investigation finding</h3>
          {currentFinding?<>
            <strong>{currentFinding.node_label}</strong>
            {currentNodeTemplate?.requirement?.trim()&&<div className="fta-template-requirement" style={{margin:'10px 0',padding:'10px 12px',borderLeft:'3px solid #2563eb',background:'var(--panel-soft, #f5f8fc)',borderRadius:6}}><b>Template requirement / specification</b><p style={{margin:'4px 0 0',whiteSpace:'pre-wrap'}}>{currentNodeTemplate.requirement}</p><small className="muted">Use this as the expected condition while checking the cause. You can adjust the expected value below for this investigation.</small></div>}
            <label>Investigation status
              <select value={findingForm.investigation_status||'NOT_INVESTIGATED'} disabled={!canWrite||!['OPEN','IN_PROGRESS'].includes(detail.status)} onChange={e=>setFindingForm((v:any)=>({...v,investigation_status:e.target.value}))}>
                {['NOT_INVESTIGATED','UNDER_INVESTIGATION','SUSPECTED','CONFIRMED','RULED_OUT','UNABLE_TO_DETERMINE','NOT_APPLICABLE'].map(x=><option key={x} value={x}>{x.replaceAll('_',' ')}</option>)}
              </select>
            </label>
            <label>Investigation priority<select value={findingForm.priority||'MEDIUM'} disabled={!canWrite||!['OPEN','IN_PROGRESS'].includes(detail.status)} onChange={e=>setFindingForm((v:any)=>({...v,priority:e.target.value}))}><option value="HIGH">High</option><option value="MEDIUM">Medium</option><option value="LOW">Low</option></select></label>
            {findingForm.investigation_status==='NOT_APPLICABLE'&&<p className="muted small">Explain why this cause does not apply in the observation field. A reason is required before saving.</p>}
            <label>Observation / evidence reference<textarea rows={3} value={findingForm.observation||''} disabled={!canWrite||!['OPEN','IN_PROGRESS'].includes(detail.status)} onChange={e=>setFindingForm((v:any)=>({...v,observation:e.target.value}))}/></label>
            <div className="fta-create-grid">
              <label>Measured value<input value={findingForm.measured_value||''} disabled={!canWrite||!['OPEN','IN_PROGRESS'].includes(detail.status)} onChange={e=>setFindingForm((v:any)=>({...v,measured_value:e.target.value}))}/></label>
              <label>Expected value (prefilled from template, editable)<input value={findingForm.expected_value||''} disabled={!canWrite||!['OPEN','IN_PROGRESS'].includes(detail.status)} onChange={e=>setFindingForm((v:any)=>({...v,expected_value:e.target.value}))}/></label>
            </div>
            <label>Verification method<textarea rows={2} value={findingForm.verification_method||''} disabled={!canWrite||!['OPEN','IN_PROGRESS'].includes(detail.status)} onChange={e=>setFindingForm((v:any)=>({...v,verification_method:e.target.value}))}/></label>
            <label>Verification result<textarea rows={2} value={findingForm.verification_result||''} disabled={!canWrite||!['OPEN','IN_PROGRESS'].includes(detail.status)} onChange={e=>setFindingForm((v:any)=>({...v,verification_result:e.target.value}))}/></label>
            <details className="fta-finding-history"><summary>Finding change history ({(detail.finding_history||[]).filter((h:any)=>h.finding_id===currentFinding.id).length})</summary>
              {(detail.finding_history||[]).filter((h:any)=>h.finding_id===currentFinding.id).map((h:any)=><div className="fta-history-row" key={h.id}><strong>{h.old?.investigation_status||'NEW'} → {h.new?.investigation_status}</strong><span>{String(h.created_at||'').replace('T',' ').slice(0,19)}</span><p>{h.new?.observation||'No observation recorded'}</p></div>)}
            </details>
            <label className="fta-check"><input type="checkbox" checked={!!findingForm.is_root_cause} disabled={!canWrite||!['OPEN','IN_PROGRESS'].includes(detail.status)} onChange={e=>setFindingForm((v:any)=>({...v,is_root_cause:e.target.checked}))}/> Confirmed root cause</label>
            <label className="fta-check"><input type="checkbox" checked={!!findingForm.is_occurrence_cause} disabled={!canWrite||!['OPEN','IN_PROGRESS'].includes(detail.status)} onChange={e=>setFindingForm((v:any)=>({...v,is_occurrence_cause:e.target.checked}))}/> Occurrence cause</label>
            <label className="fta-check"><input type="checkbox" checked={!!findingForm.is_escape_cause} disabled={!canWrite||!['OPEN','IN_PROGRESS'].includes(detail.status)} onChange={e=>setFindingForm((v:any)=>({...v,is_escape_cause:e.target.checked}))}/> Escape / detection cause</label>
            <div className="fta-evidence-box">
              <strong>Evidence attachments</strong>
              <label>Photo, PDF or inspection document<input type="file" accept=".jpg,.jpeg,.png,.webp,.pdf,.xlsx,.csv,.txt" onChange={e=>setEvidenceFile(e.target.files?.[0]||null)}/></label>
              <label>Caption<input value={evidenceCaption} onChange={e=>setEvidenceCaption(e.target.value)} placeholder="Measurement report, tool condition, setup photo…"/></label>
              <button className="secondary" disabled={!canWrite||!evidenceFile||busy||!['OPEN','IN_PROGRESS'].includes(detail.status)} onClick={async()=>{try{setBusy(true);const form=new FormData();form.append('file',evidenceFile as File);form.append('finding_id',String(currentFinding.id));form.append('caption',evidenceCaption);await api('/fta/investigations/'+detail.id+'/evidence',{method:'POST',body:form});setEvidenceFile(null);setEvidenceCaption('');await loadDetail(detail.id,true);setMessage('Evidence uploaded securely.')}catch(e:any){setError(e.message)}finally{setBusy(false)}}}>Upload evidence</button>
              {(detail.evidence||[]).filter((x:any)=>x.finding_id===currentFinding.id).map((x:any)=><div className="fta-evidence-item" key={x.id}><span>{x.file_name}{x.caption?' · '+x.caption:''}</span><button className="small secondary" onClick={()=>downloadApi('/fta/investigations/'+detail.id+'/evidence/'+x.id,x.file_name)}>Download</button></div>)}
            </div>
            <button onClick={saveFinding} disabled={!canWrite||busy||!['OPEN','IN_PROGRESS'].includes(detail.status)}>Save finding</button>
          </>:<p className="muted">Select a node in the fault tree.</p>}
        </div>
      </div>
      <div className="fta-review-controls" id="fta-section-closure">
        <label>Verification remarks<textarea rows={2} value={verificationRemarks} onChange={e=>setVerificationRemarks(e.target.value)} disabled={!canVerify||!['OPEN','IN_PROGRESS'].includes(detail.status)}/></label>
        <button className="secondary" disabled={!canVerify||busy||detail.status!=='IN_PROGRESS'||!hasRequiredAction} onClick={async()=>{try{setBusy(true);await api('/fta/investigations/'+detail.id+'/verify',{method:'POST',body:JSON.stringify({remarks:verificationRemarks})});await loadDetail(detail.id,true);await load();setMessage('Investigation verified. Complete linked actions before closure.')}catch(e:any){setError(e.message)}finally{setBusy(false)}}}>Verify investigation</button>
        <label>Closure remarks<textarea rows={2} value={closureRemarks} onChange={e=>setClosureRemarks(e.target.value)} disabled={!canVerify||detail.status!=='VERIFIED_PENDING_ACTIONS'}/></label>
        <button disabled={!canVerify||busy||detail.status!=='VERIFIED_PENDING_ACTIONS'} onClick={async()=>{try{setBusy(true);await api('/fta/investigations/'+detail.id+'/close',{method:'POST',body:JSON.stringify({remarks:closureRemarks})});await loadDetail(detail.id,true);await load();setMessage('Investigation closed.')}catch(e:any){setError(e.message)}finally{setBusy(false)}}}>Close investigation</button>
      </div>
      <section className="fta-process-flow">
        <div className="panel-title"><div><h3>Investigation process flow</h3><p>Live completion status based on saved findings, linked actions and closure records.</p></div><strong>{flowRows.filter((x:any)=>x.state==='completed').length} / {flowRows.length} completed</strong></div>
        <div className="fta-process-list">
          {flowRows.map((step:any,index:number)=>{
            const targets=['fta-section-investigation','fta-section-fault-tree','fta-section-root-cause','fta-section-actions','fta-section-action-review','fta-section-closure']
            return <article className={`fta-process-step ${step.state}`} key={step.title}>
              <div className="fta-process-marker">{step.state==='completed'?'✓':index+1}</div>
              <div className="fta-process-copy"><div className="fta-process-heading"><a className="fta-process-link" href={index===4&&requiredActions[0]?(`/actions?view=register&action_id=${requiredActions[0].id}`):`#${targets[index]}`}>{step.title}</a><span className={`fta-process-status ${step.state}`}>{step.state==='completed'?'Completed':step.state==='in-progress'?'In progress':'Pending'}</span></div><p>{step.description}</p>
                {index===4&&requiredActions.length>0?<div className="fta-process-action-links">{requiredActions.map((action:any)=><a className="fta-process-update-link" key={action.id} href={`/actions?view=register&action_id=${action.id}`}>Update {action.action_no} action plan →</a>)}</div>:<a className="fta-process-update-link" href={`#${targets[index]}`}>{index===4?'Review discovered causes →':'Go to section to update →'}</a>}
              </div>
            </article>
          })}
        </div>
      </section>
      <section className="panel fta-recurrence-panel" id="fta-section-recurrences">
        <div className="panel-title"><div><h3>Recurrence management</h3><p>Link a later rejection for the same part and shared phenomenon. Original findings and actions remain unchanged.</p></div><strong>{(detail.recurrences||[]).length} linked recurrences</strong></div>
        <div className="fta-auto-recurrence">
          <div className="panel-title">
            <div><h4>Automatic recurrence detection</h4><p>New Quality Rejection rows are checked automatically against the same Quality defect as this FTA.</p></div>
            <strong>{detail.recurrence_suggestions?.suggestion_count||0} possible matches</strong>
          </div>
          <div className="fta-defect-history-summary">
            <div><span>Quality defect</span><strong>{detail.recurrence_suggestions?.phenomenon_name||detail.source_rejection?.defect_name||'—'}</strong></div>
            <div><span>Original FTA date</span><strong>{detail.recurrence_suggestions?.original_fta_date?String(detail.recurrence_suggestions.original_fta_date).slice(0,10):String(detail.created_at||'').slice(0,10)||'—'}</strong></div>
            <div><span>Latest detected rejection</span><strong>{detail.recurrence_suggestions?.last_matching_rejection_date?String(detail.recurrence_suggestions.last_matching_rejection_date).slice(0,10):'No later rejection'}</strong></div>
          </div>
          {recurrenceSuggestionsLoading&&<p className="muted small">Checking Quality Rejection history…</p>}
          {!recurrenceSuggestionsLoading&&(detail.recurrence_suggestions?.suggestions||[]).length>0?<div className="table-wrap fta-defect-history-table">
            <table><thead><tr><th>Rejection Date</th><th>Rejection ID</th><th>Part</th><th>Machine / Plant</th><th>Time Since Original</th><th>Match</th><th></th></tr></thead>
              <tbody>{detail.recurrence_suggestions.suggestions.map((item:any)=><tr key={item.rejection_id}>
                <td>{String(item.rejection_date||'').slice(0,10)}</td>
                <td><b>#{item.rejection_id}</b><div className="muted small">Shift {item.shift||'—'} · Qty {item.reject_qty??'—'}</div></td>
                <td>{item.part_code}<div className="muted small">{item.part_name}</div></td>
                <td>{item.machine_name||'—'}<div className="muted small">{item.plant||'Plant not recorded'}</div></td>
                <td>{item.days_after_original===0?'Same day':item.days_after_original+' days later'}</td>
                <td><div className="fta-match-tags"><span className="fta-match-tag">Same defect</span>{item.same_part&&<span className="fta-match-tag same">Same part</span>}{item.same_plant&&<span className="fta-match-tag same">Same plant</span>}{item.same_machine&&<span className="fta-match-tag same">Same machine</span>}</div></td>
                <td>{item.same_part?<button type="button" className="small" disabled={!canWrite||busy} onClick={()=>linkDetectedRecurrence(item)}>Link as recurrence</button>:<span className="muted small">Different part — history only</span>}</td>
              </tr>)}</tbody>
            </table>
          </div>:!recurrenceSuggestionsLoading&&<p className="muted small">No later, unlinked Quality Rejection records were found for this defect.</p>}
          <p className="muted small">Detection is automatic. Linking creates a pending recurrence record; Quality still confirms same root cause, different root cause or unrelated occurrence. Existing FTA findings and actions are not overwritten.</p>
        </div>
        <details className="fta-manual-recurrence">
          <summary>Manually link a rejection not found by automatic detection</summary>
          <label>Quality Rejection
            <select value={recurrenceRejectionId} onChange={async e=>{const value=e.target.value;setRecurrenceRejectionId(value);setRecurrenceCandidates([]);if(value){try{setRecurrenceCandidates(await api('/fta/recurrence-candidates/'+value))}catch(err:any){setError(err.message)}}}}>
              <option value="">Select rejection</option>
              {rejections.filter((r:any)=>Number(r.id)!==Number(detail.rejection_id)).map((r:any)=><option key={r.id} value={r.id}>{rejectionOptionLabel(r)}</option>)}
            </select>
          </label>
          {recurrenceCandidates.length>0&&<div className="fta-history-row"><b>Possible original investigations:</b>{recurrenceCandidates.map((x:any)=><p key={x.investigation_id}>{x.investigation_no} · {x.part_code} · {x.status} · Previous actions: {x.previous_action_status||'None'}</p>)}</div>}
          <label>Recurrence reason<textarea rows={2} value={recurrenceReason} onChange={e=>setRecurrenceReason(e.target.value)} placeholder="Describe why this new rejection may be related to the original investigation."/></label>
          <div className="fta-create-grid"><label>Containment action<textarea rows={2} value={recurrenceContainment} onChange={e=>setRecurrenceContainment(e.target.value)}/></label><label>New evidence / observations<textarea rows={2} value={recurrenceEvidence} onChange={e=>setRecurrenceEvidence(e.target.value)}/></label></div>
          <button className="secondary" disabled={!canWrite||busy||!recurrenceRejectionId||recurrenceReason.trim().length<5} onClick={async()=>{try{setBusy(true);await api('/fta/investigations/'+detail.id+'/recurrences',{method:'POST',body:JSON.stringify({rejection_id:Number(recurrenceRejectionId),recurrence_reason:recurrenceReason,containment_action:recurrenceContainment,new_evidence:recurrenceEvidence})});setRecurrenceRejectionId('');setRecurrenceReason('');setRecurrenceContainment('');setRecurrenceEvidence('');setRecurrenceCandidates([]);await loadDetail(detail.id,true);setMessage('Recurrence linked without changing the original FTA record.')}catch(e:any){setError(e.message)}finally{setBusy(false)}}}>Link manually</button>
        </details>
        {(detail.recurrences||[]).map((r:any)=><article className="fta-history-row" key={r.id}><div className="panel-title"><strong>Rejection #{r.rejection_id} · {String(r.rejection_date||'').slice(0,10)} · {r.classification.replaceAll('_',' ')}</strong><span>{r.part_code} · Qty {r.reject_qty}</span></div><p>{r.recurrence_reason}</p>{r.containment_action&&<p><b>Containment:</b> {r.containment_action}</p>}{r.new_evidence&&<p><b>New evidence:</b> {r.new_evidence}</p>}<p className="muted small">Previous action status: {r.previous_action_status||'Not recorded'} · Previous verification: {r.previous_verification_result||'Not recorded'}</p>{r.review_remarks&&<p><b>Quality review:</b> {r.review_remarks}</p>}
          {r.related_investigation_id&&<p><a href={`/fta?view=register&investigation_id=${r.related_investigation_id}`}>Open related investigation {r.related_investigation_no||''} →</a></p>}
          {r.classification==='SAME_ROOT_CAUSE'&&<p className="muted small">Same root cause: raise an additional or revised corrective action in the original FTA's Corrective / Preventive Actions section. Existing actions and history remain preserved.</p>}
          {canWrite&&r.classification==='DIFFERENT_ROOT_CAUSE'&&!r.related_investigation_id&&<div className="button-row">
            <select value={relatedTemplateId[r.id]||''} onChange={e=>setRelatedTemplateId(v=>({...v,[r.id]:e.target.value}))}>
              <option value="">Select phenomenon-matched published FTA template</option>
              {templates.filter((t:any)=>t.status==='PUBLISHED'&&t.defect_name===r.phenomenon).map((t:any)=><option key={t.id} value={t.id}>{t.name} · v{t.version}</option>)}
            </select>
            <button className="secondary" disabled={busy||!relatedTemplateId[r.id]} onClick={async()=>{try{setBusy(true);const result:any=await api('/fta/recurrences/'+r.id+'/related-investigation',{method:'POST',body:JSON.stringify({template_id:Number(relatedTemplateId[r.id]),summary:'Separate investigation created after Quality classified this recurrence as a different root cause.'})});await loadDetail(detail.id,true);await load();setMessage('Related investigation '+result.investigation_no+' created and linked.')}catch(e:any){setError(e.message)}finally{setBusy(false)}}}>Create related FTA</button>
          </div>}
          {canVerify&&r.classification==='PENDING_REVIEW'&&<div className="button-row"><select id={'fta-recurrence-review-'+r.id} defaultValue="SAME_ROOT_CAUSE"><option value="SAME_ROOT_CAUSE">Same root cause</option><option value="DIFFERENT_ROOT_CAUSE">Different root cause</option><option value="UNRELATED">Unrelated</option></select><button className="secondary" disabled={busy} onClick={async()=>{const classification=(document.getElementById('fta-recurrence-review-'+r.id) as HTMLSelectElement).value;const remarks=window.prompt('Quality review remarks (minimum 5 characters)');if(!remarks||remarks.trim().length<5)return;try{setBusy(true);await api('/fta/recurrences/'+r.id+'/review',{method:'PATCH',body:JSON.stringify({classification,review_remarks:remarks})});await loadDetail(detail.id,true);setMessage('Recurrence classification reviewed and saved.')}catch(e:any){setError(e.message)}finally{setBusy(false)}}}>Save Quality review</button></div>}
        </article>)}
        {!(detail.recurrences||[]).length&&<p className="muted">No recurrence records linked to this investigation.</p>}
      </section>
      <section className="fta-history">
        <h3>Investigation audit history</h3>
        {(detail.status_history||[]).map((h:any)=><div className="fta-history-row" key={h.id}><strong>{h.old_status||'NEW'} → {h.new_status}</strong><span>{String(h.created_at||'').replace('T',' ').slice(0,19)}</span><p>{historyRemark(h.remarks)}</p></div>)}
      </section>
      <div className="fta-bottom-grid">
        <div id="fta-section-investigation"><h3>Investigation summary</h3>
          <label>Initial defect / investigation summary<textarea rows={2} value={summary} onChange={e=>setSummary(e.target.value)} disabled={!canWrite||!['OPEN','IN_PROGRESS'].includes(detail.status)}/></label>
          <label>Occurrence cause summary<textarea rows={2} value={occurrenceSummary} onChange={e=>setOccurrenceSummary(e.target.value)} disabled={!canWrite||!['OPEN','IN_PROGRESS'].includes(detail.status)}/></label>
          <label>Escape / detection cause summary<textarea rows={2} value={escapeSummary} onChange={e=>setEscapeSummary(e.target.value)} disabled={!canWrite||!['OPEN','IN_PROGRESS'].includes(detail.status)}/></label>
          <button className="secondary" onClick={saveSummary} disabled={!canWrite||busy||!['OPEN','IN_PROGRESS'].includes(detail.status)}>Save investigation summaries</button></div>
        <div id="fta-section-actions"><h3>Corrective / preventive actions</h3>
          <label>Create new corrective / preventive action
            <textarea rows={2} value={newActionDescription} onChange={e=>setNewActionDescription(e.target.value)} disabled={!canWrite||!['OPEN','IN_PROGRESS'].includes(detail.status)}/>
          </label>
          <button className="secondary" disabled={!canWrite||!newActionDescription.trim()||busy||!['OPEN','IN_PROGRESS'].includes(detail.status)} onClick={async()=>{try{setBusy(true);const created:any=await api('/fta/investigations/'+detail.id+'/actions/create',{method:'POST',body:JSON.stringify({action_description:newActionDescription,finding_id:currentFinding?.id||null})});await loadDetail(detail.id,true);await load();setMessage('Action '+created.action.action_no+' created and linked. Root-cause analysis remains in FTA; no separate Why-Why form is required.')}catch(e:any){setError(e.message)}finally{setBusy(false)}}}>Create action (FTA analysis)</button>
          <div className="fta-action-link">
            <select value={actionId} disabled={!canWrite||!['OPEN','IN_PROGRESS'].includes(detail.status)} onChange={e=>setActionId(e.target.value)}><option value="">Select existing action</option>{availableActions.map(a=><option key={a.id} value={a.id}>{a.action_no} · {a.status} · {a.action_description}</option>)}</select>
            <select value={actionRelationship} disabled={!canWrite||!['OPEN','IN_PROGRESS'].includes(detail.status)} onChange={e=>setActionRelationship(e.target.value)}><option value="CORRECTIVE">Corrective</option><option value="PREVENTIVE">Preventive</option><option value="CONTAINMENT">Containment</option></select>
            <button className="secondary" disabled={!canWrite||!actionId||busy||!['OPEN','IN_PROGRESS'].includes(detail.status)} onClick={async()=>{try{setBusy(true);await api(`/fta/investigations/${detail.id}/actions`,{method:'POST',body:JSON.stringify({action_id:Number(actionId),finding_id:currentFinding?.id||null,relationship_type:actionRelationship})});await loadDetail(detail.id,true);setActionId('');setMessage('Existing action linked.')}catch(e:any){setError(e.message)}finally{setBusy(false)}}}>Link action</button>
          </div>
          {(detail.actions||[]).length?detail.actions.map((a:any)=><p key={a.link_id}>{a.action_no} · {a.status} · {a.action_description}</p>):<p className="muted">No existing actions linked yet.</p>}</div>
      </div>
      <section className="panel" id="fta-section-action-review">
        <div className="panel-title"><div><h3>Causes Discovered During Action Implementation</h3><p>New reasons reported by action owners are automatically recorded here and reviewed by Quality.</p></div></div>
        {(detail.discovered_causes||[]).length?(detail.discovered_causes||[]).map((cause:any)=><article className="fta-history-row" key={cause.id}>
          <div className="panel-title"><strong>{cause.cause_description}</strong><Status value={cause.status}/></div>
          <p>Reported from {cause.action_no} · {cause.reported_by_name||'Action owner'} · {String(cause.created_at||'').replace('T',' ').slice(0,19)}</p>
          {cause.evidence_reference&&<p><b>Evidence:</b> {cause.evidence_reference}</p>}
          {cause.review_remarks&&<p><b>Review:</b> {cause.review_remarks}{cause.verification_method?' · Method: '+cause.verification_method:''}</p>}
          {['PROPOSED','ACCEPTED'].includes(cause.status)&&canVerify&&<div className="button-row">
{cause.status==='PROPOSED'&&<button className="secondary" disabled={busy} onClick={async()=>{const remarks=window.prompt('Review remarks (required)');if(!remarks||remarks.trim().length<5)return;try{setBusy(true);await api('/fta/discovered-causes/'+cause.id+'/review',{method:'POST',body:JSON.stringify({status:'ACCEPTED',review_remarks:remarks})});await loadDetail(detail.id,true);setMessage('Cause accepted for further investigation.')}catch(e:any){setError(e.message)}finally{setBusy(false)}}}>Accept for investigation</button>}
            <button className="secondary" disabled={busy} onClick={async()=>{const method=window.prompt('Verification method required to confirm this root cause');if(!method||!method.trim())return;const remarks=window.prompt('Review remarks (required)');if(!remarks||remarks.trim().length<5)return;try{setBusy(true);await api('/fta/discovered-causes/'+cause.id+'/review',{method:'POST',body:JSON.stringify({status:'CONFIRMED',verification_method:method,review_remarks:remarks})});await loadDetail(detail.id,true);setMessage('Discovered cause confirmed and recorded in the FTA report.')}catch(e:any){setError(e.message)}finally{setBusy(false)}}}>Confirm as root cause</button>
            <button className="secondary" disabled={busy} onClick={async()=>{const remarks=window.prompt('Reason for ruling out this cause (required)');if(!remarks||remarks.trim().length<5)return;try{setBusy(true);await api('/fta/discovered-causes/'+cause.id+'/review',{method:'POST',body:JSON.stringify({status:'RULED_OUT',review_remarks:remarks})});await loadDetail(detail.id,true);setMessage('Discovered cause ruled out.')}catch(e:any){setError(e.message)}finally{setBusy(false)}}}>Rule out</button>
          </div>}
        </article>):<p className="muted">No additional causes have been reported during action implementation.</p>}
      </section>
    </section>}
  </div>
}
