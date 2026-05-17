# Theme Ninja

Theme Ninja is a Binary Ninja UI plugin for creating, editing, previewing, refreshing, and activating `.bntheme` files without restarting Binary Ninja.

## Features

- Lists themes from the user `themes`, `community-themes`, and `community_themes` folders.
- Refreshes Binary Ninja's theme registry in place.
- Activates any listed theme from the plugin.
- Creates new themes from a complete starter template.
- Duplicates existing themes into the writable `themes` folder.
- Edits `colors`, `palette`, `disabledPalette`, and `theme-colors` entries.
- Provides a live in-plugin preview for disassembly, graph, hex, sidebar, tab, and console colors.
- Writes a one-time `.bak` backup before modifying an existing theme.
- Supports a temporary "Preview in BN" theme so unsaved edits can be tested in the actual UI.

## Install

Place this folder in Binary Ninja's user plugin directory:

```text
~/Library/Application Support/Binary Ninja/plugins/ThemeNinja
```

On macOS, the user plugin directory is available from Binary Ninja through:

```python
import binaryninja
binaryninja.user_plugin_path()
```

Restart Binary Ninja after installing the plugin itself. Theme edits made through the plugin do not require restarts.

## Use

Open `Plugins -> Theme Ninja`, or open the `Theme Ninja` sidebar item. The pane layout is the most comfortable way to work when editing many colors.

Use `Preview in BN` for a temporary runtime preview. Use `Save && Apply` when the theme is ready to become the active Binary Ninja theme.

## Notes

Theme Ninja preserves Binary Ninja color expressions when they are not edited. Editing a value with the color picker writes a direct `#rrggbb` or `#rrggbbaa` value for that entry, which is intentional for predictable visual editing.
