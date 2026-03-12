// ======================================================
// SESSION ISOLATION — Multi-user support
// ======================================================
// Generate a unique session ID per browser tab and persist it in sessionStorage.
// This is sent as 'X-Session-ID' on every API call so the server can route
// each user to their own isolated Orchestrator instance.
const SESSION_ID = (() => {
    const key = 'aiv_session_id';
    const existing = sessionStorage.getItem(key);
    if (existing) return existing;
    const id = (typeof crypto !== 'undefined' && crypto.randomUUID)
        ? crypto.randomUUID()
        : 'sess-' + Math.random().toString(36).slice(2) + Date.now().toString(36);
    sessionStorage.setItem(key, id);
    return id;
})();

// Intercept ALL local fetch() calls and silently add the session header.
// This means no individual fetch call needs to be changed.
(function patchFetch() {
    const _orig = window.fetch.bind(window);
    window.fetch = function (url, options = {}) {
        // Only patch same-origin (relative) URLs
        if (typeof url === 'string' && (url.startsWith('/') || url.startsWith(window.location.origin))) {
            options = {
                ...options,
                headers: {
                    ...(options.headers || {}),
                    'X-Session-ID': SESSION_ID
                }
            };
        }
        return _orig(url, options);
    };
})();

let currentAbortController = null;
let attachedFiles = [];
let chatHistory = [];
let messagePairs = []; // Tracks {userBubble, assistantBubble, prompt} for editing
let editingMessageIndex = null; // Index of message currently being edited inline (null = none)
let cellCount = 0;
let lastDataForChart = null;
let pyodide = null; // Global Pyodide instance
let showCode = true; // Global toggle: set to false to hide code blocks in AI responses
let pendingCodeProposal = null; // Pending AI code action for the active code cell
let lastActiveCellId = null; // Tracks the last cell that was run or focused
let currentConfigs = {}; // Global store for loaded database configs

// =======================
// LOADING SCREEN MANAGEMENT
// =======================
function hideLoadingScreen() {
    const loadingScreen = document.getElementById('loading-screen');
    if (loadingScreen) {
        loadingScreen.classList.add('hidden');
    }
}

// =======================
// CUSTOM DIALOG SYSTEM
// =======================
let dialogConfig = {
    resolve: null,
    type: 'confirm', // 'alert', 'confirm', 'prompt'
    validator: null  // async function(val) -> error string or null
};

function showCustomDialog(title, message, options = {}) {
    const overlay = document.getElementById('custom-dialog-overlay');
    const titleEl = document.getElementById('custom-dialog-title');
    const messageEl = document.getElementById('custom-dialog-message');
    const inputEl = document.getElementById('custom-dialog-input');
    const cancelBtn = document.getElementById('custom-dialog-cancel');
    const confirmBtn = document.getElementById('custom-dialog-confirm');

    titleEl.textContent = title;
    messageEl.textContent = message;

    // Reset dialog state
    inputEl.style.display = 'none';
    inputEl.value = '';
    inputEl.style.border = ''; // reset border
    // Clear old errors
    const oldErr = document.getElementById('custom-dialog-error');
    if (oldErr) oldErr.remove();
    cancelBtn.style.display = 'inline-block';
    confirmBtn.classList.remove('danger');
    confirmBtn.textContent = 'Confirm';
    cancelBtn.dataset.context = 'primary'; // default: blue hover border
    cancelBtn.textContent = options.cancelText || 'Cancel'; // support custom label

    // Configure based on type
    const type = options.type || 'alert';
    dialogConfig.type = type;
    dialogConfig.validator = options.validator || null;

    if (type === 'alert') {
        cancelBtn.style.display = 'none';
        confirmBtn.textContent = 'OK';
        setTimeout(() => confirmBtn.focus(), 60);
    } else if (type === 'confirm') {
        cancelBtn.style.display = 'inline-block';
        // If this is a destructive confirm, use "Delete" as the default action label
        confirmBtn.textContent = options.confirmText || (options.isDangerous ? 'Delete' : 'Confirm');
        if (options.isDangerous) {
            confirmBtn.classList.add('danger');
            cancelBtn.dataset.context = 'danger'; // red hover border
        } else {
            confirmBtn.classList.remove('danger');
            cancelBtn.dataset.context = 'primary'; // blue hover border
        }
        setTimeout(() => confirmBtn.focus(), 60);
    } else if (type === 'prompt') {
        cancelBtn.style.display = 'inline-block';
        inputEl.style.display = 'block';
        inputEl.placeholder = options.placeholder || '';
        inputEl.value = options.defaultValue || '';
        confirmBtn.textContent = 'OK';

        // Add keyboard support for prompt input
        inputEl.onkeydown = (e) => {
            if (e.key === 'Enter') {
                confirmCustomDialog();
            } else if (e.key === 'Escape') {
                cancelCustomDialog();
            }
        };

        setTimeout(() => inputEl.focus(), 100);
    }

    overlay.style.display = 'flex';

    return new Promise((resolve) => {
        dialogConfig.resolve = resolve;
    });
}

function closeCustomDialog() {
    const overlay = document.getElementById('custom-dialog-overlay');
    overlay.style.display = 'none';
    if (dialogConfig.resolve) {
        dialogConfig.resolve(null);
        dialogConfig.resolve = null;
    }
}

