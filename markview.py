#!/usr/bin/env python3
"""markview — minimal modern markdown viewer + editor for Linux."""
import os
import re
import sys
import json
import argparse
import html
import datetime
from pathlib import Path

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("WebKit2", "4.1")
gi.require_version("GtkSource", "4")
from gi.repository import Gtk, WebKit2, Gio, GLib, Gdk, GtkSource, Pango  # noqa: E402

import markdown  # noqa: E402
from markdown.extensions.toc import slugify  # noqa: E402
from pygments.formatters import HtmlFormatter  # noqa: E402

__version__ = "0.4.0"

APP_ID = "dev.markview.Viewer"
APP_NAME = "markview"
APP_DIR = Path(__file__).resolve().parent
STYLE_PATH = APP_DIR / "style.css"

MD_EXTENSIONS = [
    "fenced_code", "tables", "toc", "codehilite", "sane_lists",
    "footnotes", "attr_list", "md_in_html", "admonition", "def_list", "abbr",
]
MD_EXTENSION_CONFIGS = {
    "codehilite": {"guess_lang": False, "css_class": "codehilite"},
    "toc": {"permalink": False},
}

LIVE_PREVIEW_DEBOUNCE_MS = 220
SCROLL_SYNC_DEBOUNCE_MS = 80
SEARCH_RESULT_CAP = 500
PALETTE_ITEM_CAP = 200

TASK_LINE_RE = re.compile(r"^(\s*(?:[-*+]|\d+\.)\s+)\[([ xX])\]\s+(.*)$")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
FENCE_RE = re.compile(r"^\s*```")

# JS bridge — defines window.markview.scrollToAnchor() and wires task checkbox
# click handlers that post back to the Python side via the webkit bridge.
JS_BRIDGE = """
(function(){
  window.markview = window.markview || {};
  window.markview.scrollToAnchor = function(slug){
    if (!slug) return;
    var el = document.getElementById(slug);
    if (el) el.scrollIntoView({block:'start', behavior:'auto'});
  };
  var post = function(payload){
    try { window.webkit.messageHandlers.markview.postMessage(JSON.stringify(payload)); }
    catch(e){}
  };
  document.querySelectorAll('input.mv-task').forEach(function(el){
    el.disabled = false;
    el.style.cursor = 'pointer';
    el.addEventListener('click', function(ev){
      ev.preventDefault();
      var line = parseInt(el.getAttribute('data-task-line'), 10);
      var checked = !el.checked ? false : true;
      // flip visually; Python will reload to the truth
      el.checked = !el.checked;
      post({type:'task_toggle', line: line, checked: el.checked});
    });
  });
})();
"""


# --- rendering helpers -------------------------------------------------------

def preprocess_tasks(text: str) -> str:
    """Turn `- [ ] foo` into a list item with an inline HTML checkbox carrying
    the source line number, so the preview can round-trip clicks back."""
    in_fence = False
    lines = text.split("\n")
    out = []
    for i, line in enumerate(lines):
        if FENCE_RE.match(line):
            in_fence = not in_fence
            out.append(line)
            continue
        if not in_fence:
            m = TASK_LINE_RE.match(line)
            if m:
                indent, box, content = m.groups()
                checked = "checked" if box.lower() == "x" else ""
                out.append(
                    f'{indent}<input type="checkbox" class="mv-task" '
                    f'data-task-line="{i}" {checked}> {content}'
                )
                continue
        out.append(line)
    return "\n".join(out)


def extract_headings(text: str) -> list[dict]:
    results = []
    in_fence = False
    for i, line in enumerate(text.split("\n")):
        if FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = HEADING_RE.match(line)
        if m:
            level = len(m.group(1))
            title = m.group(2).strip()
            results.append({
                "line": i, "level": level,
                "title": title, "slug": slugify(title, "-"),
            })
    return results


def toggle_task_line(line: str, checked: bool) -> str | None:
    m = TASK_LINE_RE.match(line)
    if not m:
        return None
    indent, _, content = m.groups()
    return f"{indent}[{'x' if checked else ' '}] {content}"


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
    source = preprocess_tasks(md_text)
    md = markdown.Markdown(extensions=MD_EXTENSIONS, extension_configs=MD_EXTENSION_CONFIGS)
    body = md.convert(source)
    return (
        f"<!DOCTYPE html>\n"
        f'<html data-theme="{theme}">\n<head>\n<meta charset="utf-8">\n'
        f"<title>{html.escape(title)}</title>\n"
        f"<style>{load_style()}</style>\n"
        f"<style>{pygments_css(theme)}</style>\n"
        f'</head>\n<body>\n<main class="markdown-body">\n{body}\n</main>\n'
        f"<script>{JS_BRIDGE}</script>\n"
        f"</body>\n</html>"
    )


