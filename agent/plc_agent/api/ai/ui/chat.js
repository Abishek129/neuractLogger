/**
 * Chat panel — message rendering with proper markdown via marked.js + DOMPurify.
 */

const messagesEl = document.getElementById('messages');
let typingEl = null;

function renderMarkdown(text) {
    if (typeof marked !== 'undefined') {
        const raw = marked.parse(text, { breaks: true, gfm: true });
        if (typeof DOMPurify !== 'undefined') {
            return DOMPurify.sanitize(raw);
        }
        return raw;
    }
    // Fallback: escape and preserve newlines
    return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
               .replace(/\n/g, '<br>');
}

function addMessage(cls, html) {
    const div = document.createElement('div');
    div.className = `msg ${cls}`;
    div.innerHTML = html;
    messagesEl.appendChild(div);
    messagesEl.scrollTop = messagesEl.scrollHeight;
    return div;
}

export function renderUserMessage(text) {
    addMessage('msg-user', text.replace(/</g, '&lt;').replace(/>/g, '&gt;'));
}

export function renderAssistantMessage(text) {
    addMessage('msg-assistant', renderMarkdown(text));
}

export function renderSystemMessage(text) {
    addMessage('msg-system', text);
}

export function startStreaming() {
    if (typingEl) return;
    typingEl = document.createElement('div');
    typingEl.className = 'typing-indicator';
    typingEl.textContent = 'Thinking...';
    messagesEl.appendChild(typingEl);
    messagesEl.scrollTop = messagesEl.scrollHeight;
}

export function stopStreaming() {
    if (typingEl) { typingEl.remove(); typingEl = null; }
}

export function onChatStart(_event) { startStreaming(); }

export function onChatComplete(event) {
    stopStreaming();
    if (!event.message) return;

    // If there's an active plan card waiting for description, fill it in and show buttons
    const planDesc = document.getElementById('plan-description');
    const planButtons = document.getElementById('plan-buttons-row');
    if (planDesc && planDesc.textContent === 'Preparing plan details...') {
        planDesc.innerHTML = renderMarkdown(event.message);
        planDesc.style.color = '';
        planDesc.style.fontSize = '';
        if (planButtons) planButtons.style.display = '';
        messagesEl.scrollTop = messagesEl.scrollHeight;
    } else {
        renderAssistantMessage(event.message);
    }
}

export function onError(event) {
    stopStreaming();
    renderSystemMessage(`Error: ${event.message || 'Unknown error'}`);
}
