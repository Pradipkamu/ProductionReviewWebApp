import { formatIST, dateIST, istLocalToUTC } from '../time'
import { useEffect, useRef, useState } from 'react'
import { api, downloadApi } from '../api'
import { MultiSelect } from '../components/MultiSelect'
import { Kpi, PageHeader, Status, money, num, pct } from '../components/UI'

type Snapshot = {
  summary: any
  control: any
  quality: any
  oee: any
  vendor: any
}

const today = () => dateIST()
const emptySnapshot: Snapshot = { summary: null, control: null, quality: null, oee: null, vendor: null }
const fmtNum = (value: any) => value == null ? '—' : num(Number(value))
const fmtMoney = (value: any) => value == null ? '—' : money(Number(value))
const fmtPct = (value: any) => value == null ? '—' : pct(Number(value))

function shiftIsoDate(value: string, days: number) {
  const [year, month, day] = value.split('-').map(Number)
  const shifted = new Date(Date.UTC(year, month - 1, day + days))
  return `${shifted.getUTCFullYear()}-${String(shifted.getUTCMonth() + 1).padStart(2, '0')}-${String(shifted.getUTCDate()).padStart(2, '0')}`
}

function categoryForAlert(kind: string, detail: string) {
  const value = `${kind} ${detail}`.toLowerCase()
  if (value.includes('quality') || value.includes('ppm') || value.includes('reject')) return 'Quality'
  if (value.includes('vendor') || value.includes('wip')) return 'Vendor'
  if (value.includes('oee') || value.includes('machine') || value.includes('loss')) return 'Maintenance'
  if (value.includes('stage') || value.includes('process')) return 'Process'
  if (value.includes('delivery') || value.includes('dispatch')) return 'Delivery'
  if (value.includes('action') || value.includes('overdue')) return 'Actions'
  if (value.includes('schedule') || value.includes('plan')) return 'Planning'
  return 'Production'
}

function priorityForSeverity(severity: string) {
  const value = severity.toUpperCase()
  if (value === 'CRITICAL' || value === 'BLOCKER') return 'CRITICAL'
  return 'HIGH'
}

