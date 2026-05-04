/**
 * Main entry — wires everything together.
 */
import * as api from './api.js';
import { parseNDJSON } from './ndjson.js';
import * as chat from './chat.js';
import * as pipeline from './pipeline.js';
import * as plan from './plan.js';
import * as sidebar from './sidebar.js';

// --- State ---
let currentSessionId = null;
let isStreaming = false;
let canWrite = false;  // true if logged-in user has logger_write role

// --- DOM refs ---
const sessionIdBadge = document.getElementById('session-id-badge');
const stateBadge = document.getElementById('state-badge');
const chatInput = document.getElementById('chat-input');
const btnSend = document.getElementById('btn-send');
const btnNewSession = document.getElementById('btn-new-session');

// --- Init ---
function init() {
    sidebar.init(handleSessionSelect);

    btnNewSession.addEventListener('click', createNewSession);
    btnSend.addEventListener('click', handleSend);
    chatInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            handleSend();
        }
    });

    // Clarify response handler
    document.addEventListener('clarify-response', (e) => {
        if (currentSessionId && e.detail) {
            sendMessage(e.detail);
        }
    });

    // Ensure input is enabled on boot
    chatInput.disabled = false;
    btnSend.disabled = false;
    chatInput.focus();

    // Try to restore last session
    const lastId = localStorage.getItem('lf_last_session');
    if (lastId) {
        loadSession(lastId);
    }
    sidebar.loadSessions(currentSessionId);
}

// --- Session management ---
async function createNewSession() {
    try {
        const res = await api.createSession();
        currentSessionId = res.session_id;
        canWrite = !!res.can_write;
        localStorage.setItem('lf_last_session', currentSessionId);
        updateSessionUI(res.session_id, res.state, res.user);
        plan.init(currentSessionId, updateState, canWrite);
        plan.hide();
        pipeline.clear();
        document.getElementById('messages').innerHTML = '';
        chat.renderSystemMessage(`Session created: ${res.session_id}`);
        sidebar.loadSessions(currentSessionId);
    } catch (e) {
        chat.renderSystemMessage(`Failed to create session: ${e.message}`);
    }
}

async function loadSession(sessionId) {
    try {
        const res = await api.getSession(sessionId);
        currentSessionId = res.session_id;
        canWrite = !!res.can_write;
        localStorage.setItem('lf_last_session', currentSessionId);
        updateSessionUI(res.session_id, res.state, res.user);
        plan.init(currentSessionId, updateState, canWrite);
        plan.hide();
        pipeline.clear();
        document.getElementById('messages').innerHTML = '';
        chat.renderSystemMessage(`Loaded session: ${res.session_id} (${res.state}, ${res.turn_count} turns)`);

        // Load and render chat history
        try {
            const history = await api.getHistory(sessionId);
            if (history.messages && history.messages.length > 0) {
                for (const msg of history.messages) {
                    if (msg.role === 'user') {
                        chat.renderUserMessage(msg.content);
                    } else if (msg.role === 'assistant' && msg.content) {
                        chat.renderAssistantMessage(msg.content);
                    }
                }
            }
        } catch (_histErr) {
            // History endpoint may not exist on older servers — ignore
        }

        sidebar.loadSessions(currentSessionId);
    } catch (e) {
        // Session doesn't exist anymore, create new
        createNewSession();
    }
}

function handleSessionSelect(sessionId) {
    if (sessionId !== currentSessionId && !isStreaming) {
        loadSession(sessionId);
    }
}

function updateSessionUI(id, state, user) {
    sessionIdBadge.textContent = user ? `${id} (${user})` : id;
    updateState(state);
}

function updateState(state) {
    stateBadge.dataset.state = state;
    const disabled = state === 'applying' || state === 'approved';
    chatInput.disabled = disabled;
    btnSend.disabled = disabled || isStreaming;
    if (!disabled) chatInput.focus();
}

// --- Chat ---
async function handleSend() {
    const message = chatInput.value.trim();
    if (!message || isStreaming) return;
    // Auto-create session if none exists
    if (!currentSessionId) {
        await createNewSession();
        if (!currentSessionId) return; // creation failed
    }
    sendMessage(message);
}

