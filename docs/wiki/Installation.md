# Installation

markview can be installed on Windows from GitHub Releases, on Linux from Ubuntu PPA (`apt`), Snapcraft, Flathub (Flatpak), or from source.

## Quick install (recommended)

### Windows installer

Download the latest `markview-<version>-win-setup.exe` from the GitHub Releases page:

- https://github.com/Canary-Builds/markview/releases

The Windows installer is built from the repo's release workflow and installs the packaged PyQt6 application.

### Ubuntu App Center / APT (PPA)

```bash
sudo add-apt-repository ppa:mareekkk/canarybuilds
sudo apt update
sudo apt install markview
```

### Snapcraft

```bash
sudo snap install markview
```

### Flatpak (Flathub)

```bash
flatpak install flathub com.canarybuilds.Markview
flatpak run com.canarybuilds.Markview
```

If Flathub says the app is not found yet, it means the submission is still under review/publishing.

Arch/Manjaro AUR and Fedora packaging are planned but not yet published. Track this in [ROADMAP.md](../../ROADMAP.md).

## Linux source install (manual)

Use this if you want local development or if your distro package is not available yet.

## Required packages

| Package | Purpose |
|---|---|
| `python3` >= 3.10 | Runtime |
| `python3-gi` | PyGObject bindings |
| `GTK 3` typelib | UI toolkit |
| `WebKit2 4.1` typelib | Preview rendering |
| `GtkSourceView` typelib | Editor widget |
| `python3-markdown` | Markdown renderer |
| `python3-pygments` | Code syntax highlighting |

## Optional packages

| Package | Adds |
|---|---|
| `pandoc` | PDF / DOCX / HTML / EPUB export |
| `python3-html2text` | Better HTML clipboard -> markdown conversion |

### Ubuntu 22.04+ / Debian 12+

```bash
sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-webkit2-4.1 \
                 gir1.2-gtksource-4 python3-markdown python3-pygments
# optional
sudo apt install pandoc python3-html2text
```

## Verify dependencies

```bash
python3 - <<'PY'
import gi
gi.require_version('Gtk', '3.0')
gi.require_version('WebKit2', '4.1')
try:
    gi.require_version('GtkSource', '5')
except ValueError:
    gi.require_version('GtkSource', '4')

import markdown, pygments
print('GTK/WebKit/GtkSource + markdown + pygments: ok')
PY
```

## Install from source

```bash
git clone https://github.com/Canary-Builds/markview.git ~/markview
cd ~/markview
./install.sh
```

This creates:

| Path | Purpose |
|---|---|
| `~/.local/bin/markview` | CLI wrapper |
| `~/.local/share/applications/markview.desktop` | Desktop launcher entry |
| `~/.local/share/icons/hicolor/<size>/apps/markview.png` | App icons |

Ensure `~/.local/bin` is in your `PATH`:

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
```

## Run

```bash
markview
markview README.md
markview -V
```

Windows source run:

```powershell
py .\markview_win.py
```

## Windows build from source

```powershell
py -3.13 -m pip install -r requirements-win.txt pyinstaller
powershell -ExecutionPolicy Bypass -File .\build_win.ps1
```

Outputs:

| Path | Purpose |
|---|---|
| `dist\markview\markview.exe` | packaged Windows app |
| `installer_output\markview-<version>-win-setup.exe` | Windows installer |

## Uninstall source install

```bash
~/markview/uninstall.sh
```
