import React, { useEffect, useState } from 'react'

// Simple global toast bus via window event
const EVT = 'app:toast'

export const toast = Object.assign(
  (message, opts = {}) => {
    try {
      window.dispatchEvent(new CustomEvent(EVT, { detail: { message, ...opts } }))
    } catch {}
  },
  {
    success: (message, opts = {}) => toast(message, { type: 'success', ...opts }),
    error: (message, opts = {}) => toast(message, { type: 'error', ...opts }),
    info: (message, opts = {}) => toast(message, { type: 'info', ...opts }),
    warn: (message, opts = {}) => toast(message, { type: 'warn', ...opts }),
  }
)

export default function Toast() {
  const [items, setItems] = useState([])
  useEffect(() => {
    const onToast = (e) => {
      const id = Math.random().toString(36).slice(2)
      const t = { id, type: e.detail?.type || 'info', message: e.detail?.message || '' }
      setItems(prev => [...prev, t])
      setTimeout(() => setItems(prev => prev.filter(x => x.id !== id)), e.detail?.ttl || 2800)
    }
    window.addEventListener(EVT, onToast)
    return () => window.removeEventListener(EVT, onToast)
  }, [])
  const color = (t) => t==='success' ? '#16a34a' : t==='error' ? '#dc2626' : t==='warn' ? '#d97706' : '#2563eb'
  return (
    <div style={{ position:'fixed', right:12, top:12, display:'flex', flexDirection:'column', gap:8, zIndex: 2000 }} aria-live="polite" aria-atomic>
      {items.map(it => (
        <div key={it.id} role="status" style={{ minWidth: 240, maxWidth: 420, background:'#111827', color:'#fff', borderRadius:8, padding:'8px 10px', boxShadow:'0 6px 20px rgba(0,0,0,0.3)', display:'flex', alignItems:'center', gap:10 }}>
          <span aria-hidden className="dot" style={{ width:10, height:10, borderRadius:999, background: color(it.type) }} />
          <div style={{ fontSize:14, lineHeight:1.3, flex:1 }}>{it.message}</div>
          <button onClick={()=>setItems(prev=>prev.filter(x=>x.id!==it.id))} aria-label="Dismiss" style={{ color:'#9ca3af', background:'transparent', border:'none', cursor:'pointer' }}>×</button>
        </div>
      ))}
    </div>
  )
}

