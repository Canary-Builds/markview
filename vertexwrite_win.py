#!/usr/bin/env python3
"""VertexWrite — minimal modern markdown viewer + editor for Windows.

PyQt6-based Windows port of the GTK3/WebKit2 Linux application.
Reuses vertexwrite_core.py for all rendering and markdown processing.
"""

import datetime
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import argparse
from pathlib import Path

# Ensure Qt DLLs (especially WebEngine/WebChannel) are findable on Windows.
# PyQt6 installs them under its own Qt6/bin directory which may not be on PATH.
if sys.platform == "win32":
    try:
        import PyQt6
        _qt_bin = os.path.join(os.path.dirname(PyQt6.__file__), "Qt6", "bin")
        if os.path.isdir(_qt_bin):
            os.add_dll_directory(_qt_bin)
            if _qt_bin not in os.environ.get("PATH", ""):
                os.environ["PATH"] = _qt_bin + os.pathsep + os.environ.get("PATH", "")
    except Exception:
        pass

from PyQt6.QtCore import (
    QFileSystemWatcher, QObject, QSize, Qt, QTimer, QUrl, pyqtSignal,
    pyqtSlot,
)
from PyQt6.QtGui import (
    QAction, QColor, QDesktopServices, QDragEnterEvent, QDropEvent, QFont,
    QIcon, QKeySequence, QPainter, QPixmap, QSyntaxHighlighter,
    QTextCharFormat, QTextCursor,
)
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtWebEngineCore import QWebEnginePage
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import (
    QApplication, QDialog, QDialogButtonBox, QDockWidget, QFileDialog,
    QGridLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMainWindow, QMenu, QMenuBar, QMessageBox,
    QPlainTextEdit, QPushButton, QSizePolicy, QSpinBox, QSplitter,
    QStatusBar, QTabWidget, QToolBar, QToolButton, QVBoxLayout, QWidget,
)

from vertexwrite_core import (
    HEADING_RE,
    LIST_BULLET_RE,
    LIST_ORDERED_RE,
    MD_LINK_RE,
    TASK_LINE_RE,
    WIKI_LINK_RE,
    count_words_and_read_time,
    csv_to_markdown_table,
    extract_headings,
    html_to_markdown,
    list_snapshots as _list_snapshots,
    looks_like_csv,
    render as _render,
    toggle_task_line,
    write_snapshot as _write_snapshot,
)

__version__ = "0.6.3"

APP_NAME = "VertexWrite"
APP_SLUG = "vertexwrite"
APP_CLI = "vertexwrite"
LEGACY_APP_SLUGS = ("vertexmarkdown", "markview")
APP_DIR = Path(__file__).resolve().parent
STYLE_PATH = APP_DIR / "style.css"


def _app_data_dir(base: Path) -> Path:
    target = base / APP_SLUG
    if target.exists():
        return target
    for slug in LEGACY_APP_SLUGS:
        legacy = base / slug
        if legacy.exists():
            return legacy
    return target


CONFIG_DIR = _app_data_dir(Path(os.environ.get("APPDATA", str(Path.home()))))
STATE_DIR = _app_data_dir(Path(os.environ.get(
    "LOCALAPPDATA", str(Path.home() / "AppData/Local"))))
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
MARKDOWN_SCAN_MAX = 10000
MARKDOWN_EXTENSIONS = {".md", ".markdown", ".mdown", ".mkd"}
MARKDOWN_SKIP_DIRS = {
    ".git", "node_modules", ".venv", "venv", "__pycache__",
}


# ---------------------------------------------------------------------------
# Helpers — wrappers around vertexwrite_core with Windows paths
# ---------------------------------------------------------------------------

def render(md_text: str, theme: str, title: str,
           base_dir: Path | None = None) -> str:
    html = _render(md_text, theme, title, base_dir,
                   style_path=STYLE_PATH, custom_css_path=CUSTOM_CSS_PATH)
    # Replace the WebKit message bridge with QWebChannel bridge
    html = html.replace(
        "try { window.webkit.messageHandlers.vertexwrite.postMessage("
        "JSON.stringify(payload)); }\n    catch(e){}",
        "if(window._mvBridge) window._mvBridge.postMessage("
        "JSON.stringify(payload));"
    )
    # Inject QWebChannel setup right before </head>
    channel_js = (
        '<script src="qrc:///qtwebchannel/qwebchannel.js"></script>\n'
        '<script>\n'
        'var _mvBridge = null;\n'
        'document.addEventListener("DOMContentLoaded", function() {\n'
        '  if (typeof QWebChannel !== "undefined" && typeof qt !== "undefined") {\n'
        '    new QWebChannel(qt.webChannelTransport, function(ch) {\n'
        '      _mvBridge = ch.objects.bridge;\n'
        '      window._mvBridge = _mvBridge;\n'
        '    });\n'
        '  }\n'
        '});\n'
        '</script>\n'
    )
    html = html.replace('</head>', channel_js + '</head>')
    return html


def write_snapshot(path: Path, text: str) -> Path | None:
    return _write_snapshot(path, text, snapshot_dir=SNAPSHOT_DIR,
                           snapshot_keep=SNAPSHOT_KEEP)


def list_snapshots(path: Path) -> list[Path]:
    return _list_snapshots(path, snapshot_dir=SNAPSHOT_DIR)


def load_recents() -> list[Path]:
    try:
        raw = json.loads(RECENTS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(raw, list):
        return []
    return [Path(item) for item in raw if isinstance(item, str) and item.strip()]


def save_recents(paths: list[Path]):
    unique: list[str] = []
    seen: set[str] = set()
    for p in paths:
        s = str(p.resolve())
        if s in seen:
            continue
        seen.add(s)
        unique.append(s)
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        RECENTS_PATH.write_text(
            json.dumps(unique[:RECENT_MAX], ensure_ascii=False),
            encoding="utf-8")
    except OSError:
        pass


def add_recent(path: Path):
    path = path.resolve()
    recents = load_recents()
    recents = [p for p in recents if p != path]
    recents.insert(0, path)
    save_recents(recents)


def load_markdown_root() -> Path | None:
    try:
        value = MARKDOWN_ROOT_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not value:
        return None
    p = Path(value)
    return p if p.is_dir() else None


def save_markdown_root(path: Path | None):
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        if path is None:
            if MARKDOWN_ROOT_PATH.exists():
                MARKDOWN_ROOT_PATH.unlink()
            return
        MARKDOWN_ROOT_PATH.write_text(str(path.resolve()), encoding="utf-8")
    except OSError:
        pass


def welcome_html(theme: str) -> str:
    md_text = (
        f"# VertexWrite\n\n*v{__version__} — minimal, modern markdown viewer "
        "+ editor.*\n\n"
        "- **Open** — `Ctrl+O`, drag & drop, or CLI path\n"
        "- **Edit mode** — `Ctrl+E` (reveals the edit toolbar)\n"
        "- **Palette** — `Ctrl+P` · **Folder search** — `Ctrl+Shift+F`\n"
        "- **Outline** — `Ctrl+Shift+O` · **Typewriter mode** — "
        "`Ctrl+Shift+T`\n"
        "- **Navigate** — `Alt+Left` / `Alt+Right`\n"
        "- **Theme** — `Ctrl+D` · **Reload** — `Ctrl+R` · **Quit** — "
        "`Ctrl+Q`\n"
    )
    return render(md_text, theme, APP_NAME, APP_DIR)


def _detect_system_theme() -> str:
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        )
        value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        winreg.CloseKey(key)
        return "dark" if value == 0 else "light"
    except Exception:
        return "light"


# ---------------------------------------------------------------------------
# Markdown syntax highlighter for the editor
# ---------------------------------------------------------------------------

class MarkdownHighlighter(QSyntaxHighlighter):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._rules: list[tuple[re.Pattern, QTextCharFormat]] = []
        self._build_rules()

    def _build_rules(self):
        def fmt(fg=None, bold=False, italic=False, bg=None):
            f = QTextCharFormat()
            if fg:
                f.setForeground(QColor(fg))
            if bg:
                f.setBackground(QColor(bg))
            if bold:
                f.setFontWeight(QFont.Weight.Bold)
            if italic:
                f.setFontItalic(True)
            return f

        self._rules = [
            (re.compile(r"^#{1,6}\s+.+$", re.MULTILINE), fmt("#2f81f7", bold=True)),
            (re.compile(r"\*\*[^*]+\*\*"), fmt(bold=True)),
            (re.compile(r"(?<!\*)\*(?!\*)[^*]+\*(?!\*)"), fmt(italic=True)),
            (re.compile(r"`[^`\n]+`"), fmt("#e06c75", bg="#2d333b")),
            (re.compile(r"^\s*[-*+]\s+", re.MULTILINE), fmt("#e5c07b")),
            (re.compile(r"^\s*\d+\.\s+", re.MULTILINE), fmt("#e5c07b")),
            (re.compile(r"\[([^\]]*)\]\([^)]+\)"), fmt("#61afef")),
            (re.compile(r"^\s*>\s+.*$", re.MULTILINE), fmt("#8b949e", italic=True)),
            (re.compile(r"^---+$", re.MULTILINE), fmt("#8b949e")),
            (re.compile(r"^\s*[-*+]\s+\[[ xX]\]", re.MULTILINE), fmt("#c678dd")),
        ]
        self._fence_fmt = fmt("#98c379", bg="#1e2228")

    def highlightBlock(self, text: str):
        # Track fenced code blocks via block state
        prev_state = self.previousBlockState()
        in_fence = prev_state == 1
        if re.match(r"^\s*```", text):
            if in_fence:
                self.setFormat(0, len(text), self._fence_fmt)
                self.setCurrentBlockState(0)
                return
            else:
                self.setFormat(0, len(text), self._fence_fmt)
                self.setCurrentBlockState(1)
                return
        if in_fence:
            self.setFormat(0, len(text), self._fence_fmt)
            self.setCurrentBlockState(1)
            return
        self.setCurrentBlockState(0)
        for pattern, fmt in self._rules:
            for m in pattern.finditer(text):
                self.setFormat(m.start(), m.end() - m.start(), fmt)


