from __future__ import annotations

import json
import re
import shutil
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any


THEME_FOLDER_NAMES = ("themes", "community-themes", "community_themes")
PREVIEW_FILE_NAME = ".theme-ninja-preview.bntheme"
PREVIEW_THEME_NAME = "Theme Ninja Preview"
WINDOWS_RESERVED_FILE_STEMS = {
	"CON",
	"PRN",
	"AUX",
	"NUL",
	*(f"COM{index}" for index in range(1, 10)),
	*(f"LPT{index}" for index in range(1, 10)),
}


@dataclass(frozen=True)
class ThemeRecord:
	name: str
	path: Path | None
	folder_name: str
	data: dict[str, Any] | None = None
	error: str | None = None
	read_only: bool = False
	builtin: bool = False

	@property
	def is_valid(self) -> bool:
		return (self.data is not None or self.builtin) and self.error is None


def theme_directories(user_dir: str | Path, include_missing: bool = False) -> list[Path]:
	root = Path(user_dir)
	dirs = [root / folder for folder in THEME_FOLDER_NAMES]
	if include_missing:
		return dirs
	return [path for path in dirs if path.exists() and path.is_dir()]


def primary_theme_directory(user_dir: str | Path) -> Path:
	path = Path(user_dir) / "themes"
	path.mkdir(parents=True, exist_ok=True)
	return path


def load_theme_file(path: str | Path) -> tuple[dict[str, Any] | None, str | None]:
	path = Path(path)
	try:
		with path.open("r", encoding="utf-8-sig") as handle:
			data = json.load(handle)
	except Exception as exc:
		return None, str(exc)

	if not isinstance(data, dict):
		return None, "Theme root must be a JSON object"
	if not isinstance(data.get("name", path.stem), str):
		return None, "Theme name must be a string"
	return data, None


def discover_themes(user_dir: str | Path) -> list[ThemeRecord]:
	records: list[ThemeRecord] = []
	for directory in theme_directories(user_dir):
		for path in sorted(directory.glob("*.bntheme"), key=lambda item: item.name.lower()):
			if path.name == PREVIEW_FILE_NAME:
				continue
			data, error = load_theme_file(path)
			name = path.stem if data is None else data.get("name", path.stem)
			records.append(ThemeRecord(str(name), path, directory.name, data, error))
	return sorted(
		records,
		key=lambda record: (record.name.lower(), record.folder_name.lower(), record.path.name.lower() if record.path else ""),
	)


def safe_file_stem(name: str) -> str:
	stem = re.sub(r"[^A-Za-z0-9._-]+", "-", name.strip().lower())
	stem = re.sub(r"-{2,}", "-", stem).strip(".-")
	if not stem:
		return "theme"
	if stem.upper() in WINDOWS_RESERVED_FILE_STEMS:
		return f"theme-{stem}"
	return stem


def unique_theme_path(directory: Path, name: str) -> Path:
	stem = safe_file_stem(name)
	path = directory / f"{stem}.bntheme"
	index = 2
	while path.exists():
		path = directory / f"{stem}-{index}.bntheme"
		index += 1
	return path


def write_theme_file(path: str | Path, data: dict[str, Any], make_backup: bool = True) -> None:
	path = Path(path)
	path.parent.mkdir(parents=True, exist_ok=True)
	if make_backup and path.exists():
		backup = path.with_suffix(path.suffix + ".bak")
		if not backup.exists():
			shutil.copy2(path, backup)

	tmp_path = path.with_name(path.name + ".tmp")
	with tmp_path.open("w", encoding="utf-8") as handle:
		json.dump(data, handle, indent=4)
		handle.write("\n")
	tmp_path.replace(path)


def create_new_theme(user_dir: str | Path, name: str) -> tuple[Path, dict[str, Any]]:
	directory = primary_theme_directory(user_dir)
	data = make_default_theme(name)
	path = unique_theme_path(directory, name)
	write_theme_file(path, data, make_backup=False)
	return path, data


def duplicate_theme(user_dir: str | Path, source_data: dict[str, Any], name: str) -> tuple[Path, dict[str, Any]]:
	directory = primary_theme_directory(user_dir)
	data = deepcopy(source_data)
	data["name"] = name
	path = unique_theme_path(directory, name)
	write_theme_file(path, data, make_backup=False)
	return path, data


