import { money, num, pct } from './UI'

type Point = { label:string, plan:number, actual:number, compliance:number|null, gap:number, start?:string, end?:string }

type Metric='qty'|'sales'|'tonnage'
function formatValue(v:number, metric:Metric){ return metric==='sales' ? money(v) : metric==='tonnage' ? `${num(v)} MT` : num(v) }

export function PlanActualChart({rows, metric, height=260,onSelect}:{rows:Point[],metric:Metric,height?:number,onSelect?:(row:Point)=>void}){
  if(!rows.length) return <div className="empty">No data for this period.</div>
  const W=Math.max(760, rows.length*64), H=height, pad={l:58,r:18,t:18,b:58}
  const innerW=W-pad.l-pad.r, innerH=H-pad.t-pad.b
  const max=Math.max(1,...rows.flatMap(r=>[r.plan,r.actual]))
  const group=innerW/rows.length, bw=Math.min(20,group*.3)
  const y=(v:number)=>pad.t+innerH-(v/max)*innerH
  return <div className="svg-scroll"><svg className="report-svg" width={W} height={H} viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="xMidYMid meet" style={{width:W,height:H,minWidth:'100%'}}>
    {[0,.25,.5,.75,1].map(t=>{const yy=pad.t+innerH-(t*innerH);return <g key={t}><line x1={pad.l} y1={yy} x2={W-pad.r} y2={yy} className="grid-line"/><text x={pad.l-8} y={yy+4} textAnchor="end" className="axis-text">{metric==='sales'?new Intl.NumberFormat('en-IN',{notation:'compact'}).format(max*t):num(max*t)}</text></g>})}
    {rows.map((r,i)=>{const cx=pad.l+group*i+group/2; const ph=innerH*(r.plan/max), ah=innerH*(r.actual/max);return <g key={`${r.label}-${i}`} role={onSelect?"button":undefined} tabIndex={onSelect?0:undefined} onClick={()=>onSelect?.(r)} onKeyDown={e=>{if(e.key==="Enter")onSelect?.(r)}} style={{cursor:onSelect?"pointer":undefined}}>
      <rect x={cx-bw-2} y={y(r.plan)} width={bw} height={Math.max(0,ph)} rx="3" className="chart-plan"><title>{`${r.label} Plan: ${formatValue(r.plan,metric)}`}</title></rect>
      <rect x={cx+2} y={y(r.actual)} width={bw} height={Math.max(0,ah)} rx="3" className="chart-actual"><title>{`${r.label} Actual: ${formatValue(r.actual,metric)} • Compliance: ${pct(r.compliance)}`}</title></rect>
      <text x={cx-bw/2-2} y={Math.max(11,y(r.plan)-5)} textAnchor="middle" className="data-label">{metric==='sales'?new Intl.NumberFormat('en-IN',{notation:'compact',maximumFractionDigits:1}).format(r.plan):num(r.plan)}</text>
      <text x={cx+bw/2+2} y={Math.max(11,y(r.actual)-5)} textAnchor="middle" className="data-label">{metric==='sales'?new Intl.NumberFormat('en-IN',{notation:'compact',maximumFractionDigits:1}).format(r.actual):num(r.actual)}</text>
      <text x={cx} y={H-34} textAnchor="middle" className="axis-text x-label">{r.label}</text>
    </g>})}
    <line x1={pad.l} y1={pad.t+innerH} x2={W-pad.r} y2={pad.t+innerH} className="axis-line"/>
  </svg></div>
}

export function ComplianceLineChart({rows,height=245,onSelect}:{rows:Point[],height?:number,onSelect?:(row:Point)=>void}){
  if(!rows.length) return <div className="empty">No compliance data for this period.</div>
  const W=Math.max(760,rows.length*64),H=height,pad={l:52,r:20,t:20,b:58},innerW=W-pad.l-pad.r,innerH=H-pad.t-pad.b
  const vals=rows.map(r=>(r.compliance??0)*100)
  const max=Math.max(120,Math.ceil(Math.max(...vals,100)/20)*20), group=innerW/Math.max(1,rows.length-1)
  const x=(i:number)=>rows.length===1?pad.l+innerW/2:pad.l+group*i
  const y=(v:number)=>pad.t+innerH-(Math.max(0,Math.min(max,v))/max)*innerH
  const pts=rows.map((r,i)=>`${x(i)},${y((r.compliance??0)*100)}`).join(' ')
  return <div className="svg-scroll"><svg className="report-svg" width={W} height={H} viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="xMidYMid meet" style={{width:W,height:H,minWidth:'100%'}}>
    {[0,25,50,75,100,125].filter(v=>v<=max).map(v=><g key={v}><line x1={pad.l} y1={y(v)} x2={W-pad.r} y2={y(v)} className={v===100?'target-line':'grid-line'}/><text x={pad.l-8} y={y(v)+4} textAnchor="end" className="axis-text">{v}%</text></g>)}
    <polyline points={pts} fill="none" className="compliance-line"/>
    {rows.map((r,i)=>{const v=(r.compliance??0)*100;return <g key={`${r.label}-${i}`} role={onSelect?"button":undefined} tabIndex={onSelect?0:undefined} onClick={()=>onSelect?.(r)} onKeyDown={e=>{if(e.key==="Enter")onSelect?.(r)}} style={{cursor:onSelect?"pointer":undefined}}><circle cx={x(i)} cy={y(v)} r="4.5" className={v>=100?'dot-good':v>=90?'dot-watch':'dot-bad'}><title>{`${r.label}: ${v.toFixed(1)}%`}</title></circle><text x={x(i)} y={Math.max(11,y(v)-9)} textAnchor="middle" className="data-label">{v.toFixed(1)}%</text><text x={x(i)} y={H-34} textAnchor="middle" className="axis-text x-label">{r.label}</text></g>})}
  </svg></div>
}

