import ImportPreview from '../components/ImportPreview'
import { useNavigate } from 'react-router-dom'
import { useEffect, useMemo, useState } from 'react'
import { api, downloadApi } from '../api'
import { Kpi, PageHeader, num } from '../components/UI'
import { RankedBars, ValueTrendChart } from '../components/Charts'
import { MultiSelect } from '../components/MultiSelect'

function iso(d:Date){
  const y=d.getFullYear(), m=String(d.getMonth()+1).padStart(2,'0'), day=String(d.getDate()).padStart(2,'0')
  return `${y}-${m}-${day}`
}
function monthEnd(monthStart:string){
  const [y,m]=monthStart.slice(0,10).split('-').map(Number)
  return iso(new Date(y, m, 0))
}
function csvCell(v:any){const s=String(v??'');return `"${s.replaceAll('"','""')}"`}
function downloadCsv(name:string,rows:any[]){
  if(!rows.length)return
  const keys=Object.keys(rows[0])
  const csv='\ufeff'+[keys.map(csvCell).join(','),...rows.map(r=>keys.map(k=>csvCell(r[k])).join(','))].join('\r\n')
  const blob=new Blob([csv],{type:'text/csv;charset=utf-8'})
  const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=name;a.click();URL.revokeObjectURL(a.href)
}

