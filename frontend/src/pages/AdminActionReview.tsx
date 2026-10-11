import { timestampDateIST, formatIST, istLocalToUTC } from '../time'
import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import { MultiSelect } from '../components/MultiSelect'
import { PageHeader, Status } from '../components/UI'

export default function AdminActionReview(){
  const navigate=useNavigate()
  const [groups,setGroups]=useState<any[]>([])
  const [users,setUsers]=useState<any[]>([])
  const [selectedUsers,setSelectedUsers]=useState<string[]>([])
  const [onlyOverdue,setOnlyOverdue]=useState(false)
  const [quickFilter,setQuickFilter]=useState('all')
  const [sortBy,setSortBy]=useState('overdue')
  const [search,setSearch]=useState('')
  const [expanded,setExpanded]=useState<Record<string,boolean>>({})
  const [err,setErr]=useState('')
  const [message,setMessage]=useState('')

  async function load(){
    try{
      setErr('')
      const [rows,userRows]:any=await Promise.all([api('/actions/admin/pending-by-user'),api('/masters/users')])
      setGroups(rows); setUsers(userRows)
    }catch(e:any){setErr(e.message)}
  }
  useEffect(()=>{load()},[])

  const visible=useMemo(()=>groups.filter(g=>
    !selectedUsers.length||selectedUsers.includes(String(g.user_id??'unassigned'))
  ).map(g=>({
    ...g,
    actions:[...g.actions].filter((a:any)=>{
      if(onlyOverdue&&!a.overdue)return false
      if(quickFilter==='overdue'&&!a.overdue)return false
      if(quickFilter==='critical'&&!['HIGH','CRITICAL'].includes(a.priority))return false
      if(quickFilter==='incomplete'&&Number(a.whywhy_completion_percent??0)>=100)return false
      if(quickFilter==='unassigned'&&a.owner_id!=null)return false
      if(quickFilter==='stale'&&a.followup_age_days!=null&&a.followup_age_days<=7)return false
      return !search||String([a.action_no,a.problem_description,a.action_description].join(' ')).toLowerCase().includes(search.toLowerCase())
    }).sort((a:any,b:any)=>{
      const ranks:Record<string,number>={CRITICAL:4,HIGH:3,MEDIUM:2,LOW:1}
      if(sortBy==='priority')return (ranks[b.priority]||0)-(ranks[a.priority]||0)
      if(sortBy==='completion')return Number(a.whywhy_completion_percent??0)-Number(b.whywhy_completion_percent??0)
      if(sortBy==='followup')return (b.followup_age_days??999999)-(a.followup_age_days??999999)
      if(sortBy==='due')return String(a.due_at||'9999').localeCompare(String(b.due_at||'9999'))
      return Number(b.days_overdue||0)-Number(a.days_overdue||0)
    })
  })).filter(g=>g.actions.length),[groups,selectedUsers,onlyOverdue,quickFilter,sortBy,search])

  function exportExcelCsv(){
    const rows:any[][]=[['User','Action','Problem','Immediate Action','Priority','Status','Due IST','Days Overdue','Age Days','Why-Why %','Last Follow-up IST','Follow-up Age Days']]
    visible.forEach(g=>g.actions.forEach((a:any)=>rows.push([g.full_name,a.action_no,a.problem_description,a.action_description,a.priority,a.status,a.due_at?formatIST(a.due_at):'',a.days_overdue??0,a.age_days??0,a.whywhy_completion_percent??0,a.last_followup_at?formatIST(a.last_followup_at):'',a.followup_age_days??'Never'])))
    const csv='\uFEFF'+rows.map(row=>row.map(v=>'"'+String(v??'').replace(/^[=+@-]/,'\t$&').replace(/"/g,'""')+'"').join(',')).join('\r\n')
    const url=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8'}))
    const link=document.createElement('a');link.href=url;link.download='User_Action_Review.csv';link.click();URL.revokeObjectURL(url)
  }

  async function updateAction(action:any,patch:any){
    const comment=prompt('Review remark / reason for this update')
    if(comment===null)return
    try{
      await api(`/actions/${action.id}`,{method:'PATCH',body:JSON.stringify({...patch,comment:comment||'Updated during admin action review'})})
      setMessage(`${action.action_no} updated.`)
      await load()
    }catch(e:any){setErr(e.message)}
  }

  const userOptions=[
    ...users.map(u=>({value:String(u.id),label:u.full_name})),
    ...(groups.some(g=>g.user_id===null)?[{value:'unassigned',label:'Unassigned'}]:[])
  ]

  return <>
    <PageHeader title="User-wise Pending Action Review" subtitle="Admin review of every open action owner on one page." actions={<div className="button-row"><MultiSelect value={selectedUsers} onChange={setSelectedUsers} placeholder="All Users" options={userOptions}/><button className="secondary" onClick={exportExcelCsv}>Export to Excel (CSV)</button><button className="secondary" onClick={load}>Refresh</button></div>}/>
    <div className="panel" style={{display:'flex',flexWrap:'wrap',gap:12,alignItems:'end'}}>
      <label>Quick filter<select value={quickFilter} onChange={e=>setQuickFilter(e.target.value)}><option value="all">All pending</option><option value="overdue">Overdue</option><option value="critical">High / Critical</option><option value="incomplete">Why-Why incomplete</option><option value="stale">No follow-up in 7+ days</option><option value="unassigned">Unassigned</option></select></label>
      <label>Sort by<select value={sortBy} onChange={e=>setSortBy(e.target.value)}><option value="overdue">Most overdue</option><option value="priority">Highest priority</option><option value="completion">Lowest completion</option><option value="followup">Oldest follow-up</option><option value="due">Earliest due</option></select></label>
      <label>Find action<input value={search} onChange={e=>setSearch(e.target.value)} placeholder="Action / problem"/></label>
      <label className="inline-check"><input type="checkbox" checked={onlyOverdue} onChange={e=>setOnlyOverdue(e.target.checked)}/> Overdue only</label>
    </div>
    {err&&<div className="error">{err}</div>}{message&&<div className="notice">{message}</div>}
    <div className="kpi-grid">
      <div className="kpi"><span>Users with pending</span><strong>{visible.length}</strong></div>
      <div className="kpi"><span>Open actions</span><strong>{visible.reduce((n,g)=>n+g.actions.length,0)}</strong></div>
      <div className="kpi bad"><span>Overdue</span><strong>{visible.reduce((n,g)=>n+g.actions.filter((a:any)=>a.overdue).length,0)}</strong></div>
      <div className="kpi"><span>Due today</span><strong>{visible.reduce((n,g)=>n+g.actions.filter((a:any)=>a.days_until_due===0).length,0)}</strong></div>
    </div>
    {visible.map(g=>{
      const key=String(g.user_id??'unassigned')
      const open=expanded[key]!==false
      return <section className="panel" key={key}>
        <div className="panel-title"><div><h2>{g.full_name}</h2><p>{g.role||'No owner'} • {g.actions.length} shown • {g.actions.filter((a:any)=>a.overdue).length} overdue • Avg Why-Why {Math.round(g.actions.reduce((s:number,a:any)=>s+Number(a.whywhy_completion_percent??0),0)/g.actions.length)}% • {g.actions.filter((a:any)=>a.followup_age_days==null||a.followup_age_days>7).length} need follow-up</p></div><button className="secondary small" onClick={()=>setExpanded(x=>({...x,[key]:!open}))}>{open?'Collapse':'Review'}</button></div>
        {open&&<div className="table-wrap"><table><thead><tr><th>Action</th><th>Problem / Action</th><th>Target</th><th>Age</th><th>Overdue</th><th>Last follow-up</th><th>Priority</th><th>Status</th><th>Owner</th><th>Update</th><th>Review</th></tr></thead><tbody>
          {g.actions.map((a:any)=><tr key={a.id} className={a.overdue?'row-overdue':''}><td><b>{a.action_no}</b><br/><small>{a.reference_date}</small></td><td><b>{a.problem_description}</b><br/><small>{a.action_description}</small></td><td style={{color:a.days_until_due!=null&&a.days_until_due<0?"#B91C1C":a.days_until_due!=null&&a.days_until_due<=3?"#92400E":undefined,fontWeight:a.days_until_due!=null&&a.days_until_due<=3?600:undefined}}>{a.due_at?formatIST(a.due_at):'—'}{a.days_until_due!=null&&a.days_until_due>=0&&a.days_until_due<=3&&<div><small>{a.days_until_due===0?"Due today":`Due in ${a.days_until_due}d`}</small></div>}</td><td>{a.age_days}d</td><td><strong style={{color:a.days_overdue>0?"#B91C1C":"#166534"}}>{a.days_overdue>0?`${a.days_overdue}d late`:a.due_at?"On time":"No due"}</strong></td><td><strong style={{color:a.followup_age_days==null?"#6B7280":a.followup_age_days>7?"#B91C1C":a.followup_age_days>3?"#92400E":"#166534"}}>{a.followup_age_days==null?"Never":a.followup_age_days===0?"Today":`${a.followup_age_days}d ago`}</strong>{a.last_followup_at&&<div><small>{formatIST(a.last_followup_at)}</small></div>}</td><td><Status value={a.priority}/></td><td><Status value={a.status}/></td><td><MultiSelect singleSelect value={a.owner_id?[String(a.owner_id)]:[]} onChange={v=>updateAction(a,{owner_id:v.at(-1)?Number(v.at(-1)):null})} placeholder="Unassigned" options={users.map(u=>({value:String(u.id),label:u.full_name}))}/></td><td><select value={a.status} onChange={e=>updateAction(a,{status:e.target.value,closure_remark:e.target.value==='CLOSED'?'Closed during admin review':null})}><option>OPEN</option><option>IN_PROGRESS</option><option>BLOCKED</option><option>CLOSED</option></select><input type="date" value={timestampDateIST(a.due_at)} onChange={e=>updateAction(a,{due_at:e.target.value?istLocalToUTC(e.target.value+'T23:59:00'):null})}/></td><td><div><button className="secondary small" onClick={()=>navigate(`/actions?action_id=${a.id}`)}>Open Review</button></div><div style={{display:"flex",justifyContent:"center",marginTop:6}}><span style={{display:"inline-block",border:`1px solid ${Number(a.whywhy_completion_percent ?? 0) === 0 ? "#ADB5BD" : Number(a.whywhy_completion_percent ?? 0) < 50 ? "#F87171" : Number(a.whywhy_completion_percent ?? 0) < 100 ? "#F59E0B" : "#22C55E"}`,backgroundColor:Number(a.whywhy_completion_percent ?? 0) === 0 ? "#F1F3F5" : Number(a.whywhy_completion_percent ?? 0) < 50 ? "#FEE2E2" : Number(a.whywhy_completion_percent ?? 0) < 100 ? "#FEF3C7" : "#DCFCE7",color:Number(a.whywhy_completion_percent ?? 0) === 0 ? "#6B7280" : Number(a.whywhy_completion_percent ?? 0) < 50 ? "#B91C1C" : Number(a.whywhy_completion_percent ?? 0) < 100 ? "#92400E" : "#166534",borderRadius:6,padding:"3px 12px",fontSize:12,fontWeight:600,textAlign:"center"}}>{a.whywhy_completion_percent ?? 0}%</span></div><div style={{height:4,background:"#e5e7eb",borderRadius:4,marginTop:5}}><div style={{height:"100%",width:`${Math.max(0,Math.min(100,Number(a.whywhy_completion_percent??0)))}%`,background:Number(a.whywhy_completion_percent??0)>=100?"#22C55E":Number(a.whywhy_completion_percent??0)>=50?"#F59E0B":"#F87171"}}/></div></td></tr>)}
        </tbody></table></div>}
      </section>
    })}
    {!visible.length&&<div className="empty">No pending actions match the selected filters.</div>}
  </>
}
