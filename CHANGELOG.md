# Changelog

All notable changes to `markview` are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versioning follows [SemVer](https://semver.org/).

## [Unreleased]

## [0.4.0] — 2026-04-13

### Added
- **Command palette** (`Ctrl+P`) — a borderless fuzzy-filter popup over actions, headings in the current document, and markdown files in the current folder. Arrow keys navigate, Enter activates, Esc dismisses.
- **Folder-wide full-text search** (`Ctrl+Shift+F`) — recursive `.md` search with context snippets; selecting a result opens the file and jumps to the line. Skips `.git`, `node_modules`, `.venv`, `__pycache__`.
- **Semantic scroll-sync** — in Split view, the preview scrolls to the heading containing the editor cursor. Debounced 80 ms.
- **Interactive checkboxes in preview** — click a rendered `- [ ]` / `- [x]` to toggle it. Round-trips to the buffer (edit mode) or the file on disk (preview mode) via a WebKit ↔ Python message bridge; self-saves suppress the file-monitor reload.
- **Paste image → `./assets/`** — pasting an image (`Ctrl+V`) in the editor writes a timestamped PNG to `<doc>/assets/` and inserts a relative `![](...)` link. Untitled buffers use `~/Pictures/markview/` with an absolute path.

### Notes
- No new toolbar buttons — every new feature is keyboard-only to keep the chrome minimal.
- Palette window is borderless, modal to the main window, closes on focus-out or Esc.
- Source-line markers on checkboxes are injected via a markdown preprocessor that respects fenced code (task syntax inside code blocks is left alone).

## [0.3.1] — 2026-04-13

### Fixed
- Replaced deprecated `Gtk.Widget.override_font` with a `GtkCssProvider` targeting the editor `textview`. Quiets the runtime `DeprecationWarning` and the editor font is now applied via CSS.

## [0.3.0] — 2026-04-13

### Added
- **Edit toolbar** revealed below the header when edit mode is active. Groups:
  - File: **New** (`Ctrl+N`), **Save** (`Ctrl+S`), **Save As** (`Ctrl+Shift+S`).
  - History: **Undo** (`Ctrl+Z`), **Redo** (`Ctrl+Shift+Z` or `Ctrl+Y`).
  - Clipboard: **Cut**, **Copy**, **Paste**.
  - Formatting: **Bold** (`Ctrl+B`), **Italic** (`Ctrl+I`), **Strikethrough**, **Heading** (`Ctrl+H`), **Link** (`Ctrl+K`), **Inline code**, **Quote**, **Bulleted list**, **Numbered list**, **Checklist item**, **Image**, **Horizontal rule**.
  - View: segmented **Editor / Split / Preview** toggle.
  - Find: **Find** button + `Ctrl+F` reveals a search bar with next/prev.
- **Split view** with live preview — editor left, rendered view right, auto-refreshing 220ms after you stop typing.
- **Untitled buffer** — `New` starts a fresh document that prompts for a location on first save.
- **Discard-changes confirmation** dialog when opening/creating a file with unsaved edits.
- GtkSourceView-based editor: native undo/redo, markdown syntax highlighting, line numbers, current-line highlight, style scheme that tracks the theme.
- Image insert dialog computes a path relative to the current file's folder when possible.

### Changed
- Central content area rebuilt dynamically for the active mode/view (preview / editor / split).
- Dirty-state indicator uses a small bullet (`•`) in the header title; subtitle shows `(unsaved)` for untitled buffers.
- Leaving edit mode prompts to save when the buffer is dirty.

## [0.2.0] — 2026-04-13

### Added
- **Edit mode.** Toggle button in the header (between Open and Reload) flips the view to a plain text editor for the current file.
- `Ctrl+E` toggles edit mode; `Ctrl+S` saves the buffer to disk.
- Dirty indicator (`•`) appended to the window title when the editor buffer has unsaved changes.
- Edit button is disabled on the welcome screen (no file open); enabled once a file is loaded.

### Changed
- Live-reload file monitor is paused while in edit mode so in-flight edits are never clobbered by a self-triggered reload.
- Preview and editor share a `Gtk.Stack` with a short crossfade transition.

## [0.1.0] — 2026-04-13

### Added
- Initial release: GTK3 + WebKit2 markdown viewer for Linux.
- Light/dark theme auto-detected from system, toggle with `Ctrl+D`.
- Syntax highlighting via Pygments.
- Live reload on file save (GIO file monitor).
- Drag-and-drop of `.md` files onto the window.
- Keyboard shortcuts: `Ctrl+O` open, `Ctrl+R` reload, `Ctrl+D` theme, `Ctrl+Q` quit.
- Markdown extensions: fenced code, tables, TOC, footnotes, admonitions, def lists, abbr.
- `install.sh` / `uninstall.sh` — user-local install with `.desktop` entry and PATH shim.
- Welcome screen when launched with no file argument.
