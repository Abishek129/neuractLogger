/**
 * Sidebar — session list, KB browser, skills viewer, trace viewer.
 */
import * as api from './api.js';

const sessionListEl = document.getElementById('session-list');
const kbListEl = document.getElementById('kb-list');
const skillsListEl = document.getElementById('skills-list');
const traceContentEl = document.getElementById('trace-content');

let onSessionSelect = null; // callback set by app.js

export function init(sessionSelectCb) {
    onSessionSelect = sessionSelectCb;

    // Accordion toggles
    document.querySelectorAll('.accordion-toggle').forEach(toggle => {
        toggle.addEventListener('click', () => {
            const target = document.getElementById(toggle.dataset.target);
            const isOpen = target.classList.contains('open');
            // Close all
            document.querySelectorAll('.accordion-body').forEach(b => b.classList.remove('open'));
            document.querySelectorAll('.accordion-toggle').forEach(t => t.classList.remove('active'));
            // Toggle this one
            if (!isOpen) {
                target.classList.add('open');
                toggle.classList.add('active');
                // Lazy load content
                if (toggle.dataset.target === 'kb-panel') loadKB();
                if (toggle.dataset.target === 'skills-panel') loadSkills();
            }
        });
    });
}

// --- Sessions ---
export async function loadSessions(activeSessionId) {
    try {
        const data = await api.listSessions();
        sessionListEl.innerHTML = '';
        for (const s of data.sessions) {
            const div = document.createElement('div');
            div.className = 'session-item' + (s.session_id === activeSessionId ? ' active' : '');
            div.innerHTML = `
                <span>${s.session_id.slice(0, 8)}... (${s.turn_count}t)</span>
                <span class="state-tag">${s.state}</span>
            `;
            div.addEventListener('click', () => {
                if (onSessionSelect) onSessionSelect(s.session_id);
            });
            sessionListEl.appendChild(div);
        }
    } catch (e) {
        sessionListEl.innerHTML = `<div style="color:#6b7280;font-size:12px;">Failed to load sessions</div>`;
    }
}

// --- KB ---
async function loadKB() {
    try {
        const data = await api.listKB();
        kbListEl.innerHTML = '';
        const models = data.models || [];
        if (!models.length) {
            kbListEl.innerHTML = '<div style="color:#6b7280;font-size:12px;">No KB entries</div>';
            return;
        }
        for (const m of models) {
            const div = document.createElement('div');
            div.className = 'kb-item';
            div.textContent = `${m.model} (${m.manufacturer}, ${m.register_count} regs)`;
            div.addEventListener('click', () => toggleKBDetail(m.model, div));
            kbListEl.appendChild(div);
        }
    } catch (e) {
        kbListEl.innerHTML = `<div style="color:#6b7280;font-size:12px;">Failed to load KB</div>`;
    }
}

async function toggleKBDetail(model, parentDiv) {
    const existing = parentDiv.nextElementSibling;
    if (existing && existing.classList.contains('kb-detail')) {
        existing.remove();
        return;
    }
    try {
        const data = await api.getKBEntry(model);
        const entry = data.entry || data;
        const detail = document.createElement('div');
        detail.className = 'kb-detail';
        const regs = (entry.registers || []).slice(0, 20);
        let text = `Model: ${entry.model}\nManufacturer: ${entry.manufacturer}\nProtocol: ${entry.protocol}\nByte Order: ${entry.byte_order}\n\nRegisters (first 20):\n`;
        for (const r of regs) {
            text += `  ${r.address}: ${r.parameter} (${r.data_type}, ${r.unit})\n`;
        }
        if ((entry.registers || []).length > 20) {
            text += `  ... and ${entry.registers.length - 20} more`;
        }
        detail.textContent = text;
        parentDiv.after(detail);
    } catch (e) {
        // ignore
    }
}

// --- Skills ---
async function loadSkills() {
    try {
        const data = await api.listSkills();
        skillsListEl.innerHTML = '';
        const skills = data.skills || [];
        if (!skills.length) {
            skillsListEl.innerHTML = '<div style="color:#6b7280;font-size:12px;">No skills learned</div>';
            return;
        }
        for (const s of skills) {
            const div = document.createElement('div');
            div.className = 'skill-item';
            div.textContent = s.name || s.id;
            div.addEventListener('click', () => toggleSkillDetail(s.id, div));
            skillsListEl.appendChild(div);
        }
    } catch (e) {
        skillsListEl.innerHTML = `<div style="color:#6b7280;font-size:12px;">Failed to load skills</div>`;
    }
}

async function toggleSkillDetail(id, parentDiv) {
    const existing = parentDiv.nextElementSibling;
    if (existing && existing.classList.contains('skill-detail')) {
        existing.remove();
        return;
    }
    try {
        const data = await api.getSkill(id);
        const detail = document.createElement('div');
        detail.className = 'skill-detail';
        detail.textContent = data.content || data.content_preview || 'No content';
        parentDiv.after(detail);
    } catch (e) {
        // ignore
    }
}

// --- Trace ---
export async function loadTrace(sessionId) {
    if (!sessionId) {
        traceContentEl.innerHTML = '<div style="color:#6b7280;font-size:12px;">No active session</div>';
        return;
    }
    try {
        const data = await api.getTrace(sessionId);
        traceContentEl.innerHTML = '';
        const events = data.tool_events || [];
        if (!events.length) {
            traceContentEl.innerHTML = '<div style="color:#6b7280;font-size:12px;">No tool events yet</div>';
            return;
        }
        for (const ev of events) {
            const div = document.createElement('div');
            div.className = 'trace-event';
            div.dataset.tier = ev.tier || '';
            div.innerHTML = `<b>${ev.tool_name}</b> ${ev.duration_ms}ms${ev.error_type ? ` <span style="color:#fca5a5;">${ev.error_type}</span>` : ''}`;
            traceContentEl.appendChild(div);
        }
        // Learning signal
        if (data.learning_signal) {
            const sig = document.createElement('div');
            sig.className = 'trace-event';
            sig.style.borderLeftColor = '#e94560';
            sig.innerHTML = `<b>Learning Signal</b> clean_run=${data.learning_signal.clean_run}`;
            traceContentEl.appendChild(sig);
        }
    } catch (e) {
        traceContentEl.innerHTML = `<div style="color:#6b7280;font-size:12px;">Failed to load trace</div>`;
    }
}
