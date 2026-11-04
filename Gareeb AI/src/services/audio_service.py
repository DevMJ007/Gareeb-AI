#!/usr/bin/env python3
"""
Voice service for MJ AI (FR-02).

Push-to-talk by default: the microphone only records between an explicit
start and stop. Provides speech-to-text (faster-whisper when available),
text-to-speech (pyttsx3), and clear state reporting so the UI can
show when the mic is active.
"""

from __future__ import annotations

import time
import queue
import logging
import threading
import re
from typing import Callable, Optional, Dict, Any
from dataclasses import dataclass, field
from core.resource_monitor import cpu_thread_limit

try:
    import pyttsx3
    _PYTTSX3_AVAILABLE = True
except Exception:  # pragma: no cover - optional
    pyttsx3 = None
    _PYTTSX3_AVAILABLE = False

try:
    from faster_whisper import WhisperModel
    _FASTER_WHISPER_AVAILABLE = True
except Exception:  # pragma: no cover - optional/heavy
    WhisperModel = None
    _FASTER_WHISPER_AVAILABLE = False

try:
    import pyaudio
    _PYAUDIO_AVAILABLE = True
except Exception:  # pragma: no cover - optional
    pyaudio = None
    _PYAUDIO_AVAILABLE = False


class VoiceError(Exception):
    """Raised for voice subsystem failures."""


@dataclass
class AudioState:
    """Snapshot of the voice subsystem state."""
    is_listening: bool = False
    is_processing: bool = False
    is_speaking: bool = False
    mic_toggle_on: bool = False
    auto_start_listening: bool = False
    wake_word_enabled: bool = False
    wake_word: str = "hey gareeb"
    recognition_language: str = "en"
    wake_word_detected: bool = False
    microphone_allowed: bool = False
    mic_active: bool = False
    tts_enabled: bool = True
    tts_speed: float = 1.0
    tts_volume: float = 1.0
    asr_available: bool = False
    tts_available: bool = False
    audio_input_available: bool = False
    last_error: str = ""
    audio_devices: list = field(default_factory=list)


