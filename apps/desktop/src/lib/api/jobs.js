import { request } from './client.js'

export const listJobs = () => request('/jobs')
export const createJob = (payload) => request('/jobs', { method: 'POST', body: payload })
export const startJob = (id) => request(`/jobs/${id}/start`, { method: 'POST' })
export const stopJob = (id) => request(`/jobs/${id}/stop`, { method: 'POST' })
export const pauseJob = (id) => request(`/jobs/${id}/pause`, { method: 'POST' })
export const dryRunJob = (id) => request(`/jobs/${id}/dry_run`, { method: 'POST' })
export const backfillJob = (id) => request(`/jobs/${id}/backfill`, { method: 'POST' })
export const deleteJob = (id) => request(`/jobs/${id}`, { method: 'DELETE' })
