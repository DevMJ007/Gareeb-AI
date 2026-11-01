"""Headless regression checks for the redesigned MJ companion surfaces."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QPixmap
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from core.config_manager import ConfigManager
from ui.main_window import (
    CompanionWidget, ConversationPanel, EyesWidget, FloatingCompanionWindow,
    SettingsDialog,
)


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication(["mj-ai-ui-tests"])


def test_glass_orb_paints_every_expression(qapp):
    face = EyesWidget()
    face.resize(180, 166)
    face.set_animations_enabled(False)

    for state in ("idle", "listening", "thinking", "speaking", "success", "error"):
        face.set_state(state)
        face.set_animations_enabled(False)
        image = QPixmap(face.size())
        image.fill()
        face.render(image)
        assert not image.isNull()
        assert face.state == state


def test_floating_companion_stays_minimal_and_shows_real_controls(qapp):
    companion = CompanionWidget()
    assert companion.status_label.text() == "I’m here ♥"
    assert not companion.controls.isHidden()
    assert companion.controls_effect.opacity() == 0.0
    assert companion.controls.testAttribute(Qt.WA_TransparentForMouseEvents)

    companion.set_state("listening")
    assert companion.status_label.text() == "Listening…"
    companion.set_work_message("Transcribing…")
    assert companion.status_label.text() == "Transcribing…"

    reserved_row = companion.controls.geometry()
    companion.set_controls_visible(True)
    assert not companion.controls.isHidden()
    assert companion.controls_effect.opacity() == 1.0
    assert not companion.controls.testAttribute(Qt.WA_TransparentForMouseEvents)
    assert companion.controls.geometry() == reserved_row
    assert companion.mic_button.toolTip()
    assert companion.settings_button.toolTip()
    pressed, released = [], []
    companion.mic_pressed.connect(lambda: pressed.append(True))
    companion.mic_released.connect(lambda: released.append(True))
    QTest.mousePress(companion.mic_button, Qt.LeftButton)
    QTest.mouseRelease(companion.mic_button, Qt.LeftButton)
    assert pressed == [True]
    assert released == [True]
    companion.set_controls_visible(False)
    assert companion.controls_effect.opacity() == 0.0
    assert companion.controls.geometry() == reserved_row


def test_hover_does_not_resize_or_move_floating_window(qapp):
    class UiConfig:
        always_on_top = True
        window_opacity = 1.0
        companion_name = "MJ"
        animation_speed = 1.0
        companion_x = -1
        companion_y = -1

    class Config:
        def get_ui_config(self):
            return UiConfig()

        def set_section(self, *_args):
            pass

    companion = CompanionWidget()
    window = FloatingCompanionWindow(companion, Config(), lambda: None)
    qapp.processEvents()
    original = window.geometry()

    window.enterEvent(None)
    qapp.processEvents()
    assert window.geometry() == original
    assert companion.controls_effect.opacity() == 1.0

    window.leaveEvent(None)
    qapp.processEvents()
    assert window.geometry() == original
    window.close()


def test_reference_panel_keeps_actions_chat_and_window_controls(qapp):
    panel = ConversationPanel()
    assert set(panel.action_cards) == {
        "open_app", "analyze_screen", "create_notes", "do_tasks"
    }
    assert panel.transcript.isHidden()
    assert panel.input_edit.placeholderText() == "Ask MJ anything…"
    assert panel.send_button.width() == 48

    submitted = []
    panel.message_submitted.connect(submitted.append)
    panel.message_submitted.connect(panel.append_user)
    panel.input_edit.setText("Open Notepad")
    panel._submit()
    assert submitted == ["Open Notepad"]
    assert panel.input_edit.text() == ""
    assert not panel.transcript.isHidden()

    maximized = []
    panel.maximize_requested.connect(lambda: maximized.append(True))
    panel.maximize_button.click()
    assert maximized == [True]


def test_voice_settings_save_selected_speech_language(qapp, tmp_path):
    config = ConfigManager(config_file=str(tmp_path / "mjai-config.json"))
    dialog = SettingsDialog(config)

    assert dialog.speech_language.currentData() == "en"
    dialog.speech_language.setCurrentIndex(
        dialog.speech_language.findData("hi"))
    dialog._save()

    assert config.get_audio_config().language == "hi"
    dialog.close()
