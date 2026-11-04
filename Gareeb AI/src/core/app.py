#!/usr/bin/env python3
"""
MJ AI application entry point.

Builds the object graph (config -> memory -> permissions -> services -> UI),
starts background workers, runs the Qt event loop, and shuts everything down
cleanly.
"""

from __future__ import annotations

import sys
import os
import logging
import traceback
from pathlib import Path
from typing import Optional

# Make the src package importable regardless of the working directory.
SRC_DIR = Path(__file__).resolve().parent.parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from PySide6.QtWidgets import QApplication, QSplashScreen
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap

from core.config_manager import ConfigManager
from core.app_paths import app_data_dir, project_root
from core.resource_monitor import ResourceMonitor
from core.permissions import PermissionManager
from core.memory_store import MemoryStore
from core.task_planner import TaskPlanner
from services.ai_service import AIService
from services.audio_service import AudioService
from services.automation_service import AutomationService
from services.screen_analyzer import ScreenAnalyzer
from services.tool_dispatcher import ToolDispatcher
from utils.file_utils import FileUtils
from ui.main_window import MainWindow


class MJAIApp:
    """
    Application controller.

    Owns the service graph and the Qt application object.
    """

    def __init__(self) -> None:
        self.app = QApplication.instance()
        if self.app is None:
            self.app = QApplication(sys.argv)

        self.config_manager: Optional[ConfigManager] = None
        self.memory_store: Optional[MemoryStore] = None
        self.permissions: Optional[PermissionManager] = None
        self.resource_monitor: Optional[ResourceMonitor] = None
        self.file_utils: Optional[FileUtils] = None
        self.dispatcher: Optional[ToolDispatcher] = None
        self.task_planner: Optional[TaskPlanner] = None
        self.ai_service: Optional[AIService] = None
        self.audio_service: Optional[AudioService] = None
        self.screen_analyzer: Optional[ScreenAnalyzer] = None
        self.automation_service: Optional[AutomationService] = None
        self.main_window: Optional[MainWindow] = None
        self.splash_screen: Optional[QSplashScreen] = None

        self.logger = logging.getLogger("mjai")
        self.data_dir = app_data_dir()
        self._setup_logging()
        self._setup_directories()

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------
    def _setup_logging(self) -> None:
        log_dir = self.data_dir / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)

        handlers: list = [logging.StreamHandler(sys.stdout)]
        try:
            from logging.handlers import RotatingFileHandler
            handlers.insert(0, RotatingFileHandler(
                log_dir / "mjai.log",
                maxBytes=10 * 1024 * 1024,
                backupCount=3,
                encoding="utf-8",
            ))
        except Exception:
            handlers.append(logging.FileHandler(log_dir / "mjai.log",
                                                encoding="utf-8"))

        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            handlers=handlers,
            force=True,
        )
        self.logger.info("Gareeb AI starting up")

    def _setup_directories(self) -> None:
        for name in ("logs", "models", "config", "data", "screenshots"):
            (self.data_dir / name).mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------
    def initialize_services(self) -> bool:
        try:
            self.logger.info("Initializing services…")

            # 1. Configuration
            self.config_manager = ConfigManager()

            # 2. Local memory (SQLite)
            try:
                self.memory_store = MemoryStore.from_config(self.config_manager)
            except Exception as exc:
                self.logger.error(f"Memory store failed: {exc}")
                self.memory_store = None

            # 3. Safety layer
            self.permissions = PermissionManager(self.config_manager)

            # 4. Resource monitor
            self.resource_monitor = ResourceMonitor(self.config_manager)
            self.resource_monitor.start_monitoring()

            # 5. Tool layer
            self.file_utils = FileUtils(self.config_manager)
            self.automation_service = AutomationService(
                self.config_manager, self.resource_monitor,
                self._automation_callback,
            )
            self.screen_analyzer = ScreenAnalyzer(
                self.config_manager, self.resource_monitor,
                self._screen_callback,
            )
            self.screen_analyzer.start()

            self.dispatcher = ToolDispatcher(
                automation_service=self.automation_service,
                screen_analyzer=self.screen_analyzer,
                file_utils=self.file_utils,
            )

            # 6. Task engine
            self.task_planner = TaskPlanner(
                permissions=self.permissions,
                dispatcher=self.dispatcher.dispatch,
                memory_store=self.memory_store,
                progress_callback=self._planner_callback,
                max_execution_time=(
                    self.config_manager.get_automation_config().max_execution_time
                ),
            )

            # 7. AI service (depends on planner + memory)
            self.ai_service = AIService(
                self.config_manager,
                self.resource_monitor,
                self._ai_callback,
                memory_store=self.memory_store,
                permissions=self.permissions,
                task_planner=self.task_planner,
            )

            # 8. Voice service (delivers transcripts to the AI)
            self.audio_service = AudioService(
                self.config_manager,
                self._audio_callback,
                text_sink=self._on_voice_text,
            )

            self.logger.info("All services initialized")
            return True

        except Exception as exc:
            self.logger.error(f"Service initialization failed: {exc}")
            traceback.print_exc()
            return False

    # ------------------------------------------------------------------
    # Service event callbacks (worker threads -> main window)
    # ------------------------------------------------------------------
    def _ai_callback(self, event: str, data: dict) -> None:
        if self.main_window is not None:
            self.main_window.on_ai_event(event, data)

    def _audio_callback(self, event: str, data: dict) -> None:
        if self.main_window is not None:
            self.main_window.on_audio_event(event, data)

    def _screen_callback(self, event: str, data: dict) -> None:
        if self.main_window is not None:
            self.main_window.on_screen_event(event, data)

    def _automation_callback(self, event: str, data: dict) -> None:
        if self.main_window is not None:
            self.main_window.on_automation_event(event, data)

    def _planner_callback(self, payload: dict) -> None:
        if self.main_window is not None:
            self.main_window.on_planner_progress(payload)

    def _on_voice_text(self, text: str) -> None:
        """Voice transcript delivery: display happens via the transcript
        event, so here we only hand the text to the AI."""
        if self.ai_service is not None:
            self.ai_service.send_message(text)

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def create_main_window(self) -> bool:
        try:
            self.logger.info("Creating main window…")

            self.main_window = MainWindow(
                config_manager=self.config_manager,
                ai_service=self.ai_service,
                audio_service=self.audio_service,
                screen_analyzer=self.screen_analyzer,
                automation_service=self.automation_service,
                resource_monitor=self.resource_monitor,
                task_planner=self.task_planner,
                memory_store=self.memory_store,
            )
            MainWindow.app_ref = self.app

            self.main_window.show_companion()

            # Push stored permissions into the live services.
            audio_cfg = self.config_manager.get_audio_config()
            self.audio_service.set_microphone_allowed(audio_cfg.microphone_allowed)
            self.screen_analyzer.set_screen_capture_permission(
                audio_cfg.screen_capture_allowed)

            # Welcome message.
            self.main_window.conversation.append_status(
                "Gareeb is ready. Click the floating face to open chat. Click "
                "the mic to start listening, then click again to send, or type below."
            )

            self._first_run_permission_prompt()

            self.logger.info("Main window ready")
            return True

        except Exception as exc:
            self.logger.error(f"Window creation failed: {exc}")
            traceback.print_exc()
            return False

    def _first_run_permission_prompt(self) -> None:
        """Ask once for microphone / screen capture consent (PRD section 8)."""
        try:
            asked = False
            if self.memory_store is not None:
                asked = bool(self.memory_store.get_preference(
                    "permissions_asked", False))
            if asked:
                return

            # Give the permission prompts a visible parent. The regular chat
            # panel is hidden again afterward, leaving the companion floating.
            self.main_window.show_panel()

            from PySide6.QtWidgets import QMessageBox

            mic = QMessageBox.question(
                self.main_window,
                "Microphone permission",
                "Allow Gareeb to use your microphone for voice commands?\n\n"
                "The mic records only after you click it or press Ctrl+Shift+M. "
                "Toggle it again to stop and send; it never records in the background.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            ) == QMessageBox.Yes

            screen = QMessageBox.question(
                self.main_window,
                "Screen capture permission",
                "Allow Gareeb to capture and read your screen when you ask it to?\n\n"
                "Screenshots are only taken on your request and never "
                "continuously.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            ) == QMessageBox.Yes

            self.config_manager.set("audio", "microphone_allowed", mic)
            self.config_manager.set("audio", "screen_capture_allowed", screen)
            self.config_manager.save()

            self.audio_service.set_microphone_allowed(mic)
            self.screen_analyzer.set_screen_capture_permission(screen)

            if self.memory_store is not None:
                self.memory_store.set_preference("permissions_asked", True)
                self.memory_store.set_preference("microphone_allowed", mic)
                self.memory_store.set_preference("screen_capture_allowed", screen)

            note = "voice: {}, screen reading: {}".format(
                "on" if mic else "off", "on" if screen else "off")
            self.main_window.conversation.append_status(
                f"Permissions saved ({note}). You can change them in Settings.")
            self.main_window.hide()

        except Exception as exc:
            self.logger.warning(f"Permission prompt failed: {exc}")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def start(self) -> None:
        if self.audio_service is not None:
            self.audio_service.start()
        if self.ai_service is not None:
            self.ai_service.start()
        if self.automation_service is not None:
            self.automation_service.start()
        self.logger.info("Gareeb AI is ready")

    def shutdown(self) -> None:
        self.logger.info("Shutting down Gareeb AI…")
        try:
            if self.audio_service is not None:
                self.audio_service.cleanup()
            if self.ai_service is not None:
                self.ai_service.cleanup()
            if self.automation_service is not None:
                self.automation_service.cleanup()
            if self.screen_analyzer is not None:
                self.screen_analyzer.cleanup()
            if self.resource_monitor is not None:
                self.resource_monitor.stop_monitoring()
            if self.memory_store is not None:
                self.memory_store.close()
            if self.config_manager is not None:
                self.config_manager.save()
            self.logger.info("Gareeb AI shutdown complete")
        except Exception as exc:
            self.logger.error(f"Shutdown error: {exc}")
            traceback.print_exc()

    def run(self) -> int:
        try:
            if not self.initialize_services():
                return 1
            if not self.create_main_window():
                return 1

            self.start()
            exit_code = self.app.exec()

            # Persist window position/geometry when the window still exists.
            try:
                if self.main_window is not None:
                    ui = self.config_manager.get_ui_config()
                    ui.window_width = self.main_window.width()
                    ui.window_height = self.main_window.height()
                    ui.window_x = self.main_window.x()
                    ui.window_y = self.main_window.y()
                    self.config_manager.set_section("ui", vars(ui))
            except Exception:
                pass

            return exit_code

        except Exception as exc:
            self.logger.error(f"Application error: {exc}")
            traceback.print_exc()
            return 1
        finally:
            self.shutdown()


def main() -> int:
    application = MJAIApp()

    application.app.setApplicationName("Gareeb AI")
    application.app.setApplicationVersion("1.0.0")
    application.app.setOrganizationName("Gareeb AI")
    application.app.setQuitOnLastWindowClosed(False)

    # Splash screen (optional - never blocks startup).
    try:
        splash_path = project_root() / "assets" / "splash.png"
        if splash_path.exists():
            pixmap = QPixmap(str(splash_path))
            if not pixmap.isNull():
                application.splash_screen = QSplashScreen(pixmap)
                application.splash_screen.show()
                application.app.processEvents()
    except Exception:
        pass

    exit_code = application.run()

    if application.splash_screen is not None:
        application.splash_screen.close()

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
