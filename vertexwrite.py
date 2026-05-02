#!/usr/bin/env python3
"""VertexWrite — Markdown editing for local and SSH/SFTP files on Linux."""
import os
import re
import sys
import json
import shlex
import shutil
import argparse
import subprocess
import datetime
import gzip
import posixpath
import threading
import urllib.request
import urllib.error
from dataclasses import dataclass
from pathlib import Path

from vertexwrite_files import (
    FileInfo,
    FileUri,
    StorageError,
    backend_for,
    parse_remote_target,
)

# WebKitGTK can abort during startup on some NVIDIA/Wayland GBM stacks unless
# the DMABUF renderer is disabled before WebKit is loaded.
os.environ.setdefault("WEBKIT_DISABLE_DMABUF_RENDERER", "1")

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("WebKit2", "4.1")
# VertexWrite is a GTK 3 application. GtkSourceView 5 targets GTK 4 and cannot
# be loaded in the same process, so the Linux build requires GtkSourceView 4.
gi.require_version("GtkSource", "4")
from gi.repository import Gtk, WebKit2, Gio, GLib, Gdk, GtkSource, Pango, GdkPixbuf  # noqa: E402

from vertexwrite_core import (  # noqa: E402
    LIST_BULLET_RE,
    LIST_ORDERED_RE,
    MD_LINK_RE,
    TASK_LINE_RE,
    WIKI_LINK_RE,
    count_words_and_read_time as _count_words_and_read_time,
    csv_to_markdown_table as _csv_to_markdown_table,
    extract_headings as _extract_headings,
    html_to_markdown as _html_to_markdown,
    list_snapshots as _list_snapshots,
    looks_like_csv as _looks_like_csv,
    preprocess_tasks as _preprocess_tasks,
    preprocess_transclusions as _preprocess_transclusions,
    render as _render,
    toggle_task_line as _toggle_task_line,
    write_snapshot as _write_snapshot,
)

__version__ = "0.7.5"

APP_ID = "com.canarybuilds.VertexWrite"
APP_NAME = "VertexWrite"
APP_SLUG = "vertexwrite"
APP_CLI = "vertexwrite"
LEGACY_APP_SLUGS = ("vertexmarkdown", "markview")
APP_DIR = Path(__file__).resolve().parent
STYLE_PATH = APP_DIR / "style.css"


def _app_data_dir(env_var: str, fallback_base: Path) -> Path:
    base = Path(os.environ.get(env_var, str(fallback_base)))
    target = base / APP_SLUG
    if target.exists():
        return target
    for slug in LEGACY_APP_SLUGS:
        legacy = base / slug
        if legacy.exists():
            return legacy
    return target


CONFIG_DIR = _app_data_dir("XDG_CONFIG_HOME", Path.home() / ".config")
STATE_DIR = _app_data_dir("XDG_STATE_HOME", Path.home() / ".local/state")
CUSTOM_CSS_PATH = CONFIG_DIR / "custom.css"
SNAPSHOT_DIR = STATE_DIR / "snapshots"
LAST_SHOWN_VERSION_PATH = STATE_DIR / "last-shown-version"

DEVELOPER = "Canary Builds"
WEBSITE = "https://canarybuilds.com/"
REPO_URL = "https://github.com/Canary-Builds/vertexwrite"
ISSUES_URL = f"{REPO_URL}/issues/new/choose"
WIKI_URL = f"{REPO_URL}/wiki"

LIVE_PREVIEW_DEBOUNCE_MS = 220
SCROLL_SYNC_DEBOUNCE_MS = 80
WORD_COUNT_DEBOUNCE_MS = 250
SEARCH_RESULT_CAP = 500
PALETTE_ITEM_CAP = 200
SNAPSHOT_KEEP = 30
RECENTS_PATH = STATE_DIR / "recent.json"
RECENT_MAX = 50
MARKDOWN_ROOT_PATH = STATE_DIR / "markdown-root.txt"
MARKDOWN_EXTENSIONS = {".md", ".markdown", ".mdown", ".mkd"}
SIDEBAR_MIN_WIDTH = 180
SIDEBAR_INDENT_STEP = 8
SIDEBAR_INDENT_MAX = 32

preprocess_tasks = _preprocess_tasks
preprocess_transclusions = _preprocess_transclusions
extract_headings = _extract_headings
toggle_task_line = _toggle_task_line
html_to_markdown = _html_to_markdown
count_words_and_read_time = _count_words_and_read_time
looks_like_csv = _looks_like_csv
csv_to_markdown_table = _csv_to_markdown_table


def render(md_text: str, theme: str, title: str, base_dir: Path | None = None) -> str:
    return _render(
        md_text,
        theme,
        title,
        base_dir,
        style_path=STYLE_PATH,
        custom_css_path=CUSTOM_CSS_PATH,
    )


def write_snapshot(path: Path, text: str) -> Path | None:
    return _write_snapshot(
        path,
        text,
        snapshot_dir=SNAPSHOT_DIR,
        snapshot_keep=SNAPSHOT_KEEP,
    )


def list_snapshots(path: Path) -> list[Path]:
    return _list_snapshots(path, snapshot_dir=SNAPSHOT_DIR)


@dataclass(frozen=True)
class RecentDocument:
    uri: FileUri

    @property
    def title(self) -> str:
        return self.uri.name

    @property
    def subtitle(self) -> str:
        return self.uri.display()

    @property
    def local_path(self) -> Path | None:
        if not self.uri.is_local:
            return None
        return self.uri.to_path()

    @property
    def key(self) -> str:
        return str(self.uri)


def _recent_from_local_path(path: Path) -> RecentDocument | None:
    try:
        return RecentDocument(uri=FileUri.from_path(path))
    except (OSError, ValueError):
        return None


def _recent_from_uri(uri: str) -> RecentDocument | None:
    try:
        return RecentDocument(uri=FileUri.parse(uri))
    except ValueError:
        return None


def _coerce_recent(item) -> RecentDocument | None:
    if isinstance(item, RecentDocument):
        return item
    if isinstance(item, Path):
        return _recent_from_local_path(item)
    if isinstance(item, str) and item.strip():
        return _recent_from_uri(item.strip())
    if isinstance(item, dict):
        uri = item.get("uri")
        if isinstance(uri, str):
            return _recent_from_uri(uri)
    return None