# ---------------------------------------------------------------------------
# Code editor with line numbers
# ---------------------------------------------------------------------------

class LineNumberArea(QWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self):
        return QSize(self.editor.line_number_area_width(), 0)

    def paintEvent(self, event):
        self.editor.line_number_area_paint_event(event)


class CodeEditor(QPlainTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._line_number_area = LineNumberArea(self)
        self.blockCountChanged.connect(self._update_line_number_area_width)
        self.updateRequest.connect(self._update_line_number_area)
        self.cursorPositionChanged.connect(self._highlight_current_line)
        self._update_line_number_area_width(0)

        font = QFont("JetBrains Mono", 10)
        font.setStyleHint(QFont.StyleHint.Monospace)
        fallbacks = ["Fira Code", "Cascadia Code", "Consolas", "Courier New"]
        font.setFamilies([font.family()] + fallbacks)
        self.setFont(font)
        self.setTabStopDistance(
            self.fontMetrics().horizontalAdvance(" ") * 4)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.setWordWrapMode(
            __import__("PyQt6.QtGui", fromlist=["QTextOption"])
            .QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)

        self.document().setDocumentMargin(16)
        self._highlighter = MarkdownHighlighter(self.document())
        self._highlight_current_line()

    def line_number_area_width(self) -> int:
        digits = max(1, len(str(self.blockCount())))
        return 8 + self.fontMetrics().horizontalAdvance("9") * (digits + 1)

    def _update_line_number_area_width(self, _):
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def _update_line_number_area(self, rect, dy):
        if dy:
            self._line_number_area.scroll(0, dy)
        else:
            self._line_number_area.update(
                0, rect.y(), self._line_number_area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_line_number_area_width(0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._line_number_area.setGeometry(
            cr.left(), cr.top(),
            self.line_number_area_width(), cr.height())

    def line_number_area_paint_event(self, event):
        painter = QPainter(self._line_number_area)
        painter.fillRect(event.rect(), QColor("#1e1e2e"))
        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = round(
            self.blockBoundingGeometry(block)
            .translated(self.contentOffset()).top())
        bottom = top + round(self.blockBoundingRect(block).height())
        painter.setPen(QColor("#6c7086"))
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                painter.drawText(
                    0, top,
                    self._line_number_area.width() - 4,
                    self.fontMetrics().height(),
                    Qt.AlignmentFlag.AlignRight,
                    str(block_number + 1))
            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            block_number += 1
        painter.end()

    def _highlight_current_line(self):
        extra = []
        if not self.isReadOnly():
            from PyQt6.QtWidgets import QTextEdit
            sel = QTextEdit.ExtraSelection()
            sel.format.setBackground(QColor("#2a2d3e"))
            sel.format.setProperty(
                QTextCharFormat.Property.FullWidthSelection, True)
            sel.cursor = self.textCursor()
            sel.cursor.clearSelection()
            extra.append(sel)
        self.setExtraSelections(extra)

    def current_line_text(self) -> str:
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock,
                            QTextCursor.MoveMode.KeepAnchor)
        return cursor.selectedText()

    def current_line_number(self) -> int:
        return self.textCursor().blockNumber()


# ---------------------------------------------------------------------------
# WebBridge — QWebChannel bridge for JS↔Python communication
# ---------------------------------------------------------------------------

class WebBridge(QObject):
    taskToggled = pyqtSignal(int, bool)

    @pyqtSlot(str)
    def postMessage(self, msg: str):
        try:
            data = json.loads(msg)
        except (json.JSONDecodeError, TypeError):
            return
        if data.get("type") == "task_toggle":
            try:
                line = int(data["line"])
                checked = bool(data["checked"])
            except (KeyError, TypeError, ValueError):
                return
            self.taskToggled.emit(line, checked)


# ---------------------------------------------------------------------------
# Command Palette
# ---------------------------------------------------------------------------

class CommandPalette(QDialog):
    def __init__(self, parent, provider, on_select,
                 placeholder="Type to filter…", min_query_chars=0,
                 initial_query=""):
        super().__init__(parent, Qt.WindowType.Popup)
        self.provider = provider
        self.on_select = on_select
        self.min_query_chars = min_query_chars
        self.setFixedSize(680, 460)
        self.setStyleSheet("""
            QDialog { background: #1e1e2e; border: 1px solid #45475a;
                      border-radius: 10px; }
            QLineEdit { background: #313244; color: #cdd6f4;
                        border: 1px solid #45475a; border-radius: 6px;
                        padding: 8px 12px; font-size: 14px; }
            QListWidget { background: #1e1e2e; color: #cdd6f4;
                          border: none; font-size: 13px; outline: none; }
            QListWidget::item { padding: 6px 10px; border-radius: 4px; }
            QListWidget::item:selected { background: #313244; }
            QListWidget::item:hover { background: #313244; }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        self.entry = QLineEdit()
        self.entry.setPlaceholderText(placeholder)
        if initial_query:
            self.entry.setText(initial_query)
        self.entry.textChanged.connect(self._refresh)
        self.entry.returnPressed.connect(self._activate_selected)
        layout.addWidget(self.entry)

        self.listbox = QListWidget()
        self.listbox.itemActivated.connect(self._on_item_activated)
        self.listbox.itemClicked.connect(self._on_item_activated)
        layout.addWidget(self.listbox)

        self.entry.installEventFilter(self)
        self._refresh()

    def eventFilter(self, obj, event):
        if obj == self.entry and event.type() == event.Type.KeyPress:
            key = event.key()
            if key == Qt.Key.Key_Down:
                row = self.listbox.currentRow()
                if row < self.listbox.count() - 1:
                    self.listbox.setCurrentRow(row + 1)
                return True
            if key == Qt.Key.Key_Up:
                row = self.listbox.currentRow()
                if row > 0:
                    self.listbox.setCurrentRow(row - 1)
                return True
            if key == Qt.Key.Key_Escape:
                self.close()
                return True
        return super().eventFilter(obj, event)

    def _refresh(self):
        self.listbox.clear()
        q = self.entry.text() or ""
        if len(q.strip()) < self.min_query_chars:
            item = QListWidgetItem(
                f"Type at least {self.min_query_chars} characters…")
            item.setData(Qt.ItemDataRole.UserRole, None)
            self.listbox.addItem(item)
        else:
            items = self.provider(q) or []
            for it in items[:PALETTE_ITEM_CAP]:
                label = it["label"]
                sub = it.get("sub")
                display = f"{label}\n  {sub}" if sub else label
                widget_item = QListWidgetItem(display)
                widget_item.setData(Qt.ItemDataRole.UserRole, it.get("key"))
                self.listbox.addItem(widget_item)
        if self.listbox.count() > 0:
            self.listbox.setCurrentRow(0)

    def _activate_selected(self):
        item = self.listbox.currentItem()
        if item is None and self.listbox.count() > 0:
            item = self.listbox.item(0)
        self._on_item_activated(item)

    def _on_item_activated(self, item):
        if item is None:
            self.close()
            return
        key = item.data(Qt.ItemDataRole.UserRole)
        self.close()
        if key is not None:
            self.on_select(key)


# ---------------------------------------------------------------------------
# Outline Sidebar
# ---------------------------------------------------------------------------

class OutlineSidebar(QWidget):
    jumpRequested = pyqtSignal(int)
    fileOpenRequested = pyqtSignal(str)
    chooseFolderRequested = pyqtSignal()
    rescanFolderRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(260)
        self.setMaximumWidth(360)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabWidget::pane { border: none; }
            QTabBar::tab { padding: 6px 14px; }
        """)

        # Outline tab
        self.outline_list = QListWidget()
        self.outline_list.itemClicked.connect(self._on_outline_clicked)
        self.tabs.addTab(self.outline_list, "Outline")

        # History tab
        self.history_list = QListWidget()
        self.history_list.itemClicked.connect(self._on_history_clicked)
        self.tabs.addTab(self.history_list, "History")

        # Markdown tab
        md_widget = QWidget()
        md_layout = QVBoxLayout(md_widget)
        md_layout.setContentsMargins(4, 4, 4, 4)

        btn_row = QHBoxLayout()
        choose_btn = QPushButton("Choose Folder")
        choose_btn.clicked.connect(self.chooseFolderRequested.emit)
        rescan_btn = QPushButton("Rescan")
        rescan_btn.clicked.connect(self.rescanFolderRequested.emit)
        btn_row.addWidget(choose_btn)
        btn_row.addWidget(rescan_btn)
        btn_row.addStretch()
        md_layout.addLayout(btn_row)

        self.md_folder_label = QLabel("No folder selected")
        self.md_folder_label.setStyleSheet("color: #8b949e; padding: 2px 8px;")
        md_layout.addWidget(self.md_folder_label)

        self.md_status_label = QLabel("")
        self.md_status_label.setStyleSheet("color: #8b949e; padding: 2px 8px;")
        md_layout.addWidget(self.md_status_label)

        self.markdown_list = QListWidget()
        self.markdown_list.itemClicked.connect(self._on_markdown_clicked)
        md_layout.addWidget(self.markdown_list)

        self.tabs.addTab(md_widget, "Markdown")
        layout.addWidget(self.tabs)

    def update_outline(self, headings: list[dict]):
        self.outline_list.clear()
        for h in headings:
            indent = "  " * (h["level"] - 1)
            item = QListWidgetItem(f"{indent}{h['title']}")
            item.setData(Qt.ItemDataRole.UserRole, h["line"])
            self.outline_list.addItem(item)

    def update_history(self, paths: list[Path]):
        self.history_list.clear()
        if not paths:
            item = QListWidgetItem("No recent files yet")
            item.setData(Qt.ItemDataRole.UserRole, None)
            self.history_list.addItem(item)
            return
        for p in paths:
            item = QListWidgetItem(f"{p.name}\n  {p}")
            item.setData(Qt.ItemDataRole.UserRole, str(p))
            self.history_list.addItem(item)

    def set_markdown_results(self, root, files, truncated, status):
        self.markdown_list.clear()
        self.md_folder_label.setText(str(root) if root else "No folder selected")
        self.md_status_label.setText(status)
        for f in files:
            if root:
                try:
                    rel = f.resolve().relative_to(root.resolve())
                    sub_text = str(rel)
                except ValueError:
                    sub_text = str(f)
            else:
                sub_text = str(f)
            item = QListWidgetItem(f"{f.name}\n  {sub_text}")
            item.setData(Qt.ItemDataRole.UserRole, str(f))
            self.markdown_list.addItem(item)

    def _on_outline_clicked(self, item):
        line = item.data(Qt.ItemDataRole.UserRole)
        if line is not None:
            self.jumpRequested.emit(line)

    def _on_history_clicked(self, item):
        path = item.data(Qt.ItemDataRole.UserRole)
        if path is not None:
            self.fileOpenRequested.emit(path)

    def _on_markdown_clicked(self, item):
        path = item.data(Qt.ItemDataRole.UserRole)
        if path is not None:
            self.fileOpenRequested.emit(path)


# ---------------------------------------------------------------------------
# Main viewer window
# ---------------------------------------------------------------------------

class Viewer(QMainWindow):
    def __init__(self, path: Path | None = None):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1140, 800)
        self._set_app_icon()

        self.current_path: Path | None = None
        self.is_untitled: bool = False
        self.theme = _detect_system_theme()
        self.mode: str = "preview"
        self.edit_view: str = "editor"
        self._live_timer = QTimer(self)
        self._live_timer.setSingleShot(True)
        self._live_timer.timeout.connect(self._render_live_preview)
        self._scroll_sync_timer = QTimer(self)
        self._scroll_sync_timer.setSingleShot(True)
        self._scroll_sync_timer.timeout.connect(self._do_scroll_sync)
        self._wordcount_timer = QTimer(self)
        self._wordcount_timer.setSingleShot(True)
        self._wordcount_timer.timeout.connect(self._update_wordcount)
        self._headings_cache: list[dict] = []
        self.typewriter_on = False
        self._history: list[tuple[Path, int]] = []
        self._history_idx: int = -1
        self._in_history_nav = False
        self.markdown_root: Path | None = None
        self.markdown_files: list[Path] = []
        self.markdown_scan_truncated: bool = False
        self._suppress_reload = False
        self._modified = False
        self._file_watcher = QFileSystemWatcher(self)
        self._file_watcher.fileChanged.connect(self._on_file_changed)

        self._build_web_bridge()
        self._build_webview()
        self._build_editor()
        self._build_outline_sidebar()
        self._build_find_bar()
        self._build_toolbar()
        self._build_menu_bar()
        self._build_layout()
        self._build_status_bar()
        self._setup_shortcuts()
        self.setAcceptDrops(True)

        self._refresh_history_sidebar()
        self._restore_markdown_sidebar_state()

        if path is not None:
            self.load_file(path)
        else:
            self._render_welcome()

        self._apply_theme_style()

    def _set_app_icon(self):
        icon_path = APP_DIR / "icon.png"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

    # ---- theme ---------------------------------------------------------------

    def _apply_theme_style(self):
        if self.theme == "dark":
            self.setStyleSheet("""
                QMainWindow { background: #0d1117; }
                QToolBar { background: #161b22; border-bottom: 1px solid #30363d;
                           spacing: 2px; padding: 2px 4px; }
                QToolBar QToolButton { color: #e6edf3; padding: 4px 6px;
                                       border-radius: 4px; }
                QToolBar QToolButton:hover { background: #30363d; }
                QToolBar QToolButton:checked { background: #2f81f7;
                                               color: white; }
                QMenuBar { background: #161b22; color: #e6edf3;
                           border-bottom: 1px solid #30363d; }
                QMenuBar::item:selected { background: #30363d; }
                QMenu { background: #1c2128; color: #e6edf3;
                        border: 1px solid #30363d; }
                QMenu::item:selected { background: #2f81f7; }
                QMenu::separator { background: #30363d; height: 1px; }
                QStatusBar { background: #161b22; color: #8b949e;
                             border-top: 1px solid #30363d; }
                QDockWidget { color: #e6edf3; }
                QDockWidget::title { background: #161b22; padding: 6px;
                                     border-bottom: 1px solid #30363d; }
                QSplitter::handle { background: #30363d; }
                QLineEdit { background: #0d1117; color: #e6edf3;
                            border: 1px solid #30363d; border-radius: 4px;
                            padding: 4px 8px; }
                QLabel { color: #e6edf3; }
                QPushButton { background: #21262d; color: #e6edf3;
                              border: 1px solid #30363d; border-radius: 4px;
                              padding: 4px 12px; }
                QPushButton:hover { background: #30363d; }
                QTabWidget::pane { border: none; background: #0d1117; }
                QTabBar::tab { background: #161b22; color: #8b949e;
                               padding: 6px 14px; border: none;
                               border-bottom: 2px solid transparent; }
                QTabBar::tab:selected { color: #e6edf3;
                                        border-bottom-color: #2f81f7; }
                QListWidget { background: #0d1117; color: #e6edf3;
                              border: none; outline: none; }
                QListWidget::item { padding: 4px 8px; }
                QListWidget::item:selected { background: #161b22; }
                QListWidget::item:hover { background: #161b22; }
            """)
            self.editor.setStyleSheet("""
                QPlainTextEdit { background: #0d1117; color: #e6edf3;
                                 selection-background-color: #264f78;
                                 border: none; }
            """)
        else:
            self.setStyleSheet("""
                QMainWindow { background: #ffffff; }
                QToolBar { background: #f6f8fa; border-bottom: 1px solid #d0d7de;
                           spacing: 2px; padding: 2px 4px; }
                QToolBar QToolButton { color: #1f2328; padding: 4px 6px;
                                       border-radius: 4px; }
                QToolBar QToolButton:hover { background: #d0d7de; }
                QToolBar QToolButton:checked { background: #0969da;
                                               color: white; }
                QMenuBar { background: #f6f8fa; color: #1f2328;
                           border-bottom: 1px solid #d0d7de; }
                QMenuBar::item:selected { background: #d0d7de; }
                QMenu { background: #ffffff; color: #1f2328;
                        border: 1px solid #d0d7de; }
                QMenu::item:selected { background: #0969da; color: white; }
                QMenu::separator { background: #d0d7de; height: 1px; }
                QStatusBar { background: #f6f8fa; color: #656d76;
                             border-top: 1px solid #d0d7de; }
                QDockWidget { color: #1f2328; }
                QDockWidget::title { background: #f6f8fa; padding: 6px;
                                     border-bottom: 1px solid #d0d7de; }
                QSplitter::handle { background: #d0d7de; }
                QLineEdit { background: #ffffff; color: #1f2328;
                            border: 1px solid #d0d7de; border-radius: 4px;
                            padding: 4px 8px; }
                QLabel { color: #1f2328; }
                QPushButton { background: #f6f8fa; color: #1f2328;
                              border: 1px solid #d0d7de; border-radius: 4px;
                              padding: 4px 12px; }
                QPushButton:hover { background: #d0d7de; }
                QTabWidget::pane { border: none; background: #ffffff; }
                QTabBar::tab { background: #f6f8fa; color: #656d76;
                               padding: 6px 14px; border: none;
                               border-bottom: 2px solid transparent; }
                QTabBar::tab:selected { color: #1f2328;
                                        border-bottom-color: #0969da; }
                QListWidget { background: #ffffff; color: #1f2328;
                              border: none; outline: none; }
                QListWidget::item { padding: 4px 8px; }
                QListWidget::item:selected { background: #f6f8fa; }
                QListWidget::item:hover { background: #f6f8fa; }
            """)
            self.editor.setStyleSheet("""
                QPlainTextEdit { background: #ffffff; color: #1f2328;
                                 selection-background-color: #b6e3ff;
                                 border: none; }
            """)

    def _toggle_theme(self):
        self.theme = "dark" if self.theme == "light" else "light"
        self._apply_theme_style()
        self._refresh_preview()

    # ---- web bridge ----------------------------------------------------------

    def _build_web_bridge(self):
        self._bridge = WebBridge(self)
        self._bridge.taskToggled.connect(self._apply_task_toggle)
        self._channel = QWebChannel(self)
        self._channel.registerObject("bridge", self._bridge)

    # ---- webview -------------------------------------------------------------

    def _build_webview(self):
        self.webview = QWebEngineView()
        page = self.webview.page()
        page.setWebChannel(self._channel)

    def _load_html(self, html: str, base_url: str = ""):
        if base_url:
            self.webview.setHtml(html, QUrl(base_url))
        else:
            self.webview.setHtml(html)

    # ---- editor --------------------------------------------------------------

    def _build_editor(self):
        self.editor = CodeEditor()
        self.editor.textChanged.connect(self._on_buffer_changed)
        self.editor.cursorPositionChanged.connect(self._on_cursor_position)

    def _buffer_text(self) -> str:
        return self.editor.toPlainText()

    def _load_editor_text(self, text: str):
        self.editor.blockSignals(True)
        self.editor.setPlainText(text)
        self.editor.blockSignals(False)
        self._modified = False
        self._update_title()

    # ---- outline sidebar -----------------------------------------------------

    def _build_outline_sidebar(self):
        self.sidebar = OutlineSidebar()
        self.sidebar_dock = QDockWidget("Outline", self)
        self.sidebar_dock.setWidget(self.sidebar)
        self.sidebar_dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea
            | Qt.DockWidgetArea.RightDockWidgetArea)
        self.sidebar_dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetClosable
            | QDockWidget.DockWidgetFeature.DockWidgetMovable)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea,
                           self.sidebar_dock)
        self.sidebar_dock.hide()

        self.sidebar.jumpRequested.connect(self._goto_line)
        self.sidebar.fileOpenRequested.connect(
            lambda p: self._open_sidebar_file(Path(p)))
        self.sidebar.chooseFolderRequested.connect(
            self._choose_markdown_folder)
        self.sidebar.rescanFolderRequested.connect(
            self._scan_markdown_folder)

    def _open_sidebar_file(self, path: Path):
        if not path.exists():
            self._render_error(f"File not found: {path}")
            return
        if not self._confirm_discard_if_dirty():
            return
        self.load_file(path)

    # ---- find bar ------------------------------------------------------------

    def _build_find_bar(self):
        self.find_bar = QWidget()
        self.find_bar.setVisible(False)
        layout = QHBoxLayout(self.find_bar)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(4)

        self.find_entry = QLineEdit()
        self.find_entry.setPlaceholderText("Find…")
        self.find_entry.textChanged.connect(self._on_find_changed)
        self.find_entry.returnPressed.connect(lambda: self._find_step(True))
        layout.addWidget(self.find_entry, 1)

        prev_btn = QPushButton("Prev")
        prev_btn.clicked.connect(lambda: self._find_step(False))
        layout.addWidget(prev_btn)

        next_btn = QPushButton("Next")
        next_btn.clicked.connect(lambda: self._find_step(True))
        layout.addWidget(next_btn)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(lambda: self._toggle_find(False))
        layout.addWidget(close_btn)

    def _toggle_find(self, on: bool):
        if on and self.mode != "edit":
            return
        self.find_bar.setVisible(on)
        if on:
            self.find_entry.setFocus()
            self.find_entry.selectAll()

    def _on_find_changed(self, text: str):
        if not text:
            return
        self._do_find(text, forward=True)

    def _find_step(self, forward: bool):
        text = self.find_entry.text()
        if not text:
            return
        self._do_find(text, forward=forward)

    def _do_find(self, text: str, forward: bool = True):
        flags = QTextCursor.MoveOperation.Start if forward else QTextCursor.MoveOperation.End
        doc = self.editor.document()
        cursor = self.editor.textCursor()
        if forward:
            found = doc.find(text, cursor)
        else:
            found = doc.find(text, cursor,
                             __import__("PyQt6.QtGui", fromlist=["QTextDocument"])
                             .QTextDocument.FindFlag.FindBackward)
        if found.isNull():
            # Wrap around
            cursor2 = QTextCursor(doc)
            if forward:
                cursor2.movePosition(QTextCursor.MoveOperation.Start)
            else:
                cursor2.movePosition(QTextCursor.MoveOperation.End)
            if forward:
                found = doc.find(text, cursor2)
            else:
                found = doc.find(text, cursor2,
                                 __import__("PyQt6.QtGui", fromlist=["QTextDocument"])
                                 .QTextDocument.FindFlag.FindBackward)
        if not found.isNull():
            self.editor.setTextCursor(found)
            self.editor.centerCursor()

    # ---- toolbar (edit mode) -------------------------------------------------

    def _build_toolbar(self):
        self.edit_toolbar = QToolBar("Edit")
        self.edit_toolbar.setIconSize(QSize(16, 16))
        self.edit_toolbar.setMovable(False)
        self.edit_toolbar.setVisible(False)
        self.addToolBar(self.edit_toolbar)

        self.edit_toolbar.addAction("New", self._on_new)
        self.edit_toolbar.addAction("Save", lambda: self._save())
        self.edit_toolbar.addSeparator()

        self.edit_toolbar.addAction("Undo", lambda: self.editor.undo())
        self.edit_toolbar.addAction("Redo", lambda: self.editor.redo())
        self.edit_toolbar.addSeparator()

        self.edit_toolbar.addAction(
            "Bold", lambda: self._wrap_selection("**", "**", "bold text"))
        self.edit_toolbar.addAction(
            "Italic", lambda: self._wrap_selection("*", "*", "italic text"))
        self.edit_toolbar.addAction(
            "Code", lambda: self._wrap_selection("`", "`", "code"))
        self.edit_toolbar.addAction("Link", self._insert_link)
        self.edit_toolbar.addSeparator()

        self.edit_toolbar.addAction(
            "H1", lambda: self._set_heading_level(1))
        self.edit_toolbar.addAction(
            "H2", lambda: self._set_heading_level(2))
        self.edit_toolbar.addAction(
            "H3", lambda: self._set_heading_level(3))
        self.edit_toolbar.addSeparator()

        self.edit_toolbar.addAction(
            "Bullet", lambda: self._prefix_line("- ", toggle=True))
        self.edit_toolbar.addAction(
            "Numbered", lambda: self._prefix_line("1. ", toggle=True))
        self.edit_toolbar.addAction(
            "Task", lambda: self._prefix_line("- [ ] ", toggle=True))
        self.edit_toolbar.addSeparator()

        # View mode toggle
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding,
                             QSizePolicy.Policy.Preferred)
        self.edit_toolbar.addWidget(spacer)

        self.wc_label = QLabel("")
        self.wc_label.setStyleSheet("color: #8b949e; padding: 0 8px;")
        self.edit_toolbar.addWidget(self.wc_label)

        self.view_editor_btn = QToolButton()
        self.view_editor_btn.setText("Editor")
        self.view_editor_btn.setCheckable(True)
        self.view_editor_btn.setChecked(True)
        self.view_editor_btn.clicked.connect(
            lambda: self._set_edit_view("editor"))
        self.edit_toolbar.addWidget(self.view_editor_btn)

        self.view_split_btn = QToolButton()
        self.view_split_btn.setText("Split")
        self.view_split_btn.setCheckable(True)
        self.view_split_btn.clicked.connect(
            lambda: self._set_edit_view("split"))
        self.edit_toolbar.addWidget(self.view_split_btn)

        self.view_preview_btn = QToolButton()
        self.view_preview_btn.setText("Preview")
        self.view_preview_btn.setCheckable(True)
        self.view_preview_btn.clicked.connect(
            lambda: self._set_edit_view("preview"))
        self.edit_toolbar.addWidget(self.view_preview_btn)

        self.edit_toolbar.addSeparator()
        find_btn = QToolButton()
        find_btn.setText("Find")
        find_btn.setCheckable(True)
        find_btn.clicked.connect(lambda checked: self._toggle_find(checked))
        self.edit_toolbar.addWidget(find_btn)

    # ---- menu bar ------------------------------------------------------------

    def _build_menu_bar(self):
        mb = self.menuBar()

        def add_menu_action(menu, text, slot, shortcut=None):
            action = QAction(text, self)
            if shortcut:
                action.setShortcut(QKeySequence(shortcut))
            action.triggered.connect(slot)
            menu.addAction(action)
            return action

        file_menu = mb.addMenu("&File")
        add_menu_action(file_menu, "Open…", self._on_open_clicked, "Ctrl+O")
        add_menu_action(file_menu, "New", self._on_new, "Ctrl+N")
        file_menu.addSeparator()
        add_menu_action(file_menu, "Save", lambda: self._save(), "Ctrl+S")
        add_menu_action(file_menu, "Save As…", lambda: self._save_as(), "Ctrl+Shift+S")
        file_menu.addSeparator()
        add_menu_action(file_menu, "Reload", lambda: self._reload(), "Ctrl+R")
        file_menu.addSeparator()
        add_menu_action(file_menu, "Quit", self.close, "Ctrl+Q")

        edit_menu = mb.addMenu("&Edit")
        add_menu_action(edit_menu, "Undo", lambda: self.editor.undo(), "Ctrl+Z")
        add_menu_action(edit_menu, "Redo", lambda: self.editor.redo(), "Ctrl+Shift+Z")
        edit_menu.addSeparator()
        add_menu_action(
            edit_menu,
            "Find…",
            lambda: self._toggle_find(not self.find_bar.isVisible()),
            "Ctrl+F",
        )
        add_menu_action(
            edit_menu,
            "Search in folder…",
            self._open_folder_search,
            "Ctrl+Shift+F",
        )
        edit_menu.addSeparator()
        add_menu_action(
            edit_menu,
            "Bold",
            lambda: self._wrap_selection("**", "**", "bold text"),
            "Ctrl+B",
        )
        add_menu_action(
            edit_menu,
            "Italic",
            lambda: self._wrap_selection("*", "*", "italic text"),
            "Ctrl+I",
        )
        add_menu_action(edit_menu, "Link", self._insert_link, "Ctrl+K")
        add_menu_action(
            edit_menu,
            "Heading 1",
            lambda: self._set_heading_level(1),
            "Ctrl+H",
        )

        view_menu = mb.addMenu("&View")
        add_menu_action(view_menu, "Toggle Edit Mode", self._toggle_edit, "Ctrl+E")
        add_menu_action(view_menu, "Toggle Outline", self._toggle_outline, "Ctrl+Shift+O")
        add_menu_action(
            view_menu,
            "Toggle Typewriter Mode",
            self._toggle_typewriter,
            "Ctrl+Shift+T",
        )
        add_menu_action(view_menu, "Toggle Theme", self._toggle_theme, "Ctrl+D")
        view_menu.addSeparator()
        add_menu_action(view_menu, "Command Palette…", self._open_palette, "Ctrl+P")

        help_menu = mb.addMenu("&Help")
        add_menu_action(help_menu, "Keyboard Shortcuts", self._show_shortcuts)
        add_menu_action(help_menu, f"What's New in {__version__}", self._show_whats_new)
        help_menu.addSeparator()
        add_menu_action(help_menu, "Documentation", lambda: self._open_url(WIKI_URL))
        add_menu_action(help_menu, "Report an Issue", lambda: self._open_url(ISSUES_URL))
        add_menu_action(help_menu, f"Visit {DEVELOPER}", lambda: self._open_url(WEBSITE))
        help_menu.addSeparator()
        add_menu_action(help_menu, f"About {APP_NAME}", self._show_about)

    # ---- layout --------------------------------------------------------------

    def _build_layout(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        main_layout.addWidget(self.find_bar)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(self.editor)
        self.splitter.addWidget(self.webview)
        main_layout.addWidget(self.splitter)

        self._refresh_content()

    def _build_status_bar(self):
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_path_label = QLabel("")
        self.status_pos_label = QLabel("")
        self.status_bar.addWidget(self.status_path_label, 1)
        self.status_bar.addPermanentWidget(self.status_pos_label)

    def _refresh_content(self):
        if self.mode == "preview":
            self.editor.hide()
            self.webview.show()
            self.edit_toolbar.setVisible(False)
            self.find_bar.setVisible(False)
        else:
            self.edit_toolbar.setVisible(True)
            if self.edit_view == "editor":
                self.editor.show()
                self.webview.hide()
            elif self.edit_view == "preview":
                self.editor.hide()
                self.webview.show()
            else:  # split
                self.editor.show()
                self.webview.show()
                w = self.splitter.width()
                if w > 0:
                    self.splitter.setSizes([w // 2, w // 2])

    # ---- shortcuts -----------------------------------------------------------

    def _setup_shortcuts(self):
        from PyQt6.QtGui import QShortcut
        QShortcut(QKeySequence("Alt+Left"), self, self._history_back)
        QShortcut(QKeySequence("Alt+Right"), self, self._history_forward)
        QShortcut(QKeySequence("Ctrl+Y"), self, lambda: self.editor.redo())

    # ---- drag and drop -------------------------------------------------------

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        urls = event.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            if path:
                self.load_file(Path(path))

    # ---- file open / reload --------------------------------------------------

    def _on_open_clicked(self):
        if not self._confirm_discard_if_dirty():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Open markdown file", "",
            "Markdown (*.md *.markdown *.mdown *.mkd *.txt);;All files (*)")
        if path:
            self.load_file(Path(path))

    def load_file(self, path: Path):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            self._render_error(f"Could not read {path}: {exc}")
            return
        if self.current_path and not self._in_history_nav:
            cur_line = self.editor.current_line_number() if self.mode == "edit" else 0
            self._history_push(self.current_path, cur_line)
        self.current_path = path
        self.is_untitled = False
        add_recent(path)
        self._refresh_history_sidebar()
        base_uri = path.parent.as_uri() + "/"
        self._load_html(render(text, self.theme, path.name, path.parent),
                        base_uri)
        self._load_editor_text(text)
        self._headings_cache = extract_headings(text)
        if self.sidebar_dock.isVisible():
            self.sidebar.update_outline(self._headings_cache)
        self._watch_file(path)
        self._update_title()
        self._schedule_wordcount()
        self.status_path_label.setText(str(path))

    def _watch_file(self, path: Path):
        files = self._file_watcher.files()
        if files:
            self._file_watcher.removePaths(files)
        if path.exists():
            self._file_watcher.addPath(str(path))

    def _on_file_changed(self, path_str: str):
        if self.mode == "edit":
            return
        if self._suppress_reload:
            return
        QTimer.singleShot(120, self._reload)

    def _reload(self):
        if self.current_path and self.current_path.exists():
            self.load_file(self.current_path)
        else:
            self._render_welcome()

    def _render_welcome(self):
        self._load_html(welcome_html(self.theme), APP_DIR.as_uri() + "/")
        self.current_path = None
        self.is_untitled = False
        self._headings_cache = []
        if self.sidebar_dock.isVisible():
            self.sidebar.update_outline([])
        self._update_title()
        self.wc_label.setText("")
        self.status_path_label.setText("")

    def _render_error(self, msg: str):
        md_text = f"# Error\n\n```\n{msg}\n```\n"
        self._load_html(render(md_text, self.theme, "Error", APP_DIR),
                        APP_DIR.as_uri() + "/")

    def _refresh_preview(self):
        if self.current_path and self.current_path.exists() and self.mode == "preview":
            self.load_file(self.current_path)
        elif self.mode == "edit":
            self._render_live_preview()
        else:
            self._render_welcome()

    # ---- edit mode + view switching ------------------------------------------

    def _toggle_edit(self):
        if self.mode == "preview":
            if not self.current_path and not self.is_untitled:
                return
            self.mode = "edit"
            self._refresh_content()
            if self.edit_view != "preview":
                self.editor.setFocus()
        else:
            if self._modified:
                if self.is_untitled or not self.current_path:
                    if not self._save_as():
                        return
                else:
                    self._save()
            self.mode = "preview"
            self._refresh_content()
            if self.current_path and self.current_path.exists():
                self.load_file(self.current_path)

    def _ensure_edit_mode(self):
        if not self.current_path and not self.is_untitled:
            self.is_untitled = True
        if self.mode != "edit":
            self.mode = "edit"
            self._refresh_content()

    def _set_edit_view(self, view: str):
        self.edit_view = view
        for btn, v in ((self.view_editor_btn, "editor"),
                       (self.view_split_btn, "split"),
                       (self.view_preview_btn, "preview")):
            btn.setChecked(v == view)
        if self.mode == "edit":
            self._refresh_content()
            if view in ("split", "preview"):
                self._render_live_preview()

    # ---- editor buffer & live preview ----------------------------------------

    def _on_buffer_changed(self):
        self._modified = True
        self._headings_cache = extract_headings(self._buffer_text())
        if self.sidebar_dock.isVisible():
            self.sidebar.update_outline(self._headings_cache)
        self._update_title()
        self._schedule_wordcount()
        if self.mode == "edit" and self.edit_view in ("split", "preview"):
            self._schedule_live_preview()

    def _schedule_live_preview(self):
        self._live_timer.start(LIVE_PREVIEW_DEBOUNCE_MS)

    def _render_live_preview(self):
        text = self._buffer_text()
        base = (self.current_path.parent if self.current_path else APP_DIR)
        title = self.current_path.name if self.current_path else "untitled.md"
        self._load_html(render(text, self.theme, title, base),
                        base.as_uri() + "/")

    def _schedule_wordcount(self):
        self._wordcount_timer.start(WORD_COUNT_DEBOUNCE_MS)

    def _update_wordcount(self):
        words, minutes = count_words_and_read_time(self._buffer_text())
        if words == 0:
            self.wc_label.setText("")
        else:
            self.wc_label.setText(f"{words} words \u00b7 {minutes} min read")

    def _update_title(self):
        if self.current_path or self.is_untitled:
            name = self.current_path.name if self.current_path else "untitled.md"
            dirty = " \u2022" if self._modified else ""
            self.setWindowTitle(f"{name}{dirty} \u2014 {APP_NAME}")
        else:
            self.setWindowTitle(APP_NAME)
        # Update status bar cursor position
        cursor = self.editor.textCursor()
        self.status_pos_label.setText(
            f"Ln {cursor.blockNumber() + 1}, Col {cursor.columnNumber() + 1}")

    # ---- scroll-sync ---------------------------------------------------------

    def _on_cursor_position(self):
        self._update_title()
        if self.typewriter_on and self.mode == "edit":
            self.editor.centerCursor()
        if self.mode == "edit" and self.edit_view == "split":
            self._scroll_sync_timer.start(SCROLL_SYNC_DEBOUNCE_MS)

    def _do_scroll_sync(self):
        if not self._headings_cache:
            return
        ln = self.editor.current_line_number()
        slug = None
        for h in self._headings_cache:
            if h["line"] <= ln:
                slug = h["slug"]
            else:
                break
        if slug:
            js = f"window.vertexWrite && window.vertexWrite.scrollToAnchor({json.dumps(slug)});"
            self.webview.page().runJavaScript(js)

    # ---- task toggle (JS bridge) ---------------------------------------------

    def _apply_task_toggle(self, line: int, checked: bool):
        if self.mode == "edit":
            text = self._buffer_text()
            lines = text.split("\n")
            if 0 <= line < len(lines):
                new_line = toggle_task_line(lines[line], checked)
                if new_line and new_line != lines[line]:
                    lines[line] = new_line
                    cursor = self.editor.textCursor()
                    pos = cursor.position()
                    self.editor.blockSignals(True)
                    self.editor.setPlainText("\n".join(lines))
                    cursor = self.editor.textCursor()
                    cursor.setPosition(min(pos, len(self.editor.toPlainText())))
                    self.editor.setTextCursor(cursor)
                    self.editor.blockSignals(False)
                    self._modified = True
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
            new_line = toggle_task_line(lines[line], checked)
            if new_line is None or new_line == lines[line]:
                return
            lines[line] = new_line
            try:
                self._suppress_reload = True
                self.current_path.write_text("\n".join(lines),
                                             encoding="utf-8")
                QTimer.singleShot(1000,
                                  lambda: setattr(self, '_suppress_reload', False))
            except OSError:
                return
            self._reload()

    # ---- smart paste + smart list + block move -------------------------------

    def keyPressEvent(self, event):
        if self.mode == "edit" and self.editor.hasFocus():
            ctrl = event.modifiers() & Qt.KeyboardModifier.ControlModifier
            alt = event.modifiers() & Qt.KeyboardModifier.AltModifier
            shift = event.modifiers() & Qt.KeyboardModifier.ShiftModifier

            if event.key() == Qt.Key.Key_V and ctrl and not shift and not alt:
                if self._smart_paste():
                    return

            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not ctrl and not alt:
                if self._smart_newline():
                    return

            if event.key() == Qt.Key.Key_Up and alt and not ctrl:
                self._move_lines(-1)
                return
            if event.key() == Qt.Key.Key_Down and alt and not ctrl:
                self._move_lines(1)
                return

        super().keyPressEvent(event)

    def _smart_paste(self) -> bool:
        clipboard = QApplication.clipboard()
        mime = clipboard.mimeData()

        if mime.hasHtml():
            html_text = mime.html()
            if html_text.strip():
                md = html_to_markdown(html_text)
                if md.strip():
                    self._insert_text(md + "\n")
                    return True

        text = clipboard.text()
        if text:
            sep, ok = looks_like_csv(text)
            if ok:
                self._insert_text(csv_to_markdown_table(text, sep))
                return True
        return False

    def _smart_newline(self) -> bool:
        line_text = self.editor.current_line_text()
        m_bullet = LIST_BULLET_RE.match(line_text)
        m_ord = LIST_ORDERED_RE.match(line_text)

        # Empty bullet/task/numbered: exit list
        if m_bullet and not m_bullet.group(4).strip():
            cursor = self.editor.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
            cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock,
                                QTextCursor.MoveMode.KeepAnchor)
            cursor.removeSelectedText()
            cursor.insertText("\n")
            return True
        if m_ord and not m_ord.group(3).strip():
            cursor = self.editor.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
            cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock,
                                QTextCursor.MoveMode.KeepAnchor)
            cursor.removeSelectedText()
            cursor.insertText("\n")
            return True

        # Continue list
        if m_bullet:
            indent, marker, task, _content = m_bullet.groups()
            next_marker = f"{indent}{marker} "
            if task is not None:
                next_marker += "[ ] "
            self.editor.textCursor().insertText("\n" + next_marker)
            return True
        if m_ord:
            indent, num, _content = m_ord.groups()
            try:
                nxt = int(num) + 1
            except ValueError:
                nxt = 1
            self.editor.textCursor().insertText(f"\n{indent}{nxt}. ")
            return True
        return False

    def _move_lines(self, delta: int):
        cursor = self.editor.textCursor()
        cursor.beginEditBlock()

        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        start_block = cursor.blockNumber()

        if cursor.hasSelection():
            end_pos = cursor.selectionEnd()
            cursor.setPosition(end_pos)
        end_block = cursor.blockNumber()

        doc = self.editor.document()
        total = doc.blockCount()
        if delta < 0 and start_block == 0:
            cursor.endEditBlock()
            return
        if delta > 0 and end_block >= total - 1:
            cursor.endEditBlock()
            return

        # Select entire block range
        cursor.setPosition(
            doc.findBlockByNumber(start_block).position())
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        for _ in range(end_block - start_block):
            cursor.movePosition(QTextCursor.MoveOperation.Down,
                                QTextCursor.MoveMode.KeepAnchor)
        cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock,
                            QTextCursor.MoveMode.KeepAnchor)
        block_text = cursor.selectedText()

        if delta < 0:
            # Select block + previous line
            cursor.setPosition(
                doc.findBlockByNumber(start_block - 1).position())
            cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
            for _ in range(end_block - start_block + 1):
                cursor.movePosition(QTextCursor.MoveOperation.Down,
                                    QTextCursor.MoveMode.KeepAnchor)
            cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock,
                                QTextCursor.MoveMode.KeepAnchor)
            prev_block = doc.findBlockByNumber(start_block - 1)
            prev_text = prev_block.text()
            cursor.removeSelectedText()
            cursor.insertText(
                block_text + "\n" + prev_text)
        else:
            # Select block + next line
            cursor.setPosition(
                doc.findBlockByNumber(start_block).position())
            cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
            for _ in range(end_block - start_block + 1):
                cursor.movePosition(QTextCursor.MoveOperation.Down,
                                    QTextCursor.MoveMode.KeepAnchor)
            cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock,
                                QTextCursor.MoveMode.KeepAnchor)
            next_block = doc.findBlockByNumber(end_block + 1)
            next_text = next_block.text()
            cursor.removeSelectedText()
            cursor.insertText(
                next_text + "\n" + block_text)

        cursor.endEditBlock()

    # ---- back/forward navigation ---------------------------------------------

    def _history_push(self, path: Path, line: int):
        if not path:
            return
        entry = (path, max(0, int(line or 0)))
        if (self._history and self._history_idx >= 0
                and self._history[self._history_idx] == entry):
            return
        self._history = self._history[:self._history_idx + 1]
        self._history.append(entry)
        self._history_idx = len(self._history) - 1
        if len(self._history) > 100:
            drop = len(self._history) - 100
            self._history = self._history[drop:]
            self._history_idx -= drop

    def _history_back(self):
        if self._history_idx <= 0:
            return
        if self.current_path:
            cur_line = (self.editor.current_line_number()
                        if self.mode == "edit" else 0)
            if (self._history_idx >= len(self._history)
                    or self._history[self._history_idx]
                    != (self.current_path, cur_line)):
                self._history_push(self.current_path, cur_line)
        self._history_idx -= 1
        self._navigate_to(*self._history[self._history_idx])

    def _history_forward(self):
        if self._history_idx + 1 >= len(self._history):
            return
        self._history_idx += 1
        self._navigate_to(*self._history[self._history_idx])

    def _navigate_to(self, path: Path, line: int):
        if not path.exists():
            return
        self._in_history_nav = True
        try:
            self.load_file(path)
            if line > 0:
                QTimer.singleShot(50, lambda: self._goto_line(line))
        finally:
            self._in_history_nav = False

    # ---- typewriter mode -----------------------------------------------------

    def _toggle_typewriter(self):
        self.typewriter_on = not self.typewriter_on
        if self.typewriter_on and self.mode == "edit":
            self.editor.centerCursor()

    # ---- command palette + actions -------------------------------------------

    def _open_palette(self):
        palette = CommandPalette(
            self,
            provider=self._palette_items,
            on_select=self._palette_select,
            placeholder="Jump to file, heading, or action\u2026")
        palette.exec()

    def _open_folder_search(self):
        base = (self.current_path.parent if self.current_path
                else Path.cwd())
        palette = CommandPalette(
            self,
            provider=lambda q: self._folder_search_items(base, q),
            on_select=self._palette_select,
            placeholder=f"Search {base} \u2026",
            min_query_chars=2)
        palette.exec()

    def _palette_items(self, q: str):
        ql = (q or "").lower().strip()
        items = []
        actions = [
            ("Open file\u2026", "Ctrl+O", "action:open"),
            ("New document", "Ctrl+N", "action:new"),
            ("Save", "Ctrl+S", "action:save"),
            ("Save As\u2026", "Ctrl+Shift+S", "action:save_as"),
            ("Toggle edit mode", "Ctrl+E", "action:edit"),
            ("Editor only", "", "action:editor_only"),
            ("Split view (live preview)", "", "action:split"),
            ("Preview only", "", "action:preview_only"),
            ("Toggle outline sidebar", "Ctrl+Shift+O", "action:outline"),
            ("Toggle typewriter mode", "Ctrl+Shift+T", "action:typewriter"),
            ("Reload", "Ctrl+R", "action:reload"),
            ("Toggle theme", "Ctrl+D", "action:theme"),
            ("Search in folder\u2026", "Ctrl+Shift+F", "action:folder_search"),
            ("Open from URL\u2026", "", "action:open_url"),
            ("Insert table\u2026", "", "action:insert_table"),
            ("Show all tasks in folder\u2026", "", "action:tasks"),
            ("Show backlinks to this file", "", "action:backlinks"),
            ("Check links in current buffer", "", "action:link_check"),
            ("View snapshot history\u2026", "", "action:snapshots"),
            ("Export as PDF (via pandoc)", "", "action:export_pdf"),
            ("Export as DOCX (via pandoc)", "", "action:export_docx"),
            ("Export as HTML (via pandoc)", "", "action:export_html"),
            ("Export as EPUB (via pandoc)", "", "action:export_epub"),
            (f"What's New in {__version__}", "", "action:whats_new"),
            ("Keyboard Shortcuts", "", "action:shortcuts"),
            (f"About {APP_NAME}", "", "action:about"),
            (f"Visit {DEVELOPER} website", "", "action:website"),
            ("Open Documentation", "", "action:docs"),
            ("Report an Issue", "", "action:issues"),
        ]
        for label, sub, key in actions:
            items.append({"label": label, "sub": sub, "key": key})

        src = ""
        if self.mode == "edit":
            src = self._buffer_text()
        elif self.current_path and self.current_path.exists():
            try:
                src = self.current_path.read_text(encoding="utf-8")
            except OSError:
                pass
        for h in extract_headings(src):
            items.append({
                "label": ("#" * h["level"]) + " " + h["title"],
                "sub": f"heading \u00b7 line {h['line'] + 1}",
                "key": f"heading:{h['line']}",
            })

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
                items.append({
                    "label": f.name,
                    "sub": f"file \u00b7 {rel}",
                    "key": f"file:{f}",
                })

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
            if any(part in MARKDOWN_SKIP_DIRS for part in f.parts):
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
                        snip = snip[:140] + "\u2026"
                    results.append({
                        "label": snip or "(empty line match)",
                        "sub": f"{rel}:{i + 1}",
                        "key": f"file_line:{f}:{i}",
                    })
                    if len(results) >= SEARCH_RESULT_CAP:
                        return results
        return results

    def _palette_select(self, key: str):
        if key is None:
            return
        if key.startswith("action:"):
            name = key[len("action:"):]
            dispatch = {
                "open": self._on_open_clicked,
                "new": self._on_new,
                "save": lambda: self._save(),
                "save_as": lambda: self._save_as(),
                "edit": self._toggle_edit,
                "reload": self._reload,
                "theme": self._toggle_theme,
                "folder_search": self._open_folder_search,
                "outline": self._toggle_outline,
                "typewriter": self._toggle_typewriter,
                "open_url": self._open_from_url_prompt,
                "insert_table": self._insert_table_prompt,
                "tasks": self._show_tasks_palette,
                "backlinks": self._show_backlinks_palette,
                "link_check": self._link_integrity_palette,
                "snapshots": self._snapshot_palette,
                "export_pdf": lambda: self._pandoc_export("pdf"),
                "export_docx": lambda: self._pandoc_export("docx"),
                "export_html": lambda: self._pandoc_export("html"),
                "export_epub": lambda: self._pandoc_export("epub"),
                "whats_new": self._show_whats_new,
                "shortcuts": self._show_shortcuts,
                "about": self._show_about,
                "website": lambda: self._open_url(WEBSITE),
                "docs": lambda: self._open_url(WIKI_URL),
                "issues": lambda: self._open_url(ISSUES_URL),
                "split": lambda: (self._ensure_edit_mode(),
                                  self._set_edit_view("split")),
                "editor_only": lambda: (self._ensure_edit_mode(),
                                        self._set_edit_view("editor")),
                "preview_only": lambda: (self._ensure_edit_mode(),
                                         self._set_edit_view("preview")),
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
            QTimer.singleShot(50, lambda: self._goto_line(int(line_str)))
            return
        if key.startswith("snapshot:"):
            p = Path(key[len("snapshot:"):])
            if p.exists():
                self._show_snapshot_preview(p)
            return

    def _goto_line(self, line: int):
        self._ensure_edit_mode()
        if self.edit_view == "preview":
            self._set_edit_view("editor")
        block = self.editor.document().findBlockByNumber(line)
        if block.isValid():
            cursor = QTextCursor(block)
            self.editor.setTextCursor(cursor)
            self.editor.centerCursor()
            self.editor.setFocus()

    # ---- misc palette actions ------------------------------------------------

    def _open_from_url_prompt(self):
        url, ok = QInputDialog.getText(
            self, "Open from URL", "URL:",
            QLineEdit.EchoMode.Normal, "https://")
        if not ok or not url.strip():
            return
        url = url.strip()
        import urllib.request
        import urllib.error
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": f"{APP_NAME}/{__version__}"})
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
        self.current_path = None
        self.is_untitled = True
        self._headings_cache = extract_headings(text)
        self._load_editor_text(text)
        title = url.rsplit("/", 1)[-1] or url
        self.setWindowTitle(f"{title} (fetched) \u2014 {APP_NAME}")
        self._load_html(render(text, self.theme, title, APP_DIR),
                        APP_DIR.as_uri() + "/")

    def _insert_table_prompt(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Insert table")
        layout = QGridLayout(dialog)
        layout.addWidget(QLabel("Rows:"), 0, 0)
        rows_spin = QSpinBox()
        rows_spin.setRange(1, 40)
        rows_spin.setValue(3)
        layout.addWidget(rows_spin, 0, 1)
        layout.addWidget(QLabel("Columns:"), 1, 0)
        cols_spin = QSpinBox()
        cols_spin.setRange(1, 20)
        cols_spin.setValue(3)
        layout.addWidget(cols_spin, 1, 1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons, 2, 0, 1, 2)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        rv = rows_spin.value()
        cv = cols_spin.value()
        header = "| " + " | ".join(f"Col {i + 1}" for i in range(cv)) + " |"
        sep = "| " + " | ".join(["---"] * cv) + " |"
        body = "\n".join(
            "| " + " | ".join([""] * cv) + " |" for _ in range(rv))
        self._insert_text(f"\n{header}\n{sep}\n{body}\n")

    def _show_tasks_palette(self):
        base = self.current_path.parent if self.current_path else Path.cwd()

        def provider(q):
            q = (q or "").lower().strip()
            items = []
            try:
                files = sorted(base.rglob("*.md"))
            except OSError:
                files = []
            for f in files:
                if any(part in MARKDOWN_SKIP_DIRS for part in f.parts):
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
                    status = "\u2611" if box.lower() == "x" else "\u2610"
                    label = f"{status} {content.strip()}"
                    if q and q not in label.lower() and q not in str(f).lower():
                        continue
                    try:
                        rel = f.relative_to(base)
                    except ValueError:
                        rel = f
                    items.append({
                        "label": label,
                        "sub": f"{rel}:{i + 1}",
                        "key": f"file_line:{f}:{i}",
                    })
                    if len(items) >= SEARCH_RESULT_CAP:
                        return items
            return items or [
                {"label": "No tasks found", "sub": str(base), "key": None}]

        palette = CommandPalette(
            self, provider=provider, on_select=self._palette_select,
            placeholder=f"Tasks in {base} \u2026")
        palette.exec()

    def _show_backlinks_palette(self):
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
                if any(part in MARKDOWN_SKIP_DIRS for part in f.parts):
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
                            if (f.parent / ref).resolve() == target_abs:
                                matched = True
                                break
                        except (OSError, ValueError):
                            pass
                    if not matched:
                        for m in WIKI_LINK_RE.finditer(line):
                            nm = m.group(1).strip()
                            if nm in (target_stem, target_name):
                                matched = True
                                break
                    if not matched:
                        continue
                    snip = line.strip()
                    if len(snip) > 140:
                        snip = snip[:140] + "\u2026"
                    try:
                        rel = f.relative_to(base)
                    except ValueError:
                        rel = f
                    if q and q not in snip.lower() and q not in str(rel).lower():
                        continue
                    results.append({
                        "label": snip,
                        "sub": f"{rel}:{i + 1}",
                        "key": f"file_line:{f}:{i}",
                    })
            return results or [{"label": "No backlinks found",
                                "sub": str(target_name), "key": None}]

        palette = CommandPalette(
            self, provider=provider, on_select=self._palette_select,
            placeholder=f"Backlinks to {target_name} \u2026")
        palette.exec()

    def _link_integrity_palette(self):
        base = self.current_path.parent if self.current_path else Path.cwd()
        source = self._buffer_text() if self.mode == "edit" else (
            self.current_path.read_text(encoding="utf-8")
            if self.current_path else "")
        issues = []
        for i, line in enumerate(source.split("\n")):
            for m in MD_LINK_RE.finditer(line):
                url = m.group(3).strip()
                if url.startswith(
                        ("#", "mailto:", "tel:", "http://", "https://", "data:")):
                    continue
                target = (base / url.split("#", 1)[0]).resolve()
                if not target.exists():
                    issues.append({
                        "label": f"Missing: {url}",
                        "sub": f"line {i + 1} \u00b7 {line.strip()[:120]}",
                        "key": f"heading:{i}",
                    })
        if not issues:
            issues = [{
                "label": "All relative links resolve",
                "sub": f"scanned {len(source.splitlines())} lines",
                "key": None,
            }]

        def on_select(k):
            if k and k.startswith("heading:"):
                self._goto_line(int(k[len("heading:"):]))

        palette = CommandPalette(
            self,
            provider=lambda q: [
                it for it in issues
                if not (q or "").strip()
                or (q or "").lower() in it["label"].lower()
                or (q or "").lower() in (it.get("sub") or "").lower()
            ],
            on_select=on_select,
            placeholder="Link issues")
        palette.exec()

    def _snapshot_palette(self):
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
            items.append({
                "label": label, "sub": str(p), "key": f"snapshot:{p}"})

        palette = CommandPalette(
            self,
            provider=lambda q: [
                it for it in items
                if not q or q.lower() in it["label"].lower()
            ],
            on_select=self._palette_select,
            placeholder=f"Snapshots of {self.current_path.name}")
        palette.exec()

    def _show_snapshot_preview(self, snap: Path):
        try:
            text = snap.read_text(encoding="utf-8")
        except OSError as exc:
            self._render_error(f"Could not read {snap}: {exc}")
            return
        self.setWindowTitle(
            f"snapshot \u00b7 {snap.stem} \u2014 {APP_NAME}")
        self._load_html(
            render(text, self.theme, f"{snap.stem} (snapshot)", snap.parent),
            snap.parent.as_uri() + "/")

    def _pandoc_export(self, fmt: str):
        if not self.current_path and not self._modified:
            self._render_error("Open or save a document first.")
            return
        if not shutil.which("pandoc"):
            self._render_error(
                "pandoc is not installed.\n\n"
                "Download from: https://pandoc.org/installing.html")
            return
        if self.is_untitled or not self.current_path:
            if not self._save_as():
                return
        if self._modified:
            self._save()
        ext = {"pdf": "pdf", "docx": "docx", "html": "html", "epub": "epub"}[fmt]
        chosen, _ = QFileDialog.getSaveFileName(
            self, f"Export as {fmt.upper()}",
            str(self.current_path.with_suffix(f".{ext}")),
            f"{fmt.upper()} files (*.{ext})")
        if not chosen:
            return
        try:
            cmd = ["pandoc", str(self.current_path), "-o", chosen,
                   "--metadata", f"title={self.current_path.stem}"]
            if fmt == "pdf":
                cmd += ["--pdf-engine=xelatex"]
            res = subprocess.run(cmd, capture_output=True, text=True,
                                 timeout=120)
            if res.returncode != 0:
                self._render_error(
                    f"pandoc failed:\n\n{res.stderr or res.stdout}\n\n"
                    f"Command: {' '.join(shlex.quote(c) for c in cmd)}")
        except (OSError, subprocess.TimeoutExpired) as exc:
            self._render_error(f"Could not run pandoc: {exc}")

    # ---- file: new / save / save as ------------------------------------------

    def _on_new(self):
        if not self._confirm_discard_if_dirty():
            return
        self.current_path = None
        self.is_untitled = True
        self._load_editor_text("# Untitled\n\n")
        self._headings_cache = extract_headings("# Untitled\n\n")
        if self.sidebar_dock.isVisible():
            self.sidebar.update_outline(self._headings_cache)
        files = self._file_watcher.files()
        if files:
            self._file_watcher.removePaths(files)
        self.mode = "edit"
        self._refresh_content()
        if self.edit_view in ("split", "preview"):
            self._render_live_preview()
        self.status_path_label.setText("(unsaved)")

    def _save(self) -> bool:
        if self.mode != "edit" and not self._modified:
            return True
        if self.is_untitled or not self.current_path:
            return self._save_as()
        return self._write_to(self.current_path)

    def _save_as(self) -> bool:
        default_name = str(self.current_path) if self.current_path else "untitled.md"
        chosen, _ = QFileDialog.getSaveFileName(
            self, "Save markdown file", default_name,
            "Markdown (*.md);;All files (*)")
        if not chosen:
            return False
        p = Path(chosen)
        if not self._write_to(p):
            return False
        self.current_path = p
        self.is_untitled = False
        add_recent(p)
        self._refresh_history_sidebar()
        self._watch_file(p)
        self._update_title()
        self.status_path_label.setText(str(p))
        return True

    def _write_to(self, path: Path) -> bool:
        text = self._buffer_text()
        try:
            self._suppress_reload = True
            path.write_text(text, encoding="utf-8")
            QTimer.singleShot(1000,
                              lambda: setattr(self, '_suppress_reload', False))
        except OSError as exc:
            self._render_error(f"Could not write {path}: {exc}")
            return False
        self._modified = False
        self._update_title()
        write_snapshot(path, text)
        return True

    def _confirm_discard_if_dirty(self) -> bool:
        if not self._modified:
            return True
        reply = QMessageBox.question(
            self, "Unsaved changes",
            "You have unsaved changes. Save before continuing?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel)
        if reply == QMessageBox.StandardButton.Cancel:
            return False
        if reply == QMessageBox.StandardButton.Save:
            return self._save()
        return True

    def closeEvent(self, event):
        if self._confirm_discard_if_dirty():
            event.accept()
        else:
            event.ignore()

    # ---- text editing helpers ------------------------------------------------

    def _insert_text(self, text: str):
        if not self.editor.hasFocus():
            self.editor.setFocus()
        self.editor.textCursor().insertText(text)

    def _wrap_selection(self, left: str, right: str, placeholder: str):
        self._ensure_edit_mode()
        cursor = self.editor.textCursor()
        if cursor.hasSelection():
            sel = cursor.selectedText()
            cursor.insertText(f"{left}{sel}{right}")
        else:
            cursor.insertText(f"{left}{placeholder}{right}")
            cursor.movePosition(
                QTextCursor.MoveOperation.Left,
                QTextCursor.MoveMode.MoveAnchor, len(right))
            cursor.movePosition(
                QTextCursor.MoveOperation.Left,
                QTextCursor.MoveMode.KeepAnchor, len(placeholder))
            self.editor.setTextCursor(cursor)
        self.editor.setFocus()

    def _prefix_line(self, prefix: str, toggle: bool = False):
        self._ensure_edit_mode()
        cursor = self.editor.textCursor()
        cursor.beginEditBlock()
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock,
                            QTextCursor.MoveMode.KeepAnchor)
        text = cursor.selectedText()
        if toggle and text.startswith(prefix):
            cursor.insertText(text[len(prefix):])
        else:
            cursor.insertText(prefix + text)
        cursor.endEditBlock()
        self.editor.setFocus()

    def _set_heading_level(self, level: int):
        self._ensure_edit_mode()
        cursor = self.editor.textCursor()
        cursor.beginEditBlock()
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock,
                            QTextCursor.MoveMode.KeepAnchor)
        text = cursor.selectedText()
        stripped = re.sub(r"^#{1,6}\s+", "", text)
        new = (("#" * level) + " " if level > 0 else "") + stripped
        if new != text:
            cursor.insertText(new)
        cursor.endEditBlock()
        self.editor.setFocus()

    def _insert_link(self):
        self._ensure_edit_mode()
        cursor = self.editor.textCursor()
        if cursor.hasSelection():
            lbl = cursor.selectedText()
            cursor.insertText(f"[{lbl}](https://)")
        else:
            cursor.insertText("[text](https://)")

    # ---- sidebar helpers -----------------------------------------------------

    def _toggle_outline(self):
        visible = self.sidebar_dock.isVisible()
        self.sidebar_dock.setVisible(not visible)
        if not visible:
            self.sidebar.update_outline(self._headings_cache)

    def _refresh_history_sidebar(self):
        recents = [p for p in load_recents() if p.exists()]
        self.sidebar.update_history(recents[:RECENT_MAX])

    def _restore_markdown_sidebar_state(self):
        root = load_markdown_root()
        if root is None:
            self.sidebar.set_markdown_results(
                None, [], False, "Choose a folder to scan markdown files.")
            return
        self.markdown_root = root
        self._scan_markdown_folder()

    def _choose_markdown_folder(self):
        start = str(self.markdown_root) if self.markdown_root else ""
        chosen = QFileDialog.getExistingDirectory(
            self, "Choose markdown folder", start)
        if not chosen:
            return
        self.markdown_root = Path(chosen).resolve()
        save_markdown_root(self.markdown_root)
        self._scan_markdown_folder()

    def _scan_markdown_folder(self):
        self.markdown_files = []
        self.markdown_scan_truncated = False
        if self.markdown_root is None or not self.markdown_root.is_dir():
            self.sidebar.set_markdown_results(
                None, [], False, "Choose a folder to scan markdown files.")
            return
        root = self.markdown_root.resolve()
        try:
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = [
                    d for d in dirnames if d not in MARKDOWN_SKIP_DIRS]
                for name in filenames:
                    if Path(name).suffix.lower() not in MARKDOWN_EXTENSIONS:
                        continue
                    self.markdown_files.append(Path(dirpath) / name)
                    if len(self.markdown_files) >= MARKDOWN_SCAN_MAX:
                        self.markdown_scan_truncated = True
                        break
                if self.markdown_scan_truncated:
                    break
            self.markdown_files.sort(key=lambda p: str(p).lower())
        except OSError as exc:
            self.sidebar.set_markdown_results(
                root, [], False, f"Scan failed: {exc}")
            return
        count = len(self.markdown_files)
        status = (f"Showing first {count} files (scan limit reached)."
                  if self.markdown_scan_truncated
                  else f"Found {count} markdown files.")
        self.sidebar.set_markdown_results(
            root, self.markdown_files, self.markdown_scan_truncated, status)

    # ---- help menu actions ---------------------------------------------------

    def _open_url(self, url: str):
        QDesktopServices.openUrl(QUrl(url))

    def _show_about(self):
        QMessageBox.about(
            self, f"About {APP_NAME}",
            f"<h2>{APP_NAME}</h2>"
            f"<p>Version {__version__}</p>"
            f"<p>Minimal, modern markdown viewer + editor.</p>"
            f"<p>&copy; 2026 {DEVELOPER}</p>"
            f"<p>License: MIT</p>"
            f'<p><a href="{REPO_URL}">{REPO_URL}</a></p>')

    def _show_whats_new(self):
        import gzip
        candidates = [
            APP_DIR / "CHANGELOG.md",
            APP_DIR.parent / "CHANGELOG.md",
        ]
        text = None
        for cp in candidates:
            if not cp.exists():
                continue
            try:
                if cp.suffix == ".gz":
                    with gzip.open(cp, "rt", encoding="utf-8",
                                   errors="replace") as fh:
                        text = fh.read()
                else:
                    text = cp.read_text(encoding="utf-8", errors="replace")
                break
            except OSError:
                continue
        if text is None:
            text = f"# {APP_NAME} {__version__}\n\n(No CHANGELOG.md found.)"
        else:
            pat = re.compile(
                r"^## \[(?!Unreleased)([^\]]+)\][^\n]*$", re.MULTILINE)
            m = pat.search(text)
            if m:
                start = m.start()
                nxt = pat.search(text, m.end())
                end = nxt.start() if nxt else len(text)
                text = text[start:end].strip()
            else:
                text = (f"# {APP_NAME} {__version__}\n\n"
                        "No released entries found yet.")

        dialog = QDialog(self)
        dialog.setWindowTitle(f"What's new in {APP_NAME} {__version__}")
        dialog.resize(620, 560)
        layout = QVBoxLayout(dialog)
        web = QWebEngineView()
        web.setHtml(render(text, self.theme, "What's new", APP_DIR))
        layout.addWidget(web)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dialog.close)
        layout.addWidget(close_btn)
        dialog.exec()

    def _show_shortcuts(self):
        shortcuts = [
            ("File", [
                ("Ctrl+O", "Open file"),
                ("Ctrl+N", "New document"),
                ("Ctrl+S", "Save"),
                ("Ctrl+Shift+S", "Save As"),
                ("Ctrl+R", "Reload"),
                ("Ctrl+Q", "Quit"),
            ]),
            ("View", [
                ("Ctrl+E", "Toggle edit mode"),
                ("Ctrl+Shift+O", "Toggle outline sidebar"),
                ("Ctrl+Shift+T", "Toggle typewriter mode"),
                ("Ctrl+D", "Toggle theme"),
            ]),
            ("Navigation", [
                ("Ctrl+P", "Command palette"),
                ("Ctrl+F", "Find in buffer"),
                ("Ctrl+Shift+F", "Search in folder"),
                ("Alt+Left", "Back"),
                ("Alt+Right", "Forward"),
            ]),
            ("Editing", [
                ("Ctrl+Z", "Undo"),
                ("Ctrl+Shift+Z", "Redo"),
                ("Ctrl+V", "Smart paste"),
                ("Alt+Up", "Move line up"),
                ("Alt+Down", "Move line down"),
                ("Enter", "Smart list continuation"),
            ]),
            ("Formatting", [
                ("Ctrl+B", "Bold"),
                ("Ctrl+I", "Italic"),
                ("Ctrl+K", "Link"),
                ("Ctrl+H", "Heading 1"),
            ]),
        ]
        text = "# Keyboard Shortcuts\n\n"
        for group, items in shortcuts:
            text += f"## {group}\n\n"
            text += "| Shortcut | Action |\n| --- | --- |\n"
            for accel, label in items:
                text += f"| `{accel}` | {label} |\n"
            text += "\n"

        dialog = QDialog(self)
        dialog.setWindowTitle("Keyboard Shortcuts")
        dialog.resize(560, 520)
        layout = QVBoxLayout(dialog)
        web = QWebEngineView()
        web.setHtml(render(text, self.theme, "Shortcuts", APP_DIR))
        layout.addWidget(web)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dialog.close)
        layout.addWidget(close_btn)
        dialog.exec()


# ---------------------------------------------------------------------------
# App boot
# ---------------------------------------------------------------------------

def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog=APP_CLI,
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
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setOrganizationName(DEVELOPER)

    icon_path = APP_DIR / "icon.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    viewer = Viewer(path)
    viewer.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
