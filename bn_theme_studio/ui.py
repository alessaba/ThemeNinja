from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from binaryninja import log_error, log_info, log_warn, user_directory
from binaryninja.enums import ThemeColor
from binaryninjaui import (
	Menu,
	Sidebar,
	SidebarContextSensitivity,
	SidebarWidget,
	SidebarWidgetLocation,
	SidebarWidgetType,
	UIAction,
	UIActionHandler,
	WidgetPane,
	getActiveTheme,
	getAvailableThemes,
	getThemeColor,
	refreshUserThemes,
	setActiveTheme,
)
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFontDatabase, QImage, QPainter, QPalette, QPen
from PySide6.QtWidgets import (
	QAbstractItemView,
	QApplication,
	QColorDialog,
	QComboBox,
	QHeaderView,
	QHBoxLayout,
	QInputDialog,
	QLabel,
	QLineEdit,
	QListWidget,
	QListWidgetItem,
	QMessageBox,
	QPushButton,
	QSizePolicy,
	QSplitter,
	QTableWidget,
	QTableWidgetItem,
	QVBoxLayout,
	QWidget,
)

from .theme_store import (
	ALL_KNOWN_THEME_COLORS,
	PREVIEW_FILE_NAME,
	PREVIEW_THEME_NAME,
	THEME_COLOR_GROUPS,
	ThemeRecord,
	create_new_theme,
	discover_themes,
	display_value,
	duplicate_theme,
	pretty_key,
	primary_theme_directory,
	remove_entry,
	resolve_color_value,
	resolve_entry,
	set_entry_color,
	tuple_to_hex,
	update_entry_from_text,
	write_theme_file,
)


def _qcolor(color: tuple[int, int, int, int] | None, fallback: str = "#000000") -> QColor:
	if color is None:
		return QColor(fallback)
	return QColor(color[0], color[1], color[2], color[3])


def _contrast_text(color: QColor) -> QColor:
	luminance = (0.299 * color.red() + 0.587 * color.green() + 0.114 * color.blue())
	return QColor("#0d1117") if luminance > 155 else QColor("#f5f7fb")


def _css_color(color: QColor) -> str:
	return f"rgba({color.red()}, {color.green()}, {color.blue()}, {color.alpha() / 255:.3f})"


def _qcolor_to_tuple(color: QColor) -> tuple[int, int, int, int]:
	return color.red(), color.green(), color.blue(), color.alpha()


def _qcolor_to_hex(color: QColor) -> str:
	return tuple_to_hex(_qcolor_to_tuple(color), include_alpha=color.alpha() != 255)


def _theme_color_key(color: ThemeColor) -> str:
	name = color.name
	return name[:1].lower() + name[1:]


def _set_active_theme(name: str, persist: bool) -> None:
	try:
		setActiveTheme(name, persist)
	except TypeError:
		setActiveTheme(name)


def _active_theme_name() -> str:
	try:
		return str(getActiveTheme())
	except Exception:
		return ""


def _refresh_runtime_themes() -> None:
	try:
		refreshUserThemes()
	except Exception as exc:
		log_warn(f"Theme Ninja could not refresh Binary Ninja themes: {exc}")


def _theme_group_for_key(key: str) -> str:
	for group, keys in THEME_COLOR_GROUPS.items():
		if key in keys:
			return group
	return "Theme Colors"


