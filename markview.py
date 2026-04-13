#!/usr/bin/env python3
"""markview — minimal modern markdown viewer + editor for Linux."""
import os
import sys
import argparse
import html
from pathlib import Path

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("WebKit2", "4.1")
gi.require_version("GtkSource", "4")
from gi.repository import Gtk, WebKit2, Gio, GLib, Gdk, GtkSource  # noqa: E402

import markdown  # noqa: E402
from pygments.formatters import HtmlFormatter  # noqa: E402

__version__ = "0.3.1"

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

LIVE_PREVIEW_DEBOUNCE_MS = 220


# --- rendering ---------------------------------------------------------------

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
        f"*v{__version__} — a minimal, modern markdown viewer + editor.*\n\n"
        "- **Open** — `Ctrl+O`, drag & drop, or a path on the CLI\n"
        "- **Edit mode** — `Ctrl+E` (reveals the edit toolbar)\n"
        "- **Reload** — `Ctrl+R`\n"
        "- **Theme** — `Ctrl+D`\n"
        "- **Quit** — `Ctrl+Q`\n\n"
        "```python\n"
        "def hello():\n"
        "    print('markview')\n"
        "```\n"
    )
    return render(md_text, theme, "markview")


# --- helpers -----------------------------------------------------------------

def _icon_button(icon_name: str, tooltip: str, on_click=None) -> Gtk.Button:
    btn = Gtk.Button.new_from_icon_name(icon_name, Gtk.IconSize.BUTTON)
    btn.set_relief(Gtk.ReliefStyle.NONE)
    btn.set_tooltip_text(tooltip)
    btn.get_style_context().add_class("flat")
    if on_click is not None:
        btn.connect("clicked", on_click)
    return btn


def _toggle_icon(icon_name: str, tooltip: str) -> Gtk.ToggleButton:
    btn = Gtk.ToggleButton()
    btn.set_image(Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.BUTTON))
    btn.set_relief(Gtk.ReliefStyle.NONE)
    btn.set_tooltip_text(tooltip)
    btn.get_style_context().add_class("flat")
    return btn


def _separator() -> Gtk.Separator:
    sep = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
    sep.set_margin_start(4)
    sep.set_margin_end(4)
    return sep


# --- main window -------------------------------------------------------------