// ── Updated Confirm Logic with Async Validator Support ───────────────────────
async function confirmCustomDialog() {
    const overlay = document.getElementById('custom-dialog-overlay');
    const inputEl = document.getElementById('custom-dialog-input');
    const confirmBtn = document.getElementById('custom-dialog-confirm');
    const content = document.querySelector('.custom-dialog-content');

    // Clear previous errors
    const existingErr = document.getElementById('custom-dialog-error');
    if (existingErr) existingErr.remove();
    inputEl.style.border = '';

    let result = true;
    if (dialogConfig.type === 'prompt') {
        result = inputEl.value.trim();

        // ── Validation Logic ──────────────────────────────────────────
        if (dialogConfig.validator) {
            // Disable button during check
            confirmBtn.disabled = true;
            confirmBtn.style.opacity = '0.7';
            try {
                const error = await dialogConfig.validator(result);
                if (error) {
                    // Show error and STOP
                    const errDiv = document.createElement('div');
                    errDiv.id = 'custom-dialog-error';
                    errDiv.style.cssText = 'color:#ef4444; font-size:0.85rem; margin-top:8px; display:flex; align-items:center;';
                    // Add icon
                    errDiv.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="margin-right:6px;"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg> ${error}`;

                    content.appendChild(errDiv);
                    inputEl.style.border = '1px solid #ef4444';
                    inputEl.focus();
                    return; // Keep dialog open
                }
            } catch (e) {
                console.error(e);
                confirmCustomDialog(); // close on system error? or show error?
                return;
            } finally {
                confirmBtn.disabled = false;
                confirmBtn.style.opacity = '1';
            }
        }
    }

    overlay.style.display = 'none';
    if (dialogConfig.resolve) {
        dialogConfig.resolve(result);
        dialogConfig.resolve = null;
    }
}

function cancelCustomDialog() {
    const overlay = document.getElementById('custom-dialog-overlay');
    overlay.style.display = 'none';
    if (dialogConfig.resolve) {
        dialogConfig.resolve(false);
        dialogConfig.resolve = null;
    }
}

// Convenience functions matching browser dialog API
async function customAlert(message) {
    await showCustomDialog('Alert', message, { type: 'alert' });
}

async function customConfirm(message, isDangerous = false) {
    return await showCustomDialog('Confirm', message, { type: 'confirm', isDangerous });
}

async function customPrompt(message, defaultValue = '', options = {}) {
    return await showCustomDialog('Input Required', message, { type: 'prompt', defaultValue, ...options });
}

// ======================================================
// TOAST NOTIFICATION SYSTEM
// ======================================================
let activeRagIndexToast = null;
const inflightTableActions = new Set();
const inflightMemoryActions = new Set();

function dismissToast(toast) {
    if (!toast || !toast.parentElement) return;
    if (toast._dismissTimer) clearTimeout(toast._dismissTimer);
    toast.style.opacity = '0';
    toast.style.transform = 'translateX(40px)';
    setTimeout(() => toast.remove(), 300);
}

function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

async function fetchTablesAndMemoryState() {
    const [tablesResp, memoryResp] = await Promise.all([
        fetch('/api/tables'),
        fetch('/api/vector_memory')
    ]);
    const tablesData = await tablesResp.json();
    const memoryData = await memoryResp.json();
    return {
        tables: Array.isArray(tablesData.tables) ? tablesData.tables : [],
        sources: Array.isArray(memoryData.sources) ? memoryData.sources : []
    };
}

async function pollUntilActionComplete(checkDone, { intervalMs = 2500 } = {}) {
    while (true) {
        const state = await fetchTablesAndMemoryState();
        await Promise.all([loadTables({ preserve: true }), loadVectorMemory({ preserve: true })]);
        if (checkDone(state)) return state;
        await sleep(intervalMs);
    }
}

function showToast(message, type = 'info', duration = 4000) {
    // Create container if it doesn't exist
    let container = document.getElementById('toast-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'toast-container';
        container.style.cssText = [
            'position:fixed', 'top:84px', 'right:24px', 'z-index:99999',
            'display:flex', 'flex-direction:column', 'gap:10px',
            'pointer-events:none'
        ].join(';');
        document.body.appendChild(container);
    }

    const tones = {
        success: { accent: '#059669', border: '#d1fae5' },
        error: { accent: '#dc2626', border: '#fee2e2' },
        warning: { accent: '#d97706', border: '#fef3c7' },
        info: { accent: '#2563eb', border: '#dbeafe' },
    };
    const { accent, border } = tones[type] || tones.info;

    const toast = document.createElement('div');
    toast.style.cssText = [
        'background:#ffffff', 'color:#0f172a',
        'padding:11px 14px', 'border-radius:12px',
        'font-size:0.84rem', 'font-weight:500', 'line-height:1.4',
        'display:flex', 'align-items:center', 'gap:10px',
        'box-shadow:0 14px 36px rgba(15,23,42,0.12)',
        `border:1px solid ${border}`, `border-left:3px solid ${accent}`,
        'pointer-events:auto', 'min-width:260px', 'max-width:360px',
        'opacity:0', 'transform:translateX(40px)',
        'transition:opacity 0.24s ease, transform 0.24s ease'
    ].join(';');

    const dot = document.createElement('span');
    dot.style.cssText = [
        `background:${accent}`,
        'width:8px', 'height:8px', 'border-radius:50%', 'flex-shrink:0'
    ].join(';');

    const text = document.createElement('span');
    text.textContent = message;

    toast.appendChild(dot);
    toast.appendChild(text);
    container.appendChild(toast);

    // Slide in
    requestAnimationFrame(() => {
        toast.style.opacity = '1';
        toast.style.transform = 'translateX(0)';
    });

    // Auto dismiss
    if (duration > 0) {
        toast._dismissTimer = setTimeout(() => dismissToast(toast), duration);
    }

    return toast;
}

// Generate a default notebook name with timestamp
function generateNotebookName() {
    const now = new Date();
    const date = now.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
    const time = now.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: true });
    return `Notebook ${date} ${time}`;
}

// ======================================================
// NOTEBOOK TITLE (Navbar Center)
// ======================================================
const NAVBAR_TITLE_MAX_CHARS = 25;

function setNotebookTitle(name) {
    const wrapEl = document.getElementById('navbar-nb-scroll-wrap');
    const titleEl = document.getElementById('navbar-notebook-title');
    if (!wrapEl || !titleEl) return;

    const displayName = name || 'Untitled Notebook';

    // Reset animation and children
    wrapEl.classList.remove('marquee-active');
    wrapEl.style.removeProperty('animation-duration');
    wrapEl.innerHTML = '';

    // Build first text span
    const span1 = document.createElement('span');
    span1.id = 'navbar-nb-text';
    span1.className = 'navbar-nb-text';
    span1.textContent = displayName;
    wrapEl.appendChild(span1);

    if (displayName.length > NAVBAR_TITLE_MAX_CHARS) {
        // Wait one frame so the browser can measure real widths
        requestAnimationFrame(() => {
            const containerWidth = titleEl.offsetWidth;
            const textWidth = span1.scrollWidth;

            if (textWidth > containerWidth) {
                const GAP_PX = 56;
                span1.style.paddingRight = GAP_PX + 'px';

                // Re-measure after padding is applied
                requestAnimationFrame(() => {
                    const unitWidth = span1.scrollWidth; // text + gap

                    const span2 = document.createElement('span');
                    span2.className = 'navbar-nb-text';
                    span2.textContent = displayName;
                    span2.style.paddingRight = GAP_PX + 'px';
                    wrapEl.appendChild(span2);

                    // ── Pause-at-start logic ──────────────────────────────
                    // Scroll at 36 px/s, then hold for 1.5 s before repeating
                    const PAUSE_SECS = 1.5;
                    const scrollSecs = Math.max(8, unitWidth / 36);
                    const totalSecs = scrollSecs + PAUSE_SECS;
                    const pausePct = ((PAUSE_SECS / totalSecs) * 100).toFixed(3);

                    // Inject / update a dedicated <style> with exact keyframe percentages
                    let kfStyle = document.getElementById('nb-marquee-kf');
                    if (!kfStyle) {
                        kfStyle = document.createElement('style');
                        kfStyle.id = 'nb-marquee-kf';
                        document.head.appendChild(kfStyle);
                    }
                    kfStyle.textContent = `@keyframes nb-marquee {
  0%, ${pausePct}% { transform: translateX(0); }
  100%             { transform: translateX(-50%); }
}`;

                    wrapEl.style.animationDuration = `${totalSecs}s`;
                    wrapEl.classList.add('marquee-active');
                });
            }
        });
    }
}

// Multi-Chat System
let currentChatId = null;
let chats = [];
let currentNotebookId = 'notebook_' + Date.now();
// Transient state when viewing a history item (do NOT attach to current notebook)
let viewingHistoryItem = null; // raw history item object when viewing from History
let viewingHistoryOriginalNotebook = null; // display_name of original notebook if discovered

// Per-drawer selection state (persists across open/close)
let selectedSavedNotebook = null;  // display_name string
let selectedHistoryId = null;  // numeric id

// Dirty-state tracking
let isDirty = false;  // true when unsaved changes exist
let isNotebookSaved = false;  // true once the notebook has been saved at least once
let currentNotebookName = null; // display name of the active notebook (null if never saved)

function persistActiveNotebookId() {
    try {
        localStorage.setItem('active_notebook_id', currentNotebookId);
    } catch (e) {
        console.warn('Failed to persist active notebook id:', e);
    }
}

// Mark the current notebook as having unsaved changes
function markDirty() {
    isDirty = true;
}

// Delegated listener: catch input events on contenteditable text cells
// (code cells are covered by the CodeMirror change hook in initCodeMirror)
document.addEventListener('DOMContentLoaded', () => {
    const workspace = document.getElementById('workspace-view');
    if (workspace) {
        workspace.addEventListener('input', (e) => {
            if (e.target.classList.contains('text-editor')) {
                markDirty();
            }
        });
    }
});

// =======================
// ICON SVG CONSTANTS
// =======================

const ICON_MAXIMIZE = `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-maximize"><path d="M8 3H5a2 2 0 0 0-2 2v3"/><path d="M21 8V5a2 2 0 0 0-2-2h-3"/><path d="M3 16v3a2 2 0 0 0 2 2h3"/><path d="M16 21h3a2 2 0 0 0 2-2v-3"/></svg>`;

const ICON_MINIMIZE = `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-minimize"><path d="M8 3v3a2 2 0 0 1-2 2H3"/><path d="M21 8h-3a2 2 0 0 1-2-2V3"/><path d="M3 16h3a2 2 0 0 1 2 2v3"/><path d="M16 21v-3a2 2 0 0 1 2-2h3"/></svg>`;

const ICON_BOLD = `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 12h9a4 4 0 0 1 0 8H7a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1h7a4 4 0 0 1 0 8"/></svg>`;

const ICON_ITALIC = `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="19" x2="10" y1="4" y2="4"/><line x1="14" x2="5" y1="20" y2="20"/><line x1="15" x2="9" y1="4" y2="20"/></svg>`;

const ICON_HEADING = `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 12h12"/><path d="M6 20V4"/><path d="M18 20V4"/></svg>`;

const ICON_QUOTE = `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M16 3a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2 1 1 0 0 1 1 1v1a2 2 0 0 1-2 2 1 1 0 0 0-1 1v2a1 1 0 0 0 1 1 6 6 0 0 0 6-6V5a2 2 0 0 0-2-2z"/><path d="M5 3a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2 1 1 0 0 1 1 1v1a2 2 0 0 1-2 2 1 1 0 0 0-1 1v2a1 1 0 0 0 1 1 6 6 0 0 0 6-6V5a2 2 0 0 0-2-2z"/></svg>`;

const ICON_LINK = `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>`;

const ICON_IMAGE = `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M16 5h6"/><path d="M19 2v6"/><path d="M21 11.5V19a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h7.5"/><path d="m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21"/><circle cx="9" cy="9" r="2"/></svg>`;

const ICON_LIST = `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 5h.01"/><path d="M3 12h.01"/><path d="M3 19h.01"/><path d="M8 5h13"/><path d="M8 12h13"/><path d="M8 19h13"/></svg>`;

const ICON_LIST_ORDERED = `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 5h10"/><path d="M11 12h10"/><path d="M11 19h10"/><path d="M4 4h1v5"/><path d="M4 9h2"/><path d="M6.5 20H3.4c0-1 2.6-1.925 2.6-3.5a1.5 1.5 0 0 0-2.6-1.02"/></svg>`;

const ICON_TABLE = `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v18"/><rect width="18" height="18" x="3" y="3" rx="2"/><path d="M3 9h18"/><path d="M3 15h18"/></svg>`;

const ICON_HR = `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14"/></svg>`;

const ICON_CLOSE = `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>`;

const ICON_DELETE = `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/><path d="M3 6h18"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>`;

const ICON_MORE = `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="1"/><circle cx="12" cy="5" r="1"/><circle cx="12" cy="19" r="1"/></svg>`;

const ICON_MOVE_UP = `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 6L12 2L16 6"/><path d="M12 2V22"/></svg>`;

const ICON_MOVE_DOWN = `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 18L12 22L16 18"/><path d="M12 2V22"/></svg>`;
const ICON_EDIT = `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-square-pen-icon lucide-square-pen"><path d="M12 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.375 2.625a1 1 0 0 1 3 3l-9.013 9.014a2 2 0 0 1-.853.505l-2.873.84a.5.5 0 0 1-.62-.62l.84-2.873a2 2 0 0 1 .506-.852z"/></svg>`;
const ICON_EDIT_OFF = `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="-3 -3 30 30" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m10 10-6.157 6.162a2 2 0 0 0-.5.833l-1.322 4.36a.5.5 0 0 0 .622.624l4.358-1.323a2 2 0 0 0 .83-.5L14 13.982"/><path d="m12.829 7.172 4.359-4.346a1 1 0 1 1 3.986 3.986l-4.353 4.353"/><path d="m15 5 4 4"/><path d="m2 2 20 20"/></svg>`;
const ICON_LOADER = `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="loader-icon"><path d="M12 2v4"/><path d="m16.2 7.8 2.9-2.9"/><path d="M18 12h4"/><path d="m16.2 16.2 2.9 2.9"/><path d="M12 18v4"/><path d="m4.9 19.1 2.9-2.9"/><path d="M2 12h4"/><path d="m4.9 4.9 2.9 2.9"/></svg>`;
const ICON_EDIT_MESSAGE = `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-pencil-icon lucide-pencil"><path d="M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z"/><path d="m15 5 4 4"/></svg>`;
const ICON_ACCEPT_CHECK = `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 7 17l-5-5"/><path d="m22 10-7.5 7.5L13 16"/></svg>`;
const ICON_ACCEPT_PLAY = `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 5a2 2 0 0 1 3.008-1.728l11.997 6.998a2 2 0 0 1 .003 3.458l-12 7A2 2 0 0 1 5 19z"/></svg>`;
const ICON_CANCEL_X = `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>`;
const ICON_REFRESH = `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-rotate-cw"><path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/></svg>`;
// --- 1. UTILITIES ---
function autoResize(textarea) {
    textarea.style.height = 'auto';
    textarea.style.height = textarea.scrollHeight + 'px';

    const placeholder = textarea.previousElementSibling;
    if (placeholder && placeholder.classList.contains('code-placeholder')) {
        placeholder.style.opacity = textarea.value ? '0' : '1';
    }
}

// Initialize CodeMirror for syntax highlighting
function initCodeMirror(textarea) {
    if (!textarea || textarea.dataset.cmInitialized) return;

    const editor = CodeMirror.fromTextArea(textarea, {
        mode: 'python',
        lineNumbers: false,
        lineWrapping: true,
        indentUnit: 4,
        indentWithTabs: false,
        theme: 'default',
        viewportMargin: Infinity,
        autofocus: false,
        scrollbarStyle: 'null'
    });

    textarea.dataset.cmInitialized = 'true';
    editor.on('change', () => {
        // Mark notebook dirty whenever user edits code in CodeMirror
        markDirty();
        const placeholder = textarea.previousElementSibling;
        if (placeholder && placeholder.classList.contains('code-placeholder')) {
            placeholder.style.opacity = editor.getValue() ? '0' : '1';
        }
    });

    return editor;
}


function focusAI() {
    const mini = document.getElementById("ai-mini");
    if (mini) {
        mini.classList.add("open");
        mini.setAttribute("aria-hidden", "false");
    }
    const input = document.getElementById("prompt-input");
    if (input) input.focus();
}

// Removes triple-backtick code blocks and inline backticks from a text blob
function stripCodeBlocks(text) {
    if (!text) return text;
    // Remove fenced code blocks (```...```) including language hints
    text = text.replace(/```[\s\S]*?```/g, "");
    // Convert inline code `like_this` to plain text (remove backticks)
    text = text.replace(/`([^`]+)`/g, "$1");
    return text.trim();
}

function toggleShowCode(val) {
    if (typeof val === 'boolean') showCode = val;
    else showCode = !showCode;
    return showCode;
}

function getActiveCodeCell() {
    return document.querySelector('.code-cell.active:not(.text-cell)') || null;
}

function getCodeEditorFromCell(cellEl) {
    if (!cellEl) return null;
    return cellEl.querySelector('.code-editor');
}

function getCodeFromEditor(editor) {
    if (!editor) return '';
    if (editor.nextSibling && editor.nextSibling.classList && editor.nextSibling.classList.contains('CodeMirror')) {
        const cm = editor.nextSibling.CodeMirror;
        return cm ? cm.getValue() : (editor.value || '');
    }
    return editor.value || '';
}

function setCodeToEditor(editor, code) {
    if (!editor) return;
    if (editor.nextSibling && editor.nextSibling.classList && editor.nextSibling.classList.contains('CodeMirror')) {
        const cm = editor.nextSibling.CodeMirror;
        if (cm) {
            cm.setValue(code);
            cm.focus();
            return;
        }
    }
    editor.value = code;
    autoResize(editor);
    editor.focus();
}

function getCellNumericId(cellEl) {
    if (!cellEl || !cellEl.id || !cellEl.id.startsWith('cell-')) return null;
    const id = Number(cellEl.id.replace('cell-', ''));
    return Number.isFinite(id) ? id : null;
}

function flashCellUpdated(cellEl) {
    if (!cellEl) return;
    cellEl.classList.remove('ai-cell-updated');
    // Force reflow so re-adding class restarts animation
    void cellEl.offsetWidth;
    cellEl.classList.add('ai-cell-updated');
    setTimeout(() => {
        cellEl.classList.remove('ai-cell-updated');
    }, 2500);
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text || '';
    return div.innerHTML;
}

function isLikelyModificationPrompt(prompt = '') {
    const p = (prompt || '').toLowerCase();
    const editKeywords = ['change', 'modify', 'update', 'increase', 'decrease', 'fix', 'optimize', 'improve', 'edit'];
    return editKeywords.some((w) => p.includes(w));
}

function decideCodeProposalFlow(prompt = '') {
    const activeCell = getActiveCodeCell();
    const activeEditor = getCodeEditorFromCell(activeCell);
    const activeCode = activeEditor ? getCodeFromEditor(activeEditor) : '';
    const hasActiveCellWithCode = !!(activeCell && activeEditor && activeCode.trim() !== '');
    const isEditIntent = isLikelyModificationPrompt(prompt);

    // Strict rule:
    // EDIT only when keyword present AND active cell with existing code is available.
    // Otherwise NEW (safe fallback).
    const flow = (isEditIntent && hasActiveCellWithCode) ? 'edit' : 'new';

    return {
        flow,
        activeCell,
        activeEditor,
        activeCode,
        hasActiveCellWithCode,
        isEditIntent
    };
}

function removeCellById(cellId) {
    const cell = document.getElementById(cellId);
    if (!cell) return false;
    const bar = cell.nextElementSibling;
    if (bar && bar.classList.contains('add-cell-bar')) {
        bar.remove();
    }
    cell.remove();
    return true;
}

function createAIPreviewCodeCell(referenceActiveCell) {
    // Reuse the last code cell if it is empty (whitespace-only) before creating a new cell.
    const allCodeCells = Array.from(document.querySelectorAll('.code-cell:not(.text-cell)'));
    const lastCodeCell = allCodeCells.length ? allCodeCells[allCodeCells.length - 1] : null;
    if (lastCodeCell) {
        const lastEditor = getCodeEditorFromCell(lastCodeCell);
        const lastCode = lastEditor ? getCodeFromEditor(lastEditor) : '';
        if (lastEditor && (!lastCode || lastCode.trim() === '')) {
            return { cell: lastCodeCell, createdNewCell: false };
        }
    }

    // Prefer inserting below selected active code cell for Colab-like behavior.
    if (referenceActiveCell) {
        const barBelow = referenceActiveCell.nextElementSibling;
        if (barBelow && barBelow.classList.contains('add-cell-bar')) {
            const addCodeBtn = barBelow.querySelector('.add-cell-btn');
            if (addCodeBtn) {
                addCodeCell(addCodeBtn);
                return { cell: document.getElementById(`cell-${cellCount}`), createdNewCell: true };
            }
        }
    }

    // Fallback: append at bottom when no active cell context exists.
    addCodeCell();
    return { cell: document.getElementById(`cell-${cellCount}`), createdNewCell: true };
}

function computeLineDiff(oldText, newText) {
    const a = (oldText || '').split('\n');
    const b = (newText || '').split('\n');
    const n = a.length;
    const m = b.length;
    const dp = Array.from({ length: n + 1 }, () => Array(m + 1).fill(0));

    for (let i = n - 1; i >= 0; i--) {
        for (let j = m - 1; j >= 0; j--) {
            dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
        }
    }

    const rows = [];
    let i = 0;
    let j = 0;
    while (i < n && j < m) {
        if (a[i] === b[j]) {
            rows.push({ type: 'context', line: a[i] });
            i++;
            j++;
        } else if (dp[i + 1][j] >= dp[i][j + 1]) {
            rows.push({ type: 'remove', line: a[i] });
            i++;
        } else {
            rows.push({ type: 'add', line: b[j] });
            j++;
        }
    }
    while (i < n) {
        rows.push({ type: 'remove', line: a[i++] });
    }
    while (j < m) {
        rows.push({ type: 'add', line: b[j++] });
    }
    return rows;
}

function buildDiffView(oldCode, newCode) {
    const wrap = document.createElement('div');
    wrap.className = 'ai-inline-diff';

    const rows = computeLineDiff(oldCode, newCode);
    rows.forEach((r) => {
        const row = document.createElement('div');
        row.className = `ai-diff-row ${r.type}`;
        const prefix = r.type === 'add' ? '+' : r.type === 'remove' ? '-' : ' ';
        row.innerHTML = `<span class="ai-diff-prefix">${prefix}</span><span class="ai-diff-code">${escapeHtml(r.line)}</span>`;
        wrap.appendChild(row);
    });
    return wrap;
}

function setProposalActionsResolved(proposal, statusText) {
    if (!proposal || !proposal.actionsEl) return;
    proposal.actionsEl.innerHTML = `<span class="ai-proposal-status">${statusText}</span>`;
}

function clearPendingCodeProposal(options = {}) {
    if (!pendingCodeProposal) return;

    const {
        restoreOriginal = false,
        removeProposalUi = false,
        markResolvedText = '',
        deleteNewCell = false
    } = options;
    const proposal = pendingCodeProposal;
    const targetCell = document.getElementById(proposal.cellId);
    const activeCell = proposal.activeCellId ? document.getElementById(proposal.activeCellId) : null;
    const newCell = proposal.newCellId ? document.getElementById(proposal.newCellId) : null;

    if (restoreOriginal && proposal.proposalType === 'edit' && activeCell) {
        const editor = getCodeEditorFromCell(activeCell);
        if (editor) setCodeToEditor(editor, proposal.originalCode || '');
    }

    if (deleteNewCell && proposal.proposalType === 'new' && proposal.newCellId) {
        const previewCell = document.getElementById(proposal.newCellId);
        const isTaggedPreviewCell = !!(previewCell && previewCell.dataset && previewCell.dataset.aiPreviewCell === '1');
        if (proposal.createdNewCell && isTaggedPreviewCell) {
            removeCellById(proposal.newCellId);
        } else if (!proposal.createdNewCell && previewCell) {
            const previewEditor = getCodeEditorFromCell(previewCell);
            if (previewEditor) {
                setCodeToEditor(previewEditor, proposal.originalCode || '');
            }
            if (previewCell.dataset) {
                delete previewCell.dataset.aiPreviewCell;
            }
        }
        if (proposal.activeCellId) {
            const previousActive = document.getElementById(proposal.activeCellId);
            if (previousActive) activateCell(previousActive);
        }
        // Revert dirty state to pre-preview value if user cancels new generated cell.
        if (typeof proposal.wasDirtyBeforePreview === 'boolean') {
            isDirty = proposal.wasDirtyBeforePreview;
        }
    }

    if (targetCell) targetCell.classList.remove('ai-cell-preview');
    if (activeCell) activeCell.classList.remove('ai-cell-preview');
    if (newCell) newCell.classList.remove('ai-cell-preview');

    if (removeProposalUi && proposal.containerEl && proposal.containerEl.parentNode) {
        proposal.containerEl.remove();
    } else if (markResolvedText) {
        setProposalActionsResolved(proposal, markResolvedText);
    }

    pendingCodeProposal = null;
}

function applyPendingCodeProposal(runAfterApply = false) {
    if (!pendingCodeProposal) return;

    const proposal = pendingCodeProposal;
    const targetCellId = proposal.proposalType === 'new' ? proposal.newCellId : proposal.activeCellId;
    const cell = document.getElementById(targetCellId || proposal.cellId);
    const editor = getCodeEditorFromCell(cell);
    if (!cell || !editor) {
        clearPendingCodeProposal({ removeProposalUi: true });
        return;
    }

    if (proposal.mode === 'diff') {
        setCodeToEditor(editor, proposal.newCode);

        // Highlight new/changed lines with Colab-style green
        const cmEl = editor.nextSibling;
        if (cmEl && cmEl.classList && cmEl.classList.contains('CodeMirror')) {
            const cm = cmEl.CodeMirror;
            if (cm) {
                // Clear old highlights just in case
                for (let i = 0; i < cm.lineCount(); i++) {
                    cm.removeLineClass(i, 'background', 'cm-new-code-highlight');
                }
                const oldLines = proposal.originalCode ? proposal.originalCode.split('\n') : [];
                const newLines = proposal.newCode.split('\n');

                for (let i = 0; i < newLines.length; i++) {
                    // Simple diff check: if line is not in the original code, highlight it as new
                    if (!oldLines.includes(newLines[i].trim() ? newLines[i] : null)) {
                        cm.addLineClass(i, 'background', 'cm-new-code-highlight');
                    }
                }
            }
        }
    } else if (proposal.proposalType === 'new' && cell?.dataset) {
        // Accepting a new preview converts it to a normal, permanent cell.
        delete cell.dataset.aiPreviewCell;
    }

    cell.classList.remove('ai-cell-preview');
    flashCellUpdated(cell);
    markDirty();
    setProposalActionsResolved(proposal, runAfterApply ? 'Accepted and running...' : 'Accepted');

    const cellId = getCellNumericId(cell);
    pendingCodeProposal = null;
    if (runAfterApply && cellId !== null) {
        runCode(cellId);
    }
}

function cancelPendingCodeProposal() {
    if (!pendingCodeProposal) return;
    if (pendingCodeProposal.mode === 'diff') {
        clearPendingCodeProposal({ removeProposalUi: true });
        return;
    }
    if (pendingCodeProposal.proposalType === 'new') {
        clearPendingCodeProposal({ removeProposalUi: true, deleteNewCell: true });
        return;
    }
    clearPendingCodeProposal({ restoreOriginal: true, removeProposalUi: true });
}

function createProposalActionsRow(proposalId) {
    const actions = document.createElement('div');
    actions.className = 'ai-proposal-actions';

    const runBtn = document.createElement('button');
    runBtn.type = 'button';
    runBtn.className = 'ai-proposal-btn primary';
    runBtn.setAttribute('data-ai-proposal-action', 'accept-run');
    runBtn.setAttribute('data-ai-proposal-id', proposalId);
    runBtn.innerHTML = `${ICON_ACCEPT_PLAY}<span>Accept & Run</span>`;

    const acceptBtn = document.createElement('button');
    acceptBtn.type = 'button';
    acceptBtn.className = 'ai-proposal-btn';
    acceptBtn.setAttribute('data-ai-proposal-action', 'accept');
    acceptBtn.setAttribute('data-ai-proposal-id', proposalId);
    acceptBtn.innerHTML = `${ICON_ACCEPT_CHECK}<span>Accept</span>`;

    const cancelBtn = document.createElement('button');
    cancelBtn.type = 'button';
    cancelBtn.className = 'ai-proposal-btn';
    cancelBtn.setAttribute('data-ai-proposal-action', 'cancel');
    cancelBtn.setAttribute('data-ai-proposal-id', proposalId);
    cancelBtn.innerHTML = `${ICON_CANCEL_X}<span>Cancel</span>`;

    actions.appendChild(runBtn);
    actions.appendChild(acceptBtn);
    actions.appendChild(cancelBtn);
    return actions;
}

function stageCodeProposalUI(code, prompt) {
    const container = document.createElement('div');
    container.className = 'ai-code-proposal';

    // Decide flow FIRST, before creating or modifying any cell for this request.
    const flowDecision = decideCodeProposalFlow(prompt);
    const activeCell = flowDecision.activeCell;
    clearPendingCodeProposal({ restoreOriginal: true, removeProposalUi: true, deleteNewCell: true });
    const proposalType = flowDecision.flow;
    const proposalId = `proposal_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;

    let targetCell = null;
    let originalCode = '';
    let diffEl = null;

    if (proposalType === 'edit') {
        targetCell = activeCell;
        originalCode = flowDecision.activeCode;
        diffEl = buildDiffView(originalCode, code);
        container.appendChild(diffEl);
    } else {
        const wasDirtyBeforePreview = isDirty;
        const created = createAIPreviewCodeCell(activeCell);
        targetCell = created ? created.cell : null;
        const createdNewCell = created ? created.createdNewCell : false;
        const targetEditor = getCodeEditorFromCell(targetCell);

        if (!targetCell || !targetEditor) {
            const info = document.createElement('div');
            info.className = 'ai-proposal-info';
            info.textContent = 'Could not create a new cell for preview.';
            container.appendChild(info);
            return container;
        }

        const originalPreviewCode = getCodeFromEditor(targetEditor);
        activateCell(targetCell);
        targetCell.dataset.aiPreviewCell = '1';
        setCodeToEditor(targetEditor, code);
        targetCell.classList.add('ai-cell-preview');
        flashCellUpdated(targetCell);

        pendingCodeProposal = {
            proposalId,
            cellId: targetCell.id,
            activeCellId: activeCell ? activeCell.id : null,
            newCellId: targetCell.id,
            proposalType: 'new',
            originalCode: originalPreviewCode || '',
            newCode: code,
            mode: 'preview',
            createdNewCell,
            wasDirtyBeforePreview,
            containerEl: null,
            actionsEl: null,
            diffEl: null
        };
    }

    const actionsEl = createProposalActionsRow(proposalId);
    container.appendChild(actionsEl);

    if (pendingCodeProposal && pendingCodeProposal.proposalId === proposalId && pendingCodeProposal.proposalType === 'new') {
        pendingCodeProposal.containerEl = container;
        pendingCodeProposal.actionsEl = actionsEl;
        return container;
    }

    pendingCodeProposal = {
        proposalId,
        cellId: targetCell ? targetCell.id : null,
        activeCellId: activeCell ? activeCell.id : null,
        newCellId: null,
        proposalType: 'edit',
        originalCode,
        newCode: code,
        mode: 'diff',
        containerEl: container,
        actionsEl,
        diffEl
    };

    return container;
}


// --- script.js ---

async function initPyodide() {

    const dot = document.getElementById('status-dot');

    const text = document.getElementById('status-text');

    text.innerText = "Loading Python Kernel...";

    dot.style.color = "orange";

    try {

        pyodide = await loadPyodide();

        // 1. Load Packages

        await pyodide.loadPackage(["micropip", "numpy", "pandas", "matplotlib"]);

        // 2. Setup Environment & Helpers

        await pyodide.runPythonAsync(`

            import sys
            import io
            import base64
            import json
            import gc
            import pandas as pd

            import numpy as np


            from pyodide.http import pyfetch
 
            import matplotlib

            matplotlib.use("Agg", force=True)

            import matplotlib.pyplot as plt

            def no_op_show(*args, **kwargs): pass

            plt.show = no_op_show
 
            # --- DB BRIDGE ---

            async def query_db(sql_query):

                try:

                    response = await pyfetch(

                        url="/api/execute_sql",

                        method="POST",

                        headers={"Content-Type": "application/json"},

                        body=json.dumps({"sql": sql_query})

                    )

                    resp_json = await response.json()

                    if resp_json.get("status") == "error":

                        print(f"❌ SQL Error: {resp_json.get('message')}")

                        return None

                    data = resp_json.get("data", [])

                    if data:

                        # Now 'pd' is defined!

                        return pd.DataFrame(data)

                    else:

                        print("✅ Query executed (No rows).")

                        return pd.DataFrame()

                except Exception as e:

                    print(f"⚠️ Network Error: {e}")

                    return None
 
            # --- USER NAMESPACE (The 'Memory') ---

            user_ns = {}

            user_ns['__name__'] = '__main__'

            user_ns['np'] = np

            user_ns['pd'] = pd

            user_ns['plt'] = plt

            user_ns['query_db'] = query_db
 
            # --- HELPER: Extracts Plots ---

            def post_exec_helper():

                res = {"image": None}

                if plt.get_fignums():

                    try:

                        buf = io.BytesIO()

                        plt.savefig(buf, format='png', bbox_inches='tight', dpi=100)

                        buf.seek(0)

                        res["image"] = base64.b64encode(buf.read()).decode('utf-8')

                    except Exception as e:

                        print(f"Plot Error: {e}")

                    finally:

                        plt.close('all')

                        gc.collect()

                return json.dumps(res)

        `);

        text.innerText = "Online";

        dot.style.color = "#4ade80";

        console.log("Pyodide Ready");
        hideLoadingScreen();

    } catch (e) {

        text.innerText = "Kernel Failed";

        dot.style.color = "red";
        hideLoadingScreen();

        console.error(e);

    }

}


// Update window.onload to include initPyodide
window.onload = () => {
    addCodeCell();
    checkStatus();
    loadConnections();
    initPyodide();
    initAIWidget();
    // Fresh page load starts as a NEW untitled notebook: no chats loaded.
    currentNotebookId = 'notebook_' + Date.now();
    currentNotebookName = null;
    isNotebookSaved = false;
    chats = [];
    currentChatId = null;
    chatHistory = [];
    messagePairs = [];
    persistActiveNotebookId();
    renderChatList();
    setInterval(checkStatus, 180000); // 3 minutes

    document.getElementById("run-btn")?.addEventListener("click", runAIQuery);
    document.addEventListener("click", (e) => {
        const actionBtn = e.target.closest("[data-ai-proposal-action]");
        if (!actionBtn) return;
        if (!pendingCodeProposal) return;

        const proposalId = actionBtn.getAttribute('data-ai-proposal-id');
        if (proposalId !== pendingCodeProposal.proposalId) return;

        const action = actionBtn.getAttribute('data-ai-proposal-action');
        if (action === 'accept') {
            applyPendingCodeProposal(false);
        } else if (action === 'accept-run') {
            applyPendingCodeProposal(true);
        } else if (action === 'cancel') {
            cancelPendingCodeProposal();
        }
    });

};


// --- 2. NOTEBOOK KERNEL ---

function updateLastActiveCell(cellId, newCode) {
    if (!cellId) return;
    const editorEl = document.querySelector(`#cell-${cellId} .code-editor`);
    if (!editorEl) return;

    if (editorEl.nextSibling && editorEl.nextSibling.classList && editorEl.nextSibling.classList.contains('CodeMirror')) {
        const cm = editorEl.nextSibling.CodeMirror;
        cm.setValue(newCode);
    } else {
        editorEl.value = newCode;
    }
}

async function runCode(id) {
    lastActiveCellId = id;
    const codeEditor = document.querySelector(`#cell-${id} .code-editor`);
    let code = '';

    // Get code from CodeMirror if initialized, otherwise from textarea
    if (codeEditor.nextSibling && codeEditor.nextSibling.classList && codeEditor.nextSibling.classList.contains('CodeMirror')) {
        const cm = codeEditor.nextSibling.CodeMirror;
        code = cm ? cm.getValue() : codeEditor.value;
    } else {
        code = codeEditor.value;
    }

    const outDiv = document.getElementById(`out-${id}`);
    const btn = document.getElementById(`btn-${id}`);
    if (!pyodide) { outDiv.innerText = "⚠️ Kernel loading..."; return; }

    btn.innerHTML = ICON_LOADER;
    outDiv.innerHTML = ""; // Clear output

    // Clear previous highlights
    if (codeEditor.nextSibling && codeEditor.nextSibling.classList && codeEditor.nextSibling.classList.contains('CodeMirror')) {
        const cm = codeEditor.nextSibling.CodeMirror;
        codeEditor.parentElement.querySelectorAll('.cm-new-code-highlight').forEach(el => {
            el.classList.remove('cm-new-code-highlight');
        });
    }

    // 1. Capture Python Print Statements
    // We direct them straight to the div
    const printHandler = (text) => {
        const pre = document.createElement("pre");
        pre.style.margin = "0"; // compact
        pre.innerText = text;
        outDiv.appendChild(pre);
    };
    pyodide.setStdout({ batched: printHandler });
    pyodide.setStderr({ batched: printHandler });

    const flushOutput = () => {
        try {
            pyodide.runPython("import sys\nif hasattr(sys, 'stdout') and hasattr(sys.stdout, 'write'): sys.stdout.write('\\n')\nif hasattr(sys, 'stderr') and hasattr(sys.stderr, 'write'): sys.stderr.write('\\n')");
            let checkCount = 0;
            let pNode = outDiv.lastChild;
            while (pNode && checkCount < 2) {
                let prevNode = pNode.previousSibling;
                if (pNode.tagName === 'PRE' && pNode.innerText === '') {
                    outDiv.removeChild(pNode);
                }
                pNode = prevNode;
                checkCount++;
            }
        } catch (err) { }
    };

    try {
        await pyodide.loadPackagesFromImports(code);

        // 2. EXECUTE CODE (Supports await automatically!)
        // We pass 'user_ns' so variables are saved.
        let result = await pyodide.runPythonAsync(code, {
            globals: pyodide.globals.get("user_ns")
        });

        flushOutput();

        // 3. Handle "Last Line Value" (like Jupyter)
        if (result !== undefined && result !== null) {
            // Check for Pandas DataFrame or HTML repr
            if (result._repr_html_) {
                const div = document.createElement("div");
                div.innerHTML = result._repr_html_();
                div.style.overflowX = "auto";
                outDiv.appendChild(div);
            }
            // Check for plain text representation (if not 'None')
            else if (result.type !== "NoneType") {
                printHandler(result.toString());
            }
            // Cleanup JS proxy
            if (result.destroy) result.destroy();
        }

        // 4. Handle Plots (Matplotlib)
        // Call our helper function
        const plotDataRaw = await pyodide.runPythonAsync("post_exec_helper()");
        const plotData = JSON.parse(plotDataRaw);
        if (plotData.image) {
            const img = document.createElement("img");
            img.src = "data:image/png;base64," + plotData.image;
            img.style.maxWidth = "100%";
            outDiv.appendChild(img);
        }

        // Trigger suggestion chips based on code context
        const hasPlot = !!plotData.image;
        const hasDF = !!(outDiv.querySelector('table') || outDiv.querySelector('div[style*="overflow"]'));
        updateSuggestionChips(getSuggestionsForCode(code, false, hasPlot, hasDF));

    } catch (e) {
        flushOutput();
        const errorStack = e.message || String(e);
        const errorSample = errorStack.length > 800 ? errorStack.substring(0, 800) + '...' : errorStack;

        const debugHtml = `<button class="ai-debug-btn" onclick="debugCellError(${id})" style="background:var(--accent); color:white; border:none; border-radius:3px; padding:4px 8px; font-size:0.75rem; cursor:pointer; margin-left:10px; vertical-align:middle; display:inline-flex; align-items:center; gap:4px;"><svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m21.64 3.64-1.28-1.28a1.21 1.21 0 0 0-1.72 0L2.36 18.64a1.21 1.21 0 0 0 0 1.72l1.28 1.28a1.2 1.2 0 0 0 1.72 0L21.64 5.36a1.21 1.21 0 0 0 0-1.72Z"/><path d="m14 7 3 3"/><path d="M5 6v4"/><path d="M19 14v4"/><path d="M10 2v2"/><path d="M7 8H5.5C5.1 8 4.7 8.1 4.4 8.4L2.8 10l5.4 5.4 1.6-1.6c.3-.3.4-.7.4-1.1v-1.5"/><path d="M10 22v-2"/></svg> Debug with AI</button>`;

        outDiv.innerHTML += `<div style="color:#ef4444; margin-top:5px; line-height:1.4;"><strong>Error:</strong> ${errorStack} <div style="margin-top:8px;">${debugHtml}</div></div>`;
        outDiv.setAttribute("data-last-error", errorSample);

        // Show error-specific suggestion chips
        updateSuggestionChips(getSuggestionsForCode(code, true, false, false));
    } finally {
        btn.innerText = "▶";
    }
}

async function debugCellError(id) {
    const codeEditor = document.querySelector(`#cell-${id} .code-editor`);
    if (!codeEditor) return;

    const outDiv = document.getElementById(`out-${id}`);
    const errorTrace = outDiv.getAttribute("data-last-error") || "Unknown error";

    // Shorten the prompt request
    const prompt = `Fix the error in this code:\n\nError:\n${errorTrace}`;

    // Activate the cell so AI knows context
    const cellEl = document.getElementById(`cell-${id}`);
    if (cellEl) activateCell(cellEl);

    // Fill the AI prompt and automatically submit
    const aiInput = document.getElementById("prompt-input");
    if (aiInput) {
        aiInput.value = prompt;
        focusAI();
        await runAIQuery();
    }
}
// 1. REVISED ADD CODE CELL
function addCodeCell(button) {
    cellCount++;
    const cellHtml = `
       <div class="code-cell" id="cell-${cellCount}" onclick="activateCell(this)">
            <div class="cell-controls">
                <button title="Move Up" onclick="event.stopPropagation(); moveCellUp(this)">${ICON_MOVE_UP}</button>
                <button title="Move Down" onclick="event.stopPropagation(); moveCellDown(this)">${ICON_MOVE_DOWN}</button>
                <button title="Edit" onclick="event.stopPropagation(); editCell(this)">${ICON_EDIT}</button>
                <button title="Delete" onclick="event.stopPropagation(); deleteCell(this)">${ICON_DELETE}</button>
                <button title="More" onclick="event.stopPropagation(); moreOptions(this)">${ICON_MORE}</button>
            </div>

            <div class="cell-run-part">
                <button class="play-btn" onclick="event.stopPropagation(); runCode(${cellCount})" id="btn-${cellCount}">▶</button>
            </div>
            
            <div class="cell-content-part">
                <div class="code-placeholder">Start coding or <u onclick="event.stopPropagation(); focusAI()">generate</u> with AI.</div>
                <textarea class="code-editor" oninput="autoResize(this); markDirty()" rows="1"></textarea>
                <div class="cell-output" id="out-${cellCount}"></div>
            </div>
        </div>`;

    const barHtml = `<div class="add-cell-bar">
                        <button class="add-cell-btn" onclick="addCodeCell(this)">＋ Code</button>
                        <button class="add-cell-btn secondary" onclick="addTextCell(this)">＋ Text</button>
                     </div>`;

    if (button) {
        // If clicked from a bar between cells — user action, mark dirty
        markDirty();
        const bar = button.parentElement;
        bar.insertAdjacentHTML('afterend', cellHtml);
        const insertedCell = bar.nextElementSibling;
        insertedCell.insertAdjacentHTML('afterend', barHtml);
    } else {
        // If starting fresh
        const view = document.getElementById('workspace-view');
        view.insertAdjacentHTML('beforeend', cellHtml);
        const insertedCell = view.lastElementChild;
        insertedCell.insertAdjacentHTML('afterend', barHtml);
    }

    // Auto-focus the new text area
    setTimeout(() => {
        const ta = document.querySelector(`#cell-${cellCount} textarea`);
        if (ta) {
            autoResize(ta);
            // Initialize CodeMirror for syntax highlighting
            const editor = initCodeMirror(ta);
            if (editor) {
                editor.focus();
            } else {
                ta.focus();
            }
        }
        // activate the cell visually
        document.getElementById(`cell-${cellCount}`).classList.add('active');
    }, 50);
}


function shouldShowCodeForPrompt(promptText = "") {
    const p = promptText.toLowerCase();

    // If user explicitly wants explanation, hide code by default
    const explainIntent =
        p.includes("explain") ||
        p.includes("explanation") ||
        p.includes("describe") ||
        p.includes("meaning") ||
        p.includes("what does") ||
        p.includes("how does");

    // If user explicitly asks for code, allow it
    const codeIntent =
        p.includes("code") ||
        p.includes("give me code") ||
        p.includes("write code") ||
        p.includes("generate code") ||
        p.includes("example code");

    return codeIntent ? true : !explainIntent;
}


// 2. FIXED MOVE FUNCTIONS
// We assume the structure is: [CodeCell] -> [AddCellBar] -> [CodeCell] -> [AddCellBar]
// So we must move the "CodeCell + AddCellBar" pair together.
// --- script.js ---

// ======================================================
// CONTEXT-AWARE SUGGESTION CHIPS
// ======================================================

/**
 * Render suggestion chips in the AI panel.
 * @param {Array<{label: string, prompt: string, icon?: string}>} chips
 */
function updateSuggestionChips(chips) {
    const container = document.getElementById("ai-suggestion-chips");
    if (!container) return;
    container.innerHTML = "";

    if (!chips || chips.length === 0) return;

    chips.forEach((chip) => {
        const btn = document.createElement("button");
        btn.className = "ai-suggestion-chip";
        btn.type = "button";
        btn.innerHTML = `<span class="chip-icon">${chip.icon || "✨"}</span>${chip.label}`;
        btn.addEventListener("click", () => {
            const input = document.getElementById("prompt-input");
            if (input) {
                input.value = chip.prompt;
                input.style.height = "auto";
                input.style.height = Math.min(input.scrollHeight, 140) + "px";
            }
            // Clear chips and auto-send
            container.innerHTML = "";
            runAIQuery();
        });
        container.appendChild(btn);
    });
}

/**
 * Get context-aware suggestions based on uploaded file type.
 */
function getSuggestionsForFile(fileName) {
    const ext = fileName.split(".").pop().toLowerCase();
    const name = fileName.length > 20 ? fileName.substring(0, 17) + "..." : fileName;

    const suggestions = {
        csv: [
            { label: "Load into DataFrame", prompt: `Load the uploaded CSV file "${fileName}" into a Pandas DataFrame and display it.`, icon: "📊" },
            { label: "Show first 5 rows", prompt: `Show the first 5 rows of the uploaded file "${fileName}".`, icon: "👀" },
            { label: "Describe the dataset", prompt: `Describe the dataset in "${fileName}" — show statistics, column types, and missing values.`, icon: "📈" },
            { label: "Plot a chart", prompt: `Create a suitable visualization chart for the data in "${fileName}".`, icon: "📉" },
        ],
        xlsx: [
            { label: "Load into DataFrame", prompt: `Load the uploaded Excel file "${fileName}" into a Pandas DataFrame.`, icon: "📊" },
            { label: "Show first 5 rows", prompt: `Show the first 5 rows of the Excel file "${fileName}".`, icon: "👀" },
            { label: "List all sheets", prompt: `List all sheet names in the Excel file "${fileName}".`, icon: "📋" },
            { label: "Describe the dataset", prompt: `Describe the data in "${fileName}" — statistics and column info.`, icon: "📈" },
        ],
        xls: null, // Will fallback to xlsx
        json: [
            { label: "Parse this JSON", prompt: `Parse the uploaded JSON file "${fileName}" and display its structure.`, icon: "🔧" },
            { label: "Show the structure", prompt: `Show the keys and structure of the JSON file "${fileName}".`, icon: "🗂️" },
            { label: "Convert to DataFrame", prompt: `Convert the JSON file "${fileName}" to a Pandas DataFrame.`, icon: "📊" },
            { label: "Extract specific fields", prompt: `What fields are available in "${fileName}"? Help me extract specific data.`, icon: "🔍" },
        ],
        pdf: [
            { label: "Summarize this document", prompt: `Summarize the uploaded document "${fileName}".`, icon: "📝" },
            { label: "List key points", prompt: `List the key points from "${fileName}".`, icon: "📌" },
            { label: "What is this about?", prompt: `What is the document "${fileName}" about?`, icon: "❓" },
            { label: "Extract specific info", prompt: `Help me find specific information in "${fileName}".`, icon: "🔍" },
        ],
        docx: null, // Will fallback to pdf
        txt: null,  // Will fallback to pdf
    };

    // Fallbacks
    if (!suggestions[ext] && (ext === "xls")) return suggestions["xlsx"];
    if (!suggestions[ext] && (ext === "docx" || ext === "txt")) return suggestions["pdf"];

    return suggestions[ext] || [
        { label: "Analyze this file", prompt: `Analyze the uploaded file "${fileName}".`, icon: '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>' },
        { label: "What's in this file?", prompt: `What is in the uploaded file "${fileName}"?`, icon: '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 2-3 4"></path><line x1="12" y1="17" x2="12" y2="17"></line></svg>' },
    ];
}

/**
 * Get context-aware suggestions based on executed code.
 */
function getSuggestionsForCode(code, hasError, hasPlot, hasDataFrame) {
    const codeLower = code.toLowerCase();

    // Error case — highest priority
    if (hasError) {
        return [
            { label: "Fix this error", prompt: "Fix the error in the code I just ran.", icon: '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 2 L11 13"></path><path d="M14.5 2.5a9 9 0 1 1-12.7 12.7L11 13"></path></svg>' },
            { label: "Explain what went wrong", prompt: "Explain why my code produced an error and how to fix it.", icon: '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 2-3 4"></path><line x1="12" y1="17" x2="12" y2="17"></line></svg>' },
            { label: "Try alternative approach", prompt: "Suggest an alternative approach to achieve the same result without the error.", icon: '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="7" width="20" height="10" rx="2"></rect><path d="M7 7v-2a5 5 0 0 1 10 0v2"></path></svg>' },
        ];
    }

    // Plot/visualization case
    if (hasPlot || codeLower.includes("plt.") || codeLower.includes("matplotlib") || codeLower.includes(".plot(")) {
        return [
            { label: "Save this plot", prompt: "Save the plot I just generated as a PNG file.", icon: '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 21H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h11l5 5v9a2 2 0 0 1-2 2z"></path><polyline points="17 21 17 13 7 13 7 21"></polyline></svg>' },
            { label: "Change color scheme", prompt: "Change the color scheme of my plot to make it more visually appealing.", icon: '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><path d="M12 2a10 10 0 0 1 10 10"></path></svg>' },
            { label: "Add title & labels", prompt: "Add a proper title, axis labels, and legend to my plot.", icon: '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6L9 17l-5-5"></path></svg>' },
            { label: "Explain this visualization", prompt: "Explain what this visualization shows about the data.", icon: '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 3v18h18"></path><path d="M18 13v6"></path><path d="M13 8v11"></path><path d="M8 16v3"></path></svg>' },
        ];
    }

    // DataFrame/pandas case
    if (hasDataFrame || codeLower.includes("import pandas") || codeLower.includes("pd.read") || codeLower.includes("dataframe")) {
        return [
            { label: "Show column types", prompt: "Show the data types and info for all columns in my DataFrame.", icon: "📋" },
            { label: "Handle missing values", prompt: "Check for and handle any missing values in my DataFrame.", icon: "🔧" },
            { label: "Plot distribution", prompt: "Plot the distribution of numerical columns in my DataFrame.", icon: "📈" },
            { label: "Generate summary stats", prompt: "Generate descriptive statistics for my DataFrame.", icon: "📊" },
        ];
    }

    // General code execution
    return [
        { label: "Explain this output", prompt: "Explain the output of the code I just ran.", icon: "💡" },
        { label: "Optimize this code", prompt: "Suggest optimizations for the code I just ran.", icon: "⚡" },
        { label: "Add error handling", prompt: "Add proper error handling to my code.", icon: "🛡️" },
    ];
}

// ======================================================

function setAILoading(isLoading) {
    const sendBtn = document.getElementById("run-btn");
    const sendIcon = document.getElementById("send-icon");
    const stopIcon = document.getElementById("stop-icon");
    if (!sendBtn || !sendIcon || !stopIcon) return;

    if (isLoading) {
        sendBtn.classList.add("is-loading");
        sendIcon.style.display = "none";
        stopIcon.style.display = "block";
        sendBtn.setAttribute("aria-label", "Stop");
    } else {
        sendBtn.classList.remove("is-loading");
        sendIcon.style.display = "block";
        stopIcon.style.display = "none";
        sendBtn.setAttribute("aria-label", "Send");
    }
}

// ======================================================
// MESSAGE EDITING FUNCTIONS
// ======================================================

/**
 * Add edit button to a user message bubble
 */
function addEditButton(userBubble, prompt, messageIndex) {
    // Check if edit button already exists
    if (userBubble.querySelector('.edit-message-btn')) return;

    const editBtn = document.createElement('button');
    editBtn.className = 'edit-message-btn';
    editBtn.type = 'button';
    editBtn.title = 'Edit message';
    editBtn.innerHTML = ICON_EDIT_MESSAGE;
    editBtn.addEventListener('click', () => editMessage(messageIndex));

    userBubble.appendChild(editBtn);
}

/**
 * Cancel inline edit for a message (restoring original text).
 * Called internally — safe to call even if no edit is active.
 */
function cancelInlineEdit(messageIndex) {
    const pair = messagePairs[messageIndex];
    if (!pair || !pair.userBubble) return;

    const bubble = pair.userBubble;
    bubble.classList.remove('editing');

    // Restore original text + edit button
    bubble.innerText = pair.prompt;
    addEditButton(bubble, pair.prompt, messageIndex);

    editingMessageIndex = null;
}

/**
 * Edit a message — inline editing.
 * Replaces the user bubble content with a textarea + Send/Cancel buttons.
 * No messages are removed; chat history stays intact.
 */
function editMessage(messageIndex) {
    const messagePair = messagePairs[messageIndex];
    if (!messagePair || !messagePair.userBubble) return;

    // If another message is already being edited, cancel it first
    if (editingMessageIndex !== null && editingMessageIndex !== messageIndex) {
        cancelInlineEdit(editingMessageIndex);
    }

    // If this message is already in edit mode, do nothing
    if (editingMessageIndex === messageIndex) return;

    // If AI is currently generating, stop it first
    if (currentAbortController) {
        currentAbortController.abort();
        currentAbortController = null;
        setAILoading(false);
    }

    editingMessageIndex = messageIndex;
    const bubble = messagePair.userBubble;
    const originalText = messagePair.prompt;

    // Mark bubble as editing (hides pencil icon via CSS)
    bubble.classList.add('editing');
    bubble.innerHTML = '';

    // ── Textarea ────────────────────────────────────────────────────────────
    const textarea = document.createElement('textarea');
    textarea.className = 'inline-edit-textarea';
    textarea.value = originalText;
    textarea.rows = 1;

    const resizeTA = () => {
        textarea.style.height = 'auto';
        textarea.style.height = textarea.scrollHeight + 'px';
    };
    textarea.addEventListener('input', resizeTA);

    // ── Action buttons ──────────────────────────────────────────────────────
    const actions = document.createElement('div');
    actions.className = 'inline-edit-actions';

    // Send button — uses existing .notebook-btn styling
    const sendBtn = document.createElement('button');
    sendBtn.type = 'button';
    sendBtn.className = 'notebook-btn';
    sendBtn.title = 'Send (Ctrl+Enter)';
    sendBtn.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg> Send`;

    sendBtn.addEventListener('click', async () => {
        const newText = textarea.value.trim();
        if (!newText) return;

        // ── 1. Exit edit mode, update bubble ───────────────────────────────
        bubble.classList.remove('editing');
        bubble.innerHTML = '';
        bubble.innerText = newText;
        addEditButton(bubble, newText, messageIndex);
        editingMessageIndex = null;

        // ── 2. Remove all messages AFTER this one from DOM ─────────────────
        for (let i = messageIndex + 1; i < messagePairs.length; i++) {
            const pair = messagePairs[i];
            if (pair.userBubble?.parentNode) pair.userBubble.remove();
            if (pair.assistantBubble?.parentNode) pair.assistantBubble.remove();
        }

        // Also remove the assistant bubble that belonged to this pair
        if (messagePair.assistantBubble?.parentNode) {
            messagePair.assistantBubble.remove();
            messagePair.assistantBubble = null;
        }

        // ── 3. Slice arrays to edited index ───────────────────────────────
        messagePairs.splice(messageIndex + 1);           // keep [0..messageIndex]
        messagePair.prompt = newText;
        const chatStartIndex = messageIndex * 2;         // first relevant history entry
        chatHistory.splice(chatStartIndex);              // trim history here and beyond

        // ── 4. Regenerate AI response ──────────────────────────────────────
        await runEditedQuery(newText, messageIndex);
    });

    // Cancel button — uses existing .notebook-btn styling
    const cancelBtn = document.createElement('button');
    cancelBtn.type = 'button';
    cancelBtn.className = 'notebook-btn';
    cancelBtn.title = 'Cancel (Escape)';
    cancelBtn.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg> Cancel`;
    cancelBtn.addEventListener('click', () => cancelInlineEdit(messageIndex));

    // Keyboard shortcuts: Escape = cancel, Ctrl+Enter = send
    textarea.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            e.preventDefault();
            cancelInlineEdit(messageIndex);
        } else if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
            e.preventDefault();
            sendBtn.click();
        }
    });

    actions.appendChild(sendBtn);
    actions.appendChild(cancelBtn);

    bubble.appendChild(textarea);
    bubble.appendChild(actions);

    // Auto-resize + focus
    requestAnimationFrame(() => {
        resizeTA();
        textarea.focus();
        textarea.selectionStart = textarea.selectionEnd = textarea.value.length;
    });
}


