let currentAbortController = null;
let attachedFiles = [];
// Global chat history
let chatHistory = [];
let messagePairs = []; // Tracks {userBubble, assistantBubble, prompt} for editing
let cellCount = 0;
let lastDataForChart = null;
let pyodide = null; // Global Pyodide instance
let showCode = true; // Global toggle: set to false to hide code blocks in AI responses

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
    type: 'confirm' // 'alert', 'confirm', 'prompt'
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
    cancelBtn.style.display = 'inline-block';
    confirmBtn.classList.remove('danger');
    confirmBtn.textContent = 'Confirm';

    // Configure based on type
    const type = options.type || 'alert';
    dialogConfig.type = type;

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
        } else {
            confirmBtn.classList.remove('danger');
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

function confirmCustomDialog() {
    const overlay = document.getElementById('custom-dialog-overlay');
    const inputEl = document.getElementById('custom-dialog-input');
    
    let result = true;
    if (dialogConfig.type === 'prompt') {
        result = inputEl.value;
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

async function customPrompt(message, defaultValue = '') {
    return await showCustomDialog('Input Required', message, { type: 'prompt', defaultValue });
}

// Generate a default notebook name with timestamp
function generateNotebookName() {
    const now = new Date();
    const date = now.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
    const time = now.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: true });
    return `Notebook ${date} ${time}`;
}

// Multi-Chat System
let currentChatId = null;
let chats = [];
let currentNotebookId = 'default_notebook';

// =======================
// ICON SVG CONSTANTS
// =======================

const ICON_MAXIMIZE = `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 3h6v6"/><path d="m21 3-7 7"/><path d="m3 21 7-7"/><path d="M9 21H3v-6"/></svg>`;

const ICON_MINIMIZE = `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-minimize-icon lucide-minimize"><path d="M8 3v3a2 2 0 0 1-2 2H3"/><path d="M21 8h-3a2 2 0 0 1-2-2V3"/><path d="M3 16h3a2 2 0 0 1 2 2v3"/><path d="M16 21v-3a2 2 0 0 1 2-2h3"/></svg>`;

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



// --- script.js ---
// --- script.js ---
async function initPyodide() {
    const dot = document.getElementById('status-dot');
    const text = document.getElementById('status-text');
    text.innerText = "Loading Python Kernel...";
    dot.style.color = "orange";

    try {
        pyodide = await loadPyodide();
        // 1. Load Libraries
        await pyodide.loadPackage(["micropip", "numpy", "pandas", "matplotlib"]);
        // 2. Initialize Kernel
        await pyodide.runPythonAsync(`
            import sys
            import io
            import base64
            import ast
            import gc
            import json
            # Import HTTP Client for Pyodide
            from pyodide.http import pyfetch
 
            # --- CONFIG: MATPLOTLIB ---
            import matplotlib
            matplotlib.use("Agg", force=True) 
            import matplotlib.pyplot as plt
            def no_op_show(*args, **kwargs): pass
            plt.show = no_op_show
 
            # --- NEW: DB BRIDGE FUNCTION ---
            # This function lets the user run: df = await query_db("SELECT * FROM table")
            async def query_db(sql_query):
                try:
                    # Send SQL to main.py
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
                    # Convert List of Dicts -> Pandas DataFrame
                    if data:
                        return pd.DataFrame(data)
                    else:
                        print("✅ Query executed successfully (No rows returned).")
                        return pd.DataFrame()
                except Exception as e:
                    print(f"⚠️ Network Error: {e}")
                    return None
 
            # --- SETUP USER NAMESPACE ---
            user_ns = {}
            user_ns['__name__'] = '__main__'
            user_ns['np'] = __import__('numpy')
            user_ns['pd'] = __import__('pandas')
            user_ns['plt'] = plt
            # INJECT THE DB FUNCTION INTO USER SCOPE
            user_ns['query_db'] = query_db
 
            def run_cell_logic(code_str):
                stdout_capture = io.StringIO()
                sys.stdout = stdout_capture
                sys.stderr = stdout_capture
                html_out = None
                image_b64 = None
                try:
                    tree = ast.parse(code_str)
                    last_node = tree.body[-1] if tree.body else None
                    if isinstance(last_node, ast.Expr):
                        exec(compile(ast.Module(body=tree.body[:-1], type_ignores=[]), "<string>", "exec"), user_ns)
                        result = eval(compile(ast.Expression(body=last_node.value), "<string>", "eval"), user_ns)
                        if hasattr(result, "_repr_html_"):
                            html_out = result._repr_html_()
                        elif result is not None:
                            print(result)
                    else:
                        exec(code_str, user_ns)
 
                except Exception as e:
                    print(f"Error: {e}")
                finally:
                    sys.stdout = sys.__stdout__
                    sys.stderr = sys.__stderr__
 
                if plt.get_fignums():
                    try:
                        buf = io.BytesIO()
                        plt.savefig(buf, format='png', bbox_inches='tight', dpi=100)
                        buf.seek(0)
                        image_b64 = base64.b64encode(buf.read()).decode('utf-8')
                    except Exception as e:
                        print(f"Plotting Error: {e}")
                    finally:
                        plt.close('all')
                        gc.collect()
 
                return {
                    "text": stdout_capture.getvalue(),
                    "html": html_out,
                    "image": image_b64
                }
        `);

        text.innerText = "Online";
        dot.style.color = "#4ade80";
        console.log("Pyodide Ready");
    } catch (e) {
        text.innerText = "Kernel Failed";
        dot.style.color = "red";
        console.error(e);
    }
}// --- script.js ---
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

            # --- FIX: Import Pandas HERE so query_db can see it ---

            import pandas as pd

            import numpy as np
 
            # HTTP Client

            from pyodide.http import pyfetch
 
            # --- MATPLOTLIB SETUP ---

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
  setInterval(checkStatus, 180000); // 3 minutes

  document.getElementById("run-btn")?.addEventListener("click", runAIQuery);
  document.addEventListener("click", (e) => {
  const btn = e.target.closest("[data-add-to-cell='1']");
  if (!btn) return;

  const encodedCode = btn.getAttribute("data-code") || "";
  addGeneratedCodeToCell(encodedCode);
});

};


