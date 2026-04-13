# Installation

markview is a single Python script plus a CSS file, an icon, and a `.desktop` entry. There's no build step and no Python virtualenv — the dependencies are system packages (GTK, WebKit, GtkSourceView) plus two pip-installable libraries that are usually already present.

## Required

| Package | Purpose |
|---|---|
| `python3` ≥ 3.10 | Runtime |
| `python3-gi` | PyGObject bindings |
| `gir1.2-gtk-3.0` | GTK 3 typelib |
| `gir1.2-webkit2-4.1` | WebKit2 4.1 typelib |
| `gir1.2-gtksource-4` | GtkSourceView 4 typelib |
| `python3-markdown` | Markdown renderer |
| `python3-pygments` | Code syntax highlighting |

## Optional

| Package | Adds |
|---|---|
| `pandoc` | PDF / DOCX / HTML / EPUB export |
| `python3-html2text` | Higher-quality HTML-clipboard → markdown on paste |

## Ubuntu 22.04+ / Debian 12+

```bash
sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-webkit2-4.1 \
                 gir1.2-gtksource-4 python3-markdown python3-pygments
# optional
sudo apt install pandoc python3-html2text
```

## Arch / Manjaro

```bash
sudo pacman -S python-gobject gtk3 webkit2gtk-4.1 gtksourceview4 \
               python-markdown python-pygments
# optional
sudo pacman -S pandoc python-html2text
```

## Fedora 39+

```bash
sudo dnf install python3-gobject gtk3 webkit2gtk4.1 gtksourceview4 \
                 python3-markdown python3-pygments
sudo dnf install pandoc python3-html2text
```

## Verify the dependencies

```bash
python3 -c "import gi; gi.require_version('Gtk','3.0'); gi.require_version('WebKit2','4.1'); gi.require_version('GtkSource','4'); print('ok')"
python3 -c "import markdown, pygments; print('md+pygments ok')"
```

## Get the code

```bash
git clone https://github.com/Canary-Builds/markview.git ~/markview
cd ~/markview
```

## Install the CLI + `.desktop` entry

```bash
./install.sh
```

This creates:

| Path | What it is |
|---|---|
| `~/.local/bin/markview` | CLI wrapper (a 2-line shell script) |
| `~/.local/share/applications/markview.desktop` | Desktop entry (appears in your launcher) |
| `~/.local/share/icons/hicolor/scalable/apps/markview.svg` | App icon |

Make sure `~/.local/bin` is on your `PATH`:

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
```

## Run

```bash
markview                 # welcome screen
markview README.md       # open a specific file
markview -V              # print version
```

## Uninstall

```bash
~/markview/uninstall.sh
```

This removes the CLI, desktop entry, and icon. The source folder in `~/markview/` is not deleted.
