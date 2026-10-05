import { useEffect, useState } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { api, getToken, login, setToken } from './api'
import Layout from './components/Layout'
import Dashboard from './pages/Dashboard'
import MIS from './pages/MIS'
import Schedule from './pages/Schedule'
import Process from './pages/Process'
import ProcessActuals from './pages/ProcessActuals'
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
import Diagnostics from './pages/Diagnostics'
import CapacityPlanning from './pages/CapacityPlanning'
import MachineMaster from './pages/MachineMaster'
import { CastingQuality, CustomerQuality } from './pages/SpecialQuality'
import { canViewPage, firstVisiblePath } from './pageAccess'

function PageGate({me,pageKey,children}:{me:any,pageKey:string,children:React.ReactNode}){
  return canViewPage(me,pageKey)?children:<Navigate to={firstVisiblePath(me)} replace/>
}

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
  const page=(pageKey:string,element:React.ReactNode)=><PageGate me={me} pageKey={pageKey}>{element}</PageGate>
  return <Layout me={me}><Routes>
    <Route path="/" element={page('daily_review',<Dashboard/>)}/><Route path="/mis" element={page('mis',<MIS/>)}/><Route path="/schedule" element={page('schedule',<Schedule/>)}/>
    <Route path="/process" element={page('process',<Process/>)}/><Route path="/process-actuals" element={page('process_actuals',<ProcessActuals/>)}/><Route path="/capacity" element={page('capacity',<CapacityPlanning/>)}/><Route path="/machine-master" element={page('machine_master',<MachineMaster/>)}/><Route path="/quality" element={page('quality',<Quality/>)}/><Route path="/casting-quality" element={page('casting_quality',<CastingQuality/>)}/><Route path="/customer-quality" element={page('customer_quality',<CustomerQuality/>)}/><Route path="/reports" element={page('reports',<Reports/>)}/><Route path="/management-reports" element={page('management_reports',<AdvancedReports/>)}/><Route path="/actions" element={page('actions',<Actions/>)}/><Route path="/vendor" element={page('vendor',<Vendor/>)}/><Route path="/oee" element={page('oee',<OEE/>)}/><Route path="/analytics" element={page('analytics',<Analytics/>)}/>
    <Route path="/insights" element={page('insights',<Insights/>)}/><Route path="/diagnostics" element={page('diagnostics',<Diagnostics/>)}/><Route path="/account" element={page('account',<Security/>)}/><Route path="/governance" element={page('governance',<Governance/>)}/><Route path="/masters" element={page('masters',<Masters/>)}/><Route path="/import" element={page('import',<ImportExcel/>)}/><Route path="*" element={<Navigate to={firstVisiblePath(me)} replace/>}/>
  </Routes></Layout>
}
