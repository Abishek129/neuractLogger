import React, { useState } from 'react'
import { testOpcUa } from '../../lib/api/networking.js'

export default function OpcUaForm() {
  const [endpoint, setEndpoint] = useState('opc.tcp://localhost:4840')
  const [status, setStatus] = useState('idle')
  const probe = async () => {
    setStatus('probing...')
    try {
      const res = await testOpcUa({ endpoint })
      setStatus(res.ok ? `OK (${res.latencyMs??'?'} ms)` : `fail: ${res.message||'error'}`)
    } catch (e) {
      setStatus('error')
    }
  }
  return (
    <div>
      <h4>OPC UA</h4>
      <div style={{ display: 'flex', gap: 8 }}>
        <input value={endpoint} onChange={e=>setEndpoint(e.target.value)} placeholder="endpoint" />
        <button onClick={probe}>Test Read</button>
      </div>
      <div style={{ marginTop: 8 }}>Status: {status}</div>
    </div>
  )
}
