"""Tests for the Textual UI migration."""

import pytest
from chat.client.textual_ui import ChatUI, MessageDisplay, CommandsPanel, InputPrompt


def test_message_display_rendering():
    """Test that message display renders correctly."""
    display = MessageDisplay()
    display.messages = [
        ("User1", "Hello", "✓ Sent"),
        ("User2", "Hi there", ""),
    ]
    display.friend = "User2"
    display.friend_status = "online"
    
    # Render should not raise
    panel = display.render()
    assert panel is not None


def test_message_scroll():
    """Test message scrolling."""
    display = MessageDisplay()
    display.messages = [(f"User", f"Message {i}", "") for i in range(100)]
    
    initial_scroll = display.message_scroll
    display.scroll_messages(5)
    assert display.message_scroll == initial_scroll + 5
    
    display.scroll_messages(-3)
    assert display.message_scroll == initial_scroll + 2


def test_input_prompt_rendering():
    """Test input prompt rendering."""
    prompt = InputPrompt()
    prompt.input_buffer = "test message"
    
    text = prompt.render()
    assert text is not None
    assert "test message" in str(text)


def test_commands_panel_help():
    """Test commands panel help display."""
    panel = CommandsPanel()
    commands = [
        ("/help", "Show commands"),
        ("/ping", "Measure latency"),
    ]
    panel.set_command_help(commands)
    
    assert len(panel.command_help) == 2
    assert panel.command_help[0].name == "/help"


def test_chat_ui_properties():
    """Test ChatUI property setters and getters."""
    app = ChatUI("test_user")
    
    # Test message setting
    app.messages = [("User", "Hello", "")]
    assert len(app.messages) == 1
    
    # Test status properties
    app.friend = "Friend"
    assert app.friend == "Friend"
    
    app.typing = True
    assert app.typing is True
    
    app.online = True
    assert app.online is True
    
    app.ping_ms = 42
    assert app.ping_ms == 42


def test_chat_ui_add_message():
    """Test adding messages to ChatUI."""
    app = ChatUI("test_user")
    app.add("User1", "Hello", "✓")
    
    assert len(app.messages) == 1
    assert app.messages[0] == ("User1", "Hello", "✓")


def test_chat_ui_scroll():
    """Test scrolling in ChatUI."""
    app = ChatUI("test_user")
    for i in range(50):
        app.add(f"User", f"Message {i}")
    
    initial = app.message_scroll
    app.scroll_messages(5)
    assert app.message_scroll > initial


def test_message_visibility():
    """Test visible messages calculation."""
    display = MessageDisplay()
    for i in range(50):
        display.messages.append((f"User", f"Message {i}", ""))
    
    display.message_scroll = 0
    visible = display._visible_messages()
    assert len(visible) <= 40  # window size
    
    display.message_scroll = 10
    visible = display._visible_messages()
    assert len(visible) <= 40


def test_status_line_formatting():
    """Test status line formatting for different states."""
    display = MessageDisplay()
    display.friend = "TestUser"
    
    # Online status
    display.friend_status = "online"
    display.ping_ms = 42
    status = display._format_status_line()
    assert "TestUser" in status
    assert "42 ms" in status
    
    # Idle status
    display.friend_status = "idle"
    display.ping_ms = None
    status = display._format_status_line()
    assert "Idle" in status or "idle" in status.lower()
    
    # Offline status
    display.friend_status = "offline"
    status = display._format_status_line()
    assert "Offline" in status or "offline" in status.lower()


def test_typing_animation_frame():
    """Test typing indicator animation frame updates."""
    display = MessageDisplay()
    display.typing = True
    display.friend = "User"
    
    initial_frame = display.frame
    display.tick()
    assert display.frame == initial_frame + 1
    
    # Frame wraps around at 1M
    display.frame = 999_999
    display.tick()
    assert display.frame == 0


def test_command_execution_spinner():
    """Test command execution spinner animation."""
    display = MessageDisplay()
    display.executing_command = "ping"
    
    # Should render with different spinner characters as frame increases
    frames = []
    for _ in range(10):
        display.tick()
        panel = display.render()
        frames.append(str(panel))
    
    # Check that we got different frames (animation occurred)
    assert len(set(frames)) > 1


def test_max_scroll_calculation():
    """Test max scroll calculation."""
    display = MessageDisplay()
    assert display.max_scroll == 0
    
    display.messages = [("User", "Msg", "")] * 50
    assert display.max_scroll == 49
    
    display.messages = []
    assert display.max_scroll == 0
