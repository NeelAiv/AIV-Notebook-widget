// ======================================================
// MULTI-CHAT SYSTEM FUNCTIONS
// ======================================================

/**
 * Extract meaningful title from question (2-3 words)
 * Removes stop words and returns clean title
 */
function extractChatTitle(question) {
  if (!question || typeof question !== 'string') return 'New Chat';
  
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
    'her', 'us', 'them', 'my', 'your', 'his', 'her', 'its', 'our', 'their'
  ]);
  
  // Remove punctuation and split into words
  const words = question
    .toLowerCase()
    .replace(/[^\w\s]/g, '') // Remove punctuation
    .split(/\s+/) // Split by whitespace
    .filter(word => word.length > 0 && !stopWords.has(word)); // Filter stop words
  
  // Take first 2-3 words
  const titleWords = words.slice(0, 3);
  
  if (titleWords.length === 0) return 'New Chat';
  
  // Capitalize each word
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
  
  // Delete button SVG
  const trashIcon = `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/><path d="M3 6h18"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>`;
  
  // Edit/Pencil SVG
  const pencilIcon = `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-pen-line-icon lucide-pen-line"><path d="M13 21h8"/><path d="M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z"/></svg>`;
  
  sortedChats.forEach(chat => {
    const item = document.createElement('div');
    item.className = 'chat-list-item' + (chat.id === currentChatId ? ' active' : '');
    item.dataset.chatId = chat.id;
    
    // Add a wrapper for title and date
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
    
    // Add edit button
    const editBtn = document.createElement('button');
    editBtn.className = 'chat-edit-btn';
    editBtn.setAttribute('aria-label', 'Rename chat');
    editBtn.innerHTML = pencilIcon;
    editBtn.onclick = (e) => {
      e.stopPropagation();
      startChatRename(chat.id);
    };
    
    // Add delete button
    const deleteBtn = document.createElement('button');
    deleteBtn.className = 'delete-db-btn';
    deleteBtn.innerHTML = trashIcon;
    deleteBtn.onclick = (e) => deleteChat(e, chat.id);
    
    item.appendChild(contentWrapper);
    item.appendChild(editBtn);
    item.appendChild(deleteBtn);
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
    // Extract meaningful 2-3 word title from the question
    const cleanTitle = extractChatTitle(title);
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
  const item = document.querySelector(`[data-chat-id="${chatId}"]`);
  if (!item) return;

  const titleDiv = item.querySelector('.chat-title');
  if (!titleDiv || item.querySelector('input')) return; // Avoid duplicate inputs

  const current = titleDiv.textContent;

  const input = document.createElement('input');
  input.type = 'text';
  input.value = current;
  input.className = 'chat-title-input';

  // Replace title with input
  titleDiv.replaceWith(input);
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
/**
 * Delete a chat by ID
 */
async function deleteChat(event, chatId) {
  event.stopPropagation();
  
  const chat = chats.find(c => c.id === chatId);
  if (!chat) return;
  
  // Show confirmation dialog
  if (!await customConfirm(`Delete chat "${chat.title}"? This action cannot be undone.`, true)) {
    return;
  }
  
  try {
    // Remove chat from chats array
    chats = chats.filter(c => c.id !== chatId);
    
    // If deleted chat is the current chat, switch to another one
    if (currentChatId === chatId) {
      if (chats.length > 0) {
        // Switch to the most recent chat
        const sortedChats = [...chats].sort((a, b) => b.updatedAt - a.updatedAt);
        currentChatId = sortedChats[0].id;
        loadChatToUI(currentChatId);
      } else {
        // Create a new chat if none exist
        clearChatUI();
        createNewChat();
        return; // createNewChat will handle rendering and saving
      }
    }
    
    // Save to localStorage
    saveChatsToLocalStorage();
    
    // Re-render chat list
    renderChatList();
    
    // Remove the item from DOM
    const item = event.target.closest('.chat-list-item');
    if (item) {
      item.remove();
    }
  } catch (e) {
    console.error('Failed to delete chat:', e);
    await customAlert('Failed to delete chat. Please try again.');
  }
}