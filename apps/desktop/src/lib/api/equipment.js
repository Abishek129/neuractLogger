import { request, setToken } from './client.js'

// ---- Auth (Keycloak password grant via the agent) ----
export async function login(username, password) {
  const data = await request('/auth/login', { method: 'POST', body: { username, password } })
  setToken(data.access_token)
  try { localStorage.setItem('agent_refresh_token', data.refresh_token || '') } catch {}
  return data
}

export async function refresh() {
  let rt = ''
  try { rt = localStorage.getItem('agent_refresh_token') || '' } catch {}
  if (!rt) return false
  try {
    const data = await request('/auth/refresh', { method: 'POST', body: { refresh_token: rt } })
    setToken(data.access_token)
    try { localStorage.setItem('agent_refresh_token', data.refresh_token || rt) } catch {}
    return true
  } catch {
    return false
  }
}

export function logout() {
  setToken(null)
  try { localStorage.removeItem('agent_refresh_token') } catch {}
}

// Equipment calls retry once after a silent token refresh (Keycloak tokens are short-lived).
async function eq(path, opts) {
  try {
    return await request('/equipment' + path, opts)
  } catch (e) {
    if (e.status === 401 && (await refresh())) return request('/equipment' + path, opts)
    throw e
  }
}

/** Human-readable message from an API error ("CODE: context" detail strings). */
export function errorText(e) {
  try {
    const body = JSON.parse(e.body || '')
    const d = body.detail
    if (typeof d === 'string') return d
    if (d && (d.message || d.error)) return d.message || d.error
  } catch {}
  return e.message || String(e)
}

// ---- Categories (read-only; edited in the DB) ----
export const listCategories = () => eq('/categories').then((r) => r.items)

// ---- Equipment ----
export const listEquipment = () => eq('').then((r) => r.items)
export const getEquipment = (id) => eq(`/${id}`).then((r) => r.item)
export const createEquipment = (body) => eq('', { method: 'POST', body }).then((r) => r.item)
export const updateEquipment = (id, body) => eq(`/${id}`, { method: 'PUT', body }).then((r) => r.item)
export const deleteEquipment = (id) => eq(`/${id}`, { method: 'DELETE' })

// ---- Buses (distribution equipment only) ----
export const setBusCount = (id, count) => eq(`/${id}/buses/count`, { method: 'PUT', body: { count } }).then((r) => r.items)
export const addBus = (id, body = {}) => eq(`/${id}/buses`, { method: 'POST', body }).then((r) => r.item)
export const updateBus = (busId, patch) => eq(`/buses/${busId}`, { method: 'PUT', body: patch }).then((r) => r.item)
export const deleteBus = (busId) => eq(`/buses/${busId}`, { method: 'DELETE' })
export const attachEquipment = (busId, equipmentId, role) =>
  eq(`/buses/${busId}/equipment`, { method: 'POST', body: { equipmentId, role } }).then((r) => r.item)
export const detachEquipment = (busId, equipmentId) =>
  eq(`/buses/${busId}/equipment/${equipmentId}`, { method: 'DELETE' }).then((r) => r.item)

// ---- MFMs attached to equipment ----
export const availableMeters = () => eq('/available_meters').then((r) => r.items)
export const attachMeter = (id, deviceId) => eq(`/${id}/meters`, { method: 'POST', body: { deviceId } }).then((r) => r.items)
export const detachMeter = (id, deviceId) => eq(`/${id}/meters/${deviceId}`, { method: 'DELETE' }).then((r) => r.items)
