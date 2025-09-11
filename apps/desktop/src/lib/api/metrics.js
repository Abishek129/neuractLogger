import { request } from './client.js'

export const systemMetrics = (range = '5m') => request(`/system/metrics?range=${encodeURIComponent(range)}`)
export const dbMetrics = (targetId, range = '15m') => request(`/db/metrics?target_id=${encodeURIComponent(targetId||'')}&range=${encodeURIComponent(range)}`)
export const jobsSummary = () => request('/jobs/metrics/summary')
export const jobMetrics = (id, range = '15m') => request(`/jobs/${id}/metrics?range=${encodeURIComponent(range)}`)
export const jobRuns = (id, params = {}) => {
  const q = new URLSearchParams()
  if (params.from) q.set('from', params.from)
  if (params.to) q.set('to', params.to)
  return request(`/jobs/${id}/runs${q.toString() ? ('?' + q.toString()) : ''}`)
}
export const jobErrors = (id, params = {}) => {
  const q = new URLSearchParams()
  if (params.from) q.set('from', params.from)
  if (params.to) q.set('to', params.to)
  return request(`/jobs/${id}/errors${q.toString() ? ('?' + q.toString()) : ''}`)
}

