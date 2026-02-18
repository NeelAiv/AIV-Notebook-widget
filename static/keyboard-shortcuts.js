// ======================================================
// KEYBOARD SHORTCUTS MANAGER
// ======================================================

class KeyboardShortcutsManager {
  constructor() {
    this.shortcuts = new Map();
    this.isInputActive = false;
    this.inputSelectors = ['input', 'textarea', '[contenteditable="true"]'];
    this.init();
  }

  /**
   * Initialize the keyboard shortcuts manager
   */
  init() {
    this.registerShortcuts();
    this.setupEventListeners();
  }

  /**
   * Register all keyboard shortcuts
   */
  registerShortcuts() {
    // Run Code: Ctrl + Enter
    this.registerShortcut({
      key: 'CtrlEnter',
      ctrl: true,
      shift: false,
      alt: false,
      action: () => this.handleRunCode(),
      description: 'Run Code'
    });

    // Open AI Popup: Alt + Enter
    this.registerShortcut({
      key: 'AltEnter',
      ctrl: false,
      shift: false,
      alt: true,
      action: () => this.handleOpenAIPopup(),
      description: 'AI Assistant'
    });

    // Open Conversation Drawer: Ctrl + Shift + C
    this.registerShortcut({
      key: 'CtrlShiftC',
      ctrl: true,
      shift: true,
      alt: false,
      action: () => this.handleOpenConversationDrawer(),
      description: 'Open Conversation Drawer'
    });

    // New Chat: Ctrl + Shift + N
    this.registerShortcut({
      key: 'CtrlShiftN',
      ctrl: true,
      shift: true,
      alt: false,
      action: () => this.handleNewChat(),
      description: 'New Chat'
    });

    // Open Saved Drawer: Ctrl + Shift + S
    this.registerShortcut({
      key: 'CtrlShiftS',
      ctrl: true,
      shift: true,
      alt: false,
      action: () => this.handleOpenSavedDrawer(),
      description: 'Open Saved Drawer'
    });

    // Open History Drawer: Ctrl + Shift + H
    this.registerShortcut({
      key: 'CtrlShiftH',
      ctrl: true,
      shift: true,
      alt: false,
      action: () => this.handleOpenHistoryDrawer(),
      description: 'Open History Drawer'
    });

    // New Notebook: Ctrl + Alt + N
    this.registerShortcut({
      key: 'CtrlAltN',
      ctrl: true,
      shift: false,
      alt: true,
      action: () => this.handleNewNotebook(),
      description: 'New Notebook'
    });

    // Save Notebook: Ctrl + S
    this.registerShortcut({
      key: 'CtrlS',
      ctrl: true,
      shift: false,
      alt: false,
      action: () => this.handleSaveNotebook(),
      description: 'Save Notebook'
    });

    // Open Help: Ctrl + ?

  }

  /**
   * Register a single shortcut
   */
  registerShortcut(config) {
    this.shortcuts.set(config.key, config);
  }

  /**
   * Get all registered shortcuts
   */
  getAllShortcuts() {
    return Array.from(this.shortcuts.values());
  }

  /**
   * Get shortcut key combination display string
   */
  getShortcutDisplay(shortcut) {
    const parts = [];
    if (shortcut.ctrl) parts.push('Ctrl');
    if (shortcut.alt) parts.push('Alt');
    if (shortcut.shift) parts.push('Shift');
    
    if (shortcut.key === 'CtrlEnter') {
      parts.push('Enter');
    } else if (shortcut.key === 'AltEnter') {
      parts.push('Enter');
    } else if (shortcut.key === 'CtrlShiftC') {
      parts.push('C');
    } else if (shortcut.key === 'CtrlShiftN') {
      parts.push('N');
    } else if (shortcut.key === 'CtrlShiftS') {
      parts.push('S');
    } else if (shortcut.key === 'CtrlShiftH') {
      parts.push('H');
    } else if (shortcut.key === 'CtrlAltN') {
      parts.push('N');
    } else if (shortcut.key === 'CtrlS') {
      parts.push('S');
    } else if (shortcut.key === 'CtrlQuestion') {
      parts.push('?');
    }
    
    return parts.join(' + ');
  }