def welcome_html(theme: str) -> str:
    md_text = (
        f"# markview\n\n"
        f"*v{__version__} — minimal, modern markdown viewer + editor.*\n\n"
        "- **Open** — `Ctrl+O`, drag & drop, or CLI path\n"
        "- **Edit mode** — `Ctrl+E` (reveals the edit toolbar)\n"
        "- **Jump** — `Ctrl+P` (fuzzy palette: actions · headings · files)\n"
        "- **Search folder** — `Ctrl+Shift+F`\n"
        "- **Theme** — `Ctrl+D`  · **Reload** — `Ctrl+R`  · **Quit** — `Ctrl+Q`\n"
    )
    return render(md_text, theme, "markview")


# --- small UI helpers --------------------------------------------------------

def _icon_button(icon_name, tooltip, on_click=None) -> Gtk.Button:
    btn = Gtk.Button.new_from_icon_name(icon_name, Gtk.IconSize.BUTTON)
    btn.set_relief(Gtk.ReliefStyle.NONE)
    btn.set_tooltip_text(tooltip)
    btn.get_style_context().add_class("flat")
    if on_click is not None:
        btn.connect("clicked", on_click)
    return btn


def _toggle_icon(icon_name, tooltip) -> Gtk.ToggleButton:
    btn = Gtk.ToggleButton()
    btn.set_image(Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.BUTTON))
    btn.set_relief(Gtk.ReliefStyle.NONE)
    btn.set_tooltip_text(tooltip)
    btn.get_style_context().add_class("flat")
    return btn


def _separator():
    sep = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
    sep.set_margin_start(4); sep.set_margin_end(4)
    return sep


# --- command palette ---------------------------------------------------------

class CommandPalette(Gtk.Window):
    """Borderless fuzzy-filter popup for actions, headings, files, or search
    results. Arrow keys navigate, Enter activates, Esc dismisses."""

    def __init__(self, parent: Gtk.Window, provider, on_select,
                 placeholder="Type to filter…", min_query_chars: int = 0):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.set_decorated(False)
        self.set_transient_for(parent)
        self.set_modal(True)
        self.set_destroy_with_parent(True)
        self.set_skip_taskbar_hint(True)
        self.set_position(Gtk.WindowPosition.CENTER_ON_PARENT)
        self.set_default_size(640, 440)
        self.set_resizable(False)
        self.provider = provider
        self.on_select = on_select
        self.min_query_chars = min_query_chars

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        outer.get_style_context().add_class("markview-palette")
        outer.set_margin_top(10); outer.set_margin_bottom(10)
        outer.set_margin_start(10); outer.set_margin_end(10)

        self.entry = Gtk.SearchEntry()
        self.entry.set_placeholder_text(placeholder)
        self.entry.connect("search-changed", self._refresh)
        self.entry.connect("activate", lambda *_: self._activate_selected())
        self.entry.connect("key-press-event", self._on_entry_key)
        outer.pack_start(self.entry, False, False, 4)

        self.listbox = Gtk.ListBox()
        self.listbox.set_activate_on_single_click(True)
        self.listbox.connect("row-activated", lambda _lb, row: self._select_row(row))

        scroller = Gtk.ScrolledWindow()
        scroller.set_hexpand(True); scroller.set_vexpand(True)
        scroller.add(self.listbox)
        outer.pack_start(scroller, True, True, 0)

        self.add(outer)
        self.connect("key-press-event", self._on_window_key)
        self.connect("focus-out-event", lambda *_: self.destroy())
        self._refresh()

    def _refresh(self, *_):
        for child in self.listbox.get_children():
            self.listbox.remove(child)
        query = self.entry.get_text() or ""
        if len(query.strip()) < self.min_query_chars:
            items = [{"label": f"Type at least {self.min_query_chars} characters…",
                      "sub": None, "key": None}]
        else:
            items = self.provider(query) or []
        for item in items[:PALETTE_ITEM_CAP]:
            self.listbox.add(self._build_row(item))
        self.listbox.show_all()
        first = self.listbox.get_row_at_index(0)
        if first:
            self.listbox.select_row(first)

    def _build_row(self, item):
        row = Gtk.ListBoxRow()
        row.item_key = item.get("key")
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        vbox.set_margin_top(4); vbox.set_margin_bottom(4)
        vbox.set_margin_start(6); vbox.set_margin_end(6)
        lbl = Gtk.Label(label=item["label"], xalign=0)
        lbl.set_ellipsize(Pango.EllipsizeMode.END)
        vbox.pack_start(lbl, False, False, 0)
        if item.get("sub"):
            sub = Gtk.Label(label=item["sub"], xalign=0)
            sub.get_style_context().add_class("dim-label")
            sub.set_ellipsize(Pango.EllipsizeMode.END)
            vbox.pack_start(sub, False, False, 0)
        row.add(vbox)
        return row

    def _select_row(self, row):
        key = getattr(row, "item_key", None) if row else None
        if key is not None:
            self.on_select(key)
        self.destroy()

    def _activate_selected(self):
        self._select_row(self.listbox.get_selected_row() or
                         self.listbox.get_row_at_index(0))

    def _on_entry_key(self, _w, event):
        if event.keyval in (Gdk.KEY_Down, Gdk.KEY_Up):
            current = self.listbox.get_selected_row()
            idx = current.get_index() if current else -1
            idx += 1 if event.keyval == Gdk.KEY_Down else -1
            total = len(self.listbox.get_children())
            if total == 0:
                return True
            idx = max(0, min(idx, total - 1))
            new_row = self.listbox.get_row_at_index(idx)
            if new_row:
                self.listbox.select_row(new_row)
                adj = self.listbox.get_parent().get_vadjustment() \
                    if self.listbox.get_parent() else None
                if adj is not None:
                    alloc = new_row.get_allocation()
                    if alloc.y + alloc.height > adj.get_value() + adj.get_page_size():
                        adj.set_value(alloc.y + alloc.height - adj.get_page_size())
                    elif alloc.y < adj.get_value():
                        adj.set_value(alloc.y)
            return True
        if event.keyval == Gdk.KEY_Return:
            self._activate_selected()
            return True
        return False

    def _on_window_key(self, _w, event):
        if event.keyval == Gdk.KEY_Escape:
            self.destroy()
            return True
        return False


