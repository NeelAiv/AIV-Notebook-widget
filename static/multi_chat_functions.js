// ======================================================
// MULTI-CHAT SYSTEM FUNCTIONS
// ======================================================

/**
 * Extract meaningful title from AI response text (3-4 words)
 * Strips markdown, removes stop words, returns clean title.
 */
function extractChatTitle(text) {
  if (!text || typeof text !== 'string') return 'New Chat';

  // Strip markdown syntax
  const plain = text
    .replace(/```[\s\S]*?```/g, '')   // remove code blocks
    .replace(/`[^`]*`/g, '')           // remove inline code
    .replace(/[#*_~>\[\]()!]/g, '')    // remove markdown chars
    .replace(/\s+/g, ' ')
    .trim();

  if (!plain) return 'New Chat';

  // Common stop words to exclude
  const stopWords = new Set([
    'what', 'is', 'how', 'can', 'the', 'a', 'an', 'to', 'do', 'does', 'did',
    'are', 'am', 'be', 'been', 'being', 'have', 'has', 'had', 'will', 'would',
    'could', 'should', 'may', 'might', 'must', 'shall', 'and', 'or', 'but',
    'in', 'on', 'at', 'by', 'for', 'of', 'with', 'from', 'up', 'about', 'as',
    'into', 'through', 'during', 'before', 'after', 'above', 'below', 'between',
    'out', 'off', 'over', 'under', 'again', 'further', 'then', 'once', 'here',
    'there', 'when', 'where', 'why', 'which', 'who', 'whom', 'that', 'this',
    'these', 'those', 'i', 'you', 'he', 'she', 'it', 'we', 'they', 'me', 'him',
    'her', 'us', 'them', 'my', 'your', 'his', 'its', 'our', 'their', 'sure',
    'here', 'below', 'following', 'based', 'using', 'use', 'used', 'also',
    'note', 'example', 'result', 'output', 'returns', 'return'
  ]);

  const words = plain
    .toLowerCase()
    .replace(/[^\w\s]/g, '')
    .split(/\s+/)
    .filter(word => word.length > 1 && !stopWords.has(word));

  // Take first 3-4 meaningful words
  const titleWords = words.slice(0, 4);
  if (titleWords.length === 0) return 'New Chat';

  return titleWords
    .map(word => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
}

/**
 * Format creation time in 12-hour format (HH:MM AM/PM)
 */
function formatChatCreatedTime(timestamp) {
  const date = new Date(timestamp);
  return date.toLocaleTimeString('en-US', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: true
  });
}

// ======================================================
// POPUP STATE HELPERS
// ======================================================

function isPopupOpen() {
  const mini = document.getElementById('ai-mini');
  return mini && mini.classList.contains('open');
}

function isPopupMaximized() {
  const mini = document.getElementById('ai-mini');
  return mini && mini.classList.contains('docked');
}

/**
 * Open AI popup in MINIMIZED state (floating, not docked)
 */
function openPopupMinimized() {
  const mini = document.getElementById('ai-mini');
  const maxBtn = document.getElementById('ai-mini-max');
  const content = document.querySelector('.content');
  if (!mini) return;

  mini.classList.add('open');
  mini.classList.remove('docked');
  mini.setAttribute('aria-hidden', 'false');
  if (maxBtn) updateMaximizeButton(maxBtn, false);
  if (content) {
    content.classList.remove('ai-docked');
    content.style.marginRight = '';
  }
  localStorage.setItem('ai-popup-mode', 'min');
  const input = document.getElementById('prompt-input');
  if (input) input.focus();
}

/**
 * Open AI popup in MAXIMIZED state (docked panel)
 */
function openPopupMaximized() {
  const mini = document.getElementById('ai-mini');
  const maxBtn = document.getElementById('ai-mini-max');
  const content = document.querySelector('.content');
  if (!mini) return;

  const width = mini.style.getPropertyValue('--ai-panel-width') || '450px';
  mini.classList.add('open');
  mini.classList.add('docked');
  mini.setAttribute('aria-hidden', 'false');
  if (maxBtn) updateMaximizeButton(maxBtn, true);
  if (content) {
    content.classList.add('ai-docked');
    content.style.setProperty('--ai-panel-width', width);
    content.style.marginRight = width;
  }
  localStorage.setItem('ai-popup-mode', 'max');
  const input = document.getElementById('prompt-input');
  if (input) input.focus();
}

// ======================================================
// CORE CHAT FUNCTIONS
// ======================================================

/**
 * Create a new chat session.
 * Popup state machine:
 *   Closed      → open MINIMIZED
 *   MINIMIZED   → stay MINIMIZED, swap content
 *   MAXIMIZED   → convert to MINIMIZED, swap content
 */
function createNewChat() {
  // Save current chat before creating new one
  if (currentChatId) {
    saveCurrentChat();
  }

  const newChat = {
    id: 'chat_' + Date.now(),
    notebookId: currentNotebookId,
    title: 'New Chat',
    messages: [],
    chatHistory: [],
    createdAt: Date.now()
  };

  chats.push(newChat);
  currentChatId = newChat.id;

  // Clear UI
  clearChatUI();

  // Update drawer (preserves order — new chat at top since it has latest createdAt)
  renderChatList();

  // Save to localStorage
  saveChatsToLocalStorage();

  // Popup state machine
  if (!isPopupOpen()) {
    openPopupMinimized();
  } else if (isPopupMaximized()) {
    openPopupMinimized(); // MAXIMIZED → MINIMIZED
  }
  // If already MINIMIZED, stay as-is
}

/**
 * Switch to a different chat.
 * Popup state machine:
 *   Closed    → open MAXIMIZED
 *   MINIMIZED → convert to MAXIMIZED
 *   MAXIMIZED → stay MAXIMIZED, swap content
 * Drawer stays open. Scroll position preserved.
 */
function switchChat(chatId) {
  if (chatId === currentChatId) {
    // Already on this chat — just ensure popup is maximized
    if (!isPopupOpen() || !isPopupMaximized()) {
      openPopupMaximized();
    }
    return;
  }

  // Save current chat before switching
  if (currentChatId) {
    saveCurrentChat();
  }

  // Switch to new chat
  currentChatId = chatId;

  // Load chat content into UI
  loadChatToUI(chatId);

  // Update active state in drawer WITHOUT re-rendering (preserves scroll position)
  document.querySelectorAll('.chat-list-item').forEach(el => {
    el.classList.toggle('active', el.dataset.chatId === chatId);
  });

  // Save current chat ID
  saveChatsToLocalStorage();

  // Popup state machine — always open/stay MAXIMIZED when clicking existing chat
  if (!isPopupOpen() || !isPopupMaximized()) {
    openPopupMaximized();
  }
  // Drawer stays open — do NOT call closeDrawer
}

/**
 * Save current chat state to the chats array
 */
function saveCurrentChat() {
  const chat = chats.find(c => c.id === currentChatId);
  if (chat) {
    chat.messages = JSON.parse(JSON.stringify(messagePairs.map(pair => ({
      prompt: pair.prompt
    }))));
    chat.chatHistory = JSON.parse(JSON.stringify(chatHistory));
    // Do NOT update createdAt — sort order must remain immutable
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
 * Render chat list in sidebar.
 * Sort: newest createdAt at top (descending). Order is immutable.
 */
function renderChatList() {
  const chatList = document.getElementById('chat-list');
  if (!chatList) return;

  // Preserve scroll position
  const scrollTop = chatList.scrollTop;

  chatList.innerHTML = '';

  if (chats.length === 0) {
    chatList.innerHTML = '<div class="chat-list-empty">No chats yet.<br>Click the AI button to start.</div>';
    return;
  }

  // Sort by createdAt descending (newest first) — immutable order
  const sortedChats = [...chats].sort((a, b) => b.createdAt - a.createdAt);

  // Icons
  const trashIcon = `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/><path d="M3 6h18"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>`;
  const pencilIcon = `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-pen-line-icon lucide-pen-line"><path d="M13 21h8"/><path d="M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z"/></svg>`;

  sortedChats.forEach(chat => {
    const item = document.createElement('div');
    item.className = 'chat-list-item' + (chat.id === currentChatId ? ' active' : '');
    item.dataset.chatId = chat.id;

    // Content wrapper (title + date)
    const contentWrapper = document.createElement('div');
    contentWrapper.style.flex = '1';
    contentWrapper.style.minWidth = '0';
    contentWrapper.style.cursor = 'pointer';
    contentWrapper.onclick = () => switchChat(chat.id);

    const title = document.createElement('div');
    title.className = 'chat-title';
    title.textContent = chat.title || 'New Chat';

    const date = document.createElement('div');
    date.className = 'chat-date';
    date.textContent = formatChatCreatedTime(chat.createdAt || Date.now());

    contentWrapper.appendChild(title);
    contentWrapper.appendChild(date);

    // Edit button
    const editBtn = document.createElement('button');
    editBtn.className = 'chat-edit-btn';
    editBtn.setAttribute('aria-label', 'Rename chat');
    editBtn.innerHTML = pencilIcon;
    editBtn.onclick = (e) => {
      e.stopPropagation();
      startChatRename(chat.id);
    };

    // Delete button
    const deleteBtn = document.createElement('button');
    deleteBtn.className = 'delete-db-btn';
    deleteBtn.innerHTML = trashIcon;
    deleteBtn.onclick = (e) => deleteChat(e, chat.id);

    item.appendChild(contentWrapper);
    item.appendChild(editBtn);
    item.appendChild(deleteBtn);
    chatList.appendChild(item);
  });

  // Restore scroll position
  chatList.scrollTop = scrollTop;
}

