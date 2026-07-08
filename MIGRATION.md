## Rich to Textual Migration Guide

This document describes the complete migration of the pychat TUI from **Rich** to **Textual**.

---

## Overview

**What Changed:**
- Terminal UI framework: Rich → Textual
- Rendering model: imperative (manual `Live.update()`) → reactive (automatic on attribute change)
- Input handling: raw terminal mode with manual key parsing → Textual's event system
- Layout: Rich `Panel` + `Layout` → Textual `Static` widgets + CSS

**What Stayed the Same:**
- All networking, encryption, protocol, commands, and business logic
- Message history, presence tracking, typing indicators
- File transfers, tab completion, input history
- All command implementations
- UI color scheme and visual appearance

---

## File Changes

### New Files
- **`chat/client/textual_ui.py`** — Complete Textual app implementation
- **`chat/client/test_textual_ui.py`** — Unit tests for Textual UI

### Modified Files
- **`chat/client/client.py`** — Removed Rich-specific code, integrated Textual
- **`requirements.txt`** — Replaced `rich>=13.7.1` with `textual>=0.60.0`

### Archived/Removed Files
- **`chat/client/ui.py`** — Old Rich-based UI (can be deleted)

---

## Architecture

### Old Rich Flow
```
ChatClient.__init__()
  → ChatUI(username)  [creates dataclass with state]
  
ChatClient.run()
  → ui.live() context manager
    → asyncio.create_task(refresh loop)
      → while running: ui.tick(); live.update(ui.render())
  → input_loop() [raw terminal, key parsing]
    → updates ui.input_buffer, ui.messages directly
    
ui.render() → Panel/Layout with Rich renderables
```

### New Textual Flow
```
ChatClient.__init__()
  → ChatUI(username)  [creates Textual App]
    → compose() creates ChatContainer with widgets
    
ChatClient.run()
  → ui.run_async()  [Textual's async event loop]
    → Textual handles:
      - Rendering on reactive attribute changes
      - Keyboard input via on_key() → client_callback
      - Animation frame updates
    
on_key() → client_callback(action)
  → client updates: ui.input_buffer, ui.messages, etc.
  → reactive watchers fire → widgets re-render
```

---

## Key Concepts

### Reactive Attributes
Textual uses **reactive decorators** to automatically trigger re-renders when values change:

```python
class ChatContainer(Container):
    messages: reactive[list] = reactive([])
    input_buffer: reactive[str] = reactive("")
    
    def watch_messages(self, new_value):
        """Called automatically when messages changes."""
        if self.message_display:
            self.message_display.messages = new_value
```

When you set `ui.messages = [...]`, Textual:
1. Calls `watch_messages()`
2. Updates the child widget
3. Child widget auto-renders
4. Screen updates

### Widget Hierarchy
```
ChatUI (App)
  ├── Header
  ├── ChatContainer (main layout)
  │   ├── Vertical (left panel)
  │   │   ├── MessageDisplay (Static)
  │   │   └── InputPrompt (Static)
  │   └── CommandsPanel (Static, collapsible)
  └── Footer
```

Each widget is responsible for rendering its own content via `render()` method.

### Event Handling
Instead of raw key reading, Textual posts events:

```python
def on_key(self, event: Key) -> None:
    """Textual calls this for every key."""
    if event.key == "enter":
        self.client_callback("submit_input", text=self.input_buffer)
        event.prevent_default()  # Prevent Textual's default handling
```

The callback is a bridge back to `ChatClient` for async work.

---

## Migration Checklist

### UI State
- ✅ `messages` — list of (sender, text, status) tuples
- ✅ `input_buffer` — current input text
- ✅ `message_scroll` — scroll offset for viewport
- ✅ `typing` — friend is typing indicator
- ✅ `executing_command` — spinner for command execution
- ✅ `friend` — name of the chat partner
- ✅ `friend_status` — "online", "idle", "offline"
- ✅ `ping_ms` — latency in milliseconds
- ✅ `online` — whether friend is online
- ✅ `command_panel_visible` — collapsible commands panel
- ✅ `self_status` — user's own presence status

### Keyboard Input
- ✅ `Enter` — submit input
- ✅ `↑/↓` — navigate input history
- ✅ `Tab` — autocomplete commands/paths
- ✅ `Backspace/Delete` — delete character
- ✅ `PageUp/PageDown` — scroll messages
- ✅ `Home/End` — jump to top/bottom
- ✅ Printable characters — add to input buffer

### Features
- ✅ Typing indicators (animated dots)
- ✅ Command execution spinner (animated braille)
- ✅ Presence status with ping latency
- ✅ Message scrolling with viewport
- ✅ Scrollback indicator
- ✅ Tab completion
- ✅ Input history
- ✅ All commands (/help, /ping, /send, etc.)
- ✅ File transfers
- ✅ Notifications (OS-level)

---

## Testing the Migration

### Run the Application
```bash
export USERNAME=alice
export PASSWORD=shared_secret
export SERVER=ws://127.0.0.1:8000/ws
python -m chat.client.client
```

