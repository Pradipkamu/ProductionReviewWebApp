import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { dateIST } from '../time'
import { api, downloadApi } from '../api'
import { ScopeFilters, ScopeValues, appendScope } from '../components/ScopeFilters'
import { PercentTrendChart, RankedBars } from '../components/Charts'
import { Kpi, PageHeader, num, pct } from '../components/UI'
import { MultiSelect } from '../components/MultiSelect'

function firstDayOfCurrentMonth(){
  const today=dateIST()
  return `${today.slice(0,7)}-01`
}
function csvCell(v:any){const s=String(v??'');return `"${s.replaceAll('"','""')}"`}
function downloadCsv(name:string,rows:any[]){
  if(!rows.length){window.alert('There are no rows to export for the selected filters.');return}
  const keys=Object.keys(rows[0])
  const csv=[keys.map(csvCell).join(','),...rows.map(r=>keys.map(k=>csvCell(r[k])).join(','))].join('\r\n')
  const blob=new Blob([csv],{type:'text/csv;charset=utf-8'})
  const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=name;a.click();URL.revokeObjectURL(url)
}

export default function OEEReports(){
  const [fromDate,setFromDate]=useState(firstDayOfCurrentMonth)
  const [toDate,setToDate]=useState(dateIST())
  const [scope,setScope]=useState<ScopeValues>({plant:[],productGroup:[],customerId:[],productId:[]})
  const [options,setOptions]=useState<any>({plants:[],product_groups:[],customers:[]})
  const [products,setProducts]=useState<any[]>([])
  const [machines,setMachines]=useState<any[]>([])
  const [operators,setOperators]=useState<any[]>([])
  const [lossCategories,setLossCategories]=useState<any[]>([])
  const [lossCategoryIds,setLossCategoryIds]=useState<string[]>([])
  const [lossComponent,setLossComponent]=useState('')
  const [selectedLossCategoryId,setSelectedLossCategoryId]=useState('')
  const [machineId,setMachineId]=useState<string[]>([])
  const [operatorId,setOperatorId]=useState('')
  const [shift,setShift]=useState('')
  const [data,setData]=useState<any>(null)
  const [loss,setLoss]=useState<any>(null)
  const [busy,setBusy]=useState(false)
  const [error,setError]=useState('')
  const [exporting,setExporting]=useState(false)
  const [oeeView,setOeeView]=useState<'machine'|'operator'>('machine')

  useEffect(()=>{
    let active=true
    Promise.all([api('/masters/filter-options'),api('/masters/products'),api('/masters/machines'),api('/personnel'),api('/masters/loss-categories')])
      .then(([o,p,m,people,categories]:any[])=>{if(active){setOptions(o);setProducts(p);setMachines(m);setOperators(people);setLossCategories(categories)}})
      .catch((e:any)=>{if(active)setError(e.message)})
    return()=>{active=false}
  },[])

  const selectedMachineNames=useMemo(()=>machines.filter(m=>machineId.includes(String(m.id))).map(m=>m.name),[machines,machineId])
  const selectedRangeDays=useMemo(()=>{
    if(!fromDate||!toDate||fromDate>toDate)return 0
    const from=Date.parse(`${fromDate}T00:00:00Z`),to=Date.parse(`${toDate}T00:00:00Z`)
    return Number.isFinite(from)&&Number.isFinite(to)?Math.floor((to-from)/86400000)+1:0
  },[fromDate,toDate])
  const showMonthlyLossTrend=selectedRangeDays>31
  const dailyLossTrend=useMemo(()=>{
    const buckets=new Map<string,Map<string,number>>()
    for(const event of loss?.events||[]){
      const date=String(event.date||'')
      if(!date)continue
      const category=String(event.category||'Unclassified')
      const hours=Math.max(0,Number(event.duration_min||0))/60
      const day=buckets.get(date)||new Map<string,number>()
      day.set(category,(day.get(category)||0)+hours)
      buckets.set(date,day)
    }
    return [...buckets.entries()].sort(([a],[b])=>a.localeCompare(b)).map(([date,values])=>{
      const categories=[...values.entries()].map(([category,hours])=>({category,hours}))
      return {date,categories,total_hours:categories.reduce((sum,item)=>sum+item.hours,0)}
    })
  },[loss])
  const dailyLossCategories=useMemo(()=>Array.from(new Set<string>(dailyLossTrend.flatMap(day=>day.categories.map((item:any)=>item.category)))),[dailyLossTrend])
  const monthlyLossTrend=useMemo(()=>{
    const buckets=new Map<string,Map<string,number>>()
    for(const day of dailyLossTrend){
      const month=String(day.date).slice(0,7)
      const values=buckets.get(month)||new Map<string,number>()
      for(const item of day.categories){
        values.set(item.category,(values.get(item.category)||0)+Number(item.hours||0))
      }
      buckets.set(month,values)
    }
    return [...buckets.entries()].sort(([a],[b])=>a.localeCompare(b)).map(([month,values])=>{
      const categories=[...values.entries()].map(([category,hours])=>({category,hours}))
      return {
        month,
        label:new Date(`${month}-01T12:00:00`).toLocaleDateString("en-IN",{month:"short",year:"numeric"}),
        categories,
        total_hours:categories.reduce((sum,item)=>sum+item.hours,0),
      }
    })
  },[dailyLossTrend])
  const lossChartPalette=["#2563eb","#0d9488","#d97706","#7c3aed","#dc2626","#0891b2","#65a30d","#c026d3"]

  useEffect(()=>{
    if(!fromDate||!toDate||fromDate>toDate){setError('From date must be on or before To date.');setData(null);setLoss(null);return}
    let active=true
    setBusy(true);setError('')
    const q=new URLSearchParams({as_of:toDate,from_date:fromDate,months:'24'})
    appendScope(q,scope)
    if(machineId.length)q.set('machine_id',machineId.join(','))
    if(operatorId)q.set('operator_id',operatorId)
    if(shift)q.set('shift',shift)
    const lossQuery=new URLSearchParams(q)
    if(selectedLossCategoryId)lossQuery.set('loss_category_id',selectedLossCategoryId)
    else if(lossCategoryIds.length)lossQuery.set('loss_category_id',lossCategoryIds.join(','))
    if(lossComponent)lossQuery.set('loss_component',lossComponent)
    Promise.all([api(`/reports/oee-trends?${q}`),api(`/reports/loss-pareto?${lossQuery}`)])
      .then(([a,b]:any[])=>{if(active){setData(a);setLoss(b)}})
      .catch((e:any)=>{if(active)setError(e.message)})
      .finally(()=>{if(active)setBusy(false)})
    return()=>{active=false}
  },[fromDate,toDate,scope.plant,scope.productGroup,scope.customerId,scope.productId,machineId,operatorId,shift,lossCategoryIds,lossComponent,selectedLossCategoryId])

  const summary=data?.summary||{}
  const filteredEntries=data?.entries||[]
  const operatorRows=useMemo(()=>{
    const grouped=new Map<string,any[]>()
    for(const entry of filteredEntries){
      const name=String(entry.operator||'Unassigned').trim()||'Unassigned'
      const bucket=grouped.get(name)||[]
      bucket.push(entry)
      grouped.set(name,bucket)
    }
    return [...grouped.entries()].map(([name,rows])=>{
      const planned=rows.reduce((sum,r)=>sum+Math.max(0,Number(r.planned_min||0)),0)
      const run=rows.reduce((sum,r)=>sum+Math.max(0,Number(r.run_min||0)),0)
      const total=rows.reduce((sum,r)=>sum+Number(r.total_count||0),0)
      const good=rows.reduce((sum,r)=>sum+Number(r.good_count||0),0)
      const theoretical=rows.reduce((sum,r)=>sum+(Number(r.ideal_cycle_time_sec||0)*Number(r.total_count||0)/60),0)
      const availability=planned>0?run/planned:0
      const performanceRaw=run>0?theoretical/run:0
      const performance=Math.min(1,Math.max(0,performanceRaw))
      const quality=total>0?good/total:0
      const machineNames=[...new Set(rows.map(r=>r.machine).filter(Boolean))]
      const shifts=[...new Set(rows.map(r=>r.shift).filter(Boolean))]
      const operator=operators.find(p=>String(p.full_name||'').trim().toLowerCase()===name.toLowerCase())
      return {
        name,oeePct:availability*performance*quality*100,availability,performance_raw:performanceRaw,
        quality,good_count:good,total_count:total,reject_count:rows.reduce((sum,r)=>sum+Number(r.reject_count||0),0),
        entries:rows.length,machines:machineNames.length,shifts:shifts.length,operator_id:operator?.id,
        sub:` ${rows.length} entries • ${machineNames.length} machines • ${shifts.length} shifts • Good ${num(good)} / Total ${num(total)} pcs`,
      }
    }).sort((a,b)=>a.oeePct-b.oeePct||a.name.localeCompare(b.name))
  },[filteredEntries,operators])
  const selectedMachineLabel=selectedMachineNames.join(', ')
  const machineOptions=machines.map(m=>({value:String(m.id),label:`${m.name} — ${m.code}`}))
  const pageActions=<div className="export-row"><label>From <input aria-label="OEE report from date" type="date" value={fromDate} max={toDate||dateIST()} onChange={e=>setFromDate(e.target.value)}/></label><label>To <input aria-label="OEE report to date" type="date" value={toDate} min={fromDate} max={dateIST()} onChange={e=>setToDate(e.target.value)}/></label><button className="primary" disabled={exporting||busy} onClick={exportOeeExcel}>{exporting?'Preparing Excel…':'Download OEE Excel'}</button><button className="secondary" onClick={()=>window.print()}>Print / Save PDF</button></div>

  async function exportOeeExcel(){
    const q=new URLSearchParams({from_date:fromDate,as_of:toDate})
    appendScope(q,scope)
    if(machineId.length)q.set('machine_id',machineId.join(','))
    if(operatorId)q.set('operator_id',operatorId)
    if(shift)q.set('shift',shift)
    if(selectedLossCategoryId)q.set('loss_category_id',selectedLossCategoryId)
    else if(lossCategoryIds.length)q.set('loss_category_id',lossCategoryIds.join(','))
    if(lossComponent)q.set('loss_component',lossComponent)
    setExporting(true)
    try{
      await downloadApi(`/reports/oee-export.xlsx?${q.toString()}`,`OEE_Report_${fromDate}_to_${toDate}.xlsx`)
    }catch(e:any){setError(e?.message||'Unable to export OEE Excel workbook.')}
    finally{setExporting(false)}
  }

  function pickMachine(row:any){
    const machine=machines.find(m=>String(m.id)===String(row?.machine_id))
      || machines.find(m=>String(m.code).trim().toLowerCase()===String(row?.machine_code||'').trim().toLowerCase()||String(m.name).trim().toLowerCase()===String(row?.name||row?.machine||'').trim().toLowerCase())
    if(machine)setMachineId(old=>old.length===1&&old[0]===String(machine.id)?[]:[String(machine.id)])
  }

  return <>
    <PageHeader title="OEE Reports" subtitle="Machine, product, shift and operator performance with availability, performance, quality and loss analysis." actions={pageActions}/>
    <section className="panel oee-report-filter-panel">
      <div className="oee-report-filter-heading">
        <div><h2>Report Filters</h2><p>Choose the production scope and operational filters. Reports refresh automatically.</p></div>
        <span>FILTERS</span>
      </div>
      <div className="oee-filter-group-title">Production scope</div>
      <ScopeFilters value={scope} onChange={setScope} options={options} products={products} showLabels/>
      <div className="oee-filter-group-title oee-filter-group-spaced">Operational filters</div>
      <div className="oee-detail-filter-grid">
        <div className="oee-report-filter-control"><span>Machine</span><MultiSelect value={machineId} onChange={setMachineId} placeholder="All Machines" options={machineOptions}/></div>
        <div className="oee-report-filter-control"><span>Shift</span><select value={shift} onChange={e=>setShift(e.target.value)}><option value="">All Shifts</option><option value="A">A</option><option value="B">B</option><option value="C">C</option></select></div>
        <div className="oee-report-filter-control"><span>Operator</span><select value={operatorId} onChange={e=>setOperatorId(e.target.value)}><option value="">All Operators</option>{operators.map(p=><option key={p.id} value={p.id}>{p.full_name}</option>)}</select></div>
        <div className="oee-report-filter-control"><span>Loss category</span><MultiSelect value={lossCategoryIds} onChange={setLossCategoryIds} placeholder="All Loss Categories" options={lossCategories.map((x:any)=>({value:String(x.id),label:x.name}))}/></div>
        <div className="oee-report-filter-control"><span>Loss component</span><select value={lossComponent} onChange={e=>setLossComponent(e.target.value)}><option value="">All Components</option><option value="AVAILABILITY">Availability</option><option value="PERFORMANCE">Performance</option><option value="QUALITY">Quality</option></select></div>
      </div>
      <div className="oee-filter-export-row">
        <div><b>Export filtered data</b><span>Download the current selection for further review.</span></div>
        <div className="oee-filter-export-actions"><button type="button" className="secondary" onClick={()=>downloadCsv('oee_shift_details.csv',filteredEntries)}>Export OEE CSV</button><button type="button" className="secondary" onClick={()=>downloadCsv('oee_loss_details.csv',loss?.events||[])}>Export Loss CSV</button></div>
      </div>
    </section>
    {selectedMachineLabel&&<div className="filter-summary"><button className="filter-chip removable" onClick={()=>setMachineId([])}>Machine: {selectedMachineLabel} ×</button></div>}
    {error&&<div className="error" role="alert">{error}</div>}
    {busy&&<div className="notice">Refreshing OEE report…</div>}
    <div className="kpi-grid">
      <Kpi label="OEE" value={pct(summary.oee)} tone={(summary.oee||0)<.6?'bad':(summary.oee||0)<.75?'warn':'good'}/>
      <Kpi label="Availability" value={pct(summary.availability)}/>
      <Kpi label="Performance" value={pct(summary.performance_raw)} tone={summary.performance_master_warning?'warn':'neutral'}/>
      <Kpi label="Quality" value={pct(summary.quality)}/>
      <Kpi label="Downtime" value={`${num(summary.downtime_min||0)} min`}/>
      <Kpi label="Loss Hours" value={`${num(loss?.summary?.loss_hours||0)} h`} tone={(loss?.summary?.loss_hours||0)>0?'warn':'good'}/>
    </div>
    <section className="panel report-panel"><div className="panel-title"><div><h2>OEE / Availability / Performance / Quality Trend</h2><p>Daily trend for the selected date range and filters.</p></div></div><PercentTrendChart rows={data?.daily||[]} series={[{key:'oee',label:'OEE'},{key:'availability',label:'Availability'},{key:'performance',label:'Performance'},{key:'quality',label:'Quality'}]} target={85}/></section>
    <section className="panel"><div className="panel-title"><h2>Plant-wise OEE</h2><span>Click a plant to filter the report</span></div><RankedBars rows={(data?.plants||[]).map((r:any)=>({...r,name:r.plant,oeePct:(r.oee||0)*100,sub:`A ${pct(r.availability)} • P ${pct(r.performance_raw)} • Q ${pct(r.quality)} • Good ${num(r.good_count||0)} / Total ${num(r.total_count||0)} pcs`}))} valueKey="oeePct" suffix="%" onSelect={(r:any)=>setScope(old=>({...old,plant:old.plant.length===1&&old.plant[0]===r.plant?[]:[r.plant]}))} selectedName={scope.plant.length===1?scope.plant[0]:undefined}/></section>
    <section className="panel">
      <div className="panel-title">
        <div><h2>{oeeView==='machine'?'Machine-wise OEE':'Operator-wise OEE'}</h2><p>{oeeView==='machine'?'Compare OEE across machines.':'Aggregated from each operator’s saved shift entries using total time and quantity, not an average of shift OEE percentages.'}</p></div>
        <div className="export-row"><button className={oeeView==='machine'?'primary':'secondary'} onClick={()=>setOeeView('machine')}>Machine-wise OEE</button><button className={oeeView==='operator'?'primary':'secondary'} onClick={()=>setOeeView('operator')}>Operator-wise OEE</button></div>
      </div>
      {oeeView==='machine'
        ? <RankedBars rows={(data?.machines||[]).map((r:any)=>({...r,oeePct:(r.oee||0)*100,sub:`${r.machine_code||''} • ${r.open_actions||0} open actions • ${r.overdue_actions||0} overdue`}))} valueKey="oeePct" suffix="%" onSelect={pickMachine} selectedName={selectedMachineNames.length===1?selectedMachineNames[0]:undefined}/>
        : <><RankedBars rows={operatorRows.map(r=>({...r,sub:r.sub}))} valueKey="oeePct" suffix="%" onSelect={(r:any)=>{const person=operators.find(p=>String(p.id)===String(r.operator_id));if(person)setOperatorId(old=>old===String(person.id)?'':String(person.id))}} selectedName={operators.find(p=>String(p.id)===operatorId)?.full_name}/>
          <div className="table-wrap"><table><thead><tr><th>Operator</th><th>Entries</th><th>Machines</th><th>Shifts</th><th>Good Qty</th><th>Rejected</th><th>Availability</th><th>Performance</th><th>Quality</th><th>OEE</th></tr></thead><tbody>{operatorRows.map((r:any)=><tr key={r.name} className={operatorId&&String(r.operator_id)===operatorId?'selected':''}><td><b>{r.name}</b></td><td>{r.entries}</td><td>{r.machines}</td><td>{r.shifts}</td><td>{Number(r.good_count||0)}</td><td>{Number(r.reject_count||0)}</td><td>{pct(r.availability)}</td><td>{pct(r.performance_raw)}</td><td>{pct(r.quality)}</td><td><b>{pct(r.oeePct/100)}</b></td></tr>)}{!operatorRows.length&&<tr><td colSpan={10} className="muted">No operator entries in this date range and filter scope.</td></tr>}</tbody></table></div>
        </>}
    </section>
    <div className="advanced-grid"><section className="panel"><div className="panel-title"><h2>Loss Pareto</h2><span>Click a loss to see its machine-wise impact; click again to clear</span></div><RankedBars rows={loss?.pareto||[]} valueKey="minutes" suffix=" min" onSelect={(r:any)=>setSelectedLossCategoryId(old=>old===String(r.loss_category_id)?'':String(r.loss_category_id))} selectedName={loss?.pareto?.find((r:any)=>String(r.loss_category_id)===selectedLossCategoryId)?.name}/></section><section className="panel"><div className="panel-title"><div><h2>{selectedLossCategoryId?'Machine Loss Hours — '+(loss?.pareto?.find((r:any)=>String(r.loss_category_id)===selectedLossCategoryId)?.name||'Selected Loss'):'Machine Loss Hours'}</h2><span>{selectedLossCategoryId?'Hours by machine for the selected loss category':'Click a machine to filter'}</span></div>{selectedLossCategoryId&&<button className="secondary" onClick={()=>setSelectedLossCategoryId('')}>Clear loss selection</button>}</div><RankedBars rows={(loss?.machines||[]).map((r:any)=>({...r,sub:r.machine_code||''}))} valueKey="hours" suffix=" h" onSelect={pickMachine} selectedName={selectedMachineNames.length===1?selectedMachineNames[0]:undefined}/></section></div>
    <section className="panel report-panel">
      <div className="panel-title"><div><h2>Daily Machine Loss Hours</h2><p>Daily loss hours stacked by loss category, using the selected date range and report filters.</p></div></div>
      {dailyLossTrend.length>0?<><div className="svg-scroll"><div style={{display:"flex",alignItems:"flex-end",gap:10,height:250,minWidth:dailyLossTrend.length*54,width:"max-content",padding:"16px 8px 4px",borderBottom:"1px solid var(--border, #d7deea)"}}>{dailyLossTrend.map((day:any)=>{const max=Math.max(0.1,...dailyLossTrend.map((item:any)=>Number(item.total_hours||0)));return <div key={day.date} title={`${day.date}: ${num(day.total_hours)} h`} style={{width:44,flex:"0 0 44px",height:"100%",display:"flex",flexDirection:"column",justifyContent:"flex-end",alignItems:"center",gap:5}}><div style={{height:`${Math.max(0,Number(day.total_hours||0)/max*185)}px`,width:"76%",display:"flex",flexDirection:"column-reverse",justifyContent:"flex-start",borderRadius:"4px 4px 0 0",overflow:"hidden"}}>{day.categories.map((part:any)=>{const color=lossChartPalette[dailyLossCategories.indexOf(part.category)%lossChartPalette.length]||lossChartPalette[0];return <div key={part.category} title={`${part.category}: ${num(part.hours)} h`} style={{height:`${Number(part.hours||0)/Math.max(0.001,Number(day.total_hours||0))*100}%`,backgroundColor:color,minHeight:part.hours>0?2:0}}/>})}</div><small style={{fontSize:10,whiteSpace:"nowrap",color:"var(--muted, #64748b)"}}>{new Date(`${day.date}T12:00:00`).toLocaleDateString("en-IN",{day:"2-digit",month:"short"})}</small></div>})}</div></div><div style={{display:"flex",flexWrap:"wrap",gap:"8px 16px",paddingTop:12}}>{dailyLossCategories.map((name:string,i:number)=><span key={name} style={{display:"inline-flex",alignItems:"center",gap:6,fontSize:12}}><span style={{width:10,height:10,borderRadius:2,backgroundColor:lossChartPalette[i%lossChartPalette.length]}}/>{name}</span>)}</div></>:<div className="empty">No loss events match the selected dates and filters.</div>}
    </section>
    {!showMonthlyLossTrend&&<p className="muted">Select a date range of more than one month to display the Monthly Loss Hours Trend.</p>}
    {showMonthlyLossTrend&&<section className="panel report-panel">
      <div className="panel-title"><div><h2>Monthly Loss Hours Trend</h2><p>Monthly loss hours stacked by the same loss categories as the daily chart. Each month includes only dates inside the selected range.</p></div></div>
      {monthlyLossTrend.length>0?<><div className="svg-scroll"><div style={{display:"flex",alignItems:"flex-end",gap:14,height:250,minWidth:monthlyLossTrend.length*82,width:"max-content",padding:"16px 8px 4px",borderBottom:"1px solid var(--border, #d7deea)"}}>{monthlyLossTrend.map((month:any)=>{const max=Math.max(0.1,...monthlyLossTrend.map((item:any)=>Number(item.total_hours||0)));return <div key={month.month} title={`${month.label}: ${num(month.total_hours)} h`} style={{width:68,flex:"0 0 68px",height:"100%",display:"flex",flexDirection:"column",justifyContent:"flex-end",alignItems:"center",gap:6}}><div style={{height:`${Math.max(0,Number(month.total_hours||0)/max*185)}px`,width:"72%",display:"flex",flexDirection:"column-reverse",justifyContent:"flex-start",borderRadius:"5px 5px 0 0",overflow:"hidden"}}>{month.categories.map((part:any)=>{const color=lossChartPalette[dailyLossCategories.indexOf(part.category)%lossChartPalette.length]||lossChartPalette[0];return <div key={part.category} title={`${part.category}: ${num(part.hours)} h`} style={{height:`${Number(part.hours||0)/Math.max(0.001,Number(month.total_hours||0))*100}%`,backgroundColor:color,minHeight:part.hours>0?2:0}}/>})}</div><small style={{fontSize:11,whiteSpace:"nowrap",color:"var(--muted, #64748b)"}}>{month.label}</small></div>})}</div></div><div style={{display:"flex",flexWrap:"wrap",gap:"8px 16px",paddingTop:12}}>{dailyLossCategories.map((name:string,i:number)=><span key={name} style={{display:"inline-flex",alignItems:"center",gap:6,fontSize:12}}><span style={{width:10,height:10,borderRadius:2,backgroundColor:lossChartPalette[i%lossChartPalette.length]}}/>{name}</span>)}</div></>:<div className="empty">No loss events match the selected dates and filters.</div>}
    </section>}
    <section className="panel"><div className="panel-title"><div><h2>Machine Shift OEE Details</h2><p>Raw performance above 110% flags a cycle-time or quantity master check.</p></div></div><div className="table-wrap"><table><thead><tr><th>Date</th><th>Shift</th><th>Machine</th><th>Product / Operation</th><th>Operator</th><th>Run / Planned</th><th>Total / Good / Reject</th><th>A</th><th>P</th><th>Q</th><th>OEE</th></tr></thead><tbody>{filteredEntries.map((r:any)=><tr key={r.id}><td>{r.date}</td><td>{r.shift}</td><td><b>{r.machine}</b><br/><small>{r.machine_code||''}</small></td><td>{r.product}<br/><small>{r.operation}</small></td><td>{r.operator||'—'}</td><td>{Number(r.run_min||0)} / {Number(r.planned_min||0)} min</td><td>{Number(r.total_count||0)} / {Number(r.good_count||0)} / {Number(r.reject_count||0)}</td><td>{pct(r.availability)}</td><td className={r.performance_master_warning?'neg':''}>{pct(r.performance_raw)}</td><td>{pct(r.quality)}</td><td><b>{pct(r.oee)}</b></td></tr>)}{!filteredEntries.length&&<tr><td colSpan={11} className="muted">No OEE shift entries in this date range and filter scope.</td></tr>}</tbody></table></div></section>
    <section className="panel"><div className="panel-title"><div><h2>Machine Loss Details and Action Linkage</h2><p>Loss records are linked to their action plans where an action has been raised.</p></div><Link to="/actions">Open action register</Link></div><div className="table-wrap"><table><thead><tr><th>Date</th><th>Shift</th><th>Machine</th><th>Product / Operation</th><th>Loss</th><th>Component</th><th>Minutes</th><th>Remark</th><th>Action</th></tr></thead><tbody>{(loss?.events||[]).map((r:any)=><tr key={r.id}><td>{r.date}</td><td>{r.shift}</td><td><b>{r.machine}</b><br/><small>{r.machine_code||''}</small></td><td>{r.product||'—'}<br/><small>{r.operation||'—'}</small></td><td>{r.category}</td><td>{r.component}</td><td>{num(r.duration_min)}</td><td>{r.remark||'—'}</td><td>{r.action_no?<Link to="/actions">{r.action_no} · {r.action_status}</Link>:<span className="status watch">Action pending</span>}</td></tr>)}{!(loss?.events||[]).length&&<tr><td colSpan={9} className="muted">No loss events in this date range and filter scope.</td></tr>}</tbody></table></div></section>
  </>
}
