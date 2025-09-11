import { request } from './client.js'

export async function getHealth() { return request('/health') }

export async function testModbus(params) { return request('/networking/modbus/test', { method: 'POST', body: params }) }
export async function testOpcUa(params) { return request('/networking/opcua/test', { method: 'POST', body: params }) }
export async function addDbTarget(params) { return request('/storage/targets', { method: 'POST', body: params }) }
export async function testDbTarget(params) { return request('/storage/targets/test', { method: 'POST', body: params }) }
export async function setDefaultTarget(id) { return request('/storage/targets/default', { method: 'POST', body: { id } }) }

// Reachability
export async function listNics() { return request('/networking/nics') }
export async function pingTarget(params) { return request('/networking/ping', { method: 'POST', body: params }) }
export async function tcpTest(params) { return request('/networking/tcp_test', { method: 'POST', body: params }) }

// Storage targets
export async function listTargets() { return request('/storage/targets') }
export async function deleteDbTarget(id) { return request(`/storage/targets/${id}`, { method: 'DELETE' }) }

// Saved devices
export async function listDevices() { return request('/devices') }
export async function createDevice(params) { return request('/devices', { method: 'POST', body: params }) }
export async function connectDevice(id) { return request(`/devices/${id}/connect`, { method: 'POST' }) }
export async function disconnectDevice(id) { return request(`/devices/${id}/disconnect`, { method: 'POST' }) }
export async function quickTestDevice(id) { return request(`/devices/${id}/quick_test`, { method: 'POST' }) }

// Gateways (reachability)
export async function listGateways() { return request('/networking/gateways') }
export async function addGateway(params) { return request('/networking/gateways', { method: 'POST', body: params }) }
export async function deleteGateway(id) { return request(`/networking/gateways/${id}`, { method: 'DELETE' }) }
export async function updateGateway(id, params) { return request(`/networking/gateways/${id}`, { method: 'PUT', body: params }) }
export async function pingGateway(id, params) { return request(`/networking/gateways/${id}/ping`, { method: 'POST', body: params || {} }) }
export async function tcpGateway(id, params) { return request(`/networking/gateways/${id}/tcp`, { method: 'POST', body: params || {} }) }
