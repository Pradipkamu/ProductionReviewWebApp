import { useEffect, useState } from 'react'
import { api } from '../api'
import { Kpi, PageHeader, Status } from '../components/UI'

type Machine = { id:number; machine_number:string; machine_name:string; plant:string|null; is_active:boolean; device_registered:boolean }
type Device = { id:number; machine_id:number; machine_number:string; machine_name:string; plant:string|null; device_uid:string; device_name:string|null; device_role:string; hardware_model:string|null; firmware_version:string|null; protocol_version:string; is_active:boolean; status:string; last_seen_at:string|null; notes:string|null }
type TelemetryEvent = { id:number; device_uid:string; machine_id:number; machine_number:string; machine_name:string; event_id:string; event_type:string; sequence:number|null; occurred_at:string; received_at:string; processing_status:string; processing_error:string|null }
type Overview = { machine_master:{total:number;active:number}; devices:{registered:number;enabled:number;online:number}; telemetry:{status:string;last_received_at:string|null;events_received:number}; next_phase:string }
const empty = { machine_id:'', device_uid:'', device_name:'', device_role:'MAIN_CONTROLLER', hardware_model:'ESP32-S3', firmware_version:'', protocol_version:'1.0', notes:'' }

export default function AFMS({me}:{me:any}) {
  const [overview,setOverview]=useState<Overview|null>(null)
  const [machines,setMachines]=useState<Machine[]>([])
  const [devices,setDevices]=useState<Device[]>([])
  const [events,setEvents]=useState<TelemetryEvent[]>([])
  const [form,setForm]=useState({...empty})
  const [secret,setSecret]=useState('')
  const [error,setError]=useState('')
  const [message,setMessage]=useState('')
  const [loading,setLoading]=useState(true)
  const [busy,setBusy]=useState(false)
  const isAdmin=me?.role==='ADMIN'

  async function load(){
    const results:any[] = await Promise.all([api('/afms/overview'),api('/afms/machines'),api('/afms/devices'),api('/afms/events?limit=50')])
    setOverview(results[0]); setMachines(results[1]); setDevices(results[2]); setEvents(results[3]?.events||[])
  }
  useEffect(()=>{
    let active=true
    Promise.all([api('/afms/overview'),api('/afms/machines'),api('/afms/devices'),api('/afms/events?limit=50')])
      .then((results:any[])=>{if(active){setOverview(results[0]);setMachines(results[1]);setDevices(results[2]);setEvents(results[3]?.events||[])}})
      .catch((err:any)=>{if(active)setError(err.message||'Unable to load AFMS workspace')})
      .finally(()=>{if(active)setLoading(false)})
    return()=>{active=false}
  },[])

  async function register(e:React.FormEvent){
    e.preventDefault();setBusy(true);setError('');setMessage('');setSecret('')
    try{
      const result:any=await api('/afms/devices',{method:'POST',body:JSON.stringify({...form,machine_id:Number(form.machine_id)})})
      setSecret(result.provisioning_secret)
      setMessage('Device registered and linked to the selected PRW machine. Save the provisioning credential securely.')
      setForm({...empty});await load()
    }catch(err:any){setError(err.message)}finally{setBusy(false)}
  }
  async function toggle(device:Device){
    setBusy(true);setError('');setMessage('')
    try{await api('/afms/devices/'+device.id,{method:'PATCH',body:JSON.stringify({is_active:!device.is_active})});setMessage('Device '+device.device_uid+' updated.');await load()}
    catch(err:any){setError(err.message)}finally{setBusy(false)}
  }
  async function rotate(device:Device){
    if(!window.confirm('Rotate credentials for '+device.device_uid+'? The old credential will stop working immediately.'))return
    setBusy(true);setError('');setMessage('');setSecret('')
    try{const result:any=await api('/afms/devices/'+device.id+'/rotate-credential',{method:'POST'});setSecret(result.provisioning_secret);setMessage('Credential rotated. Update the ESP32 securely now.')}
    catch(err:any){setError(err.message)}finally{setBusy(false)}
  }

  return <>
    <PageHeader title='AFMS – Machine & HMI' subtitle='Device registry linked to the existing PRW machine master. Machine number and database ID are retained for future cycle-event attribution.'/>
    {error&&<div className='warning-box'>{error}</div>}
    {message&&<div className='notice'>{message}</div>}
    {secret&&<section className='panel'><h2>One-time device credential</h2><p>Copy this value now and provision it into the matching ESP32 using a secure local method. It cannot be displayed again.</p><div className='field'><input readOnly value={secret}/><button type='button' className='secondary' onClick={()=>navigator.clipboard?.writeText(secret)}>Copy credential</button></div></section>}
    {loading?<div className='panel'>Loading AFMS workspace…</div>:overview&&<>
      <div className='kpi-grid'>
        <Kpi label='PRW machines' value={overview.machine_master.total} sub='Existing machines table'/>
        <Kpi label='Registered devices' value={overview.devices.registered}/>
        <Kpi label='Enabled devices' value={overview.devices.enabled}/>
        <Kpi label='Online devices' value={overview.devices.online} sub='Heartbeat within 2 minutes'/>
        <Kpi label='Telemetry events' value={overview.telemetry.events_received} sub={overview.telemetry.status.replaceAll('_',' ')}/>
      </div>
      {isAdmin&&<section className='panel'>
        <h2>Register ESP32 / HMI device</h2>
        <p>Select the machine from PRW Machine Master. The machine database ID and machine number are stored with this controller mapping.</p>
        <form onSubmit={register}><div className='machine-field-grid'>
          <label>PRW machine *<select required value={form.machine_id} onChange={e=>setForm({...form,machine_id:e.target.value})}><option value=''>Select machine</option>{machines.filter(m=>m.is_active&&!devices.some(d=>d.machine_id===m.id&&d.is_active)).map(m=><option key={m.id} value={m.id}>{m.machine_number} — {m.machine_name}{m.plant?' ('+m.plant+')':''}</option>)}</select></label>
          <label>Device UID / ESP32 ID *<input required minLength={3} maxLength={100} pattern='[A-Za-z0-9._:-]+' value={form.device_uid} onChange={e=>setForm({...form,device_uid:e.target.value})} placeholder='ESP32 MAC or provisioned unique ID'/></label>
          <label>Device display name<input maxLength={120} value={form.device_name} onChange={e=>setForm({...form,device_name:e.target.value})} placeholder='Machine 01 HMI'/></label>
          <label>Device role<select value={form.device_role} onChange={e=>setForm({...form,device_role:e.target.value})}><option value='MAIN_CONTROLLER'>Main controller</option><option value='HMI'>HMI</option><option value='SENSOR_NODE'>Sensor node</option></select></label>
          <label>Hardware model<input maxLength={120} value={form.hardware_model} onChange={e=>setForm({...form,hardware_model:e.target.value})}/></label>
          <label>Firmware version<input maxLength={80} value={form.firmware_version} onChange={e=>setForm({...form,firmware_version:e.target.value})}/></label>
          <label>Protocol version<input required maxLength={30} value={form.protocol_version} onChange={e=>setForm({...form,protocol_version:e.target.value})}/></label>
          <label>Notes<input maxLength={500} value={form.notes} onChange={e=>setForm({...form,notes:e.target.value})}/></label>
        </div><p><button disabled={busy||!machines.some(m=>m.id===Number(form.machine_id)&&m.is_active)}>{busy?'Saving…':'Register device'}</button></p></form>
      </section>}
      <section className='panel'>
        <h2>Registered device mapping</h2>
        <p>Machine number is the existing <b>machines.code</b>; machine database ID is <b>machines.id</b>. Both are returned by the registry and will be carried into future cycle records.</p>
        <div className='table-wrap'><table><thead><tr><th>Machine no.</th><th>Machine name</th><th>DB ID</th><th>Device UID</th><th>Role / Hardware</th><th>Firmware</th><th>Connection</th><th>Last seen</th>{isAdmin&&<th>Admin</th>}</tr></thead>
          <tbody>{devices.map(d=><tr key={d.id}><td><b>{d.machine_number}</b></td><td>{d.machine_name}</td><td>{d.machine_id}</td><td>{d.device_uid}</td><td>{d.device_role}<br/><small>{d.hardware_model||'—'}</small></td><td>{d.firmware_version||'—'}</td><td><Status value={d.status.replaceAll('_',' ')}/></td><td>{d.last_seen_at?new Date(d.last_seen_at).toLocaleString():'Never'}</td>{isAdmin&&<td><button type='button' className='small secondary' disabled={busy} onClick={()=>toggle(d)}>{d.is_active?'Deactivate':'Activate'}</button> <button type='button' className='small secondary' disabled={busy||!d.is_active} onClick={()=>rotate(d)}>Rotate key</button></td>}</tr>)}
          {!devices.length&&<tr><td colSpan={isAdmin?9:8}>No ESP32/HMI devices registered yet.</td></tr>}</tbody>
        </table></div>
      </section>

      <section className='panel'>
        <h2>Latest telemetry events</h2>
        <p>Events are acknowledged only after the raw event is committed. Pending mapping or validation events remain stored for review and are not silently discarded.</p>
        <div className='table-wrap'><table><thead><tr><th>Received</th><th>Machine</th><th>Device UID</th><th>Event</th><th>Sequence</th><th>Processing</th><th>Details</th></tr></thead>
          <tbody>{events.map(event=><tr key={event.id}>
            <td>{new Date(event.received_at).toLocaleString()}</td>
            <td><b>{event.machine_number}</b><br/><small>{event.machine_name}</small></td>
            <td>{event.device_uid}</td><td>{event.event_type}</td><td>{event.sequence??'—'}</td>
            <td><Status value={event.processing_status.replaceAll('_',' ')}/></td>
            <td>{event.processing_error||'—'}</td>
          </tr>)}
          {!events.length&&<tr><td colSpan={7}>No telemetry events received yet.</td></tr>}</tbody>
        </table></div>
      </section>
      <section className='panel'><h2>Cycle-data identity design</h2><p>Each future cycle event will be linked using <b>device_id</b> and <b>machine_id</b>, with the machine number (<b>machines.code</b>) stored as a snapshot. This prevents later machine-master edits from changing the identity on historical cycle records.</p></section>
    </>}
  </>
}
