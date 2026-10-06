import { useEffect, useState } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import { clearToken, logout } from '../api'
import { canViewPage, navItems } from '../pageAccess'

const groups=[
  {label:'Review',keys:['daily_review','insights','actions']},
  {label:'Planning & Production',keys:['mis','schedule','capacity','machine_master','process','process_actuals','vendor']},
  {label:'Quality & OEE',keys:['quality','casting_quality','customer_quality','oee']},
  {label:'Reports',keys:['reports','management_reports','analytics']},
  {label:'Administration',keys:['masters','import','diagnostics','governance','account']},
]

function CorrectionControls({role}:{role:string}){
 if(role==='VIEW_ONLY')return null
 return <details className="correction-controls"><summary>Historical correction controls</summary><div className="correction-grid"><label>Change reason<input defaultValue={sessionStorage.getItem('changeReason')||''} onChange={e=>sessionStorage.setItem('changeReason',e.target.value)}/></label><label>Authorization number<input defaultValue={sessionStorage.getItem('correctionId')||''} onChange={e=>sessionStorage.setItem('correctionId',e.target.value)}/></label></div><p>Use only for authorized historical corrections. Authorization is consumed after one successful correction request.</p></details>
}

export default function Layout({ children, me }: { children: React.ReactNode, me:any }) {
  const [menuOpen,setMenuOpen]=useState(false)
  const routeLocation=useLocation()
  useEffect(()=>setMenuOpen(false),[routeLocation.pathname])
  useEffect(()=>{
    if(!menuOpen)return
    const previous=document.body.style.overflow
    document.body.style.overflow='hidden'
    const onKey=(event:KeyboardEvent)=>{if(event.key==='Escape')setMenuOpen(false)}
    window.addEventListener('keydown',onKey)
    return()=>{document.body.style.overflow=previous;window.removeEventListener('keydown',onKey)}
  },[menuOpen])
  useEffect(()=>{
    const minutes=Math.max(5,Number(me?.session_idle_timeout_minutes||60))
    let timer:number
    const expire=async()=>{try{await logout()}finally{window.location.reload()}}
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
    <button className="mobile-menu-button" aria-label="Open navigation" aria-expanded={menuOpen} onClick={()=>setMenuOpen(v=>!v)}>{menuOpen?'×':'☰'}<span>Menu</span></button>
    {menuOpen&&<button className="sidebar-backdrop" aria-label="Close navigation" onClick={()=>setMenuOpen(false)}/>}
    <aside className={`sidebar ${menuOpen?'open':''}`}>
      <div className="brand"><div className="brand-mark">PR</div><div><b>Production Review</b><span>Process • Sales • Actions</span></div></div>
      <div className="user-card"><div className="user-avatar">{String(me?.full_name||me?.username||'U').slice(0,1).toUpperCase()}</div><div><b>{me?.full_name||me?.username}</b><span>{String(me?.role||'').replaceAll('_',' ')}</span></div></div>
      <nav aria-label="Primary navigation">{groups.map(group=>{const items=visible.filter(item=>group.keys.includes(item.key));if(!items.length)return null;return <div className="nav-group" key={group.label}><div className="nav-group-label">{group.label}</div>{items.map(({to,label}) => <NavLink key={to} to={to} end={to==='/'} className={({isActive}) => isActive ? 'active' : ''}>{label}</NavLink>)}</div>})}</nav>
      <button className="ghost danger sign-out" onClick={signOut}>Sign out</button>
    </aside>
    <main className="content"><CorrectionControls role={me?.role}/>{children}</main>
  </div>
}
