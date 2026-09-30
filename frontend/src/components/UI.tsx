export function Kpi({ label, value, tone='neutral', sub }: { label: string, value: string|number, tone?: string, sub?: string }) {
  return <div className={`kpi ${tone}`}><span>{label}</span><strong>{value}</strong>{sub && <small>{sub}</small>}</div>
}
export function Status({ value }: { value: string }) {
  const cls = value.toLowerCase().replaceAll(' ', '-')
  return <span className={`status ${cls}`}>{value}</span>
}
export function PageHeader({ title, subtitle, actions }: { title: string, subtitle?: string, actions?: React.ReactNode }) {
  return <header className="page-header"><div><h1>{title}</h1>{subtitle && <p>{subtitle}</p>}</div><div>{actions}</div></header>
}
export const money = (v: number) => new Intl.NumberFormat('en-IN', {style:'currency', currency:'INR', maximumFractionDigits:0}).format(v)
export const num = (v: number) => new Intl.NumberFormat('en-IN', {maximumFractionDigits:0}).format(v)
export const pct = (v: number|null|undefined) => v == null ? '—' : `${(v*100).toFixed(1)}%`
