import { downloadApi } from '../api'
import { useState } from 'react'
import { PageHeader } from '../components/UI'
import ImportPreview from '../components/ImportPreview'
export default function ImportExcel(){
 const [error,setError]=useState('');
 async function template(){try{await downloadApi('/flows/template','Production_Process_Upload_v0.4.0.xlsx')}catch(e:any){setError(e.message)}}
 return <><PageHeader title="Excel Import Preview" subtitle="Preview checks all data in a transaction that is rolled back. Confirmation rechecks for changes and commits the workbook together."/><section className="panel"><h2>Process upload template</h2><p>Set up Flow Definition and Stage Schedules first. For normal daily use, choose Daily Production Upload once: the exported workbook must contain Daily_Actuals and Historical_Daily_MIS_Import. Admin or Planning can confirm customer plans and stage actuals together.</p><button onClick={template}>Download approved process template</button>{error&&<p className="error">{error}</p>}</section>{[
  ['daily-production','Daily Production Upload','One Preview and Confirm updates customer daily plans, dispatch and process/vendor actuals together. Use the values-only export containing both daily tabs.'],
  ['process-design','Flow Definition','Approved corrected mapping; creates a new effective-dated flow revision'],
  ['stage-schedules','Stage Schedules','Independent monthly allocations split over plant working days; reason and reference required'],
  ['stage-daily','Daily Actuals — stages only','Separate stage-only import; use Daily Production Upload for normal combined daily uploads'],
  ['excel','Current production workbook','PBI_Products + PBI_Fact_Daily'],
  ['historical-sales-prices','Historical Sales Price','Effective-dated prices; import before historical MIS'],
  ['historical-daily-mis','Historical Daily MIS','Historical or MIS-only import; use Daily Production Upload for normal combined daily uploads'],
  ['quality-daily','Daily Rejection','Use the Daily Rejection template from Quality'],
  ['quality-history','Historical Rejection','Monthly history with matching MIS dispatch denominator'],
  ['casting-daily','Casting Defects','Incoming casting defects with inspected-quantity PPM'],
  ['customer-quality-daily','Customer Rejection','Customer rejection with dispatch/received-quantity PPM']
 ].map(([kind,title,note])=><section className="panel" key={kind}><h2>{title}</h2><p>{note}</p><ImportPreview kind={kind}/></section>)}</>
}