class AudioService:
    """
    Audio input/output for MJ AI.

    Recording only happens after the microphone is toggled on with begin_listening().
    Toggling it off submits the captured audio for transcription.
    Nothing is ever captured silently.
    """

    SAMPLE_RATE = 16000
    CHUNK = 1024
    CHANNELS = 1

    def __init__(self,
                 config_manager=None,
                 audio_event_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None,
                 text_sink: Optional[Callable[[str], None]] = None):
        self.logger = logging.getLogger(__name__)
        self.config_manager = config_manager
        self.audio_event_callback = audio_event_callback
        # Where recognised text is delivered (usually AIService.send_message).
        self.text_sink = text_sink

        self.state = AudioState()
        self._running = False

        # Recording machinery
        self._record_frames: list = []
        self._recording = False
        self._record_lock = threading.Lock()
        self._pa: Any = None
        self._stream: Any = None

        # Worker threads
        self._transcribe_thread: Optional[threading.Thread] = None
        self._tts_thread: Optional[threading.Thread] = None
        self._tts_queue: "queue.Queue[str]" = queue.Queue()
        self._cancel_event = threading.Event()

        # Engines (created lazily on start())
        self._whisper: Any = None
        self._tts_engine: Any = None

        # Text fallback queue so the UI can always type commands.
        self.text_input_queue: "queue.Queue[str]" = queue.Queue()

        self._load_config()

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------
    def _load_config(self) -> None:
        if self.config_manager is None:
            return
        try:
            cfg = self.config_manager.get_audio_config()
            self.state.mic_toggle_on = False
            self.state.auto_start_listening = cfg.auto_start_listening
            self.state.wake_word_enabled = cfg.wake_word_enabled
            self.state.wake_word = cfg.wake_word
            self.state.recognition_language = getattr(cfg, "language", "en")
            self.state.tts_enabled = cfg.tts_enabled
            self.state.tts_speed = cfg.tts_speed
            self.state.tts_volume = cfg.tts_volume
            self.state.microphone_allowed = cfg.microphone_allowed
        except Exception as exc:
            self.logger.warning(f"Could not load audio config: {exc}")

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------
    def _emit(self, event: str, data: Optional[Dict[str, Any]] = None) -> None:
        if self.audio_event_callback is None:
            return
        try:
            self.audio_event_callback(event, data or {})
        except Exception as exc:
            self.logger.debug(f"Audio event callback error: {exc}")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def start(self) -> None:
        if self._running:
            return
        self._running = True

        # Detect capture device.
        self.state.audio_input_available = self._init_capture()
        if not self.state.audio_input_available:
            self.state.last_error = (
                "No microphone input available (pyaudio not installed or "
                "no device found). Use text input instead."
            )
            self.logger.warning(self.state.last_error)

        # Detect ASR engine.
        if _FASTER_WHISPER_AVAILABLE:
            # Model loads lazily on first use to avoid RAM use at startup.
            self.state.asr_available = True
        else:
            self.state.asr_available = False
            self.logger.warning(
                "faster-whisper not installed - voice recognition disabled, "
                "text input still available."
            )

        # pyttsx3/Windows SAPI owns COM state. Create and use its engine on
        # the same dedicated thread so Qt's UI thread never initializes COM
        # or blocks while speech is synthesized.
        self._cancel_event.clear()
        self.state.tts_available = False
        self._tts_thread = threading.Thread(target=self._tts_loop, daemon=True,
                                            name="mj-tts")
        self._tts_thread.start()

        self._emit("voice_state", self._state_dict())
        self.logger.info(
            f"Voice service started (input={self.state.audio_input_available}, "
            f"asr={self.state.asr_available}, tts={self.state.tts_available})"
        )

    def stop(self) -> None:
        self._running = False
        self._cancel_event.set()
        self.end_listening()
        self._close_capture()
        self._stop_tts()
        if (self._tts_thread is not None
                and self._tts_thread is not threading.current_thread()):
            self._tts_thread.join(timeout=1.5)
        self._emit("voice_state", self._state_dict())

    def cleanup(self) -> None:
        self.stop()
        self._whisper = None

    # ------------------------------------------------------------------
    # State helpers
    # ------------------------------------------------------------------
    def _state_dict(self) -> Dict[str, Any]:
        s = self.state
        return {
            "is_listening": s.is_listening,
            "is_speaking": s.is_speaking,
            "is_processing": s.is_processing,
            "mic_active": s.mic_active,
            "mic_toggle_on": s.mic_toggle_on,  # NEW: Toggle state
            "asr_available": s.asr_available,
            "tts_available": s.tts_available,
            "audio_input_available": s.audio_input_available,
            "microphone_allowed": s.microphone_allowed,
            "last_error": s.last_error,
        }

    def get_state(self) -> AudioState:
        return self.state

    # ------------------------------------------------------------------
    # Toggle-to-listen capture
    # ------------------------------------------------------------------
    def _init_capture(self) -> bool:
        if not _PYAUDIO_AVAILABLE:
            return False
        try:
            self._pa = pyaudio.PyAudio()
            # Find default input device.
            default_idx = self._pa.get_default_input_device_info().get("index")
            self.state.audio_devices = [
                self._pa.get_device_info_by_index(i)["name"]
                for i in range(self._pa.get_device_count())
                if self._pa.get_device_info_by_index(i).get("maxInputChannels", 0) > 0
            ]
            self._default_input = default_idx
            return default_idx is not None
        except Exception as exc:
            self.logger.warning(f"Mic init failed: {exc}")
            self._pa = None
            return False

    def _close_capture(self) -> None:
        self._stop_stream()
        if self._pa is not None:
            try:
                self._pa.terminate()
            except Exception:
                pass
            self._pa = None

    def _stop_stream(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop_stream()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

    def begin_listening(self) -> bool:
        """
        Start capturing audio (microphone toggle ON).

        Returns True when recording actually started.
        Clicking the microphone again calls end_listening() and submits the audio.
        """
        if self.state.is_listening:
            return True

        if not self.state.microphone_allowed:
            self.state.last_error = "Microphone permission is not granted."
            self._emit("voice_error", {"error": self.state.last_error})
            return False

        if not self.state.audio_input_available:
            self.state.last_error = (
                "No microphone available - use the text box instead."
            )
            self._emit("voice_error", {"error": self.state.last_error})
            return False

        with self._record_lock:
            self._record_frames = []
            try:
                self._stream = self._pa.open(
                    format=pyaudio.paInt16,
                    channels=self.CHANNELS,
                    rate=self.SAMPLE_RATE,
                    input=True,
                    input_device_index=getattr(self, "_default_input", None),
                    frames_per_buffer=self.CHUNK,
                )
                self._recording = True
            except Exception as exc:
                self.state.last_error = f"Could not open microphone: {exc}"
                self._emit("voice_error", {"error": self.state.last_error})
                return False

        self.state.is_listening = True
        self.state.mic_active = True
        self.state.mic_toggle_on = True  # NEW: Set toggle state

        # Capture pump thread.
        threading.Thread(target=self._capture_loop, daemon=True,
                         name="mj-capture").start()

        self._emit("listening_started", self._state_dict())
        return True

    def _capture_loop(self) -> None:
        while self._recording and self._running:
            try:
                data = self._stream.read(self.CHUNK, exception_on_overflow=False)
                with self._record_lock:
                    if self._recording:
                        self._record_frames.append(data)
            except Exception as exc:
                self.logger.warning(f"Capture error: {exc}")
                break
            time.sleep(0.01)

    def end_listening(self) -> None:
        """
        Stop capturing audio (microphone toggle OFF) and transcribe.
        Toggling the microphone off submits the recorded audio for transcription.
        """
        if not self.state.is_listening:
            return

        with self._record_lock:
            self._recording = False
            frames = list(self._record_frames)
            self._record_frames = []

        self._stop_stream()

        self.state.is_listening = False
        self.state.mic_active = False
        self.state.mic_toggle_on = False

        self._emit("listening_stopped", self._state_dict())

        if not frames:
            self._emit("voice_error", {"error": "No audio was captured."})
            return

        # Transcribe off the UI thread.
        self._transcribe_thread = threading.Thread(
            target=self._transcribe, args=(frames,), daemon=True,
            name="mj-transcribe")
        self._transcribe_thread.start()

    def toggle_listening(self, enabled: Optional[bool] = None) -> bool:
        """Convenience toggle for the mic button."""
        target = (not self.state.is_listening) if enabled is None else enabled
        if target:
            return self.begin_listening()
        self.end_listening()
        return True

    def cancel_current_operation(self) -> None:
        """Cancel ongoing transcription or speech."""
        self._cancel_event.set()
        self._recording = False
        self._stop_stream()
        self.state.is_listening = False
        self.state.mic_active = False
        self.state.mic_toggle_on = False
        self._stop_tts()
        self._emit("operation_cancelled", {"timestamp": time.time()})

    # ------------------------------------------------------------------
    # Speech to text
    # ------------------------------------------------------------------
    def _get_whisper(self):
        """Lazily create the ASR model (RAM friendly)."""
        if self._whisper is not None:
            return self._whisper
        if not _FASTER_WHISPER_AVAILABLE:
            raise VoiceError("faster-whisper is not installed.")
        self._emit("model_loading", {"model": "whisper-base"})
        # Share the configured CPU budget with local language model inference.
        try:
            performance = self.config_manager.get_performance_config()
            budget = performance.max_cpu_usage_percent
        except Exception:
            budget = 80
        cpu_threads = cpu_thread_limit(budget)
        # 'base' ≈ 150 MB RAM; cap threads so transcription does not occupy
        # every logical CPU on compact machines.
        self._whisper = WhisperModel(
            "base", device="cpu", compute_type="int8", cpu_threads=cpu_threads
        )
        return self._whisper

    def _frames_to_audio(self, frames: list):
        """Convert captured frames to a numpy array of floats."""
        import numpy as np
        raw = b"".join(frames)
        audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        return audio

    def _transcribe(self, frames: list) -> None:
        self.state.is_processing = True
        self._emit("transcription_started", self._state_dict())
        try:
            model = self._get_whisper()
            audio = self._frames_to_audio(frames)
            if len(audio) < int(self.SAMPLE_RATE * 0.4):
                self.state.last_error = (
                    "That recording was too short. Hold the microphone and "
                    "speak for a moment before releasing it."
                )
                self._emit("voice_error", {"error": self.state.last_error})
                return

            language = self.state.recognition_language
            language = None if language in ("", "auto", "automatic") else language
            segments, info = model.transcribe(
                audio,
                language=language,
                beam_size=3,
                vad_filter=True,
                condition_on_previous_text=False,
            )
            text = "".join(seg.text for seg in segments).strip()

            detected_language = getattr(info, "language", language or "unknown")
            try:
                language_confidence = float(
                    getattr(info, "language_probability", 0.0) or 0.0)
            except (TypeError, ValueError):
                language_confidence = 0.0
            self.logger.info(
                "Speech recognition finished "
                f"(language={detected_language}, "
                f"confidence={language_confidence:.2f}, "
                f"characters={len(text)})"
            )

            if self._cancel_event.is_set():
                self.state.is_processing = False
                return

            if not text:
                self.state.last_error = "Could not understand the audio."
                self._emit("voice_error", {"error": self.state.last_error})
                return

            self._emit("transcript", {
                "text": text,
                "language": detected_language,
                "language_confidence": language_confidence,
            })
            if self.text_sink is not None:
                self.text_sink(text)

        except Exception as exc:
            self.state.last_error = f"Speech recognition failed: {exc}"
            self.logger.error(self.state.last_error)
            self._emit("voice_error", {"error": self.state.last_error})
        finally:
            self.state.is_processing = False
            self._emit("transcription_finished", self._state_dict())

    # ------------------------------------------------------------------
    # Text to speech
    # ------------------------------------------------------------------
    def _init_tts(self) -> bool:
        if not _PYTTSX3_AVAILABLE or not self.state.tts_enabled:
            return False
        try:
            engine = pyttsx3.init()
            engine.setProperty("rate", int(180 * self.state.tts_speed))
            engine.setProperty("volume", max(0.0, min(1.0, self.state.tts_volume)))
            self._tts_engine = engine
            return True
        except Exception as exc:
            self.logger.warning(f"TTS init failed: {exc}")
            self._tts_engine = None
            return False

    def _tts_loop(self) -> None:
        try:
            self.state.tts_available = bool(self._init_tts())
        except Exception as exc:
            self.logger.warning("TTS worker initialization failed: %s", exc)
            self._tts_engine = None
        engine = self._tts_engine if self.state.tts_available else None
        self._emit("voice_state", self._state_dict())
        if engine is None:
            return

        def on_word(name, location, length):
            del name
            word = ""
            try:
                word = self._active_tts_text[int(location):int(location) + int(length)]
            except (AttributeError, TypeError, ValueError):
                pass
            syllables = max(1, len(re.findall(r"[aeiouy]+", word.lower())))
            level = min(0.9, 0.24 + syllables * 0.13)
            if len(word) > 8:
                level = min(0.95, level + 0.08)
            self._emit("speech_progress", {"level": level, "word": word})

        try:
            engine.connect("started-word", on_word)
        except Exception as exc:
            self.logger.debug("TTS word-boundary events unavailable: %s", exc)

        while self._running:
            try:
                text = self._tts_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            if not text or self._cancel_event.is_set():
                continue

            self.state.is_speaking = True
            self._active_tts_text = text
            self._emit("speech_started", {"text": text})
            try:
                # Settings are applied on the engine's owner thread.
                engine.setProperty("rate", int(180 * self.state.tts_speed))
                engine.setProperty("volume", max(0.0, min(1.0, self.state.tts_volume)))
                engine.say(text)
                engine.startLoop(False)
                while engine.isBusy():
                    if self._cancel_event.is_set() or not self._running:
                        engine.stop()
                        break
                    engine.iterate()
                    time.sleep(0.01)
                engine.endLoop()
            except Exception as exc:
                self.logger.warning(f"TTS playback failed: {exc}")
            finally:
                self.state.is_speaking = False
                self._emit("speech_progress", {"level": 0.0})
                self._emit("speech_finished", {})
                self._active_tts_text = ""

        try:
            engine.stop()
        except Exception:
            pass
        self._tts_engine = None

    def speak(self, text: str) -> bool:
        """Queue text for spoken output."""
        if not self.state.tts_enabled or not self._running:
            return False
        clean = (text or "").strip()
        if not clean:
            return False
        self._cancel_event.clear()
        self._tts_queue.put(clean)
        return True

    def stop_speaking(self) -> None:
        self._cancel_event.set()
        try:
            while True:
                self._tts_queue.get_nowait()
        except queue.Empty:
            pass
        self.state.is_speaking = False

    def _stop_tts(self) -> None:
        self.stop_speaking()

    # ------------------------------------------------------------------
    # Settings updates
    # ------------------------------------------------------------------
    def set_microphone_allowed(self, allowed: bool) -> None:
        self.state.microphone_allowed = bool(allowed)
        if not allowed:
            self.end_listening()
        self._emit("voice_state", self._state_dict())

    def set_recognition_language(self, language: str) -> None:
        """Select a Whisper language code or ``auto`` for detection."""
        language = str(language or "en").strip().lower()
        self.state.recognition_language = language if language else "en"
        self.logger.info(
            "Speech recognition language set to %s",
            self.state.recognition_language,
        )

    def update_volume(self, volume: float) -> None:
        self.state.tts_volume = max(0.0, min(1.0, float(volume)))

    def update_tts_speed(self, speed: float) -> None:
        self.state.tts_speed = max(0.5, min(3.0, speed))

    # ------------------------------------------------------------------
    # Text input fallback
    # ------------------------------------------------------------------
    def submit_text(self, text: str) -> bool:
        """
        Accept a typed command - the guaranteed fallback when the mic is
        unavailable or speech recognition fails.
        """
        clean = (text or "").strip()
        if not clean:
            return False
        self._emit("transcript", {"text": clean, "source": "text"})
        if self.text_sink is not None:
            self.text_sink(clean)
        return True