async function sendMessage(message) {
    chatInput.value = '';
    chatInput.focus();
    chat.renderUserMessage(message);
    pipeline.clear();
    plan.hide();

    isStreaming = true;
    btnSend.disabled = true;

    try {
        const response = await api.sendMessage(currentSessionId, message);

        for await (const event of parseNDJSON(response)) {
            switch (event.event) {
                case 'chat_start':
                    chat.onChatStart(event);
                    break;
                case 'stage':
                    pipeline.onStage(event);
                    break;
                case 'plan_proposed':
                    plan.onPlanProposed(event);
                    break;
                case 'approval_required':
                    plan.onApprovalRequired(event);
                    break;
                case 'chat_complete':
                    chat.onChatComplete(event);
                    if (event.session_state) updateState(event.session_state);
                    break;
                case 'error':
                    chat.onError(event);
                    pipeline.onError(event);
                    break;
            }
        }
    } catch (e) {
        chat.onError({ message: e.message });
    } finally {
        isStreaming = false;
        btnSend.disabled = false;
        // Refresh sidebar and trace
        sidebar.loadSessions(currentSessionId);
        sidebar.loadTrace(currentSessionId);
    }
}

// --- WebSocket Notifications ---
function connectNotificationWS() {
    const wsProto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${wsProto}//${location.host}/ws/logs`;
    let ws;
    function connect() {
        ws = new WebSocket(wsUrl);
        ws.onmessage = (e) => {
            try {
                const notif = JSON.parse(e.data);
                if (notif.type === 'prediction') {
                    showNotification(notif.message, 'prediction');
                } else {
                    showNotification(notif.message, notif.type || 'info');
                }
            } catch (_) {}
        };
        ws.onclose = () => setTimeout(connect, 5000); // reconnect
        ws.onerror = () => ws.close();
    }
    connect();
}

function showNotification(message, type) {
    const container = document.getElementById('notifications');
    const div = document.createElement('div');
    div.className = `notif notif-${type}`;
    div.textContent = message;
    container.prepend(div);
    // Auto-remove after 30s
    setTimeout(() => div.remove(), 30000);
    // Keep max 20
    while (container.children.length > 20) container.lastChild.remove();
}

// --- Auth expiry handler ---
window.addEventListener('auth-expired', (e) => {
    const detail = e.detail || {};
    if (detail.status === 403) {
        chat.renderSystemMessage('You don\'t have write permissions for this action. Ask an admin to assign the logger-write role.');
    } else {
        // Token expired — show login with friendly message
        api.logout();
        chat.renderSystemMessage('Your session has expired. Please log in again to continue.');
        showLoginOverlay();
        document.getElementById('login-error').textContent = 'Session expired — please sign in again.';
    }
});

// --- Login UI ---
const loginOverlay = document.getElementById('login-overlay');
const loginForm = document.getElementById('login-form');
const loginError = document.getElementById('login-error');

function showLoginOverlay() {
    loginOverlay.classList.remove('hidden');
    chatInput.disabled = true;
    btnSend.disabled = true;
    document.getElementById('login-user').focus();
}

function hideLoginOverlay() {
    loginOverlay.classList.add('hidden');
    chatInput.disabled = false;
    btnSend.disabled = false;
    chatInput.focus();
}

loginForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const user = document.getElementById('login-user').value.trim();
    const pass = document.getElementById('login-pass').value;
    const btn = document.getElementById('login-btn');
    loginError.textContent = '';
    btn.disabled = true;
    btn.textContent = 'Signing in...';
    try {
        await api.login(user, pass);
        hideLoginOverlay();
        // Reload sessions now that we have a token
        sidebar.loadSessions(currentSessionId);
        if (!currentSessionId) {
            const lastId = localStorage.getItem('lf_last_session');
            if (lastId) loadSession(lastId);
        }
    } catch (err) {
        loginError.textContent = 'Login failed — check username and password.';
    } finally {
        btn.disabled = false;
        btn.textContent = 'Sign In';
    }
});

// --- Boot ---
if (api.isLoggedIn()) {
    hideLoginOverlay();
    init();
} else {
    showLoginOverlay();
    // Still init sidebar/handlers but sessions will fail until login
    init();
}
connectNotificationWS();
