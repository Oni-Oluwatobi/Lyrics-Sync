"""Shared UI building blocks: glyphs, buttons, chips, empty states, layout."""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QPoint, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QStyle,
    QStyleOptionButton,
    QVBoxLayout,
    QWidget,
)

from lyric_sync.app import theme as theme_module
from lyric_sync.app.theme import PAGE_MAX_WIDTH, PAGE_MIN_WIDTH, PAGE_WIDTH_RATIO, SP_SM

# Colour-role aliases accepted by GlyphLabel / glyph_icon so call sites can
# use readable names ("muted") while the palette keeps its canonical fields.
_ROLE_ALIASES = {
    "muted": "text_muted",
    "dim": "text_dim",
    "text": "text",
    "accent": "accent",
    "yellow": "yellow",
    "ok": "ok",
    "danger": "danger",
    "on_accent": "on_accent",
    "text_muted": "text_muted",
    "text_dim": "text_dim",
}


def palette_color(palette, role: str) -> QColor:
    """Resolve a (possibly aliased) colour role against a palette."""
    field = _ROLE_ALIASES.get(role, role)
    value = getattr(palette, field, palette.text)
    return QColor(value)


class GlyphLabel(QLabel):
    """Tiny vector icon painted with Qt — no emoji, no image assets."""

    def __init__(self, glyph: str = "", size: int = 18, color: str = "text",
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._glyph = glyph
        self._size = size
        self._color_role = color
        self.setFixedSize(size, size)
        self.setAlignment(Qt.AlignCenter)

    def set_glyph(self, glyph: str) -> None:
        self._glyph = glyph
        self.update()

    def set_color(self, role: str) -> None:
        self._color_role = role
        self.update()

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(self._size, self._size)

    def _color(self) -> QColor:
        palette = theme_module.resolve_palette(
            self.property("tkgMode") or _app_mode()
        )
        return palette_color(palette, self._color_role)

    def paintEvent(self, event) -> None:  # noqa: N802
        if not self._glyph:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        pen = QPen(self._color())
        pen.setWidthF(max(1.4, self._size * 0.09))
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        _draw_glyph(painter, self._glyph, self.rect(), pen)


def _app_mode() -> str:
    app = theme_module.QApplication.instance()
    if app is not None and app.property("tkgMode"):
        return str(app.property("tkgMode"))
    return "dark"


def _draw_glyph(painter: QPainter, glyph: str, rect, pen: QPen) -> None:
    w = rect.width()
    h = rect.height()
    unit = min(w, h)
    left, top = rect.left(), rect.top()

    def pt(fx: float, fy: float) -> QPoint:
        return QPoint(int(left + fx * unit), int(top + fy * unit))

    if glyph == "search":
        radius = unit * 0.30
        center = pt(0.44, 0.44)
        painter.drawEllipse(center, radius, radius)
        painter.drawLine(pt(0.66, 0.66), pt(0.88, 0.88))
    elif glyph == "chevron":
        painter.drawPolyline(QPolygonF([pt(0.40, 0.20), pt(0.70, 0.50), pt(0.40, 0.80)]))
    elif glyph == "back":
        painter.drawPolyline(QPolygonF([pt(0.60, 0.20), pt(0.30, 0.50), pt(0.60, 0.80)]))
    elif glyph == "close":
        painter.drawLine(pt(0.28, 0.28), pt(0.72, 0.72))
        painter.drawLine(pt(0.72, 0.28), pt(0.28, 0.72))
    elif glyph == "check":
        painter.drawPolyline(QPolygonF([pt(0.22, 0.52), pt(0.42, 0.72), pt(0.78, 0.30)]))
    elif glyph in ("star", "star_outline"):
        path = QPainterPath()
        points: list[QPointF] = []
        for index in range(10):
            angle = -math.pi / 2 + index * math.pi / 5
            radius = 0.44 if index % 2 == 0 else 0.19
            points.append(
                QPointF(left + unit * (0.5 + radius * math.cos(angle)),
                        top + unit * (0.5 + radius * math.sin(angle)))
            )
        path.moveTo(points[0])
        for point in points[1:]:
            path.lineTo(point)
        path.closeSubpath()
        if glyph == "star":
            painter.fillPath(path, pen.color())
        else:
            painter.drawPath(path)
    elif glyph == "gear":
        painter.drawEllipse(pt(0.5, 0.5), int(unit * 0.22), int(unit * 0.22))
        for index in range(8):
            angle = index * math.pi / 4
            x0 = 0.5 + 0.30 * math.cos(angle)
            y0 = 0.5 + 0.30 * math.sin(angle)
            x1 = 0.5 + 0.44 * math.cos(angle)
            y1 = 0.5 + 0.44 * math.sin(angle)
            painter.drawLine(pt(x0, y0), pt(x1, y1))
    elif glyph == "database":
        oval = QRectF(left + unit * 0.14, top + unit * 0.14, unit * 0.72, unit * 0.28)
        painter.drawEllipse(oval)
        painter.drawLine(QPoint(int(oval.left()), int(oval.center().y())),
                         QPoint(int(oval.left()), int(top + unit * 0.76)))
        painter.drawLine(QPoint(int(oval.right()), int(oval.center().y())),
                         QPoint(int(oval.right()), int(top + unit * 0.76)))
        painter.drawArc(QRectF(oval.left(), top + unit * 0.50, oval.width(), oval.height()),
                        0, 180 * 16)
        painter.drawArc(QRectF(oval.left(), top + unit * 0.62, oval.width(), oval.height()),
                        0, 180 * 16)
    elif glyph == "trash":
        painter.drawLine(pt(0.20, 0.28), pt(0.80, 0.28))
        painter.drawLine(pt(0.40, 0.28), pt(0.44, 0.18))
        painter.drawLine(pt(0.44, 0.18), pt(0.56, 0.18))
        painter.drawLine(pt(0.56, 0.18), pt(0.60, 0.28))
        body = QPolygonF([pt(0.28, 0.28), pt(0.34, 0.84), pt(0.66, 0.84), pt(0.72, 0.28)])
        painter.drawPolygon(body)
        painter.drawLine(pt(0.44, 0.40), pt(0.46, 0.74))
        painter.drawLine(pt(0.56, 0.40), pt(0.54, 0.74))
    elif glyph == "info":
        painter.drawEllipse(pt(0.5, 0.5), int(unit * 0.40), int(unit * 0.40))
        painter.drawLine(pt(0.5, 0.44), pt(0.5, 0.70))
        painter.drawPoint(pt(0.5, 0.30))
    elif glyph == "clock":
        painter.drawEllipse(pt(0.5, 0.5), int(unit * 0.40), int(unit * 0.40))
        painter.drawLine(pt(0.5, 0.5), pt(0.5, 0.26))
        painter.drawLine(pt(0.5, 0.5), pt(0.68, 0.58))
    elif glyph == "grid":
        for row in range(2):
            for col in range(2):
                x = left + unit * (0.18 + col * 0.36)
                y = top + unit * (0.18 + row * 0.36)
                painter.drawRect(QRectF(x, y, unit * 0.28, unit * 0.28))
    else:
        return


def glyph_icon(glyph: str, size: int = 16, color: str = "text_muted") -> QIcon:
    """A ``QIcon`` painted from the built-in glyph set (no image assets)."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    palette = theme_module.resolve_palette(_app_mode())
    pen = QPen(palette_color(palette, color))
    pen.setWidthF(max(1.4, size * 0.09))
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    _draw_glyph(painter, glyph, pixmap.rect(), pen)
    painter.end()
    return QIcon(pixmap)


class GlyphCheckBox(QCheckBox):
    """Checkbox that paints the built-in check glyph over its styled indicator.

    Qt stylesheet indicators have no check mark of their own, so the checked
    state would render as a plain filled square.
    """

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        if self.checkState() != Qt.Checked or not self.isEnabled():
            return
        option = QStyleOptionButton()
        option.initFrom(self)
        indicator = self.style().subElementRect(QStyle.SE_CheckBoxIndicator, option, self)
        if indicator.isEmpty():
            return
        palette = theme_module.resolve_palette(self.property("tkgMode") or _app_mode())
        color = palette_color(palette, "on_accent")
        pen = QPen(color)
        pen.setWidthF(1.7)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        _draw_glyph(painter, "check", indicator.adjusted(3, 3, -3, -3), pen)


class Switch(QCheckBox):
    """Pill toggle used where a checkbox would read as a form control.

    Painted (not styled through QSS) so the handle, track and focus states
    stay consistent across platforms.  Emits ``toggled`` like QCheckBox.
    """

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setFixedSize(44, 24)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet("QCheckBox { spacing: 0px; } QCheckBox::indicator { width: 0px; height: 0px; }")

    def hitButton(self, pos) -> bool:  # noqa: N802
        return self.rect().contains(pos)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        palette = theme_module.resolve_palette(self.property("tkgMode") or _app_mode())
        enabled = self.isEnabled()
        checked = self.isChecked()
        hovered = self.underMouse()

        track = QRectF(1, 1, 42, 22)
        radius = 11.0
        if checked:
            track_color = QColor(palette.accent) if enabled else QColor(palette.border_strong)
        else:
            track_color = QColor(palette.surface_alt if enabled else palette.border)
        pen_color = QColor(palette.border_strong) if enabled and not checked else track_color
        painter.setPen(QPen(pen_color, 1))
        painter.setBrush(track_color)
        painter.drawRoundedRect(track, radius, radius)

        handle_radius = 8.0
        cy = track.center().y()
        if checked:
            cx = track.right() - handle_radius - 3
            handle_color = QColor("#FFFFFF")
        else:
            cx = track.left() + handle_radius + 3
            handle_color = QColor(palette.text_muted if enabled else palette.text_dim)
        if hovered and enabled:
            handle_color = handle_color.lighter(115)
        painter.setPen(Qt.NoPen)
        painter.setBrush(handle_color)
        painter.drawEllipse(QPointF(cx, cy), handle_radius, handle_radius)
        painter.end()


def icon_text_button(
    glyph: str,
    text: str,
    variant: str = "ghost",
    parent: QWidget | None = None,
) -> QPushButton:
    """A button with a painted glyph and text.

    Built from QPushButton's native icon + text (not a child layout) so the
    size hint always reflects the real content — hand-rolled layouts inside
    ``QPushButton`` size to the empty-text hint and clip their content.
    """
    button = QPushButton(text, parent)
    button.setProperty("variant", variant)
    button.setCursor(Qt.PointingHandCursor)
    button.setIcon(glyph_icon(glyph, 15, "text_muted"))
    button.setIconSize(QSize(15, 15))
    button._glyph = glyph  # type: ignore[attr-defined]  # kept for state resync
    return button


class BackButton(QPushButton):
    """The single back navigation control used by every page."""

    def __init__(self, label: str = "Back", parent: QWidget | None = None) -> None:
        super().__init__(label, parent)
        self.setProperty("variant", "ghost")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(36)
        self.setIcon(glyph_icon("back", 15, "text_muted"))
        self.setIconSize(QSize(15, 15))


class CenterColumn(QFrame):
    """Shared centred content column.

    Every page lays out ``stretch | CenterColumn | stretch`` and calls
    :meth:`sync_width` from its ``resizeEvent`` — one place decides the content
    width envelope instead of six divergent per-page formulas.
    """

    def __init__(
        self,
        min_width: int = PAGE_MIN_WIDTH,
        max_width: int = PAGE_MAX_WIDTH,
        ratio: float = PAGE_WIDTH_RATIO,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._min_width = min_width
        self._max_width = max_width
        self._ratio = ratio

    def sync_width(self, page_width: int) -> None:
        width = max(self._min_width, min(self._max_width, int(page_width * self._ratio)))
        if width != self.width():
            self.setFixedWidth(width)


class Chip(QLabel):
    """Small status / match label."""

    def __init__(self, text: str = "", kind: str = "meta",
                 parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setProperty("kind", kind)

    def set_kind(self, kind: str) -> None:
        self.setProperty("kind", kind)
        self.style().unpolish(self)
        self.style().polish(self)

    def set_text(self, text: str) -> None:  # noqa: D102
        super().setText(text)


class Divider(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("divider")
        self.setFixedHeight(1)


class SectionTitle(QLabel):
    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text.upper(), parent)
        self.setProperty("role", "section")


class MetricCard(QFrame):
    """One telemetry tile (database info page, home glance)."""

    def __init__(self, label: str = "", value: str = "",
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("panel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(SP_SM)

        self.value_label = QLabel(value)
        self.value_label.setProperty("role", "metricValue")
        self.value_label.setWordWrap(True)
        layout.addWidget(self.value_label)

        self.caption_label = QLabel(label.upper())
        self.caption_label.setProperty("role", "metricLabel")
        self.caption_label.setWordWrap(True)
        layout.addWidget(self.caption_label)

    def set_metric(self, value: str, label: str = "") -> None:
        self.value_label.setText(value)
        if label:
            self.caption_label.setText(label.upper())


class ChipFlow(QWidget):
    """Wrapping row of chip widgets (recent searches, filters).

    Qt has no flow layout in the standard library; this packs children
    greedily into rows on resize so the strip never needs a scrollbar.

    Re-entrancy: ``setFixedHeight`` inside a reflow fires ``resizeEvent``
    which would re-enter ``_reflow`` while holders are mid-teardown.  A
    guard collapses nested calls into one trailing pass instead.
    """

    def __init__(self, gap: int = SP_SM, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._gap = gap
        self._chips: list[QWidget] = []
        self._holders: list[QWidget] = []
        self._reflowing = False
        self._reflow_pending = False
        self._rows_layout = QVBoxLayout(self)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(gap)
        self._rows_layout.addStretch(1)

    def add_chip(self, chip: QWidget) -> None:
        self._chips.append(chip)
        self._reflow()

    def clear_chips(self) -> None:
        # Detach chips before deleting holders: Qt would cascade-delete
        # holder children, leaving stale wrappers that a resize-driven
        # reflow could touch before the deferred delete runs.
        for chip in self._chips:
            try:
                chip.setParent(None)
                chip.deleteLater()
            except RuntimeError:
                pass  # C++ object already gone
        self._chips.clear()
        self._discard_holders()
        self._rows_layout.addStretch(1)
        self.setFixedHeight(0)

    def chips(self) -> list[QWidget]:
        return list(self._chips)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._reflow()

    def _discard_holders(self) -> None:
        for holder in self._holders:
            try:
                holder.setParent(None)
                holder.deleteLater()
            except RuntimeError:
                pass
        self._holders.clear()
        while self._rows_layout.count():
            item = self._rows_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                try:
                    widget.setParent(None)
                    widget.deleteLater()
                except RuntimeError:
                    pass

    def _reflow(self) -> None:
        if self._reflowing:
            self._reflow_pending = True
            return
        self._reflowing = True
        try:
            while True:
                self._reflow_pending = False
                self._reflow_once()
                if not self._reflow_pending:
                    break
        finally:
            self._reflowing = False

    def _alive_chips(self) -> list[QWidget]:
        from shiboken6 import isValid

        alive = []
        for chip in self._chips:
            try:
                if isValid(chip):
                    alive.append(chip)
            except RuntimeError:
                pass  # wrapper already torn down
        if len(alive) != len(self._chips):
            self._chips = alive
        return alive

    def _reflow_once(self) -> None:
        chips = self._alive_chips()
        for chip in chips:
            try:
                chip.setParent(None)
            except RuntimeError:
                pass
        self._discard_holders()

        for chip in chips:
            chip.setParent(self)

        available = max(120, self.width())
        rows: list[list[QWidget]] = []
        current: list[QWidget] = []
        current_width = 0
        for chip in chips:
            hint = chip.sizeHint().width()
            if current and current_width + self._gap + hint > available:
                rows.append(current)
                current = []
                current_width = 0
            current.append(chip)
            current_width += hint + (self._gap if len(current) > 1 else 0)
        if current:
            rows.append(current)

        chip_height = chips[0].sizeHint().height() if chips else 0
        for row in rows:
            line = QHBoxLayout()
            line.setContentsMargins(0, 0, 0, 0)
            line.setSpacing(self._gap)
            for chip in row:
                line.addWidget(chip)
            line.addStretch(1)
            holder = QWidget()
            holder.setLayout(line)
            self._holders.append(holder)
            self._rows_layout.addWidget(holder)
            holder.setFixedHeight(chip_height)
        self._rows_layout.addStretch(1)

        if rows:
            self.setFixedHeight(len(rows) * chip_height + (len(rows) - 1) * self._gap)
        else:
            self.setFixedHeight(0)


class EmptyState(QFrame):
    """Polished empty / unavailable state with optional action buttons."""

    action_requested = Signal()

    def __init__(
        self,
        title: str,
        body: str = "",
        glyph: str = "search",
        action_label: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("panelFlat")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(32, 36, 32, 36)
        self._layout.setSpacing(8)
        self._layout.setAlignment(Qt.AlignCenter)

        icon = GlyphLabel(glyph, size=34, color="accent")
        icon.setStyleSheet("background: transparent;")
        self._layout.addWidget(icon, 0, Qt.AlignHCenter)

        self.title_label = QLabel(title)
        self.title_label.setProperty("role", "emptyTitle")
        self.title_label.setAlignment(Qt.AlignCenter)
        self._layout.addWidget(self.title_label)

        self.body_label: QLabel | None = None
        if body:
            self.body_label = QLabel(body)
            self.body_label.setProperty("role", "emptyBody")
            self.body_label.setAlignment(Qt.AlignCenter)
            self.body_label.setWordWrap(True)
            self._layout.addWidget(self.body_label)

        self._actions = QHBoxLayout()
        self._actions.setSpacing(8)
        self._actions.setAlignment(Qt.AlignCenter)
        self._layout.addLayout(self._actions)

        if action_label:
            self.add_action(action_label, self.action_requested)

    def add_suggestion(self, text: str) -> None:
        """One actionable hint shown under the body copy."""
        tip = QLabel("•  " + text)
        tip.setProperty("role", "emptyBody")
        tip.setAlignment(Qt.AlignLeft)
        tip.setWordWrap(True)
        tip.setMaximumWidth(420)
        self._layout.insertWidget(self._layout.count() - 1, tip, 0, Qt.AlignHCenter)

    def add_action(self, label: str, signal: Signal | None = None) -> QPushButton:
        """Append a secondary action button; returns it for custom wiring."""
        button = QPushButton(label)
        button.setProperty("variant", "secondary")
        button.setCursor(Qt.PointingHandCursor)
        target = signal if signal is not None else self.action_requested
        button.clicked.connect(target.emit)
        self._actions.addWidget(button)
        return button

    def set_message(self, title: str, body: str = "") -> None:
        self.title_label.setText(title)
        if self.body_label is None:
            return
        self.body_label.setText(body)


class BusyBar(QProgressBar):
    """Subtle indeterminate progress line."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setRange(0, 0)
        self.setTextVisible(False)
        self.setFixedHeight(2)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.hide()
