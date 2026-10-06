import { num } from './UI'

export type DailyPoint = {date:string, plan:number|null, actual:number|null}
const dateLabel = (date:string) => new Date(date+'T00:00:00').toLocaleDateString('en-IN',{day:'2-digit',month:'short'})

// The API supplies working dates only. Keep null separate from recorded zero.
export default function ProcessDailyChart({rows,stage}:{rows:DailyPoint[],stage:string}) {
  if (!rows.length) return <div className="empty">No working dates in this period.</div>
  const width=Math.max(820,rows.length*92),height=320,pad={left:64,right:72,top:44,bottom:54}
  const innerHeight=height-pad.top-pad.bottom,group=(width-pad.left-pad.right)/rows.length
  const qtyMax=Math.max(1,...rows.flatMap(r=>[r.plan??0,r.actual??0]))
  const achievement=rows.map(r=>r.plan!=null&&r.actual!=null&&r.plan>0?r.actual/r.plan*100:null)
  const rawPctMax=Math.max(100,...achievement.filter((v):v is number=>v!=null))
  const pctStep=rawPctMax<=125?25:Math.max(25,Math.ceil((rawPctMax/5)/25)*25)
  const pctMax=Math.max(125,Math.ceil(rawPctMax/pctStep)*pctStep)
  const pctTicks=Array.from({length:Math.floor(pctMax/pctStep)+1},(_,i)=>i*pctStep)
  if(!pctTicks.includes(100))pctTicks.push(100)
  pctTicks.sort((a,b)=>a-b)
  const yQty=(value:number)=>pad.top+innerHeight*(1-value/qtyMax)
  const yPct=(value:number)=>pad.top+innerHeight*(1-Math.max(0,Math.min(pctMax,value))/pctMax)
  const center=(index:number)=>pad.left+group*(index+.5)
  const segments:{index:number,value:number}[][]=[]
  let segment:{index:number,value:number}[]=[]
  achievement.forEach((value,index)=>{if(value==null){if(segment.length){segments.push(segment);segment=[]}}else segment.push({index,value})})
  if(segment.length)segments.push(segment)

  return <>
    <p>Blue: Plan • Green: Actual • Achievement % uses the right axis • target 100% • Pending/Missing means no record; 0 means recorded zero.</p>
    <div className="svg-scroll"><svg className="report-svg" role="img" aria-label={`${stage}: daily plan versus actual with achievement percentage; working days only`} width={width} height={height} viewBox={`0 0 ${width} ${height}`} style={{width,height,minWidth:'100%'}}>
      {[0,.25,.5,.75,1].map(t=><g key={t}><line className="grid-line" x1={pad.left} y1={yQty(qtyMax*t)} x2={width-pad.right} y2={yQty(qtyMax*t)}/><text className="axis-text" x={pad.left-8} y={yQty(qtyMax*t)+4} textAnchor="end">{num(qtyMax*t)}</text></g>)}
      {pctTicks.map(v=><text key={`pct-${v}`} className="axis-text" x={width-pad.right+10} y={yPct(v)+4}>{v}%</text>)}
      <line className="target-line" x1={pad.left} y1={yPct(100)} x2={width-pad.right} y2={yPct(100)}/>
      {rows.map((row,index)=>{
        const cx=center(index)
        return <g key={row.date}>
          {(['plan','actual'] as const).map((key,i)=>{
            const value=row[key],x=cx+(i===0?-12:12),missing=key==='plan'?'Pending':'Missing'
            return <g key={key}>
              {value!=null&&<rect x={x-10} y={yQty(value)} width={20} height={Math.max(0,innerHeight*value/qtyMax)} rx={3} className={key==='plan'?'chart-plan':'chart-actual'}><title>{`${row.date} ${key}: ${num(value)}`}</title></rect>}
              <text className="data-label" x={x} y={value==null?yQty(0)-8:Math.max(16,yQty(value)-7)} textAnchor="middle">{value==null?missing:num(value)}</text>
            </g>
          })}
          <text className="axis-text" x={cx} y={height-25} textAnchor="middle">{dateLabel(row.date)}</text>
        </g>
      })}
      {segments.map((items,i)=><polyline key={i} points={items.map(p=>`${center(p.index)},${yPct(p.value)}`).join(' ')} fill="none" className="compliance-line"/>)}
      {achievement.map((value,index)=>value==null?null:<g key={`achievement-${rows[index].date}`}><circle cx={center(index)} cy={yPct(value)} r="4.5" className={value>=100?'dot-good':value>=90?'dot-watch':'dot-bad'}><title>{`${rows[index].date} Achievement: ${value.toFixed(1)}%`}</title></circle><text className="achievement-label" x={center(index)} y={Math.max(16,yPct(value)-9)} textAnchor="middle">{value.toFixed(1)}%</text></g>)}
      <line className="axis-line" x1={pad.left} y1={yQty(0)} x2={width-pad.right} y2={yQty(0)}/>
      <line className="axis-line" x1={width-pad.right} y1={pad.top} x2={width-pad.right} y2={yQty(0)}/>
      <text className="axis-text" x={width-8} y={pad.top-12} textAnchor="end">Achievement %</text>
    </svg></div>
    <div className="table-wrap"><table aria-label={`${stage} daily quantities`}><thead><tr><th>Quantity</th>{rows.map(r=><th key={r.date}>{dateLabel(r.date)}</th>)}</tr></thead><tbody>
      <tr><th>Plan</th>{rows.map(r=><td key={r.date}>{r.plan==null?'Pending':num(r.plan)}</td>)}</tr>
      <tr><th>Actual</th>{rows.map(r=><td key={r.date}>{r.actual==null?'Missing':num(r.actual)}</td>)}</tr>
    </tbody></table></div>
  </>
}