ColorTuple = tuple[int, int, int, int]


def clamp_channel(value: Any) -> int:
	try:
		value = int(value)
	except Exception:
		value = 0
	return max(0, min(255, value))


def tuple_to_hex(color: ColorTuple, include_alpha: bool = False) -> str:
	if include_alpha or color[3] != 255:
		return "#{:02x}{:02x}{:02x}{:02x}".format(*color)
	return "#{:02x}{:02x}{:02x}".format(color[0], color[1], color[2])


def parse_hex_color(value: str) -> ColorTuple | None:
	text = value.strip()
	if not text.startswith("#"):
		return None
	text = text[1:]
	if len(text) == 3:
		text = "".join(ch * 2 for ch in text)
	if len(text) not in (6, 8):
		return None
	try:
		red = int(text[0:2], 16)
		green = int(text[2:4], 16)
		blue = int(text[4:6], 16)
		alpha = int(text[6:8], 16) if len(text) == 8 else 255
	except ValueError:
		return None
	return red, green, blue, alpha


def parse_color_text(value: str) -> ColorTuple | None:
	text = value.strip()
	hex_color = parse_hex_color(text)
	if hex_color:
		return hex_color
	parts = [part.strip() for part in text.split(",")]
	if len(parts) in (3, 4) and all(part for part in parts):
		try:
			channels = [clamp_channel(part) for part in parts]
		except Exception:
			return None
		if len(channels) == 3:
			channels.append(255)
		return tuple(channels)  # type: ignore[return-value]
	return None


def color_to_json_value(color: ColorTuple) -> str:
	return tuple_to_hex(color, include_alpha=color[3] != 255)