/**
 * Update chat title from first AI response.
 * Only fires once — when title is still the placeholder 'New Chat'.
 */
function updateChatTitle(chatId, aiResponseText) {
  const chat = chats.find(c => c.id === chatId);
  if (chat && chat.title === 'New Chat') {
    const cleanTitle = extractChatTitle(aiResponseText);
    chat.title = cleanTitle || 'New Chat';
    // Do NOT update createdAt — sort order must remain immutable
    // Update only the title text in the DOM (no full re-render to preserve scroll)
    const titleEl = document.querySelector(`[data-chat-id="${chatId}"] .chat-title`);
    if (titleEl) titleEl.textContent = chat.title;
    saveChatsToLocalStorage();
  }
}

/**
 * Start inline rename for a chat
 */
function startChatRename(chatId) {
  const item = document.querySelector(`[data-chat-id="${chatId}"]`);
  if (!item) return;

  const titleDiv = item.querySelector('.chat-title');
  if (!titleDiv || item.querySelector('input')) return;

  const current = titleDiv.textContent;

  const input = document.createElement('input');
  input.type = 'text';
  input.value = current;
  input.className = 'chat-title-input';

  titleDiv.replaceWith(input);
  input.focus();
  input.select();

  function finish(newVal) {
    const value = (newVal || input.value || '').trim() || 'New Chat';
    const chat = chats.find(c => c.id === chatId);
    if (chat) {
      chat.title = value;
      saveChatsToLocalStorage();
      renderChatList();
    }
  }

  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') finish(input.value);
    else if (e.key === 'Escape') renderChatList();
  });

  input.addEventListener('blur', () => finish(input.value));
}