// ======================================================
// REGENERATE QUERY AFTER EDIT
// ======================================================

/**
 * Called by editMessage Send — sends the updated prompt to the AI and
 * appends a fresh assistant bubble at the correct position.
 *
 * @param {string}  prompt        The updated user message text
 * @param {number}  messageIndex  Index in messagePairs for this message
 */
async function runEditedQuery(prompt, messageIndex) {
    const contentArea = document.getElementById('ai-content-area');
    const tray = document.getElementById('ai-response-tray');
    if (!contentArea) return;

    // Collect notebook context
    const cells = Array.from(document.querySelectorAll('.code-editor, .text-editor'))
        .map(el => (el.value !== undefined ? el.value : el.innerHTML));

    let activeVars = [];
    if (pyodide) {
        try {
            const keys = pyodide.runPython('list(userns.keys())').toJs();
            activeVars = keys.filter(k => !k.startsWith('_') && !['pd', 'np', 'plt', 'querydb'].includes(k));
        } catch (_) { }
    }

    // Timer
    const startTime = Date.now();
    const timerEl = document.createElement('span');
    timerEl.style.cssText = "margin-left:auto;font-family:'Fira Code', monospace;font-size:0.85rem;color:#64748b;";
    timerEl.innerText = '0.0s';

    // ── Assistant placeholder bubble ──────────────────────────────────────
    const assistantBubble = document.createElement('div');
    assistantBubble.className = 'ai-msg assistant';
    assistantBubble.style.padding = '12px 10px 12px 16px'; // Reduced
    assistantBubble.style.background = '#ffffff';
    assistantBubble.style.border = '1px solid #e6edf3';
    assistantBubble.style.borderRadius = '10px';
    assistantBubble.style.margin = '6px 0'; // Tighter
    assistantBubble.innerHTML = `<div style="display:flex;align-items:center;gap:10px;"><span class="pulse-icon"></span><strong>Assistant</strong></div><div style="margin-top:8px;color:#64748b;">Generating response... </div>`;
    assistantBubble.querySelector('div').appendChild(timerEl);
    contentArea.appendChild(assistantBubble);

    // Update messagePairs entry (index already trimmed to messageIndex)
    messagePairs[messageIndex].assistantBubble = assistantBubble;

    if (tray) tray.scrollTop = tray.scrollHeight;

    const timerInt = setInterval(() => {
        timerEl.innerText = ((Date.now() - startTime) / 1000).toFixed(1) + 's';
    }, 100);

    setAILoading(true);
    currentAbortController = new AbortController();

    const reqPayload = {
        prompt,
        notebook_cells: cells,
        variables: activeVars,
        chat_history: chatHistory
    };

    try {
        const resp = await fetch('query', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(reqPayload),
            signal: currentAbortController.signal,
        });

        if (!resp.ok) throw new Error('Server Error');

        const data = await resp.json();
        clearInterval(timerInt);
        const totalTime = ((Date.now() - startTime) / 1000).toFixed(2);
        const toolUsed = data.tool_used || '';
        let answer = data.answer || '';

        // Title: set once from FIRST user message only.
        if (currentChatId && typeof updateChatTitleFromFirstUserMessage === 'function') {
            updateChatTitleFromFirstUserMessage(currentChatId, prompt);
        }

        // Persist to chatHistory
        chatHistory.push({ role: 'user', content: prompt });
        chatHistory.push({ role: 'assistant', content: answer });

        // Code block handling (mirrors runAIQuery)
        let codeNode = null;
        const originalAnswer = answer;
        const isGenerateIntent = toolUsed.toUpperCase().includes('GENERATE');
        const codeMatch = originalAnswer.match(/```python([\s\S]*?)```/);

        if (codeMatch && isGenerateIntent) {
            const code = codeMatch[1].trim();
            if (!showCode) {
                answer = stripCodeBlocks(originalAnswer);
                codeNode = null;
            } else {
                answer = originalAnswer.replace(codeMatch[0], '').trim();
                codeNode = stageCodeProposalUI(code, prompt);
            }
        } else if (codeMatch && !isGenerateIntent) {
            answer = stripCodeBlocks(originalAnswer);
            codeNode = null;
        } else {
            if (!showCode) answer = stripCodeBlocks(answer);
        }

        // Render final assistant bubble
        assistantBubble.innerHTML = '';
        const header = document.createElement('div');
        header.style.cssText = 'display:flex;justify-content:space-between;align-items:center;margin-bottom:6px'; // Tighter
        const titleEl = document.createElement('strong');
        titleEl.innerText = 'Assistant';
        const timeLabel = document.createElement('span');
        timeLabel.style.cssText = 'color:#888;font-size:0.7rem'; // Smaller
        timeLabel.innerText = `Took ${totalTime}s`;
        header.appendChild(titleEl);
        header.appendChild(timeLabel);

        const body = document.createElement('div');
        body.style.cssText = 'font-size:0.88rem;line-height:1.5'; // Shrunk from 0.95rem (~14px)
        if (typeof marked !== 'undefined' && typeof DOMPurify !== 'undefined') {
            body.innerHTML = DOMPurify.sanitize(marked.parse(answer || ''));
        } else {
            body.innerText = answer;
        }

        assistantBubble.appendChild(header);
        assistantBubble.appendChild(body);
        if (codeNode) assistantBubble.appendChild(codeNode);

        if (tray) tray.scrollTop = tray.scrollHeight;

    } catch (e) {
        clearInterval(timerInt);
        if (e.name === 'AbortError') {
            assistantBubble.innerHTML = `<div style="display:flex;align-items:center;gap:10px;"><strong>Assistant</strong></div><div style="margin-top:8px;color:#94a3b8;font-style:italic;">Response cancelled.</div>`;
        } else {
            assistantBubble.innerHTML = `<div style="display:flex;align-items:center;gap:10px;"><strong>Assistant</strong></div><div style="margin-top:8px;color:red;">Error: ${e.message}</div>`;
        }
    } finally {
        currentAbortController = null;
        setAILoading(false);
        // Persist final state
        if (!viewingHistoryItem) {
            if (typeof saveCurrentChat === 'function') saveCurrentChat();
            if (typeof saveChatsToLocalStorage === 'function') saveChatsToLocalStorage();
        } else {
            // If viewing a history item, persist the updated chat history back to its original notebook (best-effort)
            if (viewingHistoryOriginalNotebook) {
                try {
                    await saveChatHistoryToNotebook(viewingHistoryOriginalNotebook, chatHistory);
                } catch (e) {
                    console.warn('Failed to persist history chat back to original notebook:', e);
                }
            }
        }
    }
}