export function PartComplianceBars({rows,metric}:{rows:any[],metric:Metric}){
  if(!rows.length) return <div className="empty">No part-wise data for this period.</div>
  return <div className="part-bars">{rows.map(r=>{const c=(r.compliance??0)*100;return <div className="part-bar-row" key={r.product_id}>
    <div className="part-name"><b>{r.product}</b><small>{formatValue(r.actual,metric)} / {formatValue(r.plan,metric)}</small></div>
    <div className="part-track"><div className={`part-fill ${c>=100?'good':c>=90?'watch':'bad'}`} style={{width:`${Math.min(130,Math.max(0,c))/1.3}%`}}></div><i className="part-target"></i></div>
    <strong className={c<90?'neg':c>=100?'pos':''}>{r.compliance==null?'—':`${c.toFixed(1)}%`}</strong>
    <span className={r.gap<0?'neg':'pos'}>{formatValue(r.gap,metric)}</span>
  </div>})}</div>
}

export function NamedComplianceBars({rows,metric}:{rows:any[],metric:Metric}){
  if(!rows.length) return <div className="empty">No grouped data for this period.</div>
  return <div className="part-bars">{rows.map((r:any,i:number)=>{const c=(r.compliance??0)*100;return <div className="part-bar-row" key={`${r.name}-${i}`}>
    <div className="part-name"><b>{r.name}</b><small>{formatValue(r.actual,metric)} / {formatValue(r.plan,metric)}</small></div>
    <div className="part-track"><div className={`part-fill ${c>=100?'good':c>=90?'watch':'bad'}`} style={{width:`${Math.min(130,Math.max(0,c))/1.3}%`}}></div><i className="part-target"></i></div>
    <strong className={c<90?'neg':c>=100?'pos':''}>{r.compliance==null?'—':`${c.toFixed(1)}%`}</strong>
    <span className={r.gap<0?'neg':'pos'}>{formatValue(r.gap,metric)}</span>
  </div>})}</div>
}

export function PercentTrendChart({rows,series,height=260,target}:{rows:any[],series:{key:string,label:string}[],height?:number,target?:number}){
  if(!rows?.length) return <div className="empty">No trend data for this period.</div>
  const W=Math.max(760,rows.length*70),H=height,pad={l:54,r:20,t:25,b:58},innerW=W-pad.l-pad.r,innerH=H-pad.t-pad.b
  const values=rows.flatMap(r=>series.map(s=>Number(r[s.key]||0)*100))
  const max=Math.max(100,target||0,Math.ceil(Math.max(...values,0)/10)*10)
  const x=(i:number)=>rows.length===1?pad.l+innerW/2:pad.l+(innerW/(rows.length-1))*i
  const y=(v:number)=>pad.t+innerH-(Math.max(0,Math.min(max,v))/max)*innerH
  const classes=['series-a','series-b','series-c','series-d']
  return <div className="svg-scroll"><svg className="report-svg" width={W} height={H} viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="xMidYMid meet" style={{width:W,height:H,minWidth:'100%'}}>
    {[0,25,50,75,100,125].filter(v=>v<=max).map(v=><g key={v}><line x1={pad.l} y1={y(v)} x2={W-pad.r} y2={y(v)} className={(target!=null&&Math.abs(v-target)<.1)?'target-line':'grid-line'}/><text x={pad.l-8} y={y(v)+4} textAnchor="end" className="axis-text">{v}%</text></g>)}
    {target!=null&&![0,25,50,75,100,125].includes(target)&&<line x1={pad.l} y1={y(target)} x2={W-pad.r} y2={y(target)} className="target-line"/>}
    {series.map((s,si)=>{const pts=rows.map((r,i)=>`${x(i)},${y(Number(r[s.key]||0)*100)}`).join(' ');return <g key={s.key}><polyline points={pts} fill="none" className={`trend-line ${classes[si%classes.length]}`}/>{rows.map((r,i)=>{const v=Number(r[s.key]||0)*100;return <g key={i}><circle cx={x(i)} cy={y(v)} r="3.8" className={`trend-dot ${classes[si%classes.length]}`}><title>{`${s.label}: ${v.toFixed(1)}%`}</title></circle><text x={x(i)} y={Math.max(10,y(v)-8-(si%2)*11)} textAnchor="middle" className="data-label">{v.toFixed(1)}%</text></g>})}</g>})}
    {rows.map((r,i)=><text key={i} x={x(i)} y={H-34} textAnchor="middle" className="axis-text x-label">{r.label}</text>)}
  </svg><div className="chart-legend">{series.map((s,i)=><span key={s.key}><i className={classes[i%classes.length]}></i>{s.label}</span>)}{target!=null&&<span><i className="target"></i>Target {target}%</span>}</div></div>
}

