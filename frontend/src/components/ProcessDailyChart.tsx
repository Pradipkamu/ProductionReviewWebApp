import { num } from './UI'

export type DailyPoint = {date:string, plan:number|null, actual:number|null}
const dateLabel = (date:string) => new Date(date+'T00:00:00').toLocaleDateString('en-IN',{day:'2-digit',month:'short'})

// The API supplies working dates only. Keep null separate from recorded zero.
export default function ProcessDailyChart({rows,stage}:{rows:DailyPoint[],stage:string}) {
  if (!rows.length) return <div className="empty">No working dates in this period.</div>
  const width=Math.max(780,rows.length*92),height=320,pad={left:64,right:24,top:44,bottom:54}
  const innerHeight=height-pad.top-pad.bottom,group=(width-pad.left-pad.right)/rows.length
  const max=Math.max(1,...rows.flatMap(r=>[r.plan??0,r.actual??0]))
  const y=(value:number)=>pad.top+innerHeight*(1-value/max)
  return <>
    <p>Blue: Plan • Green: Actual • Pending/Missing means no record; 0 means recorded zero.</p>
    <div className="svg-scroll"><svg className="report-svg" role="img" aria-label={`${stage}: daily plan versus actual; working days only`} width={width} height={height} viewBox={`0 0 ${width} ${height}`} style={{width,height,minWidth:'100%'}}>
      {[0,.25,.5,.75,1].map(t=><g key={t}><line className="grid-line" x1={pad.left} y1={y(max*t)} x2={width-pad.right} y2={y(max*t)}/><text className="axis-text" x={pad.left-8} y={y(max*t)+4} textAnchor="end">{num(max*t)}</text></g>)}
      {rows.map((row,index)=>{
        const center=pad.left+group*(index+.5)
        return <g key={row.date}>
          {(['plan','actual'] as const).map((key,i)=>{
            const value=row[key],x=center+(i===0?-12:12),missing=key==='plan'?'Pending':'Missing'
            return <g key={key}>
              {value!=null&&<rect x={x-10} y={y(value)} width={20} height={Math.max(0,innerHeight*value/max)} rx={3} className={key==='plan'?'chart-plan':'chart-actual'}><title>{`${row.date} ${key}: ${num(value)}`}</title></rect>}
              <text className="data-label" x={x} y={value==null?y(0)-8:Math.max(16,y(value)-7)} textAnchor="middle">{value==null?missing:num(value)}</text>
            </g>
          })}
          {row.plan!=null&&row.actual!=null&&row.plan>0&&<text className="achievement-label" x={center} y={Math.max(18,Math.min(y(row.plan),y(row.actual))-22)} textAnchor="middle">{`${(row.actual/row.plan*100).toFixed(1)}%`}</text>}
          <text className="axis-text" x={center} y={height-25} textAnchor="middle">{dateLabel(row.date)}</text>
        </g>
      })}
      <line className="axis-line" x1={pad.left} y1={y(0)} x2={width-pad.right} y2={y(0)}/>
    </svg></div>
    <div className="table-wrap"><table aria-label={`${stage} daily quantities`}><thead><tr><th>Quantity</th>{rows.map(r=><th key={r.date}>{dateLabel(r.date)}</th>)}</tr></thead><tbody>
      <tr><th>Plan</th>{rows.map(r=><td key={r.date}>{r.plan==null?'Pending':num(r.plan)}</td>)}</tr>
      <tr><th>Actual</th>{rows.map(r=><td key={r.date}>{r.actual==null?'Missing':num(r.actual)}</td>)}</tr>
      <tr><th>Achievement %</th>{rows.map(r=><td key={r.date}>{r.plan!=null&&r.actual!=null&&r.plan>0?`${(r.actual/r.plan*100).toFixed(1)}%`:'—'}</td>)}</tr>
    </tbody></table></div>
  </>
}