// ======================================================
// (Multi-chat functions are defined in multi_chat_functions.js)
// ======================================================












// ======================================================

async function runAIQuery() {
    const input = document.getElementById("prompt-input");
    const contentArea = document.getElementById("ai-content-area");
    const tray = document.getElementById("ai-response-tray");
    const mini = document.getElementById("ai-mini");

    if (!input || !contentArea) return;

    // If currently loading, abort
    if (currentAbortController) {
        currentAbortController.abort();
        currentAbortController = null;
        setAILoading(false);
        return;
    }

    const prompt = input.value.trim();
    if (!prompt && attachedFiles.length === 0) return;
    const filesToSend = attachedFiles.slice();

    const clearComposerAttachments = () => {
        attachedFiles = [];
        const chipsEl = document.getElementById('ai-file-chips');
        if (chipsEl) {
            chipsEl.querySelectorAll('[data-object-url]').forEach((el) => {
                const url = el.getAttribute('data-object-url');
                if (url) URL.revokeObjectURL(url);
            });
            chipsEl.innerHTML = '';
        }
    };

    // Safety: initialize a default chat if user sends before one exists.
    if (!currentChatId && chats.length === 0 && typeof createNewChat === 'function') {
        createNewChat();
    }

    // Ensure popup is open
    if (mini) {
        mini.classList.add("open");
        mini.setAttribute("aria-hidden", "false");
    }

    // Collect context (same idea as your current code)
    const cells = Array.from(document.querySelectorAll(".code-editor, .text-editor"))
        .map((el) => (el.value !== undefined ? el.value : el.innerHTML));

    // Variables from Pyodide namespace (keeps your existing approach)
    let activeVars = [];
    if (pyodide) {
        try {
            const keys = pyodide.runPython("list(userns.keys())").toJs();
            activeVars = keys.filter(
                (k) =>
                    !k.startsWith("_") &&
                    !["pd", "np", "plt", "querydb"].includes(k)
            );
        } catch (e) {
            console.log("No vars yet");
        }
    }

    // UI: clear input immediately, add user message, and show assistant placeholder (chat style)
    input.value = "";
    if (typeof autoResize === "function") autoResize(input);

    // --- NEW: Convert Image Files and Data Files ---
    let base64Images = [];
    let uploadedTextFiles = []; // e.g. for CSV/JSON/TXT datasets
    let messageAttachments = [];

    // Process attached files before sending
    for (let file of filesToSend) {
        const ext = file.name.includes(".") ? file.name.split(".").pop().toUpperCase() : "FILE";
        if (file.type && file.type.startsWith('image/')) {
            const base64 = await new Promise((resolve) => {
                const reader = new FileReader();
                reader.onload = (e) => resolve(e.target.result);
                reader.readAsDataURL(file); // Generates data:image/png;base64,...
            });
            base64Images.push(base64);
            messageAttachments.push({ kind: "image", name: file.name, typeLabel: "Image", previewSrc: base64 });
        } else {
            // Read all files as base64 to support binary formats like pdf, docx, xlsx
            const base64Content = await new Promise((resolve) => {
                const reader = new FileReader();
                reader.onload = (e) => resolve(e.target.result);
                reader.readAsDataURL(file);
            });
            uploadedTextFiles.push({ filename: file.name, content: base64Content });
            messageAttachments.push({ kind: "file", name: file.name, typeLabel: ext });
        }
    }

    const startTime = Date.now();
    const timerEl = document.createElement('span');
    timerEl.style.cssText = "margin-left:auto;font-family:'Fira Code', monospace;font-size:0.85rem;color:#64748b;";
    timerEl.innerText = '0.0s';

    // Append user's message (float right, dynamic width up to 70% with word-wrap)
    const userBubble = document.createElement('div');
    userBubble.className = 'ai-msg user';
    userBubble.style.padding = '10px 12px'; // Shrunk padding
    userBubble.style.background = '#eef2ff';
    userBubble.style.borderRadius = '10px';
    userBubble.style.margin = '12px 0 12px auto'; // Tightened vertical margins
    userBubble.style.width = 'fit-content'; // shrink to content
    userBubble.style.maxWidth = '70%'; // but max 70% of container
    userBubble.style.wordWrap = 'break-word';
    userBubble.style.whiteSpace = 'pre-wrap';
    userBubble.style.overflowWrap = 'break-word';

    // Add text node when present
    if (prompt) userBubble.appendChild(document.createTextNode(prompt));

    // Add attachments under the sent message (images + files)
    if (messageAttachments.length > 0) {
        const attContainer = document.createElement('div');
        attContainer.className = 'ai-user-attachments';
        if (!prompt) attContainer.classList.add('no-text');

        messageAttachments.forEach((att) => {
            const attCard = document.createElement('div');
            attCard.className = 'ai-user-attachment';

            if (att.kind === 'image') {
                const thumb = document.createElement('img');
                thumb.className = 'ai-user-attachment-thumb';
                thumb.src = att.previewSrc;
                thumb.alt = att.name;
                attCard.appendChild(thumb);
            } else {
                const icon = document.createElement('span');
                icon.className = 'ai-user-attachment-icon';
                icon.textContent = (att.typeLabel || 'FILE').slice(0, 4);
                attCard.appendChild(icon);
            }

            const textWrap = document.createElement('div');
            textWrap.className = 'ai-user-attachment-text';

            const name = document.createElement('span');
            name.className = 'ai-user-attachment-name';
            name.textContent = att.name;
            name.title = att.name;

            const meta = document.createElement('span');
            meta.className = 'ai-user-attachment-meta';
            meta.textContent = att.typeLabel || 'File';

            textWrap.appendChild(name);
            textWrap.appendChild(meta);
            attCard.appendChild(textWrap);
            attContainer.appendChild(attCard);
        });

        userBubble.appendChild(attContainer);
    }

    contentArea.appendChild(userBubble);
    clearComposerAttachments();

    // Add edit button immediately to user message
    const messageIndex = messagePairs.length;
    messagePairs.push({ userBubble, assistantBubble: null, prompt }); // Add placeholder for assistant
    addEditButton(userBubble, prompt, messageIndex);

    // Assistant placeholder
    const assistantBubble = document.createElement('div');
    assistantBubble.className = 'ai-msg assistant';
    assistantBubble.style.padding = '12px 10px 12px 16px'; // Reduced padding
    assistantBubble.style.background = '#ffffff';
    assistantBubble.style.border = '1px solid #e6edf3';
    assistantBubble.style.borderRadius = '10px';
    assistantBubble.style.margin = '6px 0'; // Tightened vertical margins
    assistantBubble.innerHTML = `<div style="display:flex;align-items:center;gap:10px;"><span class="pulse-icon"></span><strong>Assistant</strong></div><div style="margin-top:8px;color:#64748b;">Generating response... </div>`;
    // add timer to the header
    assistantBubble.querySelector('div').appendChild(timerEl);
    contentArea.appendChild(assistantBubble);

    // IMPORTANT: Update messagePair with assistantBubble immediately so it can be removed if user clicks edit
    messagePairs[messageIndex].assistantBubble = assistantBubble;

    // Auto-scroll
    if (tray) tray.scrollTop = tray.scrollHeight;

    const timerInt = setInterval(() => {
        timerEl.innerText = ((Date.now() - startTime) / 1000).toFixed(1) + 's';
    }, 100);

    try {
        // IMPORTANT: keep the SAME endpoint string you used earlier.
        // If your old code had fetch("/query"...), use "/query". If it had fetch("query"...), use "query".
        const endpoint = "query";

        // Create abort controller for this request
        currentAbortController = new AbortController();
        setAILoading(true);

        const useDbContext = document.getElementById('ai-use-db-toggle') ? document.getElementById('ai-use-db-toggle').checked : false;

        let reqPayload = {
            prompt: prompt,
            notebook_cells: cells,
            variables: activeVars,
            chat_history: chatHistory,
            images: base64Images,
            datasets: uploadedTextFiles,
            use_db_context: useDbContext
        };

        const pL = prompt.toLowerCase();
        if (pL.includes("fix") || pL.includes("update") || pL.includes("change") || pL.includes("modify")) {
            reqPayload.is_modification = true;
            reqPayload.active_cell_id = lastActiveCellId ? String(lastActiveCellId) : null;
            if (lastActiveCellId) {
                const ce = document.querySelector(`#cell-${lastActiveCellId} .code-editor`);
                if (ce) {
                    if (ce.nextSibling && ce.nextSibling.classList && ce.nextSibling.classList.contains('CodeMirror')) {
                        reqPayload.original_code = ce.nextSibling.CodeMirror.getValue();
                    } else {
                        reqPayload.original_code = ce.value;
                    }
                }
            }
        }

        const resp = await fetch(endpoint, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(reqPayload),
            signal: currentAbortController.signal,
        });

        if (!resp.ok) throw new Error("Server Error");

        const data = await resp.json();
        clearInterval(timerInt);

        const totalTime = ((Date.now() - startTime) / 1000).toFixed(2);
        const toolUsed = data.tool_used || ""; // Get the intent/tool used

        let answer = data.answer || "";

        if (data.action === "UPDATE_CELL" && data.modified_code) {
            updateLastActiveCell(data.cell_id, data.modified_code);
        }

        // Title: set once from FIRST user message only.
        if (currentChatId && typeof updateChatTitleFromFirstUserMessage === 'function') {
            updateChatTitleFromFirstUserMessage(currentChatId, prompt);
        }

        // Update history
        chatHistory.push({ role: "user", content: prompt, images: base64Images.length > 0 ? base64Images : undefined });
        chatHistory.push({ role: "assistant", content: answer });

        let codeNode = null;
        const originalAnswer = answer;

        // Show proposal controls only for generate intents with python code blocks
        const isGenerateIntent = toolUsed.toUpperCase().includes("GENERATE");

        const codeMatch = originalAnswer.match(/```python([\s\S]*?)```/);
        if (codeMatch && isGenerateIntent) {
            const code = codeMatch[1].trim();
            if (!showCode) {
                answer = stripCodeBlocks(originalAnswer);
                codeNode = null;
            } else {
                answer = originalAnswer.replace(codeMatch[0], "").trim();
                codeNode = stageCodeProposalUI(code, prompt);
            }
        } else if (codeMatch && !isGenerateIntent) {
            answer = stripCodeBlocks(originalAnswer);
            codeNode = null;
        } else {
            if (!showCode) answer = stripCodeBlocks(answer);
        }

        // Render assistant response into existing assistantBubble
        assistantBubble.innerHTML = '';
        const header = document.createElement('div');
        header.style.display = 'flex';
        header.style.justifyContent = 'space-between';
        header.style.alignItems = 'center';
        header.style.marginBottom = '6px'; // Tighter
        const title = document.createElement('strong');
        title.innerText = 'Assistant';
        const timeLabel = document.createElement('span');
        timeLabel.style.color = '#888';
        timeLabel.style.fontSize = '0.7rem'; // Smaller
        timeLabel.innerText = `Took ${totalTime}s`;
        header.appendChild(title);
        header.appendChild(timeLabel);

        const body = document.createElement('div');
        body.style.fontSize = '0.88rem'; // Shrunk from 0.95rem
        body.style.lineHeight = '1.5';
        // Convert markdown to HTML if marked is available, and sanitize
        if (typeof marked !== 'undefined' && typeof DOMPurify !== 'undefined') {
            body.innerHTML = DOMPurify.sanitize(marked.parse(answer || ''));
        } else {
            body.innerText = answer;
        }

        assistantBubble.appendChild(header);
        assistantBubble.appendChild(body);
        if (codeNode) assistantBubble.appendChild(codeNode);

        if (tray) tray.scrollTop = tray.scrollHeight;

        // Ensure composer is fresh after successful send
        clearComposerAttachments();
    } catch (e) {
        clearInterval(timerInt);
        if (e.name === 'AbortError') {
            // User cancelled - update the assistant bubble
            assistantBubble.innerHTML = `<div style="display:flex;align-items:center;gap:10px;"><strong>Assistant</strong></div><div style="margin-top:8px;color:#94a3b8;font-style:italic;">Response cancelled.</div>`;
        } else {
            contentArea.innerHTML = `<p style="color:red;padding:15px;">Error: ${e.message}</p>`;
        }
    } finally {
        currentAbortController = null;
        setAILoading(false);
    }
}


function updateMaximizeButton(maxBtn, isDocked) {
    if (!maxBtn) return;

    if (isDocked) {
        // Show minimize icon
        maxBtn.innerHTML = ICON_MINIMIZE;
        maxBtn.setAttribute("aria-label", "Minimize");
        maxBtn.setAttribute("title", "Minimize");
    } else {
        // Show maximize icon
        maxBtn.innerHTML = ICON_MAXIMIZE;
        maxBtn.setAttribute("aria-label", "Maximize");
        maxBtn.setAttribute("title", "Maximize");
    }
}