export default function Quality(){
  const navigate=useNavigate()
  function drill(r:any){const month=r.month;const first=month||r.date||r.rejection_date||fromDate;const last=month?monthEnd(month):first;const q=new URLSearchParams({kind:'ppm',from_date:first,to_date:last});if(productId.length)q.set('product_id',productId.join(','));if(plant.length)q.set('plant',plant.join(','));if(phenomenonId.length)q.set('phenomenon_id',phenomenonId.join(','));if(machineId.length)q.set('machine_id',machineId.join(','));if(operationId.length)q.set('operation_id',operationId.join(','));if(shift.length)q.set('shift',shift.join(','));navigate(`/insights?${q}`)}
  const today=new Date(); const weekAgo=new Date(today); weekAgo.setDate(today.getDate()-7)
  const [fromDate,setFromDate]=useState(iso(weekAgo)); const [toDate,setToDate]=useState(iso(today))
  const [plant,setPlant]=useState<string[]>([]); const [productId,setProductId]=useState<string[]>([]); const [phenomenonId,setPhenomenonId]=useState<string[]>([])
  const [operationId,setOperationId]=useState<string[]>([]); const [machineId,setMachineId]=useState<string[]>([]); const [shift,setShift]=useState<string[]>([])
  const [products,setProducts]=useState<any[]>([]); const [filters,setFilters]=useState<any>({plants:[]}); const [phenomena,setPhenomena]=useState<any[]>([])
  const [operations,setOperations]=useState<any[]>([]); const [machines,setMachines]=useState<any[]>([])
  const [summary,setSummary]=useState<any>({}); const [rows,setRows]=useState<any[]>([]); const [trend,setTrend]=useState<any[]>([])
  const [monthlyTrend,setMonthlyTrend]=useState<any[]>([]); const [historyRows,setHistoryRows]=useState<any[]>([]); const [historyRange,setHistoryRange]=useState<any>({min_month:null,max_month:null,records:0})
  const [partPareto,setPartPareto]=useState<any[]>([]); const [phenPareto,setPhenPareto]=useState<any[]>([]); const [busy,setBusy]=useState(false); const [err,setErr]=useState('')
  const [newPhen,setNewPhen]=useState(''); const [rejectionType,setRejectionType]=useState<string>('')
  const [showManual,setShowManual]=useState(false); const [manualOps,setManualOps]=useState<any[]>([]); const [manualSaving,setManualSaving]=useState(false); const [manualMsg,setManualMsg]=useState(''); const [actionMsg,setActionMsg]=useState('')
  const [manual,setManual]=useState<any>({rejection_date:iso(today),shift:'A',product_id:'',detection_route_operation_id:'',responsible_route_operation_id:'',machine_id:'',phenomenon_id:'',reject_qty:'',rework_qty:'0',scrap_qty:'0',remark:'',action_required:false})

  const qs=useMemo(()=>{const p=new URLSearchParams({from_date:fromDate,to_date:toDate});if(plant.length)p.set('plant',plant.join(','));if(productId.length)p.set('product_id',productId.join(','));if(phenomenonId.length)p.set('phenomenon_id',phenomenonId.join(','));if(operationId.length)p.set('operation_id',operationId.join(','));if(machineId.length)p.set('machine_id',machineId.join(','));if(shift.length)p.set('shift',shift.join(','));return p.toString()},[fromDate,toDate,plant,productId,phenomenonId,operationId,machineId,shift])

  async function loadMasters(){
    const [p,f,ph,o,m,hr]=await Promise.all([api('/masters/products'),api('/masters/filter-options'),api('/quality/phenomena'),api('/masters/operations'),api('/masters/machines'),api('/quality/history-range')])
    setProducts(p as any[]);setFilters(f);setPhenomena(ph as any[]);setOperations(o as any[]);setMachines(m as any[]);setHistoryRange(hr)
  }
  async function load(){
    setBusy(true);setErr('')
    try{
      const report:any=await api(`/quality/report-pack?${qs}`)
      setSummary(report.summary);setRows(report.rows);setTrend(report.trend);setPartPareto(report.part_pareto);setPhenPareto(report.phenomenon_pareto);setMonthlyTrend(report.monthly_trend);setHistoryRows(report.history)
    }catch(e:any){setErr(e.message)}finally{setBusy(false)}
  }
  useEffect(()=>{loadMasters().catch(e=>setErr(e.message))},[])
  useEffect(()=>{load()},[qs])
  useEffect(()=>{
    if(!manual.product_id){setManualOps([]);return}
    let active=true
    api(`/masters/routes/${manual.product_id}?on_date=${manual.rejection_date}`).then((versions:any)=>{
      if(!active)return
      const on=manual.rejection_date
      const current=(versions||[]).find((v:any)=>String(v.effective_from).slice(0,10)<=on&&(!v.effective_to||String(v.effective_to).slice(0,10)>=on))||(versions||[])[0]
      const ops=current?.operations||[]
      setManualOps(ops)
      setManual((prev:any)=>({
        ...prev,
        detection_route_operation_id:ops.some((x:any)=>String(x.route_operation_id)===String(prev.detection_route_operation_id))?prev.detection_route_operation_id:'',
        responsible_route_operation_id:ops.some((x:any)=>String(x.route_operation_id)===String(prev.responsible_route_operation_id))?prev.responsible_route_operation_id:'',
      }))
    }).catch((e:any)=>setErr(e.message))
    return()=>{active=false}
  },[manual.product_id,manual.rejection_date])

  async function addPhenomenon(){if(!newPhen.trim())return;try{await api('/quality/phenomena',{method:'POST',body:JSON.stringify({name:newPhen,default_responsible_team:'Operation',criticality:'NORMAL'})});setNewPhen('');await loadMasters()}catch(e:any){setErr(e.message)}}
  async function saveManualRejection(){
    setManualMsg('');setErr('')
    if(!manual.rejection_date||!manual.product_id||!manual.detection_route_operation_id||!manual.phenomenon_id||Number(manual.reject_qty)<=0){setErr('Date, Product, Detection Process, Phenomenon and Reject Qty are required.');return}
    setManualSaving(true)
    try{
      const payload={
        rejection_date:manual.rejection_date,shift:manual.shift,product_id:Number(manual.product_id),
        detection_route_operation_id:Number(manual.detection_route_operation_id),
        responsible_route_operation_id:manual.responsible_route_operation_id?Number(manual.responsible_route_operation_id):null,
        machine_id:manual.machine_id?Number(manual.machine_id):null,phenomenon_id:Number(manual.phenomenon_id),
        reject_qty:Number(manual.reject_qty),rework_qty:Number(manual.rework_qty||0),scrap_qty:Number(manual.scrap_qty||0),
        remark:manual.remark||null,action_required:Boolean(manual.action_required),
      }
      const saved:any=await api('/quality/daily',{method:'POST',body:JSON.stringify(payload)})
      let actionText=''
      if(manual.action_required){
        const a:any=await api(`/quality/rejections/${saved.id}/raise-action`,{method:'POST',body:JSON.stringify({priority:'HIGH',action_description:'Immediate containment and standard Why-Why analysis required'})})
        actionText=` • ${a.action_no} created`
      }
      setManualMsg(`Rejection saved successfully${saved.ppm_pending?' • PPM pending (production denominator not available yet)':''}${actionText}`)
      setManual((prev:any)=>({...prev,reject_qty:'',rework_qty:'0',scrap_qty:'0',remark:'',action_required:false}))
      if(manual.rejection_date<fromDate)setFromDate(manual.rejection_date)
      if(manual.rejection_date>toDate)setToDate(manual.rejection_date)
      await load()
    }catch(e:any){setErr(e.message)}finally{setManualSaving(false)}
  }
  async function raiseAction(id:number){setActionMsg('');try{const r:any=await api(`/quality/rejections/${id}/raise-action`,{method:'POST',body:JSON.stringify({priority:'HIGH',action_description:'Immediate containment and standard Why-Why analysis required'})});setActionMsg(`${r.action_no} ${r.status==='already_linked'?'is already linked':'created successfully'}.`);await load()}catch(e:any){setErr(e.message)}}
  function showImportedHistory(){if(!historyRange?.min_month||!historyRange?.max_month)return;setFromDate(String(historyRange.min_month).slice(0,10));setToDate(monthEnd(String(historyRange.max_month)))}
  function exportDailyRejection(){
    const out=(rows||[]).map((r:any)=>({Date:r.date,Shift:r.shift,Plant:r.plant||'',Product:r.product,Phenomenon:r.phenomenon,'Detection Process':r.detection_process||'','Responsible Process':r.responsible_process||'',Machine:r.machine||'','Reject Qty':r.reject_qty,'Denominator Qty':r.denominator_qty??'Pending',PPM:r.ppm==null?'Pending':Math.round(r.ppm),Remark:r.remark||''}))
    downloadCsv(`Rejection_Daily_${fromDate}_to_${toDate}.csv`,out)
  }
  function exportMonthlyPhenomenon(){
    const months=new Map<string,any>()
    for(const r of (historyRows||[])){const month=String(r.month||'').slice(0,7);if(!month)continue;const key=`${month}|${r.plant||''}|${r.product||''}|${r.phenomenon||''}`;const x=months.get(key)||{Month:month,Plant:r.plant||'',Product:r.product||'',Phenomenon:r.phenomenon||'','Reject Qty':0};x['Reject Qty']+=Number(r.reject_qty||0);months.set(key,x)}
    for(const r of (rows||[])){const month=String(r.date||'').slice(0,7);if(!month)continue;const key=`${month}|${r.plant||''}|${r.product||''}|${r.phenomenon||''}`;const x=months.get(key)||{Month:month,Plant:r.plant||'',Product:r.product||'',Phenomenon:r.phenomenon||'','Reject Qty':0};x['Reject Qty']+=Number(r.reject_qty||0);months.set(key,x)}
    downloadCsv(`Rejection_Phenomenon_Monthly_${fromDate}_to_${toDate}.csv`,Array.from(months.values()).sort((a:any,b:any)=>String(a.Month).localeCompare(String(b.Month))||String(a.Phenomenon).localeCompare(String(b.Phenomenon))))
  }
  function pickProduct(row:any){
    const name=String(row?.name||'')
    const product=products.find((x:any)=>String(x.name).trim().toLowerCase()===name.trim().toLowerCase())
    if(!product)return
    const id=String(product.id)
    setProductId(productId.length===1&&productId[0]===id?[]:[id])
  }
  function pickPhenomenon(row:any){
    const name=String(row?.name||'')
    const phenomenon=phenomena.find((x:any)=>String(x.name).trim().toLowerCase()===name.trim().toLowerCase())
    if(!phenomenon)return
    const id=String(phenomenon.id)
    setPhenomenonId(phenomenonId.length===1&&phenomenonId[0]===id?[]:[id])
  }
  const selectedProductNames=products.filter((x:any)=>productId.includes(String(x.id))).map((x:any)=>x.name)
  const selectedPhenomenonNames=phenomena.filter((x:any)=>phenomenonId.includes(String(x.id))).map((x:any)=>x.name)
  const hasGraphFilter=selectedProductNames.length>0||selectedPhenomenonNames.length>0
  const phenomenonGroupById=useMemo(()=>new Map(phenomena.map((x:any)=>[String(x.id),String(x.group||x.phenomenon_group||'')])),[phenomena])
  const rejectionTypeRows=useMemo(()=>{
    const totals:any={"Casting Rejection":0,"Machining Rejection":0}
    const historyCoverage=new Set<string>()
    for(const r of historyRows){
      const group=phenomenonGroupById.get(String(r.phenomenon_id))
      if((group==="Casting Rejection"||group==="Machining Rejection")&&r.include_in_aggregate===false){
        totals[group]+=Number(r.reject_qty||0)
        historyCoverage.add(`${String(r.month||'').slice(0,7)}|${r.product_id}`)
      }
    }
    for(const r of rows){
      if(historyCoverage.has(`${String(r.date||'').slice(0,7)}|${r.product_id}`))continue
      const group=phenomenonGroupById.get(String(r.phenomenon_id))
      if(group==="Casting Rejection"||group==="Machining Rejection")totals[group]+=Number(r.reject_qty||0)
    }
    return [{name:"Casting Rejection",reject_qty:totals["Casting Rejection"]},{name:"Machining Rejection",reject_qty:totals["Machining Rejection"]}]
  },[rows,historyRows,phenomenonGroupById])
  const visiblePhenPareto=useMemo(()=>rejectionType?phenPareto.filter((r:any)=>{
    const ph=phenomena.find((x:any)=>String(x.name).trim().toLowerCase()===String(r.name).trim().toLowerCase())
    return ph&&String(ph.group||ph.phenomenon_group||'')===rejectionType
  }):phenPareto,[phenPareto,phenomena,rejectionType])
  function pickRejectionType(row:any){const name=String(row?.name||'');setRejectionType(rejectionType===name?'':name)}


  const ppm=(summary.ppm==null?'—':Math.round(summary.ppm).toLocaleString('en-IN'))
  const visibleHistory=historyRows.slice(0,500)
  const monthlyPpmRows=monthlyTrend.filter((x:any)=>x.ppm!=null).map((x:any)=>({...x,value:Number(x.ppm)}))
  const monthlyPpmPending=monthlyTrend.filter((x:any)=>x.ppm==null&&Number(x.reject_qty||0)>0).length
  const dailyPpmRows=trend.filter((x:any)=>x.ppm!=null).map((x:any)=>({...x,value:Number(x.ppm)}))
  const dailyPpmPending=trend.filter((x:any)=>x.ppm==null&&Number(x.reject_qty||0)>0).length
  return <>
    <PageHeader title="Quality / Rejection" subtitle="Daily rejection, historical monthly rejection, PPM, Pareto and Why-Why actions." actions={<div className="button-row"><button onClick={()=>{setShowManual(!showManual);setManualMsg('')}}>{showManual?'Close Entry':'+ Add Rejection'}</button><button className="secondary" onClick={()=>downloadApi('/quality/template','Daily_Rejection_Upload_v0.4.6.xlsx')}>Download Daily Template</button>{historyRange?.records>0&&<button className="secondary" onClick={showImportedHistory}>Show Imported History</button>}<button onClick={()=>window.print()}>Print / PDF</button></div>}/>

    {showManual&&<section className="panel manual-rejection-panel"><div className="panel-title"><div><h2>Add Rejection</h2><p>Manual entry for a single daily rejection. Master-linked fields use the same validation and PPM denominator logic as Excel import.</p></div></div>
      <div className="quality-entry-grid">
        <label>Date<input type="date" value={manual.rejection_date} onChange={e=>setManual({...manual,rejection_date:e.target.value})}/></label>
        <label>Shift<select value={manual.shift} onChange={e=>setManual({...manual,shift:e.target.value})}>{['A','B','C','General'].map(x=><option key={x} value={x}>{x}</option>)}</select></label>
        <label>Product<MultiSelect className="manual-search-select" value={manual.product_id?[String(manual.product_id)]:[]} onChange={v=>setManual({...manual,product_id:v.at(-1)||'',detection_route_operation_id:'',responsible_route_operation_id:''})} placeholder="Select Product" options={products.map((x:any)=>({value:String(x.id),label:x.name}))}/></label>
        <label>Detection Process<MultiSelect className="manual-search-select" value={manual.detection_route_operation_id?[String(manual.detection_route_operation_id)]:[]} onChange={v=>setManual({...manual,detection_route_operation_id:v.at(-1)||''})} placeholder={manual.product_id?"Select Process":"Select Product first"} options={manual.product_id?manualOps.map((x:any)=>({value:String(x.route_operation_id),label:x.operation})):[]}/></label>
        <label>Responsible Process<MultiSelect className="manual-search-select" value={manual.responsible_route_operation_id?[String(manual.responsible_route_operation_id)]:[]} onChange={v=>setManual({...manual,responsible_route_operation_id:v.at(-1)||''})} placeholder={manual.product_id?"Optional":"Select Product first"} options={manual.product_id?manualOps.map((x:any)=>({value:String(x.route_operation_id),label:x.operation})):[]}/></label>
        <label>Machine<MultiSelect className="manual-search-select" value={manual.machine_id?[String(manual.machine_id)]:[]} onChange={v=>setManual({...manual,machine_id:v.at(-1)||''})} placeholder="Optional" options={machines.filter((x:any)=>x.active!==false).map((x:any)=>({value:String(x.id),label:x.name}))}/></label>
        <label>Phenomenon<MultiSelect className="manual-search-select" value={manual.phenomenon_id?[String(manual.phenomenon_id)]:[]} onChange={v=>setManual({...manual,phenomenon_id:v.at(-1)||''})} placeholder="Select Phenomenon" options={phenomena.map((x:any)=>({value:String(x.id),label:x.name}))}/></label>
        <label>Reject Qty<input type="number" min="0.001" step="0.001" value={manual.reject_qty} onChange={e=>setManual({...manual,reject_qty:e.target.value})}/></label>
        <label>Rework Qty<input type="number" min="0" step="0.001" value={manual.rework_qty} onChange={e=>setManual({...manual,rework_qty:e.target.value})}/></label>
        <label>Scrap Qty<input type="number" min="0" step="0.001" value={manual.scrap_qty} onChange={e=>setManual({...manual,scrap_qty:e.target.value})}/></label>
        <label className="span-2">Remark<textarea value={manual.remark} onChange={e=>setManual({...manual,remark:e.target.value})} placeholder="Optional observation / containment note"/></label>
        <label className="inline-check manual-action"><input type="checkbox" checked={manual.action_required} onChange={e=>setManual({...manual,action_required:e.target.checked})}/> Raise Why-Why action after saving</label>
      </div>
      <div className="button-row"><button onClick={saveManualRejection} disabled={manualSaving}>{manualSaving?'Saving...':'Save Rejection'}</button><button className="secondary" onClick={()=>setShowManual(false)}>Cancel</button></div>
      {manualMsg&&<div className="notice">{manualMsg}</div>}
    </section>}
    <section className="panel"><div className="filters quality-filters"><label>From<input type="date" value={fromDate} onChange={e=>setFromDate(e.target.value)}/></label><label>To<input type="date" value={toDate} onChange={e=>setToDate(e.target.value)}/></label><label>Plant<MultiSelect value={plant} onChange={setPlant} placeholder="All Plants" options={(filters.plants||[]).map((x:string)=>({value:String(x),label:String(x)}))}/></label><label>Product<MultiSelect value={productId} onChange={setProductId} placeholder="All Products" options={products.map(x=>({value:String(x.id),label:x.name}))}/></label><label>Phenomenon<MultiSelect value={phenomenonId} onChange={setPhenomenonId} placeholder="All Phenomena" options={phenomena.map(x=>({value:String(x.id),label:x.name}))}/></label><label>Process<MultiSelect value={operationId} onChange={setOperationId} placeholder="All Processes" options={operations.map(x=>({value:String(x.id),label:x.name}))}/></label><label>Machine<MultiSelect value={machineId} onChange={setMachineId} placeholder="All Machines" options={machines.map(x=>({value:String(x.id),label:x.name}))}/></label><label>Shift<MultiSelect value={shift} onChange={setShift} placeholder="All Shifts" searchable={false} options={['A','B','C','General'].map(x=>({value:x,label:x}))}/></label></div><div className="button-row"><button className="secondary" onClick={exportDailyRejection} disabled={!rows.length}>Download Daily Rejection Excel/CSV</button><button className="secondary" onClick={exportMonthlyPhenomenon} disabled={!rows.length&&!historyRows.length}>Download Phenomenon Monthly Excel/CSV</button></div>{hasGraphFilter&&<div className="filter-summary"><span className="filter-chip">Graph filter</span>{selectedProductNames.map((name:string)=><button key={`p-${name}`} className="filter-chip removable" onClick={()=>setProductId([])}>Part: {name} ×</button>)}{selectedPhenomenonNames.map((name:string)=><button key={`ph-${name}`} className="filter-chip removable" onClick={()=>setPhenomenonId([])}>Phenomenon: {name} ×</button>)}<button className="filter-chip removable" onClick={()=>{setProductId([]);setPhenomenonId([])}}>Clear graph filters</button></div>}{historyRange?.records>0&&<p className="muted">Imported history: {historyRange.min_month} to {historyRange.max_month} • {num(historyRange.records)} phenomenon rows. Historical PPM automatically uses matching Daily MIS Actual Qty as the Dispatch Done denominator when available; otherwise PPM stays Pending.</p>}{summary.history_note&&<div className="warning">{summary.history_note}</div>}{actionMsg&&<div className="notice">{actionMsg}</div>}{err&&<div className="error">{err}</div>}</section>

    <div className="kpi-grid"><Kpi label="Rejected Qty" value={num(summary.reject_qty||0)} tone={(summary.reject_qty||0)>0?'bad':'good'} sub={`${num(summary.daily_records||0)} daily + ${num(summary.historical_records||0)} historical rows`}/><Kpi label="PPM" value={ppm} tone={summary.ppm==null?'warn':summary.ppm_is_partial?'warn':'neutral'} sub={`${num(summary.denominator_qty||0)} Dispatch/denominator qty${summary.ppm_is_partial?` • Partial: ${num(summary.ppm_pending_rows||0)} denominator row${Number(summary.ppm_pending_rows||0)===1?'':'s'} pending`:''}`}/><Kpi label="Rework" value={num(summary.rework_qty||0)}/><Kpi label="Scrap" value={num(summary.scrap_qty||0)} tone={(summary.scrap_qty||0)>0?'bad':'neutral'}/><Kpi label="Open Actions" value={summary.open_actions||0} tone={(summary.open_actions||0)>0?'warn':'good'}/><Kpi label="Overdue Actions" value={summary.overdue_actions||0} tone={(summary.overdue_actions||0)>0?'bad':'good'}/></div>

    <section className="panel"><div className="panel-title"><h2>Monthly Rejection Qty Trend</h2><span>Historical + daily roll-up • labels ON</span></div><ValueTrendChart onSelect={drill} rows={monthlyTrend.map(x=>({...x,value:x.reject_qty||0}))} keyName="value" label="Reject Qty"/></section>
    <section className="panel ppm-trend-panel"><div className="panel-title"><h2>Monthly PPM Trend</h2><span>Historical + daily roll-up • PPM labels ON</span></div><ValueTrendChart onSelect={drill} rows={monthlyPpmRows} keyName="value" label="PPM"/>{monthlyTrend.length>0&&<div className="table-wrap ppm-quantity-matrix" aria-label="Monthly rejection and dispatch quantities"><table><thead><tr><th>Quantity</th>{monthlyTrend.map((r:any)=><th key={String(r.month)}>{r.label||String(r.month).slice(0,7)}</th>)}</tr></thead><tbody><tr className="ppm-rejection-row"><th>Rejection Qty</th>{monthlyTrend.map((r:any)=><td key={String(r.month)}>{num(r.reject_qty||0)}</td>)}</tr><tr><th>Dispatch Qty</th>{monthlyTrend.map((r:any)=><td key={String(r.month)}>{Number(r.denominator_qty||0)>0?num(r.denominator_qty):Number(r.reject_qty||0)>0?'Pending':'0'}</td>)}</tr></tbody></table></div>}{monthlyPpmPending>0&&<p className="muted">{monthlyPpmPending} month{monthlyPpmPending===1?'':'s'} not plotted because Dispatch/denominator Qty is still pending.</p>}<p className="muted">Dispatch Qty is the denominator used for the PPM plotted above. With process or machine filters, it can be the corresponding process/machine production quantity.</p></section>
    <section className="panel"><div className="panel-title"><h2>Daily PPM Trend</h2><span>Daily rejection uploads • labels ON</span></div>{dailyPpmRows.length>0?<ValueTrendChart onSelect={drill} rows={dailyPpmRows} keyName="value" label="PPM"/>:<p className="muted">No daily PPM is available for the selected date range and filters.</p>}{dailyPpmPending>0&&<p className="muted">{dailyPpmPending} day{dailyPpmPending===1?'':'s'} contain rejection data but cannot plot PPM because the denominator is pending.</p>}</section>
    <section className="panel"><div className="panel-title"><h2>Rejection by Type</h2><span>Casting vs Machining • click to filter Phenomenon Pareto</span></div><RankedBars rows={rejectionTypeRows} valueKey="reject_qty" labelKey="name" valueLabel="Reject Qty" onSelect={pickRejectionType} selectedName={rejectionType||undefined}/></section>
    <div className="two-col"><section className="panel"><div className="panel-title"><h2>Phenomenon Pareto</h2><span>{rejectionType?`${rejectionType} • click a phenomenon to filter`:'Click a bar to filter; click again to clear'}</span></div><RankedBars rows={visiblePhenPareto.slice(0,20)} valueKey="reject_qty" labelKey="name" valueLabel="Reject Qty" onSelect={pickPhenomenon} selectedName={selectedPhenomenonNames.length===1?selectedPhenomenonNames[0]:undefined}/></section><section className="panel"><div className="panel-title"><h2>Component Pareto</h2><span>Click a bar to filter; click again to clear</span></div><RankedBars rows={partPareto.slice(0,20)} valueKey="reject_qty" labelKey="name" valueLabel="Reject Qty" onSelect={pickProduct} selectedName={selectedProductNames.length===1?selectedProductNames[0]:undefined}/></section></div>
    

    <section className="panel"><div className="panel-title"><div><h2>Approved Phenomenon Master</h2><p>Maintain rejection phenomena individually or by controlled Excel upload.</p></div><button className="secondary" onClick={()=>downloadApi('/quality/phenomena-template','Phenomenon_Master_Upload.xlsx')}>Download Master Template</button></div><div className="two-col"><div><h3>Add One Phenomenon</h3><div className="form-row"><label>New Phenomenon<input value={newPhen} onChange={e=>setNewPhen(e.target.value)} placeholder="Add one approved phenomenon"/></label><button onClick={addPhenomenon}>Add to Master</button></div></div><div><h3>Excel Master Upload</h3><p>Preview New / Updated / Unchanged / Rejected rows before committing. Existing normalized names are updated rather than duplicated.</p><ImportPreview kind="quality-phenomena" onComplete={()=>loadMasters()}/></div></div><p className="muted">Daily rejection uploads reject unknown typed phenomena. Use groups such as Casting Rejection or Machining Rejection to keep Pareto analysis consistent.</p></section>

    <section className="panel"><h2>Excel Imports</h2><div className="two-col"><div><h3>Daily Rejection</h3><p>Download a fresh template after any Product, Process, Machine or Phenomenon master change. Orange headers and yellow cells are required; fixed master fields use dropdowns.</p><button className="secondary" onClick={()=>downloadApi('/quality/template','Daily_Rejection_Upload_v0.4.6.xlsx')}>Download Template</button><ImportPreview kind="quality-daily" onComplete={()=>{loadMasters();load()}}/></div><div><h3>Historical Rejection</h3><p>Historical rejection quantities are combined with the approved historical PPM production denominator when available.</p><ImportPreview kind="quality-history" onComplete={()=>{loadMasters();load()}}/></div><div><h3>Historical PPM Production</h3><p><b>Siddharth Machining + Silver Production</b>. Upload month-wise Product production. ACK Machining is excluded. This denominator takes priority over broad MIS Dispatch for historical PPM.</p><ImportPreview kind="quality-historical-ppm-production" onComplete={()=>{loadMasters();load()}}/></div></div></section>

    {historyRows.length>0&&<section className="panel"><div className="panel-title"><h2>Historical Monthly Rejection Detail</h2><span>{num(historyRows.length)} rows{historyRows.length>500?' • first 500 shown':''}</span></div><div className="table-wrap"><table><thead><tr><th>Month</th><th>Source</th><th>Plant</th><th>Product</th><th>Phenomenon</th><th>Reject</th><th>Dispatch Done</th><th>Calculated PPM</th><th>Source PPM</th></tr></thead><tbody>{visibleHistory.map(r=><tr key={r.id}><td>{String(r.month).slice(0,7)}</td><td>{r.source||'—'}</td><td>{r.plant||'—'}</td><td>{r.product}</td><td>{r.phenomenon}</td><td><b>{num(r.reject_qty)}</b></td><td>{r.dispatch_qty==null?'Pending':<>{num(r.dispatch_qty)}{r.dispatch_qty_source==='MIS_HISTORY'&&<span className="muted"> • MIS</span>}</>}</td><td>{r.ppm==null?'Pending':Math.round(r.ppm).toLocaleString('en-IN')}</td><td>{r.source_reported_ppm==null?'—':Math.round(r.source_reported_ppm).toLocaleString('en-IN')}</td></tr>)}</tbody></table></div></section>}

    <section className="panel"><div className="panel-title"><h2>Daily Rejection Detail</h2><span>{rows.length} rows</span></div><div className="table-wrap"><table><thead><tr><th>Date</th><th>Shift</th><th>Plant</th><th>Product</th><th>Detection Process</th><th>Responsible Process</th><th>Machine</th><th>Phenomenon</th><th>Reject</th><th>Denominator</th><th>PPM</th><th>Remark</th><th>Action</th></tr></thead><tbody>{rows.map(r=><tr key={r.id}><td>{r.date}</td><td>{r.shift}</td><td>{r.plant||'—'}</td><td>{r.product}</td><td>{r.detection_process||'—'}</td><td>{r.responsible_process||'—'}</td><td>{r.machine||'—'}</td><td>{r.phenomenon}</td><td><b>{num(r.reject_qty)}</b></td><td>{r.denominator_qty==null?'Pending':`${num(r.denominator_qty)} (${r.denominator_source})`}</td><td>{r.ppm==null?'Pending':Math.round(r.ppm).toLocaleString('en-IN')}</td><td>{r.remark||''}</td><td>{r.action?<a href="/actions">{r.action.action_no} • {r.action.status}</a>:<button className="small" onClick={()=>raiseAction(r.id)}>Raise Action</button>}</td></tr>)}</tbody></table></div></section>
  </>
}
