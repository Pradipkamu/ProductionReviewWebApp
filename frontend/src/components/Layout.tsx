import { NavLink } from 'react-router-dom'
import { clearToken } from '../api'

const nav = [
  ['/', 'Daily Review'], ['/mis', 'MIS'], ['/schedule', 'Schedule / Price / Calendar'], ['/process', 'Process Monitor'], ['/quality', 'Quality / Rejection'],
  ['/reports', 'Compliance Reports'], ['/management-reports', 'Management Reports'], ['/actions', 'Actions'], ['/vendor', 'Vendor WIP'], ['/oee', 'Machine / OEE'], ['/analytics', 'Analytics'], ['/masters', 'Masters'], ['/import', 'Excel Import']
]

export default function Layout({ children }: { children: React.ReactNode }) {
  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand"><div className="brand-mark">PR</div><div><b>Production Review</b><span>Process • Sales • Actions</span></div></div>
      <nav>{nav.map(([to, label]) => <NavLink key={to} to={to} className={({isActive}) => isActive ? 'active' : ''}>{label}</NavLink>)}</nav>
      <button className="ghost danger" onClick={() => { clearToken(); location.reload() }}>Sign out</button>
    </aside>
    <main className="content">{children}</main>
  </div>
}
