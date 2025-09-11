import { request } from './client.js'

export const bulkCreate = (payload) => request('/tables/bulk_create', { method: 'POST', body: payload })
export const dryRunDDL = (payload) => request('/tables/dry_run_ddl', { method: 'POST', body: payload })
export const migrate = (payload) => request('/tables/migrate', { method: 'POST', body: payload })
export const getTable = (id) => request(`/tables/${encodeURIComponent(id)}`)
export const listTables = (params = {}) => {
  const qs = new URLSearchParams(params).toString()
  return request('/tables' + (qs ? ('?' + qs) : ''))
}
export const discoverTables = (params = {}) => {
  const qs = new URLSearchParams(params).toString()
  return request('/tables/discover' + (qs ? ('?' + qs) : ''))
}
