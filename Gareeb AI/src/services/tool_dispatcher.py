#!/usr/bin/env python3
"""
Tool dispatcher for MJ AI.

Single entry point used by the task planner. Routes each validated action to
the concrete service (automation, files, screen) and returns honest results -
never claims success it did not verify.
"""

from __future__ import annotations

import logging
from typing import Callable, Optional, Dict, Any


class ToolDispatchError(Exception):
    """Raised when an action cannot be dispatched."""


class ToolDispatcher:
    """
    Maps planner actions to service calls.

    The dispatcher assumes the permission layer has already approved the
    action; it still performs basic argument validation as defence in depth.
    """

    def __init__(self,
                 automation_service=None,
                 screen_analyzer=None,
                 file_utils=None):
        self.logger = logging.getLogger(__name__)
        self.automation = automation_service
        self.screen = screen_analyzer
        self.files = file_utils

        # Action registry - only these actions can ever run.
        self._handlers: Dict[str, Callable[[Dict[str, Any]], Any]] = {
            # Desktop automation
            "open_app": self._open_app,
            "search_web": self._search_web,
            "switch_window": self._switch_window,
            "minimize_window": self._minimize_window,
            "maximize_window": self._maximize_window,
            "type_text": self._type_text,
            "press_key": self._press_key,
            "mouse_click": self._mouse_click,
            # Screen
            "capture_screen": self._capture_screen,
            "read_screen": self._read_screen,
            # Files
            "create_file": self._create_file,
            "read_file": self._read_file,
            "create_folder": self._create_folder,
            "move_file": self._move_file,
            "copy_file": self._copy_file,
            "rename_file": self._rename_file,
            "search_files": self._search_files,
            # No-ops handled by the planner itself
            "wait": lambda p: p.get("seconds", 0),
            "respond": lambda p: p.get("text", ""),
        }

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------
    def dispatch(self, action: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """Execute a single action and return its result."""
        handler = self._handlers.get(action)
        if handler is None:
            raise ToolDispatchError(
                f"Unknown action '{action}'. Supported: "
                f"{', '.join(sorted(self._handlers))}"
            )

        params = params or {}
        self.logger.info(f"Dispatching '{action}' with params: {list(params.keys())}")

        try:
            return handler(params)
        except (ToolDispatchError, ValueError):
            raise
        except Exception as exc:
            # Never swallow errors silently - the planner records them.
            self.logger.error(f"Action '{action}' failed: {exc}")
            raise

    @property
    def supported_actions(self) -> list:
        return sorted(self._handlers)

    # ------------------------------------------------------------------
    # Desktop automation
    # ------------------------------------------------------------------
    def _require(self, service, name: str):
        if service is None:
            raise ToolDispatchError(f"{name} is not available.")
        return service

    def _open_app(self, p: Dict[str, Any]) -> Dict[str, Any]:
        app = p.get("app") or p.get("name") or p.get("application")
        if not app:
            raise ToolDispatchError("'open_app' requires an 'app' name.")
        auto = self._require(self.automation, "Desktop automation")
        if auto.start_operation:
            auto.start_operation()
        ok = auto.open_application(str(app))
        if auto.end_operation:
            auto.end_operation()
        if not ok:
            raise ToolDispatchError(f"Could not open '{app}'.")
        return {"opened": True, "app": app, "verified": True}

    def _search_web(self, p: Dict[str, Any]) -> Dict[str, Any]:
        """Search a fixed web search endpoint in Firefox for a user query."""
        query = p.get("query")
        app = str(p.get("app", "firefox")).strip().lower()
        if not isinstance(query, str) or not query.strip():
            raise ToolDispatchError("'search_web' requires a non-empty 'query'.")
        if app not in {"firefox", "firefox.exe"}:
            raise ToolDispatchError("Web searches are currently limited to Firefox.")

        auto = self._require(self.automation, "Desktop automation")
        if auto.start_operation:
            auto.start_operation()
        try:
            ok = auto.search_web(query.strip())
        finally:
            if auto.end_operation:
                auto.end_operation()
        if not ok:
            raise ToolDispatchError("Firefox could not open the web search.")
        return {"searched": True, "query": query.strip(), "app": "firefox"}

    def _switch_window(self, p: Dict[str, Any]) -> Dict[str, Any]:
        auto = self._require(self.automation, "Desktop automation")
        title = p.get("title") or p.get("window") or p.get("name")
        if not title:
            raise ToolDispatchError("'switch_window' requires a window 'title'.")
        ok = auto.switch_to_window(str(title))
        if not ok:
            raise ToolDispatchError(f"Window '{title}' not found.")
        return {"switched": True, "title": title}

    def _minimize_window(self, p: Dict[str, Any]) -> Dict[str, Any]:
        auto = self._require(self.automation, "Desktop automation")
        title = p.get("title") or p.get("window") or p.get("name")
        if not title:
            raise ToolDispatchError("'minimize_window' requires a window 'title'.")
        ok = auto.minimize_window(str(title))
        if not ok:
            raise ToolDispatchError(f"Window '{title}' not found.")
        return {"minimized": True, "title": title}

    def _maximize_window(self, p: Dict[str, Any]) -> Dict[str, Any]:
        auto = self._require(self.automation, "Desktop automation")
        title = p.get("title") or p.get("window") or p.get("name")
        if not title:
            raise ToolDispatchError("'maximize_window' requires a window 'title'.")
        ok = auto.maximize_window(str(title))
        if not ok:
            raise ToolDispatchError(f"Window '{title}' not found.")
        return {"maximized": True, "title": title}

    def _type_text(self, p: Dict[str, Any]) -> Dict[str, Any]:
        auto = self._require(self.automation, "Desktop automation")
        text = p.get("text")
        if text is None:
            raise ToolDispatchError("'type_text' requires 'text'.")
        delay = float(p.get("delay", 0.05))
        ok = auto.type_text(str(text), delay=delay)
        if not ok:
            raise ToolDispatchError("Typing failed (keyboard input may be disabled).")
        return {"typed": True, "length": len(str(text))}

    def _press_key(self, p: Dict[str, Any]) -> Dict[str, Any]:
        auto = self._require(self.automation, "Desktop automation")
        key = p.get("key")
        if not key:
            raise ToolDispatchError("'press_key' requires a 'key'.")
        modifiers = p.get("modifiers") or []
        if isinstance(modifiers, str):
            modifiers = [modifiers]
        ok = auto.press_key(str(key), [str(m) for m in modifiers])
        if not ok:
            raise ToolDispatchError(f"Could not press key '{key}'.")
        return {"pressed": True, "key": key}

    def _mouse_click(self, p: Dict[str, Any]) -> Dict[str, Any]:
        auto = self._require(self.automation, "Desktop automation")
        if "x" not in p or "y" not in p:
            raise ToolDispatchError("'mouse_click' requires 'x' and 'y'.")
        ok = auto.click_at(int(p["x"]), int(p["y"]))
        if not ok:
            raise ToolDispatchError("Click failed (mouse control may be disabled).")
        return {"clicked": True, "x": p["x"], "y": p["y"]}

    # ------------------------------------------------------------------
    # Screen
    # ------------------------------------------------------------------
    def _capture_screen(self, p: Dict[str, Any]) -> Dict[str, Any]:
        screen = self._require(self.screen, "Screen analyzer")
        image = screen.capture(save=bool(p.get("save", True)))
        return {
            "captured": True,
            "path": screen.state.last_screenshot_path,
            "size": [image.width, image.height],
        }

    def _read_screen(self, p: Dict[str, Any]) -> Dict[str, Any]:
        screen = self._require(self.screen, "Screen analyzer")
        content = screen.analyze()
        if content.error and not content.has_text:
            raise ToolDispatchError(content.error)
        return {
            "text": content.text,
            "summary": screen.summarize(content),
            "errors": screen.explain_errors(content),
            "path": content.screenshot_path,
        }

    # ------------------------------------------------------------------
    # Files (never destructive without the permission layer's confirmation)
    # ------------------------------------------------------------------
    def _file_utils(self):
        return self._require(self.files, "File utilities")

    def _create_file(self, p: Dict[str, Any]) -> Dict[str, Any]:
        files = self._file_utils()
        path = p.get("path") or p.get("file_path")
        if not path:
            raise ToolDispatchError("'create_file' requires a 'path'.")
        content = p.get("content", "")
        overwrite = bool(p.get("overwrite", False))

        # Never overwrite silently: the caller must ask for it explicitly,
        # and the permission layer confirms sensitive writes.
        from pathlib import Path
        if Path(str(path)).exists() and not overwrite:
            raise ToolDispatchError(
                f"File already exists: {path}. Pass overwrite=true to replace it."
            )

        result = files.create_text_file(str(path), str(content),
                                         confirm_overwrite=False)
        if not result:
            raise ToolDispatchError(f"File could not be written: {path}")

        # Verification - never claim success without checking.
        exists = Path(str(path)).exists()
        if not exists:
            raise ToolDispatchError("File write reported success but file is missing.")
        return {"created": True, "path": str(path), "verified": True}

    def _read_file(self, p: Dict[str, Any]) -> Dict[str, Any]:
        files = self._file_utils()
        path = p.get("path") or p.get("file_path")
        if not path:
            raise ToolDispatchError("'read_file' requires a 'path'.")
        text = files.safe_read_file(str(path))
        max_len = int(p.get("max_chars", 8000))
        truncated = len(text) > max_len
        return {"content": text[:max_len], "truncated": truncated,
                "length": len(text)}

    def _create_folder(self, p: Dict[str, Any]) -> Dict[str, Any]:
        files = self._file_utils()
        path = p.get("path") or p.get("folder") or p.get("directory")
        if not path:
            raise ToolDispatchError("'create_folder' requires a 'path'.")
        files.safe_create_directory(str(path))
        from pathlib import Path
        if not Path(str(path)).is_dir():
            raise ToolDispatchError("Folder was not created.")
        return {"created": True, "path": str(path), "verified": True}

    def _move_file(self, p: Dict[str, Any]) -> Dict[str, Any]:
        files = self._file_utils()
        src = p.get("src_path") or p.get("source")
        dst = p.get("dst_path") or p.get("destination")
        if not src or not dst:
            raise ToolDispatchError("'move_file' requires 'src_path' and 'dst_path'.")
        ok = files.safe_move_file(str(src), str(dst),
                                  overwrite=bool(p.get("overwrite", False)),
                                  confirm=False)  # confirmation done by planner
        if not ok:
            raise ToolDispatchError(f"Move failed: {src} -> {dst}")
        return {"moved": True, "from": str(src), "to": str(dst)}

    def _copy_file(self, p: Dict[str, Any]) -> Dict[str, Any]:
        files = self._file_utils()
        src = p.get("src_path") or p.get("source")
        dst = p.get("dst_path") or p.get("destination")
        if not src or not dst:
            raise ToolDispatchError("'copy_file' requires 'src_path' and 'dst_path'.")
        ok = files.safe_copy_file(str(src), str(dst),
                                  overwrite=bool(p.get("overwrite", False)))
        if not ok:
            raise ToolDispatchError(f"Copy failed: {src} -> {dst}")
        return {"copied": True, "from": str(src), "to": str(dst)}

    def _rename_file(self, p: Dict[str, Any]) -> Dict[str, Any]:
        files = self._file_utils()
        src = p.get("src_path") or p.get("path") or p.get("source")
        new_name = p.get("new_name") or p.get("name") or p.get("dst_path")
        if not src or not new_name:
            raise ToolDispatchError("'rename_file' requires 'path' and 'new_name'.")
        from pathlib import Path
        source = Path(str(src))
        target = (source.parent / str(new_name)) if not Path(str(new_name)).is_absolute() \
            else Path(str(new_name))
        ok = files.safe_move_file(str(source), str(target),
                                  overwrite=False, confirm=False)
        if not ok:
            raise ToolDispatchError(f"Rename failed: {src} -> {new_name}")
        return {"renamed": True, "from": str(source), "to": str(target)}

    def _search_files(self, p: Dict[str, Any]) -> Dict[str, Any]:
        files = self._file_utils()
        directory = p.get("directory") or p.get("folder") or p.get("path")
        query = p.get("query") or p.get("text") or ""
        if not directory:
            raise ToolDispatchError("'search_files' requires a 'directory'.")
        results = files.search_in_directory(
            str(directory), str(query),
            recursive=bool(p.get("recursive", False)),
        )
        return {"directory": str(directory), "query": str(query),
                "matches": results, "count": len(results)}
