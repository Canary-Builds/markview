# -*- mode: python ; coding: utf-8 -*-
import os
import glob

a = Analysis(
    ['markview_win.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('style.css', '.'),
        ('icon.png', '.'),
        ('icon-16.png', '.'),
        ('icon-32.png', '.'),
        ('icon-48.png', '.'),
        ('icon-64.png', '.'),
        ('icon-128.png', '.'),
        ('icon-256.png', '.'),
        ('markview_core.py', '.'),
        ('CHANGELOG.md', '.'),
    ],
    hiddenimports=[
        'markdown.extensions.fenced_code',
        'markdown.extensions.tables',
        'markdown.extensions.toc',
        'markdown.extensions.codehilite',
        'markdown.extensions.sane_lists',
        'markdown.extensions.footnotes',
        'markdown.extensions.attr_list',
        'markdown.extensions.md_in_html',
        'markdown.extensions.admonition',
        'markdown.extensions.def_list',
        'markdown.extensions.abbr',
        'pygments.styles.friendly',
        'pygments.lexers',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter', '_tkinter',
        'unittest',
        'test',
        'distutils',
        'pydoc_data',
        'setuptools',
    ],
    noarchive=False,
    optimize=1,
)

# ---------------------------------------------------------------------------
# Strip debug resources and unnecessary translations only.
# Do not prune Qt runtime DLLs heuristically; QtWebChannel/WebEngine
# dependencies shift across PyQt/Qt releases and aggressive filtering has
# already caused broken Windows bundles.
# ---------------------------------------------------------------------------
_EXCLUDE_PATTERNS = [
    # Debug resource packs (75+ MB)
    '**/qtwebengine_devtools_resources*',
    '**/*.debug.pak',
    '**/*.debug.bin',
    # Keep only English locale — remove all other webengine translations
    '**/qtwebengine_locales/[!e]*.pak',
    '**/qtwebengine_locales/e[!n]*.pak',
]

import fnmatch

def _should_exclude(name):
    normalized = name.replace('\\', '/')
    for pat in _EXCLUDE_PATTERNS:
        if fnmatch.fnmatch(normalized, pat):
            return True
    return False

a.binaries = [(n, p, t) for n, p, t in a.binaries if not _should_exclude(n)]
a.datas = [(n, p, t) for n, p, t in a.datas if not _should_exclude(n)]


def _ensure_required_qt_runtime(collected):
    required_suffixes = [
        'PyQt6/Qt6/bin/Qt6Qml.dll',
        'PyQt6/Qt6/bin/Qt6QmlModels.dll',
        'PyQt6/Qt6/bin/Qt6WebChannel.dll',
        'PyQt6/Qt6/bin/Qt6WebEngineCore.dll',
        'PyQt6/Qt6/bin/Qt6WebEngineWidgets.dll',
        'PyQt6/Qt6/bin/QtWebEngineProcess.exe',
        'PyQt6/QtWebChannel.pyd',
        'PyQt6/QtWebEngineCore.pyd',
        'PyQt6/QtWebEngineWidgets.pyd',
    ]
    normalized = [name.replace('\\', '/') for name, _, _ in collected]
    missing = [
        suffix for suffix in required_suffixes
        if not any(path.endswith(suffix) for path in normalized)
    ]
    if missing:
        raise SystemExit(
            'Windows Qt runtime pruning removed required files:\n  - '
            + '\n  - '.join(missing)
        )


_ensure_required_qt_runtime(a.binaries + a.datas)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='markview',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='markview.ico',
    version='version_info.txt',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='markview',
)