function initAIWidget() {
    const fab = document.getElementById("ai-fab");
    const mini = document.getElementById("ai-mini");
    const closeBtn = document.getElementById("ai-mini-close");
    const maxBtn = document.getElementById("ai-mini-max");
    const input = document.getElementById("prompt-input");
    const sendBtn = document.getElementById("run-btn");
    const resizeHandle = document.querySelector(".ai-resize-handle");

    if (!fab || !mini) return;

    // Resize state
    let isResizing = false;
    let startX = 0;
    let startWidth = 450;

    // Restore saved width from localStorage
    const savedWidth = localStorage.getItem('ai-panel-width');
    if (savedWidth) {
        mini.style.setProperty('--ai-panel-width', savedWidth);
    }

    // State: whether popup is open and last used popup mode
    let isOpen = mini.classList.contains('open');
    let popupMode = localStorage.getItem('ai-popup-mode') || 'min';

    const setOpen = (open) => {
        if (!open) {
            // Save current mode (min or max) before closing but do not reset it
            const currentMode = mini.classList.contains("docked") ? 'max' : 'min';
            popupMode = currentMode;
            localStorage.setItem('ai-popup-mode', popupMode);
            isOpen = false;

            // Kill transition so it vanishes instantly
            mini.style.transition = 'none';
            // remove visual classes (panel closed)
            mini.classList.remove("open");
            mini.classList.remove("docked");
            mini.setAttribute("aria-hidden", "true");
            const content = document.querySelector(".content");
            if (content) {
                content.style.transition = 'none';
                content.classList.remove("ai-docked");
                content.style.setProperty('--ai-panel-width', '');
                content.style.marginRight = '';
                // Force a layout reflow to ensure immediate visual update when closing
                content.offsetHeight; // Trigger reflow
            }
            // Re-enable transitions after a frame for future opens
            requestAnimationFrame(() => {
                mini.style.transition = '';
                if (content) content.style.transition = '';
            });
            return;
        }

        // Opening - re-read popupMode from localStorage to support dynamic mode changes
        popupMode = localStorage.getItem('ai-popup-mode') || 'min';
        isOpen = true;
        mini.classList.add("open");
        mini.setAttribute("aria-hidden", "false");

        // Restore to maximized (docked) mode if it was previously
        if (popupMode === 'max') {
            mini.classList.add("docked");
            // Update button to show minimize icon
            updateMaximizeButton(maxBtn, true);
            const content = document.querySelector(".content");
            if (content) {
                const currentWidth = mini.style.getPropertyValue('--ai-panel-width') || '450px';
                // Disable transitions for instant layout change
                content.style.transition = 'none';
                content.classList.add("ai-docked");
                // Set both inline style and CSS custom property for consistency
                content.style.setProperty('--ai-panel-width', currentWidth);
                content.style.marginRight = currentWidth;
                // Force a layout reflow to ensure immediate visual update
                content.offsetHeight; // Trigger reflow
                // Re-enable transitions after the change
                requestAnimationFrame(() => {
                    content.style.transition = '';
                });
            }
        } else {
            // ensure undocked when opening in min mode
            mini.classList.remove("docked");
            // Update button to show maximize icon
            updateMaximizeButton(maxBtn, false);
        }

        if (input) input.focus();
    };

    fab.addEventListener("click", () => {
        // Initialize one default chat for this notebook on first FAB click only
        // (based on actual chat count, not transient click state)
        if (chats.length === 0) {
            try {
                localStorage.setItem(`chat_initialized_${currentNotebookId}`, '1');
            } catch (e) {
                console.warn('Failed to persist chat init flag:', e);
            }
            createNewChat(); // opens popup and creates the first chat
            return;
        }
        setOpen(!isOpen);
    });
    if (closeBtn) closeBtn.addEventListener("click", () => setOpen(false));

    if (maxBtn) {
        maxBtn.addEventListener("click", () => {
            // Toggle docked state instead of expanded
            const isDocked = mini.classList.toggle("docked");

            // Update button icon and label
            updateMaximizeButton(maxBtn, isDocked);

            // Save the new mode to state and localStorage
            popupMode = isDocked ? 'max' : 'min';
            localStorage.setItem('ai-popup-mode', popupMode);

            // Adjust main content margin
            const content = document.querySelector(".content");
            if (content) {
                // Disable transitions for instant layout change
                content.style.transition = 'none';

                if (isDocked) {
                    // Use saved width or default
                    const currentWidth = mini.style.getPropertyValue('--ai-panel-width') || '450px';
                    content.classList.add("ai-docked");
                    // Set both inline style and CSS custom property for consistency
                    content.style.setProperty('--ai-panel-width', currentWidth);
                    content.style.marginRight = currentWidth;
                } else {
                    content.classList.remove("ai-docked");
                    content.style.setProperty('--ai-panel-width', '');
                    content.style.marginRight = '';
                }

                // Force a layout reflow to ensure immediate visual update
                // This is necessary because we disabled transitions
                content.offsetHeight; // Trigger reflow

                // Re-enable transitions after the change
                requestAnimationFrame(() => {
                    content.style.transition = '';
                });
            }

            // Keep focus on input
            if (input) input.focus();
        });
    }

    // Resize functionality
    if (resizeHandle) {
        resizeHandle.addEventListener("mousedown", (e) => {
            isResizing = true;
            startX = e.clientX;
            startWidth = mini.offsetWidth;
            document.body.style.cursor = "col-resize";
            document.body.style.userSelect = "none";
            // Disable transitions for instant resize
            mini.style.transition = "none";
            const content = document.querySelector(".content");
            if (content) content.style.transition = "none";
            e.preventDefault();
        });
    }

    document.addEventListener("mousemove", (e) => {
        if (!isResizing) return;

        // Calculate new width (dragging left increases width, dragging right decreases)
        const deltaX = startX - e.clientX;
        const newWidth = Math.min(Math.max(startWidth + deltaX, 400), 800);

        // Update panel width using CSS custom property
        mini.style.setProperty("--ai-panel-width", newWidth + "px");

        // Update content margin to match
        const content = document.querySelector(".content");
        if (content && mini.classList.contains("docked")) {
            // Set both inline style and CSS custom property for consistency
            content.style.setProperty("--ai-panel-width", newWidth + "px");
            content.style.marginRight = newWidth + "px";
        }
    });

    document.addEventListener("mouseup", () => {
        if (isResizing) {
            isResizing = false;
            document.body.style.cursor = "";
            document.body.style.userSelect = "";
            // Re-enable transitions
            mini.style.transition = "";
            const content = document.querySelector(".content");
            if (content) content.style.transition = "";

            // Save width to localStorage
            const width = mini.style.getPropertyValue("--ai-panel-width");
            if (width) {
                localStorage.setItem("ai-panel-width", width);
            }
        }
    });

    if (sendBtn) sendBtn.addEventListener("click", runAIQuery);

    // --- File Upload ---
    const attachBtn = document.getElementById("ai-attach-btn");
    const fileInput = document.getElementById("ai-file-input");
    const fileChips = document.getElementById("ai-file-chips");

    if (attachBtn && fileInput) {
        attachBtn.addEventListener("click", () => fileInput.click());

        fileInput.addEventListener("change", () => {
            const files = Array.from(fileInput.files);
            files.forEach((file) => {
                attachedFiles.push(file);
                renderFileChip(file, fileChips);
            });
            fileInput.value = ""; // Reset so same file can be re-selected
        });
    }

    function renderFileChip(file, container) {
        if (!container) return;

        const isImage = file.type && file.type.startsWith("image/");
        const ext = file.name.includes(".") ? file.name.split(".").pop().toUpperCase() : "FILE";
        const typeLabel = isImage ? "Image" : ext;

        const chip = document.createElement("div");
        chip.className = "ai-file-chip";
        chip.title = file.name;

        if (isImage) {
            const thumb = document.createElement("img");
            const objectUrl = URL.createObjectURL(file);
            thumb.src = objectUrl;
            thumb.alt = file.name;
            thumb.className = "ai-file-thumb";
            thumb.setAttribute("data-object-url", objectUrl);
            chip.appendChild(thumb);
        } else {
            const icon = document.createElement("span");
            icon.className = "ai-file-icon";
            icon.textContent = ext.length > 4 ? ext.slice(0, 4) : ext;
            chip.appendChild(icon);
        }

        const textWrap = document.createElement("div");
        textWrap.className = "ai-file-text";

        const nameSpan = document.createElement("span");
        nameSpan.className = "ai-file-name";
        nameSpan.textContent = file.name;
        nameSpan.title = file.name;

        const metaSpan = document.createElement("span");
        metaSpan.className = "ai-file-meta";
        metaSpan.textContent = typeLabel;

        textWrap.appendChild(nameSpan);
        textWrap.appendChild(metaSpan);

        const removeBtn = document.createElement("button");
        removeBtn.className = "ai-file-remove";
        removeBtn.type = "button";
        removeBtn.title = "Remove";
        removeBtn.setAttribute("aria-label", `Remove ${file.name}`);
        removeBtn.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"><path d="M18 6 6 18"></path><path d="M6 6 18 18"></path></svg>`;
        removeBtn.addEventListener("click", () => {
            const preview = chip.querySelector('[data-object-url]');
            if (preview) {
                const url = preview.getAttribute('data-object-url');
                if (url) URL.revokeObjectURL(url);
            }
            attachedFiles = attachedFiles.filter((f) => f !== file);
            chip.remove();
        });

        chip.appendChild(textWrap);
        chip.appendChild(removeBtn);
        container.appendChild(chip);
    }

    // --- Microphone (Web Speech API) ---
    const micBtn = document.getElementById("ai-mic-btn");
    let recognition = null;

    if (micBtn && ("webkitSpeechRecognition" in window || "SpeechRecognition" in window)) {
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        recognition = new SpeechRecognition();
        recognition.lang = "en-US";
        recognition.continuous = false;
        recognition.interimResults = true;

        micBtn.addEventListener("click", () => {
            if (micBtn.classList.contains("recording")) {
                recognition.stop();
                micBtn.classList.remove("recording");
            } else {
                recognition.start();
                micBtn.classList.add("recording");
            }
        });

        recognition.onresult = (event) => {
            let transcript = "";
            for (let i = event.resultIndex; i < event.results.length; i++) {
                transcript += event.results[i][0].transcript;
            }
            if (input) {
                input.value = transcript;
                input.style.height = "auto";
                input.style.height = Math.min(input.scrollHeight, 140) + "px";
            }
        };

        recognition.onend = () => {
            micBtn.classList.remove("recording");
        };

        recognition.onerror = () => {
            micBtn.classList.remove("recording");
        };
    }

    // --- Enter to Send, Shift+Enter for newline ---
    if (input) {
        input.addEventListener("keydown", (e) => {
            if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                runAIQuery();
            }
        });
    }

    // Auto-grow textarea
    if (input) {
        input.addEventListener("input", () => {
            input.style.height = "auto";
            input.style.height = Math.min(input.scrollHeight, 140) + "px";
        });
    }

    // ESC closes
    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape") setOpen(false);
    });
}

// ==========================================
// AI POPUP MODE HELPERS
// ==========================================

/**
 * Opens AI popup in minimized mode
 */
function openAIPopupMinimized() {
    localStorage.setItem('ai-popup-mode', 'min');
    const fab = document.getElementById('ai-fab');
    if (fab) fab.click();
}

/**
 * Opens AI popup in maximized mode
 */
function openAIPopupMaximized() {
    localStorage.setItem('ai-popup-mode', 'max');
    const fab = document.getElementById('ai-fab');
    if (fab) fab.click();
}

/**
 * Opens AI popup in a specific mode ('min' or 'max')
 */
function openAIPopupWithMode(mode) {
    if (mode === 'min' || mode === 'max') {
        localStorage.setItem('ai-popup-mode', mode);
    }
    const fab = document.getElementById('ai-fab');
    if (fab) fab.click();
}

// Add these helper functions to script.js
function toggleAITray() {
    const tray = document.getElementById('ai-response-tray');
    const btn = document.getElementById('tray-toggle-btn');
    const isMin = tray.classList.toggle('minimized');
    btn.innerHTML = isMin ? ICON_MAXIMIZE : ICON_MINIMIZE;
}

// Drawer management functions
// Drawer management functions
function toggleDrawer(drawerName) {
    const drawer = document.getElementById(`drawer-${drawerName}`);
    if (!drawer) return;

    const isOpen = drawer.classList.contains('open');

    // Close all other drawers
    document.querySelectorAll('.drawer').forEach(d => {
        d.classList.remove('open');
    });

    // Toggle the clicked drawer
    if (!isOpen) {
        drawer.classList.add('open');
        document.querySelector('.content').classList.add('drawer-open');

        // Load appropriate content based on drawer type
        if (drawerName === 'saved' && typeof loadSavedNotebooks === 'function') {
            loadSavedNotebooks();
        } else if (drawerName === 'history' && typeof loadHistory === 'function') {
            loadHistory();
        }
    } else {
        document.querySelector('.content').classList.remove('drawer-open');
    }
}

function closeDrawer(drawerName) {
    const drawer = document.getElementById(`drawer-${drawerName}`);
    if (drawer) {
        drawer.classList.remove('open');
        document.querySelector('.content').classList.remove('drawer-open');
    }
}

// --- 4. TABS & DB (Preserved) ---
function switchTab(view) {
    const workspaceView = document.getElementById("workspace-view");
    const connectionsView = document.getElementById("connections-view");

    // NEW: your floating AI widget wrapper
    const aiWidget = document.getElementById("ai-widget");
    const aiMini = document.getElementById("ai-mini");

    // Update active nav item
    document.querySelectorAll(".nav-item").forEach((el) => el.classList.remove("active"));
    document.getElementById(`nav-${view}`)?.classList.add("active");

    // Hide all views
    if (workspaceView) workspaceView.style.display = "none";
    if (connectionsView) connectionsView.style.display = "none";

    // Default: hide AI on non-workspace screens
    if (aiWidget) aiWidget.style.display = "none";
    if (aiMini) aiMini.classList.remove("open");

    switch (view) {
        case "connections":
            if (connectionsView) connectionsView.style.display = "flex";
            loadConnections?.();
            loadVectorMemory?.();
            break;

        default: // "workspace" 
            if (workspaceView) workspaceView.style.display = "flex";
            if (aiWidget) aiWidget.style.display = "block";
            break;
    }
}

async function loadConnections() {
    const list = document.getElementById('connection-list');
    if (!list) return;

    // Fetch fresh data
    const resp = await fetch('/api/connections', {
        cache: 'no-store',
        headers: { 'Cache-Control': 'no-cache', 'Pragma': 'no-cache' }
    });
    const configs = await resp.json();

    const trash = `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>`;

    // Build new HTML off-screen as a string (avoids multiple repaints)
    currentConfigs = configs;
    const entries = Object.entries(configs).filter(([k]) => k !== 'detail');
    const providerInitials = {
        postgresql: 'PG',
        mysql: 'MY',
        mssql: 'MS',
        oracle: 'OR',
        sqlite: 'SQ',
        jdbc: 'JD'
    };
    const inferProvider = (conf = {}, name = '') => {
        const direct = String(conf.provider || conf.db_type || conf.database_type || '').toLowerCase();
        if (direct) return direct;

        const probe = [
            conf.url,
            conf.driver_class,
            conf.host,
            conf.database,
            conf.user,
            name
        ].filter(Boolean).join(' ').toLowerCase();

        if (probe.includes('postgres')) return 'postgresql';
        if (probe.includes('mysql')) return 'mysql';
        if (probe.includes('mssql') || probe.includes('sql server') || probe.includes('sqlserver')) return 'mssql';
        if (probe.includes('oracle')) return 'oracle';
        if (probe.includes('sqlite')) return 'sqlite';
        if (probe.includes('jdbc')) return 'jdbc';
        if (probe.includes('_post') || probe.includes('-post') || probe.includes(' post ')) return 'postgresql';
        return '';
    };
    const inferredProviders = entries.map(([name, conf]) => inferProvider(conf, name)).filter(Boolean);
    const defaultProvider = inferredProviders[0] || '';
    const html = entries.map(([name, conf]) => `
        <div class="conn-item table-card conn-card ${conf.active ? 'active indexed' : ''}" style="transition:opacity 0.15s ease;">
            <div class="table-card-main">
                <div class="table-card-icon">${providerInitials[inferProvider(conf, name) || defaultProvider] || 'DB'}</div>
                <div class="table-card-meta">
                    <span class="conn-item-label table-card-name" onclick="switchConnection('${name.replace(/'/g, "\\'")}')">${name}</span>
                    <div class="table-card-status ${conf.active ? 'indexed' : ''}">
                        ${conf.active ? 'Active connection' : 'Available connection'}
                    </div>
                </div>
            </div>
            <div class="conn-item-actions table-card-actions multiple">
                <button class="refresh-db-btn" title="Refresh connection" onclick="refreshDB(event, '${name.replace(/'/g, "\\'")}')">
                    ${ICON_REFRESH.replace('width="24"', 'width="16"').replace('height="24"', 'height="16"')}
                </button>
                <button class="edit-db-btn" title="Edit details" onclick="openEditConnectionForm(event, '${name.replace(/'/g, "\\'")}')">
                    ${ICON_EDIT.replace('width="24"', 'width="16"').replace('height="24"', 'height="16"')}
                </button>
                <button class="delete-db-btn" title="Delete connection" onclick="deleteDB(event, '${name.replace(/'/g, "\\'")}')">${trash}</button>
            </div>
        </div>
    `).join('');

    // Single DOM write — no intermediate blank state
    list.style.opacity = '0';
    list.innerHTML = html || '<div class="connection-list-empty">No connections yet.</div>';
    requestAnimationFrame(() => { list.style.transition = 'opacity 0.2s'; list.style.opacity = '1'; });

    // Load tables once, after connections are rendered
    loadTables();
}

async function deleteDB(event, name) {
    event.stopPropagation();
    const deleteBtn = event.currentTarget || event.target.closest('button');

    if (!await customConfirm(`Are you sure you want to delete "${name}"?`, true)) {
        return;
    }

    const connItem = event.target.closest('.conn-item');
    if (deleteBtn) {
        deleteBtn.disabled = true;
        deleteBtn.style.opacity = '0.6';
    }

    try {
        const resp = await fetch(`/api/connections/${encodeURIComponent(name)}`, {
            method: 'DELETE'
        });

        if (!resp.ok) {
            const error = await resp.json();
            showToast('Failed to delete: ' + (error.detail || 'Unknown error'), 'error');
            return;
        }

        const result = await resp.json();
        if (result.status === 'deleted') {
            // Remove from DOM after animation finishes
            setTimeout(() => connItem?.remove(), 160);
            showToast(`"${name}" removed.`, 'info', 2500);
            // Only reload tables (the connection row is already gone)
            loadTables({ preserve: true });
        }

    } catch (error) {
        showToast('Failed to delete: ' + error.message, 'error');
    } finally {
        if (deleteBtn) {
            deleteBtn.disabled = false;
            deleteBtn.style.opacity = '1';
        }
    }
}

async function refreshDB(event, name) {
    event.stopPropagation();

    const refreshBtn = event.currentTarget;
    const svgIcon = refreshBtn.querySelector('svg');
    if (svgIcon) svgIcon.style.animation = "spin 1s linear infinite";

    try {
        const resp = await fetch('/api/connections/activate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name })
        });

        const result = await resp.json();

        if (!resp.ok) {
            showToast(`Failed to refresh "${name}": ${result.detail || 'Unknown error'}`, 'error', 5000);
        } else if (result.status === 'activated' || result.active === true || !result.error) {
            showToast(`✅ "${name}" connection refreshed`, 'success');
            loadConnections(); // Reload list to update active state if it was broken
        } else {
            showToast(`⚠️ Refresh failed: ${result.error}`, 'warning', 6000);
        }
    } catch (error) {
        showToast(`Failed to refresh: ${error.message}`, 'error');
    } finally {
        if (svgIcon) svgIcon.style.animation = "none";
    }
}

function openNewConnectionForm() {
    const formEl = document.getElementById('conn-form');
    if (formEl.style.display === 'flex' && document.getElementById('save-conn-btn').textContent === "Connect & Save") {
        closeConnForm();
        return;
    }

    document.getElementById('save-conn-btn').textContent = "Connect & Save";
    document.getElementById('db-alias').value = '';
    document.getElementById('db-url').value = '';
    document.getElementById('db-user').value = '';
    document.getElementById('db-pass').value = '';
    document.getElementById('db-extra-config').value = '{}';
    document.getElementById('db-is-jndi').checked = false;
    document.getElementById('db-driver-class').value = '';
    document.getElementById('db-wait-time').value = 30;
    document.getElementById('conn-form').style.display = 'flex';
}

function openEditConnectionForm(event, name) {
    if (event) event.stopPropagation();

    const formEl = document.getElementById('conn-form');
    if (formEl.style.display === 'flex' &&
        document.getElementById('save-conn-btn').textContent === "Update & Connect" &&
        document.getElementById('db-alias').value === name) {
        closeConnForm();
        return;
    }

    const conf = currentConfigs[name];
    if (!conf) return;

    document.getElementById('save-conn-btn').textContent = "Update & Connect";
    document.getElementById('db-alias').value = name;
    document.getElementById('db-provider').value = conf.provider || 'postgresql';
    document.getElementById('db-url').value = conf.url || '';
    document.getElementById('db-user').value = conf.user || '';
    document.getElementById('db-pass').value = conf.password || '';
    document.getElementById('db-extra-config').value = JSON.stringify(conf.extra_config || {}, null, 2);
    document.getElementById('db-is-jndi').checked = !!conf.is_jndi;
    document.getElementById('db-driver-class').value = conf.driver_class || '';
    document.getElementById('db-wait-time').value = conf.wait_time || 30;

    onProviderChange();
    document.getElementById('conn-form').style.display = 'flex';
}

