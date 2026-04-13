# Changelog

All notable changes to `markview` are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versioning follows [SemVer](https://semver.org/).

## [Unreleased]

## [0.1.0] — 2026-04-13

### Added
- Initial release: GTK3 + WebKit2 markdown viewer for Linux.
- Light/dark theme auto-detected from system, toggle with `Ctrl+D`.
- Syntax highlighting via Pygments.
- Live reload on file save (GIO file monitor).
- Drag-and-drop of `.md` files onto the window.
- Keyboard shortcuts: `Ctrl+O` open, `Ctrl+R` reload, `Ctrl+D` theme, `Ctrl+Q` quit.
- Markdown extensions: fenced code, tables, TOC, footnotes, admonitions, def lists, abbr.
- `install.sh` / `uninstall.sh` — user-local install with `.desktop` entry and PATH shim.
- Welcome screen when launched with no file argument.
