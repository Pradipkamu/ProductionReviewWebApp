import { useEffect, useState } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { api, getToken, login, setToken } from './api'
import Layout from './components/Layout'
import Dashboard from './pages/Dashboard'
import MIS from './pages/MIS'
import Schedule from './pages/Schedule'
import Process from './pages/Process'
import Actions from './pages/Actions'
import OEE from './pages/OEE'
import Vendor from './pages/Vendor'
import Analytics from './pages/Analytics'
import Reports from './pages/Reports'
import AdvancedReports from './pages/AdvancedReports'
import Masters from './pages/Masters'
import ImportExcel from './pages/ImportExcel'
import Quality from './pages/Quality'
import Security, { PasswordForm } from './pages/Security'
import Governance from './pages/Governance'
import Insights from './pages/Insights'
import ShopCapture from './pages/ShopCapture'

function Login() {
  const [username, setUsername] = useState('admin'); const [password, setPassword] = useState('')
  const [error, setError] = useState(''); const [busy, setBusy] = useState(false)
  async function submit(e: React.FormEvent) { e.preventDefault(); setBusy(true); setError(''); try { const r:any = await login(username,password); setToken(r.access_token); location.reload() } catch(e:any){setError(e.message)} finally {setBusy(false)} }
  return <div className="login-page"><form className="login-card" onSubmit={submit}>
    <div className="brand-mark lg">PR</div><h1>Production Review Manager</h1><p>Daily sales, process, WIP, actions and OEE in one system.</p>
    <label>User name<input value={username} onChange={e=>setUsername(e.target.value)} /></label>
    <label>Password<input type="password" value={password} onChange={e=>setPassword(e.target.value)} /></label>
    {error && <div className="error">{error}</div>}<button disabled={busy}>{busy?'Signing in…':'Sign in'}</button>
  </form></div>
}

export default function App(){
  const [me,setMe]=useState<any>(null)
  useEffect(()=>{if(getToken())api('/auth/me').then(setMe).catch(()=>{})},[])
  if(!getToken()) return <Login />
  if(!me) return <p>Loading account…</p>
  if(me.must_change_password) return <div className="login-page"><PasswordForm required/></div>
  return <Layout><Routes>
    <Route path="/" element={<Dashboard/>}/><Route path="/mis" element={<MIS/>}/><Route path="/schedule" element={<Schedule/>}/>
    <Route path="/process" element={<Process/>}/><Route path="/quality" element={<Quality/>}/><Route path="/reports" element={<Reports/>}/><Route path="/management-reports" element={<AdvancedReports/>}/><Route path="/actions" element={<Actions/>}/><Route path="/vendor" element={<Vendor/>}/><Route path="/oee" element={<OEE/>}/><Route path="/analytics" element={<Analytics/>}/>
    <Route path="/shop-capture" element={<ShopCapture/>}/><Route path="/insights" element={<Insights/>}/><Route path="/account" element={<Security/>}/><Route path="/governance" element={<Governance/>}/><Route path="/masters" element={<Masters/>}/><Route path="/import" element={<ImportExcel/>}/><Route path="*" element={<Navigate to="/"/>}/>
  </Routes></Layout>
}
