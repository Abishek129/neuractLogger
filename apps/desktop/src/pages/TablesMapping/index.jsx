import React, { useEffect, useMemo, useState } from 'react'
import { createSchema, listSchemas as apiListSchemas } from '../../lib/api/schemas.js'
import { bulkCreate as apiBulkCreate, migrate as apiMigrate, discoverTables as apiDiscover, getTable as apiGetTable } from '../../lib/api/tables.js'
import { getMapping as apiGetMapping, upsertMapping as apiUpsertMapping, validateMappings as apiValidate } from '../../lib/api/mappings.js'
import { useApp } from '../../state/store.jsx'
import {
  selectSchemas,
  selectTables,
  selectMappings,
  selectDbTargets,
  selectDefaultDbTargetId,
  selectDevices,
  selectTablesGateSatisfied,
  selectTableMappingStatus,
} from '../../state/selectors.js'
import '../../styles/tables.css'

function ModalFeedbackSection({ table, rowsState, devices, mappingStatus, onClose, onNext }) {
  const [feedback, setFeedback] = useState(null)
  const [saving, setSaving] = useState(false)
  const [validating, setValidating] = useState(false)
  const [postPrompt, setPostPrompt] = useState(false)

  const runValidate = async () => {
    if (!table) return
    setValidating(true)
    try {
      const dev = devices.find(d => d.id === table.deviceId)
      const rows = Object.fromEntries(Object.entries(rowsState || {}).map(([k, v]) => [k, { ...v, protocol: dev?.protocol || v.protocol }]))
      const res = await apiValidate(table.id, { deviceId: table.deviceId || null, rows })
      setFeedback(res)
      setPostPrompt(false)
    } catch (e) {
      setFeedback({ success: false, problems: [{ code: 'VALIDATION_FAILED', detail: String(e?.message || e) }] })
    } finally {
      setValidating(false)
    }
  }

  const handleSave = async () => {
    if (!table) return
    setSaving(true)
    try {
      const dev = devices.find(d => d.id === table.deviceId)
      const rows = Object.fromEntries(Object.entries(rowsState || {}).map(([k, v]) => [k, { ...v, protocol: dev?.protocol || v.protocol }]))
      // Validate first; only save on success
      const vres = await apiValidate(table.id, { deviceId: table.deviceId || null, rows })
      setFeedback(vres)
      if (!vres?.success) { setPostPrompt(false); return }
      await apiUpsertMapping(table.id, { deviceId: table.deviceId || null, rows })
      setPostPrompt(true)
    } catch (e) {
      setFeedback({ success: false, problems: [{ code: 'SAVE_FAILED', detail: String(e?.message || e) }] })
    } finally {
      setSaving(false)
    }
  }

  const problems = feedback?.problems || []
  const success = feedback?.success
  const hasIssues = problems.length > 0
  return (
    <div className="row" style={{ marginTop: 8, flexDirection: 'column' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <span>Table status: <StatusPill status={mappingStatus} /></span>
        <button onClick={handleSave} disabled={!table || saving}>{saving ? 'Saving…' : 'Validate & Save'}</button>
        <button onClick={runValidate} disabled={!table || validating}>{validating ? 'Validating…' : 'Validate only'}</button>
      </div>
      {feedback && (
        <div className="card" style={{ marginTop: 8 }}>
          {success && !hasIssues ? (
            <div style={{ color: '#22a06b' }}>Validation passed</div>
          ) : (
            <div style={{ color: '#ef4444' }}>
              {problems.length} issue(s)
            </div>
          )}
          {problems.length > 0 && (
            <div style={{ marginTop: 6 }}>
              {problems.map((p, i) => (
                <div key={i} className="line">
                  <div className="cell" style={{ width: 160 }}>{p.field || '—'}</div>
                  <div className="cell">{p.code}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
      {postPrompt && (
        <div className="row" style={{ marginTop: 8, gap: 8 }}>
          <button onClick={onNext}>Next table</button>
          <button onClick={onClose}>Close</button>
        </div>
      )}
    </div>
  )
}

function Dot({ color = '#9ca3af' }) {
  return <span className="dot" style={{ backgroundColor: color }} aria-hidden />
}

function StatusPill({ status }) {
  const map = {
    'Not migrated': '#ef4444',
    'Migrated': '#22a06b',
    'Needs update': '#f59e0b',
    'Unmapped': '#9ca3af',
    'Partially Mapped': '#f59e0b',
    'Mapped': '#22a06b'
  }
  const color = map[status] || '#9ca3af'
  return <span className="pill"><span className="dot" style={{ backgroundColor: color }} /> {status}</span>
}

function expandPattern(text) {
  // Supports Pattern `{1..N}` sequential expansion; falls back to single name
  const m = /^(.*)\{(\d+)\.\.(\d+)\}(.*)$/.exec(text || '')
  if (!m) return [text]
  const [, pre, a, b, post] = m
  const start = parseInt(a, 10), end = parseInt(b, 10)
  const list = []
  for (let i = start; i <= end; i++) list.push(`${pre}${i}${post}`)
  return list
}

export function TablesMapping({ onProceed }) {
  const { state, dispatch } = useApp()
  const schemas = selectSchemas(state)
  const tables = selectTables(state)
  const mappings = selectMappings(state)
  const targets = selectDbTargets(state)
  const defaultTargetId = selectDefaultDbTargetId(state)
  const devices = selectDevices(state)
  const gateOK = selectTablesGateSatisfied(state)

  const [left, setLeft] = useState('schemas') // 'schemas' | 'tables' | 'utilities'
  const [selSchemaId, setSelSchemaId] = useState(null)
  const [selTableId, setSelTableId] = useState(null)
  const [mapModalOpen, setMapModalOpen] = useState(false)

  // Top DB display
  const defaultTarget = useMemo(() => targets.find(t => t.id === defaultTargetId), [targets, defaultTargetId])

  // ----------------- Schemas -----------------
  const [schName, setSchName] = useState('NewSchema')
  const [schFields, setSchFields] = useState([{ key: 'r_current', type: 'float', unit: 'A', scale: 1, desc: '' }])
  const refetchSchemas = async () => {
    try {
      const res = await apiListSchemas()
      const items = res.items || []
      dispatch({ type: 'SCH_SET_ALL', items })
    } catch {}
  }
  const saveSchema = async () => {
    if (!schName.trim()) return
    // Basic client-side field validation
    const seen = new Set()
    for (const f of schFields) {
      const k = (f.key||'').trim()
      if (!k || !/^[_A-Za-z][_A-Za-z0-9]*$/.test(k)) {
        alert('Field keys must be SQL-safe and non-empty')
        return
      }
      if (seen.has(k)) { alert('Duplicate field key: ' + k); return }
      seen.add(k)
    }
    try {
      const res = await createSchema({ name: schName.trim(), fields: schFields })
      const item = res.item || { id: res.id, name: schName.trim(), fields: schFields }
      dispatch({ type: 'SCH_ADD', schema: item })
      setSelSchemaId(item.id)
      // confirm durability
      await refetchSchemas()
    } catch (e) {
      // fallback local
      const id = 'sch_' + Math.random().toString(36).slice(2, 8)
      dispatch({ type: 'SCH_ADD', schema: { id, name: schName.trim(), fields: schFields } })
      setSelSchemaId(id)
    }
    setLeft('tables')
  }
  const addField = () => setSchFields([...schFields, { key: '', type: 'float', unit: '', scale: 1, desc: '' }])
  const updateField = (i, patch) => setSchFields(s => s.map((f, idx) => idx === i ? { ...f, ...patch } : f))
  const removeField = (i) => setSchFields(s => s.filter((_, idx) => idx !== i))

  // Handle deep-link: ?mapping=<tableId>
  useEffect(() => {
    try {
      const u = new URL(window.location.href)
      const mId = u.searchParams.get('mapping')
      if (mId) {
        setSelTableId(mId)
        setLeft('tables')
        setMapModalOpen(true)
      }
    } catch {}
  }, [])

  // ----------------- Tables -----------------
  const [pattern, setPattern] = useState('Transformer-{1..5}')
  const [overrideTarget, setOverrideTarget] = useState('')
  const canMigrate = tables.some(t => t.status !== 'migrated')
  const migrateSelected = async (ids) => {
    try {
      await apiMigrate({ ids })
    } catch {}
    // Re-discover to reflect removal of logical entries and discovery of physical tables
    try {
      const res = await apiDiscover({ dbTargetId: defaultTargetId || '' })
      const planned = res.planned || []
      const migrated = res.migrated || []
      dispatch({ type: 'TBL_SET_ALL', items: [...planned, ...migrated] })
    } catch {
      ids.forEach(id => dispatch({ type: 'TBL_UPDATE', id, patch: { status: 'migrated', lastMigratedAt: new Date().toISOString() } }))
    }
  }
  const createTables = async () => {
    const schemaId = selSchemaId || (schemas[0]?.id)
    if (!schemaId) return
    try {
      const res = await apiBulkCreate({ parentSchemaId: schemaId, pattern, dbTargetId: overrideTarget || defaultTargetId || null })
      const items = res.items || []
      if (items.length) {
        dispatch({ type: 'TBL_ADD_BULK', tables: items })
        setSelTableId(items[0]?.id)
      }
    } catch {
      const names = expandPattern(pattern)
      const created = names.filter(Boolean).map(n => ({ id: 'tbl_' + Math.random().toString(36).slice(2, 8), name: n, schemaId, dbTargetId: overrideTarget || defaultTargetId || null, status: 'not_migrated', lastMigratedAt: null }))
      if (created.length) {
        dispatch({ type: 'TBL_ADD_BULK', tables: created })
        setSelTableId(created[0]?.id)
      }
    }
    // open mapping modal directly for created table
    setMapModalOpen(true)
  }

  // ----------------- Mapping -----------------
  const table = useMemo(() => tables.find(t => t.id === selTableId) || tables[0], [tables, selTableId])
  const schema = useMemo(() => schemas.find(s => s.id === (table?.schemaId)) || schemas.find(s => s.id === selSchemaId), [schemas, table, selSchemaId])
  const [modalSchema, setModalSchema] = useState(null)
  const effSchema = modalSchema || schema
  const rows = useMemo(() => (effSchema?.fields || []).map(f => ({ ...f, map: (mappings[table?.id] || {})[f.key] || {} })), [effSchema, mappings, table])
  const setDevice = (devId) => table && dispatch({ type: 'MAP_SET_DEVICE', tableId: table.id, deviceId: devId })
  const upsertRow = (fieldKey, patch) => table && dispatch({ type: 'MAP_UPSERT_ROW', tableId: table.id, fieldKey, payload: patch })
  const mappingStatus = table ? selectTableMappingStatus(state, table.id) : 'Unmapped'

  // Accessibility: ESC closes modal
  useEffect(() => {
    if (!mapModalOpen) return
    const onKey = (e) => { if (e.key === 'Escape') setMapModalOpen(false) }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [mapModalOpen])

  // Hydrate mapping rows from User DB when modal opens
  useEffect(() => {
    if (!mapModalOpen || !table?.id) return
    (async () => {
      try {
        const res = await apiGetMapping(table.id)
        const rows = (res?.item?.rows) || {}
        dispatch({ type: 'MAP_REPLACE_TABLE', tableId: table.id, rows })
        // If schema is not known, derive a temporary one from mapping keys
        try {
          const keys = Object.keys(rows || {})
          if ((!schema || !(schema.fields||[]).length) && keys.length) {
            setModalSchema({ id: 'derived', name: table?.name || 'Derived', fields: keys.map(k => ({ key: k, type: 'string', unit: '', scale: 1, desc: '' })) })
          }
        } catch {}
      } catch {}
      try {
        const td = await apiGetTable(table.id)
        if (td?.schema?.fields) setModalSchema(td.schema)
      } catch {}
    })()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mapModalOpen, table?.id])

  // Load schemas and discover tables on entry
  useEffect(() => {
    (async () => {
      try {
        await refetchSchemas()
      } catch {}
      try {
        const res = await apiDiscover({ dbTargetId: defaultTargetId || '' })
        const planned = res.planned || []
        const migrated = res.migrated || []
        dispatch({ type: 'TBL_SET_ALL', items: [...planned, ...migrated] })
        // Hydrate mapping rows from server payload when available
        const all = [...planned, ...migrated]
        all.forEach(t => {
          if (t && t.id && t.mappingRows && Object.keys(t.mappingRows).length) {
            dispatch({ type: 'MAP_REPLACE_TABLE', tableId: t.id, rows: t.mappingRows })
          }
        })
      } catch {}
    })()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [defaultTargetId])

  return (
    <div className="tables">
      <div className="topbar">
        <div className="db">Database: {defaultTarget ? `${defaultTarget.provider} • ${defaultTarget.conn}` : '— not set —'}</div>
        <div className="actions">
          <button
            disabled={!canMigrate}
            title={canMigrate?'' : 'All up-to-date'}
            onClick={async()=>{
              const ids = tables.filter(t => t.status !== 'migrated').map(t => t.id)
              if (!ids.length) return
              try {
                await apiMigrate({ ids })
                const res = await apiDiscover({ dbTargetId: defaultTargetId || '' })
                const planned = res.planned || []
                const migrated = res.migrated || []
                dispatch({ type: 'TBL_SET_ALL', items: [...planned, ...migrated] })
              } catch {
                ids.forEach(id => dispatch({ type: 'TBL_UPDATE', id, patch: { status: 'migrated', lastMigratedAt: new Date().toISOString() } }))
              }
            }}
          >Migrate All</button>
        </div>
      </div>

      <div className="layout">
        <aside className="rail" aria-label="Tables & Mapping sections">
          <button className={`rail-item ${left==='schemas'?'active':''}`} onClick={()=>setLeft('schemas')}>
            <div className="rail-title">Schemas</div>
            <div className="rail-sub">{schemas.length} defined</div>
          </button>
          <button className={`rail-item ${left==='tables'?'active':''}`} onClick={()=>setLeft('tables')}>
            <div className="rail-title">Device Tables</div>
            <div className="rail-sub">{tables.length} tables</div>
          </button>
          {/* Mapping entry removed — mapping opens from row action only */}
          <button className={`rail-item ${left==='utilities'?'active':''}`} onClick={()=>setLeft('utilities')}>
            <div className="rail-title">Utilities</div>
            <div className="rail-sub">import/export, bulk apply</div>
          </button>
        </aside>

        <main className="main" aria-live="polite">
          {left === 'schemas' && (
            <section>
              <h3>Schemas</h3>
              <div className="card">
                <div className="row"><label>Name</label><input value={schName} onChange={e=>setSchName(e.target.value)} /></div>
                <div className="grid col-6 header">
                  <div>Key</div><div>Type</div><div>Unit</div><div>Scale</div><div>Description</div><div></div>
                </div>
                {schFields.map((f,i)=>(
                  <div key={i} className="grid col-6">
                    <input value={f.key} onChange={e=>updateField(i,{ key:e.target.value })} placeholder="key" />
                    <select value={f.type} onChange={e=>updateField(i,{ type:e.target.value })}>
                      <option value="float">float</option>
                      <option value="int">int</option>
                      <option value="bool">bool</option>
                      <option value="string">string</option>
                    </select>
                    <input value={f.unit} onChange={e=>updateField(i,{ unit:e.target.value })} placeholder="unit" />
                    <input type="number" value={f.scale} onChange={e=>updateField(i,{ scale:Number(e.target.value)||0 })} />
                    <input value={f.desc} onChange={e=>updateField(i,{ desc:e.target.value })} placeholder="description" />
                    <button onClick={()=>removeField(i)}>Remove</button>
                  </div>
                ))}
                <div className="row">
                  <button onClick={addField}>Add field</button>
                  <button onClick={saveSchema}>Save schema</button>
                </div>
              </div>

              {schemas.length > 0 && (
                <div className="card" style={{ marginTop: 12 }}>
                  <strong>Existing:</strong>
                  {schemas.map(s => (
                    <div key={s.id} className="line">
                      <div className="cell name">{s.name}</div>
                      <div className="cell">{s.fields.length} fields</div>
                      <div className="cell">used by {tables.filter(t=>t.schemaId===s.id).length} tables</div>
                      <div className="cell act"><button onClick={()=>{ setSelSchemaId(s.id); setLeft('tables') }}>Select</button></div>
                    </div>
                  ))}
                </div>
              )}
            </section>
          )}

          {left === 'tables' && (
            <section>
              <h3>Device Tables</h3>
              <div className="card">
                <div className="row"><label>Parent schema</label>
                  <select value={selSchemaId || ''} onChange={e=>setSelSchemaId(e.target.value)}>
                    <option value="" disabled>Select schema…</option>
                    {schemas.map(s => (<option key={s.id} value={s.id}>{s.name}</option>))}
                  </select>
                </div>
                <div className="row"><label>Names</label>
                  <input value={pattern} onChange={e=>setPattern(e.target.value)} placeholder="Transformer-{1..5} or paste list" />
                  <button onClick={createTables}>Create</button>
                </div>
                <div className="row"><label>Target DB</label>
                  <input value={overrideTarget} onChange={e=>setOverrideTarget(e.target.value)} placeholder={defaultTarget ? `${defaultTarget.provider}:${defaultTarget.conn}` : 'inherit default'} />
                </div>
                <div className="card" style={{ marginTop: 8 }}>
                  <strong>Preview:</strong>
                  <div>{expandPattern(pattern).join(', ') || '—'}</div>
                </div>
              </div>

              <div className="table" style={{ marginTop: 12 }}>
                {tables.length === 0 && <div className="empty">No tables yet.</div>}
                {tables.map(t => (
                  <div key={t.id} className="row line">
                    <div className="cell name">{t.name}</div>
                    <div className="cell">{schemas.find(s=>s.id===t.schemaId)?.name || '—'}</div>
                    <div className="cell">{t.dbTargetId || defaultTargetId || 'default'}</div>
                    <div className="cell"><StatusPill status={t.status==='not_migrated'?'Not migrated':t.status==='needs_update'?'Needs update':'Migrated'} /></div>
                    <div className="cell"><StatusPill status={selectTableMappingStatus(state, t.id)} /></div>
                    <div className="cell act">
                      <button onClick={()=>migrateSelected([t.id])} disabled={t.status==='migrated'}>Migrate</button>
                      <button
                        onClick={()=>{ setSelTableId(t.id); setMapModalOpen(true) }}
                        disabled={String(t.id||'').startsWith('phy_')}
                        title={String(t.id||'').startsWith('phy_') ? 'Mapping requires a cataloged table' : ''}
                      >Map</button>
                    </div>
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* legacy mapping section removed; mapping via modal only */}

          {left === 'utilities' && (
            <section>
              <h3>Utilities</h3>
              <div className="row">
                <button>Import schemas</button>
                <button>Export schemas</button>
                <button>Import mapping</button>
                <button>Export mapping</button>
                <button>Bulk apply</button>
              </div>
              <div className="hint">All actions are UI stubs for now.</div>
            </section>
          )}

          {mapModalOpen && (
            <section className="modal-overlay" role="dialog" aria-modal="true">
              <div className="modal">
                <div className="modal-header">
                  <h3>Mapping: {table?.name}</h3>
                  <button onClick={()=>setMapModalOpen(false)} aria-label="Close">✕</button>
                </div>
                <div className="modal-body">
                  <div className="row">
                    <label>Table</label>
                    <select value={table?.id || ''} onChange={e=>setSelTableId(e.target.value)}>
                      {tables.map(t => (<option key={t.id} value={t.id}>{t.name}</option>))}
                    </select>
                    <span className="hint">{schema ? `Schema: ${schema.name}` : ''}</span>
                  </div>
                  <div className="row">
                    <label>Bind device</label>
                    <select value={table?.deviceId || ''} onChange={e=>setDevice(e.target.value)}>
                      <option value="">— none —</option>
                      {devices.map(d => (<option key={d.id} value={d.id}>{d.name} ({d.status})</option>))}
                    </select>
                    {table?.deviceId ? (
                      <span className="hint">Protocol locked: {devices.find(d=>d.id===table.deviceId)?.protocol || 'unknown'}</span>
                    ) : (
                      <span className="hint" style={{ color: '#ef4444' }}>DEVICE_NOT_BOUND</span>
                    )}
                  </div>
                  <div className="grid col-6 header">
                    <div>Field</div><div>Type</div><div>Address/Node</div><div>Data type</div><div>Scale</div><div>Deadband</div>
                  </div>
                  {rows.map(r => {
                    const dev = devices.find(d=>d.id===table?.deviceId)
                    const proto = dev?.protocol
                    const isOpc = proto === 'opcua'
                    return (
                      <div key={r.key} className="grid col-6">
                        <div>{r.key}</div>
                        <div>{r.type}</div>
                        <input value={r.map.address||''} onChange={e=>upsertRow(r.key,{ address:e.target.value })} placeholder={isOpc?'ns=2;s=...':'40001'} />
                        <select value={r.map.dataType||''} onChange={e=>upsertRow(r.key,{ dataType:e.target.value })} disabled={isOpc}>
                          <option value="">—</option>
                          <option value="float">float</option>
                          <option value="int">int</option>
                          <option value="bool">bool</option>
                          <option value="string">string</option>
                        </select>
                        <input type="number" value={r.map.scale??1} onChange={e=>upsertRow(r.key,{ scale:Number(e.target.value)||1 })} />
                        <input type="number" value={r.map.deadband??0} onChange={e=>upsertRow(r.key,{ deadband:Number(e.target.value)||0 })} />
                      </div>
                    )
                  })}
                  <ModalFeedbackSection
                    table={table}
                    rowsState={mappings[table?.id] || {}}
                    devices={devices}
                    mappingStatus={mappingStatus}
                    onClose={()=>setMapModalOpen(false)}
                    onNext={()=>{
                      if (!table) return
                      const idx = tables.findIndex(t => t.id === table.id)
                      const next = idx >= 0 && idx+1 < tables.length ? tables[idx+1] : null
                      if (next) { setSelTableId(next.id) } else { setMapModalOpen(false) }
                    }}
                  />
                </div>
              </div>
            </section>
          )}

          <div className="gate">
            <div className="checks">
              <div><Dot color={schemas.length>0?'#22a06b':'#ef4444'} /> At least one parent schema exists</div>
              <div><Dot color={tables.some(t=>t.status==='migrated')?'#22a06b':'#ef4444'} /> At least one device table is migrated</div>
              <div><Dot color={tables.some(t=>selectTableMappingStatus(state,t.id)==='Mapped')?'#22a06b':'#ef4444'} /> At least one table has valid mappings</div>
            </div>
            {gateOK ? (
              <button onClick={()=>onProceed && onProceed()}>Proceed to next</button>
            ) : (
              <div className="hint">Complete the unmet items above to proceed.</div>
            )}
          </div>
        </main>
      </div>
    </div>
  )
}
