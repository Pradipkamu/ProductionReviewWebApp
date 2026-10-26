export function Kpi({ label, value, tone='neutral', sub }: { label: string, value: string|number, tone?: string, sub?: string }) {
  return <div className={`kpi ${tone}`}><span>{label}</span><strong>{value}</strong>{sub && <small>{sub}</small>}</div>
}

export function Status({ value }: { value: string }) {
  const cls = value.toLowerCase().replaceAll(' ', '-')
  return <span className={`status ${cls}`} role="status" aria-label={`Status: ${value}`}>{value}</span>
}

export function PageHeader({ title, subtitle, actions, eyebrow }: { title: string, subtitle?: string, actions?: React.ReactNode, eyebrow?: string }) {
  return <header className="page-header">
    <div className="page-heading-copy">
      {eyebrow&&<span className="page-eyebrow">{eyebrow}</span>}
      <h1>{title}</h1>
      {subtitle && <p>{subtitle}</p>}
    </div>
    {actions&&<div className="page-header-actions">{actions}</div>}
  </header>
}

export function SectionHeader({ title, subtitle, actions }: { title:string, subtitle?:string, actions?:React.ReactNode }) {
  return <div className="section-header">
    <div><h2>{title}</h2>{subtitle&&<p>{subtitle}</p>}</div>
    {actions&&<div className="section-header-actions">{actions}</div>}
  </div>
}

export function Panel({ title, subtitle, actions, children, className='' }: { title?:string, subtitle?:string, actions?:React.ReactNode, children:React.ReactNode, className?:string }) {
  return <section className={`panel ${className}`.trim()}>
    {(title||subtitle||actions)&&<div className="panel-heading">
      <div>{title&&<h2>{title}</h2>}{subtitle&&<p>{subtitle}</p>}</div>
      {actions&&<div className="panel-heading-actions">{actions}</div>}
    </div>}
    {children}
  </section>
}

export function EmptyState({ title, description, action }: { title:string, description?:string, action?:React.ReactNode }) {
  return <div className="empty-state">
    <span className="empty-state-mark" aria-hidden="true">—</span>
    <strong>{title}</strong>
    {description&&<p>{description}</p>}
    {action&&<div className="empty-state-action">{action}</div>}
  </div>
}

export const money = (v: number) => new Intl.NumberFormat('en-IN', {style:'currency', currency:'INR', maximumFractionDigits:0}).format(v)
export const num = (v: number) => new Intl.NumberFormat('en-IN', {maximumFractionDigits:0}).format(v)
export const pct = (v: number|null|undefined) => v == null ? '—' : `${(v*100).toFixed(1)}%`
