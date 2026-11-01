#!/usr/bin/env python3
"""
Screen understanding for MJ AI (FR-05).

Captures a screenshot only when requested and permitted, extracts text with
OCR (Tesseract) as the first-line technique, and summarizes or speaks the
result. Vision models are never loaded automatically.
"""

from __future__ import annotations

import time
import logging
import os
import threading
from typing import Callable, Optional, Dict, Any, List
from pathlib import Path
from core.app_paths import data_path
from dataclasses import dataclass, field

import pyautogui
from PIL import Image

try:
    import pytesseract
    _OCR_AVAILABLE = True
except Exception:  # pragma: no cover - optional
    pytesseract = None
    _OCR_AVAILABLE = False

try:
    import pyttsx3
    _TTS_AVAILABLE = True
except Exception:  # pragma: no cover - optional
    pyttsx3 = None
    _TTS_AVAILABLE = False

# Common Windows install locations for the Tesseract binary. The per-user
# location is derived at runtime so the app works under any Windows account.
_TESSERACT_CANDIDATES = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
]

# Screenshots are downscaled before analysis to bound memory usage.
MAX_ANALYSIS_WIDTH = 1600


@dataclass
class TextBlock:
    """A piece of text found on screen."""
    text: str
    x: int
    y: int
    width: int
    height: int
    confidence: float


@dataclass
class ScreenContent:
    """Result of a screen analysis."""
    image: Optional[Image.Image] = None
    text: str = ""
    text_blocks: List[TextBlock] = field(default_factory=list)
    screenshot_path: Optional[str] = None
    timestamp: float = 0.0
    ocr_used: bool = False
    error: str = ""

    @property
    def has_text(self) -> bool:
        return bool(self.text.strip())


@dataclass
class ScreenState:
    """Current screen analyzer state."""
    is_capturing: bool = False
    is_analyzing: bool = False
    last_screenshot_path: Optional[str] = None
    screen_capture_allowed: bool = False
    current_screen_text: str = ""
    ocr_available: bool = False
    tesseract_found: bool = False


class ScreenPermissionRequired(Exception):
    """Raised when screen capture is attempted without permission."""


