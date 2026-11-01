#!/usr/bin/env python3
"""
Automation service for MJ AI.

Handles desktop automation including application control, mouse/keyboard input,
and window management.
"""

import time
import pyautogui
import logging
from typing import Optional, Callable, Dict, Any, List
from pathlib import Path
from dataclasses import dataclass
import pywinauto
from pywinauto import Application
import subprocess
import os
import shutil
from urllib.parse import quote_plus

@dataclass
class WindowInfo:
    """Window information."""
    hwnd: int
    title: str
    process_name: str
    is_active: bool = False
    is_minimized: bool = False
    is_maximized: bool = False
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0

@dataclass
class MousePosition:
    """Mouse position information."""
    x: int
    y: int
    screen_width: int
    screen_height: int

@dataclass
class AutomationState:
    """Automation service state."""
    is_active: bool = False
    is_monitoring: bool = False
    current_operation: Optional[str] = None
    operation_start_time: Optional[float] = None
    last_mouse_position: Optional[MousePosition] = None
    active_windows: list = None
    enable_mouse_control: bool = True
    enable_keyboard_input: bool = True
    prevent_sleep: bool = False
    max_execution_time: int = 30  # seconds

    def __post_init__(self):
        if self.active_windows is None:
            self.active_windows = []
        if self.last_mouse_position is None:
            try:
                width, height = pyautogui.size()
                self.last_mouse_position = MousePosition(
                    x=width // 2, y=height // 2,
                    screen_width=width, screen_height=height,
                )
            except Exception:
                self.last_mouse_position = MousePosition(0, 0, 1920, 1080)

