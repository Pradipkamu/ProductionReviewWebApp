import { useEffect, useState } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import { clearToken, logout } from '../api'
import { canViewPage, navItems } from '../pageAccess'

const groups=[
  {label:'Communication',keys:['chat']},
  {label:'Executive & Review',keys:['control_tower','dispatch_intelligence','capacity_intelligence','operations_intelligence','management_assistant','daily_review','daily_meeting','insights']},
  {label:'Quality & Rejection',keys:['quality','casting_quality','customer_quality']},
  {label:'Fault Tree Analysis',keys:['fta']},
  {label:'Actions & Reviews',keys:['actions','admin_action_review']},
  {label:'Planning & Production',keys:['mis','schedule','capacity','machine_master','product_master','process','process_actuals','vendor']},
  {label:'OEE & Automation',keys:['oee','afms']},
  {label:'Reports & Analytics',keys:['reports','oee_reports','management_reports','analytics']},
  {label:'Administration',keys:['masters','import','diagnostics','governance','account']},
]

const groupIcons:Record<string,string>={Communication:"M4 5h16v12H8l-4 4V5z","Executive & Review":"M3 3h18v18H3z M8 8h8 M8 12h8 M8 16h5","Quality & Rejection":"M12 3l8 4v5c0 5-3.5 8-8 10-4.5-2-8-5-8-10V7l8-4z M8.5 12l2.2 2.2 4.8-5","Fault Tree Analysis":"M12 4v5m0 0H6v5m6-5h6v5M6 14v4m12-4v4","Actions & Reviews":"M5 3h14v18H5z M8 8h8 M8 12h8 M8 16h5","Planning & Production":"M3 21V9l9-6 9 6v12M8 21v-7h8v7","OEE & Automation":"M12 3a9 9 0 1 0 9 9 M12 7v5l4 2 M19 3v5h-5","Reports & Analytics":"M4 19V5m0 14h17 M8 16v-5m5 5V7m5 9v-8",Administration:"M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8z M4 12H2m20 0h-2M12 4V2m0 20v-2M5 5l1.5 1.5m11 11L19 19m0-14-1.5 1.5m-11 11L5 19"};
function GroupIcon({label}:{label:string}){return <svg className="nav-group-icon" viewBox="0 0 24 24" aria-hidden="true"><path d={groupIcons[label]||"M4 4h16v16H4z"}/></svg>}

function CorrectionControls({role}:{role:string}){
 if(role==='VIEW_ONLY')return null
 return <details className="correction-controls"><summary>Historical correction controls</summary><div className="correction-grid"><label>Change reason<input defaultValue={sessionStorage.getItem('changeReason')||''} onChange={e=>sessionStorage.setItem('changeReason',e.target.value)}/></label><label>Authorization number<input defaultValue={sessionStorage.getItem('correctionId')||''} onChange={e=>sessionStorage.setItem('correctionId',e.target.value)}/></label></div><p>Use only for authorized historical corrections. Authorization is consumed after one successful correction request.</p></details>
}

