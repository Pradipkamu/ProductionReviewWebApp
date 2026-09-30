import { useEffect, useState } from 'react'
import { api } from '../api'
import { ScopeFilters, ScopeValues, appendScope } from '../components/ScopeFilters'
import { Kpi, PageHeader, money, num, pct } from '../components/UI'
function month(){return new Date().toISOString().slice(0,7)+'-01'}
const emptyScope:ScopeValues={plant:[],productGroup:[],customerId:[],productId:[]}
export default function Analytics(){
 const [m,setM]=useState(month());const [rows,setRows]=useState<any[]>([]);const [acts,setActs]=useState<any>(null);const [scope,setScope]=useState<ScopeValues>(emptyScope);const [options,setOptions]=useState<any>({});const [products,setProducts]=useState<any[]>([])
 useEffect(()=>{Promise.all([api('/masters/filter-options'),api('/masters/products')]).then(([o,p]:any)=>{setOptions(o);setProducts(p)})},[])
 useEffect(()=>{const q=appendScope(new URLSearchParams({end_month:m,months:'12'}),scope);api(`/analytics/monthly?${q}`).then(setRows);const a=appendScope(new URLSearchParams(),scope);api(`/analytics/actions?${a}`).then(setActs)},[m,scope.plant,scope.productGroup,scope.customerId,scope.productId])
 const max=Math.max(1,...rows.map(r=>Math.max(r.plan_sales,r.actual_sales)))
 return <><PageHeader title="History & Analytics" subtitle="Month-over-month plant/group/customer/part performance and action trends." actions={<input type="date" value={m} onChange={e=>setM(e.target.value)}/>}/>
 <ScopeFilters value={scope} onChange={setScope} options={options} products={products}/>
 {acts&&<div className="kpi-grid"><Kpi label="Actions raised" value={acts.total}/><Kpi label="Open" value={acts.open} tone={acts.open?'warn':'good'}/><Kpi label="Closed" value={acts.closed} tone="good"/></div>}
 <section className="panel"><h2>Month-over-month sales</h2><div className="bar-list">{rows.map(r=><div className="bar-row" key={r.month}><b>{r.month}</b><div className="bars"><div className="bar plan" style={{width:`${(r.plan_sales/max)*100}%`}} title={money(r.plan_sales)}></div><div className="bar actual" style={{width:`${(r.actual_sales/max)*100}%`}} title={money(r.actual_sales)}></div></div><span>{pct(r.achievement)}</span><span className={r.sales_gap<0?'neg':'pos'}>{money(r.sales_gap)}</span></div>)}</div><div className="legend"><i className="plan"></i>Plan <i className="actual"></i>Actual</div></section>
 <section className="panel"><h2>Month-over-month tonnage</h2><div className="table-wrap"><table><thead><tr><th>Month</th><th>Plan MT</th><th>Actual MT</th><th>Gap MT</th></tr></thead><tbody>{rows.map(r=><tr key={r.month}><td>{r.month}</td><td>{num(r.plan_tonnage_mt)}</td><td>{num(r.actual_tonnage_mt)}</td><td className={(r.actual_tonnage_mt-r.plan_tonnage_mt)<0?'neg':'pos'}>{num(r.actual_tonnage_mt-r.plan_tonnage_mt)}</td></tr>)}</tbody></table></div></section>
 <section className="panel"><h2>Action reason Pareto</h2>{(acts?.by_reason||[]).map((r:any)=><div className="master-row" key={r.reason}><b>{r.reason}</b><span>{r.count}</span></div>)}</section></>
}
