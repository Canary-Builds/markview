# FAQ

### Why another markdown editor?

There are good ones (Typora, Obsidian, Marktext, Apostrophe, Ghostwriter) — most are either closed-source, Electron, or a full note database. markview is small, open-source, native, and intentionally scoped to *viewing and editing a single markdown file* with no sync, no database, and no tray daemon.

### Why GTK3 and not GTK4?

GTK3 + WebKit2 4.1 is everywhere on stock Linux desktops today. GTK4 + libadwaita is on the roadmap for 1.0 — see [ROADMAP.md](../../ROADMAP.md).

### Is it available on macOS or Windows?

Windows is supported and shipped from GitHub Releases as an installer. macOS is still not supported.

### Does it sync my notes?

No. It's a file editor. Point it at any folder — local, NFS, Syncthing, ownCloud, etc. Sync is the storage layer's job.

### Does it upload my files anywhere?

Only the KaTeX and Mermaid JavaScript libraries are fetched from `cdn.jsdelivr.net` per preview load. Your document content stays local and is never sent anywhere. Offline-mode bundled KaTeX/Mermaid are on the roadmap for 0.6.

### Can I use it without internet?

Yes — every feature *except* live math rendering and Mermaid diagrams works offline. Math will appear as raw source, diagrams as a code block. The preview still renders, search still works, the editor is fully functional.

### Why do I need `gir1.2-gtksource-4` when the editor is just text?

GtkSourceView gives us markdown syntax highlighting in the editor, line numbers, native undo/redo with a 500-level history, and the search context used by the find bar. A bare `GtkTextView` would force us to reimplement all of those.

### My system theme is dark but markview rendered the preview in light mode

Theme detection checks `gtk-application-prefer-dark-theme` then falls back to a string match in `gtk-theme-name`. Some themes don't trigger either. Use `Ctrl+D` to toggle.

### Where does "paste image" save files?

- When editing a saved document: `<doc-folder>/assets/image-YYYYMMDD-HHMMSS.png`, with a relative markdown link inserted.
- When editing an untitled buffer: `~/Pictures/markview/`, with an absolute link.

### Can I export to PDF without pandoc?

Not yet. `WebKit2.PrintOperation` → PDF is planned for post-1.0 — see ROADMAP.

### How do I browse the snapshot history?

`Ctrl+P` → "View snapshot history". Latest 30 per document. Files live under `~/.local/state/markview/snapshots/`.

### Can I change the keyboard shortcuts?

Not at runtime. Edit `_setup_shortcuts` in `markview.py` and re-launch. A user-editable keymap is on the roadmap.

### Is there a JSON/YAML config file?

No. Drop-in files (`custom.css`) and environment variables (standard XDG ones) cover the configurable surface. See [Configuration](Configuration.md).

### Does the command palette support fuzzy matching?

Substring for now, case-insensitive, over both the label and the subtitle. Real fuzzy (score + typo tolerance) is a small change if there's appetite — open an issue.

### Can I have multiple windows / tabs?

One document per window, one window per launch (`NON_UNIQUE` application). Multiple tabs will land with the GTK4 + libadwaita port (1.0).

### Does it handle very large files?

The editor and renderer scale roughly linearly with document size. Anything under ~2 MB of markdown should be snappy. Much larger files may stutter on split-view live preview (the whole doc re-renders on each keystroke after the debounce); flip to Editor-only while working.

### Why do some of my `[ ]` checkboxes not render as clickable?

Task preprocessing requires a list-item prefix: `- [ ]`, `* [ ]`, `+ [ ]`, or `1. [ ]`. `[ ]` on its own isn't a task in markview's dialect. Also: task syntax inside fenced code blocks is intentionally not rewritten.
