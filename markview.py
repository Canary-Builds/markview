#!/usr/bin/env python3
"""markview — minimal modern markdown viewer for Linux."""
import os
import sys
import argparse
import html
from pathlib import Path

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("WebKit2", "4.1")
from gi.repository import Gtk, WebKit2, Gio, GLib, Gdk  # noqa: E402

import markdown  # noqa: E402
from pygments.formatters import HtmlFormatter  # noqa: E402

__version__ = "0.1.0"

APP_ID = "dev.markview.Viewer"
APP_NAME = "markview"
APP_DIR = Path(__file__).resolve().parent
STYLE_PATH = APP_DIR / "style.css"

MD_EXTENSIONS = [
    "fenced_code",
    "tables",
    "toc",
    "codehilite",
    "sane_lists",
    "footnotes",
    "attr_list",
    "md_in_html",
    "admonition",
    "def_list",
    "abbr",
]
MD_EXTENSION_CONFIGS = {
    "codehilite": {"guess_lang": False, "css_class": "codehilite"},
    "toc": {"permalink": False},
}


def load_style() -> str:
    try:
        return STYLE_PATH.read_text()
    except OSError:
        return ""


def pygments_css(theme: str) -> str:
    style = "github-dark" if theme == "dark" else "friendly"
    try:
        return HtmlFormatter(style=style).get_style_defs(".codehilite")
    except Exception:
        return HtmlFormatter().get_style_defs(".codehilite")


def render(md_text: str, theme: str, title: str) -> str:
    md = markdown.Markdown(extensions=MD_EXTENSIONS, extension_configs=MD_EXTENSION_CONFIGS)
    body = md.convert(md_text)
    return f"""<!DOCTYPE html>
<html data-theme="{theme}">
<head>
<meta charset="utf-8">
<title>{html.escape(title)}</title>
<style>{load_style()}</style>
<style>{pygments_css(theme)}</style>
</head>
<body>
<main class="markdown-body">
{body}
</main>
</body>
</html>"""


def welcome_html(theme: str) -> str:
    md_text = (
        f"# markview\n\n"
        f"*v{__version__} — a minimal, modern markdown viewer.*\n\n"
        "- **Open a file** — `Ctrl+O`, drag & drop, or pass a path on the CLI\n"
        "- **Reload** — `Ctrl+R`\n"
        "- **Toggle theme** — `Ctrl+D`\n"
        "- **Quit** — `Ctrl+Q`\n\n"
        "```python\n"
        "def hello():\n"
        "    print('markview')\n"
        "```\n"
    )
    return render(md_text, theme, "markview")