class ColorSwatch(QWidget):
	def __init__(self, color: QColor, parent: QWidget | None = None):
		QWidget.__init__(self, parent)
		self._color = QColor(color)
		self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
		self.setMinimumWidth(28)
		self.setToolTip(color.name(QColor.NameFormat.HexArgb if color.alpha() < 255 else QColor.NameFormat.HexRgb))

	def paintEvent(self, event) -> None:  # noqa: N802 - Qt override
		painter = QPainter(self)
		painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
		rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
		if self._color.alpha() < 255:
			tile = 5
			for y in range(int(rect.top()), int(rect.bottom()), tile):
				for x in range(int(rect.left()), int(rect.right()), tile):
					check = ((x // tile) + (y // tile)) % 2
					painter.fillRect(x, y, tile, tile, QColor("#d7dde8" if check else "#5b6470"))
		painter.setPen(Qt.PenStyle.NoPen)
		painter.setBrush(self._color)
		painter.drawRoundedRect(rect, 3, 3)
		painter.setPen(QPen(QColor(0, 0, 0, 115), 1))
		painter.setBrush(Qt.BrushStyle.NoBrush)
		painter.drawRoundedRect(rect, 3, 3)
		painter.end()


class ColorValueLabel(QLabel):
	def __init__(self, text: str, color: QColor, parent: QWidget | None = None):
		QLabel.__init__(self, text, parent)
		self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
		self.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
		self.setMinimumWidth(86)
		self.setStyleSheet(
			f"color: {_css_color(color)}; background: transparent; padding-right: 8px; "
			"font-family: Menlo, Monaco, Consolas, monospace;"
		)


class ThemePreview(QWidget):
	def __init__(self, parent: QWidget | None = None):
		QWidget.__init__(self, parent)
		self._theme: dict[str, Any] | None = None
		self.setMinimumHeight(220)
		self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

	def set_theme(self, theme: dict[str, Any] | None) -> None:
		self._theme = theme
		self.update()

	def _palette_color(self, name: str, fallback: str) -> QColor:
		if not self._theme:
			return QColor(fallback)
		color = resolve_entry(self._theme, "palette", name)
		return _qcolor(color, fallback)

	def _theme_color(self, name: str, fallback: str) -> QColor:
		if not self._theme:
			return QColor(fallback)
		color = resolve_entry(self._theme, "theme-colors", name)
		return _qcolor(color, fallback)

	def _alias_color(self, name: str, fallback: str) -> QColor:
		if not self._theme:
			return QColor(fallback)
		colors = self._theme.get("colors", {})
		if isinstance(colors, dict) and name in colors:
			return _qcolor(resolve_color_value(colors[name], self._theme), fallback)
		return QColor(fallback)

	def _soft_border(self, reference: QColor, alpha: int = 72) -> QColor:
		color = QColor(reference)
		color.setAlpha(alpha)
		return color

	def _panel_fill(self, preferred: str, fallback: QColor) -> QColor:
		color = self._theme_color(preferred, fallback.name())
		if not color.isValid():
			return fallback
		return color

	def paintEvent(self, event) -> None:  # noqa: N802 - Qt override
		painter = QPainter(self)
		painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
		rect = self.rect()
		window = self._palette_color("Window", "#15171c")
		text = self._palette_color("WindowText", "#d7dde8")
		base = self._palette_color("Base", "#1d2129")
		alt = self._palette_color("AlternateBase", "#252a34")
		selection = self._theme_color("selectionColor", "#334a66")

		painter.fillRect(rect, window)
		if not self._theme:
			painter.setPen(text)
			painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "Select a theme to preview it")
			painter.end()
			return

		margin = 10
		tab_h = 34
		status_h = 22
		content = rect.adjusted(margin, margin, -margin, -margin)
		border = self._soft_border(text)
		name = str(self._theme.get("name", "Theme Preview"))

		painter.setPen(Qt.PenStyle.NoPen)
		painter.setBrush(base)
		painter.drawRoundedRect(content, 6, 6)

		tabbar = QRectF(content.left(), content.top(), content.width(), tab_h)
		self._draw_tab_bar(painter, tabbar, base, alt, text, border, name)
		painter.setPen(QPen(border, 1))
		painter.drawLine(tabbar.bottomLeft(), tabbar.bottomRight())

		sidebar_w = 42
		rightbar_w = 34
		sidebar = QRectF(content.left(), tabbar.bottom(), sidebar_w, content.height() - tab_h - status_h)
		self._draw_sidebar(painter, sidebar, base, selection)
		rightbar = QRectF(content.right() - rightbar_w, tabbar.bottom(), rightbar_w, content.height() - tab_h - status_h)
		self._draw_right_sidebar(painter, rightbar, base, selection)

		status = QRectF(content.left(), content.bottom() - status_h, content.width(), status_h)
		self._draw_status_bar(painter, status, base, text, border)

		body = QRectF(sidebar.right(), tabbar.bottom(), rightbar.left() - sidebar.right(), content.height() - tab_h - status_h)
		body = body.adjusted(10, 10, -10, -10)
		gap = 10
		right_w = max(170, min(280, body.width() * 0.26))
		left_w = max(260, body.width() - right_w - gap)
		code_rect = QRectF(body.left(), body.top(), left_w, body.height())
		right_rect = QRectF(code_rect.right() + gap, body.top(), max(0, body.right() - code_rect.right() - gap), body.height())
		map_rect = QRectF(right_rect.left(), right_rect.top(), right_rect.width(), max(92, right_rect.height() * 0.58))
		console_rect = QRectF(right_rect.left(), map_rect.bottom() + gap, right_rect.width(), max(0, right_rect.bottom() - map_rect.bottom() - gap))

		self._draw_disassembly(painter, code_rect, base, alt, text, border, selection)
		if right_rect.width() > 90:
			self._draw_feature_map(painter, map_rect, base, text, border)
		if console_rect.width() > 90 and console_rect.height() > 48:
			self._draw_console(painter, console_rect, base, text, border)

		painter.end()

	def _draw_tab_bar(self, painter: QPainter, rect: QRectF, base: QColor, alt: QColor, text: QColor, border: QColor, name: str) -> None:
		painter.setPen(Qt.PenStyle.NoPen)
		painter.setBrush(self._theme_color("inactivePaneBackgroundColor", alt.name()))
		painter.drawRect(rect)
		active = QRectF(rect.left() + 8, rect.top() + 6, min(230, rect.width() * 0.26), rect.height() - 6)
		inactive = QRectF(active.right() + 2, rect.top() + 8, min(145, rect.width() * 0.15), rect.height() - 8)
		painter.setBrush(self._theme_color("tabBarTabActiveColor", base.name()))
		painter.setPen(QPen(self._theme_color("tabBarTabBorderColor", border.name()), 1))
		painter.drawRoundedRect(active, 4, 4)
		painter.setPen(text)
		tab_font = painter.font()
		tab_font.setBold(True)
		painter.setFont(tab_font)
		painter.drawText(active.adjusted(12, 0, -24, 0), Qt.AlignmentFlag.AlignVCenter, name)
		tab_font.setBold(False)
		painter.setFont(tab_font)
		painter.setBrush(self._theme_color("tabBarTabInactiveColor", alt.name()))
		painter.setPen(QPen(border, 1))
		painter.drawRoundedRect(inactive, 4, 4)
		painter.setPen(self._soft_border(text, 155))
		painter.drawText(inactive.adjusted(12, 0, -12, 0), Qt.AlignmentFlag.AlignVCenter, "New Tab")
		painter.setPen(text)
		painter.drawText(QRectF(inactive.right() + 12, rect.top(), 22, rect.height()), Qt.AlignmentFlag.AlignCenter, "+")

	def _draw_sidebar(self, painter: QPainter, rect: QRectF, base: QColor, selection: QColor) -> None:
		painter.setPen(Qt.PenStyle.NoPen)
		painter.setBrush(self._theme_color("sidebarBackgroundColor", base.name()))
		painter.drawRect(rect)
		active_icon = self._theme_color("sidebarActiveIconColor", "#79a7ff")
		inactive_icon = self._theme_color("sidebarInactiveIconColor", "#87909f")
		for index in range(5):
			y = rect.top() + 20 + index * 30
			if index == 1:
				painter.setBrush(self._theme_color("sidebarActiveBackgroundColor", selection.name()))
				painter.drawRoundedRect(QRectF(rect.left() + 7, y - 8, rect.width() - 14, 24), 5, 5)
			painter.setBrush(active_icon if index == 1 else inactive_icon)
			painter.drawEllipse(QRectF(rect.center().x() - 4, y, 8, 8))

	def _draw_right_sidebar(self, painter: QPainter, rect: QRectF, base: QColor, selection: QColor) -> None:
		painter.setPen(Qt.PenStyle.NoPen)
		painter.setBrush(self._theme_color("sidebarBackgroundColor", base.name()))
		painter.drawRect(rect)
		icon = self._theme_color("sidebarInactiveIconColor", "#87909f")
		active = self._theme_color("sidebarFocusedIconColor", "#79a7ff")
		for index in range(7):
			y = rect.top() + 16 + index * 27
			painter.setBrush(active if index == 0 else icon)
			if index == 0:
				painter.drawRect(QRectF(rect.center().x() - 6, y, 12, 12))
			elif index % 3 == 0:
				painter.drawRoundedRect(QRectF(rect.center().x() - 6, y, 12, 12), 2, 2)
			else:
				painter.drawEllipse(QRectF(rect.center().x() - 5, y, 10, 10))

	def _draw_status_bar(self, painter: QPainter, rect: QRectF, base: QColor, text: QColor, border: QColor) -> None:
		painter.setPen(QPen(border, 1))
		painter.setBrush(self._theme_color("inactivePaneBackgroundColor", base.name()))
		painter.drawRect(rect)
		painter.setPen(self._theme_color("statusBarServerConnectedColor", "#a6d189"))
		painter.setBrush(self._theme_color("statusBarServerConnectedColor", "#a6d189"))
		painter.drawEllipse(QRectF(rect.left() + 10, rect.center().y() - 4, 8, 8))
		painter.setPen(text)
		painter.drawText(rect.adjusted(26, 0, -10, 0), Qt.AlignmentFlag.AlignVCenter, "Theme Ninja preview")

	def _draw_panel(self, painter: QPainter, rect: QRectF, title: str, fill: QColor, text: QColor, border: QColor) -> QRectF:
		painter.setPen(QPen(border, 1))
		painter.setBrush(fill)
		painter.drawRoundedRect(rect, 3, 3)
		header = QRectF(rect.left(), rect.top(), rect.width(), 25)
		painter.setBrush(self._theme_color("linearDisassemblyFunctionHeaderColor", fill.lighter(108).name()))
		painter.drawRoundedRect(header, 3, 3)
		painter.drawRect(header.adjusted(0, 14, 0, 0))
		font = painter.font()
		font.setBold(True)
		font.setPointSize(max(8, min(11, int(rect.height() / 20))))
		painter.setFont(font)
		painter.setPen(text)
		painter.drawText(header.adjusted(10, 0, -10, 0), Qt.AlignmentFlag.AlignVCenter, title)
		font.setBold(False)
		painter.setFont(font)
		return rect.adjusted(12, 34, -12, -12)

	def _draw_disassembly(self, painter: QPainter, rect: QRectF, base: QColor, alt: QColor, text: QColor, border: QColor, selection: QColor) -> None:
		inner = self._draw_panel(painter, rect, "Linear Disassembly", self._panel_fill("linearDisassemblyBlockColor", base), text, border)
		code_font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
		code_font.setPointSize(max(9, min(12, int(rect.height() / 18))))
		painter.setFont(code_font)
		line_h = max(18, min(23, int(inner.height() / 9)))
		y = inner.top()
		lines = [
			("00401000", "push", "rbp", "", "; prologue"),
			("00401001", "mov", "rbp", "rsp", ""),
			("00401004", "lea", "rdi", "[hello]", "; string"),
			("0040100b", "call", "puts", "", ""),
			("00401010", "xor", "eax", "eax", ""),
			("00401012", "ret", "", "", ""),
		]
		painter.save()
		painter.setClipRect(inner)
		for index, (addr, op, left, right, comment) in enumerate(lines):
			if y + line_h > inner.bottom() - 38:
				break
			row_rect = QRectF(inner.left(), y - 1, inner.width(), line_h)
			if index == 2:
				painter.setPen(Qt.PenStyle.NoPen)
				painter.setBrush(self._theme_color("tokenHighlightColor", selection.name()))
				painter.drawRoundedRect(row_rect, 4, 4)
			painter.setPen(self._theme_color("addressColor", "#a6d189"))
			painter.drawText(QRectF(inner.left(), y, 86, line_h), Qt.AlignmentFlag.AlignVCenter, addr)
			painter.setPen(self._theme_color("opcodeColor", "#87909f"))
			painter.drawText(QRectF(inner.left() + 90, y, 42, line_h), Qt.AlignmentFlag.AlignVCenter, op)
			painter.setPen(self._theme_color("registerColor", "#e78284"))
			painter.drawText(QRectF(inner.left() + 136, y, 56, line_h), Qt.AlignmentFlag.AlignVCenter, left)
			painter.setPen(self._theme_color("numberColor", "#e5c890"))
			painter.drawText(QRectF(inner.left() + 194, y, 70, line_h), Qt.AlignmentFlag.AlignVCenter, right)
			painter.setPen(self._theme_color("commentColor", "#87909f"))
			painter.drawText(QRectF(inner.left() + 258, y, max(20, inner.width() - 258), line_h), Qt.AlignmentFlag.AlignVCenter, comment)
			y += line_h

		if inner.height() > 148:
			hex_y = max(y + 10, inner.bottom() - 42)
			painter.setPen(QPen(border, 1))
			painter.drawLine(inner.left(), hex_y - 7, inner.right(), hex_y - 7)
			painter.setPen(self._theme_color("alphanumericHighlightColor", "#5ccfe6"))
			painter.drawText(QRectF(inner.left(), hex_y, inner.width(), 18), Qt.AlignmentFlag.AlignVCenter, "48 8d 3d 92 00 00 00   e8 21 fe ff ff")
			painter.setPen(self._theme_color("printableHighlightColor", "#e5c890"))
			painter.drawText(QRectF(inner.left(), hex_y + 18, inner.width(), 18), Qt.AlignmentFlag.AlignVCenter, "H.=.....  .!...")
		painter.restore()

	def _draw_feature_map(self, painter: QPainter, rect: QRectF, base: QColor, text: QColor, border: QColor) -> None:
		inner = self._draw_panel(painter, rect, "Feature Map", self._theme_color("featureMapBaseColor", base.name()), text, border)
		painter.save()
		painter.setClipRect(inner)
		track = QRectF(inner.left() + 10, inner.top() + 4, max(16, inner.width() - 20), inner.height() - 8)
		painter.setPen(QPen(self._soft_border(text, 72), 1))
		painter.setBrush(self._theme_color("featureMapBaseColor", base.name()))
		painter.drawRoundedRect(track, 4, 4)
		segments = [
			(0.06, 0.12, "featureMapFunctionColor", "#a6d189"),
			(0.20, 0.06, "featureMapImportColor", "#ca9ee6"),
			(0.31, 0.14, "featureMapAsciiStringColor", "#e5c890"),
			(0.52, 0.18, "featureMapDataVariableColor", "#79a7ff"),
			(0.78, 0.10, "featureMapExternColor", "#ef9f76"),
		]
		for start, size, key, fallback in segments:
			y = track.top() + track.height() * start
			h = max(5, track.height() * size)
			painter.setPen(Qt.PenStyle.NoPen)
			painter.setBrush(self._theme_color(key, fallback))
			painter.drawRoundedRect(QRectF(track.left() + 4, y, track.width() - 8, h), 2, 2)
		nav_y = track.top() + track.height() * 0.44
		painter.setPen(QPen(self._theme_color("featureMapNavLineColor", text.name()), 2))
		painter.drawLine(QPointF(track.left(), nav_y), QPointF(track.right(), nav_y))
		painter.setBrush(self._theme_color("featureMapNavHighlightColor", "#334a66"))
		painter.setPen(Qt.PenStyle.NoPen)
		painter.drawRoundedRect(QRectF(track.left() + 2, nav_y - 7, track.width() - 4, 14), 3, 3)
		painter.restore()

	def _draw_console(self, painter: QPainter, rect: QRectF, base: QColor, text: QColor, border: QColor) -> None:
		inner = self._draw_panel(painter, rect, "Console", base, text, border)
		painter.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
		painter.setPen(self._theme_color("scriptConsoleEchoColor", "#a6d189"))
		painter.drawText(QRectF(inner.left(), inner.top(), inner.width(), 18), Qt.AlignmentFlag.AlignVCenter, ">>> apply_theme()")
		painter.setPen(self._theme_color("scriptConsoleOutputColor", text.name()))
		painter.drawText(QRectF(inner.left(), inner.top() + 20, inner.width(), 18), Qt.AlignmentFlag.AlignVCenter, "Theme refreshed")
		if inner.height() > 54:
			painter.setPen(self._theme_color("scriptConsoleWarningColor", "#e5c890"))
			painter.drawText(QRectF(inner.left(), inner.top() + 40, inner.width(), 18), Qt.AlignmentFlag.AlignVCenter, "Unsaved preview")


class ThemeNinjaWidget(QWidget):
	def __init__(self, parent: QWidget | None = None):
		QWidget.__init__(self, parent)
		self.setObjectName("ThemeNinjaWidget")
		bn_user_dir = user_directory()
		self.user_dir: Path | None = Path(bn_user_dir) if bn_user_dir else None
		self.records: list[ThemeRecord] = []
		self.current_record: ThemeRecord | None = None
		self.current_path: Path | None = None
		self.current_id: str | None = None
		self.current_read_only = False
		self.theme_data: dict[str, Any] | None = None
		self.dirty = False
		self._loading = False
		self._updating_table = False
		self._row_meta: dict[int, tuple[str, str, str]] = {}

		self._build_ui()
		self.refresh_library()

	def _build_ui(self) -> None:
		root = QHBoxLayout(self)
		root.setContentsMargins(0, 0, 0, 0)
		root.setSpacing(0)

		splitter = QSplitter(Qt.Orientation.Horizontal, self)
		splitter.addWidget(self._build_library_panel())
		splitter.addWidget(self._build_editor_panel())
		splitter.setStretchFactor(0, 0)
		splitter.setStretchFactor(1, 1)
		splitter.setSizes([280, 880])
		root.addWidget(splitter)

		self.setStyleSheet(
			"""
			#ThemeNinjaTitle { font-size: 15px; font-weight: 600; }
			#ThemeNinjaSubtle { color: palette(mid); }
			QPushButton { min-height: 24px; }
			QTableWidget::item { padding: 4px; }
			"""
		)

	def _build_library_panel(self) -> QWidget:
		panel = QWidget(self)
		layout = QVBoxLayout(panel)
		layout.setContentsMargins(10, 10, 8, 10)
		layout.setSpacing(8)

		title = QLabel("Themes", panel)
		title.setObjectName("ThemeNinjaTitle")
		layout.addWidget(title)

		self.theme_filter = QLineEdit(panel)
		self.theme_filter.setPlaceholderText("Filter themes")
		self.theme_filter.textChanged.connect(self.populate_theme_list)
		layout.addWidget(self.theme_filter)

		self.theme_list = QListWidget(panel)
		self.theme_list.setUniformItemSizes(True)
		self.theme_list.currentItemChanged.connect(self._theme_selection_changed)
		layout.addWidget(self.theme_list, 1)

		row = QHBoxLayout()
		self.refresh_button = QPushButton("Refresh", panel)
		self.refresh_button.clicked.connect(lambda: self.refresh_library(call_runtime_refresh=True))
		self.new_button = QPushButton("New", panel)
		self.new_button.clicked.connect(self.new_theme)
		self.duplicate_button = QPushButton("Duplicate", panel)
		self.duplicate_button.clicked.connect(self.duplicate_current_theme)
		row.addWidget(self.refresh_button)
		row.addWidget(self.new_button)
		row.addWidget(self.duplicate_button)
		layout.addLayout(row)

		self.apply_button = QPushButton("Apply Selected", panel)
		self.apply_button.clicked.connect(self.apply_selected_theme)
		layout.addWidget(self.apply_button)

		self.theme_status = QLabel("", panel)
		self.theme_status.setObjectName("ThemeNinjaSubtle")
		self.theme_status.setWordWrap(True)
		layout.addWidget(self.theme_status)
		return panel

	def _build_editor_panel(self) -> QWidget:
		panel = QWidget(self)
		layout = QVBoxLayout(panel)
		layout.setContentsMargins(8, 10, 10, 10)
		layout.setSpacing(8)

		header = QHBoxLayout()
		header.addWidget(QLabel("Name", panel))
		self.name_edit = QLineEdit(panel)
		self.name_edit.setPlaceholderText("Theme name")
		self.name_edit.textEdited.connect(self._name_edited)
		header.addWidget(self.name_edit, 1)
		self.save_button = QPushButton("Save", panel)
		self.save_button.clicked.connect(self.save_current_theme)
		self.preview_button = QPushButton("Preview in BN", panel)
		self.preview_button.clicked.connect(self.preview_in_binary_ninja)
		self.save_apply_button = QPushButton("Save && Apply", panel)
		self.save_apply_button.clicked.connect(self.save_and_apply_current_theme)
		self.revert_button = QPushButton("Revert", panel)
		self.revert_button.clicked.connect(self.revert_current_theme)
		header.addWidget(self.save_button)
		header.addWidget(self.preview_button)
		header.addWidget(self.save_apply_button)
		header.addWidget(self.revert_button)
		layout.addLayout(header)

		self.path_label = QLabel("No theme selected", panel)
		self.path_label.setObjectName("ThemeNinjaSubtle")
		self.path_label.setWordWrap(True)
		layout.addWidget(self.path_label)

		edit_splitter = QSplitter(Qt.Orientation.Vertical, panel)
		self.preview = ThemePreview(panel)
		edit_splitter.addWidget(self.preview)
		edit_splitter.addWidget(self._build_color_editor(panel))
		edit_splitter.setStretchFactor(0, 0)
		edit_splitter.setStretchFactor(1, 1)
		edit_splitter.setSizes([260, 520])
		layout.addWidget(edit_splitter, 1)

		self._set_editor_enabled(False)
		return panel

	def _build_color_editor(self, parent: QWidget) -> QWidget:
		wrapper = QWidget(parent)
		layout = QVBoxLayout(wrapper)
		layout.setContentsMargins(0, 0, 0, 0)
		layout.setSpacing(6)

		tools = QHBoxLayout()
		self.section_filter = QComboBox(wrapper)
		self.section_filter.addItem("All Sections")
		for label in ["Colors", "Palette", "Disabled Palette", *THEME_COLOR_GROUPS.keys(), "Theme Colors"]:
			self.section_filter.addItem(label)
		self.section_filter.currentIndexChanged.connect(self.apply_color_filter)
		tools.addWidget(self.section_filter)

		self.color_filter = QLineEdit(wrapper)
		self.color_filter.setPlaceholderText("Filter colors")
		self.color_filter.textChanged.connect(self.apply_color_filter)
		tools.addWidget(self.color_filter, 1)

		self.pick_button = QPushButton("Pick Color", wrapper)
		self.pick_button.clicked.connect(self.pick_selected_color)
		self.add_alias_button = QPushButton("Add Alias", wrapper)
		self.add_alias_button.clicked.connect(self.add_color_alias)
		self.add_theme_color_button = QPushButton("Add Theme Color", wrapper)
		self.add_theme_color_button.clicked.connect(self.add_theme_color)
		self.delete_button = QPushButton("Delete", wrapper)
		self.delete_button.clicked.connect(self.delete_selected_entry)
		tools.addWidget(self.pick_button)
		tools.addWidget(self.add_alias_button)
		tools.addWidget(self.add_theme_color_button)
		tools.addWidget(self.delete_button)
		layout.addLayout(tools)

		self.color_table = QTableWidget(wrapper)
		self.color_table.setColumnCount(5)
		self.color_table.setHorizontalHeaderLabels(["", "Key", "Value", "Section", "Resolved"])
		self.color_table.verticalHeader().hide()
		self.color_table.setAlternatingRowColors(True)
		self.color_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
		self.color_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
		self.color_table.setEditTriggers(
			QAbstractItemView.EditTrigger.DoubleClicked
			| QAbstractItemView.EditTrigger.EditKeyPressed
			| QAbstractItemView.EditTrigger.SelectedClicked
		)
		header = self.color_table.horizontalHeader()
		header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
		self.color_table.setColumnWidth(0, 34)
		header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
		header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
		header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
		header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
		self.color_table.setColumnWidth(4, 96)
		self.color_table.itemChanged.connect(self._table_item_changed)
		self.color_table.cellDoubleClicked.connect(self._table_cell_double_clicked)
		layout.addWidget(self.color_table, 1)
		return wrapper

	def _set_editor_enabled(self, enabled: bool, editable: bool = True) -> None:
		for widget in [self.section_filter, self.color_filter, self.color_table]:
			widget.setEnabled(enabled)
		for widget in [
			self.name_edit,
			self.save_button,
			self.preview_button,
			self.save_apply_button,
			self.revert_button,
			self.pick_button,
			self.add_alias_button,
			self.add_theme_color_button,
			self.delete_button,
		]:
			widget.setEnabled(enabled and editable)
		self.duplicate_button.setEnabled(enabled)
		self.apply_button.setEnabled(enabled)

	def _record_id(self, record: ThemeRecord) -> str:
		if record.path:
			return f"file:{record.path}"
		return f"builtin:{record.name}"

	def _find_record(self, record_id: str) -> ThemeRecord | None:
		return next((record for record in self.records if self._record_id(record) == record_id), None)

	def _runtime_theme_data(self, name: str) -> dict[str, Any]:
		previous = _active_theme_name()
		try:
			if previous != name:
				_set_active_theme(name, False)
			data: dict[str, Any] = {
				"name": name,
				"style": "Fusion",
				"colors": {},
				"palette": {},
				"disabledPalette": {},
				"theme-colors": {},
			}
			for color in ThemeColor:
				try:
					data["theme-colors"][_theme_color_key(color)] = _qcolor_to_hex(getThemeColor(color))
				except Exception:
					continue

			app = QApplication.instance()
			if app is not None:
				palette = app.palette()
				roles = {
					"Window": QPalette.ColorRole.Window,
					"WindowText": QPalette.ColorRole.WindowText,
					"Base": QPalette.ColorRole.Base,
					"AlternateBase": QPalette.ColorRole.AlternateBase,
					"ToolTipBase": QPalette.ColorRole.ToolTipBase,
					"ToolTipText": QPalette.ColorRole.ToolTipText,
					"Text": QPalette.ColorRole.Text,
					"Button": QPalette.ColorRole.Button,
					"ButtonText": QPalette.ColorRole.ButtonText,
					"BrightText": QPalette.ColorRole.BrightText,
					"Link": QPalette.ColorRole.Link,
					"Highlight": QPalette.ColorRole.Highlight,
					"HighlightedText": QPalette.ColorRole.HighlightedText,
					"Light": QPalette.ColorRole.Light,
				}
				for label, role in roles.items():
					data["palette"][label] = _qcolor_to_hex(palette.color(QPalette.ColorGroup.Active, role))
					data["disabledPalette"][label] = _qcolor_to_hex(palette.color(QPalette.ColorGroup.Disabled, role))
			return data
		finally:
			if previous and previous != name:
				_set_active_theme(previous, False)

	def _available_theme_names(self) -> list[str]:
		try:
			return sorted({str(name) for name in getAvailableThemes() if str(name) != PREVIEW_THEME_NAME}, key=str.lower)
		except Exception as exc:
			log_warn(f"Theme Ninja could not list Binary Ninja themes: {exc}")
			return []

	def refresh_library(self, call_runtime_refresh: bool = False, select_path: Path | None = None) -> None:
		if self.user_dir is None:
			self.theme_status.setText("Binary Ninja did not report a user directory.")
			return
		if call_runtime_refresh:
			_refresh_runtime_themes()
		file_records = discover_themes(self.user_dir)
		file_theme_names = {record.name for record in file_records}
		builtin_records = [
			ThemeRecord(name, None, "Built-in", data=None, read_only=True, builtin=True)
			for name in self._available_theme_names()
			if name not in file_theme_names
		]
		self.records = sorted(
			[*builtin_records, *file_records],
			key=lambda record: (0 if record.builtin else 1, record.name.lower(), record.folder_name.lower()),
		)
		self.active_name = _active_theme_name()
		self.populate_theme_list()
		if select_path is not None:
			self._select_path(select_path)
		elif self.current_id is not None and self.current_id.startswith("file:"):
			self._select_id(self.current_id)
		elif self.active_name:
			self._select_active_theme()
		elif self.theme_list.count() > 0 and self.theme_list.currentRow() < 0:
			self.theme_list.setCurrentRow(0)
		self.theme_status.setText(
			f"{len(file_records)} file themes, {len(builtin_records)} built-in themes. Active: {self.active_name or 'unknown'}"
		)

	def populate_theme_list(self) -> None:
		filter_text = self.theme_filter.text().strip().lower()
		current = self.current_id
		self.theme_list.blockSignals(True)
		self.theme_list.clear()
		for record in self.records:
			if filter_text and filter_text not in record.name.lower() and filter_text not in record.folder_name.lower():
				continue
			label = record.name
			if record.builtin:
				label += "  (built-in)"
			if record.name == self.active_name:
				label += "  (active)"
			if record.error:
				label += "  (invalid)"
			item = QListWidgetItem(label)
			record_id = self._record_id(record)
			item.setData(Qt.ItemDataRole.UserRole, record_id)
			location = "Binary Ninja built-in theme" if record.builtin else str(record.path)
			item.setToolTip(f"{record.folder_name}\n{location}" + (f"\n{record.error}" if record.error else ""))
			if record.error:
				item.setForeground(QBrush(QColor("#e78284")))
			elif record.name == self.active_name:
				item.setForeground(QBrush(QColor("#79a7ff")))
			self.theme_list.addItem(item)
			if current and current == record_id:
				self.theme_list.setCurrentItem(item)
		self.theme_list.blockSignals(False)

	def _select_path(self, path: Path) -> None:
		self._select_id(f"file:{path}")

	def _select_active_theme(self) -> None:
		for row in range(self.theme_list.count()):
			item = self.theme_list.item(row)
			record = self._find_record(str(item.data(Qt.ItemDataRole.UserRole)))
			if record is not None and record.name == self.active_name:
				self.theme_list.setCurrentItem(item)
				return

	def _select_id(self, record_id: str) -> None:
		for row in range(self.theme_list.count()):
			item = self.theme_list.item(row)
			if item.data(Qt.ItemDataRole.UserRole) == record_id:
				self.theme_list.setCurrentItem(item)
				return

	def _theme_selection_changed(self, current: QListWidgetItem | None, previous: QListWidgetItem | None) -> None:
		if self._loading or current is None:
			return
		if not self._maybe_save_dirty():
			self.theme_list.blockSignals(True)
			if previous is not None:
				self.theme_list.setCurrentItem(previous)
			self.theme_list.blockSignals(False)
			return
		record = self._find_record(str(current.data(Qt.ItemDataRole.UserRole)))
		if record is not None:
			self.load_record(record)

	def load_theme(self, path: Path) -> None:
		record = next((item for item in self.records if item.path == path), None)
		if record is None:
			self.refresh_library(select_path=path)
			record = next((item for item in self.records if item.path == path), None)
		if record is None:
			return
		self.load_record(record)

	def load_record(self, record: ThemeRecord) -> None:
		if record.error or record.data is None:
			if record.builtin and not record.error:
				data = self._runtime_theme_data(record.name)
				record = ThemeRecord(record.name, None, record.folder_name, data=data, read_only=True, builtin=True)
			else:
				record_label = record.path.name if record.path else record.name
				QMessageBox.warning(self, "Theme Ninja", f"Could not load {record_label}:\n{record.error}")
				self._set_editor_enabled(False)
				return
		if record.data is None:
			self._set_editor_enabled(False)
			return

		self._loading = True
		self.current_record = record
		self.current_path = record.path
		self.current_id = self._record_id(record)
		self.current_read_only = record.read_only
		self.theme_data = deepcopy(record.data)
		self.dirty = False
		self.name_edit.setText(str(self.theme_data.get("name", record.name)))
		if record.read_only:
			self.path_label.setText("Built-in Binary Ninja theme: read-only. Duplicate it to edit a copy.")
		else:
			self.path_label.setText(f"{record.folder_name}: {record.path}")
		self._set_editor_enabled(True, editable=not record.read_only)
		self.populate_color_table()
		self.preview.set_theme(self.theme_data)
		self._update_dirty_state()
		self._loading = False

	def _maybe_save_dirty(self) -> bool:
		if not self.dirty or not self.theme_data:
			return True
		box = QMessageBox(self)
		box.setWindowTitle("Theme Ninja")
		box.setText("Save changes to this theme before switching?")
		box.setStandardButtons(
			QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel
		)
		box.setDefaultButton(QMessageBox.StandardButton.Save)
		result = box.exec()
		if result == QMessageBox.StandardButton.Save:
			return self.save_current_theme()
		if result == QMessageBox.StandardButton.Discard:
			return True
		return False

	def _name_edited(self, text: str) -> None:
		if self.theme_data is None or self.current_read_only:
			return
		self.theme_data["name"] = text.strip() or "Untitled Theme"
		self.mark_dirty()
		self.preview.set_theme(self.theme_data)

	def mark_dirty(self) -> None:
		if self._loading or self.current_read_only:
			return
		self.dirty = True
		self._update_dirty_state()

	def _update_dirty_state(self) -> None:
		suffix = " *" if self.dirty else ""
		self.save_button.setEnabled(self.theme_data is not None and self.dirty and not self.current_read_only)
		self.preview_button.setEnabled(self.theme_data is not None and not self.current_read_only)
		self.save_apply_button.setEnabled(self.theme_data is not None and not self.current_read_only)
		self.revert_button.setEnabled(self.theme_data is not None and not self.current_read_only)
		self.name_edit.setEnabled(self.theme_data is not None and not self.current_read_only)
		for widget in [self.pick_button, self.add_alias_button, self.add_theme_color_button, self.delete_button]:
			widget.setEnabled(self.theme_data is not None and not self.current_read_only)
		if self.current_record and self.theme_data:
			if self.current_record.read_only:
				self.path_label.setText("Built-in Binary Ninja theme: read-only. Duplicate it to edit a copy.")
			else:
				self.path_label.setText(f"{self.current_record.folder_name}: {self.current_record.path}{suffix}")

	def populate_color_table(self, preserve: tuple[str, str] | None = None) -> None:
		self._updating_table = True
		self._row_meta.clear()
		self.color_table.setRowCount(0)
		if not self.theme_data:
			self._updating_table = False
			return

		rows: list[tuple[str, str, str]] = []
		for key in sorted(self.theme_data.get("colors", {}) if isinstance(self.theme_data.get("colors"), dict) else {}):
			rows.append(("colors", key, "Colors"))
		for key in sorted(self.theme_data.get("palette", {}) if isinstance(self.theme_data.get("palette"), dict) else {}):
			rows.append(("palette", key, "Palette"))
		for key in sorted(self.theme_data.get("disabledPalette", {}) if isinstance(self.theme_data.get("disabledPalette"), dict) else {}):
			rows.append(("disabledPalette", key, "Disabled Palette"))
		theme_colors = self.theme_data.get("theme-colors", {})
		seen = set()
		if isinstance(theme_colors, dict):
			for group, keys in THEME_COLOR_GROUPS.items():
				for key in keys:
					if key in theme_colors:
						rows.append(("theme-colors", key, group))
						seen.add(key)
			for key in sorted(set(theme_colors) - seen):
				rows.append(("theme-colors", key, "Theme Colors"))

		self.color_table.setRowCount(len(rows))
		selected_row = -1
		for row, (section, key, category) in enumerate(rows):
			self._row_meta[row] = (section, key, category)
			values = self.theme_data.get(section, {})
			raw_value = values.get(key) if isinstance(values, dict) else None
			resolved = resolve_entry(self.theme_data, section, key)
			color = _qcolor(resolved, "#3b4352")

			swatch = QTableWidgetItem("")
			swatch.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
			swatch.setToolTip("Double-click to pick a color")
			self.color_table.setItem(row, 0, swatch)
			self.color_table.setCellWidget(row, 0, ColorSwatch(color, self.color_table))

			key_item = QTableWidgetItem(key)
			key_item.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
			key_item.setToolTip(pretty_key(key))
			self.color_table.setItem(row, 1, key_item)

			value_item = QTableWidgetItem(display_value(raw_value))
			value_flags = Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled
			if not self.current_read_only:
				value_flags |= Qt.ItemFlag.ItemIsEditable
			value_item.setFlags(value_flags)
			value_item.setToolTip("Use #rrggbb, #rrggbbaa, an alias name, or a Binary Ninja color expression")
			self.color_table.setItem(row, 2, value_item)

			category_item = QTableWidgetItem(category)
			category_item.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
			self.color_table.setItem(row, 3, category_item)

			resolved_item = QTableWidgetItem("")
			resolved_item.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
			resolved_item.setToolTip(tuple_to_hex(resolved) if resolved else "unresolved")
			self.color_table.setItem(row, 4, resolved_item)
			self.color_table.setCellWidget(
				row,
				4,
				ColorValueLabel(tuple_to_hex(resolved) if resolved else "unresolved", color if resolved else QColor("#e78284"), self.color_table),
			)

			if preserve == (section, key):
				selected_row = row

		self._updating_table = False
		self.apply_color_filter()
		if selected_row >= 0:
			self.color_table.selectRow(selected_row)

	def apply_color_filter(self) -> None:
		text = self.color_filter.text().strip().lower()
		category = self.section_filter.currentText()
		for row in range(self.color_table.rowCount()):
			section, key, row_category = self._row_meta.get(row, ("", "", ""))
			value_item = self.color_table.item(row, 2)
			matches_text = not text or text in key.lower() or (value_item and text in value_item.text().lower())
			matches_category = (
				category == "All Sections"
				or category == row_category
				or (category == "Theme Colors" and section == "theme-colors")
			)
			self.color_table.setRowHidden(row, not (matches_text and matches_category))

	def _selected_entry(self) -> tuple[str, str] | None:
		row = self.color_table.currentRow()
		if row < 0:
			return None
		meta = self._row_meta.get(row)
		if meta is None:
			return None
		return meta[0], meta[1]

	def _table_item_changed(self, item: QTableWidgetItem) -> None:
		if self._updating_table or item.column() != 2 or self.theme_data is None or self.current_read_only:
			return
		meta = self._row_meta.get(item.row())
		if meta is None:
			return
		section, key, _category = meta
		ok, error = update_entry_from_text(self.theme_data, section, key, item.text())
		if not ok:
			QMessageBox.warning(self, "Theme Ninja", error or "Could not update color value")
			return
		self.mark_dirty()
		self.preview.set_theme(self.theme_data)
		self.populate_color_table((section, key))

	def _table_cell_double_clicked(self, row: int, column: int) -> None:
		if column in (0, 4):
			self.pick_selected_color()

	def pick_selected_color(self) -> None:
		if self.theme_data is None or self.current_read_only:
			return
		entry = self._selected_entry()
		if entry is None:
			return
		section, key = entry
		current = _qcolor(resolve_entry(self.theme_data, section, key), "#79a7ff")
		color = QColorDialog.getColor(
			current,
			self,
			f"Pick {key}",
			QColorDialog.ColorDialogOption.ShowAlphaChannel,
		)
		if not color.isValid():
			return
		set_entry_color(self.theme_data, section, key, (color.red(), color.green(), color.blue(), color.alpha()))
		self.mark_dirty()
		self.preview.set_theme(self.theme_data)
		self.populate_color_table((section, key))

	def add_color_alias(self) -> None:
		if self.theme_data is None or self.current_read_only:
			return
		name, ok = QInputDialog.getText(self, "Add Alias", "Alias name:")
		if not ok or not name.strip():
			return
		key = name.strip()
		colors = self.theme_data.setdefault("colors", {})
		if not isinstance(colors, dict):
			QMessageBox.warning(self, "Theme Ninja", "The colors section is not editable because it is not a JSON object.")
			return
		if key in colors:
			QMessageBox.warning(self, "Theme Ninja", f"{key} already exists.")
			return
		colors[key] = "#79a7ff"
		self.mark_dirty()
		self.preview.set_theme(self.theme_data)
		self.populate_color_table(("colors", key))

	def add_theme_color(self) -> None:
		if self.theme_data is None or self.current_read_only:
			return
		theme_colors = self.theme_data.setdefault("theme-colors", {})
		if not isinstance(theme_colors, dict):
			QMessageBox.warning(self, "Theme Ninja", "The theme-colors section is not editable because it is not a JSON object.")
			return
		missing = [key for key in ALL_KNOWN_THEME_COLORS if key not in theme_colors]
		if not missing:
			QMessageBox.information(self, "Theme Ninja", "All known Binary Ninja theme colors already exist.")
			return
		key, ok = QInputDialog.getItem(self, "Add Theme Color", "Theme color:", missing, 0, False)
		if not ok or not key:
			return
		theme_colors[key] = "#79a7ff"
		self.mark_dirty()
		self.preview.set_theme(self.theme_data)
		self.populate_color_table(("theme-colors", key))

	def delete_selected_entry(self) -> None:
		if self.theme_data is None or self.current_read_only:
			return
		entry = self._selected_entry()
		if entry is None:
			return
		section, key = entry
		result = QMessageBox.question(self, "Theme Ninja", f"Delete {key} from {section}?")
		if result != QMessageBox.StandardButton.Yes:
			return
		remove_entry(self.theme_data, section, key)
		self.mark_dirty()
		self.preview.set_theme(self.theme_data)
		self.populate_color_table()

	def save_current_theme(self) -> bool:
		if self.theme_data is None or self.current_path is None or self.current_read_only:
			return False
		self.theme_data["name"] = self.name_edit.text().strip() or "Untitled Theme"
		try:
			write_theme_file(self.current_path, self.theme_data)
			_refresh_runtime_themes()
		except Exception as exc:
			QMessageBox.critical(self, "Theme Ninja", f"Could not save theme:\n{exc}")
			log_error(f"Theme Ninja save failed: {exc}")
			return False
		self.dirty = False
		self._update_dirty_state()
		log_info(f"Theme Ninja saved {self.current_path}")
		self.refresh_library(select_path=self.current_path)
		return True

	def save_and_apply_current_theme(self) -> None:
		if self.current_read_only:
			self.apply_selected_theme()
			return
		if not self.save_current_theme() or not self.theme_data:
			return
		name = str(self.theme_data.get("name", ""))
		try:
			_refresh_runtime_themes()
			_set_active_theme(name, True)
			self.active_name = _active_theme_name()
			self.populate_theme_list()
			self.theme_status.setText(f"Active: {self.active_name or name}")
		except Exception as exc:
			QMessageBox.critical(self, "Theme Ninja", f"Saved, but Binary Ninja could not apply the theme:\n{exc}")

	def preview_in_binary_ninja(self) -> None:
		if self.theme_data is None or self.user_dir is None or self.current_read_only:
			return
		data = deepcopy(self.theme_data)
		data["name"] = PREVIEW_THEME_NAME
		path = primary_theme_directory(self.user_dir) / PREVIEW_FILE_NAME
		try:
			write_theme_file(path, data, make_backup=False)
			_refresh_runtime_themes()
			_set_active_theme(PREVIEW_THEME_NAME, False)
			self.active_name = _active_theme_name()
			self.theme_status.setText(f"Previewing: {self.active_name or PREVIEW_THEME_NAME}")
		except Exception as exc:
			QMessageBox.critical(self, "Theme Ninja", f"Could not preview the theme in Binary Ninja:\n{exc}")

	def revert_current_theme(self) -> None:
		if self.current_path is None:
			return
		self.load_theme(self.current_path)

	def apply_selected_theme(self) -> None:
		item = self.theme_list.currentItem()
		if item is None:
			return
		if self.dirty and not self.save_current_theme():
			return
		record = self._find_record(str(item.data(Qt.ItemDataRole.UserRole)))
		if record is None or not record.is_valid:
			return
		try:
			_refresh_runtime_themes()
			_set_active_theme(record.name, True)
			self.active_name = _active_theme_name()
			self.populate_theme_list()
			self.theme_status.setText(f"Active: {self.active_name or record.name}")
		except Exception as exc:
			QMessageBox.critical(self, "Theme Ninja", f"Could not apply the theme:\n{exc}")

	def new_theme(self) -> None:
		if not self._maybe_save_dirty():
			return
		name, ok = QInputDialog.getText(self, "New Theme", "Theme name:")
		if not ok or not name.strip():
			return
		try:
			if self.user_dir is None:
				return
			path, _data = create_new_theme(self.user_dir, name.strip())
			_refresh_runtime_themes()
			self.refresh_library(select_path=path)
		except Exception as exc:
			QMessageBox.critical(self, "Theme Ninja", f"Could not create theme:\n{exc}")

	def duplicate_current_theme(self) -> None:
		if self.theme_data is None:
			return
		if not self._maybe_save_dirty():
			return
		default_name = f"{self.theme_data.get('name', 'Theme')} Copy"
		name, ok = QInputDialog.getText(self, "Duplicate Theme", "New theme name:", text=default_name)
		if not ok or not name.strip():
			return
		try:
			if self.user_dir is None:
				return
			path, _data = duplicate_theme(self.user_dir, self.theme_data, name.strip())
			_refresh_runtime_themes()
			self.refresh_library(select_path=path)
		except Exception as exc:
			QMessageBox.critical(self, "Theme Ninja", f"Could not duplicate theme:\n{exc}")

	@staticmethod
	def create_pane(context) -> None:
		if not context.context:
			return
		context.context.openPane(WidgetPane(ThemeNinjaWidget(), "Theme Ninja"))

	@staticmethod
	def can_create_pane(context) -> bool:
		return bool(context.context)


class ThemeNinjaSidebarWidget(SidebarWidget):
	def __init__(self, name, frame, data):
		SidebarWidget.__init__(self, name)
		self.actionHandler = UIActionHandler()
		self.actionHandler.setupActionHandler(self)
		layout = QVBoxLayout(self)
		layout.setContentsMargins(0, 0, 0, 0)
		self.studio = ThemeNinjaWidget(self)
		layout.addWidget(self.studio)

	def contextMenuEvent(self, event) -> None:  # noqa: N802 - Qt override
		self.m_contextMenuManager.show(self.m_menu, self.actionHandler)


class ThemeNinjaWidgetType(SidebarWidgetType):
	def __init__(self):
		icon = QImage(56, 56, QImage.Format.Format_RGB32)
		icon.fill(0)
		painter = QPainter()
		painter.begin(icon)
		painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
		painter.setPen(Qt.PenStyle.NoPen)
		painter.setBrush(QColor(255, 255, 255, 255))
		for index, radius in enumerate([18, 14, 10]):
			painter.drawEllipse(QRectF(8 + index * 12, 10 + index * 7, radius, radius))
		painter.setPen(QPen(QColor(255, 255, 255, 255), 6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
		painter.drawLine(16, 43, 42, 17)
		painter.end()
		SidebarWidgetType.__init__(self, icon, "Theme Ninja")

	def createWidget(self, frame, data):  # noqa: N802 - Binary Ninja API
		return ThemeNinjaSidebarWidget("Theme Ninja", frame, data)

	def defaultLocation(self):  # noqa: N802 - Binary Ninja API
		return SidebarWidgetLocation.RightContent

	def contextSensitivity(self):  # noqa: N802 - Binary Ninja API
		return SidebarContextSensitivity.GlobalSidebarContext

	def canUseAsPane(self, split_pane_widget, data):  # noqa: N802 - Binary Ninja API
		return True

	def createPane(self, split_pane_widget, data):  # noqa: N802 - Binary Ninja API
		return WidgetPane(ThemeNinjaWidget(), "Theme Ninja")


_registered = False


def register_plugin() -> None:
	global _registered
	if _registered:
		return
	Sidebar.addSidebarWidgetType(ThemeNinjaWidgetType())
	UIAction.registerAction("Theme Ninja")
	UIActionHandler.globalActions().bindAction(
		"Theme Ninja", UIAction(ThemeNinjaWidget.create_pane, ThemeNinjaWidget.can_create_pane)
	)
	Menu.mainMenu("Plugins").addAction("Theme Ninja", "Theme Ninja")
	_registered = True