class Viewer(Gtk.ApplicationWindow):
    def __init__(self, app, path: Path | None):
        super().__init__(application=app, title=APP_NAME)
        self.set_default_size(1080, 780)

        self.current_path: Path | None = None
        self.is_untitled: bool = False
        self.monitor: Gio.FileMonitor | None = None
        self.theme = self._detect_theme()
        self.mode: str = "preview"             # "preview" | "edit"
        self.edit_view: str = "editor"          # "editor" | "split" | "preview"
        self._suppress_reload_until = 0.0
        self._live_timer: int | None = None

        self._build_header()
        self._build_editor_widgets()
        self._build_edit_toolbar()
        self._build_find_bar()
        self._build_layout()
        self._setup_shortcuts()
        self._setup_dnd()

        if path is not None:
            self.load_file(path)
        else:
            self._render_welcome()
        self._refresh_content()

    # ---- theme --------------------------------------------------------------

    def _detect_theme(self) -> str:
        settings = Gtk.Settings.get_default()
        if settings is not None:
            if settings.get_property("gtk-application-prefer-dark-theme"):
                return "dark"
            name = (settings.get_property("gtk-theme-name") or "").lower()
            if "dark" in name:
                return "dark"
        return "light"

    def _theme_icon(self) -> str:
        return "weather-clear-night-symbolic" if self.theme == "light" else "weather-clear-symbolic"

    def _toggle_theme(self, *_):
        self.theme = "dark" if self.theme == "light" else "light"
        self.theme_btn.set_image(
            Gtk.Image.new_from_icon_name(self._theme_icon(), Gtk.IconSize.BUTTON)
        )
        self._apply_source_style()
        self._refresh_preview()

    # ---- header -------------------------------------------------------------

    def _build_header(self):
        header = Gtk.HeaderBar()
        header.set_show_close_button(True)
        header.props.title = APP_NAME
        self.header = header
        self.set_titlebar(header)

        open_btn = _icon_button("document-open-symbolic", "Open (Ctrl+O)", self._on_open_clicked)
        header.pack_start(open_btn)

        self.edit_btn = _toggle_icon("document-edit-symbolic", "Edit mode (Ctrl+E)")
        self.edit_btn.set_sensitive(False)
        self.edit_btn.connect("toggled", self._on_edit_toggled)
        header.pack_start(self.edit_btn)

        reload_btn = _icon_button("view-refresh-symbolic", "Reload (Ctrl+R)",
                                  lambda *_: self._reload())
        header.pack_start(reload_btn)

        self.theme_btn = _icon_button(self._theme_icon(), "Theme (Ctrl+D)", self._toggle_theme)
        header.pack_end(self.theme_btn)

    # ---- editor widgets -----------------------------------------------------

    def _build_editor_widgets(self):
        # WebKit preview
        self.webview = WebKit2.WebView()
        wsettings = self.webview.get_settings()
        wsettings.set_property("enable-developer-extras", False)
        wsettings.set_property("enable-javascript", True)
        wsettings.set_property("enable-smooth-scrolling", True)
        self.preview_scroller = Gtk.ScrolledWindow()
        self.preview_scroller.add(self.webview)

        # Source editor
        lang_mgr = GtkSource.LanguageManager.get_default()
        md_lang = lang_mgr.get_language("markdown")
        self.editor_buffer = GtkSource.Buffer(language=md_lang)
        self.editor_buffer.set_highlight_syntax(True)
        self.editor_buffer.set_highlight_matching_brackets(False)
        self.editor_buffer.set_max_undo_levels(200)
        self.editor_buffer.connect("changed", self._on_buffer_changed)
        self.editor_buffer.connect("modified-changed", self._on_modified_changed)

        self.editor = GtkSource.View.new_with_buffer(self.editor_buffer)
        self.editor.set_monospace(True)
        self.editor.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.editor.set_show_line_numbers(True)
        self.editor.set_highlight_current_line(True)
        self.editor.set_auto_indent(True)
        self.editor.set_indent_width(2)
        self.editor.set_insert_spaces_instead_of_tabs(True)
        self.editor.set_tab_width(2)
        self.editor.set_left_margin(16)
        self.editor.set_right_margin(16)
        self.editor.set_top_margin(14)
        self.editor.set_bottom_margin(120)
        self._apply_editor_font()
        self._apply_source_style()

        self.editor_scroller = Gtk.ScrolledWindow()
        self.editor_scroller.add(self.editor)

        # Search context (for find bar)
        self.search_settings = GtkSource.SearchSettings()
        self.search_settings.set_wrap_around(True)
        self.search_settings.set_case_sensitive(False)
        self.search_context = GtkSource.SearchContext.new(self.editor_buffer, self.search_settings)

    def _apply_editor_font(self):
        provider = Gtk.CssProvider()
        provider.load_from_data(
            b"textview { font-family: 'JetBrains Mono','Fira Code',"
            b"'DejaVu Sans Mono',monospace; font-size: 10.5pt; }"
        )
        ctx = self.editor.get_style_context()
        ctx.add_provider(provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def _apply_source_style(self):
        scheme_mgr = GtkSource.StyleSchemeManager.get_default()
        scheme_id = "oblivion" if self.theme == "dark" else "solarized-light"
        scheme = scheme_mgr.get_scheme(scheme_id)
        if scheme is None:
            scheme = scheme_mgr.get_scheme("classic")
        if scheme is not None:
            self.editor_buffer.set_style_scheme(scheme)

    # ---- edit toolbar -------------------------------------------------------

    def _build_edit_toolbar(self):
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        bar.set_margin_start(8)
        bar.set_margin_end(8)
        bar.set_margin_top(4)
        bar.set_margin_bottom(4)

        def add(btn):
            bar.pack_start(btn, False, False, 0)

        # File group
        add(_icon_button("document-new-symbolic", "New (Ctrl+N)", self._on_new))
        add(_icon_button("document-save-symbolic", "Save (Ctrl+S)", lambda *_: self._save()))
        add(_icon_button("document-save-as-symbolic", "Save As (Ctrl+Shift+S)",
                         lambda *_: self._save_as()))
        add(_separator())

        # Undo/redo
        self.undo_btn = _icon_button("edit-undo-symbolic", "Undo (Ctrl+Z)",
                                     lambda *_: self._do_undo())
        self.redo_btn = _icon_button("edit-redo-symbolic", "Redo (Ctrl+Shift+Z)",
                                     lambda *_: self._do_redo())
        add(self.undo_btn)
        add(self.redo_btn)
        add(_separator())

        # Clipboard
        add(_icon_button("edit-cut-symbolic", "Cut (Ctrl+X)",
                         lambda *_: self._clipboard_action("cut-clipboard")))
        add(_icon_button("edit-copy-symbolic", "Copy (Ctrl+C)",
                         lambda *_: self._clipboard_action("copy-clipboard")))
        add(_icon_button("edit-paste-symbolic", "Paste (Ctrl+V)",
                         lambda *_: self._clipboard_action("paste-clipboard")))
        add(_separator())

        # Formatting
        add(_icon_button("format-text-bold-symbolic", "Bold (Ctrl+B)",
                         lambda *_: self._wrap_selection("**", "**", "bold text")))
        add(_icon_button("format-text-italic-symbolic", "Italic (Ctrl+I)",
                         lambda *_: self._wrap_selection("*", "*", "italic text")))
        add(_icon_button("format-text-strikethrough-symbolic", "Strikethrough",
                         lambda *_: self._wrap_selection("~~", "~~", "strikethrough")))
        add(_icon_button("format-text-underline-symbolic", "Heading (Ctrl+H)",
                         lambda *_: self._prefix_line("# ", toggle=True)))
        add(_icon_button("insert-link-symbolic", "Link (Ctrl+K)",
                         lambda *_: self._insert_link()))
        add(_icon_button("utilities-terminal-symbolic", "Inline code",
                         lambda *_: self._wrap_selection("`", "`", "code")))
        add(_icon_button("format-indent-more-symbolic", "Quote",
                         lambda *_: self._prefix_line("> ", toggle=True)))
        add(_icon_button("view-list-symbolic", "Bulleted list",
                         lambda *_: self._prefix_line("- ", toggle=True)))
        add(_icon_button("view-list-ordered-symbolic", "Numbered list",
                         lambda *_: self._prefix_line("1. ", toggle=True)))
        add(_icon_button("object-select-symbolic", "Checklist item",
                         lambda *_: self._prefix_line("- [ ] ", toggle=True)))
        add(_icon_button("insert-image-symbolic", "Image",
                         lambda *_: self._insert_image()))
        add(_icon_button("format-justify-fill-symbolic", "Horizontal rule",
                         lambda *_: self._insert_text("\n---\n")))

        # Spacer
        spacer = Gtk.Box()
        bar.pack_start(spacer, True, True, 0)

        # View-mode segmented control
        view_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        view_box.get_style_context().add_class("linked")
        self.view_editor_btn = _toggle_icon("accessories-text-editor-symbolic", "Editor only")
        self.view_split_btn = _toggle_icon("view-dual-symbolic", "Split view (live preview)")
        self.view_preview_btn = _toggle_icon("view-reveal-symbolic", "Preview only")
        self.view_editor_btn.set_active(True)
        for b in (self.view_editor_btn, self.view_split_btn, self.view_preview_btn):
            view_box.pack_start(b, False, False, 0)
        self.view_editor_btn.connect("toggled", lambda b: self._set_edit_view("editor", b))
        self.view_split_btn.connect("toggled", lambda b: self._set_edit_view("split", b))
        self.view_preview_btn.connect("toggled", lambda b: self._set_edit_view("preview", b))
        bar.pack_start(view_box, False, False, 0)

        # Find
        bar.pack_start(_separator(), False, False, 0)
        find_btn = _icon_button("edit-find-symbolic", "Find (Ctrl+F)",
                                lambda *_: self._toggle_find(True))
        bar.pack_start(find_btn, False, False, 0)

        self.edit_toolbar_revealer = Gtk.Revealer()
        self.edit_toolbar_revealer.set_transition_type(
            Gtk.RevealerTransitionType.SLIDE_DOWN
        )
        self.edit_toolbar_revealer.set_transition_duration(160)
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        outer.pack_start(bar, False, False, 0)
        outer.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 0)
        self.edit_toolbar_revealer.add(outer)

    # ---- find bar -----------------------------------------------------------

    def _build_find_bar(self):
        self.find_entry = Gtk.SearchEntry()
        self.find_entry.set_width_chars(48)
        self.find_entry.connect("search-changed", self._on_find_changed)
        self.find_entry.connect("activate", lambda *_: self._find_step(forward=True))
        self.find_entry.connect("stop-search", lambda *_: self._toggle_find(False))

        next_btn = _icon_button("go-down-symbolic", "Find next (Enter)",
                                lambda *_: self._find_step(forward=True))
        prev_btn = _icon_button("go-up-symbolic", "Find previous (Shift+Enter)",
                                lambda *_: self._find_step(forward=False))

        inner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        inner.pack_start(self.find_entry, True, True, 0)
        inner.pack_start(prev_btn, False, False, 0)
        inner.pack_start(next_btn, False, False, 0)

        self.find_bar = Gtk.SearchBar()
        self.find_bar.add(inner)
        self.find_bar.connect_entry(self.find_entry)

    def _toggle_find(self, on: bool):
        if on and self.mode != "edit":
            return
        self.find_bar.set_search_mode(on)
        if on:
            self.find_entry.grab_focus()

    def _on_find_changed(self, entry):
        self.search_settings.set_search_text(entry.get_text() or "")

    def _find_step(self, forward: bool):
        start_iter = self.editor_buffer.get_iter_at_mark(self.editor_buffer.get_insert())
        func = (self.search_context.forward2 if forward else self.search_context.backward2)
        try:
            found, match_start, match_end, _wrapped = func(start_iter)
        except Exception:
            found = False
        if found:
            self.editor_buffer.select_range(match_start, match_end)
            self.editor.scroll_to_iter(match_start, 0.1, False, 0, 0)

    # ---- layout -------------------------------------------------------------

    def _build_layout(self):
        self.root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.root.pack_start(self.edit_toolbar_revealer, False, False, 0)
        self.root.pack_start(self.find_bar, False, False, 0)

        self.content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.root.pack_start(self.content_box, True, True, 0)
        self.add(self.root)

    def _refresh_content(self):
        # detach everything
        for widget in (self.preview_scroller, self.editor_scroller):
            parent = widget.get_parent()
            if parent is not None:
                parent.remove(widget)
        for child in list(self.content_box.get_children()):
            self.content_box.remove(child)

        if self.mode == "preview":
            self.content_box.pack_start(self.preview_scroller, True, True, 0)
        else:
            if self.edit_view == "editor":
                self.content_box.pack_start(self.editor_scroller, True, True, 0)
            elif self.edit_view == "preview":
                self.content_box.pack_start(self.preview_scroller, True, True, 0)
            else:  # split
                paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
                paned.set_wide_handle(True)
                paned.pack1(self.editor_scroller, resize=True, shrink=False)
                paned.pack2(self.preview_scroller, resize=True, shrink=False)
                GLib.idle_add(self._set_paned_middle, paned)
                self.content_box.pack_start(paned, True, True, 0)

        self.content_box.show_all()
        self.edit_toolbar_revealer.set_reveal_child(self.mode == "edit")
        if self.mode == "preview":
            self.find_bar.set_search_mode(False)

    def _set_paned_middle(self, paned):
        alloc = paned.get_allocated_width()
        if alloc > 0:
            paned.set_position(alloc // 2)
        return False

    # ---- shortcuts + DnD ----------------------------------------------------

    def _setup_shortcuts(self):
        accel = Gtk.AccelGroup()
        self.add_accel_group(accel)

        def bind(key: str, mod, handler):
            keyval = Gdk.keyval_from_name(key)
            accel.connect(keyval, mod, Gtk.AccelFlags.VISIBLE, lambda *_: handler() or True)

        CTRL = Gdk.ModifierType.CONTROL_MASK
        SHIFT = Gdk.ModifierType.SHIFT_MASK
        bind("o", CTRL, self._on_open_clicked)
        bind("n", CTRL, self._on_new)
        bind("s", CTRL, self._save)
        bind("s", CTRL | SHIFT, self._save_as)
        bind("r", CTRL, self._reload)
        bind("q", CTRL, self.close)
        bind("d", CTRL, self._toggle_theme)
        bind("e", CTRL, self._toggle_edit)
        bind("f", CTRL, lambda: self._toggle_find(not self.find_bar.get_search_mode()))
        bind("b", CTRL, lambda: self._wrap_selection("**", "**", "bold text"))
        bind("i", CTRL, lambda: self._wrap_selection("*", "*", "italic text"))
        bind("k", CTRL, lambda: self._insert_link())
        bind("h", CTRL, lambda: self._prefix_line("# ", toggle=True))
        bind("z", CTRL, lambda: self._do_undo())
        bind("z", CTRL | SHIFT, lambda: self._do_redo())
        bind("y", CTRL, lambda: self._do_redo())

    def _setup_dnd(self):
        targets = Gtk.TargetList.new([])
        targets.add_uri_targets(0)
        self.webview.drag_dest_set(Gtk.DestDefaults.ALL, [], Gdk.DragAction.COPY)
        self.webview.drag_dest_set_target_list(targets)
        self.webview.connect("drag-data-received", self._on_drag_received)

    def _on_drag_received(self, _w, _c, _x, _y, data, _i, _t):
        uris = data.get_uris()
        if not uris:
            return
        path = Gio.File.new_for_uri(uris[0]).get_path()
        if path:
            self.load_file(Path(path))

    # ---- file open / reload -------------------------------------------------

    def _on_open_clicked(self, *_):
        if not self._confirm_discard_if_dirty():
            return
        dialog = Gtk.FileChooserDialog(
            title="Open markdown file",
            parent=self,
            action=Gtk.FileChooserAction.OPEN,
        )
        dialog.add_buttons("Cancel", Gtk.ResponseType.CANCEL,
                           "Open", Gtk.ResponseType.OK)
        md_filter = Gtk.FileFilter()
        md_filter.set_name("Markdown")
        for p in ("*.md", "*.markdown", "*.mdown", "*.mkd", "*.txt"):
            md_filter.add_pattern(p)
        dialog.add_filter(md_filter)
        all_filter = Gtk.FileFilter()
        all_filter.set_name("All files")
        all_filter.add_pattern("*")
        dialog.add_filter(all_filter)

        response = dialog.run()
        chosen = dialog.get_filename() if response == Gtk.ResponseType.OK else None
        dialog.destroy()
        if chosen:
            self.load_file(Path(chosen))

    def load_file(self, path: Path):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            self._render_error(f"Could not read {path}: {exc}")
            return
        self.current_path = path
        self.is_untitled = False
        self.edit_btn.set_sensitive(True)
        base_uri = path.parent.as_uri() + "/"
        self.webview.load_html(render(text, self.theme, path.name), base_uri)
        self._load_editor_text(text)
        self._watch_file(path)
        self._update_title()

    def _watch_file(self, path: Path):
        if self.monitor is not None:
            self.monitor.cancel()
        try:
            self.monitor = Gio.File.new_for_path(str(path)).monitor_file(
                Gio.FileMonitorFlags.NONE, None
            )
            self.monitor.connect("changed", self._on_file_changed)
        except GLib.Error:
            self.monitor = None

    def _on_file_changed(self, _m, _f, _o, event):
        if self.mode == "edit":
            return
        if GLib.get_monotonic_time() / 1e6 < self._suppress_reload_until:
            return
        if event in (Gio.FileMonitorEvent.CHANGES_DONE_HINT, Gio.FileMonitorEvent.CREATED):
            GLib.timeout_add(120, self._reload)

    def _reload(self, *_):
        if self.current_path and self.current_path.exists():
            self.load_file(self.current_path)
        else:
            self._render_welcome()
        return False

    def _render_welcome(self):
        self.webview.load_html(welcome_html(self.theme), APP_DIR.as_uri() + "/")
        self.edit_btn.set_sensitive(False)
        self.current_path = None
        self.is_untitled = False
        self._update_title()

    def _render_error(self, msg: str):
        md_text = f"# Error\n\n```\n{msg}\n```\n"
        self.webview.load_html(render(md_text, self.theme, "Error"), APP_DIR.as_uri() + "/")

    def _refresh_preview(self):
        if self.current_path and self.current_path.exists() and self.mode == "preview":
            self.load_file(self.current_path)
        elif self.mode == "edit":
            self._render_live_preview()
        else:
            self._render_welcome()

    # ---- edit mode toggle ---------------------------------------------------

    def _on_edit_toggled(self, btn):
        self._set_mode("edit" if btn.get_active() else "preview")

    def _toggle_edit(self, *_):
        if not self.edit_btn.get_sensitive():
            return
        self.edit_btn.set_active(not self.edit_btn.get_active())

    def _set_mode(self, mode: str):
        if mode == self.mode:
            return
        if mode == "edit":
            if not self.current_path and not self.is_untitled:
                self.edit_btn.set_active(False)
                return
            self.mode = "edit"
            self._refresh_content()
            if self.edit_view != "preview":
                self.editor.grab_focus()
        else:
            # leaving edit mode — save if dirty
            if self.editor_buffer.get_modified():
                if self.is_untitled or not self.current_path:
                    if not self._save_as():
                        # user cancelled save — keep them in edit mode
                        self.edit_btn.set_active(True)
                        return
                else:
                    self._save()
            self.mode = "preview"
            self._refresh_content()
            if self.current_path and self.current_path.exists():
                self.load_file(self.current_path)

    def _set_edit_view(self, view: str, btn: Gtk.ToggleButton):
        if getattr(self, "_view_switching", False):
            return
        if not btn.get_active():
            # prevent turning all three off — re-enable if this was the active one
            if self.edit_view == view:
                self._view_switching = True
                btn.set_active(True)
                self._view_switching = False
            return
        self._view_switching = True
        self.edit_view = view
        for b, v in ((self.view_editor_btn, "editor"),
                     (self.view_split_btn, "split"),
                     (self.view_preview_btn, "preview")):
            b.set_active(v == view)
        self._view_switching = False
        if self.mode == "edit":
            self._refresh_content()
            if view in ("split", "preview"):
                self._render_live_preview()

    # ---- editor buffer & live preview ---------------------------------------

    def _load_editor_text(self, text: str):
        self.editor_buffer.handler_block_by_func(self._on_buffer_changed)
        self.editor_buffer.begin_not_undoable_action()
        self.editor_buffer.set_text(text)
        self.editor_buffer.end_not_undoable_action()
        self.editor_buffer.set_modified(False)
        self.editor_buffer.handler_unblock_by_func(self._on_buffer_changed)
        self._update_title()

    def _buffer_text(self) -> str:
        start, end = self.editor_buffer.get_bounds()
        return self.editor_buffer.get_text(start, end, True)

    def _on_buffer_changed(self, *_):
        self._update_title()
        if self.mode == "edit" and self.edit_view in ("split", "preview"):
            self._schedule_live_preview()

    def _on_modified_changed(self, *_):
        self._update_title()

    def _schedule_live_preview(self):
        if self._live_timer is not None:
            GLib.source_remove(self._live_timer)
        self._live_timer = GLib.timeout_add(
            LIVE_PREVIEW_DEBOUNCE_MS, self._render_live_preview
        )

    def _render_live_preview(self):
        self._live_timer = None
        text = self._buffer_text()
        base = (self.current_path.parent if self.current_path else APP_DIR).as_uri() + "/"
        title = self.current_path.name if self.current_path else "untitled.md"
        self.webview.load_html(render(text, self.theme, title), base)
        return False

    def _update_title(self):
        if self.current_path or self.is_untitled:
            name = (
                self.current_path.name if self.current_path
                else "untitled.md"
            )
            dirty = "  •" if self.editor_buffer.get_modified() else ""
            self.header.props.title = f"{name}{dirty}"
            sub = (
                str(self.current_path.parent)
                if self.current_path else "(unsaved)"
            )
            self.header.props.subtitle = sub
        else:
            self.header.props.title = APP_NAME
            self.header.props.subtitle = None

    # ---- file: new / save / save as -----------------------------------------

    def _on_new(self, *_):
        if not self._confirm_discard_if_dirty():
            return
        self.current_path = None
        self.is_untitled = True
        self.edit_btn.set_sensitive(True)
        self._load_editor_text("# Untitled\n\n")
        if self.monitor is not None:
            self.monitor.cancel()
            self.monitor = None
        self.edit_btn.set_active(True)
        if self.mode == "edit" and self.edit_view in ("split", "preview"):
            self._render_live_preview()

    def _save(self, *_) -> bool:
        if self.mode != "edit" and not self.editor_buffer.get_modified():
            return True
        if self.is_untitled or not self.current_path:
            return self._save_as()
        return self._write_to(self.current_path)

    def _save_as(self, *_) -> bool:
        dialog = Gtk.FileChooserDialog(
            title="Save markdown file",
            parent=self,
            action=Gtk.FileChooserAction.SAVE,
        )
        dialog.add_buttons("Cancel", Gtk.ResponseType.CANCEL,
                           "Save", Gtk.ResponseType.OK)
        dialog.set_do_overwrite_confirmation(True)
        if self.current_path:
            dialog.set_current_folder(str(self.current_path.parent))
            dialog.set_current_name(self.current_path.name)
        else:
            dialog.set_current_name("untitled.md")
        response = dialog.run()
        chosen = dialog.get_filename() if response == Gtk.ResponseType.OK else None
        dialog.destroy()
        if not chosen:
            return False
        path = Path(chosen)
        if not self._write_to(path):
            return False
        self.current_path = path
        self.is_untitled = False
        self._watch_file(path)
        self._update_title()
        return True

    def _write_to(self, path: Path) -> bool:
        try:
            self._suppress_reload_until = GLib.get_monotonic_time() / 1e6 + 1.0
            path.write_text(self._buffer_text(), encoding="utf-8")
        except OSError as exc:
            self._render_error(f"Could not write {path}: {exc}")
            return False
        self.editor_buffer.set_modified(False)
        self._update_title()
        return True

    def _confirm_discard_if_dirty(self) -> bool:
        if not self.editor_buffer.get_modified():
            return True
        dialog = Gtk.MessageDialog(
            parent=self,
            flags=0,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.NONE,
            text="You have unsaved changes.",
        )
        dialog.format_secondary_text("Save before continuing?")
        dialog.add_buttons(
            "Discard", Gtk.ResponseType.CLOSE,
            "Cancel", Gtk.ResponseType.CANCEL,
            "Save", Gtk.ResponseType.ACCEPT,
        )
        response = dialog.run()
        dialog.destroy()
        if response == Gtk.ResponseType.CANCEL:
            return False
        if response == Gtk.ResponseType.ACCEPT:
            return self._save()
        return True  # discard

    # ---- undo / redo / clipboard / format ----------------------------------

    def _do_undo(self):
        if self.editor_buffer.can_undo():
            self.editor_buffer.undo()

    def _do_redo(self):
        if self.editor_buffer.can_redo():
            self.editor_buffer.redo()

    def _clipboard_action(self, signal_name: str):
        self.editor.emit(signal_name)

    def _insert_text(self, text: str):
        if not self.editor.is_focus():
            self.editor.grab_focus()
        self.editor_buffer.begin_user_action()
        self.editor_buffer.insert_at_cursor(text)
        self.editor_buffer.end_user_action()

    def _wrap_selection(self, left: str, right: str, placeholder: str):
        buf = self.editor_buffer
        buf.begin_user_action()
        if buf.get_has_selection():
            start, end = buf.get_selection_bounds()
            sel = buf.get_text(start, end, True)
            buf.delete(start, end)
            buf.insert(start, f"{left}{sel}{right}")
        else:
            buf.insert_at_cursor(f"{left}{placeholder}{right}")
            # select the placeholder
            end_iter = buf.get_iter_at_mark(buf.get_insert())
            start_iter = end_iter.copy()
            start_iter.backward_chars(len(right) + len(placeholder))
            end_iter.backward_chars(len(right))
            buf.select_range(start_iter, end_iter)
        buf.end_user_action()
        self.editor.grab_focus()

    def _prefix_line(self, prefix: str, toggle: bool = False):
        buf = self.editor_buffer
        buf.begin_user_action()
        if buf.get_has_selection():
            start, end = buf.get_selection_bounds()
            start.set_line_offset(0)
            # expand end to line end
            if not end.ends_line():
                end.forward_to_line_end()
            self._prefix_range(buf, start, end, prefix, toggle)
        else:
            mark = buf.get_insert()
            it = buf.get_iter_at_mark(mark)
            line_start = it.copy()
            line_start.set_line_offset(0)
            line_end = it.copy()
            if not line_end.ends_line():
                line_end.forward_to_line_end()
            self._prefix_range(buf, line_start, line_end, prefix, toggle)
        buf.end_user_action()
        self.editor.grab_focus()

    def _prefix_range(self, buf, start_iter, end_iter, prefix, toggle):
        start_line = start_iter.get_line()
        end_line = end_iter.get_line()
        for line_idx in range(start_line, end_line + 1):
            line_iter = buf.get_iter_at_line(line_idx)
            if not line_iter:
                continue
            line_end = line_iter.copy()
            if not line_end.ends_line():
                line_end.forward_to_line_end()
            current = buf.get_text(line_iter, line_end, True)
            if toggle and current.startswith(prefix):
                end_prefix = line_iter.copy()
                end_prefix.forward_chars(len(prefix))
                buf.delete(line_iter, end_prefix)
            else:
                buf.insert(line_iter, prefix)

    def _insert_link(self):
        buf = self.editor_buffer
        buf.begin_user_action()
        if buf.get_has_selection():
            start, end = buf.get_selection_bounds()
            label = buf.get_text(start, end, True)
            buf.delete(start, end)
            buf.insert(start, f"[{label}](https://)")
        else:
            buf.insert_at_cursor("[text](https://)")
        buf.end_user_action()
        self.editor.grab_focus()

    def _insert_image(self):
        dialog = Gtk.FileChooserDialog(
            title="Insert image",
            parent=self,
            action=Gtk.FileChooserAction.OPEN,
        )
        dialog.add_buttons("Cancel", Gtk.ResponseType.CANCEL,
                           "Insert", Gtk.ResponseType.OK)
        img_filter = Gtk.FileFilter()
        img_filter.set_name("Images")
        for p in ("*.png", "*.jpg", "*.jpeg", "*.gif", "*.svg", "*.webp"):
            img_filter.add_pattern(p)
        dialog.add_filter(img_filter)
        response = dialog.run()
        chosen = dialog.get_filename() if response == Gtk.ResponseType.OK else None
        dialog.destroy()
        if not chosen:
            return
        # try to make it relative to current file's folder
        img_path = Path(chosen)
        if self.current_path:
            try:
                rel = os.path.relpath(img_path, self.current_path.parent)
                ref = rel
            except ValueError:
                ref = str(img_path)
        else:
            ref = str(img_path)
        self.editor_buffer.insert_at_cursor(f"![{img_path.stem}]({ref})")
        self.editor.grab_focus()


# --- app boot ----------------------------------------------------------------

class App(Gtk.Application):
    def __init__(self, path: Path | None):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.NON_UNIQUE)
        self._initial_path = path

    def do_activate(self):
        win = Viewer(self, self._initial_path)
        win.show_all()
        # Find bar is inside the root VBox but should start hidden
        win.find_bar.set_search_mode(False)


def parse_args(argv: list[str]) -> Path | None:
    parser = argparse.ArgumentParser(prog=APP_NAME, description="Minimal modern markdown viewer + editor.")
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
