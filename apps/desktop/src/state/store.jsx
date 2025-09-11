import React, { createContext, useReducer, useContext } from 'react'

const StateContext = createContext(null)

const initial = {
  // Networking reachability state (persist for session)
  reachability: {
    adapters: [
      { id: 'eth0', label: 'Ethernet', ip: '192.168.1.10', cidr: 24, gateway: '192.168.1.1' },
      { id: 'wifi0', label: 'Wi-Fi', ip: '10.0.0.5', cidr: 24, gateway: '10.0.0.1' },
    ],
    adapterId: 'eth0',
    target: '',
    lastPing: null, // { success, lossPct, min, avg, max, samples: number[] }
    portTests: [], // [{ port, status: 'open'|'closed'|'timeout', timeMs }]
    isPinging: false,
    isPortTesting: false,
  },
  // Saved devices
  devices: [], // [{ id, name, protocol: 'modbus'|'opcua', status, latencyMs, lastError, params }]
  // Saved gateways (from Reachability)
  gateways: [], // [{ id, name, host, adapterId }]
  // Database targets
  dbTargets: [], // [{ id, provider, conn, status: 'untested'|'ok'|'fail', lastMsg }]
  defaultDbTargetId: null,
  // Tables & Mapping domain
  schemas: [], // [{ id, name, fields: [{ key, type, unit, scale, desc }] }]
  tables: [], // [{ id, name, schemaId, dbTargetId, status: 'not_migrated'|'migrated'|'needs_update', lastMigratedAt, deviceId }]
  mappings: {}, // { [tableId]: { [fieldKey]: { protocol, address, dataType, scale, deadband, pollMs } } }
  // Logging & Scheduler domain
  jobs: [], // [{ id, name, type: 'continuous'|'triggered', tables: string[], columns: 'all'|string[], intervalMs: number, enabled: boolean, status: 'stopped'|'running'|'paused'|'degraded', batching: { count?: number, ms?: number }, cpuBudget: 'eco'|'balanced'|'performance', metrics: { readRate?: number, writeRate?: number, qDepth?: number, errPct?: number, p50?: number, p95?: number, nextRun?: string, lastRun?: string, errors1h?: number } }]
  alarms: { defs: [], active: [] }, // UI stubs
  buffers: { limitMb: 128, usedMb: 0, perJob: {} },
  system: { devices: {}, db: { ok: true, skewMs: 0 }, cpu: 0.2, io: 0.1 },
}

