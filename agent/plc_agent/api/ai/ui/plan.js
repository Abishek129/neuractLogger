/**
 * Plan card — renders proposed plans with approve/discard/apply buttons.
 */
import * as api from './api.js';
import { parseNDJSON } from './ndjson.js';
import * as pipeline from './pipeline.js';
import * as chat from './chat.js';

const planCard = document.getElementById('plan-card');

let currentSessionId = null;
let onStateChange = null; // callback set by app.js
let userCanWrite = false; // true if logged-in user has logger_write role

export function init(sessionId, stateChangeCb, canWrite = false) {
    currentSessionId = sessionId;
    onStateChange = stateChangeCb;
    userCanWrite = canWrite;
}

export function setSessionId(id) {
    currentSessionId = id;
}

export function onPlanProposed(event) {
    const plan = event.plan || {};

    // Build summary items — only show if there are counts
    const items = [
        planItem('Gateways', plan.gateways),
        planItem('Devices', plan.devices),
        planItem('Schemas', plan.schemas),
        planItem('Tables', plan.tables),
        planItem('Mappings', plan.mappings),
        planItem('Jobs', plan.jobs),
    ].filter(Boolean);

    // Store the card element so chat_complete can insert description above buttons
    const messagesEl = document.getElementById('messages');
    const card = document.createElement('div');
    card.className = 'msg msg-assistant plan-card-inline';
    card.id = 'active-plan-card';

    let summaryHtml = '';
    if (items.length > 0) {
        summaryHtml = `<div class="plan-summary">${items.join('')}</div>`;
    }

    card.innerHTML = `
        <div id="plan-description" style="color:#94a3b8;font-size:13px;">Preparing plan details...</div>
        ${summaryHtml}
        <div class="plan-buttons" id="plan-buttons-row" style="display:none;">
            <button class="btn-approve" id="btn-plan-approve" ${userCanWrite ? '' : 'disabled'}>Approve & Execute</button>
            <button class="btn-discard" id="btn-plan-discard">Discard</button>
        </div>
        <div id="plan-status" style="font-size:11px;color:#94a3b8;margin-top:6px;">
            ${userCanWrite ? '' : 'Read-only access — a user with write permission must approve.'}
        </div>
    `;
    messagesEl.appendChild(card);
    messagesEl.scrollTop = messagesEl.scrollHeight;

    planCard.classList.add('hidden');

    document.getElementById('btn-plan-approve').addEventListener('click', handleApproveAndApply);
    document.getElementById('btn-plan-discard').addEventListener('click', handleDiscard);
}

function planItem(label, count) {
    if (!count) return '';
    return `<div class="plan-item"><span>${label}</span><span class="count">${count}</span></div>`;
}

export function onApprovalRequired(_event) {
    // plan_proposed already rendered the buttons; this event confirms it
}

async function handleApproveAndApply() {
    const statusEl = document.getElementById('plan-status');
    const approveBtn = document.getElementById('btn-plan-approve');
    const discardBtn = document.getElementById('btn-plan-discard');

    try {
        // Step 1: Approve
        statusEl.textContent = 'Approving...';
        if (approveBtn) approveBtn.disabled = true;
        if (discardBtn) discardBtn.disabled = true;

        const res = await api.approvePlan(currentSessionId);
        if (onStateChange) onStateChange(res.state);
        chat.renderSystemMessage('Plan approved. Executing...');

        // Step 2: Apply immediately
        statusEl.textContent = 'Executing plan...';
        pipeline.clear();

        const response = await api.applyPlan(currentSessionId);
        for await (const event of parseNDJSON(response)) {
            if (event.event === 'stage') pipeline.onStage(event);
            else if (event.event === 'chat_complete') {
                statusEl.textContent = 'Done.';
                if (event.message) {
                    chat.renderAssistantMessage(event.message);
                }
                if (onStateChange) onStateChange(event.session_state);
            } else if (event.event === 'error') {
                statusEl.textContent = `Error: ${event.message}`;
                chat.renderSystemMessage(`Error: ${event.message}`);
                pipeline.onError(event);
            }
        }
    } catch (e) {
        statusEl.textContent = `Error: ${e.message}`;
        chat.renderSystemMessage(`Execution failed: ${e.message}`);
        if (approveBtn) approveBtn.disabled = false;
        if (discardBtn) discardBtn.disabled = false;
    }
}

async function handleDiscard() {
    const statusEl = document.getElementById('plan-status');
    const approveBtn = document.getElementById('btn-plan-approve');
    const discardBtn = document.getElementById('btn-plan-discard');

    try {
        if (approveBtn) approveBtn.disabled = true;
        if (discardBtn) discardBtn.disabled = true;
        statusEl.textContent = 'Discarding...';

        const res = await api.discardPlan(currentSessionId);
        statusEl.textContent = 'Discarded.';
        chat.renderSystemMessage('Plan discarded. You can ask for a different approach.');
        if (onStateChange) onStateChange(res.state);
    } catch (e) {
        statusEl.textContent = `Error: ${e.message}`;
        chat.renderSystemMessage(`Discard failed: ${e.message}`);
        if (approveBtn) approveBtn.disabled = false;
        if (discardBtn) discardBtn.disabled = false;
    }
}

export function hide() {
    planCard.classList.add('hidden');
}