// --- 2. NOTEBOOK KERNEL ---

async function runCode(id) {
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

    try {
        await pyodide.loadPackagesFromImports(code);

        // 2. EXECUTE CODE (Supports await automatically!)
        // We pass 'user_ns' so variables are saved.
        let result = await pyodide.runPythonAsync(code, {
            globals: pyodide.globals.get("user_ns")
        });

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
        outDiv.innerHTML += `<div style="color:#ef4444; margin-top:5px;"><strong>Error:</strong> ${e.message}</div>`;
        // Show error-specific suggestion chips
        updateSuggestionChips(getSuggestionsForCode(code, true, false, false));
    } finally {
        btn.innerText = "▶";
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
                <textarea class="code-editor" oninput="autoResize(this)" rows="1"></textarea>
                <div class="cell-output" id="out-${cellCount}"></div>
            </div>
        </div>`;

    const barHtml = `<div class="add-cell-bar">
                        <button class="add-cell-btn" onclick="addCodeCell(this)">＋ Code</button>
                        <button class="add-cell-btn secondary" onclick="addTextCell(this)">＋ Text</button>
                     </div>`;

    if (button) {
        // If clicked from a bar between cells
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
 * Edit a message - ChatGPT-style behavior
 * Removes the selected message AND all subsequent messages
 */
function editMessage(messageIndex) {
  const messagePair = messagePairs[messageIndex];
  if (!messagePair) return;
  
  const input = document.getElementById('prompt-input');
  if (!input) return;
  
  // If AI is currently generating, stop it first
  if (currentAbortController) {
    currentAbortController.abort();
    currentAbortController = null;
    setAILoading(false);
  }
  
  // Load the original prompt into the input field
  input.value = messagePair.prompt;
  
  // Auto-resize the input
  if (typeof autoResize === 'function') {
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 140) + 'px';
  }
  
  // Focus the input
  input.focus();
  
  // Remove this message and ALL subsequent messages from DOM
  // We need to remove from messageIndex onwards
  for (let i = messageIndex; i < messagePairs.length; i++) {
    const pair = messagePairs[i];
    if (pair.userBubble && pair.userBubble.parentNode) {
      pair.userBubble.remove();
    }
    if (pair.assistantBubble && pair.assistantBubble.parentNode) {
      pair.assistantBubble.remove();
    }
  }
  
  // Remove from chat history
  // Each message pair = 2 entries in chatHistory (user + assistant)
  // So if we're editing message at index 2, we need to remove from chatHistory[4] onwards
  const chatStartIndex = messageIndex * 2;
  if (chatStartIndex < chatHistory.length) {
    chatHistory.splice(chatStartIndex);
  }
  
  // Remove from messagePairs array (from messageIndex onwards)
  messagePairs.splice(messageIndex);
}

// ======================================================
// MULTI-CHAT SYSTEM FUNCTIONS
// ======================================================

/**
 * Create a new chat session
 */
function createNewChat() {
  // Save current chat before creating new one
  if (currentChatId) {
    saveCurrentChat();
  }
  
  const newChat = {
    id: 'chat_' + Date.now(),
    title: 'New Chat',
    messages: [],
    chatHistory: [],
    createdAt: Date.now(),
    updatedAt: Date.now()
  };
  
  chats.push(newChat);
  currentChatId = newChat.id;
  
  // Clear UI
  clearChatUI();
  
  // Update sidebar
  renderChatList();
  
  // Save to localStorage
  saveChatsToLocalStorage();
  
  // Close drawer if open
  closeDrawer('chats');
}

/**
 * Switch to a different chat
 */
function switchChat(chatId) {
  if (chatId === currentChatId) {
    closeDrawer('chats');
    return; // Already on this chat
  }
  
  // Save current chat before switching
  if (currentChatId) {
    saveCurrentChat();
  }
  
  // Switch to new chat
  currentChatId = chatId;
  
  // Load chat to UI
  loadChatToUI(chatId);
  
  // Update sidebar active state
  renderChatList();
  
  // Save current chat ID
  saveChatsToLocalStorage();
  
  // Close drawer
  closeDrawer('chats');
}

/**
 * Save current chat state
 */
function saveCurrentChat() {
  const chat = chats.find(c => c.id === currentChatId);
  if (chat) {
    chat.messages = JSON.parse(JSON.stringify(messagePairs.map(pair => ({
      prompt: pair.prompt
    }))));
    chat.chatHistory = JSON.parse(JSON.stringify(chatHistory));
    chat.updatedAt = Date.now();
  }
}

/**
 * Load chat to UI
 */
function loadChatToUI(chatId) {
  const chat = chats.find(c => c.id === chatId);
  if (!chat) return;
  
  // Clear current UI
  clearChatUI();
  
  // Restore chat history
  chatHistory = JSON.parse(JSON.stringify(chat.chatHistory || []));
  
  // Re-render messages from chat history
  renderMessagesFromHistory();
}

/**
 * Clear chat UI
 */
function clearChatUI() {
  const contentArea = document.getElementById('ai-content-area');
  if (contentArea) {
    contentArea.innerHTML = '';
  }
  messagePairs = [];
  chatHistory = [];
}

/**
 * Render messages from chat history
 */
function renderMessagesFromHistory() {
  const contentArea = document.getElementById('ai-content-area');
  if (!contentArea) return;
  
  // Process pairs from chatHistory (user + assistant)
  for (let i = 0; i < chatHistory.length; i += 2) {
    const userMsg = chatHistory[i];
    const assistantMsg = chatHistory[i + 1];
    
    if (userMsg && userMsg.role === 'user') {
      // Create user bubble
      const userBubble = document.createElement('div');
      userBubble.className = 'ai-msg user';
      userBubble.style.padding = '16px 10px 10px 10px';
      userBubble.style.background = '#eef2ff';
      userBubble.style.borderRadius = '10px';
      userBubble.style.margin = '8px 0 8px auto';
      userBubble.style.width = 'fit-content';
      userBubble.style.maxWidth = '70%';
      userBubble.style.wordWrap = 'break-word';
      userBubble.style.whiteSpace = 'pre-wrap';
      userBubble.style.overflowWrap = 'break-word';
      userBubble.innerText = userMsg.content;
      contentArea.appendChild(userBubble);
      
      // Create assistant bubble if exists
      let assistantBubble = null;
      if (assistantMsg && assistantMsg.role === 'assistant') {
        assistantBubble = document.createElement('div');
        assistantBubble.className = 'ai-msg assistant';
        assistantBubble.style.padding = '16px 10px 10px 20px';
        assistantBubble.style.background = '#ffffff';
        assistantBubble.style.border = '1px solid #e6edf3';
        assistantBubble.style.borderRadius = '10px';
        assistantBubble.style.margin = '8px 0';
        
        // Render response
        const header = document.createElement('div');
        header.style.display = 'flex';
        header.style.alignItems = 'center';
        header.style.gap = '10px';
        header.innerHTML = '<strong>Assistant</strong>';
        
        const body = document.createElement('div');
        body.style.marginTop = '8px';
        
        // Render markdown
        const rawHtml = marked.parse(assistantMsg.content || '');
        const sanitized = DOMPurify.sanitize(rawHtml);
        body.innerHTML = sanitized;
        
        assistantBubble.appendChild(header);
        assistantBubble.appendChild(body);
        contentArea.appendChild(assistantBubble);
      }
      
      // Track in messagePairs
      const pairIndex = messagePairs.length;
      messagePairs.push({
        userBubble: userBubble,
        assistantBubble: assistantBubble,
        prompt: userMsg.content
      });
      
      // Add edit button
      addEditButton(userBubble, userMsg.content, pairIndex);
    }
  }
  
  // Scroll to bottom
  const tray = document.getElementById('ai-response-tray');
  if (tray) {
    tray.scrollTop = tray.scrollHeight;
  }
}

/**
 * Render chat list in sidebar
 */
function renderChatList() {
  const chatList = document.getElementById('chat-list');
  if (!chatList) return;
  
  chatList.innerHTML = '';
  
  if (chats.length === 0) {
    chatList.innerHTML = '<div class="chat-list-empty">No chats yet.<br>Click "New Chat" to start.</div>';
    return;
  }
  
  // Sort chats by updatedAt (newest first)
  const sortedChats = [...chats].sort((a, b) => b.updatedAt - a.updatedAt);
  
  sortedChats.forEach(chat => {
    const item = document.createElement('div');
    item.className = 'chat-list-item' + (chat.id === currentChatId ? ' active' : '');
    item.dataset.chatId = chat.id;
    item.onclick = () => switchChat(chat.id);

    const titleContainer = document.createElement('div');
    titleContainer.className = 'chat-title-container';

    const title = document.createElement('div');
    title.className = 'chat-title';
    title.textContent = chat.title || 'New Chat';

    const editBtn = document.createElement('button');
    editBtn.className = 'chat-edit-btn';
    editBtn.setAttribute('aria-label', 'Rename chat');
    editBtn.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-pen-line-icon lucide-pen-line"><path d="M13 21h8"/><path d="M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z"/></svg>`;
    // Prevent parent click (switchChat) when clicking edit
    editBtn.onclick = (e) => {
      e.stopPropagation();
      startChatRename(chat.id);
    };

    titleContainer.appendChild(title);
    titleContainer.appendChild(editBtn);

    const date = document.createElement('div');
    date.className = 'chat-date';
    date.textContent = formatChatDate(chat.updatedAt);

    item.appendChild(titleContainer);
    item.appendChild(date);
    chatList.appendChild(item);
  });
}

