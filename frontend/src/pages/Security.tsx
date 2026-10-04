import { useEffect, useState } from 'react'
import { api, clearToken, setToken } from '../api'
import { Kpi, PageHeader } from '../components/UI'

function stamp(v:any){
 if(!v)return '—'
 return String(v).replace('T',' ').slice(0,16)
}

export function PasswordForm({required=false}:{required?:boolean}) {
 const [current,setCurrent]=useState(''),[password,setPassword]=useState(''),[error,setError]=useState('')
 async function submit(e:React.FormEvent){
  e.preventDefault()
  try{
   const r:any=await api('/auth/change-password',{method:'POST',body:JSON.stringify({current_password:current,new_password:password})})
   setToken(r.access_token);location.reload()
  }catch(e:any){setError(e.message)}
 }
 return <section className="panel"><h2>{required?'Change your initial password':'Change password'}</h2><p>Use at least 12 characters with uppercase, lowercase, a number and a symbol.</p><form onSubmit={submit}><label>Current password<input required type="password" autoComplete="current-password" value={current} onChange={e=>setCurrent(e.target.value)}/></label><label>New password<input required type="password" autoComplete="new-password" minLength={12} value={password} onChange={e=>setPassword(e.target.value)}/></label>{error&&<p className="error">{error}</p>}<button>Change password</button></form></section>
}