### Test Checklist
- [ ] Client connects to server (no connection errors)
- [ ] Message history loads on startup
- [ ] Incoming messages display correctly
- [ ] Typing indicator animates
- [ ] Tab completion works for `/` commands
- [ ] Arrow keys navigate input history
- [ ] PageUp/PageDown scrolls messages
- [ ] `/commands hide` toggles panel
- [ ] `/ping` shows latency
- [ ] `/send <file>` uploads files
- [ ] Presence shows friend's status
- [ ] Command execution shows spinner
- [ ] Escape key handling (arrow keys)
- [ ] Ctrl+C exits gracefully
- [ ] Colors match original theme

---

## Troubleshooting

### "AttributeError: 'ChatUI' object has no attribute 'chat_container'"

**Cause:** Method called before `on_mount()` ran (during `__init__`).

**Solution:** Fixed in current version with:
- Defensive `None` checks in all properties
- `_pending_command_help` buffer for early calls
- Apply pending state in `on_mount()`

### "TypeError: DOMNode.watch() missing 1 required positional argument"

**Cause:** Using old Rich-style `self.watch(attr, callback)` API.

**Solution:** Use Textual's `watch_{attribute}()` methods instead.

### Terminal rendering issues (glitches, overlaps)

**Cause:** Textual fighting with other terminal state.

**Solution:**
```bash
# Run with inline mode:
python -m chat.client.client

# Or reset terminal:
reset
```

### Keyboard input not working

**Cause:** Terminal not in raw mode or Textual not capturing keys.

**Solution:**
- Ensure `sys.stdin.isatty()` is true
- Check that Textual app is in focus
- Verify no other process is consuming stdin

### Performance is slow

**Cause:** Widget re-rendering too frequently or inefficient watchers.

**Solution:**
- Check animation loop interval (currently 0.08s = 12.5 fps)
- Verify message list isn't growing indefinitely
- Use `limit` in history loads

---

## Implementation Details

### Initialization Order

```
1. ChatClient.__init__()
   └─> self.ui = ChatUI(username)  # Creates app but doesn't run

2. self.ui.set_command_help(...)
   └─> Buffered in _pending_command_help (chat_container doesn't exist yet)

3. await self.ui.run_async()
   └─> Textual event loop starts
       ├─> compose() is called → chat_container created
       ├─> on_mount() is called → _pending_command_help applied
       └─> App is now interactive

4. Background tasks (WebSocket, ping, presence, etc.)
   └─> Run concurrently with Textual event loop
```

### Callback Bridge

The `client_callback` mechanism bridges Textual's event loop back to async code:

```python
def on_key(self, event: Key) -> None:
    if event.key == "enter":
        self.client_callback("submit_input", text=self.input_buffer)

def _handle_ui_callback(self, action: str, **kwargs) -> None:
    if action == "submit_input":
        asyncio.create_task(self.submit_input())  # Schedule async work
```

### Reactive Property Sync

Each reactive attribute on `ChatUI` proxies to `ChatContainer`:

```python
@property
def input_buffer(self) -> str:
    if self.chat_container:
        return self.chat_container.input_buffer
    return ""

@input_buffer.setter
def input_buffer(self, value: str) -> None:
    if self.chat_container:
        self.chat_container.input_buffer = value
        # Triggers watch_input_buffer() → InputPrompt re-renders
```

---

## Color Scheme

The OPENCLAW theme is preserved:

```python
OPENCLAW = {
    "text": "#E8E3D5",           # Light beige
    "dim": "#7B7F87",            # Dim gray
    "accent": "#F6C453",         # Yellow
    "accent_soft": "#F2A65A",    # Orange
    "border": "#3C414B",         # Dark gray
    "system": "#9BA3B2",         # Blue-gray
    "success": "#7DD3A5",        # Green
    "quote": "#8CC8FF",          # Light blue
    "error": "#F97066",          # Red
}
```

Applied to Rich renderables inside Textual widgets for consistency.

---

## Future Improvements

### Short-term
- [ ] CSS-based styling (replace manual Rich colors)
- [ ] Custom Textual widgets for message bubbles
- [ ] Better focus management (Tab between panels)
- [ ] Screen reader support

### Long-term
- [ ] Message search
- [ ] Rich formatting (bold, italic, links)
- [ ] User list display
- [ ] Attachment previews
- [ ] Theme customization
- [ ] Split-screen mode

---

## References

- **Textual Docs:** https://textual.textualize.io/
- **Textual API:** https://textual.textualize.io/reference/
- **Reactive Guide:** https://textual.textualize.io/guide/reactivity/
- **Events:** https://textual.textualize.io/guide/events/

---

## Questions?

If you encounter issues:
1. Check the logs: `LOG_LEVEL=DEBUG python -m chat.client.client`
2. Run tests: `pytest chat/client/test_textual_ui.py -v`
3. Review the code: Start with `textual_ui.py` and trace the flow
