"""Visual, animation-lifecycle, and assistant-state regression coverage."""

import os
import threading
import time
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, QThread, Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from ui.main_window import ConversationPanel, EyesWidget, MainWindow


STATES = (
    "idle", "listening", "thinking", "working", "speaking", "success",
    "error", "paused",
)
BACKGROUND = QColor("#614d43")
SNAPSHOT_DIR = Path(__file__).parent / "visual_regression"


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication(["mj-ai-animation-tests"])


class UiConfig:
    always_on_top = True
    window_opacity = 1.0
    companion_name = "MJ"
    animation_speed = 1.0
    companion_x = -1
    companion_y = -1
    window_width = 800
    window_height = 600
    window_x = 20
    window_y = 20


class Config:
    def get_ui_config(self):
        return UiConfig()

    def set_section(self, *_args):
        pass

    def save(self):
        pass


def render_state(face, state, *, dpr=1.0):
    face.set_animations_enabled(False)
    face.set_state(state)
    if state == "speaking":
        # A representative voiced frame for the static visual reference.
        face.set_speech_level(0.55)
    width, height = face.width(), face.height()
    pixmap = QPixmap(round(width * dpr), round(height * dpr))
    pixmap.setDevicePixelRatio(dpr)
    pixmap.fill(BACKGROUND)
    painter = QPainter(pixmap)
    face.render(painter, QPoint(0, 0))
    painter.end()
    return pixmap


def image_mean_channel_error(actual, expected):
    assert actual.size() == expected.size()
    total = samples = 0
    for y in range(0, actual.height(), 3):
        for x in range(0, actual.width(), 3):
            a, b = actual.pixelColor(x, y), expected.pixelColor(x, y)
            total += sum(abs(av - bv) for av, bv in zip(
                (a.red(), a.green(), a.blue(), a.alpha()),
                (b.red(), b.green(), b.blue(), b.alpha()),
            ))
            samples += 4
    return total / max(samples, 1)


def close_window(window, qapp):
    window._really_quit = True
    window.close()
    qapp.processEvents()


def test_state_visual_regression_matches_all_expression_snapshots(qapp, tmp_path):
    face = EyesWidget()
    face.resize(180, 166)
    face.set_animations_enabled(False)

    for state in STATES:
        actual_path = tmp_path / f"{state}.png"
        assert render_state(face, state).save(str(actual_path))
        expected_path = SNAPSHOT_DIR / f"{state}.png"
        assert expected_path.is_file(), f"Missing visual reference for {state}"
        from PySide6.QtGui import QImage

        actual, expected = QImage(str(actual_path)), QImage(str(expected_path))
        error = image_mean_channel_error(actual, expected)
        assert error < 0.75, f"{state} rendering changed (mean channel error {error:.2f})"


def test_face_animation_states_resize_hidpi_and_pause_expression(qapp):
    face = EyesWidget()
    face.set_animations_enabled(False)

    for state in STATES:
        face.set_state(state)
        assert face.state == state
        assert face._opening > 0.70 if state == "paused" else face._opening > 0.0

    face.set_state("not-a-state")
    assert face.state == "idle"

    for size in ((64, 64), (92, 92), (180, 166), (320, 280)):
        face.resize(*size)
        image = render_state(face, "listening", dpr=2.0)
        assert image.size().width() == size[0] * 2
        assert image.size().height() == size[1] * 2
        assert image.devicePixelRatio() == 2.0
        pixels = image.toImage()
        for x, y in ((0, 0), (image.width() - 1, 0),
                     (0, image.height() - 1),
                     (image.width() - 1, image.height() - 1)):
            assert pixels.pixelColor(x, y) == BACKGROUND


