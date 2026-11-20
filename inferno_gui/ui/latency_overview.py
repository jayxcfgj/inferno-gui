"""Latency Overview bar: configured Inferno latency + estimated PipeWire share.

``LatencyBar`` is a custom-painted QWidget: ``paintEvent`` draws a
stacked bar whose segment widths follow the millisecond shares —
green for the configured Inferno RX latency, the app's blue for the
estimated PipeWire graph round trip.  A minimum-width floor keeps
tiny-but-positive shares visible, and degenerate zero values never
reach a division.  Below the painted strip the widget carries the
total line ("Total ≈ X ms (Inferno X + PipeWire ≈ Y)" — or
"(PipeWire: unknown)" when PipeWire cannot answer) and an
"estimated" hint.

Colors follow the settings tab palette: green #4caf50 (status OK),
blue #2196F3 (the app's existing blue), amber #ffc107 for the
unknown hint, gray #aaa for informational hints, dark track #3d3d3d.
"""

from PyQt6.QtCore import QRect, Qt
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

_INFERNO_COLOR = QColor("#4caf50")   # settings tab green (status OK)
_PIPEWIRE_COLOR = QColor("#2196F3")  # the app's existing blue
_TRACK_COLOR = QColor("#3d3d3d")     # dark groove behind the segments
_LABEL_COLOR = QColor("#ffffff")

# Tiny-but-positive shares are floored to this painted width so they
# stay visible (e.g. 10 vs 0.5 ms on a narrow bar).
_MIN_SEGMENT_PX = 8
_STRIP_H = 16


class LatencyBar(QWidget):
    """Stacked latency bar with the total text below.

    The Inferno segment is fed the configured RX latency (the network
    receive direction is the end-to-end path the user hears); the
    PipeWire segment is fed the estimated graph round trip from
    ``read_pipewire_latency``.  ``pipewire_ms=None`` paints no PipeWire
    segment and the texts say "unknown".
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._inferno_ms = 0.0
        self._pw_ms = None
        # Segment fractions of the total milliseconds (attributes per
        # the contract, for assertion; painted widths add a floor, see
        # segment_widths()).
        self.inferno_fraction = 0.0
        self.pipewire_fraction = 0.0

        self._total_label = QLabel("—")
        self._hint_label = QLabel("estimated")
        self._hint_label.setStyleSheet("color: #aaa; font-size: 11px;")

        # The painted strip occupies the top _STRIP_H pixels, reserved
        # via the layout's top margin; the labels sit below it.
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, _STRIP_H + 6, 0, 0)
        lay.setSpacing(2)
        lay.addWidget(self._total_label)
        lay.addWidget(self._hint_label)

    # ── public contract ───────────────────────────────────────

    def set_values(self, inferno_ms: float, pipewire_ms: float | None) -> None:
        """Update the bar.

        ``pipewire_ms=None`` → no PipeWire segment, total line and hint
        say "unknown".  Non-positive values paint no segment of their
        own.
        """
        self._inferno_ms = float(inferno_ms or 0.0)
        self._pw_ms = None if pipewire_ms is None else float(pipewire_ms)
        self._update_fractions()
        self._update_texts()
        self.update()  # schedule a repaint of the strip

    def total_text(self) -> str:
        """The total line shown below the bar."""
        return self._total_label.text()

    def hint_text(self) -> str:
        """The "estimated" hint line shown below the total."""
        return self._hint_label.text()

    def segment_widths(self, width: int) -> tuple:
        """Painted pixel widths (inferno, pipewire) at the given bar width.

        Proportional to the millisecond shares, with a minimum-width
        floor so tiny-but-positive shares stay visible; degenerate
        zero/absent values paint nothing and never divide by zero.
        """
        width = max(int(width), 0)
        inf = self._inferno_ms
        pw = self._pw_ms
        has_inf = inf > 0
        has_pw = pw is not None and pw > 0
        if not has_inf and not has_pw:
            return 0, 0
        if not has_pw:
            return width, 0
        if not has_inf:
            return 0, width
        total = inf + pw
        if total <= 0:
            return 0, 0  # defensive: no division by zero

        iw = int(round(width * inf / total))
        pw_px = width - iw
        # Floor both segments, unless the bar is too narrow to give
        # each its floor.
        if width >= 2 * _MIN_SEGMENT_PX:
            if iw < _MIN_SEGMENT_PX:
                iw, pw_px = _MIN_SEGMENT_PX, width - _MIN_SEGMENT_PX
            elif pw_px < _MIN_SEGMENT_PX:
                pw_px, iw = _MIN_SEGMENT_PX, width - _MIN_SEGMENT_PX
        return iw, pw_px

    # ── painting ──────────────────────────────────────────────

    def paintEvent(self, event):
        """Draw the stacked strip: dark track, green Inferno share,
        blue PipeWire share, segment labels when they fit."""
        painter = QPainter(self)
        width = self.width()
        strip = QRect(0, 0, width, _STRIP_H)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_TRACK_COLOR)
        painter.drawRect(strip)

        inf_px, pw_px = self.segment_widths(width)
        if inf_px > 0:
            painter.setBrush(_INFERNO_COLOR)
            painter.drawRect(QRect(0, 0, inf_px, _STRIP_H))
        if pw_px > 0:
            painter.setBrush(_PIPEWIRE_COLOR)
            painter.drawRect(QRect(inf_px, 0, pw_px, _STRIP_H))

        self._draw_segment_label(
            painter, QRect(0, 0, inf_px, _STRIP_H), "Inferno RX")
        self._draw_segment_label(
            painter, QRect(inf_px, 0, pw_px, _STRIP_H), "PipeWire")
        painter.end()

    def _draw_segment_label(self, painter, rect, text):
        """Center `text` in the segment rect, only when it fits."""
        if rect.width() <= 0:
            return
        if rect.width() < painter.fontMetrics().horizontalAdvance(text) + 8:
            return
        painter.setPen(_LABEL_COLOR)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

    # ── internals ──────────────────────────────────────────────

    def _update_fractions(self):
        inf, pw = self._inferno_ms, self._pw_ms
        has_inf = inf > 0
        has_pw = pw is not None and pw > 0
        if has_inf and has_pw:
            total = inf + pw
            self.inferno_fraction = inf / total
            self.pipewire_fraction = pw / total
        elif has_inf:
            self.inferno_fraction, self.pipewire_fraction = 1.0, 0.0
        elif has_pw:
            self.inferno_fraction, self.pipewire_fraction = 0.0, 1.0
        else:
            self.inferno_fraction, self.pipewire_fraction = 0.0, 0.0

    def _update_texts(self):
        inf = self._inferno_ms
        if self._pw_ms is None:
            self._total_label.setText(
                f"Total ≈ {inf:.1f} ms (Inferno {inf:.1f} + PipeWire: unknown)")
            self._hint_label.setText(
                "estimated — PipeWire: unknown (is PipeWire running?)")
            # Amber, like the tab's other "cannot answer" states.
            self._hint_label.setStyleSheet(
                "color: #ffc107; font-size: 11px;")
        else:
            total = inf + self._pw_ms
            self._total_label.setText(
                f"Total ≈ {total:.1f} ms "
                f"(Inferno {inf:.1f} + PipeWire ≈ {self._pw_ms:.1f})")
            self._hint_label.setText(
                "estimated — PipeWire share from the current quantum")
            self._hint_label.setStyleSheet(
                "color: #aaa; font-size: 11px;")
