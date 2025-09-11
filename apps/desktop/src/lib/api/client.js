// In dev: route all calls via the Vite proxy at /api to avoid CORS and attach auth in the proxy layer
const isDev = typeof import.meta !== 'undefined' && import.meta.env && import.meta.env.DEV
let baseUrl = (isDev && !import.meta.env.VITE_AGENT_BASE_URL) ? '/api' : (import.meta.env.VITE_AGENT_BASE_URL || 'http://127.0.0.1:5175')
const basePinned = !!import.meta.env.VITE_AGENT_BASE_URL || (baseUrl === '/api')

let cachedToken = null

function getToken() {
  // Prefer runtime/discovered token over build-time env
  return (
    cachedToken ||
    (typeof localStorage !== 'undefined' ? localStorage.getItem('agent_token') : null) ||
    import.meta.env.VITE_AGENT_TOKEN
  )
}

function setToken(tok) {
  cachedToken = tok
  try { if (typeof localStorage !== 'undefined') localStorage.setItem('agent_token', tok) } catch {}
}

async function handshake() {
  try {
    const res = await fetch(baseUrl + '/auth/handshake')
    if (!res.ok) return null
    const data = await res.json()
    if (data && data.token) {
      setToken(data.token)
      // If backend reports its port and base isn't pinned and we are not using proxy, adopt it
      if (!basePinned && data.port && baseUrl !== '/api') {
        try {
          const p = Number(data.port)
          if (Number.isFinite(p) && p > 0) {
            baseUrl = `http://127.0.0.1:${p}`
            try { if (typeof localStorage !== 'undefined') localStorage.setItem('agent_base', baseUrl) } catch {}
          }
        } catch {}
      }
      return data.token
    }
  } catch {}
  return null
}

async function ensureToken(force = false) {
  if (!force && getToken()) return getToken()
  return await handshake()
}

let baseChecked = false
async function ensureBase() {
  if (baseChecked) return baseUrl
  baseChecked = true
  try {
    // If running under Tauri, ask backend to read lockfile for port/token
    if (typeof window !== 'undefined' && window.__TAURI__ && window.__TAURI__.invoke) {
      const tuple = await window.__TAURI__.invoke('read_lockfile')
      if (Array.isArray(tuple) && tuple.length === 2) {
        const [port, tok] = tuple
        if (port && baseUrl !== '/api') baseUrl = `http://127.0.0.1:${port}`
        if (tok) setToken(tok)
      }
    } else if (!basePinned) {
      // Non-Tauri dev: restore last discovered base if present
      if (baseUrl !== '/api') {
        try {
          const saved = typeof localStorage !== 'undefined' ? localStorage.getItem('agent_base') : null
          if (saved && /^https?:\/\//i.test(saved)) baseUrl = saved
        } catch {}
      }
    }
  } catch {}
  return baseUrl
}

async function request(path, { method = 'GET', body, headers = {} } = {}) {
  // Ensure base URL (port) and then a token
  await ensureBase()
  // Ensure we have a token (or obtain it) before first protected call
  await ensureToken(false)

  const doFetch = async () => {
    const h = { 'Content-Type': 'application/json', ...headers }
    const tok = getToken()
    if (tok) {
      h['X-Agent-Token'] = tok
      // Also send Authorization for compatibility
      if (!h['Authorization']) h['Authorization'] = `Bearer ${tok}`
    }
    return await fetch(baseUrl + path, {
      method,
      headers: h,
      body: body ? JSON.stringify(body) : undefined,
    })
  }

  let res = await doFetch()
  if (res.status === 401) {
    // Try to discover token and retry once
    const tok = await ensureToken(true)
    if (tok) res = await doFetch()
  }
  if (!res.ok) {
    let text = null
    try { text = await res.text() } catch {}
    const err = new Error(`HTTP ${res.status}${text ? `: ${text}` : ''}`)
    err.status = res.status
    err.body = text
    throw err
  }
  const ct = res.headers.get('content-type') || ''
  return ct.includes('application/json') ? res.json() : res.text()
}

export { request }