class ScreenAnalyzer:
    """
    Screenshot + OCR analysis with strict permission gating.

    Nothing is captured unless the user granted screen-capture permission
    and the capture was explicitly requested.
    """

    def __init__(self,
                 config_manager=None,
                 resource_monitor=None,
                 screen_event_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None):
        self.logger = logging.getLogger(__name__)
        self.config_manager = config_manager
        self.resource_monitor = resource_monitor
        self.screen_event_callback = screen_event_callback

        self.state = ScreenState()
        self.state.ocr_available = _OCR_AVAILABLE

        self._tts: Any = None
        self._lock = threading.Lock()

        self._configure_tesseract()
        self._load_permission()

        self.logger.info(
            f"Screen analyzer initialized (ocr={self.state.ocr_available}, "
            f"tesseract={self.state.tesseract_found})"
        )

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------
    def _configure_tesseract(self) -> None:
        if not _OCR_AVAILABLE:
            return
        candidates = list(_TESSERACT_CANDIDATES)
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            candidates.append(str(
                Path(local_app_data) / "Programs" / "Tesseract-OCR" /
                "tesseract.exe"
            ))
        else:
            candidates.append(str(
                Path.home() / "AppData" / "Local" / "Programs" /
                "Tesseract-OCR" / "tesseract.exe"
            ))

        for candidate in candidates:
            if Path(candidate).exists():
                pytesseract.pytesseract.tesseract_cmd = candidate
                self.state.tesseract_found = True
                return
        # Fall back to PATH resolution.
        import shutil
        found = shutil.which("tesseract")
        if found:
            pytesseract.pytesseract.tesseract_cmd = found
            self.state.tesseract_found = True

    def _load_permission(self) -> None:
        if self.config_manager is None:
            return
        try:
            self.state.screen_capture_allowed = bool(
                self.config_manager.get_audio_config().screen_capture_allowed
            )
        except Exception as exc:
            self.logger.warning(f"Could not load screen permission: {exc}")

    def _emit(self, event: str, data: Optional[Dict[str, Any]] = None) -> None:
        if self.screen_event_callback is None:
            return
        try:
            self.screen_event_callback(event, data or {})
        except Exception as exc:
            self.logger.debug(f"Screen event callback error: {exc}")

    # ------------------------------------------------------------------
    # Permission
    # ------------------------------------------------------------------
    def set_screen_capture_permission(self, allowed: bool) -> None:
        self.state.screen_capture_allowed = bool(allowed)
        self.logger.info(
            f"Screen capture permission {'granted' if allowed else 'revoked'}"
        )
        self._emit("permission_changed", {"screen_capture": allowed})

    def _require_permission(self) -> None:
        if not self.state.screen_capture_allowed:
            raise ScreenPermissionRequired(
                "Screen capture permission has not been granted. "
                "Enable it in Settings > Audio > Permissions."
            )

    # ------------------------------------------------------------------
    # Capture
    # ------------------------------------------------------------------
    @staticmethod
    def _downscale(image: Image.Image, max_width: int = MAX_ANALYSIS_WIDTH) -> Image.Image:
        """Shrink large screenshots before OCR to limit CPU/RAM use."""
        if image.width <= max_width:
            return image
        ratio = max_width / float(image.width)
        new_size = (max_width, max(1, int(image.height * ratio)))
        return image.resize(new_size, Image.LANCZOS)

    def capture(self, save: bool = True) -> Image.Image:
        """
        Capture the screen (permission gated).

        Raises ScreenPermissionRequired when not permitted.
        """
        self._require_permission()

        with self._lock:
            if self.state.is_capturing:
                raise RuntimeError("A capture is already in progress.")
            self.state.is_capturing = True

        try:
            shot = pyautogui.screenshot()
            # pyautogui returns a PIL image; tolerate ndarray too.
            if not isinstance(shot, Image.Image):
                import numpy as np
                shot = Image.fromarray(np.asarray(shot))

            self._emit("screenshot_captured", {
                "width": shot.width, "height": shot.height,
                "timestamp": time.time(),
            })

            if save:
                path = self._save_screenshot(shot)
                self.state.last_screenshot_path = path

            return shot

        finally:
            self.state.is_capturing = False

    def _save_screenshot(self, image: Image.Image) -> Optional[str]:
        try:
            out_dir = data_path("screenshots")
            out_dir.mkdir(parents=True, exist_ok=True)
            path = out_dir / f"screen_{int(time.time())}.png"
            image.save(str(path))
            return str(path)
        except Exception as exc:
            self.logger.warning(f"Could not save screenshot: {exc}")
            return None

    # ------------------------------------------------------------------
    # OCR
    # ------------------------------------------------------------------
    def extract_text(self, image: Image.Image) -> "tuple[str, List[TextBlock]]":
        """Run OCR and return (text, blocks)."""
        if not self.state.ocr_available or not self.state.tesseract_found:
            return "", []

        try:
            small = self._downscale(image)
            text = pytesseract.image_to_string(small) or ""

            blocks: List[TextBlock] = []
            try:
                data = pytesseract.image_to_data(
                    small, output_type=pytesseract.Output.DICT
                )
                for i, word in enumerate(data.get("text", [])):
                    if not word or not str(word).strip():
                        continue
                    conf = float(data.get("conf", ["0"])[i])
                    blocks.append(TextBlock(
                        text=str(word),
                        x=int(data["left"][i]),
                        y=int(data["top"][i]),
                        width=int(data["width"][i]),
                        height=int(data["height"][i]),
                        confidence=conf,
                    ))
            except Exception as exc:
                self.logger.debug(f"Word-level OCR unavailable: {exc}")

            return text.strip(), blocks

        except Exception as exc:
            self.logger.error(f"OCR failed: {exc}")
            return "", []

    # ------------------------------------------------------------------
    # High level analysis
    # ------------------------------------------------------------------
    def analyze(self, request_permission: bool = True) -> ScreenContent:
        """
        Capture + OCR the current screen.

        request_permission: kept for API clarity; permission is read from the
        stored grant and raises when missing.
        """
        self._require_permission()

        with self._lock:
            if self.state.is_analyzing:
                raise RuntimeError("An analysis is already in progress.")
            self.state.is_analyzing = True

        result = ScreenContent(timestamp=time.time())

        try:
            self._emit("screen_analysis_started", {})

            image = self.capture(save=True)
            result.image = image
            result.screenshot_path = self.state.last_screenshot_path

            if self.state.ocr_available and self.state.tesseract_found:
                text, blocks = self.extract_text(image)
                result.text = text
                result.text_blocks = blocks
                result.ocr_used = True
                self.state.current_screen_text = text
            else:
                result.error = (
                    "OCR is unavailable (Tesseract not found). "
                    "Install Tesseract OCR to read screen text."
                )

            self._emit("screen_analysis_finished", {
                "has_text": result.has_text,
                "block_count": len(result.text_blocks),
                "error": result.error,
                "text": result.text[:500],
            })
            return result

        except Exception as exc:
            result.error = str(exc)
            self.logger.error(f"Screen analysis failed: {exc}")
            self._emit("screen_analysis_error", {"error": str(exc)})
            return result
        finally:
            self.state.is_analyzing = False

    # ------------------------------------------------------------------
    # Summarize
    # ------------------------------------------------------------------
    @staticmethod
    def summarize(content: ScreenContent) -> str:
        """Produce a short, honest summary of what is readable on screen."""
        if content.error and not content.has_text:
            return f"I couldn't read the screen: {content.error}"

        text = content.text.strip()
        if not text:
            return (
                "I captured the screen but couldn't find readable text. "
                "The screen may be image-only or too low contrast for OCR."
            )

        words = text.split()
        # First two sentences as a brief summary.
        sentences = [s.strip() for s in text.replace("\n", " ").split(". ") if s.strip()]
        if len(sentences) >= 2:
            brief = ". ".join(sentences[:2]) + "."
        else:
            brief = sentences[0] if sentences else text

        extra = f" (about {len(words)} words visible.)"
        if len(words) > 40:
            return f"On screen: {brief}{extra}"
        return f"On screen: {brief}"

    def explain_errors(self, content: ScreenContent) -> List[str]:
        """Detect likely error messages in the OCR text."""
        error_markers = (
            "error", "exception", "failed", "failure", "cannot", "unable",
            "denied", "not found", "critical", "fatal", "警告", "错误",
        )
        found: List[str] = []
        for line in content.text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            low = stripped.lower()
            if any(marker in low for marker in error_markers):
                found.append(stripped)
        return found[:10]

    # ------------------------------------------------------------------
    # Speech output for screen content
    # ------------------------------------------------------------------
    def _get_tts(self):
        if self._tts is not None:
            return self._tts
        if not _TTS_AVAILABLE:
            return None
        try:
            engine = pyttsx3.init()
            engine.setProperty("rate", 170)
            self._tts = engine
            return self._tts
        except Exception as exc:
            self.logger.warning(f"TTS init failed: {exc}")
            return None

    def speak_text(self, text: str, blocking: bool = False) -> bool:
        """Speak given text (used for 'explain my screen' by voice)."""
        if not text:
            return False
        engine = self._get_tts()
        if engine is None:
            return False

        def _speak():
            try:
                engine.say(text)
                engine.runAndWait()
            except Exception as exc:
                self.logger.warning(f"Speech failed: {exc}")

        if blocking:
            _speak()
        else:
            threading.Thread(target=_speak, daemon=True).start()
        return True

    def speak_content(self, content: ScreenContent) -> bool:
        """Speak a summary of the screen content."""
        return self.speak_text(self.summarize(content))

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------
    def get_status(self) -> Dict[str, Any]:
        return {
            "ocr_available": self.state.ocr_available,
            "tesseract_found": self.state.tesseract_found,
            "screen_capture_allowed": self.state.screen_capture_allowed,
            "last_screenshot": self.state.last_screenshot_path,
            "is_analyzing": self.state.is_analyzing,
            "is_capturing": self.state.is_capturing,
        }

    def get_current_screen_text(self) -> str:
        return self.state.current_screen_text

    def is_busy(self) -> bool:
        return self.state.is_analyzing or self.state.is_capturing

    # ------------------------------------------------------------------
    # Lifecycle stubs (kept for API compatibility with app.py)
    # ------------------------------------------------------------------
    def start(self) -> None:
        self.logger.debug("Screen analyzer ready")

    def stop(self) -> None:
        pass

    def cleanup(self) -> None:
        if self._tts is not None:
            try:
                self._tts.stop()
            except Exception:
                pass
            self._tts = None
