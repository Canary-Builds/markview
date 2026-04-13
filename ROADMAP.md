# Roadmap

Living document. Versions and scope shift; open an issue to push or pull items.

Legend: 🟢 done · 🟡 planned · 🟣 researching · ⚪ idea

## 0.5.0 — Core is done 🟢

See [CHANGELOG.md](CHANGELOG.md). Covers 24 of the ~26 features surveyed from the category — navigation, editing, preview extras, palette actions, craft, and persistence. All keyboard-activated, no new visible chrome.

---

## 0.6.0 — Intentionally-deferred-from-0.5 🟡

Targeting the six features that were deliberately held back in 0.5 to keep the release focused.

- 🟡 **Spell check** — GtkSpell3 integration when `gir1.2-gspell-1` is available; graceful fallback when not. Dictionary selection via palette.
- 🟡 **Structured front-matter UI** — detect YAML / TOML front matter, expose as a form dialog (keys + values + add/remove) from the palette. Raw text editing stays first-class.
- 🟡 **Outline drag-to-reorder** — `Gtk.TreeView` with DnD reorder; re-emits the section moves back into the buffer.
- 🟡 **Smart list continuation for nested lists** — handle `Tab` / `Shift+Tab` for indent/outdent, renumber ordered lists on reorder.
- 🟡 **Bundled KaTeX + Mermaid** — ship minified copies under `vendor/` so math/diagrams work offline. Fall back to CDN when the bundle is missing.
- 🟡 **Link integrity: URL reachability** — optional opt-in HEAD check for http(s) links alongside the existing relative-path check.

## 0.7.0 — Writer ergonomics 🟡

- 🟡 **Table editor** — dialog with a spreadsheet-like `Gtk.Grid`: add/remove rows and columns, per-column alignment, live markdown sync. Invoked from the palette or from a right-click over a markdown table.
- 🟡 **Grammar via LanguageTool** — local server mode (`languagetool-server.jar`) or hosted API; inline squiggles using `GtkTextTag`s and a margin mark.
- 🟡 **Distraction-free focus mode** — in addition to typewriter, dim non-current paragraphs via `GtkTextTag`s. Single toggle.
- 🟡 **Word-count breakdown** — `Ctrl+P` → "Document stats": characters, words, reading time, sentence count, longest paragraph, prose/code ratio.
- 🟡 **Snippets / templates** — user-defined templates under `~/.config/markview/templates/` surfaced in the palette (e.g. "Daily note", "Meeting").

## 0.8.0 — Modality 🟡

- 🟡 **Vim keybindings** — opt-in, normal/insert/visual/command modes. Implemented as a dedicated input handler that can be disabled entirely.
- 🟡 **Command-mode `:` buffer** — reachable even without the vim layer (`Ctrl+Shift+;`) for power-user commands.
- 🟣 **Multi-cursor** — `Ctrl+D` next-occurrence (reassigning current "toggle theme" shortcut), `Alt+Click` add cursor.

## 0.9.0 — Notes graph 🟡

- 🟡 **Persistent backlinks index** — background scan of the folder, cached in `~/.local/state/markview/index/<folder-hash>.sqlite`. Makes backlink + orphan queries O(1).
- 🟡 **Orphan / broken note report** — palette: "Show orphans", "Show broken references".
- 🟡 **Graph view** — a D3 / Cytoscape mini-graph in the preview pane for a selected root note.
- 🟣 **Tag index** — treat `#tag` outside code as tags; palette view of all tags + membership.

## 1.0.0 — Foundations 🟡

- 🟡 **GTK4 + libadwaita port** — matches modern Linux desktops; `Adw.TabView` for multi-document; `Adw.HeaderBar` with adaptive layout.
- 🟡 **Plugin API** — discover Python modules under `~/.config/markview/plugins/`; stable hook points for render post-processing, palette items, and toolbar additions.
- 🟡 **Accessibility audit** — focus order, screen-reader labels, high-contrast theme, keyboard-only coverage.
- 🟡 **Packaging** — Flatpak on Flathub, Ubuntu PPA maintenance, AUR `markview` (for Arch/Manjaro), Fedora COPR package, and a pip-installable wheel for `pip install markview` on systems with PyGObject.
- 🟡 **i18n** — gettext catalog, first pass of translations (contrib-driven).

## Post-1.0 — Stretch ⚪

- ⚪ **Local LLM assist** — summarise selection, rewrite tone, generate outline; local-first via ollama or llama.cpp, opt-in and clearly bounded.
- ⚪ **Markdown Language Server** integration (`marksman`) — hover previews on links, goto-definition for internal refs, completion for heading anchors and file paths.
- ⚪ **Collaborative editing** — CRDT (Yjs/Automerge) over an optional sync backend.
- ⚪ **PDF export without pandoc** — `WebKit2.PrintOperation` straight from the preview; styleable via `custom.css`.
- ⚪ **Mobile companion** — read-only Android/iOS viewer pointed at a synced folder.
- ⚪ **Clipper** — a browser extension + Python endpoint to save a webpage as clean markdown in a chosen folder.
- ⚪ **Encryption at rest** — age-based (or similar) per-file encryption with keyring integration.
- ⚪ **Versioned local history viewer** — diff-side-by-side between snapshots with a `difflib` renderer.

---

## Explicitly out of scope

- Cloud sync, accounts, or any network-mandatory feature.
- A plugin marketplace with its own server.
- Bundling all dependencies in a universal binary (GTK is a platform; Flatpak is the right answer).
- Becoming a block editor or outliner.

---

## How items move on this roadmap

1. **Idea → Researching**: an issue exists, design is sketched.
2. **Researching → Planned**: approach is agreed, assigned to a version bucket.
3. **Planned → Done**: ships in a tagged release; moves to [CHANGELOG.md](CHANGELOG.md).

Version buckets are approximate — features may hop if they grow or shrink in scope.
