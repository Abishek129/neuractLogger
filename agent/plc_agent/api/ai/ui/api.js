/**
 * API client — thin fetch wrappers for all AI endpoints.
 * Base URL derived from window.location.origin (same-origin, no CORS issues).
 * All requests include Keycloak Bearer token from localStorage.
 */
const BASE = window.location.origin;

/** Read the Keycloak access token from localStorage.
 *  Checks both 'kc_token' (AI UI login) and 'agent_token' (desktop app).
 */
function getToken() {
    return localStorage.getItem('kc_token') || localStorage.getItem('agent_token') || '';
}

/** Build headers with auth + content-type. */
function authHeaders() {
    const headers = { 'Content-Type': 'application/json' };
    const token = getToken();
    if (token) {
        headers['Authorization'] = `Bearer ${token}`;
        headers['X-Agent-Token'] = token;
    }
    return headers;
}

/** Handle 401/403 by dispatching an event so the UI can react. */
function handleAuthError(res) {
    if (res.status === 401 || res.status === 403) {
        window.dispatchEvent(new CustomEvent('auth-expired', {
            detail: { status: res.status, url: res.url },
        }));
    }
}

async function _fetchWithRetry(method, path, body) {
    const doFetch = () => {
        const opts = { method, headers: authHeaders() };
        if (body !== undefined) opts.body = JSON.stringify(body);
        return fetch(`${BASE}${path}`, opts);
    };

    let res = await doFetch();

    // Auto-refresh on 401 and retry once
    if (res.status === 401) {
        const refreshed = await refreshToken();
        if (refreshed) {
            res = await doFetch();
        }
    }

    if (!res.ok) {
        if (res.status === 401 || res.status === 403) {
            // Token truly expired and refresh failed — show login
            window.dispatchEvent(new CustomEvent('auth-expired', {
                detail: { status: res.status },
            }));
            throw new Error('Session expired — please log in again.');
        }
        const detail = await res.text();
        throw new Error(`${res.status}: ${detail}`);
    }
    return res;
}

async function json(method, path, body) {
    const res = await _fetchWithRetry(method, path, body);
    return res.json();
}

/** Returns raw Response for NDJSON streaming */
async function stream(method, path, body) {
    return _fetchWithRetry(method, path, body);
}

// --- Auth ---
export async function login(username, password) {
    const res = await fetch(`${BASE}/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
    });
    if (!res.ok) {
        const detail = await res.text();
        throw new Error(`${res.status}: ${detail}`);
    }
    const data = await res.json();
    const accessToken = data.access_token || '';
    localStorage.setItem('kc_token', accessToken);
    localStorage.setItem('agent_token', accessToken);  // compat with desktop frontend
    localStorage.setItem('kc_refresh', data.refresh_token || '');
    localStorage.setItem('kc_expires', String(Date.now() + (data.expires_in || 300) * 1000));
    return data;
}

export function logout() {
    localStorage.removeItem('kc_token');
    localStorage.removeItem('kc_refresh');
    localStorage.removeItem('kc_expires');
}

export function isLoggedIn() {
    const token = getToken();
    if (!token) return false;
    const expires = parseInt(localStorage.getItem('kc_expires') || '0', 10);
    return Date.now() < expires;
}

export async function refreshToken() {
    const refresh = localStorage.getItem('kc_refresh');
    if (!refresh) return false;
    try {
        const res = await fetch(`${BASE}/auth/refresh`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ refresh_token: refresh }),
        });
        if (!res.ok) return false;
        const data = await res.json();
        const accessToken = data.access_token || '';
        localStorage.setItem('kc_token', accessToken);
        localStorage.setItem('agent_token', accessToken);
        localStorage.setItem('kc_refresh', data.refresh_token || '');
        localStorage.setItem('kc_expires', String(Date.now() + (data.expires_in || 300) * 1000));
        return true;
    } catch { return false; }
}

// --- Session endpoints ---
export const createSession = () => json('POST', '/ai/sessions');
export const listSessions = () => json('GET', '/ai/sessions');
export const getSession = (id) => json('GET', `/ai/sessions/${id}`);
export const getHistory = (id) => json('GET', `/ai/sessions/${id}/history`);
export const getTrace = (id) => json('GET', `/ai/sessions/${id}/trace`);

// --- Chat (streaming) ---
export const sendMessage = (id, message) => stream('POST', `/ai/sessions/${id}/chat`, { message });

// --- Plan approval ---
export const approvePlan = (id, message = '') => json('POST', `/ai/sessions/${id}/approve`, { message });
export const discardPlan = (id) => json('POST', `/ai/sessions/${id}/discard`);
export const applyPlan = (id) => stream('POST', `/ai/sessions/${id}/apply`);

// --- KB ---
export const listKB = () => json('GET', '/ai/kb');
export const getKBEntry = (model) => json('GET', `/ai/kb/${model}`);

// --- Skills ---
export const listSkills = () => json('GET', '/ai/skills');
export const getSkill = (id) => json('GET', `/ai/skills/${id}`);
