# markview

Minimal, modern markdown viewer + editor for Linux. GTK3 + WebKit + GtkSourceView, no Electron.

## Features

### Viewing
- Clean, GitHub-flavoured light/dark reading view
- Syntax highlighting (Pygments)
- Live reload when the file changes on disk
- Drag & drop any `.md` onto the window
- Supports tables, fenced code, TOC, footnotes, admonitions, def lists

### Editing (Ctrl+E)
- Full edit toolbar: **New / Save / Save As / Undo / Redo / Cut / Copy / Paste**
- Markdown formatting buttons: **Bold, Italic, Strikethrough, Heading, Link, Code, Quote, Lists, Checklist, Image, Horizontal rule**
- **Split view** with live preview — type on the left, watch the render update on the right
- **Semantic scroll-sync** — in split view, the preview follows the editor cursor by heading
- **Paste an image** — `Ctrl+V` saves the clipboard image to `./assets/` and inserts a relative `![](...)`
- Find bar with next / previous (Ctrl+F)
- GtkSourceView editor with markdown syntax highlighting + undo history

### Navigation
- **Command palette** (`Ctrl+P`) — fuzzy jump to actions, headings, or files in the folder
- **Folder search** (`Ctrl+Shift+F`) — recursive full-text search with context snippets
- **Click checkboxes in preview** — toggles `- [ ]` / `- [x]` in the source

## Run

```bash
python3 ~/markview/markview.py            # welcome screen
python3 ~/markview/markview.py notes.md   # open a file
```

## Install system-wide (user-local)

Registers `markview` on your PATH and adds a `.desktop` entry so you can right-click → Open with → markview.

```bash
~/markview/install.sh
markview notes.md
```

Uninstall with `~/markview/uninstall.sh`. Source files remain at `~/markview/`.

## Requirements

Pre-installed on Ubuntu 24.04. If missing:

```bash
sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-webkit2-4.1 \
                 gir1.2-gtksource-4 python3-markdown python3-pygments
```

## Shortcuts

### File / view / nav
| Key | Action |
|---|---|
| `Ctrl+O` | Open file |
| `Ctrl+N` | New untitled document |
| `Ctrl+S` | Save |
| `Ctrl+Shift+S` | Save As |
| `Ctrl+R` | Reload current file |
| `Ctrl+E` | Toggle edit mode |
| `Ctrl+P` | Command palette (actions · headings · files) |
| `Ctrl+F` | Find in current buffer (edit mode) |
| `Ctrl+Shift+F` | Search in folder |
| `Ctrl+D` | Toggle light/dark |
| `Ctrl+Q` | Quit |
| Drop `.md` | Open the dropped file |

### Edit
| Key | Action |
|---|---|
| `Ctrl+Z` / `Ctrl+Shift+Z` | Undo / Redo |
| `Ctrl+X / C / V` | Cut / Copy / Paste |
| `Ctrl+B` | Bold |
| `Ctrl+I` | Italic |
| `Ctrl+K` | Link |
| `Ctrl+H` | Heading |

## Layout

```
~/markview/
├── markview.py       # main app
├── style.css         # theme
├── icon.svg          # app icon
├── markview.desktop  # desktop entry template
├── install.sh        # optional install
├── uninstall.sh
└── README.md
```