  /**
   * Setup global event listeners
   */
  setupEventListeners() {
    // Track when user is typing in an input field
    document.addEventListener('focusin', (e) => {
      this.isInputActive = this.inputSelectors.some(selector =>
        e.target.matches(selector)
      );
    });

    document.addEventListener('focusout', () => {
      this.isInputActive = false;
    });

    // Handle keyboard events
    document.addEventListener('keydown', (e) => this.handleKeyDown(e));
  }

  /**
   * Handle keydown events and match shortcuts
   */
  handleKeyDown(e) {
    // Prevent default for Ctrl+S (save)
    if (e.ctrlKey && e.key === 's') {
      e.preventDefault();
    }

    // Prevent default for Ctrl+? (help)
    if (e.ctrlKey && e.key === '?') {
      e.preventDefault();
    }

    // Build key combination identifier
    const keyCombo = this.getKeyCombo(e);
    
    // Look up shortcut
    const shortcut = this.shortcuts.get(keyCombo);
    
    if (shortcut) {
      // Skip if user is typing in a regular input (except for specific shortcuts)
      const allowedWhileTyping = ['CtrlEnter', 'AltEnter', 'CtrlS', 'CtrlQuestion'];
      
      if (this.isInputActive && !allowedWhileTyping.includes(keyCombo)) {
        return;
      }

      console.log(`[KeyboardShortcuts] Executing: ${shortcut.description} (${keyCombo})`);
      e.preventDefault();
      shortcut.action();
    }
  }

  /**
   * Build key combination identifier from keyboard event
   */
  getKeyCombo(e) {
    const ctrl = e.ctrlKey || e.metaKey; // Meta for Mac
    const shift = e.shiftKey;
    const alt = e.altKey;
    const key = e.key;

    // Handle special keys
    if (key === 'Enter') {
      if (ctrl) return 'CtrlEnter';
      if (alt) return 'AltEnter';
    } else if (key === 'c' || key === 'C') {
      if (ctrl && shift) return 'CtrlShiftC';
    } else if (key === 'n' || key === 'N') {
      if (ctrl && shift) return 'CtrlShiftN';
      if (ctrl && alt) return 'CtrlAltN';
    } else if (key === 's' || key === 'S') {
      if (ctrl && shift) return 'CtrlShiftS';
      if (ctrl) return 'CtrlS';
    } else if (key === 'h' || key === 'H') {
      if (ctrl && shift) return 'CtrlShiftH';
    } else if (key === '?') {
      if (ctrl) return 'CtrlQuestion';
    }

    return null;
  }

  /**
   * Action handlers
   */

  handleRunCode() {
    console.log('[KeyboardShortcuts] handleRunCode called');
    
    // Try 1: Find focused code editor
    let targetCell = null;
    const focusedEditor = document.querySelector('.code-editor:focus');
    
    if (focusedEditor) {
      console.log('[KeyboardShortcuts] Found focused editor');
      targetCell = focusedEditor.closest('.code-cell');
    }
    
    // Try 2: Find the active/selected cell
    if (!targetCell) {
      console.log('[KeyboardShortcuts] Looking for active cell');
      targetCell = document.querySelector('.code-cell.active');
    }
    
    // Try 3: Use the last code cell
    if (!targetCell) {
      console.log('[KeyboardShortcuts] Using last code cell');
      targetCell = document.querySelector('.code-cell:last-of-type');
    }
    
    // Execute the target cell
    if (targetCell) {
      const playBtn = targetCell.querySelector('.play-btn');
      if (playBtn) {
        console.log('[KeyboardShortcuts] Clicking play button');
        playBtn.click();
      } else {
        console.error('[KeyboardShortcuts] Play button not found in cell');
      }
    } else {
      console.error('[KeyboardShortcuts] No code cell found to execute');
    }
  }