class Viewer(Gtk.ApplicationWindow):
    def __init__(self, app, path: Path | None):
        super().__init__(application=app, title=APP_NAME)
        self.set_default_size(960, 780)
        self.current_path: Path | None = None
        self.monitor: Gio.FileMonitor | None = None
        self.theme = self._detect_theme()

        header = Gtk.HeaderBar()
        header.set_show_close_button(True)
        header.props.title = APP_NAME
        self.header = header
        self.set_titlebar(header)

        open_btn = Gtk.Button.new_from_icon_name("document-open-symbolic", Gtk.IconSize.BUTTON)
        open_btn.set_tooltip_text("Open markdown file (Ctrl+O)")
        open_btn.connect("clicked", self._on_open_clicked)
        header.pack_start(open_btn)

        reload_btn = Gtk.Button.new_from_icon_name("view-refresh-symbolic", Gtk.IconSize.BUTTON)
        reload_btn.set_tooltip_text("Reload (Ctrl+R)")
        reload_btn.connect("clicked", lambda *_: self._reload())
        header.pack_start(reload_btn)

        self.theme_btn = Gtk.Button.new_from_icon_name(self._theme_icon(), Gtk.IconSize.BUTTON)
        self.theme_btn.set_tooltip_text("Toggle theme (Ctrl+D)")
        self.theme_btn.connect("clicked", lambda *_: self._toggle_theme())
        header.pack_end(self.theme_btn)

        self.webview = WebKit2.WebView()
        settings = self.webview.get_settings()
        settings.set_property("enable-developer-extras", False)
        settings.set_property("enable-javascript", True)
        settings.set_property("enable-smooth-scrolling", True)

        scroller = Gtk.ScrolledWindow()
        scroller.add(self.webview)
        self.add(scroller)

        self._setup_shortcuts()
        self._setup_dnd()

        if path is not None:
            self.load_file(path)
        else:
            self._render_welcome()

    def _detect_theme(self) -> str:
        settings = Gtk.Settings.get_default()
        if settings is not None:
            prefer_dark = settings.get_property("gtk-application-prefer-dark-theme")
            if prefer_dark:
                return "dark"
            theme_name = (settings.get_property("gtk-theme-name") or "").lower()
            if "dark" in theme_name:
                return "dark"
        return "light"

    def _theme_icon(self) -> str:
        return "weather-clear-night-symbolic" if self.theme == "light" else "weather-clear-symbolic"

    def _setup_shortcuts(self):
        accel = Gtk.AccelGroup()
        self.add_accel_group(accel)

        def bind(key: str, mod, handler):
            keyval = Gdk.keyval_from_name(key)
            accel.connect(keyval, mod, Gtk.AccelFlags.VISIBLE, lambda *_: handler() or True)

        bind("o", Gdk.ModifierType.CONTROL_MASK, self._on_open_clicked)
        bind("r", Gdk.ModifierType.CONTROL_MASK, self._reload)
        bind("q", Gdk.ModifierType.CONTROL_MASK, self.close)
        bind("d", Gdk.ModifierType.CONTROL_MASK, self._toggle_theme)

    def _setup_dnd(self):
        targets = Gtk.TargetList.new([])
        targets.add_uri_targets(0)
        self.webview.drag_dest_set(
            Gtk.DestDefaults.ALL,
            [],
            Gdk.DragAction.COPY,
        )
        self.webview.drag_dest_set_target_list(targets)
        self.webview.connect("drag-data-received", self._on_drag_received)

    def _on_drag_received(self, _widget, _context, _x, _y, data, _info, _time):
        uris = data.get_uris()
        if not uris:
            return
        path = Gio.File.new_for_uri(uris[0]).get_path()
        if path:
            self.load_file(Path(path))

    def _on_open_clicked(self, *_):
        dialog = Gtk.FileChooserDialog(
            title="Open markdown file",
            parent=self,
            action=Gtk.FileChooserAction.OPEN,
        )
        dialog.add_buttons(
            "Cancel", Gtk.ResponseType.CANCEL,
            "Open", Gtk.ResponseType.OK,
        )
        f = Gtk.FileFilter()
        f.set_name("Markdown")
        for pattern in ("*.md", "*.markdown", "*.mdown", "*.mkd", "*.txt"):
            f.add_pattern(pattern)
        dialog.add_filter(f)
        all_filter = Gtk.FileFilter()
        all_filter.set_name("All files")
        all_filter.add_pattern("*")
        dialog.add_filter(all_filter)

        if dialog.run() == Gtk.ResponseType.OK:
            path = Path(dialog.get_filename())
            dialog.destroy()
            self.load_file(path)
        else:
            dialog.destroy()

    def load_file(self, path: Path):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            self._render_error(f"Could not read {path}: {exc}")
            return
        self.current_path = path
        self.header.props.title = path.name
        self.header.props.subtitle = str(path.parent)
        base_uri = path.parent.as_uri() + "/"
        self.webview.load_html(render(text, self.theme, path.name), base_uri)
        self._watch_file(path)

    def _watch_file(self, path: Path):
        if self.monitor is not None:
            self.monitor.cancel()
        try:
            f = Gio.File.new_for_path(str(path))
            self.monitor = f.monitor_file(Gio.FileMonitorFlags.NONE, None)
            self.monitor.connect("changed", self._on_file_changed)
        except GLib.Error:
            self.monitor = None

    def _on_file_changed(self, _mon, _file, _other, event):
        if event in (
            Gio.FileMonitorEvent.CHANGES_DONE_HINT,
            Gio.FileMonitorEvent.CREATED,
        ):
            GLib.timeout_add(120, self._reload)

    def _reload(self, *_):
        if self.current_path and self.current_path.exists():
            self.load_file(self.current_path)
        else:
            self._render_welcome()
        return False

    def _toggle_theme(self, *_):
        self.theme = "dark" if self.theme == "light" else "light"
        self.theme_btn.set_image(
            Gtk.Image.new_from_icon_name(self._theme_icon(), Gtk.IconSize.BUTTON)
        )
        if self.current_path and self.current_path.exists():
            self.load_file(self.current_path)
        else:
            self._render_welcome()

    def _render_welcome(self):
        self.webview.load_html(welcome_html(self.theme), APP_DIR.as_uri() + "/")

    def _render_error(self, msg: str):
        md_text = f"# Error\n\n```\n{msg}\n```\n"
        self.webview.load_html(render(md_text, self.theme, "Error"), APP_DIR.as_uri() + "/")


class App(Gtk.Application):
    def __init__(self, path: Path | None):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.NON_UNIQUE)
        self._initial_path = path

    def do_activate(self):
        win = Viewer(self, self._initial_path)
        win.show_all()


def parse_args(argv: list[str]) -> Path | None:
    parser = argparse.ArgumentParser(prog=APP_NAME, description="Minimal modern markdown viewer.")
    parser.add_argument("file", nargs="?", help="Path to a markdown file.")
    parser.add_argument("-V", "--version", action="version", version=f"{APP_NAME} {__version__}")
    args = parser.parse_args(argv)
    if args.file:
        p = Path(args.file).expanduser().resolve()
        if not p.exists():
            print(f"{APP_NAME}: file not found: {p}", file=sys.stderr)
            sys.exit(1)
        return p
    return None


def main():
    path = parse_args(sys.argv[1:])
    app = App(path)
    app.run([])


if __name__ == "__main__":
    main()
