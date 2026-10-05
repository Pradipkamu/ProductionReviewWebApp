import { useEffect } from 'react'
import { NavLink } from 'react-router-dom'
import { clearToken, logout } from '../api'
import { canViewPage, navItems } from '../pageAccess'

function CorrectionControls({role}:{role:string}){
 if(role==='VIEW_ONLY')return null
 return <details><summary>Historical correction</summary><label>Change reason<input defaultValue={sessionStorage.getItem('changeReason')||''} onChange={e=>sessionStorage.setItem('changeReason',e.target.value)}/></label><label>Authorization number<input defaultValue={sessionStorage.getItem('correctionId')||''} onChange={e=>sessionStorage.setItem('correctionId',e.target.value)}/></label><p>Authorization is consumed after one successful correction request.</p></details>
}

export default function Layout({ children, me }: { children: React.ReactNode, me:any }) {
  useEffect(()=>{
    const minutes=Math.max(5,Number(me?.session_idle_timeout_minutes||60))
    let timer:number
    const expire=async()=>{try{await logout()}finally{location.reload()}}
    const reset=()=>{window.clearTimeout(timer);timer=window.setTimeout(expire,minutes*60*1000)}
    const events=['mousedown','keydown','touchstart','scroll']
    events.forEach(event=>window.addEventListener(event,reset))
    reset()
    return()=>{window.clearTimeout(timer);events.forEach(event=>window.removeEventListener(event,reset))}
  },[me?.session_idle_timeout_minutes])

  async function signOut(){
    try{await logout()}finally{clearToken();location.reload()}
  }

  const visible=navItems.filter(item=>canViewPage(me,item.key))
  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand"><div className="brand-mark">PR</div><div><b>Production Review</b><span>Process • Sales • Actions</span></div></div>
      <div className="filter-summary"><b>{me?.full_name||me?.username}</b><span>{me?.role}</span></div>
      <nav>{visible.map(({to,label}) => <NavLink key={to} to={to} end={to==='/'} className={({isActive}) => isActive ? 'active' : ''}>{label}</NavLink>)}</nav>
      <button className="ghost danger" onClick={signOut}>Sign out</button>
    </aside>
    <main className="content"><CorrectionControls role={me?.role}/>{children}</main>
  </div>
}
