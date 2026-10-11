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

  const visible=useMemo(()=>groups.filter(g=>{
    if(selectedUsers.length&&!selectedUsers.includes(String(g.user_id??'unassigned')))return false
    if(onlyOverdue&&!g.overdue_count)return false
    return true
  }),[groups,selectedUsers,onlyOverdue])

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
    <PageHeader title="User-wise Pending Action Review" subtitle="Admin review of every open action owner on one page." actions={<div className="button-row"><MultiSelect value={selectedUsers} onChange={setSelectedUsers} placeholder="All Users" options={userOptions}/><label className="inline-check"><input type="checkbox" checked={onlyOverdue} onChange={e=>setOnlyOverdue(e.target.checked)}/> Overdue only</label><button className="secondary" onClick={load}>Refresh</button></div>}/>
    {err&&<div className="error">{err}</div>}{message&&<div className="notice">{message}</div>}
    <div className="kpi-grid">
      <div className="kpi"><span>Users with pending</span><strong>{visible.length}</strong></div>
      <div className="kpi"><span>Open actions</span><strong>{visible.reduce((n,g)=>n+g.open_count,0)}</strong></div>
      <div className="kpi bad"><span>Overdue</span><strong>{visible.reduce((n,g)=>n+g.overdue_count,0)}</strong></div>
      <div className="kpi"><span>Due today</span><strong>{visible.reduce((n,g)=>n+g.due_today_count,0)}</strong></div>
    </div>
    {visible.map(g=>{
      const key=String(g.user_id??'unassigned')
      const open=expanded[key]!==false
      return <section className="panel" key={key}>
        <div className="panel-title"><div><h2>{g.full_name}</h2><p>{g.role||'No owner'} • {g.open_count} open • {g.overdue_count} overdue • {g.due_today_count} due today • oldest {g.oldest_age_days}d</p></div><button className="secondary small" onClick={()=>setExpanded(x=>({...x,[key]:!open}))}>{open?'Collapse':'Review'}</button></div>
        {open&&<div className="table-wrap"><table><thead><tr><th>Action</th><th>Problem / Action</th><th>Target</th><th>Age</th><th>Priority</th><th>Status</th><th>Owner</th><th>Update</th><th>Review</th></tr></thead><tbody>
          {g.actions.filter((a:any)=>!onlyOverdue||a.overdue).map((a:any)=><tr key={a.id} className={a.overdue?'row-overdue':''}><td><b>{a.action_no}</b><br/><small>{a.reference_date}</small></td><td><b>{a.problem_description}</b><br/><small>{a.action_description}</small></td><td>{a.due_at?formatIST(a.due_at):'—'}</td><td>{a.age_days}d</td><td><Status value={a.priority}/></td><td><Status value={a.status}/></td><td><MultiSelect singleSelect value={a.owner_id?[String(a.owner_id)]:[]} onChange={v=>updateAction(a,{owner_id:v.at(-1)?Number(v.at(-1)):null})} placeholder="Unassigned" options={users.map(u=>({value:String(u.id),label:u.full_name}))}/></td><td><select value={a.status} onChange={e=>updateAction(a,{status:e.target.value,closure_remark:e.target.value==='CLOSED'?'Closed during admin review':null})}><option>OPEN</option><option>IN_PROGRESS</option><option>BLOCKED</option><option>CLOSED</option></select><input type="date" value={timestampDateIST(a.due_at)} onChange={e=>updateAction(a,{due_at:e.target.value?istLocalToUTC(e.target.value+'T23:59:00'):null})}/></td><td><div><button className="secondary small" onClick={()=>navigate(`/actions?action_id=${a.id}`)}>Open Review</button></div><div style={{display:"flex",justifyContent:"center",marginTop:6}}><span style={{display:"inline-block",border:"1px solid var(--border, #b8c2cc)",borderRadius:6,padding:"3px 12px",fontSize:12,fontWeight:600,textAlign:"center"}}>{a.whywhy_completion_percent ?? 0}%</span></div></td></tr>)}
        </tbody></table></div>}
      </section>
    })}
    {!visible.length&&<div className="empty">No pending actions match the selected filters.</div>}
  </>
}
