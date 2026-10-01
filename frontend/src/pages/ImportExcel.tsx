import { downloadApi } from '../api'
import { useState } from 'react'
import { PageHeader } from '../components/UI'
import ImportPreview from '../components/ImportPreview'
export default function ImportExcel(){
 const [error,setError]=useState('');
 async function template(){try{await downloadApi('/flows/template','Production_Process_Upload_v0.4.0.xlsx')}catch(e:any){setError(e.message)}}
 return <><PageHeader title="Excel Import Preview" subtitle="Preview checks all data in a transaction that is rolled back. Confirmation rechecks for changes and commits the workbook together."/><section className="panel"><h2>Process upload template</h2><p>Import Flow Definition first, then Stage Schedules, then Daily Actuals. Enter monthly allocated pieces for each active stage. Deferred columns are excluded.</p><button onClick={template}>Download approved process template</button>{error&&<p className="error">{error}</p>}</section>{[
  ['process-design','Flow Definition','Approved corrected mapping; creates a new effective-dated flow revision'],
  ['stage-schedules','Stage Schedules','Independent monthly allocations split over plant working days; reason and reference required'],
  ['stage-daily','Daily Actuals','Stable stage codes; parent dispatch feeds MIS; corrections require a reason'],
  ['excel','Current production workbook','PBI_Products + PBI_Fact_Daily'],
  ['historical-sales-prices','Historical Sales Price','Effective-dated prices; import before historical MIS'],
  ['historical-daily-mis','Historical Daily MIS','Current product names; plan and actual'],
  ['quality-daily','Daily Rejection','Use the Daily Rejection template from Quality'],
  ['quality-history','Historical Rejection','Monthly history with matching MIS dispatch denominator']
 ].map(([kind,title,note])=><section className="panel" key={kind}><h2>{title}</h2><p>{note}</p><ImportPreview kind={kind}/></section>)}</>
}
