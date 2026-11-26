const API = import.meta.env.VITE_API_URL || '/api'

export function getToken() { return localStorage.getItem('token') }
export function setToken(token: string) { localStorage.setItem('token', token) }
export function clearToken() { localStorage.removeItem('token') }

function readableApiError(detail: any): string {
  if (typeof detail === 'string' && detail.trim()) return detail
  if (Array.isArray(detail)) {
    const messages = detail.map((item: any) => {
      if (typeof item === 'string') return item
      const message = typeof item?.msg === 'string' ? item.msg : ''
      const location = Array.isArray(item?.loc) ? item.loc.filter((part: any) => part !== 'body').join(' → ') : ''
      return [location, message].filter(Boolean).join(': ')
    }).filter(Boolean)
    if (messages.length) return messages.join('; ')
  }
  if (detail && typeof detail === 'object') {
    if (typeof detail.message === 'string') return detail.message
    if (detail.detail !== undefined && detail.detail !== detail) return readableApiError(detail.detail)
    if (Object.keys(detail).length) { try { return JSON.stringify(detail) } catch { /* use fallback below */ } }
  }
  return 'The request failed. Please check the entered values and try again.'
}

export async function api<T=any>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers || {})
  const token = getToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)
  if (!(init.body instanceof FormData) && init.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  if(init.method && !['GET','HEAD'].includes(init.method)) {
    const reason=sessionStorage.getItem('changeReason'); if(reason)headers.set('X-Change-Reason',reason)
    const correction=sessionStorage.getItem('correctionId'); if(correction)headers.set('X-Correction-ID',correction)
  }
  const res = await fetch(`${API}${path}`, { ...init, headers })
  if (res.status === 401) { clearToken(); location.reload() }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    const detail = body && typeof body === 'object' && 'detail' in body ? body.detail : body
    const message = readableApiError(detail)
    const error = new Error(message)
    window.dispatchEvent(new CustomEvent('app:api-error', { detail: { message, status: res.status, path } }))
    throw error
  }
  if(res.ok && headers.has('X-Correction-ID') && !path.split('?')[0].includes('/preview'))sessionStorage.removeItem('correctionId')
  return res.json()
}

export async function login(username: string, password: string) {
  return api('/auth/login', { method: 'POST', body: JSON.stringify({ username, password }) })
}

export async function logout() {
  try {
    if (getToken()) await api('/auth/logout', { method: 'POST' })
  } finally {
    clearToken()
  }
}

export async function downloadApi(path: string, filename: string) {
  const headers = new Headers()
  const token = getToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)
  const res = await fetch(`${API}${path}`, { headers })
  if (res.status === 401) { clearToken(); location.reload(); return }
  if (!res.ok) { const body=await res.json().catch(()=>({})); const message=readableApiError(body?.detail??body); window.dispatchEvent(new CustomEvent('app:api-error',{detail:{message,status:res.status,path}})); throw new Error(message) }
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}


export async function blobApi(path: string): Promise<Blob> {
  const headers = new Headers()
  const token = getToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)
  const res = await fetch(`${API}${path}`, { headers })
  if (res.status === 401) { clearToken(); location.reload() }
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || `${res.status} ${res.statusText}`)
  return res.blob()
}