  handleOpenAIPopup() {
    const fab = document.getElementById('ai-fab');
    if (fab) {
      fab.click();
    }
  }

  handleOpenConversationDrawer() {
    if (typeof toggleDrawer === 'function') {
      toggleDrawer('chats');
    }
  }

  handleNewChat() {
    if (typeof createNewChat === 'function') {
      createNewChat();
    }
  }

  handleOpenSavedDrawer() {
    if (typeof toggleDrawer === 'function') {
      toggleDrawer('saved');
    }
  }

  handleOpenHistoryDrawer() {
    if (typeof toggleDrawer === 'function') {
      toggleDrawer('history');
    }
  }

  handleNewNotebook() {
    if (typeof newNotebook === 'function') {
      newNotebook();
    }
  }

  handleSaveNotebook() {
    if (typeof saveNotebook === 'function') {
      saveNotebook();
    }
  }

  handleOpenHelp() {
    this.showHelpModal();
  }

  /**
   * Show help modal with all shortcuts
   */
  showHelpModal() {
    // Check if help modal already exists
    let helpModal = document.getElementById('keyboard-shortcuts-modal');
    
    if (!helpModal) {
      helpModal = this.createHelpModal();
      document.body.appendChild(helpModal);
    }
    
    helpModal.style.display = 'flex';
    
    // Close on ESC
    const handleEsc = (e) => {
      if (e.key === 'Escape') {
        helpModal.style.display = 'none';
        document.removeEventListener('keydown', handleEsc);
      }
    };
    document.addEventListener('keydown', handleEsc);
  }

  /**
   * Create help modal element
   */
  createHelpModal() {
    const modal = document.createElement('div');
    modal.id = 'keyboard-shortcuts-modal';
    modal.className = 'keyboard-shortcuts-modal';
    
    const shortcuts = this.getAllShortcuts();
    
    let shortcutsHtml = '';
    shortcuts.forEach(shortcut => {
      const display = this.getShortcutDisplay(shortcut);
      shortcutsHtml += `
        <div class="shortcut-item">
          <div class="shortcut-key">${display}</div>
          <div class="shortcut-description">${shortcut.description}</div>
        </div>
      `;
    });
    
    modal.innerHTML = `
      <div class="keyboard-shortcuts-overlay">
        <div class="keyboard-shortcuts-content">
          <div class="shortcuts-header">
            <h2>Keyboard Shortcuts</h2>
            <button class="shortcuts-close" onclick="document.getElementById('keyboard-shortcuts-modal').style.display='none'" aria-label="Close">
              <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M18 6l-12 12" />
                <path d="M6 6l12 12" />
              </svg>
            </button>
          </div>
          <div class="shortcuts-grid">
            ${shortcutsHtml}
          </div>
          <div class="shortcuts-footer">
            <p>Press <kbd>Ctrl</kbd> + <kbd>?</kbd> to open this help anytime</p>
          </div>
        </div>
      </div>
    `;
    
    // Close when clicking overlay
    modal.querySelector('.keyboard-shortcuts-overlay').addEventListener('click', (e) => {
      if (e.target === e.currentTarget) {
        modal.style.display = 'none';
      }
    });
    
    return modal;
  }
}

// Initialize shortcuts manager when DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => {
    console.log('[KeyboardShortcuts] Initializing shortcuts manager...');
    window.shortcutsManager = new KeyboardShortcutsManager();
    console.log('[KeyboardShortcuts] Shortcuts manager initialized successfully');
  });
} else {
  console.log('[KeyboardShortcuts] Initializing shortcuts manager (DOM already loaded)...');
  window.shortcutsManager = new KeyboardShortcutsManager();
  console.log('[KeyboardShortcuts] Shortcuts manager initialized successfully');
}
