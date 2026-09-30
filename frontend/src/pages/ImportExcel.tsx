import { PageHeader } from '../components/UI'
import ImportPreview from '../components/ImportPreview'
export default function ImportExcel(){
 return <><PageHeader title="Excel Import Preview" subtitle="Preview checks all data in a transaction that is rolled back. Confirmation rechecks for changes and commits the workbook together."/>{[
  ['excel','Current production workbook','PBI_Products + PBI_Fact_Daily'],
  ['historical-sales-prices','Historical Sales Price','Effective-dated prices; import before historical MIS'],
  ['historical-daily-mis','Historical Daily MIS','Current product names; plan and actual'],
  ['quality-daily','Daily Rejection','Use the Daily Rejection template from Quality'],
  ['quality-history','Historical Rejection','Monthly history with matching MIS dispatch denominator']
 ].map(([kind,title,note])=><section className="panel" key={kind}><h2>{title}</h2><p>{note}</p><ImportPreview kind={kind}/></section>)}</>
}
