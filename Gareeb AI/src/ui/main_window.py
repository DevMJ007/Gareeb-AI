#!/usr/bin/env python3
"""
Main window for MJ AI (FR-01, FR-09, section 9).

Contains the animated companion, conversation panel, settings dialog, system
tray, and the thread-safe bridge between worker-thread events and the UI.
"""

from __future__ import annotations

import math
import html
import queue
import random
import threading
import time
import logging
from typing import Optional, Dict, Any

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QTextEdit, QFrame, QSplitter, QGroupBox,
    QDialog, QFileDialog, QMessageBox, QInputDialog, QSlider, QComboBox, QLineEdit,
    QTabWidget, QCheckBox, QSpinBox, QListWidget, QListWidgetItem,
    QSystemTrayIcon, QMenu, QStyle, QScrollArea, QSizePolicy,
    QProgressBar, QDoubleSpinBox, QSizeGrip, QGraphicsOpacityEffect,
)
from PySide6.QtCore import (
    Qt, QTimer, QEvent, QRect, QRectF, QPoint, QPointF, QSize, Signal, Slot,
    QPropertyAnimation, QEasingCurve,
)
from PySide6.QtGui import (
    QGuiApplication, QFont, QColor, QPainter, QPen, QBrush,
    QLinearGradient, QRadialGradient, QPainterPath,
    QShortcut, QKeySequence, QIcon, QPixmap, QAction,
)

logger = logging.getLogger(__name__)