export default function Layout({ children, me }: { children: React.ReactNode, me:any }) {
  const [menuOpen,setMenuOpen]=useState(false)
  const [apiError,setApiError]=useState<{message:string;status?:number;path?:string}|null>(null)
  const routeLocation=useLocation()
  useEffect(()=>setMenuOpen(false),[routeLocation.pathname])
  useEffect(()=>{
    const showError=(event:Event)=>{const detail=(event as CustomEvent).detail||{};setApiError({message:String(detail.message||'The request could not be completed.'),status:detail.status,path:detail.path})}
    window.addEventListener('app:api-error',showError)
    return()=>window.removeEventListener('app:api-error',showError)
  },[])
  useEffect(()=>{
    if(!apiError)return
    const onKey=(event:KeyboardEvent)=>{if(event.key==='Escape')setApiError(null)}
    window.addEventListener('keydown',onKey)
    return()=>window.removeEventListener('keydown',onKey)
  },[apiError])
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

  const visible=[{key:'chat',to:'/chat',label:'Chat'},...navItems].filter(item=>item.key==='chat'||canViewPage(me,item.key))
  const currentNav=navItems.find(item=>item.to===routeLocation.pathname)
    || navItems.find(item=>item.to!=='/'&&routeLocation.pathname.startsWith(item.to+'/'))
  const currentLabel=routeLocation.pathname==='/inspection-measurements'?'Inspection Measurements'
    :routeLocation.pathname==='/quality-salvage'?'Rejection Salvage'
    :routeLocation.pathname==='/admin-action-review'?'User-wise Action Review'
    :routeLocation.pathname==='/casting-quality'?'Casting Quality'
    :routeLocation.pathname==='/customer-quality'?'Customer Quality'
    :routeLocation.pathname==='/'?'Daily Production Control':currentNav?.label||'Workspace'
  const currentGroup=groups.find(group=>group.keys.includes(currentNav?.key||(
    routeLocation.pathname==='/quality-salvage'?'quality':
    routeLocation.pathname==='/admin-action-review'?'admin_action_review':
    routeLocation.pathname==='/casting-quality'?'casting_quality':
    routeLocation.pathname==='/customer-quality'?'customer_quality':''
  )))?.label||'Workspace'
  return <div className="app-shell">
    <a className="skip-link" href="#main-content">Skip to content</a>
    <button className="mobile-menu-button" aria-label="Open navigation" aria-expanded={menuOpen} onClick={()=>setMenuOpen(v=>!v)}>{menuOpen?'×':'☰'}<span>Menu</span></button>
    {menuOpen&&<button className="sidebar-backdrop" aria-label="Close navigation" onClick={()=>setMenuOpen(false)}/>}
    <aside className={`sidebar ${menuOpen?'open':''}`}>
      <div className="brand"><img className="brand-mark" src="/app-icon.svg" alt="Machine Shop Operations"/><div className="brand-copy"><b>PRODUCTION REVIEW</b><span>MANAGEMENT SYSTEM</span></div></div>
      <div className="user-card"><div className="user-avatar">{String(me?.full_name||me?.username||'U').slice(0,1).toUpperCase()}</div><div><b>{me?.full_name||me?.username}</b><span>{String(me?.role||'').replaceAll('_',' ')}</span></div></div>
      <nav aria-label="Primary navigation">{groups.map(group=>{const items=visible.filter(item=>group.keys.includes(item.key));if(!items.length)return null;return <details className="nav-group" key={group.label} open={group.keys.includes(currentNav?.key||'chat')}><summary className="nav-group-label"><GroupIcon label={group.label}/><span className="nav-group-title">{group.label}</span><span className="nav-chevron" aria-hidden="true">⌄</span></summary>{items.map(({to,label}) => <NavLink key={to} to={to} end={to==='/'} className={({isActive}) => isActive ? 'active' : ''}>{label}</NavLink>)}</details>})}</nav>
      <button className="ghost danger sign-out" onClick={signOut}>Sign out</button>
    </aside>
    <main className="content" id="main-content" tabIndex={-1}>
      <header className="app-topbar">
        <div className="app-breadcrumb" aria-label="Breadcrumb">
          <span className="app-breadcrumb-root">WORKSPACE</span><span className="app-breadcrumb-separator">/</span>
          <span className="app-breadcrumb-group">{currentGroup}</span><span className="app-breadcrumb-separator">/</span>
          <strong>{currentLabel}</strong>
        </div>
        <div className="app-topbar-profile">
          <span className="app-environment"><i/>Operational workspace</span>
        </div>
      </header>
      <CorrectionControls role={me?.role}/>{children}
      {apiError&&<div className="global-error-backdrop" role="presentation" onMouseDown={event=>{if(event.target===event.currentTarget)setApiError(null)}}><section className="global-error-dialog" role="alertdialog" aria-modal="true" aria-labelledby="global-error-title"><header><span className="global-error-symbol">!</span><div><h2 id="global-error-title">Unable to complete request</h2><p>{apiError.status?`Request failed (${apiError.status})`:'Please review the details below.'}</p></div><button type="button" className="global-error-close" aria-label="Close error" onClick={()=>setApiError(null)}>×</button></header><div className="global-error-message">{apiError.message}</div>{apiError.path&&<p className="global-error-path">Reference: {apiError.path}</p>}<footer><button type="button" onClick={()=>setApiError(null)}>Close</button></footer></section></div>}
    </main>
  </div>
}
