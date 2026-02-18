# Keyboard Shortcuts - User Guide

## Overview
The AIV Notebook Widget now includes a comprehensive keyboard shortcut system to improve navigation speed and user experience. All shortcuts are designed to work globally where appropriate and won't interfere with typing in input fields.

## Available Shortcuts

### Code & Execution
| Shortcut | Action | Description |
|----------|--------|-------------|
| **Ctrl + Enter** | Run Code | Execute the current or focused code cell |

### AI & Chat
| Shortcut | Action | Description |
|----------|--------|-------------|
| **Alt + Enter** | Open AI Popup | Open or focus the AI Assistant popup |
| **Ctrl + Shift + C** | Open Conversations | Toggle the conversations/chats drawer |
| **Ctrl + Shift + N** | New Chat | Create a new chat session |

### Notebook Management
| Shortcut | Action | Description |
|----------|--------|-------------|
| **Ctrl + Shift + S** | Open Saved | Toggle the saved notebooks drawer |
| **Ctrl + Shift + H** | Open History | Toggle the history drawer |
| **Ctrl + Alt + N** | New Notebook | Create a new notebook (with confirmation) |
| **Ctrl + S** | Save Notebook | Save the current notebook |

### Help
| Shortcut | Action | Description |
|----------|--------|-------------|
| **Ctrl + ?** | Show Help | Display this keyboard shortcuts reference |

## Usage Guidelines

### ✅ What Works as Expected
- Shortcuts work globally throughout the application
- Shortcuts do NOT interfere with normal typing in input fields
- Using keyboard shortcuts triggers the same functions as the UI buttons
- All shortcuts follow standard OS conventions (Ctrl for Windows/Linux, Cmd for Mac)
- Multiple shortcuts can be used in sequence without delays

### ℹ️ Special Cases

#### Ctrl + Enter (Run Code)
- Works when focused in any code cell editor
- Executes the current or last code cell
- Press **Ctrl + Enter** while in code cell → executes the code
- Press **Ctrl + Enter** while in AI input → also sends the prompt

#### Alt + Enter (Open AI Popup)
- Works anywhere in the application
- Opens the AI Assistant popup window
- Focuses the input field for immediate typing

#### Ctrl + S (Save)
- Prevents the browser's default "Save Page" dialog
- Triggers the notebook save function instead

#### Ctrl + ? (Help)
- Works anywhere in the application
- Opens the keyboard shortcuts reference modal
- You can also click the "Help" button in the navbar

### 🎯 Best Practices
1. **Navigation**: Use Ctrl+Shift+C/S/H to quickly access different drawers
2. **Workflow**: Ctrl+Alt+N for new notebook → Start coding → Shift+Enter to test → Ctrl+S to save
3. **AI Interaction**: Ctrl+Enter to open AI, type your prompt, Enter to send
4. **Quick Help**: When you forget a shortcut, press Ctrl+?

## Implementation Details

### Files Modified/Created
- **New**: `static/keyboard-shortcuts.js` - Core shortcuts manager
- **Modified**: `static/index.html` - Added help button and script import
- **Modified**: `static/style.css` - Added styles for help modal

### Keyboard Shortcut Manager
The `KeyboardShortcutsManager` class handles:
- Registration of all keyboard shortcuts
- Event listening and key combination detection
- Context awareness (detects when user is typing)
- Help modal creation and display
- Cross-platform support (Ctrl/Cmd handling)

### How It Works
1. When the page loads, the `KeyboardShortcutsManager` initializes
2. It listens to all `keydown` events globally
3. When a shortcut is pressed, it checks:
   - If the key combination matches a registered shortcut
   - If the user is NOT typing in a regular input field (except for specific shortcuts)
4. If valid, it prevents the default browser action and executes the associated function
5. The same functions triggered by UI buttons are used (no logic duplication)

### Browser Support
- ✅ Chrome/Chromium
- ✅ Firefox
- ✅ Safari
- ✅ Edge
- ✅ macOS (Cmd key supported)

## Customization

### Adding New Shortcuts
To add a new shortcut, modify `keyboard-shortcuts.js`:

```javascript
this.registerShortcut({
  key: 'YourKeyCombo',
  ctrl: true,
  shift: true,
  alt: false,
  action: () => this.handleYourAction(),
  description: 'Your Action Description'
});
```

### Modifying Existing Shortcuts
Edit the desired shortcut in the `registerShortcuts()` method and update the `getKeyCombo()` method to detect the new key combination.

### Customizing Styles
Edit `.keyboard-shortcuts-content`, `.shortcuts-grid`, and related classes in `static/style.css`.

## Troubleshooting

### Shortcuts Not Working?
1. **Check Console**: Open DevTools (F12) and check for JavaScript errors
2. **Focus**: Click inside a code cell or text area first
3. **Reload**: Press F5 to refresh the page and reinitialize shortcuts

### Shortcut Conflicts
- The shortcuts manager automatically prevents conflicts with browser defaults
- If a shortcut doesn't work, another app or browser extension may be using it

### macOS Users
- Use **Cmd** instead of **Ctrl** (the manager automatically handles this)
- Example: Cmd+S instead of Ctrl+S

## Accessibility
- All shortcuts are documented in the Help modal (Ctrl+?)
- Help button available in the navbar for easy reference
- Keyboard shortcuts improve accessibility for power users and those with mobility needs

---

**Happy coding! 🚀**

For more help, visit the Help modal by pressing **Ctrl + ?** or clicking the "Help" button in the navbar.