# ======================================================================
# Animated eyes
# ======================================================================
class EyesWidget(QWidget):
    """Warm, abstract companion face rendered with lightweight Qt vectors."""

    _STATE_STYLE = {
        "idle": (QPointF(0.0, 0.0), 1.0, QColor(221, 151, 106)),
        "listening": (QPointF(0.0, -0.03), 0.96, QColor(239, 139, 76)),
        "thinking": (QPointF(0.13, -0.15), 0.84, QColor(221, 164, 82)),
        "speaking": (QPointF(0.0, 0.0), 0.95, QColor(226, 139, 112)),
        "success": (QPointF(0.0, -0.02), 0.9, QColor(139, 169, 128)),
        "error": (QPointF(0.0, 0.08), 0.84, QColor(205, 117, 91)),
        "paused": (QPointF(0.0, 0.0), 0.08, QColor(173, 145, 129)),
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        # The face is shared by the desktop orb and the small greeting avatar.
        self.setMinimumSize(1, 1)
        self.setMaximumHeight(168)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.state = "idle"
        self._animations_enabled = True
        self._opening = 1.0
        self._target_opening = 1.0
        self._blink_opening = 1.0
        self._blink_started: Optional[float] = None
        self._next_blink = time.monotonic() + random.uniform(2.5, 5.0)
        self._gaze = QPointF(0.0, 0.0)
        self._gaze_target = QPointF(0.0, 0.0)
        self._accent = QColor(203, 151, 125)
        self._target_accent = QColor(self._accent)
        self._phase = 0.0
        self._last_tick = time.monotonic()
        self._next_glance = self._last_tick + random.uniform(2.0, 4.5)
        self._breath = 0.0
        self._float_offset = 0.0

        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._tick)
        self.setAutoFillBackground(False)

    def set_state(self, state: str) -> None:
        state = state if state in self._STATE_STYLE else "idle"
        if state == self.state:
            return
        self.state = state
        gaze, opening, accent = self._STATE_STYLE[state]
        self._gaze_target = QPointF(gaze)
        self._target_opening = opening
        self._target_accent = QColor(accent)
        if state == "paused":
            self._blink_started = None
            self._blink_opening = 1.0
        self._last_tick = time.monotonic()
        self._next_glance = self._last_tick + random.uniform(1.8, 4.0)
        if not self._animations_enabled:
            self._opening = opening
            self._gaze = QPointF(gaze)
            self._accent = QColor(accent)
        elif self.isVisible():
            self._timer.setInterval(33 if state != "idle" else 50)
            self._timer.start()
        self.update()

    def set_animations_enabled(self, enabled: bool) -> None:
        self._animations_enabled = bool(enabled)
        if not self._animations_enabled:
            self._timer.stop()
            self._opening = self._target_opening
            self._blink_opening = 1.0
            self._gaze = QPointF(self._gaze_target)
            self._accent = QColor(self._target_accent)
            self._breath = 0.0
            self.update()
        elif self.isVisible() and self.state != "paused":
            self._last_tick = time.monotonic()
            self._timer.setInterval(33 if self.state != "idle" else 50)
            self._timer.start()

    def _tick(self) -> None:
        if not self.isVisible() or not self._animations_enabled:
            self._timer.stop()
            return

        now = time.monotonic()
        dt = min(max(now - self._last_tick, 0.0), 0.12)
        self._last_tick = now
        blend = 1.0 - math.exp(-10.0 * dt)

        if self.state != "paused":
            if self._blink_started is None and now >= self._next_blink:
                self._blink_started = now
            if self._blink_started is not None:
                progress = (now - self._blink_started) / 0.23
                if progress >= 1.0:
                    self._blink_opening = 1.0
                    self._blink_started = None
                    self._next_blink = now + random.uniform(2.7, 5.4)
                elif progress < 0.46:
                    t = progress / 0.46
                    self._blink_opening = 1.0 - (t * t * (3.0 - 2.0 * t))
                else:
                    t = (progress - 0.46) / 0.54
                    self._blink_opening = t * t * (3.0 - 2.0 * t)

        if self.state == "idle" and now >= self._next_glance:
            self._gaze_target = QPointF(
                random.uniform(-0.12, 0.12), random.uniform(-0.10, 0.08))
            self._next_glance = now + random.uniform(2.0, 5.0)

        self._opening += (self._target_opening - self._opening) * blend
        self._gaze += (self._gaze_target - self._gaze) * blend
        self._accent = self._mix_color(self._accent, self._target_accent, blend)
        self._phase += dt
        self._breath = math.sin(now * 0.75) * (0.008 if self.state == "idle" else 0.002)
        self._float_offset = math.sin(now * 0.9) * (2.0 if self.state == "idle" else 0.65)
        self.update()

        settled = (
            abs(self._opening - self._target_opening) < 0.01
            and abs(self._gaze.x() - self._gaze_target.x()) < 0.01
            and abs(self._gaze.y() - self._gaze_target.y()) < 0.01
        )
        if self.state == "paused" and settled:
            self._timer.stop()
        elif self.state == "idle":
            self._timer.setInterval(50)

    @staticmethod
    def _mix_color(start: QColor, end: QColor, amount: float) -> QColor:
        return QColor(
            round(start.red() + (end.red() - start.red()) * amount),
            round(start.green() + (end.green() - start.green()) * amount),
            round(start.blue() + (end.blue() - start.blue()) * amount),
            round(start.alpha() + (end.alpha() - start.alpha()) * amount),
        )

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        scale = min(self.width() / 176.0, self.height() / 160.0)
        painter.translate(self.width() / 2.0, self.height() / 2.0 + self._float_offset)
        painter.scale(scale * (1.0 + self._breath), scale * (1.0 - self._breath * 0.35))

        head = QPainterPath()
        head.addEllipse(QRectF(-68.0, -68.0, 136.0, 136.0))

        # Soft amber light gives the glassy orb a warm edge without a neon halo.
        halo = QRadialGradient(QPointF(0, 3), 106)
        halo_color = QColor(self._accent)
        halo_color.setAlpha(74 if self.state == "listening" else 48)
        clear_halo = QColor(halo_color)
        clear_halo.setAlpha(0)
        halo.setColorAt(0.0, halo_color)
        halo.setColorAt(1.0, clear_halo)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(halo))
        painter.drawEllipse(QRectF(-90, -90, 180, 180))

        if self.state == "listening":
            pulse = 1.0 + math.sin(self._phase * 2.0) * 0.012
            ring = QColor(self._accent)
            ring.setAlpha(108)
            painter.save()
            painter.scale(pulse, pulse)
            painter.setPen(QPen(ring, 1.8))
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(head)
            painter.restore()

        # A soft cast shadow separates the orb from transparent desktop pixels.
        painter.save()
        painter.translate(0, 5)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(116, 74, 48, 42))
        painter.drawEllipse(QRectF(-64, -64, 128, 128))
        painter.restore()

        face_gradient = QRadialGradient(QPointF(-34, -42), 142, QPointF(-39, -48))
        face_gradient.setColorAt(0.0, QColor(255, 255, 252))
        face_gradient.setColorAt(0.42, QColor(255, 246, 231))
        face_gradient.setColorAt(0.72, QColor(255, 222, 190))
        face_gradient.setColorAt(0.92, QColor(255, 192, 143))
        face_gradient.setColorAt(1.0, QColor(238, 157, 103))
        painter.fillPath(head, QBrush(face_gradient))

        # Cool and rose reflections add the iridescent glass edge from the
        # reference while keeping the sphere as lightweight vector artwork.
        painter.save()
        painter.setClipPath(head)
        for center, radius, color, alpha in (
            (QPointF(-59, -25), 42, QColor(122, 207, 255), 74),
            (QPointF(58, -24), 37, QColor(255, 163, 208), 62),
            (QPointF(0, 67), 52, QColor(255, 207, 111), 72),
        ):
            tint = QRadialGradient(center, radius)
            tint_color = QColor(color)
            tint_color.setAlpha(alpha)
            clear_tint = QColor(color)
            clear_tint.setAlpha(0)
            tint.setColorAt(0.0, tint_color)
            tint.setColorAt(1.0, clear_tint)
            painter.setBrush(QBrush(tint))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(QRectF(center.x() - radius, center.y() - radius,
                                       radius * 2, radius * 2))

        # Broad specular highlight and catchlights make the orb read as glass.
        sheen = QRadialGradient(QPointF(-38, -49), 72)
        sheen.setColorAt(0.0, QColor(255, 255, 255, 216))
        sheen.setColorAt(0.56, QColor(255, 255, 255, 86))
        sheen.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.setBrush(QBrush(sheen))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(QRectF(-76, -82, 114, 88))
        painter.setBrush(QColor(255, 255, 255, 206))
        painter.drawEllipse(QRectF(-55, -61, 31, 12))
        painter.setBrush(QColor(255, 255, 255, 145))
        painter.drawEllipse(QRectF(45, -58, 20, 7))
        painter.restore()
        painter.strokePath(head, QPen(QColor(255, 255, 255, 204), 2.3))
        painter.strokePath(head, QPen(QColor(193, 118, 76, 64), 1.0))

        opening = max(0.035, self._opening * self._blink_opening)
        eye_w, eye_h = 25.5, 31.0
        eye_y = -5.0
        for side in (-1, 1):
            ex = side * 25.0
            ey = eye_y + self._gaze.y() * 17.0
            open_h = max(2.6, eye_h * opening)
            eye = QRectF(ex - eye_w / 2, ey - open_h / 2, eye_w, open_h)
            if open_h < 5.0:
                line_pen = QPen(QColor(106, 70, 57, 205), 2.4)
                line_pen.setCapStyle(Qt.RoundCap)
                painter.setPen(line_pen)
                painter.drawLine(QPointF(ex - 15, ey), QPointF(ex + 15, ey))
                continue

            socket = eye.adjusted(-2.3, -2.3, 2.3, 2.3)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(195, 130, 94, 48))
            painter.drawEllipse(socket)

            eye_gradient = QLinearGradient(eye.topLeft(), eye.bottomRight())
            eye_gradient.setColorAt(0.0, QColor(255, 255, 252))
            eye_gradient.setColorAt(1.0, QColor(249, 235, 221))
            painter.setBrush(QBrush(eye_gradient))
            painter.drawEllipse(eye)

            pupil_w, pupil_h = 13.0, min(17.0, max(6.0, open_h * 0.58))
            px = ex + self._gaze.x() * 7.0
            py = ey + (1.5 if self.state == "listening" else 0.0)
            px = max(eye.left() + pupil_w / 2 + 3, min(eye.right() - pupil_w / 2 - 3, px))
            py = max(eye.top() + pupil_h / 2 + 2, min(eye.bottom() - pupil_h / 2 - 2, py))
            pupil = QRectF(px - pupil_w / 2, py - pupil_h / 2, pupil_w, pupil_h)
            pupil_gradient = QLinearGradient(pupil.topLeft(), pupil.bottomRight())
            pupil_gradient.setColorAt(0.0, QColor(87, 59, 51))
            pupil_gradient.setColorAt(1.0, QColor(43, 34, 34))
            painter.setBrush(QBrush(pupil_gradient))
            painter.drawEllipse(pupil)
            painter.setBrush(QColor(255, 255, 255, 240))
            painter.drawEllipse(QPointF(px - 2.0, py - 2.8), 2.0, 2.0)
            painter.setBrush(QColor(255, 255, 255, 145))
            painter.drawEllipse(QPointF(px + 2.0, py + 2.7), 0.9, 0.9)

        # Soft brows add a little character to the thinking and error expressions.
        brow_pen = QPen(QColor(151, 96, 68, 165), 2.0 if self.state != "idle" else 1.5)
        brow_pen.setCapStyle(Qt.RoundCap)
        for side in (-1, 1):
            ex = side * 25.0
            brow_y = -29.0
            lift = 2.8 if self.state == "thinking" and side == 1 else 0.0
            if self.state == "error":
                lift = -2.2 if side == -1 else 2.2
            brow = QPainterPath(QPointF(ex - 8.5, brow_y + lift))
            brow.cubicTo(ex - 4.0, brow_y - 2.4 + lift, ex + 4.0, brow_y - 2.4 - lift,
                         ex + 8.5, brow_y - lift)
            painter.setPen(brow_pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(brow)

        mouth_y = 35.0
        mouth_color = QColor(128, 77, 59, 205)
        if self.state == "speaking":
            # Playback events switch this state; the small motion stays deliberately subtle.
            open_amount = 2.0 + (1.0 + math.sin(self._phase * 7.0)) * 1.6
            painter.setPen(Qt.NoPen)
            painter.setBrush(mouth_color)
            painter.drawEllipse(QRectF(-4.5, mouth_y - open_amount / 2, 9.0, open_amount))
        else:
            curve = 5.5
            if self.state == "success":
                curve = 8.0
            elif self.state == "error":
                curve = -4.0
            elif self.state == "paused":
                curve = 0.0
            mouth = QPainterPath(QPointF(-11, mouth_y))
            mouth.cubicTo(-5, mouth_y + curve, 5, mouth_y + curve, 11, mouth_y)
            mouth_pen = QPen(mouth_color, 2.1)
            mouth_pen.setCapStyle(Qt.RoundCap)
            painter.setPen(mouth_pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(mouth)

        if self.state == "paused":
            painter.fillPath(head, QColor(87, 73, 68, 34))
        painter.end()


    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._animations_enabled and self.state != "paused":
            self._last_tick = time.monotonic()
            self._timer.setInterval(33 if self.state != "idle" else 50)
            self._timer.start()

    def hideEvent(self, event) -> None:
        self._timer.stop()
        super().hideEvent(event)

    def mousePressEvent(self, event) -> None:
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        event.accept()


# ======================================================================
# Companion widget
# ======================================================================
class CompanionWidget(QFrame):
    """Glowing desktop orb with a compact, hover-revealed control strip."""

    mic_pressed = Signal()
    mic_released = Signal()
    pause_toggled = Signal()
    settings_requested = Signal()
    hide_requested = Signal()
    state_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("companion")
        self.setFrameShape(QFrame.NoFrame)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setStyleSheet("QFrame#companion { background: transparent; border: 0; }")
        self._paused = False

        self._state = "idle"
        self._work_message = ""
        self.name_label = QLabel("MJ", self)
        self.name_label.hide()  # Kept for settings and accessibility.
        self.mic_badge = QLabel("○ MIC OFF", self)
        self.mic_badge.hide()
        self.work_badge = QLabel("", self)
        self.work_badge.hide()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 3, 4, 3)
        layout.setSpacing(0)

        # A speech chip replaces the large status header from the old widget.
        self.bubble = QFrame(self)
        self.bubble.setObjectName("companionBubble")
        self.bubble.setStyleSheet("""
            QFrame#companionBubble {
                background:rgba(255, 250, 255, 245);
                border:1px solid rgba(255,255,255,235);
                border-radius:18px;
            }
        """)
        bubble_layout = QHBoxLayout(self.bubble)
        bubble_layout.setContentsMargins(13, 7, 13, 7)
        self.status_label = QLabel("I’m here ♥", self.bubble)
        self.status_label.setObjectName("companionStatus")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet(
            "color:#44332e; font:10pt 'Segoe UI'; background:transparent; border:0;"
        )
        bubble_layout.addWidget(self.status_label)
        layout.addWidget(self.bubble, alignment=Qt.AlignHCenter)

        self.eyes = EyesWidget(self)
        self.eyes.setFixedSize(180, 166)
        self.eyes.setCursor(Qt.OpenHandCursor)
        layout.addWidget(self.eyes, alignment=Qt.AlignHCenter)

        # Keep the control row in the layout while it is transparent. Hiding
        # it collapsed the layout, resized the top-level window on hover, and
        # made the pointer fall outside the window before it could reach the mic.
        self.controls = QFrame(self)
        self.controls.setObjectName("companionControls")
        self.controls.setStyleSheet(
            "QFrame#companionControls { background:transparent; border:0; }"
        )
        control_row = QHBoxLayout(self.controls)
        control_row.setContentsMargins(0, 2, 0, 2)
        control_row.setSpacing(7)

        self.pause_button = QPushButton("Ⅱ", self.controls)
        self.pause_button.setFixedSize(31, 31)
        self.pause_button.setToolTip("Pause / resume MJ")
        self.pause_button.setStyleSheet(self._button_style(31))
        self.mic_button = QPushButton("🎙", self.controls)
        self.mic_button.setFixedSize(38, 38)
        self.mic_button.setToolTip("Hold to talk (or press Ctrl+Shift+M)")
        self.mic_button.setStyleSheet(self._button_style(38, "18px"))
        self.settings_button = QPushButton("⚙", self.controls)
        self.settings_button.setFixedSize(31, 31)
        self.settings_button.setToolTip("Settings (Ctrl+,)")
        self.settings_button.setStyleSheet(self._button_style(31))
        self.hide_button = QPushButton("×", self.controls)
        self.hide_button.setFixedSize(31, 31)
        self.hide_button.setToolTip("Hide companion (restore from the system tray)")
        self.hide_button.setStyleSheet(self._button_style(31))

        self.mic_button.pressed.connect(self._on_mic_pressed)
        self.mic_button.released.connect(self._on_mic_released)
        self.pause_button.clicked.connect(self._on_pause)
        self.settings_button.clicked.connect(self.settings_requested)
        self.hide_button.clicked.connect(self.hide_requested)
        control_row.addStretch(1)
        control_row.addWidget(self.pause_button)
        control_row.addWidget(self.mic_button)
        control_row.addWidget(self.settings_button)
        control_row.addWidget(self.hide_button)
        control_row.addStretch(1)
        self.controls_effect = QGraphicsOpacityEffect(self.controls)
        self.controls_effect.setOpacity(0.0)
        self.controls.setGraphicsEffect(self.controls_effect)
        self.controls.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        layout.addWidget(self.controls, alignment=Qt.AlignHCenter)

        self.setAccessibleName("MJ AI floating companion")
        self.set_state("idle")

    @staticmethod
    def _button_style(size: int, font_size: str = "14px") -> str:
        radius = size // 2
        return f"""
            QPushButton {{ background:rgba(255,249,243,220); border-radius:{radius}px;
                font-size:{font_size}; color:#72574f; border:1px solid rgba(174,139,122,90); }}
            QPushButton:hover {{ background:rgba(255,255,250,245); border-color:#bd9a88; }}
            QPushButton:pressed {{ background:rgba(234,211,196,245); }}
        """

    # ------------------------------------------------------------------
    def _on_mic_pressed(self) -> None:
        self.mic_pressed.emit()

    def _on_mic_released(self) -> None:
        self.mic_released.emit()

    def _on_pause(self) -> None:
        self._paused = not self._paused
        self.pause_button.setText("▶" if self._paused else "⏸")
        self.pause_toggled.emit()

    # ------------------------------------------------------------------
    @property
    def paused(self) -> bool:
        return self._paused

    def set_controls_visible(self, visible: bool) -> None:
        visible = bool(visible)
        self.controls_effect.setOpacity(1.0 if visible else 0.0)
        self.controls.setAttribute(Qt.WA_TransparentForMouseEvents, not visible)

    def set_state(self, state: str) -> None:
        if self._paused and state not in ("paused",):
            state = "paused"
        self._state = state
        self.eyes.set_state(state)
        self.state_changed.emit(state)
        labels = {
            "idle": "I’m here ♥", "listening": "Listening…",
            "thinking": "One moment…", "speaking": "I’m speaking…",
            "success": "All done ✨", "error": "Need a hand?",
            "paused": "Paused",
        }
        self.status_label.setText(self._work_message or labels.get(state, state))
        if state == "listening":
            self.mic_badge.setText("● MIC LIVE")
        else:
            self.mic_badge.setText("○ MIC OFF")

    def set_work_message(self, message: str) -> None:
        self._work_message = (message or "").strip()
        self.work_badge.setText(message)
        labels = {
            "idle": "I’m here ♥", "listening": "Listening…",
            "thinking": "One moment…", "speaking": "I’m speaking…",
            "success": "All done ✨", "error": "Need a hand?",
            "paused": "Paused",
        }
        self.status_label.setText(self._work_message or labels.get(self._state, self._state))

    def set_name(self, name: str) -> None:
        self.name_label.setText(name or "MJ")
        self.setAccessibleDescription(f"{self.name_label.text()} desktop companion")

    def set_listening_active(self, active: bool) -> None:
        self.set_state("listening" if active else "idle")

    def set_animations_enabled(self, enabled: bool) -> None:
        self.eyes.set_animations_enabled(enabled)


class FloatingCompanionWindow(QWidget):
    """Frameless, transparent desktop shell for the shared companion widget."""

    def __init__(self, companion: CompanionWidget, config_manager,
                 show_panel_callback, parent=None):
        super().__init__(parent, Qt.Tool | Qt.FramelessWindowHint)
        self.setObjectName("mjFloatingCompanion")
        self.setWindowTitle("MJ AI Companion")
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAutoFillBackground(False)
        self.setStyleSheet("QWidget#mjFloatingCompanion { background:transparent; }")
        self.config_manager = config_manager
        self.show_panel_callback = show_panel_callback
        self.companion = companion
        self._drag_anchor: Optional[QPoint] = None
        self._press_global: Optional[QPoint] = None
        self._pressed_on_face = False
        self._drag_moved = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 4, 5, 4)
        layout.addWidget(self.companion)
        self.setMinimumSize(196, 198)
        self.setMaximumSize(300, 300)
        # Measure once with the reserved controls row present. Hovering only
        # changes its opacity, so this window's hit area never shifts.
        self.adjustSize()

        self.companion.hide_requested.connect(self.hide)
        self._install_drag_filters(self.companion)

        for screen in QGuiApplication.screens():
            screen.geometryChanged.connect(self._ensure_on_screen)
        app = QGuiApplication.instance()
        if app is not None:
            app.screenAdded.connect(self._on_screen_added)
            app.screenRemoved.connect(self._ensure_on_screen)

        self.apply_config(self.config_manager.get_ui_config())
        self._restore_position()

    def _install_drag_filters(self, widget: QWidget) -> None:
        widget.installEventFilter(self)
        for child in widget.findChildren(QWidget):
            if not isinstance(child, QPushButton):
                child.installEventFilter(self)

    @staticmethod
    def _is_descendant(widget, ancestor: QWidget) -> bool:
        current = widget
        while current is not None:
            if current is ancestor:
                return True
            current = current.parentWidget() if hasattr(current, "parentWidget") else None
        return False

    def eventFilter(self, watched, event) -> bool:
        if isinstance(watched, QPushButton):
            return super().eventFilter(watched, event)

        if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            self._press_global = event.globalPosition().toPoint()
            self._drag_anchor = self._press_global - self.frameGeometry().topLeft()
            self._pressed_on_face = self._is_descendant(watched, self.companion.eyes)
            self._drag_moved = False
            if self._pressed_on_face:
                self.companion.eyes.setCursor(Qt.ClosedHandCursor)

        elif (event.type() == QEvent.MouseMove and self._drag_anchor is not None
              and event.buttons() & Qt.LeftButton):
            global_pos = event.globalPosition().toPoint()
            if (not self._drag_moved and self._press_global is not None
                    and (global_pos - self._press_global).manhattanLength()
                    >= QApplication.startDragDistance()):
                self._drag_moved = True
            if self._drag_moved:
                self.move(global_pos - self._drag_anchor)

        elif event.type() == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
            was_dragged = self._drag_moved
            open_panel = self._pressed_on_face and not was_dragged
            self._drag_anchor = None
            self._press_global = None
            self._pressed_on_face = False
            self._drag_moved = False
            self.companion.eyes.setCursor(Qt.OpenHandCursor)
            if was_dragged:
                self._ensure_on_screen()
                self._save_position()
            elif open_panel:
                self.show_panel_callback()

        return super().eventFilter(watched, event)

    def _restore_position(self) -> None:
        ui = self.config_manager.get_ui_config()
        if ui.companion_x != -1 or ui.companion_y != -1:
            self.move(ui.companion_x, ui.companion_y)
        else:
            screen = QGuiApplication.primaryScreen()
            if screen is not None:
                area = screen.availableGeometry()
                self.move(area.right() - self.width() - 24, area.top() + 72)
        self._ensure_on_screen()

    def _on_screen_added(self, screen) -> None:
        screen.geometryChanged.connect(self._ensure_on_screen)
        self._ensure_on_screen()

    def _ensure_on_screen(self, *args) -> None:
        screens = QGuiApplication.screens()
        if not screens:
            return
        current = self.frameGeometry()
        screen = QGuiApplication.screenAt(current.center())
        if screen is None:
            screen = QGuiApplication.primaryScreen() or screens[0]
        area = screen.availableGeometry()
        x = max(area.left(), min(self.x(), area.right() - self.width() + 1))
        y = max(area.top(), min(self.y(), area.bottom() - self.height() + 1))
        if (x, y) != (self.x(), self.y()):
            self.move(x, y)

    def _save_position(self) -> None:
        try:
            ui = self.config_manager.get_ui_config()
            ui.companion_x = self.x()
            ui.companion_y = self.y()
            self.config_manager.set_section("ui", vars(ui))
        except Exception as exc:
            logger.warning(f"Could not save companion position: {exc}")

    def apply_config(self, ui_config) -> None:
        was_visible = self.isVisible()
        self.setWindowFlag(Qt.WindowStaysOnTopHint, bool(ui_config.always_on_top))
        self.setWindowOpacity(ui_config.window_opacity)
        self.companion.set_name(ui_config.companion_name)
        self.companion.set_animations_enabled(ui_config.animation_speed > 0)
        if was_visible:
            self.show()
            self.raise_()

    def toggle_visible(self) -> None:
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self.raise_()

    def enterEvent(self, event) -> None:
        self.companion.set_controls_visible(True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.companion.set_controls_visible(False)
        super().leaveEvent(event)

    def closeEvent(self, event) -> None:
        self._save_position()
        super().closeEvent(event)


# ======================================================================
# Conversation panel
# ======================================================================
class ActionCard(QPushButton):
    """Compact, keyboard-accessible shortcut card for a real MJ workflow."""

    def __init__(self, icon: str, title: str, description: str, parent=None):
        super().__init__(parent)
        self.setObjectName("actionCard")
        self.setMinimumHeight(76)
        self.setCursor(Qt.PointingHandCursor)
        self.setAccessibleName(title)
        self.setAccessibleDescription(description)
        self.setStyleSheet("""
            QPushButton#actionCard {
                background: rgba(255, 253, 249, 245);
                border: 1px solid #f0e2d6;
                border-radius: 17px;
                text-align: left;
            }
            QPushButton#actionCard:hover {
                background: #fffaf4;
                border: 1px solid #e7b28d;
            }
            QPushButton#actionCard:pressed {
                background: #ffefdf;
                border: 1px solid #d98d5a;
            }
        """)

        row = QHBoxLayout(self)
        row.setContentsMargins(14, 10, 14, 10)
        row.setSpacing(12)

        badge = QLabel(icon)
        badge.setFixedSize(42, 42)
        badge.setAlignment(Qt.AlignCenter)
        badge.setStyleSheet(
            "background:#ffead9; color:#c76d3a; border-radius:14px; "
            "font: bold 20px 'Segoe UI Emoji';"
        )
        row.addWidget(badge)

        copy = QVBoxLayout()
        copy.setSpacing(2)
        heading = QLabel(title)
        heading.setStyleSheet("color:#3d302a; font:600 10pt 'Segoe UI';")
        detail = QLabel(description)
        detail.setWordWrap(True)
        detail.setStyleSheet("color:#88776c; font:9pt 'Segoe UI';")
        copy.addWidget(heading)
        copy.addWidget(detail)
        row.addLayout(copy, 1)

        # Keep the cards visually quiet; the title and supporting line are the cue.


class WindowTitleBar(QWidget):
    """Drag region for the frameless assistant window."""

    double_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._drag_offset: Optional[QPoint] = None

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            window = self.window()
            if not window.isMaximized():
                self._drag_offset = (
                    event.globalPosition().toPoint() - window.frameGeometry().topLeft())
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_offset is not None and event.buttons() & Qt.LeftButton:
            self.window().move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.double_clicked.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class ConversationPanel(QWidget):
    """Chat-style transcript with task progress, cancel and confirmations."""

    message_submitted = Signal(str)
    cancel_requested = Signal()
    action_requested = Signal(str)
    microphone_pressed = Signal()
    microphone_released = Signal()
    settings_requested = Signal()
    minimize_requested = Signal()
    maximize_requested = Signal()
    close_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("assistantPanel")
        self.setStyleSheet("""
            QWidget#assistantPanel {
                background:#fff9f2; color:#3d302a;
                border:1px solid #f0dccc; border-radius:22px;
            }
            QLineEdit, QTextEdit {
                background:#fffdfa; border:1px solid #ecded2;
                border-radius:23px; padding:10px 15px; color:#44372f;
                selection-background-color:#e59a68;
            }
            QLineEdit:focus, QTextEdit:focus { border:1px solid #d98d5a; }
            QProgressBar {
                background:#f4e7dc; border:0; border-radius:5px;
                height:9px; text-align:center; color:#6b4c3c;
            }
            QProgressBar::chunk { background:#df9665; border-radius:5px; }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 13, 22, 15)
        layout.setSpacing(12)

        # Custom titlebar mirrors the reference and replaces native window chrome.
        self.titlebar = WindowTitleBar(self)
        header = QHBoxLayout(self.titlebar)
        header.setContentsMargins(2, 0, 0, 0)
        header.setSpacing(10)
        logo = QLabel("●")
        logo.setFixedSize(22, 22)
        logo.setAlignment(Qt.AlignCenter)
        logo.setStyleSheet("color:#ff963f; font:16pt 'Segoe UI'; background:transparent; border:0;")
        header.addWidget(logo)
        name = QLabel("MJ AI")
        name.setStyleSheet("color:#3c2d26; font:600 13pt 'Segoe UI'; background:transparent; border:0;")
        header.addWidget(name)
        header.addStretch(1)

        self.minimize_button = self._window_button("−", "Minimize assistant")
        self.maximize_button = self._window_button("□", "Maximize or restore assistant")
        self.settings_button = self._window_button("⚙", "Open settings")
        self.close_button = self._window_button("×", "Hide assistant to tray")
        self.minimize_button.clicked.connect(self.minimize_requested)
        self.maximize_button.clicked.connect(self.maximize_requested)
        self.settings_button.clicked.connect(self.settings_requested)
        self.close_button.clicked.connect(self.close_requested)
        self.titlebar.double_clicked.connect(self.maximize_requested)
        header.addWidget(self.minimize_button)
        header.addWidget(self.maximize_button)
        header.addWidget(self.settings_button)
        header.addWidget(self.close_button)
        layout.addWidget(self.titlebar)

        # Greeting bubble and a small instance of the shared event-driven orb.
        welcome = QFrame()
        welcome.setObjectName("welcomeHero")
        welcome.setStyleSheet("""
            QFrame#welcomeHero { background:transparent; border:0; }
            QFrame#welcomeBubble {
                background:rgba(255,255,255,220);
                border:1px solid #f5e4d7; border-radius:20px;
            }
        """)
        hero = QHBoxLayout(welcome)
        hero.setContentsMargins(0, 2, 0, 2)
        hero.setSpacing(8)

        self.welcome_eyes = EyesWidget()
        self.welcome_eyes.setFixedSize(92, 92)
        self.welcome_eyes.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        hero.addWidget(self.welcome_eyes, 0, Qt.AlignLeft | Qt.AlignVCenter)

        bubble = QFrame()
        bubble.setObjectName("welcomeBubble")
        welcome_copy = QVBoxLayout(bubble)
        welcome_copy.setContentsMargins(18, 11, 18, 11)
        welcome_copy.setSpacing(3)
        greeting = QLabel("Hi! I'm MJ")
        greeting.setStyleSheet("color:#30241f; font:600 14pt 'Segoe UI'; background:transparent; border:0;")
        prompt = QLabel("How can I help you today?")
        prompt.setStyleSheet("color:#493b35; font:11pt 'Segoe UI'; background:transparent; border:0;")
        welcome_copy.addWidget(greeting)
        welcome_copy.addWidget(prompt)
        hero.addWidget(bubble, 1)
        layout.addWidget(welcome)

        # Four shortcuts all route into existing services and safety checks.
        actions = QGridLayout()
        actions.setHorizontalSpacing(11)
        actions.setVerticalSpacing(10)
        self.action_cards: Dict[str, ActionCard] = {}
        definitions = (
            ("open_app", "📁", "Open App", "Open your applications"),
            ("analyze_screen", "🖥️", "Analyze Screen", "Understand what's on screen"),
            ("create_notes", "📄", "Create Notes", "Write and save notes"),
            ("do_tasks", "⚙️", "Do Tasks", "Automate your work"),
        )
        for index, (key, icon, title, description) in enumerate(definitions):
            card = ActionCard(icon, title, description)
            card.clicked.connect(lambda checked=False, action=key: self.action_requested.emit(action))
            self.action_cards[key] = card
            actions.addWidget(card, index // 2, index % 2)
        layout.addLayout(actions)

        # Transcript and live activity status.
        self.chat_heading = QWidget(self)
        chat_heading = QHBoxLayout(self.chat_heading)
        chat_heading.setContentsMargins(0, 0, 0, 0)
        chat_title = QLabel("CHAT WITH MJ")
        chat_title.setStyleSheet("color:#765b4b; font:700 9pt 'Segoe UI'; letter-spacing:1px;")
        self.activity_label = QLabel("● Ready to help")
        self.activity_label.setStyleSheet("color:#82956b; font:9pt 'Segoe UI';")
        chat_heading.addWidget(chat_title)
        chat_heading.addStretch(1)
        chat_heading.addWidget(self.activity_label)
        layout.addWidget(self.chat_heading)

        self.transcript = QTextEdit()
        self.transcript.setReadOnly(True)
        self.transcript.setFont(QFont("Segoe UI", 10))
        self.transcript.setPlaceholderText("Ask MJ anything…")
        self.transcript.setMinimumHeight(76)
        self.transcript.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self.transcript, 1)
        self.chat_heading.hide()
        self.transcript.hide()

        # Task progress.
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        self.progress_bar.setTextVisible(True)
        layout.addWidget(self.progress_bar)

        self.task_label = QLabel("")
        self.task_label.setFont(QFont("Segoe UI", 9))
        self.task_label.setStyleSheet("color:#795e4e; padding:2px 2px;")
        self.task_label.setVisible(False)
        layout.addWidget(self.task_label)

        # Input row with press-and-hold voice input and conditional cancel.
        input_row = QHBoxLayout()
        input_row.setSpacing(8)
        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText("Ask MJ anything…")
        self.input_edit.setMinimumHeight(48)
        self.input_edit.returnPressed.connect(self._submit)
        self.mic_button = QPushButton("🎙")
        self.mic_button.setFixedSize(46, 46)
        self.mic_button.setToolTip("Hold to talk; release to send")
        self.mic_button.setStyleSheet(self._round_button_style())
        self.mic_button.pressed.connect(self.microphone_pressed)
        self.mic_button.released.connect(self.microphone_released)
        self.send_button = QPushButton("↗")
        self.send_button.setFixedSize(48, 48)
        self.send_button.setToolTip("Send message")
        self.send_button.setStyleSheet("""
            QPushButton { background:#ff9148; color:#fffaf5; border:0;
                border-radius:24px; font:20pt 'Segoe UI'; }
            QPushButton:hover { background:#f17d34; }
            QPushButton:disabled { background:#d8c4b7; color:#fff; }
        """)
        self.send_button.clicked.connect(self._submit)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setEnabled(False)
        self.cancel_button.setVisible(False)
        self.cancel_button.setMinimumHeight(42)
        self.cancel_button.setStyleSheet("""
            QPushButton { background:#fff3e9; color:#9a5637; border:1px solid #edc7ad;
                border-radius:13px; padding:0 13px; }
            QPushButton:hover { background:#ffe7d6; }
            QPushButton:disabled { color:#b4a59b; }
        """)
        self.cancel_button.clicked.connect(self.cancel_requested)
        input_row.addWidget(self.mic_button)
        input_row.addWidget(self.input_edit, 1)
        input_row.addWidget(self.send_button)
        input_row.addWidget(self.cancel_button)
        layout.addLayout(input_row)

        footer = QHBoxLayout()
        self.model_status = QLabel("Model: checking…")
        self.resource_status = QLabel("Resources: –")
        self.model_status.setStyleSheet(
            "color:#9a8172; font:8pt 'Segoe UI'; background:transparent; border:0;")
        self.resource_status.setStyleSheet(
            "color:#9a8172; font:8pt 'Segoe UI'; background:transparent; border:0;")
        footer.addWidget(self.model_status)
        footer.addStretch(1)
        footer.addWidget(self.resource_status)
        self.resize_grip = QSizeGrip(self)
        self.resize_grip.setFixedSize(14, 14)
        footer.addWidget(self.resize_grip)
        layout.addLayout(footer)

    @staticmethod
    def _window_button(text: str, tooltip: str) -> QPushButton:
        button = QPushButton(text)
        button.setFixedSize(34, 34)
        button.setToolTip(tooltip)
        button.setStyleSheet("""
            QPushButton { background:transparent; color:#57453a; border:0;
                border-radius:8px; font:14pt 'Segoe UI'; }
            QPushButton:hover { background:#ffead9; }
        """)
        return button

    @staticmethod
    def _round_button_style() -> str:
        return """
            QPushButton { background:#ffefe2; color:#a9633e; border:1px solid #ecd9c9;
                border-radius:23px; font:16pt 'Segoe UI Emoji'; }
            QPushButton:hover { background:#ffe5d2; border-color:#dda17c; }
            QPushButton:pressed { background:#f8ddc9; }
            QPushButton:disabled { color:#b9aca2; }
        """

    def _submit(self) -> None:
        text = self.input_edit.text().strip()
        if not text:
            return
        self.input_edit.clear()
        self.message_submitted.emit(text)

    # ------------------------------------------------------------------
    def _show_chat(self) -> None:
        self.chat_heading.show()
        self.transcript.show()

    def append_user(self, text: str) -> None:
        self._show_chat()
        self.transcript.append(
            f"<p style='margin:5px 0;color:#5d4638'><b>You</b><br>{self._esc(text)}</p>")

    def append_assistant(self, text: str, error: bool = False) -> None:
        self._show_chat()
        color = "#b44f3e" if error else "#a96137"
        self.transcript.append(
            f"<p style='margin:5px 0;color:#47372f'><b style='color:{color}'>MJ</b><br>{self._esc(text)}</p>"
        )

    def append_status(self, text: str) -> None:
        self._show_chat()
        self.transcript.append(
            f"<p style='margin:3px 0;color:#9a8172'><i>{self._esc(text)}</i></p>")

    def append_task(self, text: str) -> None:
        self._show_chat()
        self.transcript.append(
            f"<p style='margin:4px 0;color:#79533d'><b>Task</b><br>{self._esc(text)}</p>")

    @staticmethod
    def _esc(text: str) -> str:
        return html.escape(text or "", quote=False)

    def set_activity(self, message: str, active: bool = False, error: bool = False) -> None:
        color = "#b44f3e" if error else ("#c27645" if active else "#82956b")
        self.activity_label.setText(f"● {message}")
        self.activity_label.setStyleSheet(f"color:{color}; font:9pt 'Segoe UI';")

    def set_expression(self, state: str) -> None:
        self.welcome_eyes.set_state(state)

    # ------------------------------------------------------------------
    def show_task_progress(self, task: Dict[str, Any]) -> None:
        pct = int(float(task.get("progress", 0)) * 100)
        self.progress_bar.setVisible(True)
        self.task_label.setVisible(True)
        self.progress_bar.setValue(pct)

        steps = task.get("steps", [])
        current = next((s for s in steps if s.get("status") == "running"), None)
        if current:
            text = f"Step {current.get('id')} of {len(steps)}: {current.get('description')}"
        else:
            text = f"{task.get('description', 'Task')} - {task.get('status', '')}"
        self.task_label.setText(text)

        self.cancel_button.setEnabled(task.get("status") == "running")

    def finish_task(self, task: Dict[str, Any]) -> None:
        self.progress_bar.setValue(int(float(task.get("progress", 0)) * 100))
        self.task_label.setText(task.get("summary", task.get("status", "")))
        self.cancel_button.setEnabled(False)
        QTimer.singleShot(4000, self._hide_progress)

    def _hide_progress(self) -> None:
        if not self.cancel_button.isEnabled():
            self.progress_bar.setVisible(False)
            self.task_label.setVisible(False)

    def set_busy(self, busy: bool) -> None:
        self.cancel_button.setEnabled(busy)
        self.cancel_button.setVisible(busy)
        self.send_button.setEnabled(not busy)
        self.input_edit.setEnabled(not busy)


# ======================================================================
# Settings dialog
# ======================================================================
class SettingsDialog(QDialog):
    """Settings for AI model, voice, UI, automation, memory and privacy."""

    def __init__(self, config_manager, parent=None):
        super().__init__(parent)
        self.config_manager = config_manager
        self.setWindowTitle("MJ AI - Settings")
        self.resize(640, 540)

        root = QVBoxLayout(self)
        tabs = QTabWidget()

        tabs.addTab(self._build_audio_tab(), "Voice")
        tabs.addTab(self._build_ai_tab(), "AI Model")
        tabs.addTab(self._build_ui_tab(), "Appearance")
        tabs.addTab(self._build_automation_tab(), "Automation")
        tabs.addTab(self._build_memory_tab(), "Memory")
        root.addWidget(tabs)

        buttons = QHBoxLayout()
        buttons.addStretch()
        save = QPushButton("Save")
        save.clicked.connect(self._save)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(save)
        buttons.addWidget(cancel)
        root.addLayout(buttons)

        self._load()

    # ------------------------------------------------------------------
    def _build_audio_tab(self) -> QWidget:
        tab = QWidget()
        grid = QVBoxLayout(tab)

        voice = QGroupBox("Voice input")
        v = QGridLayout(voice)
        self.ptt_enabled = QCheckBox("Enable push-to-talk (hold mic button or shortcut)")
        self.ptt_key = QLineEdit()
        self.ptt_key.setPlaceholderText("e.g. Ctrl+Shift+M")
        self.auto_listen = QCheckBox("Start listening automatically on launch")
        self.wake_word = QCheckBox("Wake word (experimental, off by default)")
        self.wake_word_text = QLineEdit()
        self.wake_word_text.setPlaceholderText("hey mj")
        self.speech_language = QComboBox()
        self.speech_language.addItem("English", "en")
        self.speech_language.addItem("Hindi", "hi")
        self.speech_language.addItem("Bengali", "bn")
        self.speech_language.addItem("Gujarati", "gu")
        self.speech_language.addItem("Kannada", "kn")
        self.speech_language.addItem("Malayalam", "ml")
        self.speech_language.addItem("Marathi", "mr")
        self.speech_language.addItem("Punjabi", "pa")
        self.speech_language.addItem("Tamil", "ta")
        self.speech_language.addItem("Telugu", "te")
        self.speech_language.addItem("Urdu", "ur")
        self.speech_language.addItem("Auto-detect", "auto")
        v.addWidget(self.ptt_enabled, 0, 0, 1, 2)
        v.addWidget(QLabel("Shortcut:"), 1, 0)
        v.addWidget(self.ptt_key, 1, 1)
        v.addWidget(self.auto_listen, 2, 0, 1, 2)
        v.addWidget(self.wake_word, 3, 0, 1, 2)
        v.addWidget(QLabel("Wake word:"), 4, 0)
        v.addWidget(self.wake_word_text, 4, 1)
        v.addWidget(QLabel("Speech language:"), 5, 0)
        v.addWidget(self.speech_language, 5, 1)
        grid.addWidget(voice)

        out = QGroupBox("Voice output")
        o = QGridLayout(out)
        self.tts_enabled = QCheckBox("Speak responses aloud")
        self.tts_speed = QSlider(Qt.Horizontal)
        self.tts_speed.setRange(50, 200)
        self.tts_volume = QSlider(Qt.Horizontal)
        self.tts_volume.setRange(0, 100)
        self.tts_speed_label = QLabel("1.0x")
        self.tts_volume_label = QLabel("80%")
        self.tts_speed.valueChanged.connect(
            lambda v: self.tts_speed_label.setText(f"{v/100:.1f}x"))
        self.tts_volume.valueChanged.connect(
            lambda v: self.tts_volume_label.setText(f"{v}%"))
        o.addWidget(self.tts_enabled, 0, 0, 1, 3)
        o.addWidget(QLabel("Speed:"), 1, 0)
        o.addWidget(self.tts_speed, 1, 1)
        o.addWidget(self.tts_speed_label, 1, 2)
        o.addWidget(QLabel("Volume:"), 2, 0)
        o.addWidget(self.tts_volume, 2, 1)
        o.addWidget(self.tts_volume_label, 2, 2)
        grid.addWidget(out)

        perm = QGroupBox("Permissions")
        p = QVBoxLayout(perm)
        self.mic_permission = QCheckBox("Allow microphone access (required for voice)")
        self.screen_permission = QCheckBox("Allow screen capture (required for screen reading)")
        p.addWidget(self.mic_permission)
        p.addWidget(self.screen_permission)
        grid.addWidget(perm)

        grid.addStretch()
        return tab

    def _build_ai_tab(self) -> QWidget:
        tab = QWidget()
        form = QGridLayout(tab)

        self.model_name = QLineEdit()
        self.ollama_url = QLineEdit()
        self.auto_load = QCheckBox("Load model automatically when needed")
        self.unload_idle = QCheckBox("Unload model after inactivity (frees RAM)")
        self.idle_timeout = QSpinBox()
        self.idle_timeout.setRange(1, 120)
        self.idle_timeout.setSuffix(" min")
        self.temperature = QDoubleSpinBox()
        self.temperature.setRange(0.0, 2.0)
        self.temperature.setSingleStep(0.1)
        self.check_model = QCheckBox("Check model availability at startup")

        form.addWidget(QLabel("Model name:"), 0, 0)
        form.addWidget(self.model_name, 0, 1)
        form.addWidget(QLabel("Ollama URL:"), 1, 0)
        form.addWidget(self.ollama_url, 1, 1)
        form.addWidget(self.auto_load, 2, 0, 1, 2)
        form.addWidget(self.unload_idle, 3, 0, 1, 2)
        form.addWidget(QLabel("Unload after:"), 4, 0)
        form.addWidget(self.idle_timeout, 4, 1)
        form.addWidget(QLabel("Temperature:"), 5, 0)
        form.addWidget(self.temperature, 5, 1)
        form.addWidget(self.check_model, 6, 0, 1, 2)

        hint = QLabel(
            "Tip: for a lighter CPU model, try qwen2.5:0.5b (about 398 MB). "
            "qwen2.5:1.5b (about 986 MB) needs more free RAM. "
            "Only one model is loaded at a time.\n"
            "Install with: ollama pull <model>"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#666;")
        form.addWidget(hint, 7, 0, 1, 2)
        form.setRowStretch(8, 1)
        return tab

    def _build_ui_tab(self) -> QWidget:
        tab = QWidget()
        form = QGridLayout(tab)

        self.companion_name = QLineEdit()
        self.always_on_top = QCheckBox("Always on top")
        self.window_opacity = QSlider(Qt.Horizontal)
        self.window_opacity.setRange(40, 100)
        self.opacity_label = QLabel("100%")
        self.window_opacity.valueChanged.connect(
            lambda v: self.opacity_label.setText(f"{v}%"))
        self.animation_enabled = QCheckBox("Enable animations")

        form.addWidget(QLabel("Companion name:"), 0, 0)
        form.addWidget(self.companion_name, 0, 1)
        form.addWidget(self.always_on_top, 1, 0, 1, 2)
        form.addWidget(QLabel("Window opacity:"), 2, 0)
        row = QHBoxLayout()
        row.addWidget(self.window_opacity)
        row.addWidget(self.opacity_label)
        wrap = QWidget()
        wrap.setLayout(row)
        form.addWidget(wrap, 2, 1)
        form.addWidget(self.animation_enabled, 3, 0, 1, 2)
        form.setRowStretch(4, 1)
        return tab

    def _build_automation_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        safety = QGroupBox("Safety")
        s = QVBoxLayout(safety)
        self.confirm_sensitive = QCheckBox("Confirm sensitive/destructive actions")
        self.restrict_folders = QCheckBox("Restrict file operations to user folders")
        self.max_time = QSpinBox()
        self.max_time.setRange(5, 300)
        self.max_time.setSuffix(" sec")
        s.addWidget(self.confirm_sensitive)
        s.addWidget(self.restrict_folders)
        row = QHBoxLayout()
        row.addWidget(QLabel("Max task duration:"))
        row.addWidget(self.max_time)
        row.addStretch()
        s.addLayout(row)
        layout.addWidget(safety)

        apps = QGroupBox("Allowed applications")
        a = QVBoxLayout(apps)
        self.app_list = QListWidget()
        add_row = QHBoxLayout()
        add_btn = QPushButton("Add…")
        remove_btn = QPushButton("Remove")
        add_btn.clicked.connect(self._add_app)
        remove_btn.clicked.connect(self._remove_app)
        add_row.addWidget(add_btn)
        add_row.addWidget(remove_btn)
        add_row.addStretch()
        a.addWidget(self.app_list)
        a.addLayout(add_row)
        layout.addWidget(apps)

        mouse = QGroupBox("Input control")
        m = QVBoxLayout(mouse)
        self.enable_mouse = QCheckBox("Allow mouse control")
        self.enable_keyboard = QCheckBox("Allow typing text into windows")
        m.addWidget(self.enable_mouse)
        m.addWidget(self.enable_keyboard)
        layout.addWidget(mouse)

        layout.addStretch()
        return tab

    def _build_memory_tab(self) -> QWidget:
        tab = QWidget()
        form = QGridLayout(tab)

        self.db_path = QLineEdit()
        self.max_conversations = QSpinBox()
        self.max_conversations.setRange(5, 1000)
        self.max_messages = QSpinBox()
        self.max_messages.setRange(50, 10000)
        self.auto_cleanup = QCheckBox("Automatically remove old conversations")
        self.cleanup_days = QSpinBox()
        self.cleanup_days.setRange(1, 365)
        self.cleanup_days.setSuffix(" days")

        clear_btn = QPushButton("Clear all conversation history now")
        clear_btn.clicked.connect(self._clear_history)

        form.addWidget(QLabel("Database:"), 0, 0)
        form.addWidget(self.db_path, 0, 1)
        form.addWidget(QLabel("Max conversations:"), 1, 0)
        form.addWidget(self.max_conversations, 1, 1)
        form.addWidget(QLabel("Max messages / conversation:"), 2, 0)
        form.addWidget(self.max_messages, 2, 1)
        form.addWidget(self.auto_cleanup, 3, 0, 1, 2)
        form.addWidget(QLabel("Delete conversations older than:"), 4, 0)
        form.addWidget(self.cleanup_days, 4, 1)
        form.addWidget(clear_btn, 5, 0, 1, 2)
        form.setRowStretch(6, 1)
        return tab

    # ------------------------------------------------------------------
    def _add_app(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select application", "", "Executables (*.exe);;All files (*)")
        if path:
            self.app_list.addItem(QListWidgetItem(path))

    def _remove_app(self) -> None:
        for item in self.app_list.selectedItems():
            self.app_list.takeItem(self.app_list.row(item))

    def _clear_history(self) -> None:
        if QMessageBox.question(
            self, "Clear history",
            "Delete ALL stored conversations? This cannot be undone.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        ) == QMessageBox.Yes:
            self._pending_clear = True
            QMessageBox.information(self, "Scheduled",
                                    "History will be cleared when you save settings.")

    # ------------------------------------------------------------------
    def _load(self) -> None:
        c = self.config_manager
        a = c.get_audio_config()
        ai = c.get_ai_config()
        u = c.get_ui_config()
        auto = c.get_automation_config()
        mem = c.get_memory_config()

        self.ptt_enabled.setChecked(a.push_to_talk_enabled)
        self.ptt_key.setText(a.push_to_talk_key)
        self.auto_listen.setChecked(a.auto_start_listening)
        self.wake_word.setChecked(a.wake_word_enabled)
        self.wake_word_text.setText(a.wake_word)
        language_index = self.speech_language.findData(
            getattr(a, "language", "en"))
        self.speech_language.setCurrentIndex(
            language_index if language_index >= 0 else 0)
        self.tts_enabled.setChecked(a.tts_enabled)
        self.tts_speed.setValue(int(a.tts_speed * 100))
        self.tts_volume.setValue(int(a.tts_volume * 100))
        self.mic_permission.setChecked(a.microphone_allowed)
        self.screen_permission.setChecked(a.screen_capture_allowed)

        self.model_name.setText(ai.model_name)
        self.ollama_url.setText(ai.ollama_url)
        self.auto_load.setChecked(ai.auto_load_model)
        self.unload_idle.setChecked(ai.unload_on_idle)
        self.idle_timeout.setValue(ai.idle_timeout_minutes)
        self.check_model.setChecked(ai.check_model_on_startup)

        self.companion_name.setText(u.companion_name)
        self.always_on_top.setChecked(u.always_on_top)
        self.window_opacity.setValue(int(u.window_opacity * 100))
        self.animation_enabled.setChecked(u.animation_speed > 0)

        self.confirm_sensitive.setChecked(auto.confirm_destructive_actions)
        self.restrict_folders.setChecked(auto.restrict_to_user_folders)
        self.max_time.setValue(auto.max_execution_time)
        self.enable_mouse.setChecked(auto.enable_mouse_control)
        self.enable_keyboard.setChecked(auto.enable_keyboard_input)
        self.app_list.clear()
        for app in auto.allowed_applications:
            self.app_list.addItem(QListWidgetItem(app))

        self.db_path.setText(mem.database_path)
        self.max_conversations.setValue(mem.max_conversations)
        self.max_messages.setValue(mem.max_messages_per_conversation)
        self.auto_cleanup.setChecked(mem.auto_cleanup)
        self.cleanup_days.setValue(mem.cleanup_days)
        self._pending_clear = False

    def _save(self) -> None:
        c = self.config_manager
        saved_ui = c.get_ui_config()
        c.set_section("audio", {
            "push_to_talk_enabled": self.ptt_enabled.isChecked(),
            "push_to_talk_key": self.ptt_key.text() or "ctrl+shift+m",
            "auto_start_listening": self.auto_listen.isChecked(),
            "wake_word_enabled": self.wake_word.isChecked(),
            "wake_word": self.wake_word_text.text() or "hey mj",
            "language": self.speech_language.currentData() or "en",
            "tts_enabled": self.tts_enabled.isChecked(),
            "tts_speed": self.tts_speed.value() / 100.0,
            "tts_volume": self.tts_volume.value() / 100.0,
            "tts_voice": "default",
            "microphone_allowed": self.mic_permission.isChecked(),
            "screen_capture_allowed": self.screen_permission.isChecked(),
        })
        c.set_section("ai", {
            "model_name": self.model_name.text() or "llama3.2:1b",
            "ollama_url": self.ollama_url.text() or "http://localhost:11434",
            "auto_load_model": self.auto_load.isChecked(),
            "unload_on_idle": self.unload_idle.isChecked(),
            "idle_timeout_minutes": self.idle_timeout.value(),
            "max_context_length": 1024,
            "temperature": 0.7,
            "top_p": 0.9,
            "top_k": 40,
            "check_model_on_startup": self.check_model.isChecked(),
            "install_missing_models": False,
            "model_storage_path": "models",
        })
        c.set_section("ui", {
            "window_width": saved_ui.window_width,
            "window_height": saved_ui.window_height,
            "window_x": saved_ui.window_x,
            "window_y": saved_ui.window_y,
            "companion_x": saved_ui.companion_x,
            "companion_y": saved_ui.companion_y,
            "always_on_top": self.always_on_top.isChecked(),
            "transparent_background": False,
            "window_opacity": self.window_opacity.value() / 100.0,
            "animation_speed": 1.0 if self.animation_enabled.isChecked() else 0.0,
            "eye_blink_interval": 3000,
            "eye_movement_sensitivity": 1.0,
            "show_listening_indicator": True,
            "show_thinking_indicator": True,
            "companion_name": self.companion_name.text() or "MJ",
            "companion_personality": "friendly",
            "companion_color": "#333333",
            "conversation_panel_visible": True,
            "settings_panel_visible": False,
            "status_bar_visible": True,
        })
        c.set_section("automation", {
            "confirm_destructive_actions": self.confirm_sensitive.isChecked(),
            "restrict_to_user_folders": self.restrict_folders.isChecked(),
            "max_execution_time": self.max_time.value(),
            "allowed_applications": [
                self.app_list.item(i).text()
                for i in range(self.app_list.count())
            ],
            "enable_mouse_control": self.enable_mouse.isChecked(),
            "enable_keyboard_input": self.enable_keyboard.isChecked(),
            "prevent_sleep": False,
        })
        c.set_section("memory", {
            "storage_backend": "sqlite",
            "database_path": self.db_path.text() or "data/myai.db",
            "max_conversations": self.max_conversations.value(),
            "max_messages_per_conversation": self.max_messages.value(),
            "auto_cleanup": self.auto_cleanup.isChecked(),
            "cleanup_days": self.cleanup_days.value(),
            "store_user_preferences": True,
            "store_task_history": True,
            "store_interaction_patterns": False,
        })
        c.save()
        self.accept()


# ======================================================================
# Main window
# ======================================================================
class MainWindow(QMainWindow):
    """
    Conversation panel and system tray for the separate floating companion.

    All worker-thread events are pushed into a thread-safe queue and drained
    by a QTimer on the UI thread, keeping Qt interactions safe.
    """

    # Internal queued signal: posted from any thread, handled on UI thread.
    _event_signal = Signal(str, str, dict)

    def __init__(self,
                 config_manager,
                 ai_service=None,
                 audio_service=None,
                 screen_analyzer=None,
                 automation_service=None,
                 resource_monitor=None,
                 task_planner=None,
                 memory_store=None,
                 parent=None):
        super().__init__(parent)

        self.config_manager = config_manager
        self.ai_service = ai_service
        self.audio_service = audio_service
        self.screen_analyzer = screen_analyzer
        self.automation_service = automation_service
        self.resource_monitor = resource_monitor
        self.task_planner = task_planner
        self.memory_store = memory_store

        self._streaming_reply = ""

        self._build_ui()
        self._build_tray()
        self._build_shortcuts()
        self._apply_window_config()
        self._connect_services()

        # Deliver worker events on the UI thread (queued connection).
        self._event_signal.connect(self._handle_event)

        # Periodic status refresh (resource + idle model unload hints).
        self._status_timer = QTimer(self)
        self._status_timer.setInterval(5000)
        self._status_timer.timeout.connect(self._refresh_status)
        self._status_timer.start()

        logger.info("Main window ready")

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        self.setWindowTitle("MJ AI")
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setMinimumSize(580, 500)

        self.companion = CompanionWidget()
        self.companion_window = FloatingCompanionWindow(
            self.companion, self.config_manager, self.show_panel)

        central = QWidget()
        central.setAttribute(Qt.WA_TranslucentBackground, True)
        root = QVBoxLayout(central)
        root.setContentsMargins(6, 6, 6, 6)
        self.conversation = ConversationPanel()
        root.addWidget(self.conversation)

        self.setCentralWidget(central)
        self.setStyleSheet("QMainWindow { background:transparent; }")
        self.model_status = self.conversation.model_status
        self.resource_status = self.conversation.resource_status

        # Wire conversation panel signals.
        self.conversation.message_submitted.connect(self._on_text_submitted)
        self.conversation.cancel_requested.connect(self._on_cancel)
        self.conversation.action_requested.connect(self._on_action_card)
        self.conversation.microphone_pressed.connect(self._on_mic_pressed)
        self.conversation.microphone_released.connect(self._on_mic_released)
        self.conversation.settings_requested.connect(self.open_settings)
        self.conversation.minimize_requested.connect(self.showMinimized)
        self.conversation.maximize_requested.connect(self._toggle_maximize)
        self.conversation.close_requested.connect(self.hide)

        # Wire companion signals.
        self.companion.mic_pressed.connect(self._on_mic_pressed)
        self.companion.mic_released.connect(self._on_mic_released)
        self.companion.pause_toggled.connect(self._on_pause_toggled)
        self.companion.settings_requested.connect(self._open_settings_from_companion)
        self.companion.state_changed.connect(self.conversation.set_expression)

    def _build_tray(self) -> None:
        """Optional system tray operation (FR-10)."""
        self.tray: Optional[QSystemTrayIcon] = None
        try:
            icon = self.style().standardIcon(QStyle.SP_ComputerIcon)
            self.tray = QSystemTrayIcon(icon, self)
            self.tray.setToolTip("MJ AI")

            menu = QMenu()
            show_action = QAction("Show / Hide Assistant Panel", self)
            show_action.triggered.connect(self._toggle_visibility)
            companion_action = QAction("Show / Hide Companion", self)
            companion_action.triggered.connect(self.companion_window.toggle_visible)
            settings_action = QAction("Settings", self)
            settings_action.triggered.connect(self._open_settings_from_companion)
            quit_action = QAction("Quit", self)

            menu.addAction(show_action)
            menu.addAction(companion_action)
            menu.addAction(settings_action)
            menu.addSeparator()
            quit_action.triggered.connect(self.quit_application)
            menu.addAction(quit_action)
            self.tray.setContextMenu(menu)
            self.tray.activated.connect(self._on_tray_activated)
            self.tray.show()
        except Exception as exc:
            logger.warning(f"System tray unavailable: {exc}")

    def _build_shortcuts(self) -> None:
        """Keyboard shortcuts for listening, settings and cancellation."""
        try:
            self.mic_shortcut = QShortcut(QKeySequence("Ctrl+Shift+M"), self)
            self.mic_shortcut.setContext(Qt.ApplicationShortcut)
            # Toggle-style push-to-talk via keyboard.
            self.mic_shortcut.activated.connect(self._toggle_listening_shortcut)

            settings_sc = QShortcut(QKeySequence("Ctrl+,"), self)
            settings_sc.activated.connect(self._open_settings_from_companion)

            companion_sc = QShortcut(QKeySequence("Ctrl+Shift+H"), self)
            companion_sc.setContext(Qt.ApplicationShortcut)
            companion_sc.activated.connect(self.companion_window.toggle_visible)

            cancel_sc = QShortcut(QKeySequence("Escape"), self)
            cancel_sc.activated.connect(self._on_cancel)
        except Exception as exc:
            logger.warning(f"Shortcuts unavailable: {exc}")

    def _apply_window_config(self) -> None:
        try:
            ui = self.config_manager.get_ui_config()
            self.resize(max(ui.window_width, 600), max(ui.window_height, 520))
            self.move(ui.window_x, ui.window_y)
            self.setWindowOpacity(ui.window_opacity)
            self.companion_window.apply_config(ui)
            self.companion.set_name(ui.companion_name)
            self.companion.set_animations_enabled(ui.animation_speed > 0)
        except Exception as exc:
            logger.warning(f"Could not apply window config: {exc}")

    def _connect_services(self) -> None:
        """Register confirmation handlers with the safety layer."""
        if self.task_planner is not None:
            self.task_planner.set_confirmation_handler(self._queue_confirmation)

    # ------------------------------------------------------------------
    # Event bridge (worker threads -> UI thread)
    # ------------------------------------------------------------------
    def post_event(self, source: str, event: str, data: Optional[Dict[str, Any]] = None) -> None:
        """Thread-safe: callable from any thread. Delivered on the UI thread."""
        self._event_signal.emit(source, event, data or {})

    def _handle_event(self, source: str, event: str, data: Dict[str, Any]) -> None:
        try:
            handler = self._handlers().get((source, event))
            if handler:
                handler(data)
            else:
                logger.debug(f"Unhandled event: {source}/{event}")
        except Exception as exc:
            logger.error(f"Error handling {source}/{event}: {exc}")

    def _handlers(self):
        return {
            # ---- AI ----
            ("ai", "thinking_started"): self._on_thinking_started,
            ("ai", "thinking_finished"): self._on_thinking_finished,
            ("ai", "ai_reply"): self._on_ai_reply,
            ("ai", "ai_error"): self._on_ai_error,
            ("ai", "model_missing"): self._on_model_missing,
            ("ai", "model_error"): self._on_model_error,
            ("ai", "model_available"): self._on_model_available,
            ("ai", "model_status"): self._on_model_status,
            ("ai", "resource_warning"): self._on_resource_warning,
            # ---- Tasks ----
            ("ai", "task_planned"): self._on_task_planned,
            ("ai", "task_result"): self._on_task_result,
            ("ai", "task_error"): self._on_task_error,
            ("planner", "step_update"): self._on_task_progress,
            ("planner", "task_finished"): self._on_task_progress,
            # ---- Voice ----
            ("voice", "transcript"): self._on_transcript,
            ("voice", "listening_started"): self._on_listening_started,
            ("voice", "listening_stopped"): self._on_listening_stopped,
            ("voice", "transcription_started"): self._on_transcription_started,
            ("voice", "transcription_finished"): self._on_transcription_finished,
            ("voice", "voice_error"): self._on_voice_error,
            ("voice", "speech_started"): self._on_speech_started,
            ("voice", "speech_finished"): self._on_speech_finished,
            # ---- Screen ----
            ("screen", "screen_analysis_started"): self._on_screen_analysis_started,
            ("screen", "screen_analysis_finished"): self._on_screen_analysis,
            ("screen", "screen_analysis_error"): self._on_screen_error,
            # ---- UI ----
            ("ui", "confirmation_required"): self._on_confirmation,
        }

    # ------------------------------------------------------------------
    # Service callbacks (run in worker threads; only post events)
    # ------------------------------------------------------------------
    def on_ai_event(self, event: str, data: Dict[str, Any]) -> None:
        self.post_event("ai", event, data)

    def on_audio_event(self, event: str, data: Dict[str, Any]) -> None:
        self.post_event("voice", event, data)

    def on_screen_event(self, event: str, data: Dict[str, Any]) -> None:
        self.post_event("screen", event, data)

    def on_automation_event(self, event: str, data: Dict[str, Any]) -> None:
        self.post_event("automation", event, data)

    def on_planner_progress(self, payload: Dict[str, Any]) -> None:
        event = payload.get("event", "step_update")
        self.post_event("planner", event, payload)

    def _queue_confirmation(self, conf_id: str, action: str, description: str) -> None:
        """Called from a worker thread - route to UI thread."""
        self.post_event("ui", "confirmation_required", {
            "id": conf_id, "action": action, "description": description,
        })

    # ------------------------------------------------------------------
    # UI-thread event handlers
    # ------------------------------------------------------------------
    def _on_thinking_started(self, data: Dict[str, Any]) -> None:
        self.companion.set_state("thinking")
        self.companion.set_work_message("Thinking…")
        self.conversation.set_activity("MJ is thinking…", active=True)
        self.conversation.set_busy(True)

    def _on_thinking_finished(self, data: Dict[str, Any]) -> None:
        if data.get("cancelled"):
            self.conversation.append_status("Generation cancelled.")
        self.companion.set_work_message("")

    def _on_ai_reply(self, data: Dict[str, Any]) -> None:
        text = data.get("text", "")
        error = bool(data.get("error"))
        if text:
            self.conversation.append_assistant(text, error=error)
            self._speak(text)
        self.conversation.set_activity(
            "Something went wrong" if error else "Ready to help", error=error)
        self.companion.set_state("error" if error else "idle")
        self.companion.set_work_message("")
        self.conversation.set_busy(False)

    def _on_ai_error(self, data: Dict[str, Any]) -> None:
        self.conversation.append_assistant(
            f"Something went wrong: {data.get('error', 'unknown error')}", error=True)
        self.conversation.set_activity("AI needs attention", error=True)
        self.companion.set_state("error")
        self.conversation.set_busy(False)

    def _on_model_missing(self, data: Dict[str, Any]) -> None:
        model = data.get("model", "?")
        hint = data.get("hint", f"Run: ollama pull {model}")
        installed = data.get("installed", [])
        installed_hint = (
            f" Installed models: {', '.join(installed)}."
            if installed else ""
        )
        self.model_status.setText(f"Model: {model} NOT installed")
        self.conversation.set_activity("AI model is not installed", error=True)
        self.conversation.append_status(
            f"The AI model '{model}' is not installed.{installed_hint} {hint}"
        )
        self.companion.set_state("error")

    def _on_model_error(self, data: Dict[str, Any]) -> None:
        self.model_status.setText("Model: server error")
        self.conversation.set_activity("Ollama is unavailable", error=True)
        self.conversation.append_status(
            f"AI server problem: {data.get('error', '')} {data.get('hint', '')}"
        )

    def _on_model_available(self, data: Dict[str, Any]) -> None:
        model = data.get("model", "?")
        self.model_status.setText(f"Model: {model} ready")
        self.conversation.set_activity("Ready to help")
        self.conversation.append_status(f"AI model '{model}' is ready.")

    def _on_model_status(self, data: Dict[str, Any]) -> None:
        loaded = data.get("loaded")
        model = data.get("model", "")
        if loaded:
            self.model_status.setText(f"Model: {model} loaded")
        else:
            self.model_status.setText(f"Model: {model} unloaded (idle)")

    def _on_resource_warning(self, data: Dict[str, Any]) -> None:
        self.conversation.append_status(data.get("message", "Low resources."))
        self.conversation.set_activity("Waiting for system resources", error=True)

    def _on_task_planned(self, data: Dict[str, Any]) -> None:
        task = data.get("task", {})
        self.conversation.append_task(task.get("description", "Task"))
        self.conversation.show_task_progress(task)
        self.companion.set_state("thinking")
        self.conversation.set_activity("Working on your task…", active=True)
        self.conversation.set_busy(True)

    def _on_task_progress(self, data: Dict[str, Any]) -> None:
        task = data.get("task", {})
        if task:
            self.conversation.show_task_progress(task)

    def _on_task_result(self, data: Dict[str, Any]) -> None:
        task = data.get("task", {})
        status = task.get("status", "")
        summary = task.get("summary", "")
        self.conversation.finish_task(task)
        self.conversation.append_status(f"Task {status}: {summary}")
        self.conversation.set_busy(False)
        if status == "completed":
            self.conversation.set_activity("Task complete")
            self._pulse_success()
        elif status in ("failed", "cancelled"):
            self.conversation.set_activity("Task needs attention", error=True)
            self.companion.set_state("error")
        else:
            self.conversation.set_activity("Ready to help")
            self.companion.set_state("idle")

    def _on_task_error(self, data: Dict[str, Any]) -> None:
        self.conversation.append_status(f"Task error: {data.get('error', '')}")
        self.conversation.set_activity("Task needs attention", error=True)
        self.companion.set_state("error")
        self.conversation.set_busy(False)

    def _on_transcript(self, data: Dict[str, Any]) -> None:
        """Display a recognised transcript (delivery to AI happens in the
        voice service via the text sink - never twice from here)."""
        text = data.get("text", "")
        if text:
            self.conversation.append_user(text)
            self.conversation.set_activity("Heard you — preparing that…", active=True)

    def _on_listening_started(self, data: Dict[str, Any]) -> None:
        self.companion.set_state("listening")
        self.conversation.set_activity("Listening — release to send", active=True)
        self.conversation.append_status("Listening… (release to send)")

    def _on_listening_stopped(self, data: Dict[str, Any]) -> None:
        if self.companion.eyes.state == "listening":
            self.companion.set_state("idle")
        self.companion.set_work_message("Transcribing…")
        self.conversation.set_activity("Transcribing your voice…", active=True)

    def _on_transcription_started(self, data: Dict[str, Any]) -> None:
        self.conversation.set_activity("Transcribing your voice…", active=True)

    def _on_transcription_finished(self, data: Dict[str, Any]) -> None:
        self.companion.set_work_message("")
        if self.ai_service is None or not self.ai_service.is_busy():
            self.conversation.set_activity("Ready to help")

    def _on_voice_error(self, data: Dict[str, Any]) -> None:
        error = data.get("error", "")
        self.conversation.append_status(f"Voice: {error}")
        self.conversation.append_status("You can type your command instead.")
        self.conversation.set_activity("Voice input needs attention", error=True)
        self.companion.set_state("error")

    def _on_speech_started(self, data: Dict[str, Any]) -> None:
        if self.companion.eyes.state == "idle":
            self.companion.set_state("speaking")
        self.conversation.set_activity("MJ is speaking…", active=True)

    def _on_speech_finished(self, data: Dict[str, Any]) -> None:
        if self.companion.eyes.state == "speaking":
            self.companion.set_state("idle")
        if self.ai_service is None or not self.ai_service.is_busy():
            self.conversation.set_activity("Ready to help")

    def _on_screen_analysis_started(self, data: Dict[str, Any]) -> None:
        self.companion.set_state("thinking")
        self.conversation.set_activity("Reading your screen…", active=True)

    def _on_screen_analysis(self, data: Dict[str, Any]) -> None:
        if data.get("has_text"):
            text = data.get("text", "")
            self.conversation.append_status(f"Screen text extracted ({len(text)} chars).")
            self.conversation.set_activity("Screen text ready — asking MJ…", active=True)
            self.companion.set_state("thinking")
            # Feed to AI for explanation with untrusted-source labelling.
            if self.ai_service is not None:
                self.ai_service.send_message(
                    f"Explain what is on my screen:\n{text}", source="screen")
        else:
            err = data.get("error") or "No readable text found."
            self.conversation.append_status(f"Screen reading: {err}")
            self.conversation.set_activity(
                "No readable screen text", error=bool(data.get("error")))
            self.companion.set_state("error" if data.get("error") else "idle")

    def _on_screen_error(self, data: Dict[str, Any]) -> None:
        self.conversation.append_status(
            f"Screen analysis failed: {data.get('error', '')}", )
        self.conversation.set_activity("Screen reading needs attention", error=True)
        self.companion.set_state("error")

    def _on_confirmation(self, data: Dict[str, Any]) -> None:
        """Modal confirmation for sensitive actions (UI thread)."""
        conf_id = data.get("id", "")
        description = data.get("description", "An operation requires approval.")

        result = QMessageBox.question(
            self,
            "MJ AI - Confirmation required",
            f"{description}\n\nDo you want to allow this?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        approved = result == QMessageBox.Yes

        if self.task_planner is not None:
            self.task_planner.resolve_confirmation(conf_id, approved)
        elif self.ai_service is not None and hasattr(self.ai_service, "permissions"):
            self.ai_service.permissions.resolve_confirmation(conf_id, approved)

        self.conversation.append_status(
            "Approved." if approved else "Declined by user."
        )

    # ------------------------------------------------------------------
    # User actions
    # ------------------------------------------------------------------
    def _on_text_submitted(self, text: str) -> None:
        self.conversation.append_user(text)
        self.conversation.set_activity("Sending to MJ…", active=True)
        if self.ai_service is not None:
            self.ai_service.send_message(text)
        else:
            self.conversation.set_activity("AI service unavailable", error=True)
            self.conversation.append_assistant(
                "The AI service is not available yet.", error=True)

    def _on_action_card(self, action: str) -> None:
        """Turn a home-card click into a request handled by existing services."""
        self.show_panel()

        if action == "open_app":
            app_name, accepted = QInputDialog.getText(
                self,
                "Open an application",
                "Which installed app should MJ open?",
                QLineEdit.Normal,
                "Notepad",
            )
            if accepted and app_name.strip():
                self._on_text_submitted(f"Open {app_name.strip()}.")
            return

        if action == "analyze_screen":
            if self.screen_analyzer is None:
                self.conversation.append_status("Screen analysis is unavailable.")
                self.conversation.set_activity("Screen analysis unavailable", error=True)
                return
            if not self.screen_analyzer.state.screen_capture_allowed:
                self.conversation.append_status(
                    "Screen capture is off. Allow it in Settings → Voice → Permissions, "
                    "then choose Analyze Screen again.")
                self.conversation.set_activity("Screen permission is off", error=True)
                return

            self.conversation.append_user("Analyze my current screen")
            self.conversation.set_activity("Reading your screen…", active=True)
            self._screen_analysis_thread = threading.Thread(
                target=self._run_screen_analysis,
                daemon=True,
                name="mj-screen-action",
            )
            self._screen_analysis_thread.start()
            return

        if action == "create_notes":
            topic, accepted = QInputDialog.getText(
                self,
                "Create a note",
                "What should the note be about?",
            )
            if accepted and topic.strip():
                self._on_text_submitted(
                    "Create a concise note about " + topic.strip() +
                    ". Save it as a new text file in my Documents folder, "
                    "and ask me before overwriting any file."
                )
            return

        if action == "do_tasks":
            task, accepted = QInputDialog.getText(
                self,
                "Describe a task",
                "What would you like MJ to do?",
                QLineEdit.Normal,
                "Open Chrome and…",
            )
            if accepted and task.strip():
                self._on_text_submitted(task.strip())

    def _run_screen_analysis(self) -> None:
        """Run the permission-gated OCR operation away from the Qt UI thread."""
        try:
            self.screen_analyzer.analyze()
        except Exception as exc:
            logger.error(f"Screen action failed: {exc}")
            self.post_event("screen", "screen_analysis_error", {"error": str(exc)})

    def _on_mic_pressed(self) -> None:
        if self.audio_service is None:
            self.conversation.append_status("Voice service unavailable.")
            return
        started = self.audio_service.begin_listening()
        if not started:
            err = self.audio_service.state.last_error
            if err:
                self.conversation.append_status(err)

    def _on_mic_released(self) -> None:
        if self.audio_service is not None and self.audio_service.state.is_listening:
            self.audio_service.end_listening()

    def _toggle_listening_shortcut(self) -> None:
        """Ctrl+Shift+M toggles listening (press again to stop)."""
        if self.audio_service is None:
            return
        if self.audio_service.state.is_listening:
            self.audio_service.end_listening()
        else:
            if not self.audio_service.begin_listening():
                err = self.audio_service.state.last_error
                if err:
                    self.conversation.append_status(err)

    def _on_pause_toggled(self) -> None:
        if self.companion.paused:
            if self.audio_service is not None:
                self.audio_service.cancel_current_operation()
            if self.ai_service is not None:
                self.ai_service.cancel_generation()
            self.companion.set_state("paused")
            self.conversation.append_status("Paused.")
        else:
            self.companion.set_state("idle")
            self.conversation.append_status("Resumed.")

    def _on_cancel(self) -> None:
        """Cancel any running operation (Esc or Cancel button)."""
        cancelled = False
        if self.task_planner is not None and self.task_planner.is_running:
            self.task_planner.cancel()
            cancelled = True
        if self.ai_service is not None and self.ai_service.is_busy():
            self.ai_service.cancel_generation()
            cancelled = True
        if self.audio_service is not None:
            if self.audio_service.state.is_listening:
                self.audio_service.end_listening()
                cancelled = True
            self.audio_service.stop_speaking()

        if cancelled:
            self.conversation.append_status("Cancellation requested…")
            self.conversation.set_activity("Cancellation requested")
            self.companion.set_state("idle")
            self.conversation.set_busy(False)

    def open_settings(self) -> None:
        dialog = SettingsDialog(self.config_manager, self)
        if dialog.exec() == QDialog.Accepted:
            if getattr(dialog, "_pending_clear", False):
                if self.memory_store is not None:
                    try:
                        removed = self.memory_store.clear_history()
                        self.conversation.append_status(
                            f"Cleared {removed} stored message(s).")
                    except Exception as exc:
                        self.conversation.append_status(
                            f"Could not clear history: {exc}")
            self._apply_settings_changes()

    def show_companion(self) -> None:
        self.companion_window.show()
        self.companion_window.raise_()

    def _toggle_maximize(self) -> None:
        if self.isMaximized():
            self.showNormal()
            self.conversation.maximize_button.setText("□")
        else:
            self.showMaximized()
            self.conversation.maximize_button.setText("❐")

    def show_panel(self) -> None:
        """Show the conversation panel without creating another app instance."""
        if self.isMaximized():
            self.showMaximized()
        else:
            self.showNormal()
        self.raise_()
        self.activateWindow()

    def _open_settings_from_companion(self) -> None:
        self.show_panel()
        self.open_settings()

    def _apply_settings_changes(self) -> None:
        """Push saved settings into live services."""
        try:
            audio_cfg = self.config_manager.get_audio_config()
            if self.audio_service is not None:
                self.audio_service.set_microphone_allowed(audio_cfg.microphone_allowed)
                self.audio_service.set_recognition_language(audio_cfg.language)
                self.audio_service.update_tts_speed(audio_cfg.tts_speed)
                self.audio_service.update_volume(audio_cfg.tts_volume)

            if self.screen_analyzer is not None:
                self.screen_analyzer.set_screen_capture_permission(
                    audio_cfg.screen_capture_allowed)

            ui_cfg = self.config_manager.get_ui_config()
            self.companion.set_name(ui_cfg.companion_name)
            self.companion_window.apply_config(ui_cfg)

            self.conversation.append_status("Settings saved.")
        except Exception as exc:
            logger.error(f"Failed to apply settings: {exc}")
            self.conversation.append_status(f"Settings error: {exc}")

    # ------------------------------------------------------------------
    # Tray / window behaviour
    # ------------------------------------------------------------------
    def _toggle_visibility(self) -> None:
        if self.isVisible():
            self.hide()
        else:
            self.show_panel()

    def _on_tray_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.Trigger:
            self._toggle_visibility()

    def closeEvent(self, event) -> None:
        # Move to tray instead of quitting when tray is available.
        if self.tray is not None and getattr(self, "_really_quit", False) is False:
            self.hide()
            self.tray.showMessage(
                "MJ AI", "Still running in the system tray. "
                         "Use Quit from the tray menu to exit.",
                QSystemTrayIcon.Information, 2000,
            )
            event.ignore()
            return

        self._shutdown()
        event.accept()
        if self.app_ref is not None:
            self.app_ref.quit()

    def quit_application(self) -> None:
        """Real exit: bypass the tray and close everything."""
        self._really_quit = True
        self._shutdown()
        self.hide()
        if self.tray is not None:
            self.tray.hide()
        app = self.app_ref
        if app is not None:
            app.quit()
        else:
            self.close()

    app_ref = None

    def _shutdown(self) -> None:
        logger.info("Shutting down MJ AI from UI…")
        try:
            poll_timer = getattr(self, "_poll_timer", None)
            if poll_timer is not None:
                poll_timer.stop()
            self._status_timer.stop()
            self.companion_window.close()
            if self.audio_service is not None:
                self.audio_service.cleanup()
            if self.ai_service is not None:
                self.ai_service.cleanup()
            if self.memory_store is not None:
                self.memory_store.close()
            if self.config_manager is not None:
                # Persist window geometry.
                ui = self.config_manager.get_ui_config()
                ui.window_width = self.width()
                ui.window_height = self.height()
                ui.window_x = self.x()
                ui.window_y = self.y()
                ui.companion_x = self.companion_window.x()
                ui.companion_y = self.companion_window.y()
                self.config_manager.set_section("ui", vars(ui))
                self.config_manager.save()
            if self.tray is not None:
                self.tray.hide()
        except Exception as exc:
            logger.error(f"Shutdown error: {exc}")
        logger.info("MJ AI closed.")

    # ------------------------------------------------------------------
    # Status refresh
    # ------------------------------------------------------------------
    def _refresh_status(self) -> None:
        if self.resource_monitor is not None:
            try:
                status = self.resource_monitor.get_resource_status()
                stats = status.get("stats", {})
                self.resource_status.setText(
                    f"CPU {stats.get('cpu_percent', 0):.0f}%  |  "
                    f"Free RAM {stats.get('memory_available_mb', 0):.0f} MB"
                )
                if status.get("status") == "critical":
                    self.conversation.append_status(
                        "System memory is critically low."
                    )
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _speak(self, text: str) -> None:
        if self.audio_service is not None:
            self.audio_service.speak(text)

    def _pulse_success(self) -> None:
        self.companion.set_state("success")
        QTimer.singleShot(1500, self._finish_success_pulse)

    def _finish_success_pulse(self) -> None:
        if self.companion.eyes.state == "success":
            self.companion.set_state("idle")

    # Compatibility API used by app.py lifecycle hooks.
    def update_ai_status(self, event: str, data: Dict[str, Any]) -> None:
        self._handle_event("ai", event, data)

    def update_audio_status(self, event: str, data: Dict[str, Any]) -> None:
        self._handle_event("voice", event, data)

    def update_automation_status(self, event: str, data: Dict[str, Any]) -> None:
        self._handle_event("automation", event, data)