function closeConnForm() {
    document.getElementById('conn-form').style.display = 'none';
}

// ── Helpers for the new connection form ───────────────────────────
function adjustWaitTime(delta) {
    const el = document.getElementById('db-wait-time');
    if (!el) return;
    const next = Math.min(300, Math.max(5, (parseInt(el.value) || 30) + delta));
    el.value = next;
}

function onProviderChange() {
    const provider = document.getElementById('db-provider')?.value;
    const hintEl = document.getElementById('db-url-hint');
    const driverRow = document.getElementById('db-driver-row');
    const driverInput = document.getElementById('db-driver-class');
    const hints = {
        postgresql: 'postgresql://user:password@host:5432/dbname',
        mysql: 'mysql+pymysql://user:password@host:3306/dbname',
        mssql: 'mssql+pyodbc://user:password@host:1433/dbname',
        oracle: 'oracle+cx_oracle://user:password@host:1521/SID',
        sqlite: 'sqlite:///path/to/database.db',
        jdbc: 'jdbc:database://host:port/dbname',
    };
    const drivers = {
        mysql: 'com.mysql.jdbc.Driver',
        mssql: 'com.microsoft.sqlserver.jdbc.SQLServerDriver',
        oracle: 'oracle.jdbc.driver.OracleDriver',
        postgresql: 'org.postgresql.Driver',
        jdbc: 'com.your.jdbc.Driver',
    };
    if (hintEl) hintEl.textContent = hints[provider] ? `Example: ${hints[provider]}` : '';
    if (driverInput && drivers[provider]) driverInput.placeholder = drivers[provider];
    if (driverRow) driverRow.style.display = ['postgresql', 'sqlite'].includes(provider) ? 'none' : 'block';
}

function onJndiChange() {
    // Styling handled automatically by the .toggle-switch-db CSS now! No JS slider paint needed.
}

// ── Main save function ─────────────────────────────────────────────
async function saveNewConnection() {
    const name = document.getElementById('db-alias')?.value.trim();
    if (!name) { showToast('Please enter a display name.', 'warning'); return; }

    const url = document.getElementById('db-url')?.value.trim();
    if (!url) { showToast('Please enter a Connection URL.', 'warning'); return; }

    let extraConfig = {};
    try {
        const raw = document.getElementById('db-extra-config')?.value.trim() || '{}';
        extraConfig = JSON.parse(raw);
    } catch {
        showToast('Extra Configuration is not valid JSON.', 'error', 5000);
        return;
    }

    const data = {
        name,
        provider: document.getElementById('db-provider')?.value || 'postgresql',
        url,
        user: document.getElementById('db-user')?.value.trim() || '',
        password: document.getElementById('db-pass')?.value || '',
        wait_time: parseInt(document.getElementById('db-wait-time')?.value) || 30,
        is_jndi: document.getElementById('db-is-jndi')?.checked || false,
        driver_class: document.getElementById('db-driver-class')?.value.trim() || '',
        extra_config: extraConfig,
    };

    try {
        showToast(`Connecting to "${name}"...`, 'info', 6000);
        const resp = await fetch('/api/connections', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        const result = await resp.json();
        if (!resp.ok) { showToast(`❌ Failed: ${result.detail || 'Connection error'}`, 'error', 6000); return; }
        if (result.status === 'saved' || result.active === true) {
            showToast(`✅ "${name}" connected successfully!`, 'success');
        } else {
            showToast(`⚠️ Saved "${name}" but could not activate. Check your Connection URL.`, 'warning', 6000);
        }
        closeConnForm();
        loadConnections();
    } catch (e) {
        showToast(`Connection failed: ${e.message}`, 'error', 6000);
    }
}

async function switchConnection(name) {
    try {
        showToast(`Switching to "${name}"...`, 'info', 3000);

        const resp = await fetch('/api/connections/activate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name })
        });

        const result = await resp.json();

        if (!resp.ok) {
            showToast(`Failed to activate "${name}": ${result.detail || 'Unknown error'}`, 'error', 5000);
        } else if (result.status === 'activated' || result.active === true) {
            showToast(`✅ Now using "${name}"`, 'success');
        } else if (result.error) {
            showToast(`⚠️ "${name}" selected but connection failed: ${result.error}`, 'warning', 6000);
        } else {
            showToast(`Switched to "${name}"`, 'success');
        }

        loadConnections();
    } catch (e) {
        showToast(`Switch failed: ${e.message}`, 'error', 5000);
    }
}

async function loadTables(options = {}) {
    const tableList = document.getElementById('tables-list');
    if (!tableList) return;
    const preserve = options.preserve === true;
    const hasRendered = tableList.dataset.rendered === '1';
    if (!preserve || !hasRendered) {
        tableList.innerHTML = 'Loading tables...';
    } else {
        tableList.classList.add('is-updating');
    }
    try {
        // Fetch tables list AND currently indexed RAG sources simultaneously
        const [tablesResp, ragResp] = await Promise.all([
            fetch('/api/tables'),
            fetch('/api/vector_memory')
        ]);
        const tablesData = await tablesResp.json();
        const ragData = await ragResp.json();

        if (!tablesData.tables || tablesData.tables.length === 0) {
            tableList.innerHTML = 'No active connection or tables found.';
            tableList.dataset.rendered = '1';
            tableList.classList.remove('is-updating');
            return;
        }

        // Build a Set of already-indexed source names for O(1) lookup
        const indexedSources = new Set(ragData.sources || []);

        tableList.innerHTML = `
            <div class="tables-helper-note">Click <strong>+ RAG</strong> to index a table into AI memory.</div>
            <div class="table-card-grid">${tablesData.tables.map(tbl => {
            const isIndexed = indexedSources.has(tbl);
            const isLoading = inflightTableActions.has(tbl);
            return `
                <div class="table-card ${isIndexed ? 'indexed' : ''}">
                    <div class="table-card-main">
                        <div class="table-card-icon">${isIndexed ? 'AI' : 'DB'}</div>
                        <div class="table-card-meta">
                            <div class="table-card-name">${tbl}</div>
                            <div class="table-card-status ${isIndexed ? 'indexed' : ''}">
                                ${isIndexed ? 'Indexed in RAG' : 'Not Indexed in RAG'}
                            </div>
                        </div>
                    </div>
                    <div class="table-card-actions">
                        <button class="table-action-btn ${isIndexed ? 'secondary' : 'primary'} ${isLoading ? 'is-loading' : ''}" ${isLoading ? 'disabled' : ''} onclick="indexTable('${tbl}', event)">
                            ${isIndexed ? 'Re-index' : '+ RAG'}
                        </button>
                    </div>
                </div>`;
        }).join('')}</div>`;
        tableList.dataset.rendered = '1';
        tableList.classList.remove('is-updating');
    } catch (err) {
        if (!hasRendered) {
            tableList.innerHTML = 'Error loading tables.';
        }
        tableList.classList.remove('is-updating');
    }
}

async function indexTable(tableName, event) {
    const btn = event.target.closest('button');
    if (!btn) return;

    if (inflightTableActions.has(tableName)) return;
    btn.disabled = true;
    btn.classList.add('is-loading');
    inflightTableActions.add(tableName);

    try {
        if (activeRagIndexToast) dismissToast(activeRagIndexToast);
        activeRagIndexToast = showToast(`Indexing "${tableName}" into RAG memory...`, 'info', 0);

        const resp = await fetch('/api/index_table', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ table_name: tableName })
        });
        const result = await resp.json();
        if (resp.ok) {
            // Use the same completion polling path for +RAG and Re-index.
            await pollUntilActionComplete((state) => state.sources.includes(tableName), { intervalMs: 2500 });
            inflightTableActions.delete(tableName);
            btn.disabled = false;
            btn.classList.remove('is-loading');
            await loadTables({ preserve: true });

            if (activeRagIndexToast) {
                dismissToast(activeRagIndexToast);
                activeRagIndexToast = null;
            }
            showToast(`"${tableName}" indexed into RAG.`, 'success', 3000);
            return;
        } else {
            throw new Error(result.message || 'Failed');
        }
    } catch (err) {
        if (activeRagIndexToast) {
            dismissToast(activeRagIndexToast);
            activeRagIndexToast = null;
        }
        showToast(`Failed to index "${tableName}": ${err.message}`, 'error', 6000);
    } finally {
        if (inflightTableActions.has(tableName)) {
            inflightTableActions.delete(tableName);
            btn.disabled = false;
            btn.classList.remove('is-loading');
            await loadTables({ preserve: true });
        }
    }
}

async function loadVectorMemory(options = {}) {
    const memoryList = document.getElementById('vector-memory-list');
    if (!memoryList) return;
    const preserve = options.preserve === true;
    const hasRendered = memoryList.dataset.rendered === '1';
    if (!preserve || !hasRendered) {
        memoryList.innerHTML = 'Loading memory...';
    } else {
        memoryList.classList.add('is-updating');
    }
    try {
        const resp = await fetch('/api/vector_memory');
        const data = await resp.json();
        if (!data.sources || data.sources.length === 0) {
            memoryList.innerHTML = 'No data currently indexed.';
            memoryList.dataset.rendered = '1';
            memoryList.classList.remove('is-updating');
            return;
        }
        memoryList.innerHTML = `
            <div class="table-card-grid memory-card-grid">${data.sources.map(src => `
                <div class="table-card memory-card">
                    <div class="table-card-main">
                        <div class="table-card-icon">AI</div>
                        <div class="table-card-meta">
                            <div class="table-card-name memory-card-name" title="${src}">${src}</div>
                            <div class="table-card-status indexed">Indexed in RAG</div>
                        </div>
                    </div>
                    <div class="table-card-actions">
                        <button class="memory-delete-btn table-action-btn danger ${inflightMemoryActions.has(src) ? 'is-loading' : ''}" ${inflightMemoryActions.has(src) ? 'disabled' : ''} onclick="deleteVectorMemory('${src}', event)" title="Delete from Memory">
                            Delete
                        </button>
                    </div>
                </div>
            `).join('')}</div>`;
        memoryList.dataset.rendered = '1';
        memoryList.classList.remove('is-updating');
    } catch (err) {
        if (!hasRendered) {
            memoryList.innerHTML = 'Error loading memory.';
        }
        memoryList.classList.remove('is-updating');
    }
}

async function deleteVectorMemory(sourceName, event) {
    if (inflightMemoryActions.has(sourceName)) return;
    inflightMemoryActions.add(sourceName);
    await loadVectorMemory({ preserve: true });

    if (!await customConfirm(`Remove "${sourceName}" from AI Vector Memory?\n\nThis will delete all indexed chunks for this source from ChromaDB.`, true)) {
        inflightMemoryActions.delete(sourceName);
        await loadVectorMemory({ preserve: true });
        return;
    }
    try {
        const resp = await fetch(`/api/vector_memory/${encodeURIComponent(sourceName)}`, {
            method: 'DELETE'
        });
        if (resp.ok) {
            const loadingToast = showToast(`Removing "${sourceName}" from RAG memory...`, 'info', 0);
            await pollUntilActionComplete((state) => !state.sources.includes(sourceName), { intervalMs: 2500 });
            dismissToast(loadingToast);
            showToast(`🗑️ "${sourceName}" removed from Vector Memory.`, 'info', 3000);
        } else {
            const error = await resp.json();
            showToast('Delete failed: ' + (error.detail || 'Unknown error'), 'error');
        }
    } catch (err) {
        showToast('Failed to delete memory block: ' + err.message, 'error');
    } finally {
        inflightMemoryActions.delete(sourceName);
        await loadVectorMemory({ preserve: true });
    }
}

async function loadHistory() {
    const resp = await fetch('/api/history');
    const hist = await resp.json();
    const list = document.getElementById('history-list');
    list.innerHTML = hist.map(item => `
        <div class="history-card">
            <div style="font-size:0.7rem; color:grey;">${item.timestamp}</div>
            <div style="font-weight:600; margin:5px 0;">Q: ${item.query}</div>
            <div style="font-size:0.85rem;">A: ${item.answer}</div>
            ${item.notebook ? `<details style="margin-top:10px;"><summary style="cursor:pointer; font-size:0.75rem;">Notebook State</summary><pre style="font-size:0.7rem; margin-top:5px;">${item.notebook}</pre></details>` : ''}
        </div>
    `).join('');
}

async function checkStatus() {
    const dot = document.getElementById('status-dot');
    const text = document.getElementById('status-text');
    try {
        const resp = await fetch('/health');
        if (resp.ok) {
            dot.style.color = '#4ade80';
            text.innerText = 'Online';
        } else {
            dot.style.color = '#ef4444';
            text.innerText = 'Offline';
        }
    } catch {
        dot.style.color = '#ef4444';
        text.innerText = 'Offline';
    }
}




// saveNotebook: optionally pre-fill the name prompt (e.g. current name when saving during dialog)
async function saveNotebook(prefillName) {
    // ── Guard: nothing to save if clean and already saved ────────────────────
    if (!isDirty && isNotebookSaved) {
        await customAlert('You have no changes to save.');
        return;
    }

    const oldName = currentNotebookName;
    const defaultName = prefillName || currentNotebookName || generateNotebookName();

    // ── Validator for Duplicate Check ──────────────────────────────────────
    const duplicateValidator = async (name) => {
        if (!name || !name.trim()) return "Name cannot be empty";
        // Fetch fresh list
        try {
            const res = await fetch('/api/notebooks');
            const list = await res.json();
            const exists = list.some(nb =>
                nb.display_name.trim().toLowerCase() === name.trim().toLowerCase() &&
                nb.display_name !== oldName // allow saving to self (update)
            );
            return exists ? "A notebook with this name already exists" : null;
        } catch (e) {
            return "Could not validate name";
        }
    };

    const name = await customPrompt('Enter notebook name:', defaultName, { validator: duplicateValidator });
    if (!name) return;

    // Do NOT update global state yet - wait for successful save!
    // setNotebookTitle(name); <--- moved down
    // currentNotebookName = name; <--- moved down

    const cells = [];

    document.querySelectorAll('.code-cell').forEach(cell => {
        const codeEditor = cell.querySelector('.code-editor');
        const textEditor = cell.querySelector('.text-editor');
        const outputDiv = cell.querySelector('.cell-output');

        if (codeEditor) {
            let code = codeEditor.value;
            if (codeEditor.nextSibling && codeEditor.nextSibling.classList &&
                codeEditor.nextSibling.classList.contains('CodeMirror')) {
                const cm = codeEditor.nextSibling.CodeMirror;
                if (cm) code = cm.getValue();
            }
            cells.push({
                cell_type: 'code',
                source: code,
                output: outputDiv ? outputDiv.innerHTML : ''
            });
        } else if (textEditor) {
            cells.push({
                cell_type: 'markdown',
                source: textEditor.innerHTML
            });
        }
    });

    if (currentChatId) saveCurrentChat();
    // currentNotebookId = 'notebook_' + name; <--- move to success

    try {
        const chatsSnapshot = JSON.parse(JSON.stringify(chats || []));
        const resp = await fetch('/api/notebooks/save', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                name,
                cells,
                // Persist full multi-chat state per notebook (not flat chatHistory).
                chat_data: { currentChatId, chats: chatsSnapshot }
            })
        });

        const result = await resp.json();

        if (!resp.ok || result.error) {
            throw new Error(result.detail || result.error || "Save failed");
        }

        // ── Success: Update State & UI ───────────────────────────────────────
        setNotebookTitle(name);
        currentNotebookName = name;
        currentNotebookId = 'notebook_' + name;
        persistActiveNotebookId();

        saveChatsToLocalStorage();

        // ── Rename: delete old entry if it was a different name ──────────────
        if (oldName && oldName !== name) {
            await fetch(`/api/notebooks/${encodeURIComponent(oldName)}`, { method: 'DELETE' });
        }

        loadSavedNotebooks();
        isDirty = false;
        isNotebookSaved = true;

    } catch (e) {
        console.error(e);
        await customAlert(e.message || "An error occurred while saving.");
        // Do not update state, do not delete old notebook. Safe.
    }
}



// ── Internal reset: create a blank notebook (no dialogs) ─────────────────
function _doNewNotebook() {
    if (currentChatId) saveCurrentChat();

    const view = document.getElementById('workspace-view');
    view.innerHTML = '';
    cellCount = 0;
    addCodeCell();

    currentNotebookId = 'notebook_' + Date.now();
    persistActiveNotebookId();
    setNotebookTitle('Untitled Notebook');
    chats = [];
    currentChatId = null;
    chatHistory = [];
    messagePairs = [];
    document.getElementById('ai-content-area').innerHTML = '';
    renderChatList();

    // Reset dirty state for fresh notebook
    isDirty = false;
    isNotebookSaved = false;
    currentNotebookName = null;
}

// ── New Notebook — three-case dialog logic ─────────────────────────────────
async function newNotebook() {
    if (!isNotebookSaved) {
        // ── Case 1: New (never saved) notebook ───────────────────────────
        if (!isDirty) {
            _doNewNotebook();
            return;
        }
        const save = await showCustomDialog(
            'Unsaved Notebook',
            'Do you want to save this notebook before creating a new one?',
            { type: 'confirm', confirmText: 'Save & Continue', cancelText: 'Continue Without Saving' }
        );
        if (save === null) return; // X button — stay on current notebook
        if (save) await saveNotebook(currentNotebookName);
        _doNewNotebook();

    } else {
        // ── Case 2/3: Previously saved notebook ──────────────────────────
        if (!isDirty) {
            _doNewNotebook();
            return;
        }
        const save = await showCustomDialog(
            'Unsaved Changes',
            'You have unsaved changes. Save before creating a new notebook?',
            { type: 'confirm', confirmText: 'Save Changes', cancelText: 'Cancel' }
        );
        if (save === null) return; // X button — stay on current notebook
        if (save) await saveNotebook(currentNotebookName);
        _doNewNotebook();
    }
}


// (Removed duplicate loadSavedNotebooks function)

async function openNotebook(name) {
    const resp = await fetch(`/api/notebooks/${name}`);
    const data = await resp.json();

    if (data.error) {
        await customAlert("Could not load notebook.");
        return;
    }

    // Set notebook identity based on notebook name
    currentNotebookId = 'notebook_' + name;
    currentNotebookName = name;  // prefill for future saves
    persistActiveNotebookId();
    setNotebookTitle(name);

    // Extract cells (backward compatible with legacy array format)
    let notebookCells = Array.isArray(data) ? data : (data.cells || []);

    // Restore multi-chat data
    if (data.chat_data && data.chat_data.chats && data.chat_data.chats.length > 0) {
        // New format: full multi-chat data
        chats = data.chat_data.chats;
        currentChatId = data.chat_data.currentChatId;
        chatHistory = [];
        messagePairs = [];
    } else if (data.chat_history && data.chat_history.length > 0) {
        // Legacy format: migrate flat chat_history into a single chat
        chats = [{
            id: 'chat_' + Date.now(),
            title: 'Restored Chat',
            messages: [],
            chatHistory: data.chat_history,
            createdAt: Date.now(),
            updatedAt: Date.now()
        }];
        currentChatId = chats[0].id;
        chatHistory = data.chat_history;
        messagePairs = [];
    } else {
        // No chat data at all
        chats = [];
        currentChatId = null;
        chatHistory = [];
        messagePairs = [];
    }

    // 1. Switch to workspace view
    switchTab('workspace');

    // 2. Clear the screen
    const view = document.getElementById('workspace-view');
    view.innerHTML = '';
    cellCount = 0;

    // 3. Rebuild the cells from the saved data
    notebookCells.forEach(cellData => {
        if (cellData.cell_type === 'code') {
            addCodeCell();
            const currentCell = document.getElementById(`cell-${cellCount}`);
            const textarea = currentCell.querySelector('.code-editor');

            if (textarea) {
                // Check if CodeMirror is initialized
                if (textarea.nextSibling && textarea.nextSibling.classList && textarea.nextSibling.classList.contains('CodeMirror')) {
                    const cm = textarea.nextSibling.CodeMirror;
                    if (cm) cm.setValue(cellData.source || '');
                } else {
                    textarea.value = cellData.source || '';
                    autoResize(textarea);
                }
            }

            if (cellData.output) {
                const out = currentCell.querySelector('.cell-output');
                if (out) out.innerHTML = cellData.output;
            }

        } else if (cellData.cell_type === 'markdown') {
            addTextCell();
            const currentCell = document.getElementById(`cell-${cellCount}`);
            const editor = currentCell.querySelector('.text-editor');

            if (editor) editor.innerHTML = cellData.source || '';
        }
    });

    // 4. Clear AI content area and render chat list + last active chat
    document.getElementById('ai-content-area').innerHTML = '';
    renderChatList();
    if (currentChatId && chats.find(c => c.id === currentChatId)) {
        loadChatToUI(currentChatId);
    } else if (chats.length > 0) {
        const sorted = [...chats].sort((a, b) => b.updatedAt - a.updatedAt);
        currentChatId = sorted[0].id;
        loadChatToUI(currentChatId);
    }
    saveChatsToLocalStorage();

    // Mark this as a clean, previously-saved notebook
    isDirty = false;
    isNotebookSaved = true;
}

