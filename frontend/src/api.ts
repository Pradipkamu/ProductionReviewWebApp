const API = import.meta.env.VITE_API_URL || '/api'

export function getToken() { return localStorage.getItem('token') }
export function setToken(token: string) { localStorage.setItem('token', token) }
export function clearToken() { localStorage.removeItem('token') }

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
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || `${res.status} ${res.statusText}`)
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
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || `${res.status} ${res.statusText}`)
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
