import React, { useMemo, useState, useEffect } from 'react'
import { useApp } from '../../state/store.jsx'
import {
  selectJobs, selectTables, selectSchemas, selectDevices,
  selectBuffers, selectSystem, selectDbDefaultOk,
  selectAnyJobEnabled, selectAnyJobHasMappedScope, selectLoggingReady,
  selectTableMappingStatus,
} from '../../state/selectors.js'
import '../../styles/logging.css'
import { listJobs as apiListJobs, createJob as apiCreateJob, startJob as apiStartJob, stopJob as apiStopJob, pauseJob as apiPauseJob, dryRunJob as apiDryRunJob, backfillJob as apiBackfillJob, deleteJob as apiDeleteJob } from '../../lib/api/jobs.js'
import { systemMetrics as apiSystemMetrics, jobsSummary as apiJobsSummary, jobRuns as apiJobRuns, jobErrors as apiJobErrors } from '../../lib/api/metrics.js'

function Dot({ color = '#9ca3af' }) { return <span className="dot" style={{ backgroundColor: color }} aria-hidden /> }
const statusColor = (s) => s==='running' ? '#22a06b' : s==='paused' ? '#f59e0b' : s==='degraded'? '#b37feb' : '#9ca3af'

export function LoggingSchedules() {
  const { state, dispatch } = useApp()
  const jobs = selectJobs(state)
  const tables = selectTables(state)
  const schemas = selectSchemas(state)
  const devices = selectDevices(state)
  const buffers = selectBuffers(state)
  const system = selectSystem(state)
  const dbOk = selectDbDefaultOk(state)
  const jobEnabled = selectAnyJobEnabled(state)
  const jobHasMapped = selectAnyJobHasMappedScope(state)
  const ready = selectLoggingReady(state)

  const [left, setLeft] = useState('jobs') // jobs | alarms | buffers | history | utilities
  const [selJobId, setSelJobId] = useState(null)

  const selJob = useMemo(() => jobs.find(j => j.id === selJobId) || jobs[0], [jobs, selJobId])

  // ------ Job creation/edit (compact wizard) ------
  const [creating, setCreating] = useState(false)
  const [jType, setJType] = useState('continuous')
  const [jName, setJName] = useState('New Job')
  const [jTables, setJTables] = useState([])
  const [jColumns, setJColumns] = useState('all')
  const [jInterval, setJInterval] = useState(1000)
  const [jEnabled, setJEnabled] = useState(true)
  const [jBatchCount, setJBatchCount] = useState(1)
  const [jBatchMs, setJBatchMs] = useState(0)
  const [jCpu, setJCpu] = useState('balanced')
  // Trigger config (minimal)
  const [trField, setTrField] = useState('')
  const [trOp, setTrOp] = useState('>')
  const [trValue, setTrValue] = useState('')
  const [trDeadband, setTrDeadband] = useState('0')
  const saveJob = async () => {
    const payload = {
      name: jName,
      type: jType === 'triggered' ? 'trigger' : jType,
      tables: jType === 'triggered' ? (jTables && jTables.length ? [jTables[0]] : []) : jTables,
      columns: jColumns,
      intervalMs: jInterval,
      enabled: jEnabled,
      batching: { count: jBatchCount || undefined, ms: jBatchMs || undefined },
      cpuBudget: jCpu,
    }
    if (payload.type === 'trigger') {
      if (!payload.tables || payload.tables.length === 0) return
      payload.triggers = [{ tableId: payload.tables[0], field: trField, op: trOp, value: trOp==='change'? undefined : (trValue===''? undefined : Number(trValue)), deadband: trOp==='change' ? Number(trDeadband||0) : 0, cooldownMs: 0 }]
    }
    try {
      const res = await apiCreateJob(payload)
      const job = (res && res.item) ? res.item : { id: 'job_' + Math.random().toString(36).slice(2,8), ...payload, status: payload.enabled ? 'paused' : 'stopped', metrics: {} }
      dispatch({ type: 'JOB_ADD', job })
      setCreating(false); setSelJobId(job.id); setLeft('jobs')
    } catch (e) {
      const id = 'job_' + Math.random().toString(36).slice(2,8)
      dispatch({ type: 'JOB_ADD', job: { id, ...payload, status: payload.enabled ? 'paused' : 'stopped', metrics: {} } })
      setCreating(false); setSelJobId(id); setLeft('jobs')
    }
  }

  // ------ Job controls & metrics ------
  const startJob = async (id) => { try { await apiStartJob(id) } catch {} dispatch({ type: 'JOB_SET_STATUS', id, status: 'running' }) }
  const pauseJob = async (id) => { try { await apiPauseJob(id) } catch {} dispatch({ type: 'JOB_SET_STATUS', id, status: 'paused' }) }
  const stopJob = async (id) => { try { await apiStopJob(id) } catch {} dispatch({ type: 'JOB_SET_STATUS', id, status: 'stopped' }) }
  const dryRun = async (id) => {
    try {
      const res = await apiDryRunJob(id)
      const n = (res?.items||[]).length||0
      const readRate = Math.max(1, n)
      const writeRate = readRate
      const qDepth = 0
      const errPct = (res?.items||[]).some(x=>x.error) ? 100 : 0
      const p50 = 20, p95 = 60
      dispatch({ type: 'JOB_SET_METRICS', id, metrics: { readRate, writeRate, qDepth, errPct, p50, p95, lastRun: new Date().toISOString(), errors1h: 0 } })
    } catch {
      dispatch({ type: 'JOB_SET_METRICS', id, metrics: { lastRun: new Date().toISOString() } })
    }
  }
  const backfillOnce = async (id) => {
    try { await apiBackfillJob(id) } catch {}
    dispatch({ type: 'JOB_SET_METRICS', id, metrics: { ...(selJob?.metrics||{}), lastRun: new Date().toISOString() } })
  }

  // Load jobs from backend on entry
  useEffect(() => {
    (async () => {
      try {
        const res = await apiListJobs()
        const items = res?.items || []
        if (items.length) dispatch({ type: 'JOB_SET_ALL', items })
      } catch {}
    })()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Poll per-job metrics summary every 2s
  useEffect(() => {
    let timer = null
    const tick = async () => {
      try {
        const res = await apiJobsSummary()
        const items = res?.data || []
        for (const m of items) {
          const id = m.jobId
          const readRate = Math.round((m.reads || 0) / 60)
          const writeRate = Math.round((m.writes || 0) / 60)
          const qDepth = 0
          const errPct = Math.round(m.errorPct || 0)
          const p50 = Math.round(m.writeP50 || 0)
          const p95 = Math.round(m.writeP95 || 0)
          dispatch({ type: 'JOB_SET_METRICS', id, metrics: { readRate, writeRate, qDepth, errPct, p50, p95 } })
        }
      } catch {}
      timer = setTimeout(tick, 2000)
    }
    tick()
    return () => { if (timer) clearTimeout(timer) }
  }, [dispatch])

  // Poll system metrics every 2s for Buffers & Health
  useEffect(() => {
    let timer = null
    const tick = async () => {
      try {
        const res = await apiSystemMetrics('60s')
        const items = (res?.data?.timeseries) || []
        const last = items[items.length - 1] || {}
        const cpu = ((last.cpu || 0) / 100)
        const disk = (last.disk_rps || 0) + (last.disk_wps || 0)
        const net = (last.net_rxps || 0) + (last.net_txps || 0)
        const bytes = (disk || 0) + (net || 0)
        const io = Math.max(0, Math.min(1, bytes / (5 * 1024 * 1024)))
        dispatch({ type: 'SYS_UPDATE', patch: { cpu, io } })
      } catch {}
      timer = setTimeout(tick, 2000)
    }
    tick()
    return () => { if (timer) clearTimeout(timer) }
  }, [dispatch])

  // History & Reports: load runs and errors when tab open or selection changes
  const [runs, setRuns] = useState([])
  const [errors, setErrors] = useState([])
  useEffect(() => {
    if (left !== 'history' || !selJob) return
    (async () => {
      try {
        const [rr, ee] = await Promise.all([
          apiJobRuns(selJob.id),
          apiJobErrors(selJob.id),
        ])
        setRuns(rr?.data || [])
        setErrors(ee?.data || [])
      } catch (e) {
        setRuns([]); setErrors([])
      }
    })()
  }, [left, selJob?.id])

  // Poll runs while on History tab for near real-time updates
  useEffect(() => {
    if (left !== 'history' || !selJob) return
    let timer = null
    const poll = async () => {
      try {
        const rr = await apiJobRuns(selJob.id)
        setRuns(rr?.data || [])
      } catch {}
      timer = setTimeout(poll, 3000)
    }
    poll()
    return () => { if (timer) clearTimeout(timer) }
  }, [left, selJob?.id])

  // ------ Alarms (stubs) ------
  const [alarmName, setAlarmName] = useState('New Alarm')
  const [alarmField, setAlarmField] = useState('')
  const addAlarm = () => {
    const id = 'alm_' + Math.random().toString(36).slice(2,8)
    dispatch({ type: 'ALARM_ADD_DEF', def: { id, name: alarmName, field: alarmField } })
  }

  return (
    <div className="logging">
      <div className="layout">
        <aside className="rail" aria-label="Logging sections">
          <button className={`rail-item ${left==='jobs'?'active':''}`} onClick={()=>setLeft('jobs')}>
            <div className="rail-title">Jobs</div>
            <div className="rail-sub">{jobs.length} total</div>
          </button>
          <button className={`rail-item ${left==='alarms'?'active':''}`} onClick={()=>setLeft('alarms')}>
            <div className="rail-title">Alarms</div>
            <div className="rail-sub">define, arm, acknowledge</div>
          </button>
          <button className={`rail-item ${left==='buffers'?'active':''}`} onClick={()=>setLeft('buffers')}>
            <div className="rail-title">Buffers & Health</div>
            <div className="rail-sub">queues, CPU/IO budget</div>
          </button>
          <button className={`rail-item ${left==='history'?'active':''}`} onClick={()=>setLeft('history')}>
            <div className="rail-title">History & Reports</div>
            <div className="rail-sub">runs, errors</div>
          </button>
          <button className={`rail-item ${left==='utilities'?'active':''}`} onClick={()=>setLeft('utilities')}>
            <div className="rail-title">Utilities</div>
            <div className="rail-sub">templates, validation</div>
          </button>
        </aside>

        <main className="main" aria-live="polite">
          {left === 'jobs' && (
            <section>
              <h3>Jobs</h3>
              {!creating && <button onClick={()=>setCreating(true)}>Create Job</button>}
              {creating && (
                <div className="card">
                  <div className="row"><label>Name</label><input value={jName} onChange={e=>setJName(e.target.value)} /></div>
                  <div className="row"><label>Type</label>
                    <select value={jType} onChange={e=>setJType(e.target.value)}>
                      <option value="continuous">Continuous</option>
                      <option value="triggered">Triggered</option>
                    </select>
                  </div>
                  {jType==='continuous' && (
                    <>
                      <div className="row"><label>Scope tables</label>
                        <select multiple value={jTables} onChange={e=>setJTables(Array.from(e.target.selectedOptions).map(o=>o.value))}>
                          {tables.filter(t=>selectTableMappingStatus(state,t.id)!=='Unmapped').map(t=>(<option key={t.id} value={t.id}>{t.name}</option>))}
                        </select>
                      </div>
                      <div className="row"><label>Interval (ms)</label><input type="number" value={jInterval} onChange={e=>setJInterval(Number(e.target.value)||0)} /></div>
                    </>
                  )}
                  {jType==='triggered' && (
                    <>
                      <div className="row"><label>Target table</label>
                        <select value={jTables[0]||''} onChange={e=>setJTables(e.target.value? [e.target.value] : [])}>
                          <option value="">Select table…</option>
                          {tables.filter(t=>selectTableMappingStatus(state,t.id)!=='Unmapped').map(t=>(<option key={t.id} value={t.id}>{t.name}</option>))}
                        </select>
                      </div>
                      <div className="row"><label>Trigger</label>
                        <select value={trField} onChange={e=>setTrField(e.target.value)}>
                          <option value="">field…</option>
                          {(schemas.find(s=>s.id===tables.find(t=>t.id===(jTables[0]||''))?.schemaId)?.fields||[]).map(f => (<option key={f.key} value={f.key}>{f.key}</option>))}
                        </select>
                        <select value={trOp} onChange={e=>setTrOp(e.target.value)}>
                          <option value=">">&gt;</option>
                          <option value=">=">&gt;=</option>
                          <option value="<">&lt;</option>
                          <option value="<=">&lt;=</option>
                          <option value="==">==</option>
                          <option value="!=">!=</option>
                          <option value="change">change</option>
                          <option value="rising">rising</option>
                          <option value="falling">falling</option>
                        </select>
                        {trOp==='change' ? (
                          <input type="number" value={trDeadband} onChange={e=>setTrDeadband(e.target.value)} placeholder="deadband" />
                        ) : (
                          <input type="number" value={trValue} onChange={e=>setTrValue(e.target.value)} placeholder="threshold" />
                        )}
                      </div>
                    </>
                  )}
                  <div className="row"><label>Batching</label>
                    <input type="number" value={jBatchCount} onChange={e=>setJBatchCount(Number(e.target.value)||0)} placeholder="count" />
                    <input type="number" value={jBatchMs} onChange={e=>setJBatchMs(Number(e.target.value)||0)} placeholder="ms" />
                  </div>
                  <div className="row"><label>CPU budget</label>
                    <select value={jCpu} onChange={e=>setJCpu(e.target.value)}>
                      <option value="eco">Eco</option>
                      <option value="balanced">Balanced</option>
                      <option value="performance">Performance</option>
                    </select>
                  </div>
                  <div className="row"><label>Enabled</label><input type="checkbox" checked={jEnabled} onChange={e=>setJEnabled(e.target.checked)} /></div>
                  <div className="row">
                    <button onClick={saveJob}>Save</button>
                    <button onClick={()=>setCreating(false)}>Cancel</button>
                  </div>
                </div>
              )}

              <div className="table" style={{ marginTop: 12 }}>
                <div className="line head"><div>Name</div><div>Type</div><div>Scope</div><div>Interval</div><div>Batching</div><div>Status</div><div>Next</div><div>Last</div><div>Errors</div><div></div></div>
                {jobs.length===0 && <div className="empty">No jobs yet.</div>}
                {jobs.map(j => (
                  <div key={j.id} className={`line ${selJobId===j.id?'sel':''}`} onClick={()=>setSelJobId(j.id)}>
                    <div>{j.name}</div>
                    <div>{j.type}</div>
                    <div>{(j.tables||[]).length} table(s)</div>
                    <div>{j.type==='continuous'? (j.intervalMs+'ms') : 'triggered'}</div>
                    <div>{j.batching?.count||1}/{j.batching?.ms||0}ms</div>
                    <div><Dot color={statusColor(j.status)} /> {j.status||'stopped'}</div>
                    <div>{j.metrics?.nextRun || '—'}</div>
                    <div>{j.metrics?.lastRun || '—'}</div>
                    <div>{j.metrics?.errors1h ?? 0}</div>
                    <div className="cell act">
                      <button onClick={(e)=>{e.stopPropagation(); startJob(j.id)}}>Start</button>
                      <button onClick={(e)=>{e.stopPropagation(); pauseJob(j.id)}}>Pause</button>
                      <button onClick={(e)=>{e.stopPropagation(); stopJob(j.id)}}>Stop</button>
                      <button onClick={(e)=>{e.stopPropagation(); dryRun(j.id)}}>Dry-Run 60s</button>
                      <button onClick={(e)=>{e.stopPropagation(); backfillOnce(j.id)}}>Backfill once</button>
                      <button onClick={(e)=>{e.stopPropagation(); dispatch({ type:'JOB_DUPLICATE', id:j.id })}}>Duplicate</button>
                      <button onClick={async (e)=>{
                        e.stopPropagation()
                        try {
                          await apiDeleteJob(j.id)
                          dispatch({ type:'JOB_DELETE', id:j.id })
                        } catch (err) {
                          console.error('JOB_DELETE_FAILED', err)
                          alert('Delete failed')
                        }
                      }}>Delete</button>
                    </div>
                  </div>
                ))}
              </div>

              {selJob && (
                <div className="card" style={{ marginTop: 12 }}>
                  <strong>{selJob.name}</strong>
                  <div className="metrics">
                    <div>Read: {selJob.metrics?.readRate ?? 0}/s</div>
                    <div>Write: {selJob.metrics?.writeRate ?? 0}/s</div>
                    <div>Queue: {selJob.metrics?.qDepth ?? 0}</div>
                    <div>Errors: {selJob.metrics?.errPct ?? 0}%</div>
                    <div>p50: {selJob.metrics?.p50 ?? 0}ms</div>
                    <div>p95: {selJob.metrics?.p95 ?? 0}ms</div>
                  </div>
                </div>
              )}
            </section>
          )}

          {left === 'alarms' && (
            <section>
              <h3>Alarms</h3>
              <div className="card">
                <div className="row"><label>Name</label><input value={alarmName} onChange={e=>setAlarmName(e.target.value)} /></div>
                <div className="row"><label>Field</label><input value={alarmField} onChange={e=>setAlarmField(e.target.value)} placeholder="table.field" /></div>
                <div className="row"><button onClick={addAlarm}>Add Alarm</button></div>
              </div>
              <div className="hint">Alarm definitions and actions are UI stubs.</div>
            </section>
          )}

          {left === 'buffers' && (
            <section>
              <h3>Buffers & Health</h3>
              <div className="card">
                <strong>Store-and-forward</strong>
                <div className="row">
                  <div className="bar"><div className="bar-fill" style={{ width: `${Math.min(100, (buffers.usedMb/buffers.limitMb)*100||0)}%` }} /></div>
                  <span>{buffers.usedMb} / {buffers.limitMb} MB</span>
                </div>
              </div>
              <div className="card">
                <strong>Per-job queues</strong>
                {jobs.map(j => (
                  <div key={j.id} className="row"><span>{j.name}</span><div className="bar small"><div className="bar-fill" style={{ width: `${Math.min(100,(buffers.perJob[j.id]||0))}%` }} /></div></div>
                ))}
              </div>
              <div className="card">
                <strong>System</strong>
                <div className="row"><label>CPU</label><div className="bar small"><div className="bar-fill" style={{ width: `${(system.cpu*100)|0}%` }} /></div></div>
                <div className="row"><label>I/O</label><div className="bar small"><div className="bar-fill" style={{ width: `${(system.io*100)|0}%` }} /></div></div>
                <div className="row"><button onClick={()=>{ jobs.forEach(j=>dispatch({ type:'JOB_SET_STATUS', id:j.id, status:'stopped' })); dispatch({ type:'BUF_UPDATE', patch:{ usedMb:0, perJob:{} }}) }}>Drain and stop all jobs</button></div>
              </div>
            </section>
          )}

          {left === 'history' && (
            <section>
              <h3>History & Reports</h3>
              {selJob ? (
                <>
                  <div className="card">
                    <strong>Runs for {selJob.name}</strong>
                    <div className="table" style={{ marginTop: 8 }}>
                      <div className="line head" style={{ gridTemplateColumns: '1fr 1fr .6fr .6fr .6fr .6fr' }}>
                        <div>Started</div><div>Stopped</div><div>Duration</div><div>Rows</div><div>Read avg</div><div>Write avg</div>
                      </div>
                      {runs.length === 0 && <div className="empty">No runs yet.</div>}
                      {runs.map(r => (
                        <div key={r.id} className="line" style={{ gridTemplateColumns: '1fr 1fr .6fr .6fr .6fr .6fr' }}>
                          <div>{r.started_at || '—'}</div>
                          <div>{r.stopped_at || '—'}</div>
                          <div>{(r.duration_ms||0)} ms</div>
                          <div>{r.rows||0}</div>
                          <div>{Math.round(r.read_lat_avg||0)} ms</div>
                          <div>{Math.round(r.write_lat_avg||0)} ms</div>
                        </div>
                      ))}
                    </div>
                    <div className="row">
                      <a href={(import.meta.env.VITE_AGENT_BASE_URL || 'http://127.0.0.1:5175') + `/reports/runs.csv?job_id=${encodeURIComponent(selJob.id)}`} target="_blank" rel="noreferrer">Export runs CSV</a>
                      <a href={(import.meta.env.VITE_AGENT_BASE_URL || 'http://127.0.0.1:5175') + `/reports/errors.csv?job_id=${encodeURIComponent(selJob.id)}`} target="_blank" rel="noreferrer">Export errors CSV</a>
                    </div>
                  </div>
                  <div className="card">
                    <strong>Top errors (last hour)</strong>
                    <div className="table" style={{ marginTop: 8 }}>
                      <div className="line head" style={{ gridTemplateColumns: '1fr .4fr 2fr' }}>
                        <div>Code</div><div>Count</div><div>Last message</div>
                      </div>
                      {errors.length === 0 && <div className="empty">No errors recorded.</div>}
                      {errors.map((e,i) => (
                        <div key={i} className="line" style={{ gridTemplateColumns: '1fr .4fr 2fr' }}>
                          <div>{e.code}</div>
                          <div>{e.count}</div>
                          <div title={e.lastMessage}>{e.lastMessage}</div>
                        </div>
                      ))}
                    </div>
                  </div>
                </>
              ) : (
                <div className="hint">Select a job to see history.</div>
              )}
            </section>
          )}

          {left === 'utilities' && (
            <section>
              <h3>Utilities</h3>
              <div className="row">
                <button>Import jobs</button>
                <button>Export jobs</button>
                <button>Templates</button>
                <button>Validation center</button>
              </div>
            </section>
          )}

          <div className="gate">
            <div className="checks">
              <div><Dot color={jobHasMapped?'#22a06b':'#ef4444'} /> A job selects a mapped table</div>
              <div><Dot color={jobEnabled?'#22a06b':'#ef4444'} /> A job is enabled</div>
              <div><Dot color={dbOk?'#22a06b':'#ef4444'} /> Default DB is OK</div>
            </div>
            {ready ? (
              <div className="hint">Ready to run</div>
            ) : (
              <div className="hint">Complete the unmet items above.</div>
            )}
          </div>
        </main>
      </div>
    </div>
  )
}
