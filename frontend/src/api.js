export class APIError extends Error {
  constructor(message, status) { super(message); this.status = status }
}

async function request(path, options = {}) {
  const headers = { ...(options.body ? { 'Content-Type': 'application/json' } : {}), ...options.headers }
  const response = await fetch(path, { credentials: 'include', ...options, headers })
  const type = response.headers.get('content-type') || ''
  const payload = type.includes('application/json') ? await response.json() : await response.text()
  if (!response.ok) {
    const detail = payload && payload.detail
    throw new APIError(typeof detail === 'string' ? detail : 'Request failed (' + response.status + ')', response.status)
  }
  return payload
}

export const api = request
export const get = (path) => request(path)
export const post = (path, body) => request(path, { method: 'POST', body: JSON.stringify(body ?? {}) })
export const patch = (path, body) => request(path, { method: 'PATCH', body: JSON.stringify(body ?? {}) })
export const put = (path, body) => request(path, { method: 'PUT', body: JSON.stringify(body ?? {}) })
export const del = (path) => request(path, { method: 'DELETE' })

export function parseHash() {
  const raw = window.location.hash.replace(/^#/, '') || '/'
  const [path, query = ''] = raw.split('?')
  const params = new URLSearchParams(query)
  return { path: path || '/', query: Object.fromEntries(params.entries()) }
}

export function navigate(path) {
  if (window.location.hash.replace(/^#/, '') === path) {
    window.dispatchEvent(new HashChangeEvent('hashchange'))
  } else {
    window.location.hash = path
  }
}

export function money(cents, currency = 'USD') {
  return new Intl.NumberFormat(undefined, { style: 'currency', currency, maximumFractionDigits: cents % 100 ? 2 : 0 }).format(cents / 100)
}

export function dateLabel(value) {
  if (!value) return '—'
  return new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric', year: 'numeric' }).format(new Date(value))
}

export function dateTimeLabel(value) {
  if (!value) return 'Not yet'
  return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
}

export function relativeLabel(value) {
  if (!value) return '—'
  const seconds = Math.max(0, Math.floor((Date.now() - new Date(value).getTime()) / 1000))
  if (seconds < 60) return `${seconds}s ago`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`
  return `${Math.floor(seconds / 86400)}d ago`
}

export function download(path, filename) {
  const link = document.createElement('a')
  link.href = path
  link.download = filename || 'agentdock-file'
  document.body.appendChild(link)
  link.click()
  link.remove()
}

export function copy(text, setCopied) {
  navigator.clipboard?.writeText(text).then(() => {
    setCopied?.(true)
    window.setTimeout(() => setCopied?.(false), 1600)
  }).catch(() => setCopied?.(false))
}

export function stars(value) {
  return '★'.repeat(Math.round(value || 0)) + '☆'.repeat(5 - Math.round(value || 0))
}
