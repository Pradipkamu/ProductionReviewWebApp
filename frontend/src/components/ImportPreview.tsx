import { useState } from 'react'
import { api } from '../api'

export default function ImportPreview({kind,onComplete}:{kind:string,onComplete?:()=>void}){
 const [file,setFile]=useState<File|null>(null),[result,setResult]=useState<any>(null),[error,setError]=useState(''),[busy,setBusy]=useState(false),[changeReason,setChangeReason]=useState('')
 const isHistorical=kind==='quality-history'
 const requiresReason=isHistorical&&Number(result?.counts?.updated||0)>0

 async function preview(){
  if(!file)return
  setBusy(true);setError('');setResult(null)
  try{
   const fd=new FormData();fd.append('file',file)
   setResult(await api(`/import/preview/${kind}`,{method:'POST',body:fd}))
  }catch(e:any){setError(e.message)}finally{setBusy(false)}
 }

 async function confirm(){
  if(requiresReason&&!changeReason.trim()){
   setError('A Change Reason is required when correcting existing historical rejection records.')
   return
  }
  setBusy(true);setError('')
  try{
   if(isHistorical&&changeReason.trim())sessionStorage.setItem('changeReason',changeReason.trim())
   setResult(await api('/import/confirm',{method:'POST',body:JSON.stringify({preview_token:result.preview_token})}))
   if(isHistorical){sessionStorage.removeItem('changeReason');setChangeReason('')}
   onComplete?.()
  }catch(e:any){
   if(isHistorical)sessionStorage.removeItem('changeReason')
   setError(e.message)
  }finally{setBusy(false)}
 }

 return <><input type="file" accept=".xlsx,.xlsm" onChange={e=>{setFile(e.target.files?.[0]||null);setResult(null);setError('')}}/><button disabled={!file||busy} onClick={preview}>{busy?'Processing…':'Preview workbook'}</button>{error&&<p className="error">{error}</p>}{result&&<div><p className="notice">{result.message||'No rows have been committed. Review counts, errors and warnings before confirmation.'}</p><table><thead><tr><th>New</th><th>Updated</th><th>Unchanged</th><th>Rejected</th></tr></thead><tbody><tr>{['new','updated','unchanged','rejected'].map(k=><td key={k}>{result.counts?.[k]??0}</td>)}</tr></tbody></table>{result.count_scope&&<p>{result.count_scope}</p>}{result.stats?.customer_mis&&<table><thead><tr><th>Section</th><th>New</th><th>Updated</th><th>Unchanged</th></tr></thead><tbody><tr><td>Customer MIS</td><td>{result.stats.customer_mis.mis_created}</td><td>{result.stats.customer_mis.mis_updated}</td><td>{result.stats.customer_mis.mis_unchanged}</td></tr><tr><td>Stage actuals</td><td>{result.stats.stage_actuals.new}</td><td>{result.stats.stage_actuals.updated}</td><td>{result.stats.stage_actuals.unchanged}</td></tr></tbody></table>}{result.errors?.length>0&&<div className="error"><h3>Row errors</h3><ul>{result.errors.map((x:string,i:number)=><li key={i}>{x}</li>)}</ul></div>}{result.warnings?.length>0&&<div className="warning-box"><h3>Warnings</h3><ul>{result.warnings.map((x:string,i:number)=><li key={i}>{x}</li>)}</ul></div>}{isHistorical&&result.can_confirm&&<label>Change Reason{requiresReason&&' *'}<input value={changeReason} onChange={e=>setChangeReason(e.target.value)} placeholder="e.g. Correct Casting/Machining classification from previous historical import"/></label>}<details><summary>Detailed import results</summary><pre>{JSON.stringify(result.stats,null,2)}</pre></details>{result.can_confirm&&<button disabled={busy||(requiresReason&&!changeReason.trim())} onClick={confirm}>Confirm and commit all rows</button>}</div>}</>
}
