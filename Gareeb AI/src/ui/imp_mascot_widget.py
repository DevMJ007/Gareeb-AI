"""Animated, hand-drawn imp mascot matching the supplied reference."""

from __future__ import annotations

import math
import random
import time
from typing import Optional

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget


class ImpMascotWidget(QWidget):
    """Paint the Gareeb imp mascot and animate it for assistant states."""

    _STATES = {
        "idle", "listening", "thinking", "working",
        "speaking", "success", "error", "paused",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(1, 1)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        self.setAccessibleName(
            "Gareeb, a red imp with bat wings, horns, and crossed swords"
        )
        self.state = "idle"
        self._animations_enabled = True
        self._opening = 1.0
        self._target_opening = 1.0
        self._phase = 0.0
        self._last_tick = time.monotonic()
        self._next_blink = self._last_tick + random.uniform(2.5, 5.0)
        self._blink_started: Optional[float] = None
        self._blink_opening = 1.0
        self._gaze = QPointF()
        self._gaze_target = QPointF()
        self._next_glance = self._last_tick + random.uniform(2.0, 4.5)
        self._wing_offset = 0.0
        self._float_offset = 0.0
        self._breath = 0.0
        self._speech_level = 0.0
        self._target_speech_level = 0.0
        self._last_speech_pulse = 0.0
        self._mouth_opening = 0.0
        self._target_mouth_opening = 0.0
        self._head_tilt = 0.0
        self._arm_l_angle = -35.0
        self._arm_r_angle = 35.0
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)

    def set_state(self, state: str) -> None:
        state = state if state in self._STATES else "idle"
        if state == self.state:
            return
        self.state = state
        self._target_opening = {
            "idle": 1.0, "listening": 0.98, "thinking": 0.90,
            "working": 0.94, "speaking": 0.98, "success": 0.96,
            "error": 0.91, "paused": 0.82,
        }[state]
        self._target_mouth_opening = {
            "idle": 0.0, "listening": 0.0, "thinking": 0.0,
            "working": 0.0, "speaking": 0.25, "success": 0.35,
            "error": 0.2, "paused": 0.0,
        }[state]
        self._head_tilt = {
            "thinking": -5.0, "error": 5.0, "success": 2.0,
        }.get(state, 0.0)
        self._last_tick = time.monotonic()
        if state == "paused":
            self._blink_started = None
            self._blink_opening = 1.0
            self._speech_level = 0.0
            self._target_speech_level = 0.0
        if self._animations_enabled and self.isVisible():
            self._timer.start()
        else:
            self._opening = self._target_opening
            self._mouth_opening = self._target_mouth_opening
        self.update()

    def set_speech_level(self, level: float) -> None:
        """Animate the mouth from speech progress reported by the audio service."""
        self._target_speech_level = max(0.0, min(1.0, float(level)))
        self._last_speech_pulse = time.monotonic()
        if not self._animations_enabled:
            self._speech_level = self._target_speech_level
            self._mouth_opening = max(
                self._target_mouth_opening, self._speech_level * 0.8
            )
        if self._animations_enabled and self.isVisible() and not self._timer.isActive():
            self._last_tick = time.monotonic()
            self._timer.start()
        self.update()

    def set_animations_enabled(self, enabled: bool) -> None:
        self._animations_enabled = bool(enabled)
        if not self._animations_enabled:
            self._timer.stop()
            self._opening = self._target_opening
            self._blink_opening = 1.0
            self._float_offset = 0.0
            self._breath = 0.0
            self._speech_level = self._target_speech_level
            self._mouth_opening = self._target_mouth_opening
        elif self.isVisible():
            self._last_tick = time.monotonic()
            self._timer.start()
        self.update()

    def _tick(self) -> None:
        if not self.isVisible() or not self._animations_enabled:
            self._timer.stop()
            return

        now = time.monotonic()
        dt = min(max(now - self._last_tick, 0.0), 0.12)
        self._last_tick = now
        blend = 1.0 - math.exp(-11.5 * dt)
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
                    self._blink_opening = 1.0 - t * t * (3.0 - 2.0 * t)
                else:
                    t = (progress - 0.46) / 0.54
                    self._blink_opening = t * t * (3.0 - 2.0 * t)

        if self.state in ("idle", "thinking", "working") and now >= self._next_glance:
            targets = (QPointF(-0.10, 0.015), QPointF(0.09, -0.03),
                       QPointF(-0.035, -0.09), QPointF(0.03, 0.025))
            self._gaze_target = random.choice(targets)
            self._next_glance = now + random.uniform(1.8, 3.8)
        self._gaze += (self._gaze_target - self._gaze) * blend
        self._opening += (self._target_opening - self._opening) * blend
        self._phase += dt
        self._wing_offset = math.sin(now * 2.0) * 0.1 if self.state != "paused" else 0.0

        if self.state == "idle":
            self._arm_l_angle = -35 + math.sin(now * 3.0) * 5
            self._arm_r_angle = 35 + math.sin(now * 3.0 + 1.5) * 5
        elif self.state == "thinking":
            self._arm_l_angle, self._arm_r_angle = -20, 20
        elif self.state == "working":
            self._arm_l_angle, self._arm_r_angle = -15, 15
        else:
            self._arm_l_angle, self._arm_r_angle = -35, 35

        if now - self._last_speech_pulse > 0.24:
            self._target_speech_level = 0.0
        self._speech_level += (self._target_speech_level - self._speech_level) * blend
        mouth_target = max(self._target_mouth_opening, self._speech_level * 0.8)
        self._mouth_opening += (mouth_target - self._mouth_opening) * blend
        self._float_offset = math.sin(self._phase * 1.55) * (
            0.25 if self.state == "paused" else 1.5
        )
        self._breath = math.sin(self._phase * 1.25) * (
            0.002 if self.state == "paused" else 0.008
        )
        self.update()
        if (self.state == "paused"
                and abs(self._opening - self._target_opening) < 0.01
                and self._speech_level < 0.03):
            self._timer.stop()

    @staticmethod
    def _stroke(color: QColor, width: float) -> QPen:
        return QPen(color, width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        scale = max(0.01, min((self.width() - 8.0) / 600.0,
                              (self.height() - 8.0) / 720.0))
        painter.translate(self.width() / 2.0,
                          self.height() / 2.0 + self._float_offset)
        painter.scale(scale * (1.0 + self._breath),
                      scale * (1.0 - self._breath * 0.35))
        painter.translate(-300.0, -360.0)

        ink = QColor("#1b1114")
        red = QColor("#d8432d")
        head_red = QColor("#e24b33")
        wing = QColor("#5a2a5c")
        horn = QColor("#f1dfb4")
        steel = QColor("#c3ccd6")
        gold = QColor("#e5a93a")
        grip = QColor("#6b3a2a")

        # Broad scalloped wings sit behind the imp, as in the supplied design.
        for side in (-1, 1):
            painter.save()
            pivot_x = 225.0 if side < 0 else 375.0
            painter.translate(pivot_x, 410.0)
            painter.rotate(self._wing_offset * 30.0 * side)
            painter.translate(-pivot_x, -410.0)
            path = QPainterPath()
            if side < 0:
                path.moveTo(225, 410)
                path.lineTo(45, 165)
                path.quadTo(18, 230, 22, 300)
                path.quadTo(60, 310, 72, 352)
                path.quadTo(115, 350, 135, 392)
                path.quadTo(190, 375, 225, 410)
            else:
                path.moveTo(375, 410)
                path.lineTo(555, 165)
                path.quadTo(582, 230, 578, 300)
                path.quadTo(540, 310, 528, 352)
                path.quadTo(485, 350, 465, 392)
                path.quadTo(410, 375, 375, 410)
            path.closeSubpath()
            painter.setBrush(wing)
            painter.setPen(self._stroke(ink, 8))
            painter.drawPath(path)
            painter.setPen(self._stroke(QColor(30, 17, 20, 155), 3))
            if side < 0:
                veins = ((45, 165, 22, 300), (45, 165, 72, 352),
                         (45, 165, 135, 392))
            else:
                veins = ((555, 165, 578, 300), (555, 165, 528, 352),
                         (555, 165, 465, 392))
            for x1, y1, x2, y2 in veins:
                painter.drawLine(x1, y1, x2, y2)
            painter.restore()

        # Crossed steel swords remain visible behind the round body.
        for angle in (self._arm_l_angle, self._arm_r_angle):
            painter.save()
            painter.translate(300, 470)
            painter.rotate(angle)
            painter.translate(-300, -470)
            blade = QPainterPath()
            blade.moveTo(286, 288)
            blade.lineTo(314, 288)
            blade.lineTo(314, 630)
            blade.lineTo(300, 692)
            blade.lineTo(286, 630)
            blade.closeSubpath()
            painter.setBrush(steel)
            painter.setPen(self._stroke(ink, 7))
            painter.drawPath(blade)
            painter.setPen(self._stroke(gold, 14))
            painter.drawLine(262, 281, 338, 281)
            painter.setPen(self._stroke(grip, 18))
            painter.drawLine(300, 274, 300, 238)
            painter.setPen(self._stroke(ink, 2))
            for y in (247, 257, 267):
                painter.drawLine(292, y, 308, y)
            painter.setBrush(gold)
            painter.setPen(self._stroke(ink, 4))
            painter.drawEllipse(QPointF(300, 226), 14, 14)
            painter.setBrush(red)
            painter.drawEllipse(QPointF(300, 226), 5, 5)
            painter.restore()

        # Feet and shoulders frame the round red body.
        painter.setBrush(QColor("#9e2a22"))
        painter.setPen(self._stroke(ink, 7))
        painter.save()
        painter.translate(205, 664)
        painter.rotate(-10)
        painter.drawEllipse(QRectF(-62, -24, 124, 48))
        painter.restore()
        painter.save()
        painter.translate(400, 664)
        painter.rotate(8)
        painter.drawEllipse(QRectF(-62, -24, 124, 48))
        painter.restore()

        painter.setBrush(red)
        painter.setPen(self._stroke(ink, 8))
        painter.drawEllipse(QPointF(150, 410), 42, 42)
        painter.drawEllipse(QPointF(450, 410), 42, 42)
        painter.drawEllipse(QPointF(300, 500), 155, 150)

        belly = QPainterPath()
        belly.moveTo(222, 498)
        belly.quadTo(300, 478, 384, 494)
        belly.quadTo(372, 590, 302, 594)
        belly.quadTo(232, 590, 222, 498)
        painter.setBrush(QColor("#f6c76b"))
        painter.setPen(self._stroke(ink, 6))
        painter.drawPath(belly)
        painter.setPen(self._stroke(QColor("#b97935"), 3))
        painter.drawLine(235, 498, 365, 498)

        painter.setBrush(red)
        painter.setPen(self._stroke(ink, 7))
        painter.drawEllipse(QRectF(262, 333, 76, 48))

        # The ridged horns and large expressive head define the mascot's face.
        painter.save()
        painter.translate(300, 235)
        painter.rotate(self._head_tilt)
        painter.translate(-300, -235)
        for points in (
            ((232, 172), (178, 150), (184, 90), (188, 55),
             (226, 34), (208, 70), (214, 100), (220, 130), (272, 158)),
            ((368, 172), (422, 150), (416, 90), (412, 55),
             (374, 34), (392, 70), (386, 100), (380, 130), (328, 158)),
        ):
            horn_path = QPainterPath(QPointF(*points[0]))
            horn_path.cubicTo(QPointF(*points[1]), QPointF(*points[2]),
                              QPointF(*points[3]))
            horn_path.cubicTo(QPointF(*points[4]), QPointF(*points[5]),
                              QPointF(*points[6]))
            horn_path.quadTo(QPointF(*points[7]), QPointF(*points[8]))
            horn_path.closeSubpath()
            painter.setBrush(horn)
            painter.setPen(self._stroke(ink, 7))
            painter.drawPath(horn_path)

        painter.setBrush(head_red)
        painter.setPen(self._stroke(ink, 8))
        painter.drawEllipse(QPointF(300, 235), 92, 92)
        painter.setBrush(Qt.NoBrush)
        painter.setPen(self._stroke(QColor(255, 235, 220, 100), 3))
        painter.drawEllipse(QPointF(303, 238), 87, 87)

        opening = max(0.08, self._opening * self._blink_opening)
        eye_rx, eye_ry = {
            "thinking": (16, 23), "working": (17, 24),
            "error": (17, 25), "paused": (18, 13),
        }.get(self.state, (19, 29))
        for ex in (262, 338):
            eye = QRectF(ex - eye_rx, 228 - eye_ry * opening,
                         eye_rx * 2, eye_ry * 2 * opening)
            painter.setBrush(QColor("#fffaf3"))
            painter.setPen(self._stroke(ink, 5))
            painter.drawEllipse(eye)
            pupil_w = min(13.0, eye.width() * 0.52)
            pupil_h = min(19.0, eye.height() * 0.67)
            px = ex + self._gaze.x() * 18
            py = 228 + self._gaze.y() * 22
            px = max(eye.left() + pupil_w / 2 + 2,
                     min(eye.right() - pupil_w / 2 - 2, px))
            py = max(eye.top() + pupil_h / 2 + 2,
                     min(eye.bottom() - pupil_h / 2 - 2, py))
            painter.setBrush(QColor("#24191a"))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(QRectF(px - pupil_w / 2, py - pupil_h / 2,
                                       pupil_w, pupil_h))
            painter.setBrush(QColor("#ffffff"))
            painter.drawEllipse(QPointF(px - 2, py - 3), 2.5, 2.5)

        brow_pen = self._stroke(ink, 6)
        for side in (-1, 1):
            ex = 262 if side < 0 else 338
            brow = QPainterPath(QPointF(ex - 24, 194))
            if self.state == "error":
                brow.cubicTo(ex - 8, 194, ex + 8, 208, ex + 24, 210)
            elif self.state == "thinking" and side == 1:
                brow.cubicTo(ex - 8, 177, ex + 8, 177, ex + 24, 194)
            else:
                brow.cubicTo(ex - 8, 181, ex + 8, 181, ex + 24, 194)
            painter.setPen(brow_pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(brow)

        mouth = QPainterPath()
        mouth_y = 292
        if self._mouth_opening > 0.12 or self.state in ("speaking", "success"):
            mouth_h = 8 + self._mouth_opening * 42
            painter.setBrush(QColor("#24191a"))
            painter.setPen(self._stroke(ink, 5))
            painter.drawEllipse(QRectF(300 - 18, mouth_y - mouth_h / 2,
                                       36, mouth_h))
            if self._mouth_opening > 0.35:
                painter.setBrush(QColor("#fff3dc"))
                painter.setPen(Qt.NoPen)
                painter.drawEllipse(QRectF(289, mouth_y + mouth_h * 0.12,
                                           22, 5))
        else:
            mouth.moveTo(254, mouth_y)
            if self.state == "error":
                mouth.cubicTo(280, 270, 320, 270, 346, mouth_y)
            elif self.state == "thinking":
                mouth.cubicTo(278, mouth_y - 4, 322, mouth_y - 4, 346, mouth_y)
            else:
                mouth.cubicTo(278, 321, 322, 321, 346, mouth_y)
            painter.setPen(self._stroke(ink, 7))
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(mouth)
        painter.restore()
        painter.end()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._animations_enabled and self.state != "paused":
            self._last_tick = time.monotonic()
            self._timer.start()

    def hideEvent(self, event) -> None:
        self._timer.stop()
        super().hideEvent(event)

    def mousePressEvent(self, event) -> None:
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        event.accept()