/**
 * Save chats to localStorage — merges into existing data (no overwrite)
 */
function saveChatsToLocalStorage() {
  try {
    const existing = JSON.parse(localStorage.getItem('notebook_chats') || '{}');
    const data = {
      ...existing,
      currentNotebookId,
    };
    if (!data.notebooks) data.notebooks = {};
    data.notebooks[currentNotebookId] = {
      currentChatId,
      chats: chats
    };
    localStorage.setItem('notebook_chats', JSON.stringify(data));
  } catch (e) {
    console.error('Failed to save chats to localStorage:', e);
  }
}

/**
 * Load chats from localStorage for the current notebook.
 * Filters by notebookId to ensure no cross-notebook leakage.
 */
function loadChatsFromLocalStorage() {
  try {
    const data = JSON.parse(localStorage.getItem('notebook_chats'));
    if (data && data.notebooks && data.notebooks[currentNotebookId]) {
      const notebook = data.notebooks[currentNotebookId];
      // Filter to only chats belonging to this notebook (defense in depth)
      chats = (notebook.chats || []).filter(
        c => !c.notebookId || c.notebookId === currentNotebookId
      );
      currentChatId = notebook.currentChatId;

      // Load the current chat
      if (currentChatId && chats.find(c => c.id === currentChatId)) {
        loadChatToUI(currentChatId);
      } else if (chats.length > 0) {
        // Load most recently created chat
        const sorted = [...chats].sort((a, b) => b.createdAt - a.createdAt);
        currentChatId = sorted[0].id;
        loadChatToUI(currentChatId);
      }
    }

    // Do NOT auto-create chats here.
    // New notebooks start empty; first FAB click triggers chat creation.
    renderChatList();
  } catch (e) {
    console.error('Failed to load chats from localStorage:', e);
    renderChatList();
  }
}

/**
 * Delete a chat by ID
 */
async function deleteChat(event, chatId) {
  event.stopPropagation();

  const chat = chats.find(c => c.id === chatId);
  if (!chat) return;

  if (!await customConfirm(`Delete chat "${chat.title}"? This action cannot be undone.`, true)) {
    return;
  }

  try {
    chats = chats.filter(c => c.id !== chatId);

    if (currentChatId === chatId) {
      if (chats.length > 0) {
        const sorted = [...chats].sort((a, b) => b.createdAt - a.createdAt);
        currentChatId = sorted[0].id;
        loadChatToUI(currentChatId);
      } else {
        clearChatUI();
        currentChatId = null;
      }
    }

    saveChatsToLocalStorage();
    renderChatList();
  } catch (e) {
    console.error('Failed to delete chat:', e);
    await customAlert('Failed to delete chat. Please try again.');
  }
}