function renderChatHistory(history) {
    const contentArea = document.getElementById("ai-content-area");
    contentArea.innerHTML = '';

    history.forEach(msg => {
        const bubble = document.createElement('div');
        const isUser = msg.role === 'user';
        bubble.className = `ai-msg ${isUser ? 'user' : 'assistant'}`;

        if (isUser) {
            bubble.style.cssText = "padding:16px 10px 10px 10px; background:#eef2ff; border-radius:10px; margin:8px 0 8px auto; width:fit-content; max-width:70%; word-wrap:break-word; white-space:pre-wrap; overflow-wrap:break-word;";
            bubble.innerText = msg.content;
        } else {
            bubble.style.cssText = "padding:16px 10px 10px 20px; background:#ffffff; border:1px solid #e6edf3; border-radius:10px; margin:8px 0;";

            // Header
            const header = document.createElement('div');
            header.style.cssText = "display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;";
            header.innerHTML = `<strong>Assistant</strong><span style="color:#888; font-size:0.75rem;">Restored</span>`;

            // Body
            const body = document.createElement('div');
            body.style.cssText = "font-size:0.95rem; line-height:1.5;";

            if (typeof marked !== 'undefined' && typeof DOMPurify !== 'undefined') {
                body.innerHTML = DOMPurify.sanitize(marked.parse(msg.content || ''));
            } else {
                body.innerText = msg.content;
            }

            bubble.appendChild(header);
            bubble.appendChild(body);
        }
        contentArea.appendChild(bubble);
    });

    const tray = document.getElementById("ai-response-tray");
    if (tray) tray.scrollTop = tray.scrollHeight;
}
async function uploadNotebook() {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.ipynb';

    input.onchange = async (e) => {
        const file = e.target.files[0];
        if (!file) return;

        const formData = new FormData();
        formData.append('file', file);

        try {
            const resp = await fetch('/api/notebooks/upload', {
                method: 'POST',
                body: formData
            });

            const result = await resp.json();

            if (result.error) {
                await customAlert(result.error);
            } else {
                await customAlert(`Successfully uploaded: ${result.name} with ${result.cells_count} cells`);
                loadSavedNotebooks();
            }
        } catch (error) {
            await customAlert('Upload failed: ' + error.message);
        }
    };

    input.click();
}



// Update loadNotebookIntoWorkspace to properly restore cells
async function loadNotebookIntoWorkspace(name) {
    try {
        const resp = await fetch(`/api/notebooks/${name}`);
        const cells = await resp.json();

        if (cells.error) {
            alert(cells.error);
            return;
        }

        // Clear current notebook
        notebookCells = [];

        // Load all cells from saved notebook
        cells.forEach(cellData => {
            const cell = createCell();
            const textarea = cell.querySelector('textarea');
            const outputDiv = cell.querySelector('.output');

            // Set cell type
            if (cellData.type === 'markdown') {
                cell.classList.add('markdown-cell');
                textarea.placeholder = 'Enter markdown...';
            }

            // Set content
            textarea.value = cellData.content || '';

            // Restore output if available
            if (cellData.output) {
                outputDiv.innerHTML = cellData.output;
                outputDiv.style.display = 'block';
            }
        });

        // Switch to notebook view
        switchTab('notebook');
        alert(`Loaded: ${name} (${cells.length} cells)`);

    } catch (error) {
        alert('Failed to load notebook: ' + error.message);
    }
}

function addTextCell(button) {
    const cellHtml = `
        <div class="code-cell text-cell" onclick="activateCell(this)">

            <div class="cell-controls">
                <button onclick="toggleEdit(this)">${ICON_EDIT}</button>
                <button onclick="moveCellUp(this)">${ICON_MOVE_UP}</button>
                <button onclick="moveCellDown(this)">${ICON_MOVE_DOWN}</button>
                <button onclick="deleteCell(this)">${ICON_DELETE}</button>
                <button onclick="moreOptions(this)">${ICON_MORE}</button>
            </div>

            <div class="cell-content-part">
                <div class="text-toolbar hidden">
                    <button onclick="formatText('bold')">${ICON_BOLD}</button>
                    <button onclick="formatText('italic')">${ICON_ITALIC}</button>
                    <button onclick="formatBlockquote()">${ICON_QUOTE}</button>
                    <button onclick="insertLinkNewTab()">${ICON_LINK}</button>
                    <button onclick="insertImage()">${ICON_IMAGE}</button>
                    <button onclick="formatText('insertUnorderedList')">${ICON_LIST}</button>
                    <button onclick="formatText('insertOrderedList')">${ICON_LIST_ORDERED}</button>
                    <button onclick="insertHR()">${ICON_HR}</button>
                    <button onclick="toggleEdit(this, true)">${ICON_EDIT_OFF}</button>
                </div>

                <div class="text-editor"
                     contenteditable="false"
                     ondblclick="enableTextEdit(this)"
                     data-placeholder="Write text / notes…"></div>
            </div>
        </div>
    `;

    insertCellWithBar(button, cellHtml);
}
function activateCell(cell) {
    document.querySelectorAll('.code-cell').forEach(c => c.classList.remove('active'));
    cell.classList.add('active');
}

function enableTextEdit(editor) {
    console.log("Double click event fired on text editor", editor);
    const cell = editor.closest('.code-cell');
    if (!cell) {
        console.error("Parent .code-cell not found");
        return;
    }
    const toolbar = cell.querySelector('.text-toolbar');

    if (editor.contentEditable === "true") {
        console.log("Already in edit mode");
        return;
    }

    editor.contentEditable = "true";
    toolbar.classList.remove('hidden');
    editor.focus();

    // Move cursor to start
    try {
        const range = document.createRange();
        range.selectNodeContents(editor); // Select everything
        range.collapse(true); // Collapse to start
        const sel = window.getSelection();
        sel.removeAllRanges();
        sel.addRange(range);
        console.log("Cursor set to start");
    } catch (e) {
        console.error("Error setting cursor:", e);
    }
}

function toggleEdit(btn, close = false) {
    const cell = btn.closest('.code-cell');
    const editor = cell.querySelector('.text-editor');
    const toolbar = cell.querySelector('.text-toolbar');

    if (close) {
        editor.contentEditable = "false";
        toolbar.classList.add('hidden');
        return;
    }

    const isEditing = editor.contentEditable === "true";
    editor.contentEditable = isEditing ? "false" : "true";
    toolbar.classList.toggle('hidden', isEditing);
}

function formatBlockquote() {
    document.execCommand('formatBlock', false, 'blockquote');
}

async function insertLinkNewTab() {
    const url = await customPrompt("Enter URL");
    if (!url) return;
    document.execCommand('insertHTML', false, `<a href="${url}" target="_blank">${url}</a>`);
}

function insertCellWithBar(button, cellHtml) {
    const barHtml = `
        <div class="add-cell-bar">
            <button class="add-cell-btn" onclick="addCodeCell(this)">＋ Code</button>
            <button class="add-cell-btn secondary" onclick="addTextCell(this)">＋ Text</button>
        </div>`;

    if (button) {
        const bar = button.parentElement;
        bar.insertAdjacentHTML('afterend', cellHtml);
        bar.nextElementSibling.insertAdjacentHTML('afterend', barHtml);
    } else {
        const view = document.getElementById('workspace-view');
        view.insertAdjacentHTML('beforeend', cellHtml);
        view.lastElementChild.insertAdjacentHTML('afterend', barHtml);
    }
}



// Text formatting functions
function formatText(command, value) {
    document.execCommand(command, false, value);
}

async function insertLink() {
    const url = await customPrompt('Enter URL:');
    if (url) {
        document.execCommand('createLink', false, url);
    }
}

async function insertImage() {
    const url = await customPrompt('Enter image URL:');
    if (url) {
        document.execCommand('insertImage', false, url);
    }
}

function insertHR() {
    document.execCommand('insertHorizontalRule');
}


function insertTable() {
    // Simple table insertion
    const table = '<table border="1"><tr><td>Cell 1</td><td>Cell 2</td></tr><tr><td>Cell 3</td><td>Cell 4</td></tr></table>';
    document.execCommand('insertHTML', false, table);
}

function closeToolbar(button) {
    const toolbar = button.closest('.text-toolbar');
    toolbar.style.display = 'none';
}

// Cell control functions
function moveCellUp(button) {
    const cell = button.closest('.code-cell');
    const prev = cell.previousElementSibling;
    if (prev && prev.classList.contains('code-cell')) {
        cell.parentNode.insertBefore(cell, prev);
        markDirty();
    }
}

function moveCellDown(button) {
    const cell = button.closest('.code-cell');
    const next = cell.nextElementSibling;
    if (next && next.classList.contains('code-cell')) {
        cell.parentNode.insertBefore(next, cell);
        markDirty();
    }
}

function editCell(button) {
    // Toggle edit mode or something, for now just focus
    const editor = button.closest('.code-cell').querySelector('.text-editor, .code-editor');
    if (editor) editor.focus();
}

function deleteCell(button) {
    // 1. Find the cell wrapper
    const cell = button.closest('.code-cell');

    if (cell) {
        // 2. Remove the "+ Code" bar below it (cleanup)
        const bar = cell.nextElementSibling;
        if (bar && bar.classList.contains('add-cell-bar')) {
            bar.remove();
        }

        // 3. Delete immediately (No confirm box)
        cell.remove();
        markDirty();
    }
}

async function moreOptions(button) {
    await customAlert('More options: duplicate, etc. (not implemented)');
}

/* ===========================================
   ✅ CELL MANAGEMENT LOGIC (COPY TO BOTTOM)
   =========================================== */

function moveCellUp(button) {
    // 1. Find the current cell and its attached "Add Cell" bar
    const currentCell = button.closest('.code-cell');
    if (!currentCell) return;
    const currentBar = currentCell.nextElementSibling; // The bar belonging to this cell

    // 2. Find the items immediately above (Previous Bar -> Previous Cell)
    const prevBar = currentCell.previousElementSibling;

    // We can only move up if there is a previous Bar and a Previous Cell
    if (prevBar && prevBar.previousElementSibling) {
        const prevCell = prevBar.previousElementSibling;

        // Ensure we are jumping over a real cell (code or text)
        if (prevCell.classList.contains('code-cell')) {
            const parent = currentCell.parentNode;

            // 3. Move Current Cell ABOVE the Previous Cell
            parent.insertBefore(currentCell, prevCell);

            // 4. Move Current Bar ABOVE the Previous Cell (so it follows current cell)
            if (currentBar && currentBar.classList.contains('add-cell-bar')) {
                parent.insertBefore(currentBar, prevCell);
            }
        }
    }
}


function moveCellDown(button) {
    const currentCell = button.closest('.code-cell');
    if (!currentCell) return;
    const currentBar = currentCell.nextElementSibling;

    // 1. To move down, we actually target the NEXT cell and move IT up.
    if (currentBar && currentBar.nextElementSibling) {
        const nextCell = currentBar.nextElementSibling;
        const parent = currentCell.parentNode;

        if (nextCell && nextCell.classList.contains('code-cell')) {
            // 2. Insert the NEXT cell before the CURRENT cell (effectively swapping)
            parent.insertBefore(nextCell, currentCell);

            // 3. Move the NEXT cell's bar along with it
            if (nextBar && nextBar.classList.contains('add-cell-bar')) {
                parent.insertBefore(nextBar, currentCell);
            }
        }
    }
}

function downloadAsJupyter() {
    const cells = [];

    // Loop through DOM to build Jupyter Cell Structure
    document.querySelectorAll('#workspace-view .code-cell').forEach(cellDiv => {
        const textarea = cellDiv.querySelector('.code-editor');
        const textEditor = cellDiv.querySelector('.text-editor');

        if (textarea) { // Code Cell
            let code = textarea.value;
            // Check if CodeMirror is initialized
            if (textarea.nextSibling && textarea.nextSibling.classList && textarea.nextSibling.classList.contains('CodeMirror')) {
                const cm = textarea.nextSibling.CodeMirror;
                if (cm) code = cm.getValue();
            }
            cells.push({
                "cell_type": "code",
                "execution_count": null,
                "metadata": {},
                "outputs": [], // Logic to capture outputs would go here
                "source": code.split('\n').map(line => line + '\n')
            });
        } else if (textEditor) { // Markdown/Text Cell
            cells.push({
                "cell_type": "markdown",
                "metadata": {},
                "source": [textEditor.innerText]
            });
        }
    });

    const notebookObj = {
        "cells": cells,
        "metadata": {
            "kernelspec": {
                "display_name": "Python 3 (Pyodide)",
                "language": "python",
                "name": "python3"
            },
            "language_info": {
                "name": "python",
                "version": "3.10"
            }
        },
        "nbformat": 4,
        "nbformat_minor": 5
    };

    // Trigger Download
    const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(notebookObj, null, 2));
    const downloadAnchor = document.createElement('a');
    downloadAnchor.setAttribute("href", dataStr);
    downloadAnchor.setAttribute("download", "notebook.ipynb");
    document.body.appendChild(downloadAnchor);
    downloadAnchor.click();
    downloadAnchor.remove();
}

function deleteCell(button) {
    // 1. Find the cell wrapper
    const cell = button.closest('.code-cell');

    if (cell) {
        // 2. Remove the "+ Code" bar below it (cleanup)
        const bar = cell.nextElementSibling;
        if (bar && bar.classList.contains('add-cell-bar')) {
            bar.remove();
        }

        // 3. Delete immediately (No confirm box)
        cell.remove();
    }
}

// Handles the Pencil icon
function editCell(button) {
    const cell = button.closest('.code-cell');

    // Check if it is a Text Cell
    if (cell.classList.contains('text-cell')) {
        toggleEdit(button); // Calls the existing text logic
    } else {
        // If it is a Code Cell, just focus the code area
        const editor = cell.querySelector('.code-editor');
        if (editor) {
            editor.focus();
            // Optional: visual feedback
            cell.style.borderColor = '#2563eb';
            setTimeout(() => cell.style.borderColor = '', 1000);
        }
    }
}
// Reformat backend timestamp "YYYY-MM-DD HH:MM" to "dd/mm/yy, h:mm AM/PM"
function formatSavedTimestamp(ts) {
    if (!ts) return '';
    const [datePart, timePart] = ts.split(' ');
    const [yyyy, mm, dd] = datePart.split('-');
    const [hh, min] = timePart.split(':');
    const hour = parseInt(hh, 10);
    const ampm = hour >= 12 ? 'PM' : 'AM';
    const h12 = hour % 12 || 12;
    const yy = yyyy.slice(-2);
    return `${dd}/${mm}/${yy}, ${h12}:${min} ${ampm}`;
}

async function uploadSavedNotebook(event) {
    const file = event.target.files[0];
    if (!file) return;

    if (!file.name.endsWith('.ipynb')) {
        await customAlert("Only .ipynb files can be uploaded as notebooks.");
        return;
    }

    const formData = new FormData();
    formData.append('file', file);

    try {
        setNotebookTitle("Uploading...");

        const response = await fetch('/api/notebooks/upload', {
            method: 'POST',
            body: formData
        });

        const data = await response.json();
        if (response.ok) {
            await customAlert(`Notebook '${data.name}' uploaded successfully!`);
            setNotebookTitle(data.name);
            currentNotebookName = data.name;

            // Reload the saved notebooks drawer
            if (typeof loadSavedNotebooks === 'function') {
                loadSavedNotebooks();
            }
            // Open the freshly uploaded notebook
            if (typeof openNotebook === 'function') {
                openNotebook(data.name);
            }
        } else {
            throw new Error(data.detail || data.error || 'Upload failed');
        }
    } catch (e) {
        setNotebookTitle("Untitled Notebook");
        await customAlert('Upload error: ' + e.message);
    }

    // Clear the input so the same file can be uploaded again if needed
    event.target.value = '';
}
async function loadSavedNotebooks() {
    const resp = await fetch('/api/notebooks');
    const data = await resp.json();
    const list = document.getElementById('saved-list');

    if (!data || data.length === 0) {
        list.innerHTML = '<p style="color:grey; padding:20px;">No saved notebooks found.</p>';
        return;
    }

    const notebookIcon = `<svg xmlns="http://www.w3.org/2000/svg" width="15.6" height="15.6" viewBox="-2 -1 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-notebook-text"><path d="M2 6h4"/><path d="M2 10h4"/><path d="M2 14h4"/><path d="M2 18h4"/><rect width="16" height="20" x="4" y="2" rx="2"/><path d="M9.5 8h5"/><path d="M9.5 12H16"/><path d="M9.5 16H14"/></svg>`;
    const trash = `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/><path d="M3 6h18"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>`;
    const pen = `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-pen-line"><path d="M13 21h8"/><path d="M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z"/></svg>`;
    const downloadSvg = `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-download"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" x2="12" y1="15" y2="3"/></svg>`;

    list.innerHTML = '';
    data.forEach(nb => {
        const card = document.createElement('div');
        card.className = 'history-card';
        card.dataset.nbName = nb.display_name;
        // Added position: relative for absolute positioning of buttons
        card.style.cssText = 'position:relative; cursor:pointer; border-left:4px solid #3b82f6; padding:15px; background:white; border-radius:8px;';

        // Re-apply selected state after re-render
        if (selectedSavedNotebook === nb.display_name) {
            card.classList.add('drawer-item--selected');
        }

        card.innerHTML = `
            <button class="download-db-btn" onclick="downloadSavedNotebook(event, '${nb.display_name}')" title="Download">${downloadSvg}</button>
            <button class="rename-db-btn" onclick="initRename(event, '${nb.display_name}')" title="Rename">${pen}</button>
            <button class="delete-db-btn" onclick="deleteSavedNotebook(event, '${nb.display_name}')" title="Delete">${trash}</button>
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <strong style="color:#1e293b; font-size:1rem;">${notebookIcon} ${nb.display_name}</strong>
                <span style="font-size:0.625rem; color:#94a3b8;">${formatSavedTimestamp(nb.timestamp)}</span>
            </div>
            <p style="margin:8px 0 0 0; font-size:0.85rem; color:#64748b;">Click to Open in Workspace.</p>
        `;

        card.addEventListener('click', (e) => {
            // Ignore clicks if clicking buttons or input
            if (e.target.closest('.delete-db-btn') || e.target.closest('.rename-db-btn') || e.target.closest('.download-db-btn') || e.target.closest('input')) return;
            // Update selection state
            selectedSavedNotebook = nb.display_name;
            // Highlight this card, deselect others in list
            list.querySelectorAll('.history-card').forEach(c => c.classList.remove('drawer-item--selected'));
            card.classList.add('drawer-item--selected');
            // Load the notebook
            openNotebook(nb.display_name);
        });

        list.appendChild(card);
    });
}

// ── Download Notebook Logic ───────────────────────────────────────────────────
async function downloadSavedNotebook(event, name) {
    event.stopPropagation();
    try {
        const resp = await fetch(`/api/notebooks/${encodeURIComponent(name)}/download`);
        if (!resp.ok) {
            throw new Error(`Failed to download notebook (Status: ${resp.status})`);
        }

        // Convert response to blob
        const blob = await resp.blob();

        // Generate a temporary anchor to trigger download
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;

        // Try to get exact filename backend sent
        const contentDisposition = resp.headers.get('Content-Disposition');
        let filename = `${name}.ipynb`;
        if (contentDisposition && contentDisposition.includes('filename=')) {
            const matches = /filename="([^"]+)"/.exec(contentDisposition);
            if (matches != null && matches[1]) {
                filename = matches[1];
            }
        }

        a.download = filename;
        document.body.appendChild(a);
        a.click();

        // Cleanup
        a.remove();
        window.URL.revokeObjectURL(url);
    } catch (e) {
        await customAlert('Download error: ' + e.message);
    }
}

// ── Relative time helper ─────────────────────────────────────────────────────
// Input: "YYYY-MM-DD HH:MM:SS" or "YYYY-MM-DD HH:MM"
function getRelativeTime(ts) {
    if (!ts) return '';
    // Parse backend format: replace space with T for ISO compatibility
    const past = new Date(ts.replace(' ', 'T'));
    const diffMs = Date.now() - past.getTime();
    const diffMin = Math.floor(diffMs / 60000);
    if (diffMin < 1) return 'just now';
    if (diffMin < 60) return diffMin + 'm';
    const diffHr = Math.floor(diffMin / 60);
    if (diffHr < 24) return diffHr + 'hr';
    const diffDay = Math.floor(diffHr / 24);
    if (diffDay < 7) return diffDay + 'd';
    const diffWk = Math.floor(diffDay / 7);
    if (diffWk < 52) return diffWk + 'w';
    return Math.floor(diffWk / 52) + 'yr';
}

