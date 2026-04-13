# markview

> Minimal, modern markdown viewer **and editor** for Linux — GTK3 + WebKit + GtkSourceView.
> No Electron, no tray daemon, no account. Starts in under a second.

[![version](https://img.shields.io/badge/version-0.5.0-blue)](CHANGELOG.md)
[![license](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![platform](https://img.shields.io/badge/platform-Linux-lightgrey)](#install)

<p align="center">
  <img src="icon.png" width="128" alt="markview logo">
</p>

---

## What it is

A single Python script that turns any `.md` file into a clean, themeable reading view — and when you hit `Ctrl+E` it becomes a proper editor with a 13-button formatting toolbar, a command palette, folder-wide search, an outline sidebar, live split-view preview with scroll-sync, auto-save snapshots, and live math / diagrams.

The chrome stays minimal: **three buttons in the header**, one toolbar that only appears in edit mode, everything else is keyboard-driven.

## Features

### Viewing
- GitHub-flavoured light/dark theme, auto-detected from your GTK settings
- Pygments syntax highlighting in code blocks
- Live reload when the file changes on disk
- Drag-and-drop any `.md` onto the window

### Editing (`Ctrl+E`)
- Full toolbar: **New · Save · Save As · Undo · Redo · Cut · Copy · Paste**
- Formatting: **Bold · Italic · Strikethrough · Heading · Link · Inline code · Quote · Lists · Checklist · Image · HR**
- **Split view** with semantic scroll-sync (preview follows editor cursor)
- **Smart paste** — images → `./assets/`, HTML → markdown, CSV → table
- **Smart list continuation** (Enter in a list auto-continues; empty bullet exits)
- **Block move** (`Alt+↑` / `Alt+↓`)
- **Typewriter mode** (`Ctrl+Shift+T`) — keep the cursor vertically centered
- Native **undo/redo** via GtkSourceView; word count + reading time in the toolbar

### Preview extras
- **KaTeX** math (`$x^2$`, `$$\int$$`, `\(…\)`, `\[…\]`)
- **Mermaid** diagrams in ` ```mermaid ` fences
- **Transclusion** — `![[other-note]]` or `![[other-note#Section]]`
- **Click-to-toggle task checkboxes** in preview — round-trips to source
- **Print stylesheet** and a **custom CSS drop-in** (`~/.config/markview/custom.css`)
- Tables, footnotes, admonitions, definition lists, abbreviations

### Navigation
- **Command palette** (`Ctrl+P`) — fuzzy jump to actions, headings, or files in the folder
- **Folder full-text search** (`Ctrl+Shift+F`) — recursive `.md`, context snippets
- **Outline sidebar** (`Ctrl+Shift+O`) — slide-in heading tree
- **Back / forward** (`Alt+←` / `Alt+→`) — history of opened files + cursor lines

### Palette actions (Ctrl+P)
Open / New / Save · Toggle edit / split / preview · Outline · Typewriter · Reload · Theme · Folder search · **Open from URL** · **Insert table** · **All tasks in folder** · **Backlinks to this file** · **Check links** · **Snapshot history** · **Export PDF / DOCX / HTML / EPUB** via pandoc.

### Persistence
- Every save writes a dated copy to `~/.local/state/markview/snapshots/`. Latest 30 per document; browse with the palette.

## Install

### Ubuntu 22.04+ / Debian 12+

```bash
sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-webkit2-4.1 \
                 gir1.2-gtksource-4 python3-markdown python3-pygments

git clone https://github.com/Canary-Builds/markview.git ~/markview
cd ~/markview && ./install.sh
```

### Arch

```bash
sudo pacman -S python-gobject gtk3 webkit2gtk-4.1 gtksourceview4 \
               python-markdown python-pygments
```

### Fedora

```bash
sudo dnf install python3-gobject gtk3 webkit2gtk4.1 gtksourceview4 \
                 python3-markdown python3-pygments
```

### Optional

| Dep | Adds |
|---|---|
| `pandoc` | PDF / DOCX / HTML / EPUB export from the palette |
| `python3-html2text` | Higher-quality HTML-clipboard → markdown conversion |
| internet | KaTeX + Mermaid (loaded from a CDN on each render) |

## Run

```bash
markview                 # welcome screen
markview notes.md        # open a file
markview -V              # version
```

Or right-click any `.md` → **Open With → markview**.

## Shortcuts

| Key | Action |
|---|---|
| `Ctrl+O` | Open file |
| `Ctrl+N` | New document |
| `Ctrl+S` / `Ctrl+Shift+S` | Save / Save As |
| `Ctrl+E` | Toggle edit mode |
| `Ctrl+P` | Command palette |
| `Ctrl+F` / `Ctrl+Shift+F` | Find in buffer / Search in folder |
| `Ctrl+Shift+O` | Toggle outline sidebar |
| `Ctrl+Shift+T` | Toggle typewriter mode |
| `Ctrl+R` | Reload from disk |
| `Ctrl+D` | Toggle theme |
| `Ctrl+Q` | Quit |
| `Alt+←` / `Alt+→` | Back / forward |
| `Alt+↑` / `Alt+↓` | Move line/selection |
| `Ctrl+B / I / K / H` | Bold / Italic / Link / Heading |
| `Ctrl+Z` / `Ctrl+Shift+Z` | Undo / Redo |

Full reference: [`docs/wiki/Keyboard-Shortcuts.md`](docs/wiki/Keyboard-Shortcuts.md).

## Configuration

markview is configuration-free by default. Optional drop-ins:

| Path | Purpose |
|---|---|
| `~/.config/markview/custom.css` | Appended to the preview stylesheet on every render |
| `<doc>/assets/` | Where pasted images land (auto-created) |
| `~/.local/state/markview/snapshots/` | Auto-save history |

See [Configuration](docs/wiki/Configuration.md) for details.

## Layout

```
markview/
├── markview.py         # single-file app (~1500 lines)
├── style.css           # preview theme (light/dark/print)
├── icon-final.png      # master icon (1536×1024 source)
├── icon.png            # 512×512 square (installed via install.sh)
├── icon-{16..256}.png  # hicolor sizes
├── markview.desktop    # desktop entry template
├── install.sh          # user-local installer
├── uninstall.sh
├── CHANGELOG.md
├── ROADMAP.md
├── CONTRIBUTING.md
├── LICENSE
├── .github/            # issue + PR templates, CI
└── docs/wiki/          # wiki pages (mirrored to the GitHub wiki)
```

## Architecture (TL;DR)

Render pipeline: `markdown` + custom preprocessors (tasks, transclusion) → HTML → WebKit. Editor is GtkSourceView with markdown syntax highlighting. A JS bridge handles checkbox clicks and `scrollToAnchor(slug)` messages. See [Architecture](docs/wiki/Architecture.md).

## Roadmap

Planned features and the ones intentionally skipped live in [ROADMAP.md](ROADMAP.md).

## Contributing

Pull requests welcome — please read [CONTRIBUTING.md](CONTRIBUTING.md) first. Small, focused PRs against `main`.

## License

MIT — see [LICENSE](LICENSE).

## Acknowledgments

- [python-markdown](https://python-markdown.github.io/) + [Pygments](https://pygments.org/) for rendering
- [GtkSourceView](https://wiki.gnome.org/Projects/GtkSourceView) for the editor
- [KaTeX](https://katex.org/) and [Mermaid](https://mermaid.js.org/) for math and diagrams
