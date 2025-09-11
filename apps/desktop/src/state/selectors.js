export const selectReachability = (s) => s.reachability
export const selectDevices = (s) => s.devices
export const selectDbTargets = (s) => s.dbTargets
export const selectGateways = (s) => s.gateways
export const selectDefaultDbTargetId = (s) => s.defaultDbTargetId

export const selectHasConnectedDevice = (s) => s.devices.some(d => d.status === 'connected')
export const selectDbDefaultOk = (s) => {
  const id = s.defaultDbTargetId
  if (!id) return false
  const t = s.dbTargets.find(x => x.id === id)
  return !!t && t.status === 'ok'
}
export const selectGateSatisfied = (s) => selectHasConnectedDevice(s) && selectDbDefaultOk(s)

// Tables & Mapping domain
export const selectSchemas = (s) => s.schemas
export const selectTables = (s) => s.tables
export const selectMappings = (s) => s.mappings

export const selectUsedByCount = (s, schemaId) => s.tables.filter(t => t.schemaId === schemaId).length

export const selectTableMappingStatus = (s, tableId) => {
  const t = s.tables.find(x => x.id === tableId)
  if (!t) return 'Unmapped'
  const sch = s.schemas.find(sc => sc.id === t.schemaId)
  const rows = (s.mappings[tableId]) || {}
  const total = sch?.fields?.length || 0
  if (total === 0) return Object.keys(rows).length ? 'Mapped' : 'Unmapped'
  const dev = s.devices.find(d => d.id === t.deviceId)
  const proto = (dev?.protocol || '').toLowerCase()
  let mapped = 0
  for (const f of (sch?.fields || [])) {
    const r = rows[f.key] || {}
    const rp = (r.protocol || '').toLowerCase()
    const useProto = proto || rp
    if (useProto === 'opcua') {
      if (r && r.address) mapped++
    } else if (useProto === 'modbus') {
      if (r && r.address && r.dataType) mapped++
    } else {
      // Unknown: accept address as minimal mapping signal
      if (r && r.address) mapped++
    }
  }
  if (mapped === 0) return 'Unmapped'
  if (mapped < total) return 'Partially Mapped'
  return 'Mapped'
}

export const selectTablesGateSatisfied = (s) => {
  const hasSchema = s.schemas.length > 0
  const hasMigrated = s.tables.some(t => t.status === 'migrated')
  const hasMapped = s.tables.some(t => selectTableMappingStatus(s, t.id) === 'Mapped')
  return hasSchema && hasMigrated && hasMapped
}

// Logging & Schedules domain
export const selectJobs = (s) => s.jobs
export const selectAlarms = (s) => s.alarms
export const selectBuffers = (s) => s.buffers
export const selectSystem = (s) => s.system

export const selectAnyJobEnabled = (s) => s.jobs.some(j => j.enabled)
export const selectAnyJobHasMappedScope = (s) => s.jobs.some(j =>
  (j.tables||[]).some(tid => selectTableMappingStatus(s, tid) === 'Mapped')
)
export const selectLoggingReady = (s) => selectAnyJobEnabled(s) && selectAnyJobHasMappedScope(s) && selectDbDefaultOk(s)
