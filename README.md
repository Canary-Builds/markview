# markview

Minimal, modern markdown viewer for Linux. GTK3 + WebKit, ~300 lines of Python, no Electron.

## Features

- Clean, GitHub-flavoured light/dark reading view
- Syntax highlighting (Pygments)
- Live reload on file save
- Drag & drop any `.md` onto the window
- Keyboard-first: `Ctrl+O`, `Ctrl+R`, `Ctrl+D`, `Ctrl+Q`
- Supports tables, fenced code, TOC, footnotes, admonitions, def lists

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
                 python3-markdown python3-pygments
```

## Shortcuts

| Key | Action |
|---|---|
| `Ctrl+O` | Open file |
| `Ctrl+R` | Reload current file |
| `Ctrl+D` | Toggle light/dark |
| `Ctrl+Q` | Quit |
| Drop `.md` | Open the dropped file |

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