def average_colors(left: ColorTuple, right: ColorTuple) -> ColorTuple:
	return tuple((left[index] + right[index]) // 2 for index in range(4))  # type: ignore[return-value]


def mix_colors(left: ColorTuple, right: ColorTuple, amount: int) -> ColorTuple:
	amount = clamp_channel(amount)
	inverse = 255 - amount
	return tuple((left[index] * inverse + right[index] * amount) // 255 for index in range(4))  # type: ignore[return-value]


def _parse_expression(tokens: list[Any], theme: dict[str, Any], seen: set[str], index: int = 0) -> tuple[ColorTuple | None, int]:
	if index >= len(tokens):
		return None, index

	token = tokens[index]
	if token == "+":
		left, after_left = _parse_expression(tokens, theme, seen, index + 1)
		right, after_right = _parse_expression(tokens, theme, seen, after_left)
		if left is None or right is None:
			return None, after_right
		return average_colors(left, right), after_right
	if token == "~":
		left, after_left = _parse_expression(tokens, theme, seen, index + 1)
		right, after_right = _parse_expression(tokens, theme, seen, after_left)
		if after_right >= len(tokens) or left is None or right is None:
			return None, after_right
		return mix_colors(left, right, clamp_channel(tokens[after_right])), after_right + 1
	return resolve_color_value(token, theme, seen), index + 1


def resolve_color_value(value: Any, theme: dict[str, Any], seen: set[str] | None = None) -> ColorTuple | None:
	if seen is None:
		seen = set()

	if isinstance(value, str):
		hex_color = parse_hex_color(value)
		if hex_color:
			return hex_color
		colors = theme.get("colors", {})
		if isinstance(colors, dict) and value in colors and value not in seen:
			seen.add(value)
			return resolve_color_value(colors[value], theme, seen)
		return None

	if isinstance(value, (list, tuple)):
		if len(value) in (3, 4) and all(isinstance(part, (int, float)) for part in value):
			channels = [clamp_channel(part) for part in value]
			if len(channels) == 3:
				channels.append(255)
			return tuple(channels)  # type: ignore[return-value]
		if len(value) > 0 and value[0] in ("+", "~"):
			color, consumed = _parse_expression(list(value), theme, seen, 0)
			if consumed <= len(value):
				return color
	return None


def resolve_entry(theme: dict[str, Any], section: str, key: str) -> ColorTuple | None:
	values = theme.get(section, {})
	if not isinstance(values, dict) or key not in values:
		return None
	return resolve_color_value(values[key], theme)


def set_entry_color(theme: dict[str, Any], section: str, key: str, color: ColorTuple) -> None:
	values = theme.setdefault(section, {})
	if not isinstance(values, dict):
		values = {}
		theme[section] = values
	values[key] = color_to_json_value(color)


def remove_entry(theme: dict[str, Any], section: str, key: str) -> None:
	values = theme.get(section)
	if isinstance(values, dict):
		values.pop(key, None)


def display_value(value: Any) -> str:
	if isinstance(value, str):
		return value
	return json.dumps(value, separators=(",", ":"))


def update_entry_from_text(theme: dict[str, Any], section: str, key: str, text: str) -> tuple[bool, str | None]:
	color = parse_color_text(text)
	if color:
		set_entry_color(theme, section, key, color)
		return True, None
	try:
		value = json.loads(text)
	except json.JSONDecodeError:
		value = text.strip()
	values = theme.setdefault(section, {})
	if not isinstance(values, dict):
		return False, f"{section} is not a JSON object"
	values[key] = value
	return True, None


def make_default_theme(name: str) -> dict[str, Any]:
	theme = deepcopy(DEFAULT_THEME)
	theme["name"] = name.strip() or "Untitled Theme"
	return theme


def pretty_key(key: str) -> str:
	text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", key)
	text = text.replace("-", " ").replace("_", " ")
	return text[:1].upper() + text[1:]


THEME_COLOR_GROUPS: dict[str, list[str]] = {
	"Tokens": [
		"addressColor", "instructionColor", "registerColor", "numberColor", "codeSymbolColor", "dataSymbolColor",
		"localVariableColor", "stackVariableColor", "importColor", "exportColor", "annotationColor", "opcodeColor",
		"stringColor", "typeNameColor", "fieldNameColor", "keywordColor", "uncertainColor", "nameSpaceColor",
		"nameSpaceSeparatorColor", "gotoLabelColor", "commentColor", "operationColor", "baseStructureNameColor",
		"voidTypeColor", "structureTypeColor", "enumerationTypeColor", "functionTypeColor", "boolTypeColor",
		"integerTypeColor", "floatTypeColor", "pointerTypeColor", "arrayTypeColor", "varArgsTypeColor",
		"valueTypeColor", "namedTypeReferenceColor", "wideCharTypeColor",
	],
	"Highlighting": [
		"selectionColor", "outlineColor", "instructionHighlightColor", "relatedInstructionHighlightColor",
		"tokenHighlightColor", "tokenSelectionColor", "blueStandardHighlightColor", "greenStandardHighlightColor",
		"cyanStandardHighlightColor", "redStandardHighlightColor", "magentaStandardHighlightColor",
		"yellowStandardHighlightColor", "orangeStandardHighlightColor", "whiteStandardHighlightColor",
		"blackStandardHighlightColor", "braceOption1Color", "braceOption2Color", "braceOption3Color",
		"braceOption4Color", "braceOption5Color", "braceOption6Color",
	],
	"Hex View": [
		"modifiedColor", "insertedColor", "notPresentColor", "backgroundHighlightDarkColor",
		"backgroundHighlightLightColor", "boldBackgroundHighlightDarkColor", "boldBackgroundHighlightLightColor",
		"alphanumericHighlightColor", "printableHighlightColor",
	],
	"Graph": [
		"graphBackgroundDarkColor", "graphBackgroundLightColor", "graphNodeDarkColor", "graphNodeLightColor",
		"graphNodeOutlineColor", "graphNodeShadowColor", "graphEntryNodeIndicatorColor", "graphExitNodeIndicatorColor",
		"graphExitNoreturnNodeIndicatorColor", "trueBranchColor", "falseBranchColor", "unconditionalBranchColor",
		"altTrueBranchColor", "altFalseBranchColor", "altUnconditionalBranchColor",
	],
	"Linear View": [
		"linearDisassemblyFunctionHeaderColor", "linearDisassemblyBlockColor", "linearDisassemblyNoteColor",
		"linearDisassemblySeparatorColor", "linearDisassemblyCodeFoldColor", "indentationLineColor",
		"indentationLineHighlightColor",
	],
	"Console": [
		"scriptConsoleOutputColor", "scriptConsoleWarningColor", "scriptConsoleErrorColor", "scriptConsoleEchoColor",
	],
	"Mini Graph": ["miniGraphOverlayColor"],
	"Feature Map": [
		"featureMapBaseColor", "featureMapNavLineColor", "featureMapNavHighlightColor", "featureMapDataVariableColor",
		"featureMapAsciiStringColor", "featureMapUnicodeStringColor", "featureMapFunctionColor",
		"featureMapImportColor", "featureMapExternColor", "featureMapLibraryColor",
	],
	"Sidebar": [
		"sidebarBackgroundColor", "sidebarInactiveIconColor", "sidebarHoverIconColor", "sidebarActiveIconColor",
		"sidebarFocusedIconColor", "sidebarHoverBackgroundColor", "sidebarActiveBackgroundColor",
		"sidebarFocusedBackgroundColor", "sidebarActiveIndicatorLineColor", "sidebarHeaderBackgroundColor",
		"sidebarHeaderTextColor", "sidebarWidgetBackgroundColor",
	],
	"Panes And Tabs": [
		"activePaneBackgroundColor", "inactivePaneBackgroundColor", "focusedPaneBackgroundColor",
		"tabBarTabActiveColor", "tabBarTabHoverColor", "tabBarTabInactiveColor", "tabBarTabBorderColor",
		"tabBarTabGlowColor",
	],
	"Status Bar": [
		"statusBarServerConnectedColor", "statusBarServerDisconnectedColor", "statusBarServerWarningColor",
		"statusBarProjectColor",
	],
}


ALL_KNOWN_THEME_COLORS = sorted({key for keys in THEME_COLOR_GROUPS.values() for key in keys})


DEFAULT_THEME: dict[str, Any] = {
	"name": "Untitled Theme",
	"style": "Fusion",
	"colors": {
		"bg": "#15171c",
		"panel": "#1d2129",
		"panelAlt": "#252a34",
		"text": "#d7dde8",
		"muted": "#87909f",
		"blue": "#79a7ff",
		"cyan": "#5ccfe6",
		"green": "#a6d189",
		"yellow": "#e5c890",
		"orange": "#ef9f76",
		"red": "#e78284",
		"magenta": "#ca9ee6",
		"outline": "#3b4352",
		"selection": "#334a66",
		"white": "#f2f4f8",
		"black": "#080a0f",
	},
	"palette": {
		"Window": "bg",
		"WindowText": "text",
		"Base": "panel",
		"AlternateBase": "panelAlt",
		"ToolTipBase": "panelAlt",
		"ToolTipText": "text",
		"Text": "text",
		"Button": "panelAlt",
		"ButtonText": "text",
		"BrightText": "white",
		"Link": "blue",
		"Highlight": "selection",
		"HighlightedText": "white",
		"Light": "outline",
	},
	"disabledPalette": {
		"WindowText": "muted",
		"Text": "muted",
		"ButtonText": "muted",
		"Highlight": "outline",
		"HighlightedText": "text",
	},
	"theme-colors": {
		"addressColor": "green",
		"modifiedColor": "red",
		"insertedColor": "cyan",
		"notPresentColor": "muted",
		"selectionColor": "selection",
		"outlineColor": "outline",
		"backgroundHighlightDarkColor": "panel",
		"backgroundHighlightLightColor": "panelAlt",
		"boldBackgroundHighlightDarkColor": ["~", "blue", "panel", 80],
		"boldBackgroundHighlightLightColor": ["~", "orange", "panel", 92],
		"alphanumericHighlightColor": "cyan",
		"printableHighlightColor": "yellow",
		"graphBackgroundDarkColor": "bg",
		"graphBackgroundLightColor": "panel",
		"graphNodeDarkColor": "panel",
		"graphNodeLightColor": "panelAlt",
		"graphNodeOutlineColor": "outline",
		"graphNodeShadowColor": "black",
		"graphEntryNodeIndicatorColor": "green",
		"graphExitNodeIndicatorColor": "blue",
		"graphExitNoreturnNodeIndicatorColor": "red",
		"trueBranchColor": "green",
		"falseBranchColor": "red",
		"unconditionalBranchColor": "blue",
		"altTrueBranchColor": "cyan",
		"altFalseBranchColor": "orange",
		"altUnconditionalBranchColor": "magenta",
		"instructionColor": "text",
		"registerColor": "red",
		"numberColor": "yellow",
		"codeSymbolColor": "green",
		"dataSymbolColor": "magenta",
		"localVariableColor": "cyan",
		"stackVariableColor": "blue",
		"importColor": "green",
		"exportColor": "cyan",
		"instructionHighlightColor": ["~", "selection", "panel", 100],
		"relatedInstructionHighlightColor": ["~", "magenta", "panel", 80],
		"tokenHighlightColor": "selection",
		"tokenSelectionColor": "blue",
		"annotationColor": "muted",
		"opcodeColor": "muted",
		"linearDisassemblyFunctionHeaderColor": "panelAlt",
		"linearDisassemblyBlockColor": "panel",
		"linearDisassemblyNoteColor": "panelAlt",
		"linearDisassemblySeparatorColor": "outline",
		"linearDisassemblyCodeFoldColor": "muted",
		"stringColor": "yellow",
		"typeNameColor": "cyan",
		"fieldNameColor": "blue",
		"keywordColor": "magenta",
		"uncertainColor": "orange",
		"nameSpaceColor": "blue",
		"nameSpaceSeparatorColor": "muted",
		"gotoLabelColor": "green",
		"commentColor": "muted",
		"operationColor": "magenta",
		"baseStructureNameColor": "cyan",
		"indentationLineColor": "outline",
		"indentationLineHighlightColor": "blue",
		"scriptConsoleOutputColor": "text",
		"scriptConsoleWarningColor": "yellow",
		"scriptConsoleErrorColor": "red",
		"scriptConsoleEchoColor": "green",
		"blueStandardHighlightColor": "blue",
		"greenStandardHighlightColor": "green",
		"cyanStandardHighlightColor": "cyan",
		"redStandardHighlightColor": "red",
		"magentaStandardHighlightColor": "magenta",
		"yellowStandardHighlightColor": "yellow",
		"orangeStandardHighlightColor": "orange",
		"whiteStandardHighlightColor": "white",
		"blackStandardHighlightColor": "black",
		"miniGraphOverlayColor": ["~", "blue", "panel", 70],
		"featureMapBaseColor": "panel",
		"featureMapNavLineColor": "text",
		"featureMapNavHighlightColor": "selection",
		"featureMapDataVariableColor": "blue",
		"featureMapAsciiStringColor": "yellow",
		"featureMapUnicodeStringColor": "cyan",
		"featureMapFunctionColor": "green",
		"featureMapImportColor": "magenta",
		"featureMapExternColor": "orange",
		"featureMapLibraryColor": "muted",
		"sidebarBackgroundColor": "panel",
		"sidebarInactiveIconColor": "muted",
		"sidebarHoverIconColor": "text",
		"sidebarActiveIconColor": "blue",
		"sidebarFocusedIconColor": "cyan",
		"sidebarHoverBackgroundColor": "panelAlt",
		"sidebarActiveBackgroundColor": "selection",
		"sidebarFocusedBackgroundColor": "outline",
		"sidebarActiveIndicatorLineColor": "blue",
		"sidebarHeaderBackgroundColor": "panelAlt",
		"sidebarHeaderTextColor": "text",
		"sidebarWidgetBackgroundColor": "bg",
		"activePaneBackgroundColor": "panel",
		"inactivePaneBackgroundColor": "bg",
		"focusedPaneBackgroundColor": "panelAlt",
		"tabBarTabActiveColor": "panel",
		"tabBarTabHoverColor": "panelAlt",
		"tabBarTabInactiveColor": "bg",
		"tabBarTabBorderColor": "outline",
		"tabBarTabGlowColor": "blue",
		"statusBarServerConnectedColor": "green",
		"statusBarServerDisconnectedColor": "red",
		"statusBarServerWarningColor": "yellow",
		"statusBarProjectColor": "blue",
		"braceOption1Color": "blue",
		"braceOption2Color": "green",
		"braceOption3Color": "cyan",
		"braceOption4Color": "magenta",
		"braceOption5Color": "yellow",
		"braceOption6Color": "orange",
		"voidTypeColor": "muted",
		"structureTypeColor": "cyan",
		"enumerationTypeColor": "green",
		"functionTypeColor": "magenta",
		"boolTypeColor": "orange",
		"integerTypeColor": "yellow",
		"floatTypeColor": "cyan",
		"pointerTypeColor": "blue",
		"arrayTypeColor": "green",
		"varArgsTypeColor": "red",
		"valueTypeColor": "text",
		"namedTypeReferenceColor": "cyan",
		"wideCharTypeColor": "yellow",
	},
}
