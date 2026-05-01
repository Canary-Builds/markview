# Changelog

All notable changes to `VertexWrite` are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versioning follows [SemVer](https://semver.org/).

## [Unreleased]

## [0.6.6] — 2026-05-01

### Fixed
- Resizing the sidebar now keeps folder-tree names visible instead of clipping the right side of deeply indented rows first.

## [0.6.5] — 2026-05-01

### Added
- **Resizable document sidebar.** The left sidebar can now be resized against the editor/preview, and the recent-documents/folder-tree split can be resized inside the sidebar.
- **File-based folder tree selection.** The sidebar can now choose a markdown file and then display the folder containing that file.

### Changed
- The final VertexWrite logo is now sourced from `vertexwrite-logo.png`, with Linux hicolor icons and the Windows `.ico` regenerated from that logo.

### Fixed
- Linux startup now defaults `WEBKIT_DISABLE_DMABUF_RENDERER=1` before WebKitGTK loads, avoiding a GBM/EGL abort seen on some NVIDIA driver stacks.

## [0.6.4] — 2026-05-01

### Added
- **Welcome actions for new documents, opening files, and showing the sidebar.** The start screen now exposes the common first actions directly instead of relying only on shortcuts or the header.
- **Document sidebar layout.** `Ctrl+Shift+O` now opens a left pane with recent documents at the top and a folder tree at the bottom.

### Changed
- Opening a saved file while the sidebar is visible now binds the folder tree to that file's folder. If the sidebar is opened later, it initializes from the current file.
- Sidebar wording in menus, shortcuts, and docs now reflects the recent-documents/folder-tree behavior.

## [0.6.3] — 2026-05-01

### Changed
- Public documentation, examples, and release references now consistently use the VertexWrite product name and `vertexwrite` command/package identifiers.
- Changelog and packaging notes now describe legacy compatibility generically while keeping the runtime migration cleanup in place.

## [0.6.2] — 2026-05-01

### Changed
- **Final product rename to VertexWrite.** Linux, Windows, source, Debian, Snap, Flatpak, desktop, AppStream, and release assets now use the VertexWrite name consistently.
- **Package and command identifiers now use `vertexwrite`.** The Linux CLI, Windows executable, installer outputs, app IDs, config/state paths, docs, and release artifacts now match the VertexWrite brand.

### Compatibility
- Existing legacy config/state directories are still read when the new `vertexwrite` directories do not exist.
- Source install and uninstall cleanup remove stale legacy launchers, desktop entries, and icons.

## [0.6.1] — 2026-04-27

### Fixed
- **Windows GitHub release builds now install Inno Setup reliably again.** The release workflow now installs Inno Setup directly on the runner instead of depending on the failing third-party setup action.
- **Release recovery is now manual-dispatchable.** The Windows release workflow accepts an optional tag input so an existing tag can be rebuilt and re-attached without moving tags or cutting ad hoc hotfixes.
- **CI pytest now runs against the shared core module with the Python markdown dependencies installed.** The release branch no longer shows a false-red CI failure caused by importing the GTK frontend under the isolated Actions Python environment.

## [0.6.0] — 2026-04-27

### Changed
- **Full product rename to VertexWrite.** The application name, executable names, installer names, desktop entry, app IDs, config/state directories, documentation, and release workflow assets now use the VertexWrite branding consistently.
- **Windows packaging outputs were renamed.** PyInstaller now builds `dist\\vertexwrite\\vertexwrite.exe` and Inno Setup now emits `vertexwrite-<version>-win-setup.exe`.

### Added
- **GitHub tag releases now ship source archives too.** In addition to the Windows installer, tagged releases now attach `vertexwrite-<version>-source.zip` and `vertexwrite-<version>-source.tar.gz` for source installs and downstream packaging.

### Fixed
- **Windows runtime validation now covers the renamed bundle.** The source frontend imports cleanly, the packaged Qt bundle smoke test passes, and the rebuilt Windows installer is generated from the new names without stale legacy paths.

## [0.5.4] — 2026-04-22

### Added
- **Windows support is now a first-class release target.** The repo now includes a Windows frontend (`vertexwrite_win.py`), PyInstaller spec, Inno Setup installer script, Windows version metadata, and a smoke test for the packaged Qt runtime.
- **Automated Windows release workflow.** Tag pushes matching `v*` now build the Windows installer on GitHub Actions and attach it to the GitHub Release.

### Fixed
- **Windows Qt packaging no longer strips required runtime DLLs.** The PyInstaller build now keeps the Qt QML/WebEngine dependencies required by `QtWebChannel` and `QtWebEngine`.
- **Windows menu construction is PyQt6-compatible.** Menu actions now use explicit `QAction` wiring instead of fragile overloaded `addAction(...)` calls.

### Changed
- Repository documentation now reflects the supported platforms as **Linux and Windows**.
- Repository versioning is now aligned to `0.5.4` for the release tag, README badge, changelog, and both application entry points.

## [0.5.3] — 2026-04-13

### Fixed
- **Keyboard Shortcuts menu action works on GTK3 builds.** `Gtk.ShortcutsWindow` now uses a compatibility fallback (`add_section` when available, otherwise `add`) so Menu → Keyboard Shortcuts opens reliably.
- **What’s New now finds packaged changelogs.** The app now checks common installed paths (`/usr/share/doc/vertexwrite/CHANGELOG.md`, `.gz`, and `changelog.gz`) instead of only local source paths.
- **GtkSource compatibility for runtime variants.** VertexWrite now prefers GtkSource 5 with a fallback to 4 so the same app code runs on modern Flatpak GNOME runtimes and Debian/Ubuntu packages.

### Changed
- README install section now includes store/package-manager install entries for **Ubuntu PPA (apt)**, **Snapcraft**, and **Flathub**, including visual badges.

## [0.5.2] — 2026-04-13

### Added
- **Help menu** — hamburger button on the right side of the header bar with:
  - **Keyboard Shortcuts** — opens a native `Gtk.ShortcutsWindow` grouped by File / View / Navigation / Editing / Formatting.
  - **What’s New in `<version>`** — pops the latest CHANGELOG section in a styled WebKit dialog. Auto-shown once the first time a new version launches (skipped on first ever install).
  - **Documentation** — opens the GitHub Wiki.
  - **Report an Issue** — opens the GitHub issue chooser.
  - **Visit Canary Builds** — opens [https://canarybuilds.com/](https://canarybuilds.com/).
  - **About VertexWrite** — `Gtk.AboutDialog` with version, credits, MIT license, app icon, and developer link.
- All help-menu entries are also surfaced in the command palette (`Ctrl+P`).
- Last-shown-version pin at `~/.local/state/vertexwrite/last-shown-version` so the upgrade dialog appears exactly once per release.

### Notes
- Developer is now declared as **Canary Builds** (https://canarybuilds.com/) in About + menu.
- No keyboard shortcuts changed; the menu is keyboard-discoverable via the palette and click-discoverable via the header.

## [0.5.1] — 2026-04-13

### Fixed
- **Find toolbar button now toggles.** It previously always called `_toggle_find(True)` so clicking the icon a second time did nothing. The button is now a `Gtk.ToggleButton` whose state is kept in sync with `find_bar.search_mode_enabled`, so clicking the icon (or pressing Esc, or pressing Ctrl+F again) closes the search bar as expected.

### Changed (toolbar declutter)
- 24 toolbar buttons collapsed to 12 visible elements. No keyboard shortcut or palette action changed.
- **Removed Cut / Copy / Paste buttons** — `Ctrl+X` / `Ctrl+C` / `Ctrl+V` are universal, and the smart-paste handler keeps Ctrl+V special.
- **Removed Save As button** — `Ctrl+Shift+S` and the palette still expose it; Save's tooltip notes the shortcut.
- **Block-formatting popovers** for less-frequent actions:
  - Heading menu: H1 / H2 / H3 / H4 / Clear · Quote · Horizontal rule.
  - Lists menu: Bulleted / Numbered / Checklist.
  - Insert menu: Image / Table / Strikethrough.
- New `_set_heading_level(N)` properly replaces existing heading prefixes (so H2 on an H1 line yields `## …`, not `## # …`); `Ctrl+H` now uses it for H1.

## [0.5.0] — 2026-04-13

### Added (17 new features — all keyboard-activated, no new visible chrome)

**Navigation**
- **Outline sidebar** — `Ctrl+Shift+O` reveals a slide-in panel listing every heading with click-to-jump.
- **Back/forward navigation** — `Alt+←` / `Alt+→` walks a history stack of (file, cursor line) populated automatically on opens and palette jumps.

**Editing**
- **Smart paste** — `Ctrl+V` picks the right thing per clipboard contents: image (saved to `./assets/`), HTML (converted to markdown via `html2text` or built-in fallback), CSV/TSV (converted to a markdown table), or plain text.
- **Smart list continuation** — `Enter` at the end of `- `, `1. `, or `- [ ] ` auto-inserts the next bullet/number/task; `Enter` on an empty one exits the list.
- **Block move** — `Alt+↑` / `Alt+↓` moves the current line (or selected lines) as a unit.

**Preview & output**
- **KaTeX math** rendered in the preview — supports `$...$`, `$$...$$`, `\(...\)`, `\[...\]` delimiters via KaTeX auto-render (CDN).
- **Mermaid diagrams** — fenced ```mermaid blocks render as live diagrams.
- **Transclusion** — `![[other-note]]` or `![[other-note#Section]]` in a document inlines the target file (or a section of it) into the preview; max 4-level depth, fenced-code-aware.
- **Print stylesheet** — `@media print` rules for clean, high-contrast output.
- **Custom preview CSS** — drop a file at `~/.config/vertexwrite/custom.css` and it's appended to the rendered style on every load.

**Palette actions (`Ctrl+P`)**
- **Open from URL…** — fetches the URL, converts HTML → markdown if the response is HTML, opens as an untitled buffer.
- **Insert table…** — prompt for rows × columns, inserts a skeleton markdown table.
- **Show all tasks in folder…** — palette view of every `- [ ]` / `- [x]` across the folder; Enter jumps to the task.
- **Show backlinks to this file** — scans the folder for `[text](this-file.md)` and `[[this-file]]` references and lists them.
- **Check links in current buffer** — flags relative links/images whose targets don't exist on disk.
- **View snapshot history…** — opens any of the last 30 auto-saved snapshots in preview.
- **Export as PDF / DOCX / HTML / EPUB (via pandoc)** — shells out to `pandoc` when present; clear error if not installed.

**Craft**
- **Typewriter mode** — `Ctrl+Shift+T` toggles vertical-center cursor behavior.
- **Word count + reading time** — small dim label on the far right of the edit toolbar (hidden when no doc is open).

**Persistence**
- **Snapshot on save** — each `_write_to` also drops a copy into `~/.local/state/vertexwrite/snapshots/<hash>-<stem>/<timestamp>.md`. Keeps the latest 30 per document.

### Deferred
- Vim keybindings
- Full spreadsheet-style table editor (only the `Insert table…` prompt ships)
- LanguageTool grammar integration (spell-check was not available via stock GTK3 in this release)
- Front-matter as a structured form (raw YAML remains in the editor)

## [0.4.0] — 2026-04-13

### Added
- **Command palette** (`Ctrl+P`) — a borderless fuzzy-filter popup over actions, headings in the current document, and markdown files in the current folder. Arrow keys navigate, Enter activates, Esc dismisses.
- **Folder-wide full-text search** (`Ctrl+Shift+F`) — recursive `.md` search with context snippets; selecting a result opens the file and jumps to the line. Skips `.git`, `node_modules`, `.venv`, `__pycache__`.
- **Semantic scroll-sync** — in Split view, the preview scrolls to the heading containing the editor cursor. Debounced 80 ms.
- **Interactive checkboxes in preview** — click a rendered `- [ ]` / `- [x]` to toggle it. Round-trips to the buffer (edit mode) or the file on disk (preview mode) via a WebKit ↔ Python message bridge; self-saves suppress the file-monitor reload.
- **Paste image → `./assets/`** — pasting an image (`Ctrl+V`) in the editor writes a timestamped PNG to `<doc>/assets/` and inserts a relative `![](...)` link. Untitled buffers use `~/Pictures/vertexwrite/` with an absolute path.

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