def load_recents() -> list[RecentDocument]:
    try:
        raw = json.loads(RECENTS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw:
        recent = _coerce_recent(item)
        if recent is not None:
            out.append(recent)
    return out


def save_recents(items: list[RecentDocument | Path]):
    unique: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in items:
        recent = _coerce_recent(item)
        if recent is None:
            continue
        if recent.key in seen:
            continue
        seen.add(recent.key)
        unique.append({"uri": recent.key})
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        RECENTS_PATH.write_text(
            json.dumps(unique[:RECENT_MAX], ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError:
        pass


def add_recent_uri(uri: FileUri):
    recent = RecentDocument(uri=uri)
    recents = load_recents()
    recents = [item for item in recents if item.key != recent.key]
    recents.insert(0, recent)
    save_recents(recents)


def add_recent(path: Path):
    recent = _recent_from_local_path(path)
    if recent is not None:
        add_recent_uri(recent.uri)


def load_markdown_root_uri() -> FileUri | None:
    try:
        value = MARKDOWN_ROOT_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not value:
        return None
    try:
        uri = FileUri.parse(value)
    except ValueError:
        return None
    if uri.is_remote:
        return uri
    path = uri.to_path()
    return uri if path.is_dir() else None


def load_markdown_root() -> Path | None:
    uri = load_markdown_root_uri()
    if uri is None or not uri.is_local:
        return None
    return uri.to_path()


def save_markdown_root_uri(root: FileUri | Path | None):
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        if root is None:
            if MARKDOWN_ROOT_PATH.exists():
                MARKDOWN_ROOT_PATH.unlink()
            return
        if isinstance(root, FileUri):
            value = str(root) if root.is_remote else str(root.to_path().resolve())
        else:
            value = str(root.resolve())
        MARKDOWN_ROOT_PATH.write_text(value, encoding="utf-8")
    except OSError:
        pass


def save_markdown_root(path: Path | None):
    save_markdown_root_uri(path)


def welcome_html(theme: str) -> str:
    md_text = (
        f"# VertexWrite\n\n*v{__version__} — edit Markdown locally or over SSH/SFTP.*\n\n"
        '<div class="vw-actions">\n'
        '<button type="button" class="vw-action" data-vw-action="new">New document</button>\n'
        '<button type="button" class="vw-action secondary" data-vw-action="open">Open file</button>\n'
        '<button type="button" class="vw-action secondary" data-vw-action="sidebar">Show sidebar</button>\n'
        '<button type="button" class="vw-action secondary" data-vw-action="remote">Connect SSH/SFTP</button>\n'
        "</div>\n\n"
        "- **New document** — `Ctrl+N` or the header button\n"
        "- **Open** — `Ctrl+O`, drag & drop, or CLI path\n"
        "- **Sidebar** — `Ctrl+Shift+O` shows recent documents and a file-browser folder tree\n"
        "- **SSH/SFTP** — use the sidebar's bottom SSH control or **Connect SSH/SFTP** to browse remote servers\n"
        "- **Folder tree** — browse folders and files, navigate into folders, refresh, and toggle hidden dotfiles\n"
        "- **Edit mode** — `Ctrl+E` (reveals the edit toolbar)\n"
        "- **Palette** — `Ctrl+P` · **Folder search** — `Ctrl+Shift+F`\n"
        "- **Typewriter mode** — `Ctrl+Shift+T`\n"
        "- **Navigate** — `Alt+←` / `Alt+→`\n"
        "- **Theme** — `Ctrl+D` · **Reload** — `Ctrl+R` · **Quit** — `Ctrl+Q`\n"
    )
    return render(md_text, theme, APP_NAME, APP_DIR)


def _icon_button(icon_name, tooltip, on_click=None):
    btn = Gtk.Button.new_from_icon_name(icon_name, Gtk.IconSize.BUTTON)
    btn.set_relief(Gtk.ReliefStyle.NONE)
    btn.set_tooltip_text(tooltip)
    btn.get_style_context().add_class("flat")
    if on_click is not None:
        btn.connect("clicked", on_click)
    return btn


def _toggle_icon(icon_name, tooltip):
    btn = Gtk.ToggleButton()
    btn.set_image(Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.BUTTON))
    btn.set_relief(Gtk.ReliefStyle.NONE)
    btn.set_tooltip_text(tooltip)
    btn.get_style_context().add_class("flat")
    return btn


def _separator():
    sep = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
    sep.set_margin_start(4)
    sep.set_margin_end(4)
    return sep


def _shrink_label(
        text: str,
        *,
        ellipsize=Pango.EllipsizeMode.END,
        xalign=0) -> Gtk.Label:
    label = Gtk.Label(label=text, xalign=xalign)
    label.set_ellipsize(ellipsize)
    label.set_single_line_mode(True)
    label.set_hexpand(True)
    label.set_halign(Gtk.Align.FILL)
    label.set_size_request(1, -1)
    label.set_max_width_chars(1)
    return label


def _menu_button(icon_name, tooltip, items):
    """items: list of (label, callback) tuples; None means a separator."""
    btn = Gtk.MenuButton()
    btn.set_image(Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.BUTTON))
    btn.set_tooltip_text(tooltip)
    btn.set_relief(Gtk.ReliefStyle.NONE)
    btn.get_style_context().add_class("flat")
    popover = Gtk.Popover()
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
    box.set_margin_top(4)
    box.set_margin_bottom(4)
    box.set_margin_start(4)
    box.set_margin_end(4)
    for entry in items:
        if entry is None:
            sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
            sep.set_margin_top(4)
            sep.set_margin_bottom(4)
            box.pack_start(sep, False, False, 0)
            continue
        label, callback = entry
        item = Gtk.ModelButton()
        item.set_property("text", label)
        item.connect("clicked", lambda _b, cb=callback: cb())
        box.pack_start(item, False, False, 0)
    box.show_all()
    popover.add(box)
    btn.set_popover(popover)
    return btn


# --- command palette ---------------------------------------------------------

class CommandPalette(Gtk.Window):
    def __init__(
            self,
            parent,
            provider,
            on_select,
            placeholder="Type to filter…",
            min_query_chars=0,
            initial_query=""):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.set_decorated(False)
        self.set_transient_for(parent)
        self.set_modal(True)
        self.set_destroy_with_parent(True)
        self.set_skip_taskbar_hint(True)
        self.set_position(Gtk.WindowPosition.CENTER_ON_PARENT)
        self.set_default_size(680, 460)
        self.set_resizable(False)
        self.provider = provider
        self.on_select = on_select
        self.min_query_chars = min_query_chars

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        outer.set_margin_top(10)
        outer.set_margin_bottom(10)
        outer.set_margin_start(10)
        outer.set_margin_end(10)
        self.entry = Gtk.SearchEntry()
        self.entry.set_placeholder_text(placeholder)
        if initial_query:
            self.entry.set_text(initial_query)
        self.entry.connect("search-changed", self._refresh)
        self.entry.connect("activate", lambda *_: self._activate_selected())
        self.entry.connect("key-press-event", self._on_entry_key)
        outer.pack_start(self.entry, False, False, 4)

        self.listbox = Gtk.ListBox()
        self.listbox.set_activate_on_single_click(True)
        self.listbox.connect(
            "row-activated",
            lambda _lb,
            row: self._select_row(row))
        scroller = Gtk.ScrolledWindow()
        scroller.set_hexpand(True)
        scroller.set_vexpand(True)
        scroller.add(self.listbox)
        outer.pack_start(scroller, True, True, 0)
        self.add(outer)

        self.connect("key-press-event", self._on_window_key)
        self.connect("focus-out-event", lambda *_: self.destroy())
        self._refresh()

    def _refresh(self, *_):
        for c in self.listbox.get_children():
            self.listbox.remove(c)
        q = self.entry.get_text() or ""
        if len(q.strip()) < self.min_query_chars:
            items = [{"label": f"Type at least {self.min_query_chars} characters…",
                      "sub": None, "key": None}]
        else:
            items = self.provider(q) or []
        for item in items[:PALETTE_ITEM_CAP]:
            self.listbox.add(self._row(item))
        self.listbox.show_all()
        first = self.listbox.get_row_at_index(0)
        if first:
            self.listbox.select_row(first)

    def _row(self, item):
        row = Gtk.ListBoxRow()
        row.item_key = item.get("key")
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        vbox.set_margin_top(4)
        vbox.set_margin_bottom(4)
        vbox.set_margin_start(6)
        vbox.set_margin_end(6)
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
            cur = self.listbox.get_selected_row()
            idx = cur.get_index() if cur else -1
            idx += 1 if event.keyval == Gdk.KEY_Down else -1
            total = len(self.listbox.get_children())
            if not total:
                return True
            idx = max(0, min(idx, total - 1))
            new_row = self.listbox.get_row_at_index(idx)
            if new_row:
                self.listbox.select_row(new_row)
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


# --- remote file browser -----------------------------------------------------

class RemoteFileBrowserDialog(Gtk.Dialog):
    def __init__(self, parent, root_uri: FileUri, select_mode: str):
        super().__init__(title="Browse Remote Server", parent=parent, flags=0)
        if select_mode not in {"folder", "file"}:
            raise ValueError("select_mode must be 'folder' or 'file'")
        self.select_mode = select_mode
        self.current_uri = root_uri
        self._result_uri: FileUri | None = None
        self._raw_entries: list[FileInfo] = []
        self._load_generation = 0
        self._loading = False
        self._show_hidden = False

        self.set_default_size(760, 540)
        self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        self.select_button = Gtk.Button(
            label="Use Current Folder"
            if select_mode == "folder"
            else "Choose File"
        )
        self.select_button.get_style_context().add_class("suggested-action")
        self.select_button.connect("clicked", self._accept_selection)
        self.get_action_area().pack_end(self.select_button, False, False, 0)

        box = self.get_content_area()
        box.set_spacing(8)
        box.set_margin_top(10)
        box.set_margin_bottom(10)
        box.set_margin_start(12)
        box.set_margin_end(12)

        title = _shrink_label(
            root_uri.authority,
            ellipsize=Pango.EllipsizeMode.MIDDLE,
        )
        title.get_style_context().add_class("dim-label")
        box.pack_start(title, False, False, 0)

        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.home_button = _icon_button(
            "go-home-symbolic",
            "Go to remote home",
            self._go_home,
        )
        self.up_button = _icon_button(
            "go-up-symbolic",
            "Go to parent folder",
            self._go_up,
        )
        self.refresh_button = _icon_button(
            "view-refresh-symbolic",
            "Reload remote folder",
            self._refresh,
        )
        self.show_hidden_check = Gtk.CheckButton.new_with_label("Show hidden")
        self.show_hidden_check.set_tooltip_text("Show dotfiles and dotfolders")
        self.show_hidden_check.connect("toggled", self._on_show_hidden_toggled)
        self.path_entry = Gtk.Entry()
        self.path_entry.set_hexpand(True)
        self.path_entry.set_placeholder_text("/home/user/docs or ~/docs")
        self.path_entry.set_activates_default(True)
        self.path_entry.connect("activate", self._go_to_entry)
        self.go_button = Gtk.Button(label="Go")
        self.go_button.connect("clicked", self._go_to_entry)
        toolbar.pack_start(self.home_button, False, False, 0)
        toolbar.pack_start(self.up_button, False, False, 0)
        toolbar.pack_start(self.refresh_button, False, False, 0)
        toolbar.pack_start(self.show_hidden_check, False, False, 0)
        toolbar.pack_start(self.path_entry, True, True, 0)
        toolbar.pack_start(self.go_button, False, False, 0)
        box.pack_start(toolbar, False, False, 0)

        self.status_label = _shrink_label("")
        self.status_label.get_style_context().add_class("dim-label")
        box.pack_start(self.status_label, False, False, 0)

        self.listbox = Gtk.ListBox()
        self.listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.listbox.set_activate_on_single_click(False)
        self.listbox.connect("row-activated", self._on_row_activated)
        self.listbox.connect("row-selected", self._on_row_selected)
        scroller = Gtk.ScrolledWindow()
        scroller.set_hexpand(True)
        scroller.set_vexpand(True)
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.add(self.listbox)
        box.pack_start(scroller, True, True, 0)

        help_text = (
            "Double-click folders to navigate. "
            "Files are shown so you can confirm the remote location."
        )
        if select_mode == "file":
            help_text = "Double-click folders to navigate, then choose a file."
        help_label = Gtk.Label(label=help_text, xalign=0)
        help_label.set_line_wrap(True)
        help_label.get_style_context().add_class("dim-label")
        box.pack_start(help_label, False, False, 0)

        self.connect("key-press-event", self._on_key_press)
        self._load_directory(root_uri)

    @property
    def result_uri(self) -> FileUri | None:
        return self._result_uri

    def _set_loading(self, loading: bool, status: str):
        self._loading = loading
        self.status_label.set_text(status)
        self.listbox.set_sensitive(not loading)
        self.home_button.set_sensitive(not loading)
        self.up_button.set_sensitive(not loading and self.current_uri.path != "/")
        self.refresh_button.set_sensitive(not loading)
        self.show_hidden_check.set_sensitive(not loading)
        self.path_entry.set_sensitive(not loading)
        self.go_button.set_sensitive(not loading)
        self.select_button.set_sensitive(not loading)

    def _load_directory(self, uri: FileUri):
        if not uri.is_remote:
            self.status_label.set_text("Remote browser requires an SFTP URI.")
            return
        self._load_generation += 1
        generation = self._load_generation
        self.current_uri = uri
        self.path_entry.set_text(uri.path)
        self._clear_rows()
        self._set_loading(True, f"Loading {uri.display()}...")

        def worker():
            backend = backend_for(uri)
            normalize = getattr(backend, "normalize_uri", None)
            current = normalize(uri) if normalize else uri
            info = backend.stat(current)
            if info.is_file:
                current = current.parent
            entries = backend.list_dir(current)
            return current, entries

        def done(result, error):
            if generation != self._load_generation:
                return False
            if error is not None:
                self._set_loading(False, f"Load failed: {error}")
                self.select_button.set_sensitive(False)
                self._show_message_row("Could not load remote folder", str(error))
                return False
            current, entries = result
            self.current_uri = current
            self.path_entry.set_text(current.path)
            self._raw_entries = entries
            self._render_entries(entries)
            count = len(self._visible_entries(entries))
            noun = "item" if count == 1 else "items"
            self._set_loading(False, f"{count} {noun} in {current.display()}")
            self._update_selection_action()
            return False

        threading.Thread(
            target=self._run_worker,
            args=(worker, done),
            daemon=True,
        ).start()

    def _run_worker(self, worker, done):
        try:
            result = worker()
            error = None
        except Exception as exc:
            result = None
            error = exc
        GLib.idle_add(done, result, error)

    def _render_entries(self, entries: list[FileInfo]):
        self._clear_rows()
        if self.current_uri.path != "/":
            self.listbox.add(
                self._browser_row(
                    "..",
                    self.current_uri.parent,
                    is_dir=True,
                    subtitle="Parent folder",
                )
            )
        visible_entries = self._visible_entries(entries)
        if not visible_entries:
            hidden_count = len(entries) - len(visible_entries)
            message = (
                "Only hidden files are in this folder"
                if hidden_count
                else "This remote folder is empty"
            )
            detail = (
                "Turn on Show hidden to display dotfiles."
                if hidden_count
                else ""
            )
            self._show_message_row(message, detail)
        for info in visible_entries:
            subtitle = "Folder" if info.is_dir else self._file_subtitle(info)
            self.listbox.add(
                self._browser_row(
                    info.name,
                    info.uri,
                    is_dir=info.is_dir,
                    subtitle=subtitle,
                )
            )
        self.listbox.show_all()

    def _visible_entries(self, entries: list[FileInfo]) -> list[FileInfo]:
        return [
            info for info in entries
            if info.name not in {".", ".."}
            and (self._show_hidden or not info.name.startswith("."))
        ]

    def _browser_row(
            self,
            name: str,
            uri: FileUri,
            *,
            is_dir: bool,
            subtitle: str):
        row = Gtk.ListBoxRow()
        row.file_uri = uri
        row.is_dir = is_dir
        row.set_tooltip_text(uri.display())
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        hbox.set_margin_top(5)
        hbox.set_margin_bottom(5)
        hbox.set_margin_start(8)
        hbox.set_margin_end(8)
        icon = Gtk.Image.new_from_icon_name(
            "folder-symbolic" if is_dir else "text-x-generic-symbolic",
            Gtk.IconSize.MENU,
        )
        hbox.pack_start(icon, False, False, 0)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        text.set_hexpand(True)
        label = _shrink_label(name)
        sub = _shrink_label(subtitle, ellipsize=Pango.EllipsizeMode.MIDDLE)
        sub.get_style_context().add_class("dim-label")
        text.pack_start(label, False, False, 0)
        text.pack_start(sub, False, False, 0)
        hbox.pack_start(text, True, True, 0)
        row.add(hbox)
        return row

    def _show_message_row(self, message: str, detail: str):
        row = Gtk.ListBoxRow()
        row.file_uri = None
        row.is_dir = False
        row.set_selectable(False)
        row.set_activatable(False)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(8)
        box.set_margin_end(8)
        label = Gtk.Label(label=message, xalign=0)
        box.pack_start(label, False, False, 0)
        if detail:
            sub = _shrink_label(detail, ellipsize=Pango.EllipsizeMode.MIDDLE)
            sub.get_style_context().add_class("dim-label")
            box.pack_start(sub, False, False, 0)
        row.add(box)
        self.listbox.add(row)
        self.listbox.show_all()

    def _clear_rows(self):
        for child in self.listbox.get_children():
            self.listbox.remove(child)

    def _file_subtitle(self, info: FileInfo) -> str:
        return f"File · {self._format_size(info.size)}"

    def _format_size(self, size: int) -> str:
        value = float(size)
        for unit in ("B", "KB", "MB", "GB"):
            if value < 1024 or unit == "GB":
                if unit == "B":
                    return f"{int(value)} {unit}"
                return f"{value:.1f} {unit}"
            value /= 1024
        return f"{size} B"

    def _selected_row_uri(self) -> tuple[FileUri | None, bool]:
        row = self.listbox.get_selected_row()
        if row is None:
            return None, False
        return getattr(row, "file_uri", None), bool(getattr(row, "is_dir", False))

    def _on_row_selected(self, *_):
        self._update_selection_action()

    def _update_selection_action(self):
        if self._loading:
            return
        uri, is_dir = self._selected_row_uri()
        if self.select_mode == "folder":
            self.select_button.set_sensitive(True)
            self.select_button.set_label(
                "Use Selected Folder" if uri and is_dir else "Use Current Folder"
            )
            return
        self.select_button.set_sensitive(bool(uri and not is_dir))

    def _on_row_activated(self, _lb, row):
        uri = getattr(row, "file_uri", None)
        if uri is None:
            return
        if getattr(row, "is_dir", False):
            self._load_directory(uri)
            return
        if self.select_mode == "file":
            self._result_uri = uri
            self.response(Gtk.ResponseType.OK)

    def _accept_selection(self, *_):
        uri, is_dir = self._selected_row_uri()
        if self.select_mode == "folder":
            self._result_uri = uri if uri and is_dir else self.current_uri
            self.response(Gtk.ResponseType.OK)
            return
        if uri is None or is_dir:
            self.status_label.set_text("Choose a file first.")
            return
        self._result_uri = uri
        self.response(Gtk.ResponseType.OK)

    def _go_home(self, *_):
        self._load_directory(FileUri("sftp", "/.", self.current_uri.authority))

    def _go_up(self, *_):
        if self.current_uri.path != "/":
            self._load_directory(self.current_uri.parent)

    def _refresh(self, *_):
        self._load_directory(self.current_uri)

    def _on_show_hidden_toggled(self, button):
        self._show_hidden = button.get_active()
        self._render_entries(self._raw_entries)
        count = len(self._visible_entries(self._raw_entries))
        noun = "item" if count == 1 else "items"
        self.status_label.set_text(f"{count} {noun} in {self.current_uri.display()}")
        self._update_selection_action()

    def _go_to_entry(self, *_):
        text = self.path_entry.get_text().strip()
        if not text:
            return
        try:
            uri = self._uri_from_path_entry(text)
        except ValueError as exc:
            self.status_label.set_text(f"Invalid path: {exc}")
            return
        self._load_directory(uri)

    def _uri_from_path_entry(self, text: str) -> FileUri:
        if text.startswith("sftp://") or text.startswith("ssh "):
            return parse_remote_target(text)
        if (
                not text.startswith(("/", "~", "."))
                and (":" in text or "@" in text or " " in text)):
            return parse_remote_target(text)
        if text in {".", ".."} or text.startswith(("./", "../")):
            path = posixpath.normpath(posixpath.join(self.current_uri.path, text))
            if not path.startswith("/"):
                path = "/" + path
            return FileUri("sftp", path, self.current_uri.authority)
        if not text.startswith(("/", "~")):
            return FileUri(
                "sftp",
                posixpath.join(self.current_uri.path, text),
                self.current_uri.authority,
            )
        return parse_remote_target(
            f"{self.current_uri.authority} {shlex.quote(text)}"
        )

    def _on_key_press(self, _widget, event):
        if event.keyval == Gdk.KEY_Escape:
            self.response(Gtk.ResponseType.CANCEL)
            return True
        if event.keyval in (Gdk.KEY_BackSpace, Gdk.KEY_Left) and (
                event.state & Gdk.ModifierType.MOD1_MASK):
            self._go_up()
            return True
        return False


# --- document sidebar --------------------------------------------------------

class DocumentSidebar(Gtk.Box):
    def __init__(
            self,
            on_jump,
            on_open_history,
            on_open_markdown,
            on_open_folder,
            on_choose_markdown_file,
            on_choose_markdown_folder,
            on_rescan_markdown_folder,
            on_toggle_hidden_files,
            on_remote_connect):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.set_size_request(SIDEBAR_MIN_WIDTH, -1)
        self.set_hexpand(True)
        self.on_jump = on_jump
        self.on_open_history = on_open_history
        self.on_open_markdown = on_open_markdown
        self.on_open_folder = on_open_folder
        self.on_choose_markdown_file = on_choose_markdown_file
        self.on_choose_markdown_folder = on_choose_markdown_folder
        self.on_rescan_markdown_folder = on_rescan_markdown_folder
        self.on_toggle_hidden_files = on_toggle_hidden_files
        self.on_remote_connect = on_remote_connect
        self.show_hidden_files = False
        self._remote_state = "idle"
        self._remote_pulse_timer: int | None = None
        self._remote_pulse_on = False

        self.split_paned = Gtk.Paned(orientation=Gtk.Orientation.VERTICAL)
        self.split_paned.set_wide_handle(True)

        history_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.history_listbox = Gtk.ListBox()
        self.history_listbox.set_hexpand(True)
        self.history_listbox.set_activate_on_single_click(True)
        self.history_listbox.connect("row-activated", self._on_history_row)
        history_scroller = Gtk.ScrolledWindow()
        history_scroller.set_hexpand(True)
        history_scroller.set_vexpand(True)
        history_scroller.set_policy(
            Gtk.PolicyType.NEVER,
            Gtk.PolicyType.AUTOMATIC,
        )
        history_scroller.add(self.history_listbox)
        history_box.pack_start(self._section_label("Recent documents"), False, False, 0)
        history_box.pack_start(history_scroller, True, True, 0)

        folder_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        folder_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        folder_header.set_margin_top(8)
        folder_header.set_margin_bottom(4)
        folder_header.set_margin_start(10)
        folder_header.set_margin_end(8)
        folder_label = _shrink_label("Folder tree")
        folder_label.get_style_context().add_class("dim-label")
        folder_header.pack_start(folder_label, True, True, 0)
        self.choose_file_btn = _icon_button(
            "text-x-generic-symbolic",
            "Choose a markdown file and show its folder",
            self.on_choose_markdown_file,
        )
        self.choose_folder_btn = _icon_button(
            "folder-open-symbolic",
            "Choose markdown folder",
            self.on_choose_markdown_folder,
        )
        rescan_btn = _icon_button(
            "view-refresh-symbolic",
            "Rescan selected folder",
            self.on_rescan_markdown_folder,
        )
        self.show_hidden_btn = Gtk.ToggleButton.new_with_label(".*")
        self.show_hidden_btn.set_relief(Gtk.ReliefStyle.NONE)
        self.show_hidden_btn.set_tooltip_text("Show hidden dotfiles")
        self.show_hidden_btn.get_style_context().add_class("flat")
        self.show_hidden_btn.connect("toggled", self._on_show_hidden_toggled)
        folder_header.pack_start(self.choose_file_btn, False, False, 0)
        folder_header.pack_start(self.choose_folder_btn, False, False, 0)
        folder_header.pack_start(rescan_btn, False, False, 0)
        folder_header.pack_start(self.show_hidden_btn, False, False, 0)

        self.markdown_folder_label = _shrink_label(
            "No folder selected",
            ellipsize=Pango.EllipsizeMode.MIDDLE,
        )
        self.markdown_folder_label.get_style_context().add_class("dim-label")
        self.markdown_folder_label.set_margin_start(10)
        self.markdown_folder_label.set_margin_end(10)

        self.markdown_status_label = _shrink_label("")
        self.markdown_status_label.get_style_context().add_class("dim-label")
        self.markdown_status_label.set_margin_start(10)
        self.markdown_status_label.set_margin_end(10)
        self.markdown_status_label.set_margin_bottom(6)

        self.folder_listbox = Gtk.ListBox()
        self.folder_listbox.set_hexpand(True)
        self.folder_listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self.folder_listbox.set_activate_on_single_click(True)
        self.folder_listbox.connect("row-activated", self._on_folder_tree_row)

        self.folder_scroller = Gtk.ScrolledWindow()
        self.folder_scroller.set_hexpand(True)
        self.folder_scroller.set_vexpand(True)
        self.folder_scroller.set_policy(
            Gtk.PolicyType.NEVER,
            Gtk.PolicyType.AUTOMATIC,
        )
        self.folder_scroller.add(self.folder_listbox)

        folder_box.pack_start(folder_header, False, False, 0)
        folder_box.pack_start(self.markdown_folder_label, False, False, 0)
        folder_box.pack_start(self.markdown_status_label, False, False, 0)
        folder_box.pack_start(self.folder_scroller, True, True, 0)

        self.split_paned.pack1(history_box, resize=True, shrink=False)
        self.split_paned.pack2(folder_box, resize=True, shrink=False)
        self.split_paned.set_position(220)
        self.pack_start(self.split_paned, True, True, 0)

        self.remote_button = Gtk.Button()
        self.remote_button.set_relief(Gtk.ReliefStyle.NONE)
        self.remote_button.connect("clicked", self.on_remote_connect)
        remote_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        remote_box.set_margin_top(6)
        remote_box.set_margin_bottom(6)
        remote_box.set_margin_start(8)
        remote_box.set_margin_end(8)
        self.remote_dot = Gtk.Label()
        self.remote_label = _shrink_label("SSH")
        self.remote_detail = _shrink_label(
            "Connect",
            ellipsize=Pango.EllipsizeMode.MIDDLE,
        )
        self.remote_detail.get_style_context().add_class("dim-label")
        remote_text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        remote_text.set_hexpand(True)
        remote_text.pack_start(self.remote_label, False, False, 0)
        remote_text.pack_start(self.remote_detail, False, False, 0)
        remote_box.pack_start(self.remote_dot, False, False, 0)
        remote_box.pack_start(remote_text, True, True, 0)
        self.remote_button.add(remote_box)
        self.pack_start(self.remote_button, False, False, 0)

        self.update_history([])
        self.set_file_browser_results(None, [], "Choose a folder to browse.")
        self.set_remote_status("idle", "SSH", "Connect")

    def _folder_tree_row(
            self,
            name: str,
            *,
            depth: int = 0,
            file_path: Path | None = None,
            file_uri: FileUri | None = None,
            tooltip: str | None = None,
            folder: bool = False):
        row = Gtk.ListBoxRow()
        row.file_path = file_path
        row.file_uri = file_uri
        row.is_dir = folder
        row.set_tooltip_text(tooltip or name)
        row.set_hexpand(True)
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        box.set_hexpand(True)
        box.set_halign(Gtk.Align.FILL)
        box.set_margin_top(3)
        box.set_margin_bottom(3)
        box.set_margin_start(8)
        box.set_margin_end(8)
        indent = Gtk.Box()
        indent.set_size_request(
            min(depth * SIDEBAR_INDENT_STEP, SIDEBAR_INDENT_MAX),
            1,
        )
        box.pack_start(indent, False, False, 0)
        icon = Gtk.Image.new_from_icon_name(
            "folder-symbolic" if folder else "text-x-generic-symbolic",
            Gtk.IconSize.MENU,
        )
        box.pack_start(icon, False, False, 0)
        label = _shrink_label(name)
        box.pack_start(label, True, True, 0)
        row.add(box)
        return row

    def _section_label(self, text):
        label = Gtk.Label(label=text, xalign=0)
        label.set_margin_top(4)
        label.set_margin_bottom(4)
        label.set_margin_start(10)
        label.set_margin_end(10)
        label.get_style_context().add_class("dim-label")
        return label

    def update(self, headings):
        # Kept for existing call sites; heading jumps remain in the palette.
        return

    def set_remote_status(self, state: str, label: str, detail: str = ""):
        self._remote_state = state
        colors = {
            "idle": "#8b949e",
            "connecting": "#2f81f7",
            "connected": "#2da44e",
            "failed": "#cf222e",
        }
        color = colors.get(state, colors["idle"])
        self.remote_dot.set_markup(f'<span foreground="{color}">●</span>')
        self.remote_label.set_text(label)
        self.remote_detail.set_text(detail)
        self.remote_button.set_tooltip_text(
            f"{label} {detail}".strip() or "Connect SSH/SFTP"
        )
        if state == "connecting":
            self._start_remote_pulse()
        elif self._remote_pulse_timer is not None:
            GLib.source_remove(self._remote_pulse_timer)
            self._remote_pulse_timer = None

    def _start_remote_pulse(self):
        if self._remote_pulse_timer is not None:
            return
        self._remote_pulse_timer = GLib.timeout_add(650, self._pulse_remote_dot)

    def _pulse_remote_dot(self):
        if self._remote_state != "connecting":
            self._remote_pulse_timer = None
            return False
        self._remote_pulse_on = not self._remote_pulse_on
        dot = "●" if self._remote_pulse_on else "◌"
        self.remote_dot.set_markup(f'<span foreground="#2f81f7">{dot}</span>')
        return True

    def update_history(self, recents: list[RecentDocument]):
        for c in self.history_listbox.get_children():
            self.history_listbox.remove(c)
        if not recents:
            row = Gtk.ListBoxRow()
            row.file_path = None
            row.recent = None
            lbl = _shrink_label("No recent files yet")
            lbl.set_margin_top(8)
            lbl.set_margin_bottom(8)
            lbl.set_margin_start(10)
            lbl.set_margin_end(10)
            lbl.get_style_context().add_class("dim-label")
            row.add(lbl)
            self.history_listbox.add(row)
            self.history_listbox.show_all()
            return
        for recent in recents:
            row = Gtk.ListBoxRow()
            row.recent = recent
            row.file_path = recent.local_path
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            box.set_hexpand(True)
            box.set_halign(Gtk.Align.FILL)
            box.set_margin_top(6)
            box.set_margin_bottom(6)
            box.set_margin_start(8)
            box.set_margin_end(8)
            name = _shrink_label(recent.title)
            sub = _shrink_label(
                recent.subtitle,
                ellipsize=Pango.EllipsizeMode.MIDDLE,
            )
            sub.get_style_context().add_class("dim-label")
            box.pack_start(name, False, False, 0)
            box.pack_start(sub, False, False, 0)
            row.add(box)
            self.history_listbox.add(row)
        self.history_listbox.show_all()

    def set_file_browser_results(
            self,
            root: FileUri | Path | None,
            entries: list[FileInfo],
            status: str):
        for c in self.folder_listbox.get_children():
            self.folder_listbox.remove(c)
        root_uri = self._coerce_uri(root) if root is not None else None
        self.set_remote_tree_mode(root_uri.is_remote if root_uri else False)
        self.markdown_folder_label.set_text(
            root_uri.display() if root_uri else "No folder selected"
        )
        self.markdown_status_label.set_text(status)
        if root_uri is None:
            self.folder_listbox.add(
                self._folder_tree_row("No folder selected", tooltip="No folder selected")
            )
            self.folder_listbox.show_all()
            return
        if root_uri.parent != root_uri:
            self.folder_listbox.add(
                self._folder_tree_row(
                    "..",
                    file_path=root_uri.parent.to_path()
                    if root_uri.parent.is_local else None,
                    file_uri=root_uri.parent,
                    tooltip=root_uri.parent.display(),
                    folder=True,
                )
            )
        visible_entries = [
            info for info in entries
            if self.show_hidden_files or not info.name.startswith(".")
        ]
        if not visible_entries:
            hidden_count = len(entries) - len(visible_entries)
            message = (
                "Only hidden files are in this folder"
                if hidden_count
                else "No files in folder"
            )
            self.folder_listbox.add(
                self._folder_tree_row(message, tooltip=message)
            )
            self.folder_listbox.show_all()
            return
        for info in visible_entries:
            file_uri = info.uri
            self.folder_listbox.add(
                self._folder_tree_row(
                    info.name,
                    file_path=file_uri.to_path() if file_uri.is_local else None,
                    file_uri=file_uri,
                    tooltip=file_uri.display(),
                    folder=info.is_dir,
                )
            )
        self.folder_listbox.show_all()

    def set_markdown_results(
            self,
            root: FileUri | Path | None,
            entries: list[FileInfo],
            _truncated: bool,
            status: str):
        self.set_file_browser_results(root, entries, status)

    def set_remote_tree_mode(self, is_remote: bool):
        if is_remote:
            self.choose_file_btn.set_tooltip_text(
                "Browse remote server and choose a file"
            )
            self.choose_folder_btn.set_tooltip_text(
                "Browse remote server and choose a folder"
            )
            return
        self.choose_file_btn.set_tooltip_text(
            "Choose a file and show its folder"
        )
        self.choose_folder_btn.set_tooltip_text("Choose folder")

    def _on_show_hidden_toggled(self, button):
        self.show_hidden_files = button.get_active()
        self.on_toggle_hidden_files(self.show_hidden_files)

    def _coerce_uri(self, value: FileUri | Path) -> FileUri:
        if isinstance(value, FileUri):
            return value
        return FileUri.from_path(value)

    def _relative_parts(self, root_uri: FileUri, file_uri: FileUri) -> tuple[str, ...]:
        if root_uri.scheme == file_uri.scheme and root_uri.authority == file_uri.authority:
            root_path = root_uri.path.rstrip("/") + "/"
            if file_uri.path.startswith(root_path):
                rel = file_uri.path[len(root_path):]
                parts = tuple(part for part in rel.split("/") if part)
                if parts:
                    return parts
        return (file_uri.name,)

    def _on_history_row(self, _lb, row):
        recent = getattr(row, "recent", None)
        if recent is not None:
            self.on_open_history(recent)

    def _on_folder_tree_row(self, _lb, row):
        file_uri = getattr(row, "file_uri", None)
        if file_uri and getattr(row, "is_dir", False):
            self.on_open_folder(file_uri)
            return
        if file_uri:
            self.on_open_markdown(file_uri)
            return
        file_path = getattr(row, "file_path", None)
        if file_path:
            self.on_open_markdown(Path(file_path))


# --- main window -------------------------------------------------------------

class Viewer(Gtk.ApplicationWindow):
    def __init__(self, app, path: Path | None):
        super().__init__(application=app, title=APP_NAME)
        self.set_default_size(1140, 800)

        self.current_path: Path | None = None
        self.current_uri: FileUri | None = None
        self.is_untitled: bool = False
        self.monitor: Gio.FileMonitor | None = None
        self.theme = self._detect_theme()
        self.mode: str = "preview"
        self.edit_view: str = "editor"
        self._suppress_reload_until = 0.0
        self._live_timer: int | None = None
        self._scroll_sync_timer: int | None = None
        self._wordcount_timer: int | None = None
        self._headings_cache: list[dict] = []
        self.outline_visible = False
        self._sidebar_width = 300
        self.typewriter_on = False
        self._history: list[tuple[FileUri, int]] = []
        self._history_idx: int = -1
        self._in_history_nav = False
        self.markdown_root: Path | None = None
        self.markdown_root_uri: FileUri | None = None
        self.markdown_files: list[FileUri] = []
        self.folder_entries: list[FileInfo] = []
        self.markdown_scan_truncated: bool = False
        self.show_hidden_files = False
        self._folder_scan_generation = 0

        self._build_header()
        self._build_editor_widgets()
        self._build_edit_toolbar()
        self._build_find_bar()
        self._build_outline()
        self._build_layout()
        self._setup_shortcuts()
        self._setup_dnd()
        self._refresh_history_sidebar()
        self._restore_markdown_sidebar_state()

        if path is not None:
            self.load_file(path)
        else:
            self._render_welcome()
        self._refresh_content()
        GLib.idle_add(self._maybe_show_whats_new_on_upgrade)

    # ---- theme --------------------------------------------------------------

    def _detect_theme(self):
        s = Gtk.Settings.get_default()
        if s is not None:
            if s.get_property("gtk-application-prefer-dark-theme"):
                return "dark"
            if "dark" in (s.get_property("gtk-theme-name") or "").lower():
                return "dark"
        return "light"

    def _theme_icon(self):
        return "weather-clear-night-symbolic" if self.theme == "light" else "weather-clear-symbolic"

    def _toggle_theme(self, *_):
        self.theme = "dark" if self.theme == "light" else "light"
        self.theme_btn.set_image(
            Gtk.Image.new_from_icon_name(
                self._theme_icon(),
                Gtk.IconSize.BUTTON))
        self._apply_source_style()
        self._refresh_preview()

    def _sidebar_icon(self):
        return "sidebar-hide-symbolic" if self.outline_visible else "sidebar-show-symbolic"

    def _sync_sidebar_button(self):
        if hasattr(self, "sidebar_btn"):
            self.sidebar_btn.set_image(
                Gtk.Image.new_from_icon_name(
                    self._sidebar_icon(),
                    Gtk.IconSize.BUTTON,
                )
            )
            self.sidebar_btn.set_tooltip_text(
                "Hide sidebar (Ctrl+Shift+O)"
                if self.outline_visible else
                "Show sidebar (Ctrl+Shift+O)"
            )

    # ---- header -------------------------------------------------------------

    def _build_header(self):
        header = Gtk.HeaderBar()
        header.set_show_close_button(True)
        header.props.title = APP_NAME
        self.header = header
        self.set_titlebar(header)
        header.pack_start(
            _icon_button(
                "document-new-symbolic",
                "New (Ctrl+N)",
                self._on_new))
        header.pack_start(
            _icon_button(
                "document-open-symbolic",
                "Open (Ctrl+O)",
                self._on_open_clicked))
        self.sidebar_btn = _icon_button(
            self._sidebar_icon(),
            "Show sidebar (Ctrl+Shift+O)",
            lambda *_: self._toggle_outline())
        header.pack_start(self.sidebar_btn)
        self.edit_btn = _toggle_icon(
            "document-edit-symbolic",
            "Edit mode (Ctrl+E)")
        self.edit_btn.set_sensitive(False)
        self.edit_btn.connect("toggled", self._on_edit_toggled)
        header.pack_start(self.edit_btn)
        header.pack_start(
            _icon_button(
                "view-refresh-symbolic",
                "Reload (Ctrl+R)",
                lambda *_: self._reload()))
        # Right side: hamburger (rightmost) → theme to its left
        header.pack_end(self._build_menu())
        self.theme_btn = _icon_button(self._theme_icon(), "Theme (Ctrl+D)",
                                      self._toggle_theme)
        header.pack_end(self.theme_btn)

    def _build_menu(self):
        return _menu_button("open-menu-symbolic", "Menu", [
            ("Keyboard Shortcuts", self._show_shortcuts),
            (f"What’s New in {__version__}", self._show_whats_new),
            None,
            ("Documentation", lambda: self._open_url(WIKI_URL)),
            ("Report an Issue", lambda: self._open_url(ISSUES_URL)),
            (f"Visit {DEVELOPER}", lambda: self._open_url(WEBSITE)),
            None,
            (f"About {APP_NAME}", self._show_about),
        ])

    # ---- editor widgets -----------------------------------------------------

    def _build_editor_widgets(self):
        ucm = WebKit2.UserContentManager()
        ucm.register_script_message_handler("vertexwrite")
        ucm.connect(
            "script-message-received::vertexwrite",
            self._on_script_message)
        self._ucm = ucm
        self.webview = WebKit2.WebView.new_with_user_content_manager(ucm)
        ws = self.webview.get_settings()
        ws.set_property("enable-developer-extras", False)
        ws.set_property("enable-javascript", True)
        ws.set_property("enable-smooth-scrolling", True)
        self.preview_scroller = Gtk.ScrolledWindow()
        self.preview_scroller.add(self.webview)

        lang_mgr = GtkSource.LanguageManager.get_default()
        md_lang = lang_mgr.get_language("markdown")
        self.editor_buffer = GtkSource.Buffer(language=md_lang)
        self.editor_buffer.set_highlight_syntax(True)
        self.editor_buffer.set_highlight_matching_brackets(False)
        self.editor_buffer.set_max_undo_levels(500)
        self.editor_buffer.connect("changed", self._on_buffer_changed)
        self.editor_buffer.connect(
            "modified-changed",
            self._on_modified_changed)
        self.editor_buffer.connect(
            "notify::cursor-position",
            self._on_cursor_position)

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
        self.editor.get_style_context().add_provider(
            provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def _apply_source_style(self):
        mgr = GtkSource.StyleSchemeManager.get_default()
        s = mgr.get_scheme("oblivion" if self.theme ==
                           "dark" else "solarized-light") or mgr.get_scheme("classic")
        if s is not None:
            self.editor_buffer.set_style_scheme(s)

    # ---- edit toolbar -------------------------------------------------------

    def _build_edit_toolbar(self):
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        bar.set_margin_start(8)
        bar.set_margin_end(8)
        bar.set_margin_top(4)
        bar.set_margin_bottom(4)

        def add(b): bar.pack_start(b, False, False, 0)

        # File: New, Save (Save As + clipboard live in the palette /
        # Ctrl-shortcuts)
        add(_icon_button("document-new-symbolic", "New (Ctrl+N)", self._on_new))
        add(_icon_button("document-save-symbolic",
                         "Save (Ctrl+S) · Save As: Ctrl+Shift+S",
                         lambda *_: self._save()))
        add(_separator())

        # History
        add(_icon_button("edit-undo-symbolic", "Undo (Ctrl+Z)",
                         lambda *_: self._do_undo()))
        add(_icon_button("edit-redo-symbolic", "Redo (Ctrl+Shift+Z)",
                         lambda *_: self._do_redo()))
        add(_separator())

        # Inline formatting (most-used)
        add(_icon_button("format-text-bold-symbolic", "Bold (Ctrl+B)",
                         lambda *_: self._wrap_selection("**", "**", "bold text")))
        add(_icon_button("format-text-italic-symbolic", "Italic (Ctrl+I)",
                         lambda *_: self._wrap_selection("*", "*", "italic text")))
        add(_icon_button("utilities-terminal-symbolic", "Inline code",
                         lambda *_: self._wrap_selection("`", "`", "code")))
        add(_icon_button("insert-link-symbolic", "Link (Ctrl+K)",
                         lambda *_: self._insert_link()))
        add(_separator())

        # Block-level grouped into popovers
        add(_menu_button("format-text-underline-symbolic",
                         "Headings, quote, rule",
                         [
                             ("Heading 1", lambda: self._set_heading_level(1)),
                             ("Heading 2", lambda: self._set_heading_level(2)),
                             ("Heading 3", lambda: self._set_heading_level(3)),
                             ("Heading 4", lambda: self._set_heading_level(4)),
                             ("Clear heading", lambda: self._set_heading_level(0)),
                             None,
                             ("Quote", lambda: self._prefix_line("> ", toggle=True)),
                             ("Horizontal rule", lambda: self._insert_text("\n---\n")),
                         ]))
        add(_menu_button("view-list-symbolic",
                         "Lists",
                         [("Bulleted list",
                           lambda: self._prefix_line("- ",
                                                     toggle=True)),
                          ("Numbered list",
                           lambda: self._prefix_line("1. ",
                                                     toggle=True)),
                             ("Checklist item",
                              lambda: self._prefix_line("- [ ] ",
                                                        toggle=True)),
                          ]))
        add(_menu_button("insert-object-symbolic",
                         "Insert",
                         [("Image…",
                           lambda: self._insert_image()),
                          ("Table…",
                           lambda: self._insert_table_prompt()),
                             None,
                             ("Strikethrough",
                              lambda: self._wrap_selection("~~",
                                                           "~~",
                                                           "strikethrough")),
                          ]))

        # Spacer
        bar.pack_start(Gtk.Box(), True, True, 0)

        # Word count + reading time
        self.wc_label = Gtk.Label(label="")
        self.wc_label.get_style_context().add_class("dim-label")
        self.wc_label.set_margin_end(6)
        bar.pack_start(self.wc_label, False, False, 0)

        # View segmented (Editor / Split / Preview)
        view_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        view_box.get_style_context().add_class("linked")
        self.view_editor_btn = _toggle_icon(
            "accessories-text-editor-symbolic", "Editor only")
        self.view_split_btn = _toggle_icon(
            "view-dual-symbolic", "Split view (live preview)")
        self.view_preview_btn = _toggle_icon(
            "view-reveal-symbolic", "Preview only")
        self.view_editor_btn.set_active(True)
        for b in (
            self.view_editor_btn,
            self.view_split_btn,
                self.view_preview_btn):
            view_box.pack_start(b, False, False, 0)
        self.view_editor_btn.connect(
            "toggled", lambda b: self._set_edit_view(
                "editor", b))
        self.view_split_btn.connect(
            "toggled", lambda b: self._set_edit_view(
                "split", b))
        self.view_preview_btn.connect(
            "toggled", lambda b: self._set_edit_view(
                "preview", b))
        bar.pack_start(view_box, False, False, 0)

        bar.pack_start(_separator(), False, False, 0)

        # Find toggle — synced with the search bar so the icon really toggles
        self.find_btn = _toggle_icon("edit-find-symbolic", "Find (Ctrl+F)")
        self.find_btn.connect("toggled", self._on_find_toggled)
        bar.pack_start(self.find_btn, False, False, 0)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        outer.pack_start(bar, False, False, 0)
        outer.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL),
                         False, False, 0)
        self.edit_toolbar_revealer = Gtk.Revealer()
        self.edit_toolbar_revealer.set_transition_type(
            Gtk.RevealerTransitionType.SLIDE_DOWN)
        self.edit_toolbar_revealer.set_transition_duration(160)
        self.edit_toolbar_revealer.add(outer)

    # ---- find bar -----------------------------------------------------------

    def _build_find_bar(self):
        self.find_entry = Gtk.SearchEntry()
        self.find_entry.set_width_chars(48)
        self.find_entry.connect("search-changed", self._on_find_changed)
        self.find_entry.connect("activate", lambda *_: self._find_step(True))
        self.find_entry.connect(
            "stop-search",
            lambda *_: self._toggle_find(False))

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

    def _toggle_find(self, on):
        if on and self.mode != "edit":
            return
        self.find_bar.set_search_mode(on)
        if hasattr(self, "find_btn"):
            self._suppress_find_toggle = True
            self.find_btn.set_active(on)
            self._suppress_find_toggle = False
        if on:
            self.find_entry.grab_focus()

    def _on_find_toggled(self, btn):
        if getattr(self, "_suppress_find_toggle", False):
            return
        self._toggle_find(btn.get_active())

    def _on_find_changed(self, entry):
        self.search_settings.set_search_text(entry.get_text() or "")

    def _find_step(self, forward):
        start = self.editor_buffer.get_iter_at_mark(
            self.editor_buffer.get_insert())
        func = self.search_context.forward2 if forward else self.search_context.backward2
        try:
            found, ms, me, _w = func(start)
        except Exception:
            found = False
        if found:
            self.editor_buffer.select_range(ms, me)
            self.editor.scroll_to_iter(ms, 0.1, False, 0, 0)

    # ---- document sidebar ---------------------------------------------------

    def _build_outline(self):
        self.outline = DocumentSidebar(
            on_jump=self._goto_line,
            on_open_history=self._open_history_file,
            on_open_markdown=self._open_markdown_file,
            on_open_folder=self._open_folder_tree_folder,
            on_choose_markdown_file=self._choose_markdown_file,
            on_choose_markdown_folder=self._choose_markdown_folder,
            on_rescan_markdown_folder=self._scan_markdown_folder,
            on_toggle_hidden_files=self._toggle_folder_hidden_files,
            on_remote_connect=self._open_remote_dialog,
        )
        self.outline_revealer = Gtk.Revealer()
        self.outline_revealer.set_no_show_all(True)
        self.outline_revealer.set_transition_type(
            Gtk.RevealerTransitionType.CROSSFADE)
        self.outline_revealer.set_transition_duration(140)
        self.outline_revealer.add(self.outline)
        self.outline_revealer.hide()

    def _toggle_outline(self, *_):
        self._set_sidebar_visible(not self.outline_visible)

    def _set_sidebar_visible(self, visible: bool):
        self.outline_visible = visible
        if visible:
            self.outline.show_all()
            self.outline_revealer.show()
        self.outline_revealer.set_reveal_child(visible)
        self._sync_sidebar_button()
        if visible:
            self._refresh_history_sidebar()
            if self.current_uri:
                self._ensure_sidebar_folder_for_uri(self.current_uri)
            self.outline.update(self._headings_cache)
            GLib.idle_add(self._restore_sidebar_paned_position)
        elif hasattr(self, "middle_paned"):
            pos = self.middle_paned.get_position()
            if pos > 80:
                self._sidebar_width = pos
            self.outline_revealer.hide()
            self.middle_paned.set_position(0)

    def _restore_sidebar_paned_position(self):
        if hasattr(self, "middle_paned"):
            width = getattr(self, "_sidebar_width", 300)
            self.middle_paned.set_position(max(SIDEBAR_MIN_WIDTH, width))
        return False

    def _on_sidebar_paned_position_changed(self, paned, _pspec):
        if self.outline_visible and paned.get_position() >= SIDEBAR_MIN_WIDTH:
            self._sidebar_width = paned.get_position()

    def _run_storage_task(self, worker, on_done):
        def _runner():
            try:
                result = worker()
                error = None
            except Exception as exc:
                result = None
                error = exc
            GLib.idle_add(on_done, result, error)

        threading.Thread(target=_runner, daemon=True).start()

    def _open_remote_dialog(self, *_):
        dialog = Gtk.Dialog(title="Connect SSH/SFTP", parent=self, flags=0)
        dialog.add_buttons(
            "Cancel",
            Gtk.ResponseType.CANCEL,
            "Connect",
            Gtk.ResponseType.OK,
        )
        dialog.set_default_size(560, 330)
        dialog.set_default_response(Gtk.ResponseType.OK)
        box = dialog.get_content_area()
        box.set_spacing(8)
        box.set_margin_top(10)
        box.set_margin_bottom(10)
        box.set_margin_start(12)
        box.set_margin_end(12)

        label = Gtk.Label(
            label=(
                "Quick connect: enter an SSH host alias or SFTP URI. Examples: "
                "ssh example-host, ssh example-host ~/docs, sftp://user@host:22/path. "
                "Authentication uses SSH agent/keys and known_hosts."
            ),
            xalign=0,
        )
        label.set_line_wrap(True)
        box.pack_start(label, False, False, 0)

        entry = Gtk.Entry()
        entry.set_placeholder_text("ssh example-host")
        entry.set_activates_default(True)
        if self.markdown_root_uri and self.markdown_root_uri.is_remote:
            entry.set_text(str(self.markdown_root_uri))
        box.pack_start(entry, False, False, 0)

        separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        separator.set_margin_top(6)
        separator.set_margin_bottom(4)
        box.pack_start(separator, False, False, 0)

        manual_label = Gtk.Label(
            label=(
                "Manual connection. Fill Host/IP to use these fields instead "
                "of the quick field above."
            ),
            xalign=0,
        )
        manual_label.set_line_wrap(True)
        box.pack_start(manual_label, False, False, 0)

        grid = Gtk.Grid(row_spacing=8, column_spacing=10)
        grid.set_column_homogeneous(False)
        host_entry = Gtk.Entry()
        host_entry.set_placeholder_text("example-host or 192.0.2.10")
        user_entry = Gtk.Entry()
        user_entry.set_placeholder_text("optional username")
        port_entry = Gtk.Entry()
        port_entry.set_placeholder_text("22")
        path_entry = Gtk.Entry()
        path_entry.set_placeholder_text("/home/user/docs or ~/docs")
        if self.markdown_root_uri and self.markdown_root_uri.is_remote:
            path_entry.set_placeholder_text(self.markdown_root_uri.path)
        for widget in (host_entry, user_entry, port_entry, path_entry):
            widget.set_hexpand(True)
            widget.set_activates_default(True)
        port_entry.set_width_chars(6)

        grid.attach(Gtk.Label(label="Host/IP", xalign=0), 0, 0, 1, 1)
        grid.attach(host_entry, 1, 0, 3, 1)
        grid.attach(Gtk.Label(label="User", xalign=0), 0, 1, 1, 1)
        grid.attach(user_entry, 1, 1, 1, 1)
        grid.attach(Gtk.Label(label="Port", xalign=0), 2, 1, 1, 1)
        grid.attach(port_entry, 3, 1, 1, 1)
        grid.attach(Gtk.Label(label="Path", xalign=0), 0, 2, 1, 1)
        grid.attach(path_entry, 1, 2, 3, 1)
        box.pack_start(grid, False, False, 0)

        dialog.show_all()
        response = dialog.run()
        value = entry.get_text().strip()
        manual_host = host_entry.get_text().strip()
        manual_user = user_entry.get_text().strip()
        manual_port = port_entry.get_text().strip()
        manual_path = path_entry.get_text().strip()
        dialog.destroy()
        if response != Gtk.ResponseType.OK:
            return
        try:
            if manual_host:
                value = self._manual_remote_target(
                    manual_host,
                    manual_user,
                    manual_port,
                    manual_path,
                )
            if not value:
                return
            uri = parse_remote_target(value)
        except ValueError as exc:
            self.outline.set_remote_status("failed", "Remote failed", str(exc))
            self._render_error(f"Invalid SFTP URI:\n{exc}")
            return

        self._set_remote_markdown_root(uri)

    def _manual_remote_target(
            self,
            host: str,
            username: str,
            port: str,
            path: str) -> str:
        host = host.strip()
        username = username.strip()
        port = port.strip()
        path = path.strip()
        if not host:
            raise ValueError("Manual connection requires a Host/IP value")
        if username and "@" in host:
            raise ValueError("Use either user@host or the User field, not both")
        if port:
            if not port.isdigit():
                raise ValueError("Port must be a number")
            number = int(port)
            if number < 1 or number > 65535:
                raise ValueError("Port must be between 1 and 65535")
        if ":" in host and not host.startswith("[") and host.count(":") > 1:
            host = f"[{host}]"
        authority = f"{username}@{host}" if username else host
        if port:
            authority = f"{authority}:{port}"
        if path:
            return f"{authority} {shlex.quote(path)}"
        return authority

    def _set_remote_markdown_root(self, uri: FileUri):
        if uri.name.lower().endswith(tuple(MARKDOWN_EXTENSIONS)):
            uri = uri.parent
        self.markdown_root_uri = uri
        self.markdown_root = None
        save_markdown_root_uri(uri)
        self.outline.set_remote_status("connecting", "Connecting", uri.authority)
        self._scan_markdown_folder()

    def _ensure_sidebar_folder_for_file(
            self,
            path: Path,
            force_rescan: bool = False):
        try:
            file_path = path.resolve()
        except OSError:
            file_path = path
        folder = file_path.parent
        root = None
        if self.markdown_root and self.markdown_root.is_dir():
            try:
                root = self.markdown_root.resolve()
            except OSError:
                root = None

        needs_update = root is None
        if root is not None:
            try:
                file_path.relative_to(root)
            except ValueError:
                needs_update = True

        if needs_update:
            self.markdown_root = folder
            self.markdown_root_uri = FileUri.from_path(folder)
            save_markdown_root(folder)
            self._scan_markdown_folder()
        elif force_rescan:
            self._scan_markdown_folder()

    def _ensure_sidebar_folder_for_uri(
            self,
            uri: FileUri,
            force_rescan: bool = False):
        if uri.is_local:
            self._ensure_sidebar_folder_for_file(uri.to_path(), force_rescan)
            return
        folder_uri = uri.parent
        root = self.markdown_root_uri
        needs_update = (
            root is None
            or root.scheme != folder_uri.scheme
            or root.authority != folder_uri.authority
            or not (uri.path + "/").startswith(root.path.rstrip("/") + "/")
        )
        if needs_update:
            self.markdown_root = None
            self.markdown_root_uri = folder_uri
            save_markdown_root_uri(folder_uri)
            self._scan_markdown_folder()
        elif force_rescan:
            self._scan_markdown_folder()

    def _refresh_history_sidebar(self):
        recents = []
        for recent in load_recents():
            if recent.local_path is not None and not recent.local_path.exists():
                continue
            recents.append(recent)
        self.outline.update_history(recents[:RECENT_MAX])

    def _open_history_file(self, recent: RecentDocument | Path):
        recent = _coerce_recent(recent)
        if recent is None:
            return
        if recent.uri.is_local and not recent.uri.to_path().exists():
            self._render_error(f"Could not read {recent.subtitle}: file not found")
            self._refresh_history_sidebar()
            return
        if not self._confirm_discard_if_dirty():
            return
        self.load_document_uri(recent.uri, update_sidebar_folder=False)

    def _open_markdown_file(self, target: FileUri | Path):
        try:
            uri = target if isinstance(target, FileUri) else FileUri.from_path(target)
        except (OSError, ValueError) as exc:
            self._render_error(f"Could not read {target}: {exc}")
            return
        if uri.is_local:
            path = uri.to_path()
            if not path.exists():
                self._render_error(f"Could not read {path}: file not found")
                return
        if not self._confirm_discard_if_dirty():
            return
        self.load_document_uri(uri)

    def _restore_markdown_sidebar_state(self):
        root_uri = load_markdown_root_uri()
        if root_uri is None:
            self.outline.set_file_browser_results(
                None,
                [],
                "Choose a folder to browse.",
            )
            return
        self.markdown_root_uri = root_uri
        self.markdown_root = root_uri.to_path() if root_uri.is_local else None
        self._scan_markdown_folder()

    def _open_folder_tree_folder(self, target: FileUri | Path):
        try:
            uri = target if isinstance(target, FileUri) else FileUri.from_path(target)
        except (OSError, ValueError) as exc:
            self._render_error(f"Could not open folder {target}: {exc}")
            return
        self.markdown_root_uri = uri
        self.markdown_root = uri.to_path() if uri.is_local else None
        save_markdown_root_uri(uri)
        self._scan_markdown_folder()

    def _toggle_folder_hidden_files(self, show_hidden: bool):
        self.show_hidden_files = show_hidden
        root = self.markdown_root_uri
        if root is None:
            self.outline.set_file_browser_results(
                None,
                [],
                "Choose a folder to browse.",
            )
            return
        status = self._folder_browser_status(self.folder_entries)
        self.outline.set_file_browser_results(root, self.folder_entries, status)

    def _choose_markdown_file(self, *_):
        if self.markdown_root_uri and self.markdown_root_uri.is_remote:
            self._open_remote_browser_dialog("file")
            return
        d = Gtk.FileChooserDialog(
            title="Choose file",
            parent=self,
            action=Gtk.FileChooserAction.OPEN,
        )
        d.add_buttons(
            "Cancel",
            Gtk.ResponseType.CANCEL,
            "Select",
            Gtk.ResponseType.OK,
        )
        af = Gtk.FileFilter()
        af.set_name("All files")
        af.add_pattern("*")
        d.add_filter(af)
        if self.markdown_root and self.markdown_root.is_dir():
            d.set_current_folder(str(self.markdown_root))
        elif self.current_path:
            d.set_current_folder(str(self.current_path.parent))
        r = d.run()
        chosen = d.get_filename() if r == Gtk.ResponseType.OK else None
        d.destroy()
        if not chosen:
            return
        selected = Path(chosen).resolve()
        self.markdown_root = selected if selected.is_dir() else selected.parent
        self.markdown_root_uri = FileUri.from_path(self.markdown_root)
        save_markdown_root_uri(self.markdown_root_uri)
        self._scan_markdown_folder()

    def _choose_markdown_folder(self, *_):
        if self.markdown_root_uri and self.markdown_root_uri.is_remote:
            self._open_remote_browser_dialog("folder")
            return
        d = Gtk.FileChooserDialog(
            title="Choose markdown folder",
            parent=self,
            action=Gtk.FileChooserAction.SELECT_FOLDER,
        )
        d.add_buttons(
            "Cancel",
            Gtk.ResponseType.CANCEL,
            "Select",
            Gtk.ResponseType.OK,
        )
        if self.markdown_root and self.markdown_root.is_dir():
            d.set_current_folder(str(self.markdown_root))
        elif self.current_path:
            d.set_current_folder(str(self.current_path.parent))
        r = d.run()
        chosen = d.get_filename() if r == Gtk.ResponseType.OK else None
        d.destroy()
        if not chosen:
            return
        self.markdown_root = Path(chosen).resolve()
        self.markdown_root_uri = FileUri.from_path(self.markdown_root)
        save_markdown_root_uri(self.markdown_root_uri)
        self._scan_markdown_folder()

    def _open_remote_browser_dialog(self, kind: str):
        root = self.markdown_root_uri
        if root is None or not root.is_remote:
            return
        dialog = RemoteFileBrowserDialog(self, root, kind)
        dialog.show_all()
        response = dialog.run()
        uri = dialog.result_uri if response == Gtk.ResponseType.OK else None
        dialog.destroy()
        if uri is None:
            return
        if kind == "file":
            uri = uri.parent
        self._set_remote_markdown_root(uri)

    def _scan_markdown_folder(self, *_):
        self.markdown_files = []
        self.folder_entries = []
        self.markdown_scan_truncated = False
        root_uri = self.markdown_root_uri
        if root_uri is None and self.markdown_root is not None:
            root_uri = FileUri.from_path(self.markdown_root)
            self.markdown_root_uri = root_uri
        if root_uri is None:
            self.outline.set_file_browser_results(
                None,
                [],
                "Choose a folder to browse.",
            )
            return
        if root_uri.is_remote:
            self._scan_remote_markdown_folder(root_uri)
            return
        self.outline.set_remote_status("idle", "SSH", "Connect")
        backend = backend_for(root_uri)
        try:
            info = backend.stat(root_uri)
            if info.is_file:
                root_uri = root_uri.parent
            if not backend.stat(root_uri).is_dir:
                raise OSError(f"{root_uri.display()} is not a folder")
            entries = backend.list_dir(root_uri)
        except OSError as exc:
            self.outline.set_file_browser_results(
                root_uri,
                [],
                f"Load failed: {exc}",
            )
            return

        self.markdown_root_uri = root_uri
        self.markdown_root = root_uri.to_path()
        save_markdown_root_uri(root_uri)
        self.folder_entries = entries
        self.outline.set_file_browser_results(
            root_uri,
            entries,
            self._folder_browser_status(entries),
        )

    def _scan_remote_markdown_folder(self, root_uri: FileUri):
        self._folder_scan_generation += 1
        generation = self._folder_scan_generation
        self.outline.set_file_browser_results(
            root_uri,
            [],
            "Loading remote folder...",
        )
        self.outline.set_remote_status(
            "connecting",
            "Loading",
            root_uri.authority,
        )

        def worker():
            backend = backend_for(root_uri)
            normalize = getattr(backend, "normalize_uri", None)
            root = normalize(root_uri) if normalize else root_uri
            root_info = backend.stat(root)
            if root_info.is_file:
                root = root.parent
            entries = backend.list_dir(root)
            return root, entries

        def done(result, error):
            if generation != self._folder_scan_generation:
                return False
            if error is not None:
                self.markdown_files = []
                self.folder_entries = []
                self.outline.set_remote_status(
                    "failed",
                    "Remote failed",
                    str(error),
                )
                self.outline.set_file_browser_results(
                    root_uri,
                    [],
                    f"Remote folder load failed: {error}",
                )
                return False
            root, entries = result
            self.markdown_root_uri = root
            self.markdown_root = None
            save_markdown_root_uri(root)
            self.folder_entries = entries
            self.outline.set_remote_status(
                "connected",
                "SSH connected",
                root.authority,
            )
            self.outline.set_file_browser_results(
                root,
                entries,
                self._folder_browser_status(entries),
            )
            return False

        self._run_storage_task(worker, done)

    def _folder_browser_status(self, entries: list[FileInfo]) -> str:
        visible = [
            info for info in entries
            if self.show_hidden_files or not info.name.startswith(".")
        ]
        hidden_count = len(entries) - len(visible)
        count = len(visible)
        noun = "item" if count == 1 else "items"
        if hidden_count and not self.show_hidden_files:
            hidden_noun = "item" if hidden_count == 1 else "items"
            return f"{count} {noun} shown ({hidden_count} hidden {hidden_noun})."
        return f"{count} {noun}."

    # ---- layout -------------------------------------------------------------

    def _build_layout(self):
        self.root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.root.pack_start(self.edit_toolbar_revealer, False, False, 0)
        self.root.pack_start(self.find_bar, False, False, 0)
        self.middle_paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        self.middle_paned.set_wide_handle(True)
        self.middle_paned.connect(
            "notify::position",
            self._on_sidebar_paned_position_changed,
        )
        self.middle_paned.pack1(self.outline_revealer, resize=False, shrink=False)
        self.content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.middle_paned.pack2(self.content_box, resize=True, shrink=False)
        self.middle_paned.set_position(0)
        self.root.pack_start(self.middle_paned, True, True, 0)
        self.add(self.root)

    def _refresh_content(self):
        for w in (self.preview_scroller, self.editor_scroller):
            p = w.get_parent()
            if p is not None:
                p.remove(w)
        for c in list(self.content_box.get_children()):
            self.content_box.remove(c)
        if self.mode == "preview":
            self.content_box.pack_start(self.preview_scroller, True, True, 0)
        else:
            if self.edit_view == "editor":
                self.content_box.pack_start(
                    self.editor_scroller, True, True, 0)
            elif self.edit_view == "preview":
                self.content_box.pack_start(
                    self.preview_scroller, True, True, 0)
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
        w = paned.get_allocated_width()
        if w > 0:
            paned.set_position(w // 2)
        return False

    # ---- shortcuts + DnD ----------------------------------------------------

    def _setup_shortcuts(self):
        accel = Gtk.AccelGroup()
        self.add_accel_group(accel)

        def bind(key, mod, handler):
            kv = Gdk.keyval_from_name(key)
            accel.connect(kv, mod, Gtk.AccelFlags.VISIBLE,
                          lambda *_: handler() or True)
        CTRL = Gdk.ModifierType.CONTROL_MASK
        SHIFT = Gdk.ModifierType.SHIFT_MASK
        ALT = Gdk.ModifierType.MOD1_MASK
        bind("o", CTRL, self._on_open_clicked)
        bind("n", CTRL, self._on_new)
        bind("s", CTRL, self._save)
        bind("s", CTRL | SHIFT, self._save_as)
        bind("r", CTRL, self._reload)
        bind("q", CTRL, self.close)
        bind("d", CTRL, self._toggle_theme)
        bind("e", CTRL, self._toggle_edit)
        bind("f", CTRL, lambda: self._toggle_find(
            not self.find_bar.get_search_mode()))
        bind("f", CTRL | SHIFT, self._open_folder_search)
        bind("p", CTRL, self._open_palette)
        bind("o", CTRL | SHIFT, self._toggle_outline)
        bind("t", CTRL | SHIFT, self._toggle_typewriter)
        bind("b", CTRL, lambda: self._wrap_selection("**", "**", "bold text"))
        bind("i", CTRL, lambda: self._wrap_selection("*", "*", "italic text"))
        bind("k", CTRL, lambda: self._insert_link())
        bind("h", CTRL, lambda: self._set_heading_level(1))
        bind("z", CTRL, lambda: self._do_undo())
        bind("z", CTRL | SHIFT, lambda: self._do_redo())
        bind("y", CTRL, lambda: self._do_redo())
        bind("Left", ALT, self._history_back)
        bind("Right", ALT, self._history_forward)

    def _setup_dnd(self):
        targets = Gtk.TargetList.new([])
        targets.add_uri_targets(0)
        self.webview.drag_dest_set(
            Gtk.DestDefaults.ALL, [], Gdk.DragAction.COPY)
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
        d = Gtk.FileChooserDialog(title="Open markdown file", parent=self,
                                  action=Gtk.FileChooserAction.OPEN)
        d.add_buttons(
            "Cancel",
            Gtk.ResponseType.CANCEL,
            "Open",
            Gtk.ResponseType.OK)
        md = Gtk.FileFilter()
        md.set_name("Markdown")
        for p in ("*.md", "*.markdown", "*.mdown", "*.mkd", "*.txt"):
            md.add_pattern(p)
        d.add_filter(md)
        af = Gtk.FileFilter()
        af.set_name("All files")
        af.add_pattern("*")
        d.add_filter(af)
        r = d.run()
        chosen = d.get_filename() if r == Gtk.ResponseType.OK else None
        d.destroy()
        if chosen:
            self.load_file(Path(chosen))

    def load_file(self, path: Path, *, update_sidebar_folder: bool = True):
        self.load_document_uri(FileUri.from_path(path), update_sidebar_folder=update_sidebar_folder)

    def load_document_uri(
            self,
            uri: FileUri,
            *,
            update_sidebar_folder: bool = True):
        if uri.is_remote:
            self.outline.set_remote_status("connecting", "Opening", uri.authority)

            def worker():
                return backend_for(uri).read_bytes(uri).decode("utf-8")

            def done(text, error):
                if error is not None:
                    self.outline.set_remote_status(
                        "failed",
                        "Remote failed",
                        str(error),
                    )
                    self._render_error(f"Could not read {uri.display()}: {error}")
                    return False
                self.outline.set_remote_status(
                    "connected",
                    "SSH connected",
                    uri.authority,
                )
                self._load_document_text(uri, text, update_sidebar_folder)
                return False

            self._run_storage_task(worker, done)
            return

        try:
            text = backend_for(uri).read_bytes(uri).decode("utf-8")
        except (OSError, UnicodeDecodeError, StorageError) as exc:
            self._render_error(f"Could not read {uri.display()}: {exc}")
            return
        self._load_document_text(uri, text, update_sidebar_folder)

    def _load_document_text(
            self,
            uri: FileUri,
            text: str,
            update_sidebar_folder: bool):
        path = uri.to_path() if uri.is_local else None
        prior_line = None
        if self.current_uri and not self._in_history_nav:
            cur = self.editor_buffer.get_iter_at_mark(
                self.editor_buffer.get_insert())
            prior_line = cur.get_line() if self.mode == "edit" else 0
            self._history_push(self.current_uri, prior_line)
        self.current_uri = uri
        self.current_path = path
        self.is_untitled = False
        self.edit_btn.set_sensitive(True)
        add_recent_uri(uri)
        self._refresh_history_sidebar()
        if self.outline_visible and update_sidebar_folder:
            self._ensure_sidebar_folder_for_uri(uri)
        base_dir = path.parent if path else None
        base_uri = path.parent.as_uri() + "/" if path else APP_DIR.as_uri() + "/"
        self.webview.load_html(
            render(
                text,
                self.theme,
                uri.name,
                base_dir),
            base_uri)
        self._load_editor_text(text)
        self._headings_cache = extract_headings(text)
        if self.outline_visible:
            self.outline.update(self._headings_cache)
        if path:
            self._watch_file(path)
        elif self.monitor is not None:
            self.monitor.cancel()
            self.monitor = None
        self._update_title()
        self._schedule_wordcount()

    def _watch_file(self, path: Path):
        if self.monitor is not None:
            self.monitor.cancel()
        try:
            self.monitor = Gio.File.new_for_path(str(path)).monitor_file(
                Gio.FileMonitorFlags.NONE, None)
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
        if self.current_uri:
            self.load_document_uri(self.current_uri)
        else:
            self._render_welcome()
        return False

    def _render_welcome(self):
        self.webview.load_html(
            welcome_html(
                self.theme),
            APP_DIR.as_uri() + "/")
        self.edit_btn.set_sensitive(False)
        self.current_path = None
        self.current_uri = None
        self.is_untitled = False
        self._headings_cache = []
        if self.outline_visible:
            self._refresh_history_sidebar()
            self.outline.update([])
        self._update_title()
        if hasattr(self, "wc_label"):
            self.wc_label.set_text("")

    def _render_error(self, msg):
        md_text = f"# Error\n\n```\n{msg}\n```\n"
        self.webview.load_html(render(md_text, self.theme, "Error", APP_DIR),
                               APP_DIR.as_uri() + "/")

    def _refresh_preview(self):
        if self.current_uri and self.mode == "preview":
            self.load_document_uri(self.current_uri)
        elif self.mode == "edit":
            self._render_live_preview()
        else:
            self._render_welcome()

    # ---- edit mode + view switching -----------------------------------------

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
            if not self.current_uri and not self.is_untitled:
                self.edit_btn.set_active(False)
                return
            self.mode = "edit"
            self._refresh_content()
            if self.edit_view != "preview":
                self.editor.grab_focus()
        else:
            if self.editor_buffer.get_modified():
                if self.is_untitled or not self.current_uri:
                    if not self._save_as():
                        self.edit_btn.set_active(True)
                        return
                else:
                    self._save()
            self.mode = "preview"
            self._refresh_content()
            if self.current_uri:
                self.load_document_uri(self.current_uri)

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
        if self.outline_visible:
            self.outline.update(self._headings_cache)
        self._update_title()
        self._schedule_wordcount()
        if self.mode == "edit" and self.edit_view in ("split", "preview"):
            self._schedule_live_preview()

    def _on_modified_changed(self, *_):
        self._update_title()

    def _schedule_live_preview(self):
        if self._live_timer is not None:
            GLib.source_remove(self._live_timer)
        self._live_timer = GLib.timeout_add(LIVE_PREVIEW_DEBOUNCE_MS,
                                            self._render_live_preview)

    def _render_live_preview(self):
        self._live_timer = None
        text = self._buffer_text()
        base = (
            self.current_path.parent
            if self.current_uri and self.current_uri.is_local and self.current_path
            else APP_DIR
        )
        title = self.current_uri.name if self.current_uri else "untitled.md"
        self.webview.load_html(render(text, self.theme, title, base),
                               base.as_uri() + "/")
        return False

    def _schedule_wordcount(self):
        if self._wordcount_timer is not None:
            GLib.source_remove(self._wordcount_timer)
        self._wordcount_timer = GLib.timeout_add(WORD_COUNT_DEBOUNCE_MS,
                                                 self._update_wordcount)

    def _update_wordcount(self):
        self._wordcount_timer = None
        words, minutes = count_words_and_read_time(self._buffer_text())
        if words == 0:
            self.wc_label.set_text("")
        else:
            self.wc_label.set_text(f"{words} words · {minutes} min read")
        return False

    def _update_title(self):
        if self.current_uri or self.is_untitled:
            name = self.current_uri.name if self.current_uri else "untitled.md"
            dirty = "  •" if self.editor_buffer.get_modified() else ""
            self.header.props.title = f"{name}{dirty}"
            self.header.props.subtitle = (
                self.current_uri.parent.display()
                if self.current_uri else "(unsaved)"
            )
        else:
            self.header.props.title = APP_NAME
            self.header.props.subtitle = None

    # ---- scroll-sync --------------------------------------------------------

    def _on_cursor_position(self, *_):
        if self.typewriter_on and self.mode == "edit":
            GLib.idle_add(self._recenter_editor)
        if self.mode == "edit" and self.edit_view == "split":
            if self._scroll_sync_timer is not None:
                GLib.source_remove(self._scroll_sync_timer)
            self._scroll_sync_timer = GLib.timeout_add(
                SCROLL_SYNC_DEBOUNCE_MS, self._do_scroll_sync)

    def _recenter_editor(self):
        mark = self.editor_buffer.get_insert()
        self.editor.scroll_to_mark(mark, 0.0, True, 0.0, 0.5)
        return False

    def _do_scroll_sync(self):
        self._scroll_sync_timer = None
        if not self._headings_cache:
            return False
        cur = self.editor_buffer.get_iter_at_mark(
            self.editor_buffer.get_insert())
        ln = cur.get_line()
        slug = None
        for h in self._headings_cache:
            if h["line"] <= ln:
                slug = h["slug"]
            else:
                break
        if slug:
            slug_json = json.dumps(slug)
            js = f"window.vertexWrite && window.vertexWrite.scrollToAnchor({slug_json});"
            try:
                self.webview.run_javascript(js, None, None, None)
            except Exception:
                pass
        return False

    # ---- webkit bridge (task toggle) ----------------------------------------

    def _on_script_message(self, _ucm, msg):
        try:
            data = json.loads(msg.get_js_value().to_string())
        except Exception:
            return
        if data.get("type") == "app_action":
            action = data.get("action")
            dispatch = {
                "new": self._on_new,
                "open": self._on_open_clicked,
                "sidebar": lambda *_: self._set_sidebar_visible(True),
                "remote": self._open_remote_from_welcome,
            }
            handler = dispatch.get(action)
            if handler is None:
                return

            def run_handler():
                handler()
                return False

            GLib.idle_add(run_handler)
            return
        if data.get("type") == "task_toggle":
            try:
                line = int(data.get("line"))
                checked = bool(data.get("checked"))
            except (TypeError, ValueError):
                return
            self._apply_task_toggle(line, checked)

    def _open_remote_from_welcome(self, *_):
        self._set_sidebar_visible(True)
        self._open_remote_dialog()

    def _apply_task_toggle(self, line, checked):
        if self.mode == "edit":
            buf = self.editor_buffer
            start = buf.get_iter_at_line(line)
            if not start:
                return
            end = start.copy()
            if not end.ends_line():
                end.forward_to_line_end()
            t = buf.get_text(start, end, True)
            nt = toggle_task_line(t, checked)
            if nt and nt != t:
                buf.begin_user_action()
                buf.delete(start, end)
                buf.insert(start, nt)
                buf.end_user_action()
        else:
            if not self.current_uri:
                return
            try:
                content = backend_for(self.current_uri).read_bytes(
                    self.current_uri).decode("utf-8")
            except (OSError, UnicodeDecodeError, StorageError):
                return
            lines = content.split("\n")
            if not (0 <= line < len(lines)):
                return
            new_line = toggle_task_line(lines[line], checked)
            if new_line is None or new_line == lines[line]:
                return
            lines[line] = new_line
            try:
                self._suppress_reload_until = GLib.get_monotonic_time() / 1e6 + 1.0
                backend_for(self.current_uri).write_bytes_atomic(
                    self.current_uri,
                    "\n".join(lines).encode("utf-8"),
                )
            except (OSError, StorageError):
                return
            self._reload()

    # ---- smart paste + smart list + block move (editor keypress) ------------

    def _on_editor_keypress(self, _w, event):
        CTRL = Gdk.ModifierType.CONTROL_MASK
        SHIFT = Gdk.ModifierType.SHIFT_MASK
        ALT = Gdk.ModifierType.MOD1_MASK
        state = event.state & (CTRL | SHIFT | ALT)
        # Ctrl+V: smart paste
        if event.keyval == Gdk.KEY_v and state == CTRL:
            return self._smart_paste()
        # Enter: smart list continuation
        if event.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and state == 0:
            if self._smart_newline():
                return True
        # Alt+Up / Alt+Down: block move
        if event.keyval == Gdk.KEY_Up and state == ALT:
            self._move_lines(-1)
            return True
        if event.keyval == Gdk.KEY_Down and state == ALT:
            self._move_lines(1)
            return True
        return False

    # Smart paste: image > HTML > CSV/TSV > default
    def _smart_paste(self) -> bool:
        clip = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        if clip.wait_is_image_available():
            pb = clip.wait_for_image()
            if pb is not None and self._handle_image_paste(pb):
                return True
        html_atom = Gdk.Atom.intern("text/html", False)
        if clip.wait_is_target_available(html_atom):
            data = clip.wait_for_contents(html_atom)
            if data is not None:
                raw = data.get_data()
                if isinstance(raw, bytes):
                    try:
                        html_text = raw.decode("utf-8")
                    except UnicodeDecodeError:
                        html_text = raw.decode("utf-16", errors="replace")
                else:
                    html_text = str(raw)
                if html_text.strip():
                    md = html_to_markdown(html_text)
                    if md.strip():
                        self._insert_text(md + "\n")
                        return True
        text = clip.wait_for_text()
        if text:
            sep, ok = looks_like_csv(text)
            if ok:
                self._insert_text(csv_to_markdown_table(text, sep))
                return True
        return False

    def _smart_newline(self) -> bool:
        buf = self.editor_buffer
        it = buf.get_iter_at_mark(buf.get_insert())
        line_idx = it.get_line()
        line_start = buf.get_iter_at_line(line_idx)
        line_end = line_start.copy()
        if not line_end.ends_line():
            line_end.forward_to_line_end()
        line_text = buf.get_text(line_start, line_end, True)
        # empty bullet / task / numbered: exit list
        m_bullet = LIST_BULLET_RE.match(line_text)
        m_ord = LIST_ORDERED_RE.match(line_text)
        if m_bullet and not m_bullet.group(4).strip():
            buf.begin_user_action()
            buf.delete(line_start, line_end)
            buf.insert_at_cursor("\n")
            buf.end_user_action()
            return True
        if m_ord and not m_ord.group(3).strip():
            buf.begin_user_action()
            buf.delete(line_start, line_end)
            buf.insert_at_cursor("\n")
            buf.end_user_action()
            return True
        # continue list
        if m_bullet:
            indent, marker, task, _content = m_bullet.groups()
            next_marker = f"{indent}{marker} "
            if task is not None:
                next_marker += "[ ] "
            buf.begin_user_action()
            buf.insert_at_cursor("\n" + next_marker)
            buf.end_user_action()
            return True
        if m_ord:
            indent, num, _content = m_ord.groups()
            try:
                nxt = int(num) + 1
            except ValueError:
                nxt = 1
            buf.begin_user_action()
            buf.insert_at_cursor(f"\n{indent}{nxt}. ")
            buf.end_user_action()
            return True
        return False

    def _move_lines(self, delta: int):
        buf = self.editor_buffer
        if buf.get_has_selection():
            s, e = buf.get_selection_bounds()
        else:
            it = buf.get_iter_at_mark(buf.get_insert())
            s = it.copy()
            e = it.copy()
        s.set_line_offset(0)
        if not e.ends_line():
            e.forward_to_line_end()
        first, last = s.get_line(), e.get_line()
        total_lines = buf.get_line_count()
        if delta < 0 and first == 0:
            return
        if delta > 0 and last >= total_lines - 1:
            return
        block_start = buf.get_iter_at_line(first)
        block_end = buf.get_iter_at_line(last)
        if not block_end.ends_line():
            block_end.forward_to_line_end()
        block = buf.get_text(block_start, block_end, True)
        buf.begin_user_action()
        if delta < 0:
            prev_start = buf.get_iter_at_line(first - 1)
            prev_end = buf.get_iter_at_line(first)
            prev_text = buf.get_text(prev_start, prev_end, True).rstrip("\n")
            # delete block + prev
            region_start = buf.get_iter_at_line(first - 1)
            region_end = block_end.copy()
            buf.delete(region_start, region_end)
            buf.insert(region_start, block + "\n" + prev_text)
        else:
            next_start = buf.get_iter_at_line(last + 1)
            next_end = next_start.copy()
            if not next_end.ends_line():
                next_end.forward_to_line_end()
            next_text = buf.get_text(next_start, next_end, True)
            region_start = buf.get_iter_at_line(first)
            region_end = next_end.copy()
            buf.delete(region_start, region_end)
            buf.insert(region_start, next_text + "\n" + block)
        buf.end_user_action()

    # ---- image paste --------------------------------------------------------

    def _handle_image_paste(self, pb) -> bool:
        if self.current_path:
            assets = self.current_path.parent / "assets"
        else:
            assets = Path.home() / "Pictures" / "vertexwrite"
        try:
            assets.mkdir(parents=True, exist_ok=True)
        except OSError:
            return False
        ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        p = assets / f"image-{ts}.png"
        n = 1
        while p.exists():
            n += 1
            p = assets / f"image-{ts}-{n}.png"
        try:
            pb.savev(str(p), "png", [], [])
        except Exception:
            return False
        if self.current_path:
            try:
                rel = os.path.relpath(
                    p, self.current_path.parent).replace(
                    os.sep, "/")
            except ValueError:
                rel = str(p)
        else:
            rel = str(p)
        self._insert_text(f"![{p.stem}]({rel})\n")
        return True

    # ---- back/forward navigation --------------------------------------------

    def _history_push(self, target: FileUri | Path, line: int):
        if not target:
            return
        uri = target if isinstance(target, FileUri) else FileUri.from_path(target)
        entry = (uri, max(0, int(line or 0)))
        if self._history and self._history_idx >= 0 and self._history[self._history_idx] == entry:
            return
        # truncate forward history
        self._history = self._history[: self._history_idx + 1]
        self._history.append(entry)
        self._history_idx = len(self._history) - 1
        if len(self._history) > 100:
            drop = len(self._history) - 100
            self._history = self._history[drop:]
            self._history_idx -= drop

    def _history_back(self, *_):
        if self._history_idx <= 0:
            return
        if self.current_uri:
            cur_line = self.editor_buffer.get_iter_at_mark(
                self.editor_buffer.get_insert()).get_line() if self.mode == "edit" else 0
            if self._history_idx >= len(self._history) or \
               self._history[self._history_idx] != (self.current_uri, cur_line):
                self._history_push(self.current_uri, cur_line)
        self._history_idx -= 1
        self._navigate_to(*self._history[self._history_idx])

    def _history_forward(self, *_):
        if self._history_idx + 1 >= len(self._history):
            return
        self._history_idx += 1
        self._navigate_to(*self._history[self._history_idx])

    def _navigate_to(self, uri: FileUri, line: int):
        if uri.is_local and not uri.to_path().exists():
            return
        self._in_history_nav = True
        try:
            self.load_document_uri(uri)
            if line > 0:
                GLib.idle_add(self._goto_line, line)
        finally:
            self._in_history_nav = False

    # ---- typewriter mode ----------------------------------------------------

    def _toggle_typewriter(self, *_):
        self.typewriter_on = not self.typewriter_on
        if self.typewriter_on and self.mode == "edit":
            GLib.idle_add(self._recenter_editor)

    # ---- command palette + actions ------------------------------------------

    def _open_palette(self, *_):
        CommandPalette(
            self,
            provider=self._palette_items,
            on_select=self._palette_select,
            placeholder="Jump to file, heading, or action…").show_all()

    def _open_folder_search(self, *_):
        base = (self.current_path.parent if self.current_path else Path.cwd())
        CommandPalette(
            self,
            provider=lambda q: self._folder_search_items(
                base,
                q),
            on_select=self._palette_select,
            placeholder=f"Search {base} …",
            min_query_chars=2).show_all()

    def _palette_items(self, q: str):
        ql = (q or "").lower().strip()
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
            ("Toggle sidebar", "Ctrl+Shift+O", "action:sidebar"),
            ("Connect SSH/SFTP…", "", "action:remote"),
            ("Toggle typewriter mode", "Ctrl+Shift+T", "action:typewriter"),
            ("Reload", "Ctrl+R", "action:reload"),
            ("Toggle theme", "Ctrl+D", "action:theme"),
            ("Search in folder…", "Ctrl+Shift+F", "action:folder_search"),
            ("Open from URL…", "", "action:open_url"),
            ("Insert table…", "", "action:insert_table"),
            ("Show all tasks in folder…", "", "action:tasks"),
            ("Show backlinks to this file", "", "action:backlinks"),
            ("Check links in current buffer", "", "action:link_check"),
            ("View snapshot history…", "", "action:snapshots"),
            ("Export as PDF (via pandoc)", "", "action:export_pdf"),
            ("Export as DOCX (via pandoc)", "", "action:export_docx"),
            ("Export as HTML (via pandoc)", "", "action:export_html"),
            ("Export as EPUB (via pandoc)", "", "action:export_epub"),
            (f"What’s New in {__version__}", "", "action:whats_new"),
            ("Keyboard Shortcuts", "", "action:shortcuts"),
            (f"About {APP_NAME}", "", "action:about"),
            (f"Visit {DEVELOPER} website", "", "action:website"),
            ("Open Documentation", "", "action:docs"),
            ("Report an Issue", "", "action:issues"),
        ]
        for label, shortcut, key in actions:
            items.append({"label": label, "sub": shortcut, "key": key})
        src = ""
        if self.mode == "edit":
            src = self._buffer_text()
        elif self.current_path and self.current_path.exists():
            try:
                src = self.current_path.read_text(encoding="utf-8")
            except OSError:
                pass
        for h in extract_headings(src):
            items.append({"label": ("#" * h["level"]) + " " + h["title"],
                          "sub": f"heading · line {h['line'] + 1}",
                          "key": f"heading:{h['line']}"})
        folder = self.current_path.parent if self.current_path else None
        if folder and folder.is_dir():
            try:
                files = sorted(folder.rglob("*.md"))[:200]
            except OSError:
                files = []
            for f in files:
                if self.current_path and f == self.current_path:
                    continue
                try:
                    rel = f.relative_to(folder)
                except ValueError:
                    rel = f
                items.append({"label": f.name, "sub": f"file · {rel}",
                              "key": f"file:{f}"})
        if not ql:
            return items[:PALETTE_ITEM_CAP]
        return [it for it in items
                if ql in it["label"].lower()
                or ql in (it.get("sub") or "").lower()][:PALETTE_ITEM_CAP]

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
                    snip = line.strip()
                    if len(snip) > 140:
                        snip = snip[:140] + "…"
                    results.append({"label": snip or "(empty line match)",
                                    "sub": f"{rel}:{i + 1}",
                                    "key": f"file_line:{f}:{i}"})
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
                "outline": self._toggle_outline,
                "sidebar": self._toggle_outline,
                "remote": self._open_remote_from_welcome,
                "typewriter": self._toggle_typewriter,
                "open_url": self._open_from_url_prompt,
                "insert_table": self._insert_table_prompt,
                "tasks": self._show_tasks_palette,
                "backlinks": self._show_backlinks_palette,
                "link_check": self._link_integrity_palette,
                "snapshots": self._snapshot_palette,
                "export_pdf": lambda *_: self._pandoc_export("pdf"),
                "export_docx": lambda *_: self._pandoc_export("docx"),
                "export_html": lambda *_: self._pandoc_export("html"),
                "export_epub": lambda *_: self._pandoc_export("epub"),
                "whats_new": self._show_whats_new,
                "shortcuts": self._show_shortcuts,
                "about": self._show_about,
                "website": lambda *_: self._open_url(WEBSITE),
                "docs": lambda *_: self._open_url(WIKI_URL),
                "issues": lambda *_: self._open_url(ISSUES_URL),
                "split": lambda *_: (self._ensure_edit_mode(),
                                     self._set_edit_view("split", self.view_split_btn)),
                "editor_only": lambda *_: (self._ensure_edit_mode(),
                                           self._set_edit_view("editor", self.view_editor_btn)),
                "preview_only": lambda *_: (self._ensure_edit_mode(),
                                            self._set_edit_view("preview", self.view_preview_btn)),
            }
            fn = dispatch.get(name)
            if fn:
                fn()
            return
        if key.startswith("heading:"):
            self._goto_line(int(key[len("heading:"):]))
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
        if key.startswith("snapshot:"):
            p = Path(key[len("snapshot:"):])
            if p.exists():
                self._show_snapshot_preview(p)
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

    # ---- misc palette actions -----------------------------------------------

    def _open_from_url_prompt(self, *_):
        d = Gtk.Dialog(title="Open from URL", transient_for=self, flags=0)
        d.add_buttons(
            "Cancel",
            Gtk.ResponseType.CANCEL,
            "Open",
            Gtk.ResponseType.OK)
        d.set_default_size(520, 120)
        box = d.get_content_area()
        e = Gtk.Entry()
        e.set_placeholder_text("https://…")
        e.set_activates_default(True)
        e.set_margin_top(10)
        e.set_margin_bottom(10)
        e.set_margin_start(12)
        e.set_margin_end(12)
        box.pack_start(e, False, False, 0)
        d.set_default_response(Gtk.ResponseType.OK)
        d.show_all()
        r = d.run()
        url = e.get_text().strip() if r == Gtk.ResponseType.OK else ""
        d.destroy()
        if not url:
            return
        try:
            req = urllib.request.Request(
                url, headers={
                    "User-Agent": f"{APP_NAME}/{__version__}"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = resp.read()
                ctype = resp.headers.get("Content-Type", "")
        except (urllib.error.URLError, OSError, ValueError) as exc:
            self._render_error(f"Fetch failed: {exc}")
            return
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("latin-1", errors="replace")
        if "html" in ctype.lower():
            text = html_to_markdown(text)
        base = APP_DIR
        title = url.rsplit("/", 1)[-1] or url
        self.current_path = None
        self.is_untitled = True
        self.edit_btn.set_sensitive(True)
        self._headings_cache = extract_headings(text)
        self._load_editor_text(text)
        self.header.props.title = title
        self.header.props.subtitle = f"(fetched) {url}"
        self.webview.load_html(
            render(
                text,
                self.theme,
                title,
                base),
            base.as_uri() +
            "/")

    def _insert_table_prompt(self, *_):
        d = Gtk.Dialog(title="Insert table", transient_for=self, flags=0)
        d.add_buttons(
            "Cancel",
            Gtk.ResponseType.CANCEL,
            "Insert",
            Gtk.ResponseType.OK)
        box = d.get_content_area()
        grid = Gtk.Grid(row_spacing=8, column_spacing=10)
        grid.set_margin_top(10)
        grid.set_margin_bottom(10)
        grid.set_margin_start(12)
        grid.set_margin_end(12)
        grid.attach(Gtk.Label(label="Rows:", xalign=0), 0, 0, 1, 1)
        rows = Gtk.SpinButton.new_with_range(1, 40, 1)
        rows.set_value(3)
        grid.attach(rows, 1, 0, 1, 1)
        grid.attach(Gtk.Label(label="Columns:", xalign=0), 0, 1, 1, 1)
        cols = Gtk.SpinButton.new_with_range(1, 20, 1)
        cols.set_value(3)
        grid.attach(cols, 1, 1, 1, 1)
        box.pack_start(grid, False, False, 0)
        d.set_default_response(Gtk.ResponseType.OK)
        d.show_all()
        r = d.run()
        rv = int(rows.get_value())
        cv = int(cols.get_value())
        d.destroy()
        if r != Gtk.ResponseType.OK:
            return
        header = "| " + " | ".join(f"Col {i + 1}" for i in range(cv)) + " |"
        sep = "| " + " | ".join(["---"] * cv) + " |"
        body = "\n".join(
            "| " +
            " | ".join(
                [""] *
                cv) +
            " |" for _ in range(rv))
        self._insert_text(f"\n{header}\n{sep}\n{body}\n")

    def _show_tasks_palette(self, *_):
        base = self.current_path.parent if self.current_path else Path.cwd()

        def provider(q):
            q = (q or "").lower().strip()
            items = []
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
                    m = TASK_LINE_RE.match(line)
                    if not m:
                        continue
                    _, box, content = m.groups()
                    status = "☑" if box.lower() == "x" else "☐"
                    label = f"{status} {content.strip()}"
                    if q and q not in label.lower() and q not in str(f).lower():
                        continue
                    try:
                        rel = f.relative_to(base)
                    except ValueError:
                        rel = f
                    items.append({"label": label, "sub": f"{rel}:{i + 1}",
                                  "key": f"file_line:{f}:{i}"})
                    if len(items) >= SEARCH_RESULT_CAP:
                        return items
            return items or [
                {"label": "No tasks found", "sub": str(base), "key": None}]
        CommandPalette(self, provider=provider, on_select=self._palette_select,
                       placeholder=f"Tasks in {base} …").show_all()

    def _show_backlinks_palette(self, *_):
        if not self.current_path:
            self._render_error("Save the document first to find backlinks.")
            return
        base = self.current_path.parent
        target_name = self.current_path.name
        target_stem = self.current_path.stem
        target_abs = self.current_path.resolve()

        def provider(q):
            q = (q or "").lower().strip()
            results = []
            try:
                files = sorted(base.rglob("*.md"))
            except OSError:
                files = []
            for f in files:
                if f.resolve() == target_abs:
                    continue
                if any(part in (".git", "node_modules") for part in f.parts):
                    continue
                try:
                    text = f.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                for i, line in enumerate(text.split("\n")):
                    matched = False
                    for m in MD_LINK_RE.finditer(line):
                        ref = m.group(3).strip().split("#")[0]
                        try:
                            resolved = (f.parent / ref).resolve()
                            if resolved == target_abs:
                                matched = True
                                break
                        except (OSError, ValueError):
                            pass
                    if not matched:
                        for m in WIKI_LINK_RE.finditer(line):
                            nm = m.group(1).strip()
                            if nm == target_stem or nm == target_name:
                                matched = True
                                break
                    if not matched:
                        continue
                    snip = line.strip()
                    if len(snip) > 140:
                        snip = snip[:140] + "…"
                    try:
                        rel = f.relative_to(base)
                    except ValueError:
                        rel = f
                    if q and q not in snip.lower() and q not in str(rel).lower():
                        continue
                    results.append({"label": snip, "sub": f"{rel}:{i + 1}",
                                    "key": f"file_line:{f}:{i}"})
            return results or [{"label": "No backlinks found",
                                "sub": str(target_name), "key": None}]
        CommandPalette(self, provider=provider, on_select=self._palette_select,
                       placeholder=f"Backlinks to {target_name} …").show_all()

    def _link_integrity_palette(self, *_):
        base = self.current_path.parent if self.current_path else Path.cwd()
        source = self._buffer_text() if self.mode == "edit" else (
            self.current_path.read_text(encoding="utf-8") if self.current_path else "")
        issues = []
        for i, line in enumerate(source.split("\n")):
            for m in MD_LINK_RE.finditer(line):
                url = m.group(3).strip()
                if url.startswith(
                        ("#", "mailto:", "tel:", "http://", "https://", "data:")):
                    continue
                target = (
                    base /
                    url.split(
                        "#",
                        1)[0]).resolve() if base else Path(url)
                if not target.exists():
                    issues.append({"label": f"Missing: {url}",
                                   "sub": f"line {i + 1} · {line.strip()[:120]}",
                                   "key": f"heading_line:{i}"})
        if not issues:
            issues = [{"label": "All relative links resolve",
                       "sub": f"scanned {len(source.splitlines())} lines",
                       "key": None}]

        def provider(q):
            ql = (q or "").lower().strip()
            if not ql:
                return issues
            return [
                it for it in issues if ql in it["label"].lower() or ql in (
                    it.get("sub") or "").lower()]

        def on_select(k):
            if k and k.startswith("heading_line:"):
                self._goto_line(int(k[len("heading_line:"):]))
        CommandPalette(self, provider=provider, on_select=on_select,
                       placeholder="Link issues").show_all()

    def _snapshot_palette(self, *_):
        if not self.current_path:
            self._render_error("Save the document first to browse snapshots.")
            return
        snaps = list_snapshots(self.current_path)
        if not snaps:
            self._render_error(
                "No snapshots yet. Snapshots are written on save.")
            return
        items = []
        for p in snaps:
            try:
                ts = datetime.datetime.strptime(p.stem, "%Y%m%d-%H%M%S")
                label = ts.strftime("%Y-%m-%d %H:%M:%S")
            except ValueError:
                label = p.stem
            items.append(
                {"label": label, "sub": str(p), "key": f"snapshot:{p}"})
        CommandPalette(self, provider=lambda q: [
            it for it in items
            if not q or q.lower() in it["label"].lower()
        ], on_select=self._palette_select,
            placeholder=f"Snapshots of {self.current_path.name}").show_all()

    def _show_snapshot_preview(self, snap: Path):
        try:
            text = snap.read_text(encoding="utf-8")
        except OSError as exc:
            self._render_error(f"Could not read {snap}: {exc}")
            return
        self.header.props.title = f"snapshot · {snap.stem}"
        self.header.props.subtitle = str(snap)
        self.webview.load_html(render(text, self.theme,
                                      f"{snap.stem} (snapshot)", snap.parent),
                               snap.parent.as_uri() + "/")

    def _pandoc_export(self, fmt: str):
        if not self.current_path and not self.editor_buffer.get_modified():
            self._render_error("Open or save a document first.")
            return
        if not shutil.which("pandoc"):
            self._render_error(
                "pandoc is not installed.\n\nOn Ubuntu:\n\n    sudo apt install pandoc")
            return
        if self.is_untitled or not self.current_path:
            if not self._save_as():
                return
        if self.editor_buffer.get_modified():
            self._save()
        ext = {
            "pdf": "pdf",
            "docx": "docx",
            "html": "html",
            "epub": "epub"}[fmt]
        dialog = Gtk.FileChooserDialog(
            title=f"Export as {fmt.upper()}",
            parent=self,
            action=Gtk.FileChooserAction.SAVE)
        dialog.add_buttons(
            "Cancel",
            Gtk.ResponseType.CANCEL,
            "Export",
            Gtk.ResponseType.OK)
        dialog.set_do_overwrite_confirmation(True)
        assert self.current_path is not None
        dialog.set_current_folder(str(self.current_path.parent))
        dialog.set_current_name(f"{self.current_path.stem}.{ext}")
        r = dialog.run()
        chosen = dialog.get_filename() if r == Gtk.ResponseType.OK else None
        dialog.destroy()
        if not chosen:
            return
        try:
            cmd = ["pandoc", str(self.current_path), "-o", chosen,
                   "--metadata", f"title={self.current_path.stem}"]
            if fmt == "pdf":
                cmd += ["--pdf-engine=xelatex"]
            res = subprocess.run(
                cmd, capture_output=True, text=True, timeout=120)
            if res.returncode != 0:
                self._render_error(
                    f"pandoc failed:\n\n{res.stderr or res.stdout}\n\n"
                    f"Command: {' '.join(shlex.quote(c) for c in cmd)}"
                )
                return
        except (OSError, subprocess.TimeoutExpired) as exc:
            self._render_error(f"Could not run pandoc: {exc}")
            return

    # ---- file: new / save / save as -----------------------------------------

    def _on_new(self, *_):
        if not self._confirm_discard_if_dirty():
            return
        self.current_path = None
        self.current_uri = None
        self.is_untitled = True
        self.edit_btn.set_sensitive(True)
        self._load_editor_text("# Untitled\n\n")
        self._headings_cache = extract_headings("# Untitled\n\n")
        if self.outline_visible:
            self.outline.update(self._headings_cache)
        if self.monitor is not None:
            self.monitor.cancel()
            self.monitor = None
        self.edit_btn.set_active(True)
        if self.mode == "edit" and self.edit_view in ("split", "preview"):
            self._render_live_preview()

    def _save(self, *_):
        if self.mode != "edit" and not self.editor_buffer.get_modified():
            return True
        if self.is_untitled or not self.current_uri:
            return self._save_as()
        return self._write_to(self.current_uri)

    def _save_as(self, *_):
        d = Gtk.FileChooserDialog(title="Save markdown file", parent=self,
                                  action=Gtk.FileChooserAction.SAVE)
        d.add_buttons(
            "Cancel",
            Gtk.ResponseType.CANCEL,
            "Save",
            Gtk.ResponseType.OK)
        d.set_do_overwrite_confirmation(True)
        if self.current_path:
            d.set_current_folder(str(self.current_path.parent))
            d.set_current_name(self.current_path.name)
        elif self.current_uri:
            d.set_current_name(self.current_uri.name)
        else:
            d.set_current_name("untitled.md")
        r = d.run()
        chosen = d.get_filename() if r == Gtk.ResponseType.OK else None
        d.destroy()
        if not chosen:
            return False
        p = Path(chosen)
        if not self._write_to(p):
            return False
        self.current_path = p
        self.current_uri = FileUri.from_path(p)
        self.is_untitled = False
        add_recent_uri(self.current_uri)
        self._refresh_history_sidebar()
        if self.outline_visible:
            self._ensure_sidebar_folder_for_file(p, force_rescan=True)
        self._watch_file(p)
        self._update_title()
        return True

    def _write_to(self, target: FileUri | Path) -> bool:
        text = self._buffer_text()
        uri = target if isinstance(target, FileUri) else FileUri.from_path(target)
        try:
            self._suppress_reload_until = GLib.get_monotonic_time() / 1e6 + 1.0
            backend_for(uri).write_bytes_atomic(uri, text.encode("utf-8"))
        except (OSError, StorageError) as exc:
            self._render_error(f"Could not write {uri.display()}: {exc}")
            return False
        self.editor_buffer.set_modified(False)
        self._update_title()
        if uri.is_local:
            write_snapshot(uri.to_path(), text)
        return True

    def _confirm_discard_if_dirty(self):
        if not self.editor_buffer.get_modified():
            return True
        d = Gtk.MessageDialog(parent=self, flags=0,
                              message_type=Gtk.MessageType.QUESTION,
                              buttons=Gtk.ButtonsType.NONE,
                              text="You have unsaved changes.")
        d.format_secondary_text("Save before continuing?")
        d.add_buttons("Discard", Gtk.ResponseType.CLOSE,
                      "Cancel", Gtk.ResponseType.CANCEL,
                      "Save", Gtk.ResponseType.ACCEPT)
        r = d.run()
        d.destroy()
        if r == Gtk.ResponseType.CANCEL:
            return False
        if r == Gtk.ResponseType.ACCEPT:
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
            end_i = buf.get_iter_at_mark(buf.get_insert())
            start_i = end_i.copy()
            start_i.backward_chars(len(right) + len(placeholder))
            end_i.backward_chars(len(right))
            buf.select_range(start_i, end_i)
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
            ls = it.copy()
            ls.set_line_offset(0)
            le = it.copy()
            if not le.ends_line():
                le.forward_to_line_end()
            self._prefix_range(buf, ls, le, prefix, toggle)
        buf.end_user_action()
        self.editor.grab_focus()

    def _prefix_range(self, buf, s, e, prefix, toggle):
        for li in range(s.get_line(), e.get_line() + 1):
            it = buf.get_iter_at_line(li)
            if not it:
                continue
            le = it.copy()
            if not le.ends_line():
                le.forward_to_line_end()
            cur = buf.get_text(it, le, True)
            if toggle and cur.startswith(prefix):
                ep = it.copy()
                ep.forward_chars(len(prefix))
                buf.delete(it, ep)
            else:
                buf.insert(it, prefix)

    def _set_heading_level(self, level: int):
        """Replace any existing heading prefix on the current line(s) with `level` `#`s."""
        buf = self.editor_buffer
        buf.begin_user_action()
        if buf.get_has_selection():
            s, e = buf.get_selection_bounds()
            first, last = s.get_line(), e.get_line()
        else:
            it = buf.get_iter_at_mark(buf.get_insert())
            first = last = it.get_line()
        for line_idx in range(first, last + 1):
            li = buf.get_iter_at_line(line_idx)
            if not li:
                continue
            le = li.copy()
            if not le.ends_line():
                le.forward_to_line_end()
            text = buf.get_text(li, le, True)
            stripped = re.sub(r"^#{1,6}\s+", "", text)
            new = (("#" * level) + " " if level > 0 else "") + stripped
            if new != text:
                buf.delete(li, le)
                buf.insert(li, new)
        buf.end_user_action()
        self.editor.grab_focus()

    def _insert_link(self):
        buf = self.editor_buffer
        buf.begin_user_action()
        if buf.get_has_selection():
            s, e = buf.get_selection_bounds()
            lbl = buf.get_text(s, e, True)
            buf.delete(s, e)
            buf.insert(s, f"[{lbl}](https://)")
        else:
            buf.insert_at_cursor("[text](https://)")
        buf.end_user_action()
        self.editor.grab_focus()

    # ---- help menu actions --------------------------------------------------

    def _open_url(self, url: str):
        try:
            Gtk.show_uri_on_window(self, url, Gdk.CURRENT_TIME)
        except Exception:
            try:
                Gio.AppInfo.launch_default_for_uri(url, None)
            except Exception as exc:
                self._render_error(f"Could not open {url}: {exc}")

    def _show_about(self, *_):
        d = Gtk.AboutDialog(transient_for=self, modal=True)
        d.set_program_name(APP_NAME)
        d.set_version(__version__)
        d.set_comments("Edit Markdown wherever it lives: local folders or remote servers over SSH/SFTP.")
        d.set_copyright(f"© 2026 {DEVELOPER}")
        d.set_license_type(Gtk.License.MIT_X11)
        d.set_website(WEBSITE)
        d.set_website_label(WEBSITE.rstrip("/").split("//", 1)[-1])
        d.set_authors([f"{DEVELOPER} <{WEBSITE}>"])
        icon = APP_DIR / "icon.png"
        if icon.exists():
            try:
                pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(
                    str(icon), 128, 128, True)
                d.set_logo(pb)
            except Exception:
                pass
        d.run()
        d.destroy()

    def _show_whats_new(self, *_):
        text = self._latest_changelog_section()
        d = Gtk.Dialog(title=f"What’s new in {APP_NAME} {__version__}",
                       transient_for=self, modal=True)
        d.add_buttons("Close", Gtk.ResponseType.CLOSE)
        d.set_default_size(620, 560)
        web = WebKit2.WebView()
        web.get_settings().set_property("enable-javascript", False)
        web.load_html(render(text, self.theme, "What’s new", APP_DIR),
                      APP_DIR.as_uri() + "/")
        scroller = Gtk.ScrolledWindow()
        scroller.set_hexpand(True)
        scroller.set_vexpand(True)
        scroller.add(web)
        d.get_content_area().pack_start(scroller, True, True, 0)
        d.show_all()
        d.run()
        d.destroy()

    def _latest_changelog_section(self) -> str:
        candidates = [
            APP_DIR / "CHANGELOG.md",                      # flatpak/local copy
            APP_DIR.parent / "CHANGELOG.md",               # local dev layout
            Path("/usr/share/doc") / APP_SLUG / "CHANGELOG.md",
            Path("/usr/share/doc") / APP_SLUG / "CHANGELOG.md.gz",
            Path("/usr/share/doc") / APP_SLUG / "changelog.gz",
        ]
        text = None
        found_unreadable = False
        for cp in candidates:
            if not cp.exists():
                continue
            try:
                if cp.suffix == ".gz":
                    with gzip.open(cp, "rt", encoding="utf-8", errors="replace") as fh:
                        text = fh.read()
                else:
                    text = cp.read_text(encoding="utf-8", errors="replace")
                break
            except OSError:
                found_unreadable = True
                continue
        if text is None:
            if found_unreadable:
                return f"# {APP_NAME} {__version__}\n\n(CHANGELOG.md unreadable.)"
            return f"# {APP_NAME} {__version__}\n\n(No CHANGELOG.md found.)"
        # find the FIRST `## [<not-Unreleased>]` heading and capture until the
        # next `## [`
        pat = re.compile(
            r"^## \[(?!Unreleased)([^\]]+)\][^\n]*$",
            re.MULTILINE)
        m = pat.search(text)
        if not m:
            return f"# {APP_NAME} {__version__}\n\nNo released entries found yet."
        start = m.start()
        nxt = pat.search(text, m.end())
        end = nxt.start() if nxt else len(text)
        return text[start:end].strip()

    def _show_shortcuts(self, *_):
        win = Gtk.ShortcutsWindow(transient_for=self, modal=True)
        section = Gtk.ShortcutsSection(visible=True, section_name="main",
                                       title="Shortcuts", max_height=12)

        def group(title, items):
            g = Gtk.ShortcutsGroup(visible=True, title=title)
            for accel, label in items:
                g.add(
                    Gtk.ShortcutsShortcut(
                        visible=True,
                        accelerator=accel,
                        title=label))
            return g

        section.add(group("File", [
            ("<Primary>o", "Open file"),
            ("<Primary>n", "New document"),
            ("<Primary>s", "Save"),
            ("<Primary><Shift>s", "Save As"),
            ("<Primary>r", "Reload"),
            ("<Primary>q", "Quit"),
        ]))
        section.add(group("View", [
            ("<Primary>e", "Toggle edit mode"),
            ("<Primary><Shift>o", "Toggle local/SSH sidebar"),
            ("<Primary><Shift>t", "Toggle typewriter mode"),
            ("<Primary>d", "Toggle theme"),
        ]))
        section.add(group("Navigation", [
            ("<Primary>p", "Command palette"),
            ("<Primary>f", "Find in buffer"),
            ("<Primary><Shift>f", "Search current folder"),
            ("<Alt>Left", "Back"),
            ("<Alt>Right", "Forward"),
        ]))
        section.add(group("Editing", [
            ("<Primary>z", "Undo"),
            ("<Primary><Shift>z", "Redo"),
            ("<Primary>x <Primary>c <Primary>v", "Cut · Copy · Smart paste"),
            ("<Alt>Up", "Move line up"),
            ("<Alt>Down", "Move line down"),
            ("Return", "Smart list continuation"),
        ]))
        section.add(group("Formatting", [
            ("<Primary>b", "Bold"),
            ("<Primary>i", "Italic"),
            ("<Primary>k", "Link"),
            ("<Primary>h", "Heading 1"),
        ]))
        if hasattr(win, "add_section"):
            win.add_section(section)
        else:
            win.add(section)
        win.show_all()
        win.present()

    def _maybe_show_whats_new_on_upgrade(self):
        try:
            last = (LAST_SHOWN_VERSION_PATH.read_text().strip()
                    if LAST_SHOWN_VERSION_PATH.exists() else "")
        except OSError:
            last = ""
        if last != __version__:
            try:
                STATE_DIR.mkdir(parents=True, exist_ok=True)
                LAST_SHOWN_VERSION_PATH.write_text(__version__)
            except OSError:
                pass
            # don't pop the dialog on the very first run, only on actual
            # upgrades
            if last:
                self._show_whats_new()
        return False

    # ---- editor inserts -----------------------------------------------------

    def _insert_image(self):
        d = Gtk.FileChooserDialog(title="Insert image", parent=self,
                                  action=Gtk.FileChooserAction.OPEN)
        d.add_buttons(
            "Cancel",
            Gtk.ResponseType.CANCEL,
            "Insert",
            Gtk.ResponseType.OK)
        imgf = Gtk.FileFilter()
        imgf.set_name("Images")
        for p in ("*.png", "*.jpg", "*.jpeg", "*.gif", "*.svg", "*.webp"):
            imgf.add_pattern(p)
        d.add_filter(imgf)
        r = d.run()
        chosen = d.get_filename() if r == Gtk.ResponseType.OK else None
        d.destroy()
        if not chosen:
            return
        ip = Path(chosen)
        if self.current_path:
            try:
                rel = os.path.relpath(
                    ip, self.current_path.parent).replace(
                    os.sep, "/")
            except ValueError:
                rel = str(ip)
        else:
            rel = str(ip)
        self.editor_buffer.insert_at_cursor(f"![{ip.stem}]({rel})")
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
    parser = argparse.ArgumentParser(
        prog=APP_CLI,
        description="Edit Markdown locally or over SSH/SFTP.")
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