class AutomationService:
    """
    Handles desktop automation for MJ AI.
    
    Provides controlled access to desktop applications, window management,
    and input devices for task execution.
    """
    
    def __init__(
        self,
        config_manager=None,
        resource_monitor=None,
        automation_event_callback: Optional[Callable[[str, Dict], None]] = None
    ):
        self.logger = logging.getLogger(__name__)
        
        self.config_manager = config_manager
        self.resource_monitor = resource_monitor
        self.automation_event_callback = automation_event_callback
        
        self.state = AutomationState()
        
        # Initialize PyAutoGUI settings
        pyautogui.PAUSE = 0.5
        pyautogui.FAILSAFE = True  # Move mouse to corner to abort
        
        self.logger.info("Automation service initialized")
    
    def start(self):
        """Start the automation service."""
        self.state.is_active = True
        self.logger.info("Automation service started")
        
        # Start monitoring
        self._start_monitoring()
    
    def stop(self):
        """Stop the automation service."""
        self.state.is_active = False
        self.state.is_monitoring = False
        self.logger.info("Automation service stopped")
    
    def cleanup(self):
        """Clean up automation service resources."""
        self.stop()
    
    def _start_monitoring(self):
        """Start system monitoring."""
        import threading
        
        def monitoring_loop():
            while self.state.is_monitoring:
                try:
                    self._update_system_info()
                    time.sleep(1.0)
                except Exception as e:
                    self.logger.error(f"Error in monitoring loop: {e}")
                    time.sleep(5.0)
        
        self.state.is_monitoring = True
        monitor_thread = threading.Thread(target=monitoring_loop, daemon=True)
        monitor_thread.start()
    
    def _update_system_info(self):
        """Update system information."""
        # Update window information
        self._update_windows_list()
        
        # Update mouse position
        self.state.last_mouse_position = self._get_mouse_position()
    
    def _get_mouse_position(self) -> Optional[MousePosition]:
        """Get current mouse position."""
        try:
            x, y = pyautogui.position()
            width, height = pyautogui.size()
            return MousePosition(x=x, y=y, screen_width=width, screen_height=height)
        except Exception as e:
            self.logger.error(f"Error getting mouse position: {e}")
            return None
    
    def _update_windows_list(self):
        """Update list of active windows."""
        try:
            # In a real implementation, this would use pywinauto to enumerate windows
            # For now, we'll simulate some windows
            self.state.active_windows = [
                WindowInfo(
                    hwnd=1,
                    title="Notepad",
                    process_name="notepad.exe",
                    is_active=True
                ),
                WindowInfo(
                    hwnd=2,
                    title="Chrome",
                    process_name="chrome.exe",
                    is_active=False
                )
            ]
        except Exception as e:
            self.logger.error(f"Error updating windows list: {e}")
    
    def open_application(self, app_name: str) -> bool:
        """
        Open an application.
        
        Args:
            app_name: Name of the application to open
            
        Returns:
            True if successful, False otherwise
        """
        self.logger.info(f"Opening application: {app_name}")
        return self._launch_application(app_name)

    def search_web(self, query: str) -> bool:
        """Open a fixed Google search URL in Firefox for the supplied query."""
        query = str(query or "").strip()
        if not query:
            self.logger.warning("Refusing to open an empty web search")
            return False
        if len(query) > 500:
            self.logger.warning("Refusing an overly long web search query")
            return False

        search_url = "https://www.google.com/search?q=" + quote_plus(query)
        return self._launch_application("firefox", [search_url])

    def _launch_application(self, app_name: str, arguments: Optional[List[str]] = None) -> bool:
        """Launch an allowlisted application, optionally with safe arguments."""
        self.logger.info(f"Launching application: {app_name}")
        try:
            # Validate application name
            if not self._is_allowed_application(app_name):
                self.logger.warning(f"Application not allowed: {app_name}")
                return False
            
            # Check execution time
            if self._check_execution_time():
                self.logger.warning("Execution time limit reached")
                return False
            
            # Resolve known applications through PATH, Windows App Paths, and
            # their standard install folders before falling back to PATH.
            command = self._resolve_application_command(app_name)
            if not command:
                self.logger.error("Could not locate executable for %s", app_name)
                return False
            subprocess.Popen([command, *(arguments or [])])
            
            # Wait for application to start
            time.sleep(2.0)
            
            # Verify the application is running
            if self._verify_application_running(app_name):
                self.logger.info(f"Successfully opened application: {app_name}")
                return True
            else:
                self.logger.warning(f"Application may not have opened correctly: {app_name}")
                return False
                
        except Exception as e:
            self.logger.error(f"Error opening application {app_name}: {e}")
            return False
    
    def _is_allowed_application(self, app_name: str) -> bool:
        """Check if an application is allowed to be opened."""
        config = self.config_manager.get_automation_config() if self.config_manager else None
        
        if not config:
            return True  # Default to allowing if no config
        
        exe_name = Path(app_name.strip()).name.lower()
        if exe_name.endswith(".exe"):
            exe_name = exe_name[:-4]

        allowed_apps = set()
        for allowed in config.allowed_applications:
            name = Path(str(allowed).strip()).name.lower()
            allowed_apps.add(name[:-4] if name.endswith(".exe") else name)

        # Keep these legacy aliases working while comparing the allowlist by
        # executable basename (so firefox and firefox.exe both match).
        legacy_aliases = {"vscode": "code"}
        exe_name = legacy_aliases.get(exe_name, exe_name)
        return exe_name in allowed_apps or exe_name in {"notepad", "chrome", "code", "explorer"}

    @staticmethod
    def _resolve_application_command(app_name: str) -> Optional[str]:
        """Find a safe executable path for an allowlisted application."""
        aliases = {
            "vscode": "code.exe",
            "visual studio code": "code.exe",
            "vs code": "code.exe",
            "google chrome": "chrome.exe",
            "microsoft edge": "msedge.exe",
            "edge": "msedge.exe",
            "mozilla firefox": "firefox.exe",
        }
        name = Path(app_name.strip()).name.lower()
        exe_name = aliases.get(name, name if name.endswith(".exe") else f"{name}.exe")

        path_match = shutil.which(exe_name)
        if path_match:
            return path_match

        # Windows installers commonly register the executable in App Paths,
        # even when it is not on PATH (Firefox and Chrome in particular).
        if os.name == "nt":
            try:
                import winreg

                key_path = rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{exe_name}"
                for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                    try:
                        with winreg.OpenKey(hive, key_path) as key:
                            registered, _ = winreg.QueryValueEx(key, None)
                        registered = os.path.expandvars(str(registered).strip('"'))
                        if Path(registered).is_file():
                            return registered
                    except OSError:
                        continue
            except ImportError:
                pass

            roots = [
                os.environ.get("PROGRAMFILES"),
                os.environ.get("PROGRAMFILES(X86)"),
                os.environ.get("LOCALAPPDATA"),
            ]
            relative_paths = {
                "firefox.exe": ("Mozilla Firefox/firefox.exe",),
                "chrome.exe": ("Google/Chrome/Application/chrome.exe",),
                "msedge.exe": ("Microsoft/Edge/Application/msedge.exe",),
                "code.exe": ("Programs/Microsoft VS Code/Code.exe",),
            }.get(exe_name, ())
            for root in roots:
                if not root:
                    continue
                for relative in relative_paths:
                    candidate = Path(root) / relative
                    if candidate.is_file():
                        return str(candidate)

        # Windows can resolve system executables such as notepad.exe from
        # PATH when Popen starts them.
        return exe_name
    
    def _verify_application_running(self, app_name: str) -> bool:
        """Verify that an application is running."""
        try:
            # Check for window with the application title
            exe_name = app_name.lower()
            if exe_name.endswith(".exe"):
                exe_name = exe_name[:-4]
            
            # Use pywinauto to find windows
            app = Application()
            try:
                # Check if there's a window with the application title
                for window in app.windows():
                    if exe_name in window.window_text().lower() or app_name.lower() in window.window_text().lower():
                        return True
            except:
                pass
            
            # Fallback: check processes
            import psutil
            for proc in psutil.process_iter(['pid', 'name']):
                try:
                    if exe_name in proc.info['name'].lower():
                        return True
                except:
                    pass
            
            return False
            
        except Exception as e:
            self.logger.error(f"Error verifying application {app_name}: {e}")
            return False
    
    def _open_application_generic(self, app_name: str):
        """Open an application using generic method."""
        try:
            command = self._resolve_application_command(app_name)
            if not command:
                return False
            subprocess.Popen([command])
            return True
        except Exception as e:
            self.logger.error(f"Error opening generic application {app_name}: {e}")
            return False
    
    def switch_to_window(self, window_title: str) -> bool:
        """
        Switch to a specific window.
        
        Args:
            window_title: Title of the window to switch to
            
        Returns:
            True if successful, False otherwise
        """
        self.logger.info(f"Switching to window: {window_title}")
        
        try:
            # Use pywinauto to find and activate the window
            app = Application()
            
            # Try to find window by title
            windows = app.windows()
            for window in windows:
                if window_title.lower() in window.window_text().lower():
                    window.set_focus()
                    self.logger.info(f"Switched to window: {window.window_text()}")
                    return True
            
            self.logger.warning(f"Window not found: {window_title}")
            return False
            
        except Exception as e:
            self.logger.error(f"Error switching to window {window_title}: {e}")
            return False
    
    def minimize_window(self, window_title: str) -> bool:
        """
        Minimize a window.
        
        Args:
            window_title: Title of the window to minimize
            
        Returns:
            True if successful, False otherwise
        """
        self.logger.info(f"Minimizing window: {window_title}")
        
        try:
            app = Application()
            windows = app.windows()
            
            for window in windows:
                if window_title.lower() in window.window_text().lower():
                    window.minimize()
                    self.logger.info(f"Minimized window: {window.window_text()}")
                    return True
            
            self.logger.warning(f"Window not found: {window_title}")
            return False
            
        except Exception as e:
            self.logger.error(f"Error minimizing window {window_title}: {e}")
            return False
    
    def maximize_window(self, window_title: str) -> bool:
        """
        Maximize a window.
        
        Args:
            window_title: Title of the window to maximize
            
        Returns:
            True if successful, False otherwise
        """
        self.logger.info(f"Maximizing window: {window_title}")
        
        try:
            app = Application()
            windows = app.windows()
            
            for window in windows:
                if window_title.lower() in window.window_text().lower():
                    window.maximize()
                    self.logger.info(f"Maximized window: {window.window_text()}")
                    return True
            
            self.logger.warning(f"Window not found: {window_title}")
            return False
            
        except Exception as e:
            self.logger.error(f"Error maximizing window {window_title}: {e}")
            return False
    
    def type_text(self, text: str, delay: float = 0.1) -> bool:
        """
        Type text into the active application.
        
        Args:
            text: Text to type
            delay: Delay between keystrokes
            
        Returns:
            True if successful, False otherwise
        """
        self.logger.info(f"Typing text: {text}")
        
        try:
            if not self.state.enable_keyboard_input:
                self.logger.warning("Keyboard input is disabled")
                return False
            
            # Check execution time
            if self._check_execution_time():
                return False
            
            pyautogui.typewrite(text, interval=delay)
            self.logger.info("Text typed successfully")
            return True
            
        except Exception as e:
            self.logger.error(f"Error typing text: {e}")
            return False
    
    def click_at(self, x: int, y: int) -> bool:
        """
        Click at specified coordinates.
        
        Args:
            x: X coordinate
            y: Y coordinate
            
        Returns:
            True if successful, False otherwise
        """
        self.logger.info(f"Clicking at: ({x}, {y})")
        
        try:
            if not self.state.enable_mouse_control:
                self.logger.warning("Mouse control is disabled")
                return False
            
            # Check execution time
            if self._check_execution_time():
                return False
            
            pyautogui.click(x, y)
            self.logger.info("Click completed successfully")
            return True
            
        except Exception as e:
            self.logger.error(f"Error clicking at ({x}, {y}): {e}")
            return False
    
    def press_key(self, key: str, modifiers: list[str] = None) -> bool:
        """
        Press a key with optional modifiers.
        
        Args:
            key: Key to press
            modifiers: List of modifier keys (e.g., "ctrl", "alt", "shift")
            
        Returns:
            True if successful, False otherwise
        """
        self.logger.info(f"Pressing key: {key}")
        
        try:
            if not self.state.enable_keyboard_input:
                self.logger.warning("Keyboard input is disabled")
                return False

            # Check execution time
            if self._check_execution_time():
                return False

            # Normalise aliases to pyautogui key names.
            key_aliases = {"return": "enter", "esc": "escape",
                           "control": "ctrl", "pgup": "pageup",
                           "pgdn": "pagedown", "spacebar": "space"}
            key = key_aliases.get(key.lower(), key.lower())

            released = []
            try:
                if modifiers:
                    for modifier in modifiers:
                        pyautogui.keyDown(modifier)
                        released.append(modifier)
                pyautogui.press(key)
            finally:
                for modifier in reversed(released):
                    try:
                        pyautogui.keyUp(modifier)
                    except Exception:
                        pass

            self.logger.info(f"Key pressed successfully: {key}")
            return True

        except Exception as e:
            self.logger.error(f"Error pressing key {key}: {e}")
            return False
    
    def _check_execution_time(self) -> bool:
        """Check if execution time limit has been exceeded."""
        if self.state.operation_start_time is None:
            return False
        
        elapsed_time = time.time() - self.state.operation_start_time
        
        if elapsed_time > self.state.max_execution_time:
            self.logger.error(f"Execution time limit exceeded: {elapsed_time:.1f}s > {self.state.max_execution_time}s")
            return True
        
        return False
    
    def start_operation(self):
        """Start tracking an operation."""
        self.state.operation_start_time = time.time()
        self.state.current_operation = "unknown"
    
    def end_operation(self):
        """End tracking an operation."""
        self.state.operation_start_time = None
        self.state.current_operation = None
    
    def get_active_windows(self) -> List[WindowInfo]:
        """Get list of active windows."""
        return self.state.active_windows.copy()
    
    def get_mouse_position(self) -> Optional[MousePosition]:
        """Get current mouse position."""
        return self.state.last_mouse_position
    
    def prevent_sleep_mode(self, enabled: bool):
        """
        Enable or disable sleep prevention (recorded as a preference).

        Uses SetThreadExecutionState so the system stays awake while MJ AI
        works, without blocking dialogs.
        """
        self.state.prevent_sleep = enabled
        try:
            import ctypes
            ES_CONTINUOUS = 0x80000000
            ES_SYSTEM_REQUIRED = 0x00000001
            ES_DISPLAY_REQUIRED = 0x00000002
            flags = ES_CONTINUOUS
            if enabled:
                flags |= ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED
            ctypes.windll.kernel32.SetThreadExecutionState(flags)
        except Exception as e:
            self.logger.warning(f"Could not set sleep state: {e}")
        self.logger.debug(f"Sleep prevention {'enabled' if enabled else 'disabled'}")
