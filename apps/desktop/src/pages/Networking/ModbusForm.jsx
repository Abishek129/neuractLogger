import React, { useState } from 'react'
import { testModbus } from '../../lib/api/networking.js'

export default function ModbusForm() {
  const [host, setHost] = useState('127.0.0.1')
  const [port, setPort] = useState(502)
  const [unitId, setUnitId] = useState(1)
  const [status, setStatus] = useState('idle')

  const probe = async () => {
    setStatus('probing...')
    try {
      const res = await testModbus({ host, port, unitId })
      setStatus(res.ok ? `OK (${res.latencyMs??'?'} ms)` : `fail: ${res.message||'error'}`)
    } catch (e) {
      setStatus('error')
    }
  }

  return (
    <div>
      <h4>Modbus</h4>
      <div style={{ display: 'flex', gap: 8 }}>
        <input value={host} onChange={e=>setHost(e.target.value)} placeholder="host" />
        <input value={port} onChange={e=>setPort(Number(e.target.value))} placeholder="port" />
        <input value={unitId} onChange={e=>setUnitId(Number(e.target.value))} placeholder="unit id" />
        <button onClick={probe}>Test Read/Probe</button>
      </div>
      <div style={{ marginTop: 8 }}>Status: {status}</div>
    </div>
  )
}
