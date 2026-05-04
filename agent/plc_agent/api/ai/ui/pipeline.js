/**
 * Pipeline panel — tool stage progress bars and error display.
 */

const stagesEl = document.getElementById('stages');
const errorsEl = document.getElementById('pipeline-errors');

/** Map of stage name -> DOM element */
const activeStages = new Map();

function getOrCreateStage(name, internal) {
    if (activeStages.has(name)) return activeStages.get(name);

    const row = document.createElement('div');
    row.className = 'stage-row' + (internal ? ' internal' : '');
    row.innerHTML = `
        <div class="stage-name">
            <span class="name">${name}</span>
            <span class="check"></span>
        </div>
        <div class="progress-bar"><div class="progress-fill"></div></div>
    `;
    stagesEl.appendChild(row);
    stagesEl.scrollTop = stagesEl.scrollHeight;
    activeStages.set(name, row);
    return row;
}

export function onStage(event) {
    const { stage, status, progress, internal, detail } = event;

    // Handle clarify events
    if (stage === 'clarify' && status === 'waiting') {
        onClarify(detail);
        return;
    }

    const row = getOrCreateStage(stage, internal);
    const fill = row.querySelector('.progress-fill');
    const check = row.querySelector('.check');

    if (status === 'started') {
        fill.style.width = '10%';
    } else if (status === 'running') {
        fill.style.width = `${progress || 50}%`;
    } else if (status === 'complete') {
        fill.style.width = '100%';
        check.textContent = ' \u2713';
        row.classList.add('complete');
    }
}

function onClarify(detail) {
    if (!detail) return;
    // Render clarify in the CHAT area, not the pipeline panel
    const messagesEl = document.getElementById('messages');
    const box = document.createElement('div');
    box.className = 'msg msg-assistant clarify-box';

    let html = `<div class="question">${detail.question || 'Agent needs input:'}</div>`;
    if (detail.choices && detail.choices.length) {
        html += '<div class="clarify-choices">';
        for (const choice of detail.choices) {
            html += `<button class="clarify-choice" data-choice="${choice}">${choice}</button>`;
        }
        html += '</div>';
    }
    box.innerHTML = html;

    // Clicking a choice dispatches a custom event for app.js to handle
    box.querySelectorAll('.clarify-choice').forEach(btn => {
        btn.addEventListener('click', () => {
            const evt = new CustomEvent('clarify-response', { detail: btn.dataset.choice });
            document.dispatchEvent(evt);
            // Disable buttons after selection
            box.querySelectorAll('.clarify-choice').forEach(b => b.disabled = true);
            btn.style.opacity = '1';
            btn.style.background = '#22c55e';
        });
    });

    messagesEl.appendChild(box);
    messagesEl.scrollTop = messagesEl.scrollHeight;
}

export function onError(event) {
    const banner = document.createElement('div');
    banner.className = 'error-banner';
    banner.textContent = event.message || 'Pipeline error';
    errorsEl.appendChild(banner);
}

export function clear() {
    stagesEl.innerHTML = '';
    errorsEl.innerHTML = '';
    activeStages.clear();
}
