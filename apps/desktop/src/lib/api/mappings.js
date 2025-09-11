import { request } from './client.js'

export const getMapping = (tableId) => request(`/mappings/${encodeURIComponent(tableId)}`)
export const upsertMapping = (tableId, payload) => request(`/mappings/${encodeURIComponent(tableId)}`, { method: 'POST', body: payload })
export const bulkApply = (tableId, payload) => request(`/mappings/${encodeURIComponent(tableId)}/bulk_apply`, { method: 'POST', body: payload })
export const importMappings = (tableId, payload) => request(`/mappings/${encodeURIComponent(tableId)}/import`, { method: 'POST', body: payload })
export const validateMappings = (tableId, payload) => request(`/mappings/${encodeURIComponent(tableId)}/validate`, { method: 'POST', body: payload })
export const deleteMappingRow = (tableId, fieldKey) => request(`/mappings/${encodeURIComponent(tableId)}/${encodeURIComponent(fieldKey)}`, { method: 'DELETE' })
