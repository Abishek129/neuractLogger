import { logFrontout, redactHeaders } from '../frontlog.js'

// In dev: route all calls via the Vite proxy at /api to avoid CORS and attach auth in the proxy layer
const isDev = typeof import.meta !== 'undefined' && import.meta.env && import.meta.env.DEV
const isProd = typeof import.meta !== 'undefined' && import.meta.env && import.meta.env.PROD

// Accept both env names; dev defaults to /api if not pinned
const ENV_BASE = (import.meta.env && (import.meta.env.VITE_AGENT_BASE_URL || import.meta.env.VITE_API_BASE))
let baseUrl = (isDev && !ENV_BASE) ? '/api' : (ENV_BASE || 'http://127.0.0.1:5175')
const basePinned = !!ENV_BASE || (baseUrl === '/api')
const forcePinned = !!(import.meta.env && import.meta.env.VITE_FORCE_AGENT_BASE)

try { if (isProd) { logFrontout('init', { baseUrl, basePinned, forcePinned }) } } catch {}

// Use last known good base if present and not force-pinned
try {
  if (!forcePinned && baseUrl !== '/api' && typeof localStorage !== 'undefined') {
    const saved = localStorage.getItem('agent_base')
    if (saved && /^https?:\/\//i.test(saved)) baseUrl = saved
  }
} catch {}

let cachedToken = null

function getToken() {
  return (
    cachedToken ||
    (typeof localStorage !== 'undefined' ? localStorage.getItem('agent_token') : null) ||
    (import.meta.env ? import.meta.env.VITE_AGENT_TOKEN : null) ||
    null
  )
}

function setToken(tok) {
  if (!tok) return
  cachedToken = tok
  try { if (typeof localStorage !== 'undefined') localStorage.setItem('agent_token', tok) } catch {}
}

async function tryReadLockfile() {
  try {
    let invoker = null
    if (typeof window !== 'undefined' && window.__TAURI__ && window.__TAURI__.invoke) {
      invoker = window.__TAURI__.invoke
    } else {
      try {
        const mod = await import('@tauri-apps/api/core')
        if (mod && typeof mod.invoke === 'function') invoker = mod.invoke
      } catch {}
    }
    if (!invoker) return
    const tuple = await invoker('read_lockfile')
    if (Array.isArray(tuple) && tuple.length === 2) {
      const [port, tok] = tuple
      try { if (isProd) logFrontout('lockfile', { port, hasToken: !!tok, tokPrefix: (tok || '').slice(0, 6) + '...' }) } catch {}
      if (port && baseUrl !== '/api' && !forcePinned) {
        baseUrl = `http://127.0.0.1:${port}`
        try { if (typeof localStorage !== 'undefined') localStorage.setItem('agent_base', baseUrl) } catch {}
      }
      if (tok) setToken(tok)
    }
  } catch {}
}

async function handshake() {
  try {
    const res = await fetch(baseUrl + '/auth/handshake')
    if (!res.ok) return
    const data = await res.json().catch(() => null)
    if (!data) return
    try { if (isProd) logFrontout('handshake', { port: data.port, hasToken: !!data.token, baseUrl }) } catch {}
    if (data.port && baseUrl !== '/api' && !forcePinned) {
      baseUrl = `http://127.0.0.1:${data.port}`
      try { if (typeof localStorage !== 'undefined') localStorage.setItem('agent_base', baseUrl) } catch {}
    }
    if (data.token) setToken(data.token)
  } catch {}
}

let initialized = false
async function ensureInit() {
  if (initialized) return
  initialized = true
  await tryReadLockfile()
  if (!getToken()) await handshake()
}

export async function request(path, { method = 'GET', body, headers = {} } = {}) {
  if (!path.startsWith('/')) path = '/' + path
  await ensureInit()

  const doFetch = async () => {
    const h = { 'Content-Type': 'application/json', ...headers }
    const tok = getToken()
    if (tok) {
      h['X-Agent-Token'] = tok
      if (!h['Authorization']) h['Authorization'] = `Bearer ${tok}`
    }
    try { if (isProd) logFrontout('request_start', { method, url: baseUrl + path, headers: redactHeaders(h) }) } catch {}
    return fetch(baseUrl + path, {
      method,
      headers: h,
      body: body != null ? JSON.stringify(body) : undefined,
    })
  }

  let res = await doFetch()
  try { if (isProd) logFrontout('response', { url: baseUrl + path, status: res.status }) } catch {}
  if (res.status === 401) {
    try { if (isProd) logFrontout('retry_after_401', { url: baseUrl + path }) } catch {}
    await handshake()
    res = await doFetch()
    try { if (isProd) logFrontout('response', { url: baseUrl + path, status: res.status }) } catch {}
  }

  if (!res.ok) {
    let text = ''
    try { text = await res.text() } catch {}
    try { if (isProd) logFrontout('request_error', { url: baseUrl + path, status: res.status, text: text.slice(0, 200) }) } catch {}
    const msg = `HTTP ${res.status} ${res.statusText || ''} for ${method} ${baseUrl}${path}${text ? ` — ${text}` : ''}`.trim()
    // eslint-disable-next-line no-console
    console.error(msg)
    const err = new Error(msg)
    err.status = res.status
    err.body = text
    err.url = baseUrl + path
    throw err
  }

  const ct = res.headers.get('content-type') || ''
  return ct.includes('application/json') ? res.json() : null
}

// Temporary runtime debug helper for packaged app
try {
  if (typeof window !== 'undefined') {
    window.__plc_debug = () => ({ baseUrl, tokenPrefix: (getToken() || '').slice(0, 8) + '…' })
    window.plc_debug = window.__plc_debug
  }
} catch {}

export function getBaseUrl() { return baseUrl }

