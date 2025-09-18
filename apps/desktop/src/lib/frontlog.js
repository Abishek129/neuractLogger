// Frontend logging to frontout.md via Tauri command
// Only active in production builds

const isProd = typeof import.meta !== 'undefined' && import.meta.env && import.meta.env.PROD

let _invoke = null
async function getInvoker() {
  if (_invoke) return _invoke
  try {
    if (typeof window !== 'undefined' && window.__TAURI__ && typeof window.__TAURI__.invoke === 'function') {
      _invoke = window.__TAURI__.invoke
      return _invoke
    }
  } catch {}
  try {
    const mod = await import('@tauri-apps/api/core')
    if (mod && typeof mod.invoke === 'function') {
      _invoke = mod.invoke
      return _invoke
    }
  } catch {}
  return null
}

export async function logFrontout(kind, data) {
  if (!isProd) return
  try {
    const inv = await getInvoker()
    if (!inv) return
    const stamp = new Date().toISOString()
    const line = JSON.stringify({ t: stamp, kind, ...data })
    await inv('frontout_log', { line })
  } catch {}
}

// Redact token values leaving a short prefix
export function redactHeaders(h) {
  const out = { ...(h || {}) }
  const redact = (v) => {
    if (!v) return v
    const s = String(v)
    if (s.length <= 6) return '***'
    return s.slice(0, 6) + '...'
  }
  if (out['Authorization']) out['Authorization'] = redact(out['Authorization'])
  if (out['X-Agent-Token']) out['X-Agent-Token'] = redact(out['X-Agent-Token'])
  return out
}

// Attach a global click listener to capture all clicks
export function setupClickLogging() {
  if (!isProd || typeof document === 'undefined') return
  const pick = (el) => {
    if (!el || !el.tagName) return null
    const name = el.tagName.toLowerCase()
    const id = el.id ? `#${el.id}` : ''
    const cls = (el.classList && el.classList.value) ? '.' + Array.from(el.classList).join('.') : ''
    const text = (el.innerText || el.textContent || '').trim().slice(0, 80)
    const role = el.getAttribute ? el.getAttribute('role') : null
    const type = el.getAttribute ? el.getAttribute('type') : null
    return { name, id, cls, text, role, type }
  }
  const handler = (evt) => {
    try {
      const target = pick(evt.target)
      const path = []
      let node = evt.target
      for (let i = 0; i < 5 && node && node.parentElement; i++) {
        const p = pick(node.parentElement)
        if (p) path.push(p)
        node = node.parentElement
      }
      logFrontout('click', { target, path })
    } catch {}
  }
  document.addEventListener('click', handler, true)
}
