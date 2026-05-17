# Theme Ninja

Theme Ninja is a Binary Ninja UI plugin for creating, editing, previewing, and activating `.bntheme` files without restarting Binary Ninja.

## Features

- Lists themes from the user `themes`, `community-themes`, and `community_themes` folders.
- Refreshes Binary Ninja's theme registry in place.
- Activates any listed theme from the plugin.
- Creates new themes from a complete starter template.
- Duplicates existing themes into the writable `themes` folder.
- Edits `colors`, `palette`, `disabledPalette`, and `theme-colors` entries.
- Provides a live in-plugin preview for disassembly, sidebar, tab, status, and console colors.
- Writes a one-time `.bak` backup before modifying an existing theme.

## Install

Place this folder in Binary Ninja's user plugin directory as `ThemeNinja`. The most reliable way to find that directory on any platform is from Binary Ninja's Python console:

```python
import binaryninja
binaryninja.user_plugin_path()
```

Common defaults are:

```text
macOS:   ~/Library/Application Support/Binary Ninja/plugins/ThemeNinja
Linux:   ~/.binaryninja/plugins/ThemeNinja
Windows: %APPDATA%\Binary Ninja\plugins\ThemeNinja
```

Restart Binary Ninja after installing the plugin itself. Theme edits made through the plugin do not require restarts.

## Use

Open `Plugins -> Theme Ninja`. The sidebar button is off by default; enable `themeNinja.showSidebarWidget` in Binary Ninja settings if you want it available in the sidebar after restart.

Use `Save` to persist edits. Use `Apply Theme` to make the selected theme active; after an edit, that same button becomes `Save & Apply`.

## Notes

Theme Ninja preserves Binary Ninja color expressions when they are not edited. Editing a value with the color picker writes a direct `#rrggbb` or `#rrggbbaa` value for that entry, which is intentional for predictable visual editing.