/**
 * Format date for chat list
 */
function formatChatDate(timestamp) {
  const now = Date.now();
  const diff = now - timestamp;
  
  const minutes = Math.floor(diff / 60000);
  const hours = Math.floor(diff / 3600000);
  const days = Math.floor(diff / 86400000);
  
  if (minutes < 1) return 'Just now';
  if (minutes < 60) return `${minutes}m ago`;
  if (hours < 24) return `${hours}h ago`;
  if (days < 7) return `${days}d ago`;
  
  const date = new Date(timestamp);
  return date.toLocaleDateString();
}

/**
 * Update chat title from first message
 */
function updateChatTitle(chatId, title) {
  const chat = chats.find(c => c.id === chatId);
  if (chat && chat.title === 'New Chat') {
    // Extract first 50 chars or first line
    const cleanTitle = title.trim().substring(0, 50).split('\n')[0];
    chat.title = cleanTitle || 'New Chat';
    chat.updatedAt = Date.now();
    renderChatList();
    saveChatsToLocalStorage();
  }
}

/**
 * Start inline rename for a chat
 */
function startChatRename(chatId) {
  const selector = `[data-chat-id="${chatId}"] .chat-title-container`;
  const container = document.querySelector(selector);
  if (!container) return;
  // Avoid duplicate inputs
  if (container.querySelector('input')) return;

  const titleDiv = container.querySelector('.chat-title');
  const current = titleDiv ? titleDiv.textContent : '';

  const input = document.createElement('input');
  input.type = 'text';
  input.value = current;
  input.className = 'chat-title-input';

  // Replace the title div with input
  container.replaceChild(input, titleDiv);
  input.focus();
  input.select();

  function finish(newVal) {
    const value = (newVal || input.value || '').trim() || 'New Chat';
    const chat = chats.find(c => c.id === chatId);
    if (chat) {
      chat.title = value;
      chat.updatedAt = Date.now();
      saveChatsToLocalStorage();
      renderChatList();
    }
  }

  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      finish(input.value);
    } else if (e.key === 'Escape') {
      renderChatList();
    }
  });

  input.addEventListener('blur', () => finish(input.value));
}

