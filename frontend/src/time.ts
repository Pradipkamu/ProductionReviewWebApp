const IST_TIME_ZONE = 'Asia/Kolkata'

function parseBackendTimestamp(value: unknown): Date | null {
  if (!value) return null
  const raw = String(value)
  const normalized = /[zZ]|[+-]\d\d:\d\d$/.test(raw) ? raw : `${raw}Z`
  const parsed = new Date(normalized)
  return Number.isNaN(parsed.getTime()) ? null : parsed
}

export function formatIST(value: unknown, seconds = false): string {
  if (!value) return '—'
  const parsed = parseBackendTimestamp(value)
  if (!parsed) return String(value)
  return new Intl.DateTimeFormat('en-IN', {
    timeZone: IST_TIME_ZONE, year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', ...(seconds ? { second: '2-digit' as const } : {}), hour12: false,
  }).format(parsed).replace(',', '') + ' IST'
}

export function dateIST(date = new Date()): string {
  const parts = new Intl.DateTimeFormat('en-CA', {timeZone: IST_TIME_ZONE, year: 'numeric', month: '2-digit', day: '2-digit'}).formatToParts(date)
  const get = (type: string) => parts.find(p => p.type === type)?.value || ''
  return `${get('year')}-${get('month')}-${get('day')}`
}

export function monthIST(date = new Date()): string { return dateIST(date).slice(0, 7) }

export function istLocalToUTC(value: string): string | null {
  if (!value) return null
  const m=value.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?$/)
  if (!m) return null
  const [,y,mo,d,h,mi,s='00']=m
  return new Date(Date.UTC(+y,+mo-1,+d,+h,+mi,+s)-330*60*1000).toISOString()
}