// ── Rename Logic ─────────────────────────────────────────────────────────────
function initRename(event, name) {
    event.stopPropagation();
    const btn = event.currentTarget;
    const card = btn.closest('.history-card');
    const strong = card.querySelector('strong');

    // Create container for input + error
    const container = document.createElement('div');
    container.style.display = 'flex';
    container.style.flexDirection = 'column'; // Vertical stack for error msg

    // Create input
    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'rename-input';
    input.value = name;
    input.dataset.oldName = name;

    container.appendChild(input);

    // Replace strong with container
    strong.style.display = 'none';
    strong.parentNode.insertBefore(container, strong);
    input.focus();
    input.select();

    let isSaving = false;

    const save = async (e) => {
        if (isSaving) return;
        isSaving = true;

        // Pass event type to finishRename so we handle Blur vs Enter differently
        const isBlur = e && e.type === 'blur';

        await finishRename(input, container, strong, isBlur);

        // Reset flag if we returned (e.g. error on Enter kept input open)
        // If success or revert happened, input/container are removed anyway
        if (document.body.contains(input)) {
            isSaving = false;
        }
    };

    // Use a slight delay on blur to allow for other interactions if needed, 
    // but main logic is robust.
    input.addEventListener('blur', save);

    input.addEventListener('keydown', async (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            // Remove blur listener to avoid double-fire
            input.removeEventListener('blur', save);
            await save(e);
        }
        if (e.key === 'Escape') {
            input.removeEventListener('blur', save);
            container.remove();
            strong.style.display = '';
        }
    });

    input.addEventListener('click', e => e.stopPropagation());
}

async function finishRename(input, container, strong, isBlur) {
    const oldName = input.dataset.oldName;
    const newName = input.value.trim();

    // Clear any previous error
    const errorSpan = container.querySelector('.rename-error');
    if (errorSpan) errorSpan.remove();
    input.style.border = '1px solid #3b82f6'; // Reset border

    // 1. Validation: Empty or same name -> Revert/Cancel
    if (!newName || newName === oldName) {
        container.remove();
        strong.style.display = '';
        return;
    }

    try {
        // 2. Fetch list to check for duplicates
        const listResp = await fetch('/api/notebooks');
        if (!listResp.ok) throw new Error("Validation check failed");
        const listData = await listResp.json();

        // Case-insensitive check
        const exists = listData.some(nb =>
            nb.display_name.trim().toLowerCase() === newName.toLowerCase()
        );

        if (exists) {
            if (isBlur) {
                // On blur: duplicate -> Revert to safe state (cancel edit)
                container.remove();
                strong.style.display = '';
                return;
            } else {
                // On Enter: duplicate -> Show error, keep input open for retry
                const err = document.createElement('span');
                err.className = 'rename-error';
                err.textContent = "Name already exists";
                err.style.color = '#ef4444';
                err.style.fontSize = '0.75rem';
                err.style.marginTop = '2px';
                container.appendChild(err);
                input.style.border = '1px solid #ef4444';
                input.focus();
                return; // Stop here, let user fix
            }
        }

        // 3. Attempt Atomic Rename (Preserves mtime/position)
        // If this works, the notebook stays in place in the sorted list.
        const resRename = await fetch('/api/notebooks/rename', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ old_name: oldName, new_name: newName })
        });

        if (resRename.ok) {
            // Success! Mtime preserved.
            loadSavedNotebooks();

            if (currentNotebookId === 'notebook_' + oldName) {
                currentNotebookId = 'notebook_' + newName;
                currentNotebookName = newName;
                setNotebookTitle(newName);
                persistActiveNotebookId();
            }
            return;
        }

        // If 404/405 (endpoint not found/loaded), fallback to Save-As-New (Updates mtime -> moves to top)
        if (resRename.status === 404 || resRename.status === 405) {
            console.warn("Atomic rename not available, falling back to copy-delete (timestamp will update).");
        } else {
            // Other error (e.g. 500)
            const err = await resRename.json();
            throw new Error(err.detail || "Rename failed");
        }

        // 4. Fallback: Fetch -> Save New -> Delete Old
        const resGet = await fetch(`/api/notebooks/${encodeURIComponent(oldName)}`);
        if (!resGet.ok) throw new Error("Could not read original notebook");
        const data = await resGet.json();

        const payload = {
            name: newName,
            cells: data.cells || [],
            chat_data: data.chat_data || {},
            chat_history: data.chat_history || []
        };

        const resSave = await fetch('/api/notebooks/save', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        if (!resSave.ok) {
            const err = await resSave.json();
            throw new Error(err.error || err.detail || "Failed to save new name");
        }

        // 5. Delete old notebook
        await fetch(`/api/notebooks/${encodeURIComponent(oldName)}`, { method: 'DELETE' });

        // Success: Update UI
        loadSavedNotebooks();

        // If active notebook was renamed, update globals
        if (currentNotebookId === 'notebook_' + oldName) {
            currentNotebookId = 'notebook_' + newName;
            currentNotebookName = newName;
            setNotebookTitle(newName);
            persistActiveNotebookId();
        }

    } catch (e) {
        console.error(e);
        // On error (network/other), revert to safe state
        // If it was Enter, show alert? Or just revert? Alert is safer so user knows why failed.
        if (!isBlur) {
            await customAlert(e.message || 'Rename failed');
        }
        container.remove();
        strong.style.display = '';
    }
}

// ── Restore a history item as a live chat session ─────────────────────────────
async function openHistoryInChat(item) {
    // Save current chat first
    if (currentChatId) saveCurrentChat();

    // Set transient viewing state — do NOT attach this history chat to the current notebook
    viewingHistoryItem = item;
    viewingHistoryOriginalNotebook = null;

    // Try to discover the original saved notebook (best-effort)
    try {
        viewingHistoryOriginalNotebook = await findNotebookForHistory(item);
    } catch (e) {
        console.warn('Failed to find original notebook for history item', e);
    }

    // Load the history conversation into the popup UI without adding it to `chats`
    const restoredHistory = [
        { role: 'user', content: item.query },
        { role: 'assistant', content: item.answer }
    ];

    // Clear current UI and render history
    clearChatUI();
    chatHistory = JSON.parse(JSON.stringify(restoredHistory));
    renderMessagesFromHistory();

    // Mark there is no currentChatId for this transient view (so it won't be persisted to current notebook)
    currentChatId = null;

    // Ensure the popup is open + maximized per requirement
    if (!isPopupOpen() || !isPopupMaximized()) {
        openPopupMaximized();
    }
}

// ── History drawer renderer ───────────────────────────────────────────────────
async function loadHistory() {
    const resp = await fetch('/api/history');
    const data = await resp.json();
    const list = document.getElementById('history-list');

    if (!data || data.length === 0) {
        list.innerHTML = '<p style="color:grey; padding:20px;">No history items found.</p>';
        return;
    }

    const historyIcon = `<svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-history" style="vertical-align:-1px;margin-right:3px;opacity:0.6"><path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/><path d="M12 7v5l4 2"/></svg>`;
    const trash = `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/><path d="M3 6h18"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>`;

    list.innerHTML = '';
    data.forEach(item => {
        const card = document.createElement('div');
        card.className = 'history-card';
        card.dataset.historyId = item.id;
        card.style.cssText = 'cursor:pointer; border-left: 4px solid #3b82f6;';

        // Re-apply selected state after re-render
        if (selectedHistoryId === item.id) {
            card.classList.add('drawer-item--selected');
        }

        card.innerHTML = `
            <button class="delete-db-btn" onclick="deleteHistoryItem(event, ${item.id})">${trash}</button>
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
                <span style="font-size:0.75rem; background:#f1f5f9; padding:3px 6px; border-radius:4px; white-space:nowrap; line-height:1; display:inline-flex; align-items:center;">${item.tool.replace(/_/g, ' ')}</span>
                <span style="font-size:0.72rem; color:#94a3b8; display:inline-flex; align-items:center; gap:2px;">${historyIcon}${getRelativeTime(item.timestamp)}</span>
            </div>
            <div style="font-weight:500; margin-bottom:4px; font-size:0.9rem; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">${item.query}</div>
            <div style="color:#64748b; font-size:0.82rem; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">${item.answer.substring(0, 100)}…</div>
        `;

        card.addEventListener('click', (e) => {
            if (e.target.closest('.delete-db-btn')) return;
            // Update selection
            selectedHistoryId = item.id;
            list.querySelectorAll('.history-card').forEach(c => c.classList.remove('drawer-item--selected'));
            card.classList.add('drawer-item--selected');
            // Restore full conversation in popup
            openHistoryInChat(item);
        });

        list.appendChild(card);
    });
}

async function deleteHistoryItem(event, itemId) {
    event.stopPropagation();
    try {
        const resp = await fetch(`/api/history/${itemId}`, { method: 'DELETE' });
        if (resp.ok) {
            const card = event.target.closest('.history-card');
            if (card) card.remove();
        }
    } catch (e) {
        console.error('Failed to delete history item:', e);
    }
}

async function deleteSavedNotebook(event, name) {
    event.stopPropagation();
    if (!await customConfirm(`Delete notebook "${name}"?`, true)) return;
    try {
        const resp = await fetch(`/api/notebooks/${encodeURIComponent(name)}`, { method: 'DELETE' });
        if (resp.ok) {
            const card = event.target.closest('.history-card');
            if (card) card.remove();
        }
    } catch (e) {
        console.error('Failed to delete notebook:', e);
    }
}
// Try to find the original saved notebook name for a history entry (best-effort).
async function findNotebookForHistory(item) {
    if (!item || !item.notebook) return null;
    try {
        const listResp = await fetch('/api/notebooks');
        const notebooks = await listResp.json();
        if (!Array.isArray(notebooks)) return null;

        // Attempt to parse stored notebook context (history stores as stringified list)
        let histArr = null;
        try {
            histArr = JSON.parse(item.notebook);
        } catch (e) {
            // Try converting single-quotes to double-quotes (python repr -> json)
            try {
                histArr = JSON.parse(item.notebook.replace(/'/g, '"'));
            } catch (e2) {
                histArr = null;
            }
        }

        for (const nb of notebooks) {
            try {
                const resp = await fetch(`/api/notebooks/${encodeURIComponent(nb.display_name)}`);
                const data = await resp.json();
                if (!data || !data.cells) continue;

                const cellTexts = data.cells.map(c => (c.source || c.content || '').toString()).filter(Boolean);

                if (histArr && Array.isArray(histArr) && histArr.length > 0) {
                    // If any history cell appears in notebook cells, treat as match
                    let matches = 0;
                    for (const h of histArr) {
                        if (!h) continue;
                        for (const ct of cellTexts) {
                            if (!ct) continue;
                            if (ct.includes(h) || h.includes(ct) || ct.includes(h.slice(0, Math.min(50, h.length)))) {
                                matches++;
                                break;
                            }
                        }
                    }
                    if (matches > 0) return nb.display_name;
                } else {
                    // Fallback: check if the query or answer text exists in notebook cells
                    const joined = cellTexts.join('\n');
                    if ((item.query && joined.includes(item.query)) || (item.answer && joined.includes(item.answer))) {
                        return nb.display_name;
                    }
                }
            } catch (e) {
                continue;
            }
        }
    } catch (e) {
        console.warn('findNotebookForHistory failed', e);
    }
    return null;
}

// Save chat history back into a named saved notebook (POST /api/notebooks/save)
async function saveChatHistoryToNotebook(notebookName, chatHistoryArr) {
    if (!notebookName) throw new Error('Notebook name required');
    const resp = await fetch(`/api/notebooks/${encodeURIComponent(notebookName)}`);
    const data = await resp.json();
    if (data.error) throw new Error(data.error);

    const payload = {
        name: notebookName,
        cells: data.cells || [],
        chat_data: data.chat_data || {},
        chat_history: chatHistoryArr || []
    };

    const saveResp = await fetch('/api/notebooks/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });

    if (!saveResp.ok) {
        const txt = await saveResp.text();
        throw new Error('Save failed: ' + txt);
    }

    return true;
}
//// Add this NEW function after loadSavedNotebooks()
async function openSavedNotebook(notebookName) {
    try {
        const resp = await fetch(`/api/notebooks/${encodeURIComponent(notebookName)}`);
        const cells = await resp.json();

        if (cells.error) {
            await customAlert('Error loading notebook: ' + cells.error);
            return;
        }

        // Clear current workspace
        document.getElementById('cells').innerHTML = '';

        // Load each cell from the saved notebook
        cells.forEach(cellData => {
            const cellDiv = document.createElement('div');
            cellDiv.className = 'cell';
            cellDiv.innerHTML = `
                <div class="cell-input">
                    <textarea placeholder="Enter Python code or natural language..." 
                              onkeydown="if(event.ctrlKey && event.key==='Enter') runCell(this)">${cellData.input || ''}</textarea>
                    <button onclick="runCell(this.previousElementSibling)">▶ Run</button>
                </div>
                <div class="cell-output">${cellData.output || ''}</div>
            `;
            document.getElementById('cells').appendChild(cellDiv);
        });

        // Switch to notebook view
        switchTab('notebook');
        await customAlert(`Notebook "${notebookName}" loaded successfully!`);

    } catch (e) {
        await customAlert('Failed to load notebook: ' + e.message);
    }
}


// Modify your existing newNotebook function to include auto-save


// --- File Upload Logic ---
async function uploadFile() {
    const fileInput = document.getElementById('file-input');
    const statusDiv = document.getElementById('upload-status');

    if (!fileInput.files || fileInput.files.length === 0) {
        statusDiv.innerHTML = '<span style="color: #ef4444;">Please select a file first.</span>';
        return;
    }

    const file = fileInput.files[0];
    const formData = new FormData();
    formData.append('file', file);

    statusDiv.innerHTML = '<span style="color: var(--text-secondary);">Uploading and processing... <span class="pulse-icon" style="display:inline-block;width:8px;height:8px;background:var(--text-secondary);border-radius:50%;"></span></span>';

    try {
        const response = await fetch('/api/upload_file', {
            method: 'POST',
            body: formData
        });

        const result = await response.json();

        if (response.ok) {
            statusDiv.innerHTML = `<div style="color: #10b981; font-weight: 500;">✅ ${result.message}</div>`;
            // Show context-aware suggestion chips for uploaded file
            const fileName = file.name;
            updateSuggestionChips(getSuggestionsForFile(fileName));
            // Optional: clear input
            fileInput.value = '';

            // Ask user if they'd like to index for RAG
            setTimeout(async () => {
                const wantToindex = confirm(`Would you like to index '${fileName}' for AI Semantic Search (RAG)?\n\nThis allows the AI to deeply read and compare text, but may take a few moments.`);
                if (wantToindex) {
                    statusDiv.innerHTML = '<span style="color: var(--text-secondary);">Starting background indexing...</span>';
                    try {
                        const ragResp = await fetch('/api/index_rag', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ source_name: fileName })
                        });
                        const ragResult = await ragResp.json();
                        statusDiv.innerHTML = `<div style="color: #10b981; font-weight: 500;">✅ ${ragResult.message}</div>`;
                    } catch (err) {
                        statusDiv.innerHTML = `<span style="color: #ef4444;">Failed to start indexing: ${err.message}</span>`;
                    }
                }
            }, 300);

        } else {
            statusDiv.innerHTML = `<span style="color: #ef4444;">Error: ${result.detail || 'Upload failed'}</span>`;
        }
    } catch (e) {
        statusDiv.innerHTML = `<span style="color: #ef4444;">Network Error: ${e.message}</span>`;
    }
}

// Fetch settings when the settings drawer is opened
async function loadLLMSettings() {
    try {
        const resp = await fetch('/api/llm/settings');
        const config = await resp.json();

        document.getElementById('llm-provider').value = config.provider || 'custom';
        document.getElementById('llm-openai-model').value = config.openai_model || 'gpt-4o';
    } catch (e) {
        console.error("Failed to load LLM settings", e);
    }
}

// Save settings back to the server
async function saveLLMSettings() {
    const data = {
        provider: document.getElementById('llm-provider').value,
        openai_model: document.getElementById('llm-openai-model').value
    };

    try {
        const resp = await fetch('/api/llm/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        const result = await resp.json();

        const statusEl = document.getElementById('llm-status-msg');
        statusEl.innerText = result.message || "Settings Saved!";
        setTimeout(() => statusEl.innerText = "", 3000);
    } catch (e) {
        await customAlert("Failed to save settings: " + e.message);
    }
}

// Update your existing toggleDrawer function to fetch settings when opened
const originalToggleDrawer = window.toggleDrawer;
window.toggleDrawer = function (drawerName) {
    if (drawerName === 'settings') {
        loadLLMSettings(); // Load values every time user opens the settings tab
    }
    // Call the original function to handle the animation and closing other drawers
    if (originalToggleDrawer) {
        originalToggleDrawer(drawerName);
    }
};

// --- Image Enlarge Modal for AI Chat ---
document.addEventListener("DOMContentLoaded", () => {
    // 1. Create Modal Container
    const modal = document.createElement("div");
    modal.id = "ai-image-modal";
    modal.style.cssText = `
        display: none;
        position: fixed;
        top: 0; left: 0; width: 100vw; height: 100vh;
        background: rgba(0, 0, 0, 0.85);
        z-index: 100000;
        justify-content: center;
        align-items: center;
        backdrop-filter: blur(4px);
        opacity: 0;
        transition: opacity 0.2s ease;
    `;

    // 2. Create Modal Image
    const modalImg = document.createElement("img");
    modalImg.style.cssText = `
        max-width: 90vw;
        max-height: 90vh;
        border-radius: 8px;
        box-shadow: 0 10px 25px rgba(0,0,0,0.5);
        object-fit: contain;
        transform: scale(0.95);
        transition: transform 0.1s ease;
    `;
    modal.appendChild(modalImg);
    document.body.appendChild(modal);

    let scale = 1;
    let isDragging = false;
    let startX = 0, startY = 0, translateX = 0, translateY = 0;

    const updateTransform = () => {
        modalImg.style.transform = `translate(${translateX}px, ${translateY}px) scale(${scale})`;
    };

    // 3. Zoom with mouse wheel
    modal.addEventListener("wheel", (e) => {
        if (modal.style.display !== "flex") return;
        e.preventDefault();
        const zoomIntensity = 0.15;
        const wheel = e.deltaY < 0 ? 1 : -1;
        const newScale = scale + (wheel * zoomIntensity * scale); // Relative scaling
        if (newScale >= 0.5 && newScale <= 15) { // Min 0.5x, Max 15x
            scale = newScale;
            updateTransform();
        }
    });

    // 4. Click and Drag for Panning
    modalImg.addEventListener("mousedown", (e) => {
        e.preventDefault();
        isDragging = true;
        startX = e.clientX - translateX;
        startY = e.clientY - translateY;
        modalImg.style.cursor = "grabbing";
    });

    window.addEventListener("mousemove", (e) => {
        if (!isDragging) return;
        e.preventDefault();
        translateX = e.clientX - startX;
        translateY = e.clientY - startY;
        updateTransform();
    });

    window.addEventListener("mouseup", () => {
        if (isDragging) {
            isDragging = false;
            modalImg.style.cursor = "grab";
        }
    });

    // Reset and Close logic
    const closeModal = () => {
        modal.style.opacity = "0";
        setTimeout(() => {
            modal.style.display = "none";
            scale = 1; translateX = 0; translateY = 0; // Reset
            updateTransform();
        }, 200);
    };

    // Close on clicking backdrop (not the image itself)
    modal.addEventListener("click", (e) => {
        if (e.target === modal) {
            closeModal();
        }
    });

    // 5. Add Global CSS for cursor style mapping to zoomable images in chat
    const style = document.createElement("style");
    style.innerHTML = ".ai-msg img { cursor: zoom-in; transition: transform 0.1s; } .ai-msg img:hover { transform: scale(1.02); box-shadow: 0 4px 12px rgba(0,0,0,0.1); }";
    document.head.appendChild(style);

    // 6. Event Delegation for any image clicked inside AI chat window
    document.body.addEventListener("click", (e) => {
        if (e.target.tagName && e.target.tagName.toLowerCase() === "img") {
            // Check if the clicked image is inside the chat area (.ai-msg or .ai-content-area)
            if (e.target.closest('.ai-msg') || e.target.closest('#ai-content-area')) {
                modalImg.src = e.target.src;
                modal.style.display = "flex";
                modalImg.style.cursor = "grab";

                // Initialize clean slate
                scale = 1; translateX = 0; translateY = 0;
                updateTransform();

                // Trigger reflow & fade in
                void modal.offsetWidth;
                modal.style.opacity = "1";
            }
        }
    });

    // Handle escape key
    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape" && modal.style.display === "flex") {
            closeModal();
        }
    });
});