def test_idle_repaint_budget_and_timer_show_hide_enable_lifecycle(qapp):
    class CountingEyes(EyesWidget):
        def __init__(self):
            self.paint_count = 0
            super().__init__()

        def paintEvent(self, event):
            self.paint_count += 1
            super().paintEvent(event)

    face = CountingEyes()
    face.resize(180, 166)
    assert len(face.findChildren(type(face._timer))) == 1
    face.show()
    qapp.processEvents()
    assert face._timer.isActive()

    cpu_start, wall_start = time.process_time(), time.perf_counter()
    QTest.qWait(650)
    cpu_ratio = (time.process_time() - cpu_start) / (time.perf_counter() - wall_start)
    assert 10 <= face.paint_count <= 24
    assert cpu_ratio < 0.50

    face.hide()
    qapp.processEvents()
    hidden_count = face.paint_count
    QTest.qWait(180)
    assert not face._timer.isActive()
    assert face.paint_count == hidden_count

    face.set_animations_enabled(False)
    face.show()
    qapp.processEvents()
    QTest.qWait(100)
    assert not face._timer.isActive()
    face.set_state("speaking")
    assert face.state == "speaking"
    face.set_speech_level(0.8)
    assert face._speech_level == pytest.approx(0.8)
    face.set_animations_enabled(True)
    assert face._timer.isActive()

    face.set_state("paused")
    QTest.qWait(420)
    assert face._opening > 0.70
    assert not face._timer.isActive()
    face.close()


def test_conversation_progress_timer_is_owned_and_restarted(qapp):
    panel = ConversationPanel()
    panel.finish_task({"progress": 1.0, "summary": "Finished"})
    assert panel._progress_hide_timer.isActive()
    panel.show_task_progress({
        "description": "Second task", "status": "running", "progress": 0.2,
        "steps": [],
    })
    assert not panel._progress_hide_timer.isActive()
    assert not panel.progress_bar.isHidden()
    panel.close()


def test_task_voice_pause_and_ai_states_stay_synchronized(qapp):
    window = MainWindow(Config())
    eyes = window.companion.eyes

    window._on_ai_reply({"text": "Here is the answer", "error": False})
    assert eyes.state == "idle"  # A successful HTTP response is not task success.

    window._on_listening_started({})
    assert eyes.state == "listening"
    window._on_listening_stopped({})
    assert eyes.state == "working"  # Recording has ended; transcription is active.
    window._on_transcription_finished({})
    assert eyes.state == "idle"

    window._on_thinking_started({})
    assert eyes.state == "thinking"
    window._on_task_planned({"task": {
        "description": "Open an app", "status": "running", "progress": 0.0,
        "steps": [],
    }})
    assert eyes.state == "working"
    window._on_task_result({"task": {
        "status": "completed", "progress": 1.0, "summary": "App opened",
    }})
    assert eyes.state == "success"
    assert window._face_state_timer.isActive()
    window._on_ai_reply({"text": "The app is open.", "error": False})
    assert eyes.state == "success"  # The reply event cannot erase task completion.

    window._on_speech_started({"text": "The app is open."})
    assert eyes.state == "speaking"
    window._on_speech_progress({"level": 0.72})
    assert eyes._target_speech_level == pytest.approx(0.72)
    window._on_speech_finished({})
    assert eyes.state == "idle"

    window.companion.pause_button.click()
    assert eyes.state == "paused"
    assert eyes._opening > 0.70
    window.companion.pause_button.click()
    assert eyes.state == "idle"
    close_window(window, qapp)


def test_worker_events_update_widgets_only_on_qt_thread(qapp):
    window = MainWindow(Config())
    observed_threads = []
    original_handler = window._on_speech_started

    def record_thread(data):
        observed_threads.append(QThread.currentThread())
        original_handler(data)

    window._on_speech_started = record_thread
    worker = threading.Thread(
        target=lambda: window.post_event("voice", "speech_started", {"text": "hello"})
    )
    worker.start()
    worker.join(timeout=1.0)
    QTest.qWait(50)

    assert observed_threads == [window.thread()]
    assert window.companion.eyes.state == "speaking"
    close_window(window, qapp)


def test_floating_window_hide_restore_restarts_animation_timer(qapp):
    window = MainWindow(Config())
    floating = window.companion_window
    floating.show()
    qapp.processEvents()
    assert window.companion.eyes._timer.isActive()
    floating.hide()
    qapp.processEvents()
    assert not window.companion.eyes._timer.isActive()
    floating.show()
    qapp.processEvents()
    assert window.companion.eyes._timer.isActive()
    close_window(window, qapp)