export default function Security(){
 const [users,setUsers]=useState<any[]>([]),[me,setMe]=useState<any>(null),[status,setStatus]=useState<any>(null)
 const [sessions,setSessions]=useState<any[]>([]),[events,setEvents]=useState<any[]>([])
 const [error,setError]=useState(''),[message,setMessage]=useState('')
 const [form,setForm]=useState({username:'',full_name:'',password:'',role:'VIEW_ONLY'})
 const roles=['ADMIN','PRODUCTION','QUALITY','PLANNING','MANAGEMENT','VIEW_ONLY','PURCHASE','DISPATCH','VENDOR']

 async function load(){
  try{
   setError('')
   const m:any=await api('/auth/me');setMe(m)
   const requests:Promise<any>[]=[api('/auth/security-status'),api(`/auth/sessions?all_users=${m.role==='ADMIN'}`)]
   const [s,ss]=await Promise.all(requests);setStatus(s);setSessions(ss)
   if(m.role==='ADMIN')setUsers(await api('/masters/users'))
   if(['ADMIN','MANAGEMENT'].includes(m.role))setEvents(await api('/auth/security-events?limit=150'))
  }catch(e:any){setError(e.message)}
 }
 useEffect(()=>{load()},[])

 async function create(e:React.FormEvent){
  e.preventDefault();setMessage('')
  try{
   await api('/masters/users',{method:'POST',body:JSON.stringify(form)})
   setForm({...form,username:'',full_name:'',password:''});setMessage('User created. Initial password must be changed at first sign-in.');load()
  }catch(e:any){setError(e.message)}
 }
 async function update(u:any,role:string,active:boolean){
  const reason=prompt('Reason for account change');if(!reason)return
  try{await api(`/auth/users/${u.id}`,{method:'PATCH',body:JSON.stringify({role,is_active:active,reason})});setMessage('User permissions updated and existing sessions revoked.');load()}catch(e:any){setError(e.message)}
 }
 async function reset(u:any){
  const password=prompt('Temporary password (12+ characters, upper/lower/number/symbol)');if(!password)return
  const reason=prompt('Reason for password reset');if(!reason)return
  try{await api(`/auth/users/${u.id}/reset-password`,{method:'POST',body:JSON.stringify({temporary_password:password,reason})});setMessage('Password reset. All existing sessions were revoked.');load()}catch(e:any){setError(e.message)}
 }
 async function revoke(s:any){
  if(!confirm(`Revoke this session${s.username?' for '+s.username:''}?`))return
  try{
   const r:any=await api(`/auth/sessions/${s.id}`,{method:'DELETE'})
   if(r.current_session){clearToken();location.reload();return}
   setMessage('Session revoked.');load()
  }catch(e:any){setError(e.message)}
 }

 return <><PageHeader title="Security & User Administration" subtitle="Account security, role control, active sessions and sign-in audit. Backend permissions remain authoritative even when a page is visible."/>
  {error&&<p className="error">{error}</p>}{message&&<div className="notice">{message}</div>}
  {status&&<section className="panel">
   <div className="panel-title"><div><h2>Security Status</h2><p>Oracle HTTP remains supported. HTTPS enforcement is intentionally disabled until TLS is working.</p></div><span className={`status ${status.transport==='HTTPS'?'good':'watch'}`}>{status.transport}</span></div>
   {status.transport!=='HTTPS'&&<div className="warning-box"><b>HTTP mode:</b> login and application traffic are not encrypted in transit. The application will continue to work on Oracle, but avoid exposing it broadly to the public internet until HTTPS or a VPN/reverse proxy is configured.</div>}
   <div className="kpi-grid">
    <Kpi label="Transport" value={status.transport} tone={status.transport==='HTTPS'?'good':'warn'}/>
    <Kpi label="Idle logout" value={`${status.session_idle_timeout_minutes} min`}/>
    <Kpi label="Absolute session" value={`${status.access_token_expire_minutes} min`}/>
    <Kpi label="Login lockout" value={`${status.login_max_failures} fails / ${status.login_lock_minutes} min`}/>
   </div>
  </section>}

  <PasswordForm/>

  <section className="panel">
   <div className="panel-title"><div><h2>Active / Recent Sessions</h2><p>{me?.role==='ADMIN'?'Administrator view of user sessions.':'Your current and recent sessions.'}</p></div><button className="small secondary" onClick={load}>Refresh</button></div>
   <div className="table-wrap"><table><thead><tr><th>User</th><th>Created</th><th>Last Seen</th><th>Expires</th><th>IP</th><th>Client</th><th>Status</th><th></th></tr></thead><tbody>
    {sessions.map(s=><tr key={s.id}><td>{s.username||me?.username}{s.is_current&&<><br/><small>Current session</small></>}</td><td>{stamp(s.created_at)}</td><td>{stamp(s.last_seen_at)}</td><td>{stamp(s.expires_at)}</td><td>{s.ip_address||'—'}</td><td><small>{s.user_agent||'—'}</small></td><td><span className={`status ${s.revoked_at?'bad':'good'}`}>{s.revoked_at?'REVOKED':'ACTIVE'}</span></td><td>{!s.revoked_at&&<button className="small danger" onClick={()=>revoke(s)}>Revoke</button>}</td></tr>)}
    {!sessions.length&&<tr><td colSpan={8} className="muted">No sessions found.</td></tr>}
   </tbody></table></div>
  </section>

  {['ADMIN','MANAGEMENT'].includes(me?.role)&&<section className="panel">
   <div className="panel-title"><div><h2>Login / Security Audit</h2><p>Latest successful and failed sign-ins, lockouts, password changes and session revocations.</p></div></div>
   <div className="table-wrap"><table><thead><tr><th>Time</th><th>Event</th><th>User</th><th>Result</th><th>IP</th><th>Detail</th></tr></thead><tbody>
    {events.map(e=><tr key={e.id}><td>{stamp(e.occurred_at)}</td><td>{e.event_type}</td><td>{e.username||'—'}</td><td><span className={`status ${e.success?'good':'bad'}`}>{e.success?'SUCCESS':'FAILED'}</span></td><td>{e.ip_address||'—'}</td><td>{e.detail||'—'}</td></tr>)}
    {!events.length&&<tr><td colSpan={6} className="muted">No security events recorded yet.</td></tr>}
   </tbody></table></div>
  </section>}

  {me?.role==='ADMIN'&&<><section className="panel"><h2>Users & Roles</h2><div className="table-wrap"><table><thead><tr><th>Name</th><th>Role</th><th>Active</th><th>Last Login</th><th>Lock</th><th>Password</th></tr></thead><tbody>{users.map(u=><tr key={u.id}><td>{u.full_name}<br/><small>{u.username}</small></td><td><select value={u.role} onChange={e=>update(u,e.target.value,u.is_active)}>{roles.map(r=><option key={r}>{r}</option>)}</select></td><td><input type="checkbox" checked={u.is_active} onChange={e=>update(u,u.role,e.target.checked)}/></td><td>{stamp(u.last_login_at)}</td><td>{u.locked_until?<span className="status bad">Until {stamp(u.locked_until)}</span>:<span className="status good">OK</span>}<br/><small>{u.failed_login_attempts||0} failed</small></td><td><button onClick={()=>reset(u)}>Reset</button></td></tr>)}</tbody></table></div></section>
   <section className="panel"><h2>Create User</h2><p>New accounts are forced to change their temporary password on first sign-in.</p><form onSubmit={create}>{['username','full_name','password'].map(k=><label key={k}>{k.replace('_',' ')}<input required type={k==='password'?'password':'text'} minLength={k==='password'?12:undefined} value={(form as any)[k]} onChange={e=>setForm({...form,[k]:e.target.value})}/></label>)}<label>Role<select value={form.role} onChange={e=>setForm({...form,role:e.target.value})}>{roles.map(r=><option key={r}>{r}</option>)}</select></label><button>Create user</button></form></section></>}
 </>
}