function reducer(state, action) {
  switch (action.type) {
    // Reachability
    case 'NET_PING_PENDING':
      return { ...state, reachability: { ...state.reachability, isPinging: true } }
    case 'NET_SET_ADAPTER':
      return { ...state, reachability: { ...state.reachability, adapterId: action.id } }
    case 'NET_SET_TARGET':
      return { ...state, reachability: { ...state.reachability, target: action.target } }
    case 'NET_SET_PING_RESULT':
      return { ...state, reachability: { ...state.reachability, lastPing: action.result, isPinging: false } }
    case 'NET_PORTS_PENDING':
      return { ...state, reachability: { ...state.reachability, isPortTesting: true } }
    case 'NET_SET_PORT_RESULTS':
      return { ...state, reachability: { ...state.reachability, portTests: action.results, isPortTesting: false } }

    // Saved Gateways
    case 'GW_ADD': {
      const gw = action.gateway || {}
      // Upsert by id if present, else by (name or host)
      let updated = false
      const gateways = state.gateways.map(g => {
        if ((gw.id && g.id === gw.id) || (!gw.id && (g.name === gw.name || g.host === gw.host))) {
          updated = true
          return { ...g, ...gw }
        }
        return g
      })
      const list = updated ? gateways : [...gateways, gw]
      return { ...state, gateways: list }
    }
    case 'GW_DELETE': {
      const gateways = state.gateways.filter(g => g.id !== action.id)
      return { ...state, gateways }
    }

    // Devices
    case 'DEV_SET_ALL': {
      const seen = new Set()
      const items = []
      for (const d of (action.items||[])) {
        if (!d || !d.id || seen.has(d.id)) continue
        seen.add(d.id)
        items.push(d)
      }
      return { ...state, devices: items }
    }
    case 'DEV_ADD': {
      const d = action.device
      let updated = false
      const devices = (state.devices||[]).map(x => {
        if (x.id === d.id || (x.name||'').toLowerCase() === (d.name||'').toLowerCase()) { updated = true; return { ...x, ...d } }
        return x
      })
      return { ...state, devices: updated ? devices : [...devices, d] }
    }
    case 'DEV_UPDATE_STATUS': {
      const devices = state.devices.map(d => d.id === action.id ? { ...d, ...action.patch } : d)
      return { ...state, devices }
    }
    case 'DEV_DELETE': {
      const devices = state.devices.filter(d => d.id !== action.id)
      return { ...state, devices }
    }

    // Database targets
    case 'DB_ADD_TARGET': {
      // Upsert to avoid duplicates
      const idx = state.dbTargets.findIndex(t => t.id === action.target.id)
      const dbTargets = idx >= 0
        ? state.dbTargets.map((t,i) => i===idx ? { ...t, ...action.target } : t)
        : [...state.dbTargets, action.target]
      return { ...state, dbTargets }
    }
    case 'DB_SET_ALL': {
      // Replace list, de-duplicated by id
      const seen = new Set()
      const dbTargets = []
      for (const t of (action.items||[])) {
        if (!t || !t.id || seen.has(t.id)) continue
        seen.add(t.id); dbTargets.push(t)
      }
      return { ...state, dbTargets }
    }
    case 'DB_UPDATE_TARGET': {
      const dbTargets = state.dbTargets.map(t => t.id === action.id ? { ...t, ...action.patch } : t)
      return { ...state, dbTargets }
    }
    case 'DB_MARK_TESTING': {
      const dbTargets = state.dbTargets.map(t => t.id === action.id ? { ...t, status: 'testing' } : t)
      return { ...state, dbTargets }
    }
    case 'DB_DELETE_TARGET': {
      const dbTargets = state.dbTargets.filter(t => t.id !== action.id)
      return { ...state, dbTargets }
    }
    case 'DB_SET_DEFAULT':
      return { ...state, defaultDbTargetId: action.id }

  // Schemas
    case 'SCH_SET_ALL': {
      // Replace list with de-duplicated by id
      const seen = new Set()
      const items = []
      for (const s of (action.items||[])) {
        if (!s || !s.id || seen.has(s.id)) continue
        seen.add(s.id)
        items.push(s)
      }
      return { ...state, schemas: items }
    }
    case 'SCH_ADD':
      return { ...state, schemas: [...state.schemas, action.schema] }
    case 'SCH_UPDATE': {
      const schemas = state.schemas.map(s => s.id === action.id ? { ...s, ...action.patch } : s)
      return { ...state, schemas }
    }

  // Device tables
    case 'TBL_SET_ALL': {
      // Replace entire table list with normalized items
      const seen = new Set()
      const items = []
      for (const t of (action.items||[])) {
        if (!t || !t.id || seen.has(t.id)) continue
        seen.add(t.id)
        items.push(t)
      }
      return { ...state, tables: items }
    }
    case 'TBL_ADD_BULK':
      return { ...state, tables: [...state.tables, ...action.tables] }
    case 'TBL_UPDATE': {
      const tables = state.tables.map(t => t.id === action.id ? { ...t, ...action.patch } : t)
      return { ...state, tables }
    }

    // Mappings
    case 'MAP_SET_DEVICE': {
      const tables = state.tables.map(t => t.id === action.tableId ? { ...t, deviceId: action.deviceId } : t)
      return { ...state, tables }
    }
    case 'MAP_UPSERT_ROW': {
      const byTable = { ...(state.mappings[action.tableId] || {}) }
      byTable[action.fieldKey] = { ...(byTable[action.fieldKey] || {}), ...action.payload }
      return { ...state, mappings: { ...state.mappings, [action.tableId]: byTable } }
    }
    case 'MAP_REPLACE_TABLE': {
      return { ...state, mappings: { ...state.mappings, [action.tableId]: action.rows } }
    }

    // Jobs & Scheduler
    case 'JOB_SET_ALL': {
      const seen = new Set()
      const items = []
      for (const j of (action.items||[])) {
        if (!j || !j.id || seen.has(j.id)) continue
        seen.add(j.id); items.push(j)
      }
      return { ...state, jobs: items }
    }
    case 'JOB_ADD':
      return { ...state, jobs: [...state.jobs, action.job] }
    case 'JOB_UPDATE': {
      const jobs = state.jobs.map(j => j.id === action.id ? { ...j, ...action.patch } : j)
      return { ...state, jobs }
    }
    case 'JOB_DELETE': {
      const jobs = state.jobs.filter(j => j.id !== action.id)
      const perJob = { ...state.buffers.perJob }; delete perJob[action.id]
      return { ...state, jobs, buffers: { ...state.buffers, perJob } }
    }
    case 'JOB_SET_STATUS': {
      const jobs = state.jobs.map(j => j.id === action.id ? { ...j, status: action.status } : j)
      return { ...state, jobs }
    }
    case 'JOB_SET_METRICS': {
      const jobs = state.jobs.map(j => j.id === action.id ? { ...j, metrics: { ...(j.metrics||{}), ...action.metrics } } : j)
      return { ...state, jobs }
    }
    case 'JOB_DUPLICATE': {
      const orig = state.jobs.find(j => j.id === action.id)
      if (!orig) return state
      const copy = { ...orig, id: 'job_' + Math.random().toString(36).slice(2,8), name: orig.name + ' (copy)', status: 'stopped', enabled: false }
      return { ...state, jobs: [...state.jobs, copy] }
    }

    // Alarms (simplified stubs)
    case 'ALARM_ADD_DEF':
      return { ...state, alarms: { ...state.alarms, defs: [...state.alarms.defs, action.def] } }
    case 'ALARM_ACK': {
      return { ...state, alarms: { ...state.alarms, active: state.alarms.active.filter(a => a.id !== action.id) } }
    }

    // Buffers/Health
    case 'BUF_UPDATE':
      return { ...state, buffers: { ...state.buffers, ...action.patch } }
    case 'BUF_SET_JOB_DEPTH': {
      const perJob = { ...state.buffers.perJob, [action.id]: action.depth }
      return { ...state, buffers: { ...state.buffers, perJob } }
    }
    case 'SYS_UPDATE':
      return { ...state, system: { ...state.system, ...action.patch } }

    default:
      return state
  }
}

export function Provider({ children }) {
  const [state, dispatch] = useReducer(reducer, initial)
  return <StateContext.Provider value={{ state, dispatch }}>{children}</StateContext.Provider>
}

export function useApp() { return useContext(StateContext) }