/**
 * Save chats to localStorage
 */
function saveChatsToLocalStorage() {
  try {
    const data = {
      currentNotebookId,
      notebooks: {
        [currentNotebookId]: {
          currentChatId,
          chats: chats
        }
      }
    };
    
    localStorage.setItem('notebook_chats', JSON.stringify(data));
  } catch (e) {
    console.error('Failed to save chats to localStorage:', e);
  }
}

/**
 * Load chats from localStorage
 */
function loadChatsFromLocalStorage() {
  try {
    const data = JSON.parse(localStorage.getItem('notebook_chats'));
    if (data && data.notebooks && data.notebooks[currentNotebookId]) {
      const notebook = data.notebooks[currentNotebookId];
      chats = notebook.chats || [];
      currentChatId = notebook.currentChatId;
      
      // Load the current chat
      if (currentChatId && chats.find(c => c.id === currentChatId)) {
        loadChatToUI(currentChatId);
      } else if (chats.length > 0) {
        // Load most recent chat
        const sortedChats = [...chats].sort((a, b) => b.updatedAt - a.updatedAt);
        currentChatId = sortedChats[0].id;
        loadChatToUI(currentChatId);
      }
    }
    
    // If no chats exist, create first one
    if (chats.length === 0) {
      createNewChat();
    }
    
    // Render chat list
    renderChatList();
  } catch (e) {
    console.error('Failed to load chats from localStorage:', e);
    // Create initial chat on error
    createNewChat();
  }
}

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
    
    const startTime = Date.now();
    const timerEl = document.createElement('span');
    timerEl.style.cssText = "margin-left:auto;font-family:'Fira Code', monospace;font-size:0.85rem;color:#64748b;";
    timerEl.innerText = '0.0s';

    // Append user's message (float right, dynamic width up to 70% with word-wrap)
    const userBubble = document.createElement('div');
    userBubble.className = 'ai-msg user';
    userBubble.style.padding = '16px 10px 10px 10px';
    userBubble.style.background = '#eef2ff';
    userBubble.style.borderRadius = '10px';
    userBubble.style.margin = '8px 0 8px auto'; // margin-left auto pushes right
    userBubble.style.width = 'fit-content'; // shrink to content
    userBubble.style.maxWidth = '70%'; // but max 70% of container
    userBubble.style.wordWrap = 'break-word';
    userBubble.style.whiteSpace = 'pre-wrap';
    userBubble.style.overflowWrap = 'break-word';
    userBubble.innerText = prompt;
    contentArea.appendChild(userBubble);
    
    // Add edit button immediately to user message
    const messageIndex = messagePairs.length;
    messagePairs.push({ userBubble, assistantBubble: null, prompt }); // Add placeholder for assistant
    addEditButton(userBubble, prompt, messageIndex);

    // Assistant placeholder
    const assistantBubble = document.createElement('div');
    assistantBubble.className = 'ai-msg assistant';
    assistantBubble.style.padding = '16px 10px 10px 20px';
    assistantBubble.style.background = '#ffffff';
    assistantBubble.style.border = '1px solid #e6edf3';
    assistantBubble.style.borderRadius = '10px';
    assistantBubble.style.margin = '8px 0';
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

    const resp = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        prompt: prompt,
        notebook_cells: cells,
        variables: activeVars,
        chat_history: chatHistory
      }),
      signal: currentAbortController.signal,
    });

        if (!resp.ok) throw new Error("Server Error");

        const data = await resp.json();
        clearInterval(timerInt);

        const totalTime = ((Date.now() - startTime) / 1000).toFixed(2);
        const toolUsed = data.tool_used || ""; // Get the intent/tool used

        let answer = data.answer || "";
        
        // Update history
        chatHistory.push({ role: "user", content: prompt });
        chatHistory.push({ role: "assistant", content: answer });
        
        let codeHtml = "";
        const originalAnswer = answer;

        // Only show Add to Cell for GENERATE_CODE, not for EXPLAIN_CODE or other tools
        const isGenerateIntent = toolUsed.toUpperCase().includes("GENERATE");
        
        const codeMatch = originalAnswer.match(/```python([\s\S]*?)```/);
        if (codeMatch && isGenerateIntent) {
            // Only process code blocks if it's a GENERATE_CODE intent
            const code = codeMatch[1].trim();
            if (!showCode) {
                // User chose to hide code: remove any fenced code blocks
                answer = stripCodeBlocks(originalAnswer);
                codeHtml = ""; // do not render add-to-cell
            } else {
                // Show code: strip the python block from the visible answer and provide add-to-cell UI
                answer = originalAnswer.replace(codeMatch[0], "").trim();

                // Build code block element safely
                const codeBlock = document.createElement('div');
                codeBlock.style.marginTop = '10px';
                codeBlock.style.padding = '10px';
                codeBlock.style.background = '#e0f2fe';
                codeBlock.style.borderRadius = '8px';
                codeBlock.style.borderLeft = '4px solid #3b82f6';

                const pre = document.createElement('pre');
                pre.style.fontSize = '0.85rem';
                pre.style.overflowX = 'auto';
                const codeEl = document.createElement('code');
                codeEl.textContent = code;
                pre.appendChild(codeEl);

                const btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 'add-to-cell-btn';
                btn.setAttribute('data-add-to-cell', '1');
                btn.setAttribute('data-code', encodeURIComponent(code));
                btn.style.cssText = 'background:#3b82f6;color:white;border:none;padding:6px 12px;border-radius:6px;cursor:pointer;margin-top:8px';
                btn.innerText = 'Add to Cell';

                codeBlock.appendChild(pre);
                codeBlock.appendChild(btn);
                codeHtml = codeBlock; // DOM element
            }
        } else if (codeMatch && !isGenerateIntent) {
            // If it's EXPLAIN_CODE or other intent, strip code blocks but don't show Add to Cell
            answer = stripCodeBlocks(originalAnswer);
            codeHtml = "";
        } else {
            // No explicit python block found. If showCode is false, strip any code fences from answer.
            if (!showCode) answer = stripCodeBlocks(answer);
        }

        // Render assistant response into existing assistantBubble
        assistantBubble.innerHTML = '';
        const header = document.createElement('div');
        header.style.display = 'flex';
        header.style.justifyContent = 'space-between';
        header.style.alignItems = 'center';
        header.style.marginBottom = '8px';
        const title = document.createElement('strong');
        title.innerText = 'Assistant';
        const timeLabel = document.createElement('span');
        timeLabel.style.color = '#888';
        timeLabel.style.fontSize = '0.75rem';
        timeLabel.innerText = `Took ${totalTime}s`;
        header.appendChild(title);
        header.appendChild(timeLabel);

        const body = document.createElement('div');
        body.style.fontSize = '0.95rem';
        body.style.lineHeight = '1.5';
        // Convert markdown to HTML if marked is available, and sanitize
        if (typeof marked !== 'undefined' && typeof DOMPurify !== 'undefined') {
            body.innerHTML = DOMPurify.sanitize(marked.parse(answer || ''));
        } else {
            body.innerText = answer;
        }

        assistantBubble.appendChild(header);
        assistantBubble.appendChild(body);
        if (codeHtml) assistantBubble.appendChild(codeHtml);

        if (tray) tray.scrollTop = tray.scrollHeight;

        // Clear attached files after successful send
        attachedFiles = [];
        const chipsEl = document.getElementById('ai-file-chips');
        if (chipsEl) chipsEl.innerHTML = '';
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
        content.style.marginRight = '';
      }
      // Re-enable transitions after a frame for future opens
      requestAnimationFrame(() => {
        mini.style.transition = '';
        if (content) content.style.transition = '';
      });
      return;
    }

    // Opening
    isOpen = true;
    mini.classList.add("open");
    mini.setAttribute("aria-hidden", "false");

    // Restore to maximized (docked) mode if it was previously
    if (popupMode === 'max') {
      mini.classList.add("docked");
      const content = document.querySelector(".content");
      if (content) {
        const currentWidth = mini.style.getPropertyValue('--ai-panel-width') || '450px';
        content.classList.add("ai-docked");
        content.style.marginRight = currentWidth;
      }
    } else {
      // ensure undocked when opening in min mode
      mini.classList.remove("docked");
    }

    if (input) input.focus();
  };

  fab.addEventListener("click", () => setOpen(!isOpen));
  if (closeBtn) closeBtn.addEventListener("click", () => setOpen(false));

  if (maxBtn) {
    maxBtn.addEventListener("click", () => {
      // Toggle docked state instead of expanded
      const isDocked = mini.classList.toggle("docked");
      
      // Save the new mode to state and localStorage
      popupMode = isDocked ? 'max' : 'min';
      localStorage.setItem('ai-popup-mode', popupMode);
      
      // Adjust main content margin
      const content = document.querySelector(".content");
      if (content) {
        if (isDocked) {
          // Use saved width or default
          const currentWidth = mini.style.getPropertyValue('--ai-panel-width') || '450px';
          content.classList.add("ai-docked");
          content.style.marginRight = currentWidth;
        } else {
          content.classList.remove("ai-docked");
          content.style.marginRight = '';
        }
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
    const chip = document.createElement("div");
    chip.className = "ai-file-chip";
    const nameSpan = document.createElement("span");
    nameSpan.textContent = file.name;
    nameSpan.title = file.name;
    const removeBtn = document.createElement("button");
    removeBtn.innerHTML = "×";
    removeBtn.title = "Remove";
    removeBtn.addEventListener("click", () => {
      attachedFiles = attachedFiles.filter((f) => f !== file);
      chip.remove();
    });
    chip.appendChild(nameSpan);
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

function addGeneratedCodeToCell(encodedCode) {
  const code = decodeURIComponent(encodedCode || "");

  addCodeCell();

  const editors = document.querySelectorAll(".code-editor");
  const lastEditor = editors[editors.length - 1];

  if (!lastEditor) return;

  // Check if CodeMirror is initialized
  if (lastEditor.nextSibling && lastEditor.nextSibling.classList && lastEditor.nextSibling.classList.contains('CodeMirror')) {
    const cm = lastEditor.nextSibling.CodeMirror;
    if (cm) {
      cm.setValue(code);
      cm.focus();
    }
  } else {
    lastEditor.value = code;
    autoResize(lastEditor);
    lastEditor.focus();
  }
}


// --- 4. TABS & DB (Preserved) ---
function switchTab(view) {
  const workspaceView = document.getElementById("workspace-view");
  const connectionsView = document.getElementById("connections-view");
  
  // NEW: your floating AI widget wrapper
  const aiWidget = document.getElementById("ai-widget");
  const aiMini = document.getElementById("ai-mini");

  // Close all drawers when switching views
  document.querySelectorAll('.drawer').forEach(d => {
    d.classList.remove('open');
  });
  document.querySelector('.content')?.classList.remove('drawer-open');

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
      break;

    default: // "workspace" 
      if (workspaceView) workspaceView.style.display = "flex";
      if (aiWidget) aiWidget.style.display = "block";
      break;
  }
}

async function loadConnections() {
    // Add cache-busting to prevent browser from using old data
    const resp = await fetch('/api/connections', {
        cache: 'no-store',
        headers: {
            'Cache-Control': 'no-cache',
            'Pragma': 'no-cache'
        }
    });
    const configs = await resp.json();
    const list = document.getElementById('connection-list');
    list.innerHTML = '';

    // The trash icon SVG
    const trash = `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>`;

    for (const name in configs) {
        if (name === "detail") continue;
        const div = document.createElement('div');
        div.className = `conn-item ${configs[name].active ? 'active' : ''}`;

        // We create the inner HTML with a specific button for deleting
        div.innerHTML = `
            <span style="flex:1" onclick="switchConnection('${name}')">${name} ${configs[name].active ? '✓' : ''}</span>
            <button class="delete-db-btn" onclick="deleteDB(event, '${name}')">${trash}</button>
        `;
        list.appendChild(div);
    }
} async function deleteDB(event, name) {
    event.stopPropagation();

    if (!await customConfirm(`Are you sure you want to delete "${name}"?`, true)) {
        return;
    }

    try {
        console.log('Deleting:', name);

        const resp = await fetch(`/api/connections/${encodeURIComponent(name)}`, {
            method: 'DELETE'
        });

        if (!resp.ok) {
            const error = await resp.json();
            throw new Error(error.detail || 'Delete failed');
        }

        const result = await resp.json();
        console.log('Delete result:', result);

        if (result.status === 'deleted') {
            // Immediately remove from UI without waiting
            const connItem = event.target.closest('.conn-item');
            if (connItem) {
                connItem.remove();
            }

            // Then reload to get fresh data
            setTimeout(() => loadConnections(), 100);
        }

    } catch (error) {
        console.error('Delete error:', error);
        await customAlert('Failed to delete: ' + error.message);
    }
}

function toggleConnForm() {
    const f = document.getElementById('conn-form');
    f.style.display = f.style.display === 'none' ? 'flex' : 'none';
}

async function saveNewConnection() {
    const data = {
        name: document.getElementById('db-alias').value,
        host: document.getElementById('db-host').value,
        port: document.getElementById('db-port').value,
        database: document.getElementById('db-name').value,
        user: document.getElementById('db-user').value,
        password: document.getElementById('db-pass').value
    };
    await fetch('/api/connections', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) });
    toggleConnForm(); loadConnections();
}

async function switchConnection(name) {
    await fetch('/api/connections/activate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name }) });
    loadConnections();
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
    try {
        const resp = await fetch('/health');
        dot.style.color = resp.ok ? '#4ade80' : '#ef4444';
    } catch { dot.style.color = '#ef4444'; }
}




async function saveNotebook() {
    const name = await customPrompt('Enter notebook name:', generateNotebookName());
    if (!name) return;

    const cells = [];

    document.querySelectorAll('.code-cell').forEach(cell => {
        const codeEditor = cell.querySelector('.code-editor');
        const textEditor = cell.querySelector('.text-editor');
        const outputDiv = cell.querySelector('.cell-output');

        if (codeEditor) {
            let code = codeEditor.value;
            // Check if CodeMirror is initialized
            if (codeEditor.nextSibling && codeEditor.nextSibling.classList && codeEditor.nextSibling.classList.contains('CodeMirror')) {
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

    const resp = await fetch('/api/notebooks/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, cells, chat_history: chatHistory })
    });

    const result = await resp.json();
    if (result.error) await customAlert(result.error);
    else await customAlert('Notebook saved!');
}



async function newNotebook() {
    if (!await customConfirm("Start a new notebook? Unsaved changes will be lost.")) return;

    const view = document.getElementById('workspace-view');
    view.innerHTML = '';
    cellCount = 0;

    addCodeCell();
    
    // Reset chat history
    chatHistory = [];
    document.getElementById("ai-content-area").innerHTML = '';
}

// Update loadSavedNotebooks to include cell count and upload button
async function loadSavedNotebooks() {
    const resp = await fetch('/api/notebooks');
    const data = await resp.json();
    const list = document.getElementById('saved-list');

    if (!data || data.length === 0) {
        list.innerHTML = '<p style="color: #888;">No saved notebooks found. Upload or save a notebook to get started.</p>';
        return;
    }

    list.innerHTML = `
        <div style="margin-bottom: 16px;">
            <button onclick="uploadNotebook()" style="padding: 8px 16px; background: #4a9eff; color: white; border: none; border-radius: 4px; cursor: pointer;">
                📤 Upload .ipynb File
            </button>
        </div>
    ` + data.map(nb => `
        <div class="saved-item" onclick="loadNotebookIntoWorkspace('${nb.display_name}')">
            <strong>${nb.display_name}</strong>
            <span style="color: #999; font-size: 12px;">${nb.cell_count} cells | ${nb.timestamp}</span>
        </div>
    `).join('');
}

async function openNotebook(name) {
    const resp = await fetch(`/api/notebooks/${name}`);
    const cells = await resp.json();

    if (cells.error) {
        await customAlert("Could not load notebook.");
        return;
    }
    
    // Handle new format vs legacy format
    let notebookCells = [];
    if (Array.isArray(cells)) {
        notebookCells = cells;
        chatHistory = [];
    } else {
        notebookCells = cells.cells || [];
        chatHistory = cells.chat_history || [];
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
    // 4. Render Chat History
    renderChatHistory(chatHistory);

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
    }
}

function moveCellDown(button) {
    const cell = button.closest('.code-cell');
    const next = cell.nextElementSibling;
    if (next && next.classList.contains('code-cell')) {
        cell.parentNode.insertBefore(next, cell);
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
async function loadSavedNotebooks() {
    const resp = await fetch('/api/notebooks');
    const data = await resp.json();
    const list = document.getElementById('saved-list');

    if (!data || data.length === 0) {
        list.innerHTML = '<p style="color:grey; padding:20px;">No saved notebooks found.</p>';
        return;
    }

    const trash = `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/><path d="M3 6h18"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>`;

    list.innerHTML = data.map(nb => `
        <div class="history-card" onclick="openNotebook('${nb.display_name}')" style="cursor:pointer; border-left:4px solid #3b82f6; padding:15px; background:white; border-radius:8px;">
            <button class="delete-db-btn" onclick="deleteSavedNotebook(event, '${nb.display_name}')">${trash}</button>
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <strong style="color:#1e293b; font-size:1rem;">📂 ${nb.display_name}</strong>
                <span style="font-size:0.75rem; color:#94a3b8;">${nb.timestamp}</span>
            </div>
            <p style="margin:8px 0 0 0; font-size:0.85rem; color:#64748b;">Click to reload this notebook into the Workspace.</p>
        </div>
    `).join('');
}

async function loadHistory() {
    const resp = await fetch('/api/history');
    const data = await resp.json();
    const list = document.getElementById('history-list');

    if (!data || data.length === 0) {
        list.innerHTML = '<p style="color:grey; padding:20px;">No history items found.</p>';
        return;
    }

    const trash = `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/><path d="M3 6h18"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>`;

    list.innerHTML = data.map(item => `
        <div class="history-card" style="border-left: 4px solid #3b82f6;">
            <button class="delete-db-btn" onclick="deleteHistoryItem(event, ${item.id})">${trash}</button>
            <div style="display:flex; justify-content:space-between; margin-bottom:6px;">
                 <span style="font-weight:600; font-size:0.85rem; color:#475569;">${item.timestamp || ''}</span>
                 <span style="font-size:0.75rem; background:#f1f5f9; padding:4px 6px; border-radius:4px; white-space:nowrap; line-height:1; display:inline-flex; align-items:center;">${item.tool.replace(/_/g, ' ')}</span>
            </div>
            <div style="font-weight:500; margin-bottom:4px; font-size:0.9rem;">${item.query}</div>
            <div style="color:#64748b; font-size:0.85rem; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">${item.answer.substring(0, 100)}...</div>
        </div>
    `).join('');
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
        } else {
            statusDiv.innerHTML = `<span style="color: #ef4444;">Error: ${result.detail || 'Upload failed'}</span>`;
        }
    } catch (e) {
        statusDiv.innerHTML = `<span style="color: #ef4444;">Network Error: ${e.message}</span>`;
    }
}