export default function DailyMeeting() {
  const [date, setDate] = useState(today())
  const [productionReviewDate, setProductionReviewDate] = useState('')
  const [productionReviewDateNote, setProductionReviewDateNote] = useState('')
  const [productionReviewDateLoading, setProductionReviewDateLoading] = useState(false)
  const [productionReviewDateResolvedKey, setProductionReviewDateResolvedKey] = useState('')
  const [calendarRefresh, setCalendarRefresh] = useState(0)
  const [review, setReview] = useState<any>(null)
  const [mom, setMom] = useState<any>(null)
  const [users, setUsers] = useState<any[]>([])
  const [products, setProducts] = useState<any[]>([])
  const [filterOptions, setFilterOptions] = useState<any>({ plants: [] })
  const [plants, setPlants] = useState<string[]>([])
  const [participants, setParticipants] = useState('')
  const [comments, setComments] = useState('')
  const [err, setErr] = useState('')
  const [message, setMessage] = useState('')
  const [meetings, setMeetings] = useState<any[]>([])
  const [participantFilter, setParticipantFilter] = useState('')
  const [meetingSearch, setMeetingSearch] = useState('')
  const [form, setForm] = useState<any>({
    category: 'Production',
    discussion_point: '',
    action_required: true,
    action_description: '',
    owner_id: '',
    due_at: '',
    priority: 'HIGH',
    product_id: '',
  })
  const [snapshot, setSnapshot] = useState<Snapshot>(emptySnapshot)
  const [snapshotBusy, setSnapshotBusy] = useState(false)
  const [snapshotWarnings, setSnapshotWarnings] = useState<string[]>([])
  const activeLookup = useRef(0)
  const snapshotLookup = useRef(0)
  const skipNextDateLookup = useRef(false)
  const productionReviewDateManual = useRef(false)
  const calendarLookup = useRef(0)
  const calendarCache = useRef(new Map<string, Map<string, boolean>>())

  const productionReviewScopeKey = `${date}|${plants.join('|')}|${(filterOptions?.plants || []).join('|')}|${calendarRefresh}`

  const productOptions = products.filter(p => !plants.length || plants.includes(String(p.plant || '')))
  const plantOptions = (filterOptions?.plants || []).map((x: string) => ({ value: String(x), label: String(x) }))

  async function load(r: any, expectedLookup?: number) {
    if (!r) {
      setMom(null)
      return
    }
    const next = await api(`/reviews/${r.id}/mom`)
    if (expectedLookup !== undefined && expectedLookup !== activeLookup.current) return
    setMom(next)
  }

  async function loadHistory() {
    try {
      setMeetings(await api('/reviews'))
    } catch (e: any) {
      setErr(e.message)
    }
  }

  async function findActive(forDate = date) {
    const request = ++activeLookup.current
    try {
      setErr('')
      const r: any = await api(`/reviews/active?review_date=${forDate}`)
      if (request !== activeLookup.current) return
      if (r) {
        setReview(r)
        setParticipants(r.participants || '')
        setComments(r.comments || '')
        await load(r, request)
      } else {
        setReview(null)
        setMom(null)
        setParticipants('')
        setComments('')
      }
    } catch (e: any) {
      if (request === activeLookup.current) setErr(e.message)
    }
  }

  useEffect(() => {
    Promise.all([
      api('/masters/users'),
      api('/masters/products'),
      api('/masters/filter-options'),
    ]).then(([u, p, f]: any[]) => {
      setUsers(u)
      setProducts(p)
      setFilterOptions(f)
    }).catch((e: any) => setErr(e.message))
    loadHistory()
  }, [])

  useEffect(() => {
    if (skipNextDateLookup.current) {
      skipNextDateLookup.current = false
      return
    }
    findActive(date)
  }, [date])

  useEffect(() => {
    const lookup = ++calendarLookup.current
    let cancelled = false

    if (productionReviewDateManual.current && productionReviewDate) {
      setProductionReviewDateResolvedKey(productionReviewScopeKey)
      setProductionReviewDateLoading(false)
      return () => { cancelled = true }
    }

    setProductionReviewDate('')
    setProductionReviewDateResolvedKey('')
    setProductionReviewDateLoading(true)
    setProductionReviewDateNote('Checking the plant working calendar…')

    const scopePlants = [...new Set(
      plants.length
        ? plants
        : ((filterOptions?.plants || []).length ? filterOptions.plants : ['Main Plant'])
    )]
    const firstCandidate = shiftIsoDate(date, -1)

    async function resolvePreviousWorkingDate() {
      let candidate = firstCandidate
      let skipped = 0

      for (let attempt = 0; attempt < 62; attempt += 1) {
        const workFlags = await Promise.all(scopePlants.map(async plant => {
          const month = candidate.slice(0, 7)
          const cacheKey = `${plant}|${month}`
          let calendar = calendarCache.current.get(cacheKey)
          if (!calendar) {
            const params = new URLSearchParams({ month: `${month}-01`, plant: String(plant) })
            const rows: any[] = await api(`/masters/calendar?${params}`)
            calendar = new Map(rows.map(row => [String(row.date).slice(0, 10), Boolean(row.working)]))
            calendarCache.current.set(cacheKey, calendar)
          }
          return calendar.get(candidate) === true
        }))

        // A single date is used for the whole selected scope. It must be a
        // working day at every selected plant to keep the review comparable.
        if (workFlags.every(Boolean)) return { date: candidate, skipped }
        candidate = shiftIsoDate(candidate, -1)
        skipped += 1
      }
      throw new Error('No common working day was found in the previous 62 days. Select the Production Review Date manually.')
    }

    resolvePreviousWorkingDate().then(result => {
      if (cancelled || lookup !== calendarLookup.current || productionReviewDateManual.current) return
      setProductionReviewDate(result.date)
      setProductionReviewDateNote(
        result.skipped > 0
          ? `Automatically selected the previous common working day; skipped ${result.skipped} non-working day(s) in the selected plant calendar.`
          : 'Automatically selected the previous day; the working calendar confirms it is a working day for the selected plant scope.'
      )
      setProductionReviewDateResolvedKey(productionReviewScopeKey)
      setProductionReviewDateLoading(false)
    }).catch((e: any) => {
      if (cancelled || lookup !== calendarLookup.current || productionReviewDateManual.current) return
      setProductionReviewDate(firstCandidate)
      setProductionReviewDateNote(`Calendar lookup failed: ${e.message}. The previous calendar day is shown; please verify or select the Production Review Date manually.`)
      setProductionReviewDateResolvedKey(productionReviewScopeKey)
      setProductionReviewDateLoading(false)
    })

    return () => { cancelled = true }
  }, [date, plants.join('|'), (filterOptions?.plants || []).join('|'), calendarRefresh])

  function changeMeetingDate(value: string) {
    productionReviewDateManual.current = false
    setProductionReviewDate('')
    setProductionReviewDateResolvedKey('')
    setDate(value)
  }

  function changeProductionReviewDate(value: string) {
    if (!value) {
      productionReviewDateManual.current = false
      setProductionReviewDate('')
      setProductionReviewDateResolvedKey('')
      setCalendarRefresh(v => v + 1)
      return
    }
    productionReviewDateManual.current = true
    setProductionReviewDate(value)
    setProductionReviewDateLoading(false)
    setProductionReviewDateNote('Manually selected. The date is used exactly as entered; calendar holidays are not automatically adjusted.')
    setProductionReviewDateResolvedKey(productionReviewScopeKey)
  }

  async function loadSnapshot() {
    const request = ++snapshotLookup.current
    setSnapshotBusy(true)
    const reviewDate = productionReviewDate
    const params = new URLSearchParams({ as_of: reviewDate })
    const period = new URLSearchParams({ from_date: reviewDate, to_date: reviewDate })
    const vendorParams = new URLSearchParams({ as_of: reviewDate, months: '36' })
    if (plants.length) {
      params.set('plant', plants.join(','))
      period.set('plant', plants.join(','))
      vendorParams.set('plant', plants.join(','))
    }

    const warnings: string[] = []
    const capture = async (label: string, path: string) => {
      try {
        return await api(path)
      } catch (e: any) {
        warnings.push(`${label}: ${e.message}`)
        return null
      }
    }

    const [summary, control, quality, oee, vendor] = await Promise.all([
      capture('Production and sales', `/dashboard/summary?${params}`),
      capture('Daily exceptions', `/dashboard/daily-control?${params}`),
      capture('Quality', `/quality/report-pack?${period}`),
      capture('OEE', `/oee/management-summary?${period}`),
      capture('Vendor WIP', `/reports/vendor-performance?${vendorParams}`),
    ])

    if (request === snapshotLookup.current) {
      setSnapshot({ summary, control, quality, oee, vendor })
      setSnapshotWarnings(warnings)
      setSnapshotBusy(false)
    }
  }

  useEffect(() => {
    if (!productionReviewDate || productionReviewDateResolvedKey !== productionReviewScopeKey) return
    loadSnapshot()
  }, [productionReviewDate, productionReviewDateResolvedKey, productionReviewScopeKey, plants.join('|')])

  async function start() {
    try {
      setErr('')
      const r: any = await api('/reviews', {
        method: 'POST',
        body: JSON.stringify({ review_date: date, participants: participants || null, comments: comments || null }),
      })
      if (r.existing) {
        const updated: any = await api(`/reviews/${r.id}`, {
          method: 'PATCH',
          body: JSON.stringify({ participants: participants || null, comments: comments || null }),
        })
        setReview(updated)
        await load(updated)
        setMessage('Existing meeting resumed and meeting details saved.')
      } else {
        setReview(r)
        await load(r)
        setMessage('Daily Review meeting started.')
      }
      await loadHistory()
    } catch (e: any) {
      setErr(e.message)
    }
  }

  async function saveMeetingDetails() {
    if (!review) return
    try {
      const r: any = await api(`/reviews/${review.id}`, {
        method: 'PATCH',
        body: JSON.stringify({ participants: participants || null, comments: comments || null }),
      })
      setReview(r)
      await loadHistory()
      setMessage('Meeting participants and remarks saved.')
    } catch (e: any) {
      setErr(e.message)
    }
  }

  async function openMeeting(m: any) {
    activeLookup.current += 1
    const request = activeLookup.current
    productionReviewDateManual.current = false
    setProductionReviewDate('')
    setProductionReviewDateResolvedKey('')
    setCalendarRefresh(v => v + 1)
    if (date !== m.review_date) {
      skipNextDateLookup.current = true
      setDate(m.review_date)
    }
    setReview(m)
    setParticipants(m.participants || '')
    setComments(m.comments || '')
    try {
      await load(m, request)
      setMessage(`Opened meeting #${m.id}.`)
    } catch (e: any) {
      setErr(e.message)
    }
  }

  async function reopen() {
    if (!review) return
    if (!confirm('Reopen this closed meeting to add more MOM points?')) return
    try {
      const r: any = await api(`/reviews/${review.id}/reopen`, { method: 'PATCH', body: JSON.stringify({}) })
      setReview(r)
      await load(r)
      await loadHistory()
      setMessage('Meeting reopened. Add the missing points, then close it again.')
    } catch (e: any) {
      setErr(e.message)
    }
  }

  async function addPoint(e: React.FormEvent) {
    e.preventDefault()
    if (!review) return
    if (form.action_required && !form.owner_id) {
      setErr('Select a responsible owner before assigning this action.')
      return
    }
    if (form.action_required && !form.due_at) {
      setErr('Enter a target date and time before assigning this action.')
      return
    }
    try {
      setErr('')
      await api(`/reviews/${review.id}/points`, {
        method: 'POST',
        body: JSON.stringify({
          ...form,
          owner_id: form.owner_id ? Number(form.owner_id) : null,
          product_id: form.product_id ? Number(form.product_id) : null,
          due_at: form.due_at ? istLocalToUTC(form.due_at) : null,
        }),
      })
      setForm((f: any) => ({ ...f, discussion_point: '', action_description: '' }))
      await load(review)
      await loadHistory()
      setMessage('MOM point added and action linked to its product context.')
    } catch (e: any) {
      setErr(e.message)
    }
  }

  function addExceptionToMom(row: any) {
    const category = categoryForAlert(row.kind || '', row.detail || '')
    const productId = row.product_id ? String(row.product_id) : ''
    const productName = row.product || productOptions.find(p => String(p.id) === productId)?.name || ''
    const detail = String(row.detail || row.summary || 'Management attention required')
    const severity = String(row.severity || 'BLOCKER')
    setForm((f: any) => ({
      ...f,
      category,
      discussion_point: productName ? `${productName}: ${detail}` : detail,
      action_required: true,
      action_description: productName
        ? `Investigate and resolve the ${category.toLowerCase()} issue for ${productName}; report the corrective action and result.`
        : `Investigate and resolve: ${detail}; report the corrective action and result.`,
      owner_id: '',
      due_at: '',
      priority: priorityForSeverity(severity),
      product_id: productId,
    }))
    document.getElementById('add-mom-point')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  function addRejectionToMom(row: any) {
    const productId = row.product_id ? String(row.product_id) : ''
    const productName = row.product || productOptions.find(p => String(p.id) === productId)?.name || ''
    const defect = row.phenomenon || row.detail || 'Critical rejection'
    const rejectQty = Number(row.reject_qty || 0)
    const ppmText = row.ppm == null ? 'PPM denominator pending' : `${num(Number(row.ppm))} PPM`
    const context = [
      productName,
      defect,
      `Rejected quantity: ${num(rejectQty)}`,
      ppmText,
      row.shift ? `Shift: ${row.shift}` : '',
      row.detection_process ? `Detection process: ${row.detection_process}` : '',
      row.responsible_team ? `Responsible team: ${row.responsible_team}` : '',
      row.detail || '',
    ].filter(Boolean).join(' | ')
    setForm((f: any) => ({
      ...f,
      category: 'Quality',
      discussion_point: context,
      action_required: true,
      action_description: `Contain the ${defect} rejection, investigate the cause for ${productName || 'the affected product'}, and report corrective action with verification.`,
      owner_id: '',
      due_at: '',
      priority: 'CRITICAL',
      product_id: productId,
    }))
    document.getElementById('add-mom-point')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    if (!review || review.ended_at) {
      setMessage('Start or reopen the meeting before adding this rejection to the MOM.')
    }
  }

  async function updateAction(a: any, status: string) {
    const comment = prompt('Enter follow-up update / closure remark')
    if (comment === null) return
    if (!comment.trim()) {
      setErr('Please enter a brief follow-up or closure remark.')
      return
    }
    try {
      await api(`/actions/${a.id}`, {
        method: 'PATCH',
        body: JSON.stringify({
          status,
          comment: comment.trim(),
          closure_remark: status === 'CLOSED' ? comment.trim() : null,
        }),
      })
      await load(review)
      await loadHistory()
      setMessage(`${a.action_no} follow-up saved.`)
    } catch (e: any) {
      setErr(e.message)
    }
  }

  async function escalate(a: any) {
    if (!confirm(`Escalate ${a.action_no} to Why-Why analysis?`)) return
    try {
      await api(`/reviews/actions/${a.id}/escalate-whywhy`, { method: 'POST' })
      await load(review)
      setMessage(`${a.action_no} escalated to Why-Why.`)
    } catch (e: any) {
      setErr(e.message)
    }
  }

  async function close() {
    if (!review) return
    try {
      const r: any = await api(`/reviews/${review.id}/close`, {
        method: 'PATCH',
        body: JSON.stringify({ comments: comments || null }),
      })
      if (r.discarded) {
        setReview(null)
        setMom(null)
        setParticipants('')
        setComments('')
        await loadHistory()
        setMessage('Meeting closed. No MOM points or linked actions were recorded, so the empty meeting was not saved.')
        return
      }
      setReview(r)
      await load(r)
      await loadHistory()
      setMessage('Meeting closed. It remains available in Meeting History.')
    } catch (e: any) {
      setErr(e.message)
    }
  }

  const summary = snapshot.summary
  const k = summary?.kpis || {}
  const quality = snapshot.quality?.summary || {}
  const qualityPpmValue = quality.ppm == null
    ? (Number(quality.reject_qty || 0) > 0 ? 'Pending' : '—')
    : `${fmtNum(quality.ppm)}${quality.ppm_is_partial ? ' (partial)' : ''}`
  const oee = snapshot.oee || {}
  const vendorRows = snapshot.vendor?.vendors || []
  const vendorPending = vendorRows.reduce((sum: number, x: any) => sum + Number(x.pending || 0), 0)
  const vendorOverdue = vendorRows.reduce((sum: number, x: any) => sum + Number(x.overdue_count || 0), 0)

  const rejectionExceptionRows: any[] = []
  const rejectionKeys = new Set<string>()
  const addRejectionException = (row: any, key: string) => {
    if (!rejectionKeys.has(key)) {
      rejectionKeys.add(key)
      rejectionExceptionRows.push(row)
    }
  }

  // Criticality is maintained in the Quality Phenomenon Master. Any non-zero
  // rejection tagged CRITICAL is surfaced even when its individual PPM is below
  // the numeric critical threshold.
  for (const row of snapshot.quality?.rows || []) {
    if (String(row.criticality || '').toUpperCase() !== 'CRITICAL' || Number(row.reject_qty || 0) <= 0) continue
    addRejectionException({
      ...row,
      severity: 'CRITICAL',
      detail: `Critical phenomenon: ${row.phenomenon || 'Unspecified defect'}`,
    }, `phenomenon:${row.id}`)
  }

  // Keep the established Daily Review rule: >= 5,000 PPM is CRITICAL.
  // A missing denominator is shown separately as a PPM data blocker.
  for (const alert of snapshot.control?.alerts || []) {
    if (alert.kind === 'high_daily_ppm' && alert.severity === 'CRITICAL') {
      const productRows = (snapshot.quality?.rows || []).filter((x: any) => x.product_id === alert.product_id)
      addRejectionException({
        product_id: alert.product_id,
        product: alert.product || productRows[0]?.product,
        severity: 'CRITICAL',
        reject_qty: productRows.reduce((sum: number, x: any) => sum + Number(x.reject_qty || 0), 0),
        ppm: alert.value,
        detail: alert.detail,
        phenomenon: 'Product-level daily PPM',
      }, `ppm:${alert.product_id}`)
    } else if (alert.kind === 'ppm_denominator_pending') {
      addRejectionException({
        product_id: alert.product_id,
        product: alert.product,
        severity: 'BLOCKER',
        reject_qty: Number(alert.value || 0),
        ppm: null,
        detail: alert.detail,
        phenomenon: 'PPM denominator missing',
      }, `pending:${alert.product_id}`)
    }
  }
  rejectionExceptionRows.sort((a, b) => {
    const rank = (x: string) => x === 'CRITICAL' ? 0 : x === 'BLOCKER' ? 1 : 2
    return rank(a.severity) - rank(b.severity) || String(a.product || '').localeCompare(String(b.product || ''))
  })

  // Restore only the general blockers and critical alerts. Routine WARNING
  // items intentionally remain hidden. Rejection/PPM items stay in their own
  // dedicated panel so that they are not repeated here.
  const blockingCriticalRows: any[] = []
  const blockingKeys = new Set<string>()
  const addBlockingCritical = (row: any, key: string) => {
    if (!blockingKeys.has(key)) {
      blockingKeys.add(key)
      blockingCriticalRows.push(row)
    }
  }
  const rejectionAlertKinds = new Set(['high_daily_ppm', 'ppm_denominator_pending'])
  for (const alert of snapshot.control?.alerts || []) {
    const severity = String(alert.severity || '').toUpperCase()
    if (!['BLOCKER', 'CRITICAL'].includes(severity) || rejectionAlertKinds.has(alert.kind)) continue
    addBlockingCritical({ ...alert, severity }, `daily:${alert.kind || ''}:${alert.product_id || 0}:${alert.detail || ''}`)
  }
  for (const row of summary?.exceptions || []) {
    if (!['CRITICAL', 'NO PLAN'].includes(String(row.status || '').toUpperCase())) continue
    const severity = String(row.status).toUpperCase() === 'CRITICAL' ? 'CRITICAL' : 'BLOCKER'
    const achievement = row.achievement == null ? 'not available' : `${(Number(row.achievement) * 100).toFixed(1)}% MTD achievement`
    const detail = `${row.status}: ${achievement}; Plan ${num(row.plan_qty)}, Actual ${num(row.actual_qty)}`
    addBlockingCritical({
      kind: 'mtd_dispatch_performance',
      severity,
      product_id: row.product_id,
      product: row.product,
      detail,
    }, `mtd:${row.product_id || 0}:${severity}`)
  }
  blockingCriticalRows.sort((a, b) => {
    const rank = (x: string) => x === 'CRITICAL' ? 0 : 1
    return rank(a.severity) - rank(b.severity) || String(a.product || '').localeCompare(String(b.product || ''))
  })

  return <>
    <PageHeader
      title="Daily Management Review"
      subtitle="Review performance, discuss exceptions, assign accountable actions and follow commitments through to closure."
    />

    {err && <div className="error">{err}</div>}
    {message && <div className="notice">{message}</div>}

    <section className="panel">
      <div className="form-row">
        <label>Meeting date<input type="date" value={date} onChange={e => changeMeetingDate(e.target.value)} /></label>
        <label>Production Review Date<input type="date" value={productionReviewDate} onChange={e => changeProductionReviewDate(e.target.value)} /></label>
        <label>Plant scope<MultiSelect value={plants} onChange={setPlants} options={plantOptions} placeholder="All Plants" /></label>
        <label>Participants<input value={participants} onChange={e => setParticipants(e.target.value)} placeholder="Names / departments" disabled={Boolean(review?.ended_at)} /></label>
        <label>Meeting remarks<input value={comments} onChange={e => setComments(e.target.value)} placeholder="Key meeting notes" disabled={!review || Boolean(review.ended_at)} /></label>
        {!review
          ? <button onClick={start}>Start Meeting</button>
          : <>
            {review.ended_at
              ? <button onClick={reopen}>Reopen Meeting</button>
              : <>
                <button className="secondary" onClick={saveMeetingDetails}>Save Details</button>
                <button onClick={close}>Close Meeting</button>
              </>
            }
            <button className="secondary" onClick={() => downloadApi(`/reviews/${review.id}/pdf`, `${mom?.mom_no || 'MOM'}.pdf`)}>Download MOM PDF</button>
            <button className="secondary" onClick={() => downloadApi(`/reviews/${review.id}/xlsx`, `${mom?.mom_no || 'MOM'}.xlsx`)}>Download Excel</button>
          </>
        }
      </div>
      <div className="data-note">
        <b>MOM Date:</b> {date} • <b>Production Review Date:</b> {productionReviewDate || (productionReviewDateLoading ? 'Calculating…' : 'Not selected')}
      </div>
      {productionReviewDateNote && <div className="data-note">{productionReviewDateNote}</div>}
      {mom && <div className="data-note"><b>{mom.mom_no}</b> • {review?.ended_at ? 'Closed' : 'Meeting active'} • {review?.participants || 'Participants not entered'}</div>}
    </section>

    <section className="panel">
      <div className="panel-title">
        <div>
          <h2>Business performance snapshot</h2>
          <p>Production and sales KPIs are month-to-date through the Production Review Date. Quality, rejection, OEE and production blockers use that selected production date. The MOM remains dated separately.</p>
        </div>
        <button className="secondary small" onClick={loadSnapshot} disabled={snapshotBusy}>{snapshotBusy ? 'Refreshing…' : 'Refresh Snapshot'}</button>
      </div>
      {snapshotWarnings.length > 0 && <div className="data-note">Some sources could not be loaded: {snapshotWarnings.join(' • ')}</div>}
      <div className="kpi-grid">
        <Kpi label="MTD Production Plan" value={fmtNum(k.plan_qty)} />
        <Kpi label="MTD Production Actual" value={fmtNum(k.actual_qty)} tone="good" />
        <Kpi label="MTD Qty Gap" value={fmtNum(k.qty_gap)} tone={Number(k.qty_gap || 0) < 0 ? 'bad' : 'good'} />
        <Kpi label="MTD Sales Achievement" value={fmtPct(k.achievement)} tone={Number(k.achievement || 0) < .9 ? 'bad' : 'good'} />
        <Kpi label="MTD Sales Gap" value={fmtMoney(k.sales_gap)} tone={Number(k.sales_gap || 0) < 0 ? 'bad' : 'good'} />
        <Kpi label="Rejection Qty (quality scope)" value={fmtNum(quality.reject_qty)} tone={Number(quality.reject_qty || 0) > 0 ? 'warn' : 'good'} />
        <Kpi label="PPM (quality scope)" value={qualityPpmValue} tone={quality.ppm_pending_rows > 0 || (quality.ppm == null && Number(quality.reject_qty || 0) > 0) ? 'warn' : 'good'} />
        <Kpi label="Critical Rejection Alerts" value={fmtNum(rejectionExceptionRows.filter(x => x.severity === 'CRITICAL').length)} tone={rejectionExceptionRows.some(x => x.severity === 'CRITICAL') ? 'bad' : 'good'} />
        <Kpi label="Daily OEE" value={Number(snapshot.oee?.entry_count || 0) ? pct(oee.overall?.oee_reported) : '—'} tone={Number(oee.overall?.oee_reported || 0) < .85 && Number(snapshot.oee?.entry_count || 0) ? 'warn' : 'good'} />
        <Kpi label="OEE Loss Events" value={fmtNum(snapshot.oee?.loss_event_count)} />
        <Kpi label="Vendor WIP Pending" value={num(vendorPending)} tone={vendorPending > 0 ? 'warn' : 'good'} />
        <Kpi label="Vendor Overdue Lots" value={num(vendorOverdue)} tone={vendorOverdue > 0 ? 'bad' : 'good'} />
        <Kpi label="Open Actions (scope)" value={fmtNum(k.open_actions)} />
        <Kpi label="Overdue Actions (scope)" value={fmtNum(k.overdue_actions)} tone={Number(k.overdue_actions || 0) > 0 ? 'bad' : 'good'} />
      </div>
      {Number(quality.ppm_pending_rows || 0) > 0 && <div className="data-note">PPM denominator is missing for {quality.ppm_pending_rows} record(s); the displayed PPM may be partial or pending.</div>}
      {quality.history_note && <div className="data-note">{quality.history_note}</div>}
      {!summary && !snapshotBusy && <div className="empty">Production and sales snapshot is unavailable. Check the source status above.</div>}
    </section>

    <section className="panel">
      <div className="panel-title">
        <div>
          <h2>Blocking &amp; Critical Items</h2>
          <p>Only general BLOCKER and CRITICAL items for the selected Production Review Date are shown here. Routine WARNING items are excluded; rejection and PPM exceptions are shown separately.</p>
        </div>
        <span>{blockingCriticalRows.length} item(s)</span>
      </div>
      {blockingCriticalRows.length === 0
        ? <div className="empty">{snapshotBusy ? 'Checking blockers and critical items…' : 'No general blocking or critical items were found for this date and plant scope.'}</div>
        : <div className="table-wrap"><table>
          <thead><tr><th>Severity</th><th>Category</th><th>Product</th><th>Blocking / Critical Detail</th><th>MOM</th></tr></thead>
          <tbody>
            {blockingCriticalRows.map((row: any, i: number) => (
              <tr key={`${row.kind || 'critical'}-${row.product_id || 0}-${i}`}>
                <td><Status value={row.severity} /></td>
                <td>{categoryForAlert(row.kind || '', row.detail || '')}</td>
                <td>{row.product || '—'}</td>
                <td>{row.detail}</td>
                <td><button className="small" type="button" disabled={!review || Boolean(review.ended_at)} onClick={() => addExceptionToMom(row)}>Add to MOM</button></td>
              </tr>
            ))}
          </tbody>
        </table></div>
      }
      {(!review || review.ended_at) && <div className="data-note">Start or reopen a meeting to add a blocking or critical item to its MOM.</div>}
    </section>

    <section className="panel">
      <div className="panel-title">
        <div>
          <h2>Critical Rejection Exceptions</h2>
          <p>Rejection records for the selected Production Review Date. Criticality comes from the Quality Phenomenon Master; product-level rejection at or above 5,000 PPM is also critical. Missing PPM denominators are shown as blockers.</p>
        </div>
        <span>{rejectionExceptionRows.length} item(s)</span>
      </div>
      {rejectionExceptionRows.length === 0
        ? <div className="empty">{snapshotBusy ? 'Checking rejection data…' : 'No critical rejection or PPM data-blocker was found for this date and plant scope.'}</div>
        : <div className="table-wrap"><table>
          <thead><tr><th>Severity</th><th>Product</th><th>Defect / Rejection trigger</th><th>Reject Qty</th><th>PPM</th><th>Detection / Details</th><th>MOM</th></tr></thead>
          <tbody>
            {rejectionExceptionRows.map((row: any, i: number) => (
              <tr key={`${row.id || row.kind || 'rejection'}-${row.product_id || 0}-${i}`}>
                <td><Status value={row.severity} /></td>
                <td>{row.product || '—'}</td>
                <td>{row.phenomenon || 'Rejection'}</td>
                <td>{fmtNum(row.reject_qty)}</td>
                <td>{row.ppm == null ? <Status value="PPM PENDING" /> : `${fmtNum(row.ppm)} PPM`}</td>
                <td>{[row.detection_process, row.responsible_team, row.shift, row.detail].filter(Boolean).join(' • ') || '—'}</td>
                <td><button className="small" type="button" disabled={!review || Boolean(review.ended_at)} onClick={() => addRejectionToMom(row)}>Add to MOM</button></td>
              </tr>
            ))}
          </tbody>
        </table></div>
      }
      {(!review || review.ended_at) && <div className="data-note">Start or reopen a meeting to add a rejection exception to the MOM.</div>}
    </section>

    {review && !review.ended_at && <section className="panel" id="add-mom-point">
      <h2>Add discussion / MOM point</h2>
      <form onSubmit={addPoint}>
        <div className="form-row">
          <label>Category<select value={form.category} onChange={e => setForm({ ...form, category: e.target.value })}>
            {['Production', 'Quality', 'Delivery', 'Process', 'Maintenance', 'Capacity', 'Vendor', 'Customer', 'Safety', 'Cost', 'Planning', 'Actions', 'Other'].map(x => <option key={x}>{x}</option>)}
          </select></label>
          <label>Product context<select value={form.product_id} onChange={e => setForm({ ...form, product_id: e.target.value })}>
            <option value="">No product context</option>
            {productOptions.map((p: any) => <option key={p.id} value={String(p.id)}>{p.name}</option>)}
          </select></label>
          <label>Action Required<select value={form.action_required ? 'YES' : 'NO'} onChange={e => setForm({ ...form, action_required: e.target.value === 'YES' })}>
            <option>YES</option><option>NO</option>
          </select></label>
          <label>Priority<select value={form.priority} onChange={e => setForm({ ...form, priority: e.target.value })}>
            <option>LOW</option><option>MEDIUM</option><option>HIGH</option><option>CRITICAL</option>
          </select></label>
        </div>
        <label>Discussion / MOM Point<textarea required value={form.discussion_point} onChange={e => setForm({ ...form, discussion_point: e.target.value })} /></label>
        {form.action_required && <>
          <label>Action Required<textarea required value={form.action_description} onChange={e => setForm({ ...form, action_description: e.target.value })} /></label>
          <div className="form-row">
            <label>Responsible Owner<MultiSelect className="manual-search-select" value={form.owner_id ? [String(form.owner_id)] : []} onChange={v => setForm({ ...form, owner_id: v.at(-1) || '' })} placeholder="Select owner" options={users.map(u => ({ value: String(u.id), label: u.full_name }))} /></label>
            <label>Target Date / Time (IST)<input type="datetime-local" value={form.due_at} onChange={e => setForm({ ...form, due_at: e.target.value })} /></label>
          </div>
          <div className="data-note">Owner and target date are required when creating an action. This keeps each commitment accountable.</div>
        </>}
        <button type="submit">Add MOM Point</button>
      </form>
    </section>}

    {mom && <div className="kpi-grid">
      <Kpi label="Discussion points" value={num(mom.points?.length || 0)} />
      <Kpi label="Today's open actions" value={num(
        (mom.points || []).filter((p: any) => p.action && p.action.status !== 'CLOSED').length
        + (mom.linked_actions || []).filter((a: any) => a.status !== 'CLOSED').length
      )} />
      <Kpi label="Previous pending actions" value={num(mom.previous_pending_actions?.length || 0)} />
      <Kpi label="Overdue previous actions" value={num((mom.previous_pending_actions || []).filter((a: any) => a.overdue_days > 0).length)} tone={(mom.previous_pending_actions || []).some((a: any) => a.overdue_days > 0) ? 'bad' : 'good'} />
    </div>}

    {mom && <section className="panel">
      <div className="panel-title"><h2>Today's MOM Points</h2><span>{mom.points.length} point(s)</span></div>
      <div className="table-wrap"><table>
        <thead><tr><th>Sr.</th><th>Category</th><th>Product</th><th>Discussion</th><th>Action / Owner</th><th>Target</th><th>Priority</th><th>Status</th><th>Follow-up</th></tr></thead>
        <tbody>{mom.points.map((p: any) => <tr key={p.id}>
          <td>{p.sequence_no}</td><td>{p.category || '—'}</td><td>{p.product || '—'}</td><td>{p.discussion_point}</td>
          <td>{p.action ? <><b>{p.action.action_no}</b><br />{p.action.description}<br /><small>{p.action.owner || 'Unassigned'}</small></> : 'No action'}</td>
          <td>{p.action ? formatIST(p.action.due_at) : '—'}</td>
          <td>{p.action ? <Status value={p.action.priority} /> : '—'}</td>
          <td>{p.action ? <Status value={p.action.status} /> : <Status value="INFO" />}</td>
          <td>{p.action && <><select value={p.action.status} disabled={Boolean(review?.ended_at)} onChange={e => updateAction(p.action, e.target.value)}>
            <option>OPEN</option><option>IN_PROGRESS</option><option>BLOCKED</option><option>CLOSED</option>
          </select>{!p.action.requires_whywhy && <button className="secondary small" type="button" disabled={Boolean(review?.ended_at)} onClick={() => escalate(p.action)}>Escalate to Why-Why</button>}</>}</td>
        </tr>)}</tbody>
      </table></div>
    </section>}

    {mom?.linked_actions?.length > 0 && <section className="panel">
      <div className="panel-title">
        <div><h2>Other Actions Linked to This Meeting</h2><p>Actions raised from Dashboard, Quality, OEE or the Actions page. These are linked to this MOM but are not typed discussion points.</p></div>
        <span>{mom.linked_actions.length} action(s)</span>
      </div>
      <div className="table-wrap"><table>
        <thead><tr><th>Action No.</th><th>Problem / Action</th><th>Product context</th><th>Owner</th><th>Priority</th><th>Target</th><th>Status</th><th>Update</th></tr></thead>
        <tbody>{mom.linked_actions.map((a: any) => <tr key={a.id}>
          <td><b>{a.action_no}</b></td>
          <td>{a.description}</td>
          <td>{(a.products || []).join(', ') || '—'}</td>
          <td>{a.owner || 'Unassigned'}</td>
          <td><Status value={a.priority} /></td>
          <td>{formatIST(a.due_at)}</td>
          <td><Status value={a.status} /></td>
          <td><select value={a.status} disabled={Boolean(review?.ended_at)} onChange={e => updateAction(a, e.target.value)}>
            <option>OPEN</option><option>IN_PROGRESS</option><option>BLOCKED</option><option>CLOSED</option>
          </select>{!a.requires_whywhy && <button className="secondary small" type="button" disabled={Boolean(review?.ended_at)} onClick={() => escalate(a)}>Escalate to Why-Why</button>}</td>
        </tr>)}</tbody>
      </table></div>
    </section>}

    {mom?.previous_pending_actions?.length > 0 && <section className="panel">
      <div className="panel-title"><div><h2>Previous Pending Actions</h2><p>Only actions linked to earlier meetings (plus legacy daily-review actions) are carried forward.</p></div></div>
      <div className="table-wrap"><table>
        <thead><tr><th>Action</th><th>Product context</th><th>Owner</th><th>Priority</th><th>Target</th><th>Age</th><th>Last Follow-up</th><th>Status</th><th>Update</th></tr></thead>
        <tbody>{mom.previous_pending_actions.map((a: any) => <tr key={a.id} className={a.overdue_days ? 'row-overdue' : ''}>
          <td><b>{a.action_no}</b><br /><small>{a.description}</small></td>
          <td>{(a.products || []).join(', ') || '—'}</td><td>{a.owner || 'Unassigned'}</td><td><Status value={a.priority} /></td>
          <td>{formatIST(a.due_at)}{a.overdue_days > 0 && <><br /><small>{a.overdue_days}d overdue</small></>}</td>
          <td>{a.age_days}d</td>
          <td>{a.last_followup_at ? <>{formatIST(a.last_followup_at)}<br /><small>{a.last_followup_comment}</small></> : 'No recorded update'}</td>
          <td><Status value={a.status} /></td>
          <td><select value={a.status} disabled={Boolean(review?.ended_at)} onChange={e => updateAction(a, e.target.value)}>
            <option>OPEN</option><option>IN_PROGRESS</option><option>BLOCKED</option><option>CLOSED</option>
          </select>{!a.requires_whywhy && <button className="secondary small" type="button" disabled={Boolean(review?.ended_at)} onClick={() => escalate(a)}>Escalate to Why-Why</button>}</td>
        </tr>)}</tbody>
      </table></div>
    </section>}

    <section className="panel">
      <div className="panel-title">
        <div><h2>Meeting History</h2><p>Open a closed meeting without losing the selected historical session, reopen it to add points, or download its MOM.</p></div>
        <label>Search MOM / date<input value={meetingSearch} onChange={e => setMeetingSearch(e.target.value)} placeholder="MOM number or date" /></label>
        <label>Filter Participants<input value={participantFilter} onChange={e => setParticipantFilter(e.target.value)} placeholder="Name or department" /></label>
      </div>
      <div className="table-wrap"><table>
        <thead><tr><th>MOM</th><th>Date</th><th>Participants</th><th>Actions</th><th>Closed</th><th>Pending</th><th>Overdue</th><th>Status</th><th>Open</th><th>Meeting Note</th></tr></thead>
        <tbody>{meetings
          .filter((m: any) => (!participantFilter.trim() || String(m.participants || '').toLowerCase().includes(participantFilter.trim().toLowerCase()))
            && (!meetingSearch.trim() || (`MOM-${m.review_date}-${String(m.id).padStart(3, '0')}`).toLowerCase().includes(meetingSearch.trim().toLowerCase())))
          .map((m: any) => <tr key={m.id}>
            <td><b>{`MOM-${m.review_date}-${String(m.id).padStart(3, '0')}`}</b></td><td>{m.review_date}</td><td>{m.participants || '—'}</td>
            <td><b>{m.action_count || 0}</b></td><td><b>{m.closed_action_count || 0}</b></td><td><b>{Math.max(0, (m.action_count || 0) - (m.closed_action_count || 0))}</b></td>
            <td>{m.overdue_action_count || 0}</td><td>{m.ended_at ? <Status value="CLOSED" /> : <Status value="OPEN" />}</td>
            <td><button className="secondary small" onClick={() => openMeeting(m)}>Open Meeting</button></td>
            <td><button className="secondary small" onClick={() => downloadApi(`/reviews/${m.id}/pdf`, `MOM-${m.review_date}-${String(m.id).padStart(3, '0')}.pdf`)}>PDF</button> <button className="secondary small" onClick={() => downloadApi(`/reviews/${m.id}/xlsx`, `MOM-${m.review_date}-${String(m.id).padStart(3, '0')}.xlsx`)}>Excel</button></td>
          </tr>)}
        </tbody>
      </table></div>
    </section>
  </>
}