export function ValueTrendChart({rows,keyName='value',label='Value',suffix='',prefix='',height=250,onSelect}:{rows:any[],keyName?:string,label?:string,suffix?:string,prefix?:string,height?:number,onSelect?:(row:any)=>void}){
  if(!rows?.length) return <div className="empty">No trend data for this period.</div>
  const W=Math.max(760,rows.length*70),H=height,pad={l:62,r:20,t:20,b:58},innerW=W-pad.l-pad.r,innerH=H-pad.t-pad.b
  const vals=rows.map(r=>Number(r[keyName]||0)),max=Math.max(1,...vals)
  const x=(i:number)=>rows.length===1?pad.l+innerW/2:pad.l+(innerW/(rows.length-1))*i
  const y=(v:number)=>pad.t+innerH-(v/max)*innerH
  const pts=rows.map((r,i)=>`${x(i)},${y(Number(r[keyName]||0))}`).join(' ')
  return <div className="svg-scroll"><svg className="report-svg" width={W} height={H} viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="xMidYMid meet" style={{width:W,height:H,minWidth:'100%'}}>
    {[0,.25,.5,.75,1].map(t=>{const yy=pad.t+innerH-innerH*t;return <g key={t}><line x1={pad.l} y1={yy} x2={W-pad.r} y2={yy} className="grid-line"/><text x={pad.l-8} y={yy+4} textAnchor="end" className="axis-text">{new Intl.NumberFormat('en-IN',{notation:'compact'}).format(max*t)}</text></g>})}
    <polyline points={pts} fill="none" className="trend-line series-a"/>{rows.map((r,i)=>{const v=Number(r[keyName]||0);return <g key={i} role={onSelect?"button":undefined} tabIndex={onSelect?0:undefined} onClick={()=>onSelect?.(r)} onKeyDown={e=>{if(e.key==="Enter")onSelect?.(r)}} style={{cursor:onSelect?"pointer":undefined}}><circle cx={x(i)} cy={y(v)} r="4" className="trend-dot series-a"><title>{`${label}: ${prefix}${v.toLocaleString('en-IN')}${suffix}`}</title></circle><text x={x(i)} y={Math.max(11,y(v)-9)} textAnchor="middle" className="data-label">{prefix}{new Intl.NumberFormat('en-IN',{maximumFractionDigits:1,notation:Math.abs(v)>=10000?'compact':'standard'}).format(v)}{suffix}</text><text x={x(i)} y={H-34} textAnchor="middle" className="axis-text x-label">{r.label}</text></g>})}
  </svg></div>
}

export function RankedBars({rows,valueKey='value',labelKey='name',valueLabel='Value',suffix='',prefix=''}:{rows:any[],valueKey?:string,labelKey?:string,valueLabel?:string,suffix?:string,prefix?:string}){
  if(!rows?.length) return <div className="empty">No data available.</div>
  const max=Math.max(1,...rows.map(r=>Math.abs(Number(r[valueKey]||0))))
  return <div className="rank-bars">{rows.map((r:any,i:number)=>{const v=Number(r[valueKey]||0);return <div className="rank-row" key={`${r[labelKey]}-${i}`}><div className="rank-name"><b>{r[labelKey]}</b>{r.sub&&<small>{r.sub}</small>}</div><div className="rank-track"><div className="rank-fill" style={{width:`${Math.min(100,Math.abs(v)/max*100)}%`}}></div></div><strong>{prefix}{new Intl.NumberFormat('en-IN',{maximumFractionDigits:1}).format(v)}{suffix}</strong></div>})}</div>
}

export function ProcessFunnelChart({rows}:{rows:any[]}){
  if(!rows?.length) return <div className="empty">Select a part with an active route to see the process funnel.</div>
  const max=Math.max(1,...rows.flatMap(r=>[Number(r.plan||0),Number(r.actual||0)]))
  return <div className="funnel-chart">{rows.map((r:any,i:number)=>{const aw=Math.max(2,Number(r.actual||0)/max*100),pw=Math.max(2,Number(r.plan||0)/max*100);return <div className="funnel-step" key={r.route_operation_id}><div className="funnel-label"><b>{r.operation}</b><span>{r.vendor||r.type}</span></div><div className="funnel-bars"><div className="funnel-plan" style={{width:`${pw}%`}}><span>Plan {num(r.plan)}</span></div><div className={`funnel-actual ${(r.compliance??0)<.9?'bad':(r.compliance??0)<1?'watch':'good'}`} style={{width:`${aw}%`}}><span>Actual {num(r.actual)}</span></div></div><div className="funnel-kpi"><strong>{pct(r.compliance)}</strong><small>WIP {num(r.display_wip||0)}</small></div>{i<rows.length-1&&<div className="funnel-arrow">↓</div>}</div>})}</div>
}
