# VertexMarkdown

> Minimal, modern markdown viewer **and editor** for Linux and Windows.
> GTK3 + WebKit on Linux. PyQt6 + QtWebEngine on Windows.
> No Electron, no tray daemon, no account. Starts in under a second.

[![version](https://img.shields.io/badge/version-0.6.1-blue)](CHANGELOG.md)
[![license](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![platform](https://img.shields.io/badge/platform-Linux%20%7C%20Windows-lightgrey)](#install)
[![snap](https://img.shields.io/badge/Snapcraft-vertexmarkdown-E95420?logo=snapcraft&logoColor=white)](https://snapcraft.io/vertexmarkdown)
[![ubuntu-ppa](https://img.shields.io/badge/Ubuntu%20PPA-mareekkk%2Fcanarybuilds-E95420?logo=ubuntu&logoColor=white)](https://launchpad.net/~mareekkk/+archive/ubuntu/canarybuilds)
[![flathub](https://img.shields.io/badge/Flathub-com.canarybuilds.VertexMarkdown-000000?logo=flathub&logoColor=white)](https://flathub.org/apps/com.canarybuilds.VertexMarkdown)

<p align="center">
  <img src="icon.png" width="128" alt="VertexMarkdown logo">
</p>

## Screenshots

<p align="center">
  <a href="docs/screenshots/01-preview.png"><img src="docs/screenshots/01-preview.png" width="49%" alt="Reading view"></a>
  <a href="docs/screenshots/02-split-view.png"><img src="docs/screenshots/02-split-view.png" width="49%" alt="Split view with live preview"></a>
</p>
<p align="center">
  <a href="docs/screenshots/03-editor.png"><img src="docs/screenshots/03-editor.png" width="32%" alt="Editor with markdown syntax highlighting"></a>
  <a href="docs/screenshots/04-dark-mode.png"><img src="docs/screenshots/04-dark-mode.png" width="32%" alt="Dark theme"></a>
  <a href="docs/screenshots/05-command-palette.png"><img src="docs/screenshots/05-command-palette.png" width="32%" alt="Command palette (Ctrl+P)"></a>
</p>

<p align="center"><sub>Reading view Â· Split view Â· Editor Â· Dark theme Â· Command palette (Ctrl+P)</sub></p>

---

## What it is

A single Python script that turns any `.md` file into a clean, themeable reading view â€” hitting `Ctrl+E` flips it into a proper editor with a focused formatting toolbar, a command palette, folder-wide search, an outline sidebar, live split-view preview with scroll-sync, auto-save snapshots, and live math / diagrams.

The chrome stays minimal: **three buttons in the header**, one toolbar that only appears in edit mode, everything else is keyboard-driven.

## Features

### Viewing
- GitHub-flavoured light/dark theme, auto-detected from your system theme
- Pygments syntax highlighting in code blocks
- Live reload when the file changes on disk
- Drag-and-drop any `.md` onto the window

### Editing (`Ctrl+E`)
- Full toolbar: **New Â· Save Â· Save As Â· Undo Â· Redo Â· Cut Â· Copy Â· Paste**
- Formatting: **Bold Â· Italic Â· Strikethrough Â· Heading Â· Link Â· Inline code Â· Quote Â· Lists Â· Checklist Â· Image Â· HR**
- **Split view** with semantic scroll-sync (preview follows editor cursor)
- **Smart paste** â€” images â†’ `./assets/`, HTML â†’ markdown, CSV â†’ table
- **Smart list continuation** (Enter in a list auto-continues; empty bullet exits)
- **Block move** (`Alt+â†‘` / `Alt+â†“`)
- **Typewriter mode** (`Ctrl+Shift+T`) â€” keep the cursor vertically centered
- Native **undo/redo** via GtkSourceView; word count + reading time in the toolbar

### Preview extras
- **KaTeX** math (`$x^2$`, `$$\int$$`, `\(â€¦\)`, `\[â€¦\]`)
- **Mermaid** diagrams in ` ```mermaid ` fences
- **Transclusion** â€” `![[other-note]]` or `![[other-note#Section]]`
- **Click-to-toggle task checkboxes** in preview â€” round-trips to source
- **Print stylesheet** and a **custom CSS drop-in** (`~/.config/vertexmarkdown/custom.css`)
- Tables, footnotes, admonitions, definition lists, abbreviations

### Navigation
- **Command palette** (`Ctrl+P`) â€” fuzzy jump to actions, headings, or files in the folder
- **Folder full-text search** (`Ctrl+Shift+F`) â€” recursive `.md`, context snippets
- **Outline sidebar** (`Ctrl+Shift+O`) â€” slide-in heading tree
- **Back / forward** (`Alt+â†` / `Alt+â†’`) â€” history of opened files + cursor lines

### Palette actions (Ctrl+P)
Open / New / Save Â· Toggle edit / split / preview Â· Outline Â· Typewriter Â· Reload Â· Theme Â· Folder search Â· **Open from URL** Â· **Insert table** Â· **All tasks in folder** Â· **Backlinks to this file** Â· **Check links** Â· **Snapshot history** Â· **Export PDF / DOCX / HTML / EPUB** via pandoc.

### Persistence
- Every save writes a dated copy to `~/.local/state/vertexmarkdown/snapshots/`. Latest 30 per document; browse with the palette.

## Install

<p align="center">
  <a href="https://snapcraft.io/vertexmarkdown"><img alt="Get it from Snapcraft" src="https://snapcraft.io/vertexmarkdown/badge.svg"></a>
  <a href="https://launchpad.net/~mareekkk/+archive/ubuntu/canarybuilds"><img alt="Install from Ubuntu PPA" src="https://img.shields.io/badge/Ubuntu_App_Center-PPA%20mareekkk%2Fcanarybuilds-E95420?logo=ubuntu&logoColor=white"></a>
  <a href="https://flathub.org/apps/com.canarybuilds.VertexMarkdown"><img alt="Get it on Flathub" src="https://img.shields.io/badge/Flathub-com.canarybuilds.VertexMarkdown-000000?logo=flathub&logoColor=white"></a>
</p>

### Windows

Download the latest Windows installer from [GitHub Releases](https://github.com/Canary-Builds/VertexMarkdown/releases).
Tagged releases also publish `.zip` and `.tar.gz` source archives there for manual installs and downstream packaging.

The Windows build ships as an `.exe` installer built with Inno Setup and includes the packaged PyQt6 runtime.

### Ubuntu (App Center via PPA)

```bash
sudo add-apt-repository ppa:mareekkk/canarybuilds
sudo apt update
sudo apt install vertexmarkdown
```

### Snapcraft

```bash
sudo snap install vertexmarkdown
```

### Flathub

```bash
flatpak install flathub com.canarybuilds.VertexMarkdown
flatpak run com.canarybuilds.VertexMarkdown
```

### Linux source install (Ubuntu 22.04+ / Debian 12+)

```bash
sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-webkit2-4.1 \
                 gir1.2-gtksource-4 python3-markdown python3-pygments

git clone https://github.com/Canary-Builds/VertexMarkdown.git ~/VertexMarkdown
cd ~/VertexMarkdown && ./install.sh
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
| `python3-html2text` | Higher-quality HTML-clipboard â†’ markdown conversion |
| internet | KaTeX + Mermaid (loaded from a CDN on each render) |

### Windows build from source

```powershell
py -3.13 -m pip install -r requirements-win.txt pyinstaller
powershell -ExecutionPolicy Bypass -File .\build_win.ps1
```

This produces:

| Path | Purpose |
|---|---|
| `dist\vertexmarkdown\vertexmarkdown.exe` | packaged Windows app |
| `installer_output\vertexmarkdown-<version>-win-setup.exe` | Windows installer |

## Run

Linux:

```bash
vertexmarkdown           # welcome screen
vertexmarkdown notes.md  # open a file
vertexmarkdown -V  # version
```

Windows:

```powershell
.\dist\vertexmarkdown\vertexmarkdown.exe
py .\vertexmarkdown_win.py README.md
```

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
| `Alt+â†` / `Alt+â†’` | Back / forward |
| `Alt+â†‘` / `Alt+â†“` | Move line/selection |
| `Ctrl+B / I / K / H` | Bold / Italic / Link / Heading |
| `Ctrl+Z` / `Ctrl+Shift+Z` | Undo / Redo |

Full reference: [`docs/wiki/Keyboard-Shortcuts.md`](docs/wiki/Keyboard-Shortcuts.md).

## Configuration

VertexMarkdown is configuration-free by default. Optional drop-ins:

| Path | Purpose |
|---|---|
| `~/.config/vertexmarkdown/custom.css` | Appended to the preview stylesheet on every render |
| `<doc>/assets/` | Where pasted images land (auto-created) |
| `~/.local/state/vertexmarkdown/snapshots/` | Auto-save history |

See [Configuration](docs/wiki/Configuration.md) for details.

## Layout

```
VertexMarkdown/
â”œâ”€â”€ vertexmarkdown.py         # Linux GTK3/WebKit frontend
â”œâ”€â”€ vertexmarkdown_win.py     # Windows PyQt6/QtWebEngine frontend
â”œâ”€â”€ vertexmarkdown_core.py    # shared markdown/rendering helpers
â”œâ”€â”€ style.css           # preview theme (light/dark/print)
â”œâ”€â”€ icon-final.png      # master icon (1536Ã—1024 source)
â”œâ”€â”€ icon.png            # 512Ã—512 square (installed via install.sh)
â”œâ”€â”€ icon-{16..256}.png  # hicolor sizes
â”œâ”€â”€ vertexmarkdown.desktop    # desktop entry template
â”œâ”€â”€ install.sh          # user-local installer
â”œâ”€â”€ build_win.ps1       # Windows bundle + installer helper
â”œâ”€â”€ installer_win.iss   # Inno Setup script
â”œâ”€â”€ requirements-win.txt
â”œâ”€â”€ vertexmarkdown.spec       # PyInstaller spec for Windows
â”œâ”€â”€ uninstall.sh
â”œâ”€â”€ CHANGELOG.md
â”œâ”€â”€ ROADMAP.md
â”œâ”€â”€ CONTRIBUTING.md
â”œâ”€â”€ LICENSE
â”œâ”€â”€ .github/            # issue + PR templates, CI
â””â”€â”€ docs/wiki/          # wiki pages (mirrored to the GitHub wiki)
```

## Architecture (TL;DR)

Render pipeline: `markdown` + shared preprocessors (tasks, transclusion) â†’ HTML â†’ native webview frontend. Linux uses GTK3 + WebKit2. Windows uses PyQt6 + QtWebEngine/QWebChannel. See [Architecture](docs/wiki/Architecture.md).

## Roadmap

Planned features and the ones intentionally skipped live in [ROADMAP.md](ROADMAP.md).

## Contributing

Pull requests welcome â€” please read [CONTRIBUTING.md](CONTRIBUTING.md) first. Small, focused PRs against `main`.

## License

MIT â€” see [LICENSE](LICENSE).

## Acknowledgments

- [python-markdown](https://python-markdown.github.io/) + [Pygments](https://pygments.org/) for rendering
- [GtkSourceView](https://wiki.gnome.org/Projects/GtkSourceView) for the editor
- [KaTeX](https://katex.org/) and [Mermaid](https://mermaid.js.org/) for math and diagrams