# --- main window -------------------------------------------------------------

class Viewer(Gtk.ApplicationWindow):
    def __init__(self, app, path: Path | None):
        super().__init__(application=app, title=APP_NAME)
        self.set_default_size(1080, 780)

        self.current_path: Path | None = None
        self.is_untitled: bool = False
        self.monitor: Gio.FileMonitor | None = None
        self.theme = self._detect_theme()
        self.mode: str = "preview"
        self.edit_view: str = "editor"
        self._suppress_reload_until = 0.0
        self._live_timer: int | None = None
        self._scroll_sync_timer: int | None = None
        self._headings_cache: list[dict] = []

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

    def _detect_theme(self):
        settings = Gtk.Settings.get_default()
        if settings is not None:
            if settings.get_property("gtk-application-prefer-dark-theme"):
                return "dark"
            name = (settings.get_property("gtk-theme-name") or "").lower()
            if "dark" in name:
                return "dark"
        return "light"

    def _theme_icon(self):
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
        header.pack_start(_icon_button("document-open-symbolic", "Open (Ctrl+O)",
                                       self._on_open_clicked))
        self.edit_btn = _toggle_icon("document-edit-symbolic", "Edit mode (Ctrl+E)")
        self.edit_btn.set_sensitive(False)
        self.edit_btn.connect("toggled", self._on_edit_toggled)
        header.pack_start(self.edit_btn)
        header.pack_start(_icon_button("view-refresh-symbolic", "Reload (Ctrl+R)",
                                       lambda *_: self._reload()))
        self.theme_btn = _icon_button(self._theme_icon(), "Theme (Ctrl+D)",
                                      self._toggle_theme)
        header.pack_end(self.theme_btn)

    # ---- editor widgets -----------------------------------------------------

    def _build_editor_widgets(self):
        # WebKit preview with user-content-manager for the JS bridge
        ucm = WebKit2.UserContentManager()
        ucm.register_script_message_handler("markview")
        ucm.connect("script-message-received::markview", self._on_script_message)
        self._ucm = ucm
        self.webview = WebKit2.WebView.new_with_user_content_manager(ucm)
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
        self.editor_buffer.connect("notify::cursor-position", self._on_cursor_position)

        self.editor = GtkSource.View.new_with_buffer(self.editor_buffer)
        self.editor.set_monospace(True)
        self.editor.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.editor.set_show_line_numbers(True)
        self.editor.set_highlight_current_line(True)
        self.editor.set_auto_indent(True)
        self.editor.set_indent_width(2)
        self.editor.set_insert_spaces_instead_of_tabs(True)
        self.editor.set_tab_width(2)
        self.editor.set_left_margin(16); self.editor.set_right_margin(16)
        self.editor.set_top_margin(14); self.editor.set_bottom_margin(120)
        self.editor.connect("key-press-event", self._on_editor_keypress)

        self._apply_editor_font()
        self._apply_source_style()

        self.editor_scroller = Gtk.ScrolledWindow()
        self.editor_scroller.add(self.editor)

        self.search_settings = GtkSource.SearchSettings()
        self.search_settings.set_wrap_around(True)
        self.search_settings.set_case_sensitive(False)
        self.search_context = GtkSource.SearchContext.new(self.editor_buffer,
                                                          self.search_settings)

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
        scheme = scheme_mgr.get_scheme(scheme_id) or scheme_mgr.get_scheme("classic")
        if scheme is not None:
            self.editor_buffer.set_style_scheme(scheme)

    # ---- edit toolbar -------------------------------------------------------

    def _build_edit_toolbar(self):
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        bar.set_margin_start(8); bar.set_margin_end(8)
        bar.set_margin_top(4); bar.set_margin_bottom(4)

        def add(btn):
            bar.pack_start(btn, False, False, 0)

        add(_icon_button("document-new-symbolic", "New (Ctrl+N)", self._on_new))
        add(_icon_button("document-save-symbolic", "Save (Ctrl+S)", lambda *_: self._save()))
        add(_icon_button("document-save-as-symbolic", "Save As (Ctrl+Shift+S)",
                         lambda *_: self._save_as()))
        add(_separator())
        add(_icon_button("edit-undo-symbolic", "Undo (Ctrl+Z)",
                         lambda *_: self._do_undo()))
        add(_icon_button("edit-redo-symbolic", "Redo (Ctrl+Shift+Z)",
                         lambda *_: self._do_redo()))
        add(_separator())
        add(_icon_button("edit-cut-symbolic", "Cut (Ctrl+X)",
                         lambda *_: self._clipboard_action("cut-clipboard")))
        add(_icon_button("edit-copy-symbolic", "Copy (Ctrl+C)",
                         lambda *_: self._clipboard_action("copy-clipboard")))
        add(_icon_button("edit-paste-symbolic", "Paste (Ctrl+V)",
                         lambda *_: self._clipboard_action("paste-clipboard")))
        add(_separator())
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

        bar.pack_start(Gtk.Box(), True, True, 0)

        view_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        view_box.get_style_context().add_class("linked")
        self.view_editor_btn = _toggle_icon("accessories-text-editor-symbolic",
                                            "Editor only")
        self.view_split_btn = _toggle_icon("view-dual-symbolic",
                                           "Split view (live preview)")
        self.view_preview_btn = _toggle_icon("view-reveal-symbolic", "Preview only")
        self.view_editor_btn.set_active(True)
        for b in (self.view_editor_btn, self.view_split_btn, self.view_preview_btn):
            view_box.pack_start(b, False, False, 0)
        self.view_editor_btn.connect("toggled", lambda b: self._set_edit_view("editor", b))
        self.view_split_btn.connect("toggled", lambda b: self._set_edit_view("split", b))
        self.view_preview_btn.connect("toggled", lambda b: self._set_edit_view("preview", b))
        bar.pack_start(view_box, False, False, 0)

        bar.pack_start(_separator(), False, False, 0)
        bar.pack_start(_icon_button("edit-find-symbolic", "Find (Ctrl+F)",
                                    lambda *_: self._toggle_find(True)),
                       False, False, 0)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        outer.pack_start(bar, False, False, 0)
        outer.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL),
                         False, False, 0)

        self.edit_toolbar_revealer = Gtk.Revealer()
        self.edit_toolbar_revealer.set_transition_type(
            Gtk.RevealerTransitionType.SLIDE_DOWN
        )
        self.edit_toolbar_revealer.set_transition_duration(160)
        self.edit_toolbar_revealer.add(outer)

    # ---- find bar -----------------------------------------------------------

    def _build_find_bar(self):
        self.find_entry = Gtk.SearchEntry()
        self.find_entry.set_width_chars(48)
        self.find_entry.connect("search-changed", self._on_find_changed)
        self.find_entry.connect("activate", lambda *_: self._find_step(True))
        self.find_entry.connect("stop-search", lambda *_: self._toggle_find(False))

        inner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        inner.pack_start(self.find_entry, True, True, 0)
        inner.pack_start(_icon_button("go-up-symbolic", "Find previous",
                                      lambda *_: self._find_step(False)),
                         False, False, 0)
        inner.pack_start(_icon_button("go-down-symbolic", "Find next",
                                      lambda *_: self._find_step(True)),
                         False, False, 0)
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
        func = self.search_context.forward2 if forward else self.search_context.backward2
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
            else:
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

        def bind(key, mod, handler):
            keyval = Gdk.keyval_from_name(key)
            accel.connect(keyval, mod, Gtk.AccelFlags.VISIBLE,
                          lambda *_: handler() or True)

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
        bind("f", CTRL | SHIFT, self._open_folder_search)
        bind("p", CTRL, self._open_palette)
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
        dialog = Gtk.FileChooserDialog(title="Open markdown file", parent=self,
                                        action=Gtk.FileChooserAction.OPEN)
        dialog.add_buttons("Cancel", Gtk.ResponseType.CANCEL,
                           "Open", Gtk.ResponseType.OK)
        md = Gtk.FileFilter(); md.set_name("Markdown")
        for p in ("*.md", "*.markdown", "*.mdown", "*.mkd", "*.txt"):
            md.add_pattern(p)
        dialog.add_filter(md)
        all_f = Gtk.FileFilter(); all_f.set_name("All files"); all_f.add_pattern("*")
        dialog.add_filter(all_f)
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
        self._headings_cache = extract_headings(text)
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
        if event in (Gio.FileMonitorEvent.CHANGES_DONE_HINT,
                     Gio.FileMonitorEvent.CREATED):
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
        self._headings_cache = []
        self._update_title()

    def _render_error(self, msg: str):
        md_text = f"# Error\n\n```\n{msg}\n```\n"
        self.webview.load_html(render(md_text, self.theme, "Error"),
                               APP_DIR.as_uri() + "/")

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

    def _ensure_edit_mode(self):
        if not self.edit_btn.get_sensitive():
            self.is_untitled = True
            self.edit_btn.set_sensitive(True)
        if not self.edit_btn.get_active():
            self.edit_btn.set_active(True)

    def _set_mode(self, mode):
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
            if self.editor_buffer.get_modified():
                if self.is_untitled or not self.current_path:
                    if not self._save_as():
                        self.edit_btn.set_active(True)
                        return
                else:
                    self._save()
            self.mode = "preview"
            self._refresh_content()
            if self.current_path and self.current_path.exists():
                self.load_file(self.current_path)

    def _set_edit_view(self, view, btn):
        if getattr(self, "_view_switching", False):
            return
        if not btn.get_active():
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

    def _load_editor_text(self, text):
        self.editor_buffer.handler_block_by_func(self._on_buffer_changed)
        self.editor_buffer.begin_not_undoable_action()
        self.editor_buffer.set_text(text)
        self.editor_buffer.end_not_undoable_action()
        self.editor_buffer.set_modified(False)
        self.editor_buffer.handler_unblock_by_func(self._on_buffer_changed)
        self._update_title()

    def _buffer_text(self):
        s, e = self.editor_buffer.get_bounds()
        return self.editor_buffer.get_text(s, e, True)

    def _on_buffer_changed(self, *_):
        self._headings_cache = extract_headings(self._buffer_text())
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
            name = self.current_path.name if self.current_path else "untitled.md"
            dirty = "  •" if self.editor_buffer.get_modified() else ""
            self.header.props.title = f"{name}{dirty}"
            self.header.props.subtitle = (str(self.current_path.parent)
                                          if self.current_path else "(unsaved)")
        else:
            self.header.props.title = APP_NAME
            self.header.props.subtitle = None

    # ---- scroll-sync (editor cursor → preview anchor) -----------------------

    def _on_cursor_position(self, *_):
        if self.mode != "edit" or self.edit_view != "split":
            return
        if self._scroll_sync_timer is not None:
            GLib.source_remove(self._scroll_sync_timer)
        self._scroll_sync_timer = GLib.timeout_add(
            SCROLL_SYNC_DEBOUNCE_MS, self._do_scroll_sync
        )

    def _do_scroll_sync(self):
        self._scroll_sync_timer = None
        if not self._headings_cache:
            return False
        cur = self.editor_buffer.get_iter_at_mark(self.editor_buffer.get_insert())
        cursor_line = cur.get_line()
        slug = None
        for h in self._headings_cache:
            if h["line"] <= cursor_line:
                slug = h["slug"]
            else:
                break
        if slug:
            js = (
                "window.markview && window.markview.scrollToAnchor("
                f"{json.dumps(slug)});"
            )
            try:
                self.webview.run_javascript(js, None, None, None)
            except Exception:
                pass
        return False

    # ---- webkit ↔ python bridge (task checkbox clicks) ----------------------

    def _on_script_message(self, _ucm, msg):
        try:
            raw = msg.get_js_value().to_string()
            data = json.loads(raw)
        except Exception:
            return
        if data.get("type") == "task_toggle":
            try:
                line = int(data.get("line"))
                checked = bool(data.get("checked"))
            except (TypeError, ValueError):
                return
            self._apply_task_toggle(line, checked)

    def _apply_task_toggle(self, line: int, checked: bool):
        if self.mode == "edit":
            buf = self.editor_buffer
            start = buf.get_iter_at_line(line)
            if not start:
                return
            end = start.copy()
            if not end.ends_line():
                end.forward_to_line_end()
            line_text = buf.get_text(start, end, True)
            new_text = toggle_task_line(line_text, checked)
            if new_text is not None and new_text != line_text:
                buf.begin_user_action()
                buf.delete(start, end)
                buf.insert(start, new_text)
                buf.end_user_action()
        else:
            if not self.current_path:
                return
            try:
                content = self.current_path.read_text(encoding="utf-8")
            except OSError:
                return
            lines = content.split("\n")
            if not (0 <= line < len(lines)):
                return
            updated = toggle_task_line(lines[line], checked)
            if updated is None or updated == lines[line]:
                return
            lines[line] = updated
            try:
                self._suppress_reload_until = GLib.get_monotonic_time() / 1e6 + 1.0
                self.current_path.write_text("\n".join(lines), encoding="utf-8")
            except OSError:
                return
            self._reload()

    # ---- image paste --------------------------------------------------------

    def _on_editor_keypress(self, _w, event):
        if (event.keyval == Gdk.KEY_v
                and (event.state & Gdk.ModifierType.CONTROL_MASK)
                and not (event.state & Gdk.ModifierType.SHIFT_MASK)):
            clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
            if clipboard.wait_is_image_available():
                pixbuf = clipboard.wait_for_image()
                if pixbuf is not None:
                    return self._handle_image_paste(pixbuf)
        return False

    def _handle_image_paste(self, pixbuf) -> bool:
        if self.current_path:
            assets_dir = self.current_path.parent / "assets"
        else:
            assets_dir = Path.home() / "Pictures" / "markview"
        try:
            assets_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            return False
        ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        img_path = assets_dir / f"image-{ts}.png"
        n = 1
        while img_path.exists():
            n += 1
            img_path = assets_dir / f"image-{ts}-{n}.png"
        try:
            pixbuf.savev(str(img_path), "png", [], [])
        except Exception:
            return False
        if self.current_path:
            try:
                rel = os.path.relpath(img_path, self.current_path.parent)
                ref = rel.replace(os.sep, "/")
            except ValueError:
                ref = str(img_path)
        else:
            ref = str(img_path)
        self._insert_text(f"![{img_path.stem}]({ref})\n")
        return True

    # ---- command palette + folder search -----------------------------------

    def _open_palette(self, *_):
        palette = CommandPalette(
            self,
            provider=self._palette_items,
            on_select=self._palette_select,
            placeholder="Jump to file, heading, or action…",
        )
        palette.show_all()

    def _open_folder_search(self, *_):
        base = (self.current_path.parent if self.current_path else Path.cwd())
        palette = CommandPalette(
            self,
            provider=lambda q: self._folder_search_items(base, q),
            on_select=self._palette_select,
            placeholder=f"Search {base} …",
            min_query_chars=2,
        )
        palette.show_all()

    def _palette_items(self, query: str):
        q = (query or "").lower().strip()
        items = []
        actions = [
            ("Open file…", "Ctrl+O", "action:open"),
            ("New document", "Ctrl+N", "action:new"),
            ("Save", "Ctrl+S", "action:save"),
            ("Save As…", "Ctrl+Shift+S", "action:save_as"),
            ("Toggle edit mode", "Ctrl+E", "action:edit"),
            ("Editor only", "", "action:editor_only"),
            ("Split view (live preview)", "", "action:split"),
            ("Preview only", "", "action:preview_only"),
            ("Reload", "Ctrl+R", "action:reload"),
            ("Toggle theme", "Ctrl+D", "action:theme"),
            ("Search in folder…", "Ctrl+Shift+F", "action:folder_search"),
        ]
        for label, sub, key in actions:
            items.append({"label": label, "sub": sub, "key": key})

        source = ""
        if self.mode == "edit":
            source = self._buffer_text()
        elif self.current_path and self.current_path.exists():
            try:
                source = self.current_path.read_text(encoding="utf-8")
            except OSError:
                source = ""
        for h in extract_headings(source):
            items.append({
                "label": ("#" * h["level"]) + " " + h["title"],
                "sub": f"heading · line {h['line'] + 1}",
                "key": f"heading:{h['line']}",
            })

        folder = self.current_path.parent if self.current_path else None
        if folder and folder.is_dir():
            try:
                md_files = sorted(folder.rglob("*.md"))[:200]
            except OSError:
                md_files = []
            for f in md_files:
                if self.current_path and f == self.current_path:
                    continue
                try:
                    rel = f.relative_to(folder)
                except ValueError:
                    rel = f
                items.append({
                    "label": f.name,
                    "sub": f"file · {rel}",
                    "key": f"file:{f}",
                })

        if not q:
            return items[:PALETTE_ITEM_CAP]
        return [it for it in items
                if q in it["label"].lower()
                or q in (it.get("sub") or "").lower()][:PALETTE_ITEM_CAP]

    def _folder_search_items(self, base: Path, query: str):
        query = query.strip()
        if len(query) < 2:
            return []
        pat = re.compile(re.escape(query), re.IGNORECASE)
        results = []
        try:
            files = sorted(base.rglob("*.md"))
        except OSError:
            files = []
        for f in files:
            if any(part in (".git", "node_modules", ".venv", "__pycache__")
                   for part in f.parts):
                continue
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for i, line in enumerate(text.split("\n")):
                if pat.search(line):
                    try:
                        rel = f.relative_to(base)
                    except ValueError:
                        rel = f
                    snippet = line.strip()
                    if len(snippet) > 140:
                        snippet = snippet[:140] + "…"
                    results.append({
                        "label": snippet or "(empty line match)",
                        "sub": f"{rel}:{i + 1}",
                        "key": f"file_line:{f}:{i}",
                    })
                    if len(results) >= SEARCH_RESULT_CAP:
                        return results
        return results

    def _palette_select(self, key):
        if key is None:
            return
        if key.startswith("action:"):
            name = key[len("action:"):]
            dispatch = {
                "open": self._on_open_clicked,
                "new": self._on_new,
                "save": lambda *_: self._save(),
                "save_as": lambda *_: self._save_as(),
                "edit": self._toggle_edit,
                "reload": lambda *_: self._reload(),
                "theme": self._toggle_theme,
                "folder_search": lambda *_: self._open_folder_search(),
                "split": lambda *_: (self._ensure_edit_mode(),
                                     self._set_edit_view("split",
                                                         self.view_split_btn)),
                "editor_only": lambda *_: (self._ensure_edit_mode(),
                                           self._set_edit_view("editor",
                                                               self.view_editor_btn)),
                "preview_only": lambda *_: (self._ensure_edit_mode(),
                                            self._set_edit_view("preview",
                                                                self.view_preview_btn)),
            }
            fn = dispatch.get(name)
            if fn:
                fn()
            return
        if key.startswith("heading:"):
            line = int(key[len("heading:"):])
            self._goto_line(line)
            return
        if key.startswith("file:"):
            self.load_file(Path(key[len("file:"):]))
            return
        if key.startswith("file_line:"):
            rest = key[len("file_line:"):]
            path_str, line_str = rest.rsplit(":", 1)
            self.load_file(Path(path_str))
            GLib.idle_add(self._goto_line, int(line_str))
            return

    def _goto_line(self, line: int):
        self._ensure_edit_mode()
        if self.edit_view == "preview":
            self.view_editor_btn.set_active(True)
        buf = self.editor_buffer
        it = buf.get_iter_at_line(line)
        if it:
            buf.place_cursor(it)
            self.editor.scroll_to_iter(it, 0.2, True, 0.0, 0.2)
            self.editor.grab_focus()
        return False

    # ---- file: new / save / save as -----------------------------------------

    def _on_new(self, *_):
        if not self._confirm_discard_if_dirty():
            return
        self.current_path = None
        self.is_untitled = True
        self.edit_btn.set_sensitive(True)
        self._load_editor_text("# Untitled\n\n")
        self._headings_cache = extract_headings("# Untitled\n\n")
        if self.monitor is not None:
            self.monitor.cancel()
            self.monitor = None
        self.edit_btn.set_active(True)
        if self.mode == "edit" and self.edit_view in ("split", "preview"):
            self._render_live_preview()

    def _save(self, *_):
        if self.mode != "edit" and not self.editor_buffer.get_modified():
            return True
        if self.is_untitled or not self.current_path:
            return self._save_as()
        return self._write_to(self.current_path)

    def _save_as(self, *_):
        dialog = Gtk.FileChooserDialog(title="Save markdown file", parent=self,
                                        action=Gtk.FileChooserAction.SAVE)
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

    def _confirm_discard_if_dirty(self):
        if not self.editor_buffer.get_modified():
            return True
        dialog = Gtk.MessageDialog(parent=self, flags=0,
                                   message_type=Gtk.MessageType.QUESTION,
                                   buttons=Gtk.ButtonsType.NONE,
                                   text="You have unsaved changes.")
        dialog.format_secondary_text("Save before continuing?")
        dialog.add_buttons("Discard", Gtk.ResponseType.CLOSE,
                           "Cancel", Gtk.ResponseType.CANCEL,
                           "Save", Gtk.ResponseType.ACCEPT)
        response = dialog.run()
        dialog.destroy()
        if response == Gtk.ResponseType.CANCEL:
            return False
        if response == Gtk.ResponseType.ACCEPT:
            return self._save()
        return True

    # ---- undo / redo / clipboard / format ----------------------------------

    def _do_undo(self):
        if self.editor_buffer.can_undo():
            self.editor_buffer.undo()

    def _do_redo(self):
        if self.editor_buffer.can_redo():
            self.editor_buffer.redo()

    def _clipboard_action(self, signal_name):
        self.editor.emit(signal_name)

    def _insert_text(self, text):
        if not self.editor.is_focus():
            self.editor.grab_focus()
        self.editor_buffer.begin_user_action()
        self.editor_buffer.insert_at_cursor(text)
        self.editor_buffer.end_user_action()

    def _wrap_selection(self, left, right, placeholder):
        buf = self.editor_buffer
        buf.begin_user_action()
        if buf.get_has_selection():
            s, e = buf.get_selection_bounds()
            sel = buf.get_text(s, e, True)
            buf.delete(s, e)
            buf.insert(s, f"{left}{sel}{right}")
        else:
            buf.insert_at_cursor(f"{left}{placeholder}{right}")
            end_iter = buf.get_iter_at_mark(buf.get_insert())
            start_iter = end_iter.copy()
            start_iter.backward_chars(len(right) + len(placeholder))
            end_iter.backward_chars(len(right))
            buf.select_range(start_iter, end_iter)
        buf.end_user_action()
        self.editor.grab_focus()

    def _prefix_line(self, prefix, toggle=False):
        buf = self.editor_buffer
        buf.begin_user_action()
        if buf.get_has_selection():
            s, e = buf.get_selection_bounds()
            s.set_line_offset(0)
            if not e.ends_line():
                e.forward_to_line_end()
            self._prefix_range(buf, s, e, prefix, toggle)
        else:
            it = buf.get_iter_at_mark(buf.get_insert())
            ls = it.copy(); ls.set_line_offset(0)
            le = it.copy()
            if not le.ends_line():
                le.forward_to_line_end()
            self._prefix_range(buf, ls, le, prefix, toggle)
        buf.end_user_action()
        self.editor.grab_focus()

    def _prefix_range(self, buf, start_iter, end_iter, prefix, toggle):
        for line_idx in range(start_iter.get_line(), end_iter.get_line() + 1):
            li = buf.get_iter_at_line(line_idx)
            if not li:
                continue
            le = li.copy()
            if not le.ends_line():
                le.forward_to_line_end()
            current = buf.get_text(li, le, True)
            if toggle and current.startswith(prefix):
                ep = li.copy(); ep.forward_chars(len(prefix))
                buf.delete(li, ep)
            else:
                buf.insert(li, prefix)

    def _insert_link(self):
        buf = self.editor_buffer
        buf.begin_user_action()
        if buf.get_has_selection():
            s, e = buf.get_selection_bounds()
            label = buf.get_text(s, e, True)
            buf.delete(s, e)
            buf.insert(s, f"[{label}](https://)")
        else:
            buf.insert_at_cursor("[text](https://)")
        buf.end_user_action()
        self.editor.grab_focus()

    def _insert_image(self):
        dialog = Gtk.FileChooserDialog(title="Insert image", parent=self,
                                        action=Gtk.FileChooserAction.OPEN)
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
        img_path = Path(chosen)
        if self.current_path:
            try:
                rel = os.path.relpath(img_path, self.current_path.parent)
                ref = rel.replace(os.sep, "/")
            except ValueError:
                ref = str(img_path)
        else:
            ref = str(img_path)
        self.editor_buffer.insert_at_cursor(f"![{img_path.stem}]({ref})")
        self.editor.grab_focus()


# --- app boot ----------------------------------------------------------------

class App(Gtk.Application):
    def __init__(self, path):
        super().__init__(application_id=APP_ID,
                         flags=Gio.ApplicationFlags.NON_UNIQUE)
        self._initial_path = path

    def do_activate(self):
        win = Viewer(self, self._initial_path)
        win.show_all()
        win.find_bar.set_search_mode(False)


def parse_args(argv):
    parser = argparse.ArgumentParser(prog=APP_NAME,
        description="Minimal modern markdown viewer + editor.")
    parser.add_argument("file", nargs="?", help="Path to a markdown file.")
    parser.add_argument("-V", "--version", action="version",
                        version=f"{APP_NAME} {__version__}")
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
