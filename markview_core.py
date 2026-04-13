#!/usr/bin/env python3
"""Core markdown/render/snapshot helpers for markview.

This module is intentionally GTK-free so core behavior can be tested and reused
without pulling UI dependencies into the import graph.
"""

import datetime
import hashlib
import html as html_mod
import re
from html.parser import HTMLParser
from pathlib import Path

import markdown
from markdown.extensions.toc import slugify
from pygments.formatters import HtmlFormatter

try:
    import html2text as _html2text  # type: ignore
except Exception:
    _html2text = None

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

TASK_LINE_RE = re.compile(r"^(\s*(?:[-*+]|\d+\.)\s+)\[([ xX])\]\s+(.*)$")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
FENCE_RE = re.compile(r"^\s*```")
LIST_BULLET_RE = re.compile(r"^(\s*)([-*+])\s+(\[[ xX]\]\s+)?(.*)$")
LIST_ORDERED_RE = re.compile(r"^(\s*)(\d+)\.\s+(.*)$")
TRANSCLUDE_RE = re.compile(
    r"^(\s*)!\[\[([^\]|#]+?)(?:#([^\]|]+))?(?:\|[^\]]*)?\]\]\s*$"
)
MD_LINK_RE = re.compile(r"(!?)\[([^\]]*)\]\(([^)]+)\)")
WIKI_LINK_RE = re.compile(r"\[\[([^\]|#]+?)(?:#[^\]|]+)?(?:\|[^\]]*)?\]\]")


class _HtmlToMd(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self._list_stack: list[tuple[str, int]] = []
        self._href: str | None = None
        self._alt: str | None = None
        self._src: str | None = None
        self._in_pre = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.out.append("\n\n" + "#" * int(tag[1]) + " ")
        elif tag == "p":
            self.out.append("\n\n")
        elif tag == "br":
            self.out.append("  \n")
        elif tag in ("strong", "b"):
            self.out.append("**")
        elif tag in ("em", "i"):
            self.out.append("*")
        elif tag == "code" and not self._in_pre:
            self.out.append("`")
        elif tag == "pre":
            self._in_pre = True
            self.out.append("\n\n```\n")
        elif tag == "blockquote":
            self.out.append("\n> ")
        elif tag == "hr":
            self.out.append("\n\n---\n\n")
        elif tag == "a":
            self._href = a.get("href", "")
            self.out.append("[")
        elif tag == "img":
            self._alt = a.get("alt", "")
            self._src = a.get("src", "")
            self.out.append(f"![{self._alt}]({self._src})")
        elif tag == "ul":
            self._list_stack.append(("ul", 0))
        elif tag == "ol":
            self._list_stack.append(("ol", 1))
        elif tag == "li" and self._list_stack:
            kind, counter = self._list_stack[-1]
            indent = "  " * (len(self._list_stack) - 1)
            if kind == "ol":
                self.out.append(f"\n{indent}{counter}. ")
                self._list_stack[-1] = ("ol", counter + 1)
            else:
                self.out.append(f"\n{indent}- ")

    def handle_endtag(self, tag):
        if tag in ("strong", "b"):
            self.out.append("**")
        elif tag in ("em", "i"):
            self.out.append("*")
        elif tag == "code" and not self._in_pre:
            self.out.append("`")
        elif tag == "pre":
            self._in_pre = False
            self.out.append("\n```\n")
        elif tag == "a" and self._href is not None:
            self.out.append(f"]({self._href})")
            self._href = None
        elif tag in ("ul", "ol") and self._list_stack:
            self._list_stack.pop()

    def handle_data(self, data):
        self.out.append(data)

    def result(self) -> str:
        text = "".join(self.out)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        return text


def html_to_markdown(html_text: str) -> str:
    if _html2text is not None:
        conv = _html2text.HTML2Text()
        conv.body_width = 0
        return conv.handle(html_text).strip()
    parser = _HtmlToMd()
    parser.feed(html_text)
    return parser.result()


def preprocess_tasks(text: str) -> str:
    in_fence = False
    out = []
    for i, line in enumerate(text.split("\n")):
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


def preprocess_transclusions(
    text: str,
    current_dir: Path | None,
    depth: int = 0,
) -> str:
    """Resolve `![[other.md]]` / `![[other.md#Section]]` by inlining targets."""
    if depth > 4 or current_dir is None:
        return text
    in_fence = False
    out = []
    for line in text.split("\n"):
        if FENCE_RE.match(line):
            in_fence = not in_fence
            out.append(line)
            continue
        if in_fence:
            out.append(line)
            continue
        m = TRANSCLUDE_RE.match(line)
        if not m:
            out.append(line)
            continue
        indent, target, anchor = m.groups()
        candidates = [current_dir / target, current_dir / f"{target}.md"]
        loaded = None
        for c in candidates:
            if c.is_file():
                try:
                    loaded = c.read_text(encoding="utf-8")
                except OSError:
                    loaded = None
                break
        if loaded is None:
            out.append(f"{indent}> *transclusion target not found: {target}*")
            continue
        if anchor:
            loaded = _extract_section(loaded, anchor)
        loaded = preprocess_transclusions(
            loaded,
            candidates[0].parent if candidates else current_dir,
            depth + 1,
        )
        out.append(loaded)
    return "\n".join(out)


def _extract_section(text: str, anchor: str) -> str:
    slug_target = slugify(anchor, "-")
    lines = text.split("\n")
    start = None
    start_level = None
    for i, line in enumerate(lines):
        m = HEADING_RE.match(line)
        if m and slugify(m.group(2).strip(), "-") == slug_target:
            start = i + 1
            start_level = len(m.group(1))
            break
    if start is None:
        return f"> *section not found: #{anchor}*"
    end = len(lines)
    for j in range(start, len(lines)):
        m = HEADING_RE.match(lines[j])
        if m and len(m.group(1)) <= (start_level or 6):
            end = j
            break
    return "\n".join(lines[start:end]).strip()


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
            results.append(
                {
                    "line": i,
                    "level": level,
                    "title": title,
                    "slug": slugify(title, "-"),
                }
            )
    return results


def toggle_task_line(line: str, checked: bool) -> str | None:
    m = TASK_LINE_RE.match(line)
    if not m:
        return None
    indent, _, content = m.groups()
    return f"{indent}[{'x' if checked else ' '}] {content}"


def load_style(style_path: Path, custom_css_path: Path) -> str:
    base = ""
    try:
        base = style_path.read_text(encoding="utf-8")
    except OSError:
        pass

    custom = ""
    try:
        if custom_css_path.exists():
            custom = custom_css_path.read_text(encoding="utf-8")
    except OSError:
        pass

    return base + ("\n/* custom.css */\n" + custom if custom else "")


def pygments_css(theme: str) -> str:
    style = "github-dark" if theme == "dark" else "friendly"
    try:
        return HtmlFormatter(style=style).get_style_defs(".codehilite")
    except Exception:
        return HtmlFormatter().get_style_defs(".codehilite")


def _js_bridge(theme: str) -> str:
    mermaid_theme = "dark" if theme == "dark" else "default"
    return f"""
(function(){{
  window.markview = window.markview || {{}};
  window.markview.scrollToAnchor = function(slug){{
    if (!slug) return;
    var el = document.getElementById(slug);
    if (el) el.scrollIntoView({{block:'start', behavior:'auto'}});
  }};
  var post = function(payload){{
    try {{ window.webkit.messageHandlers.markview.postMessage(JSON.stringify(payload)); }}
    catch(e){{}}
  }};
  document.querySelectorAll('input.mv-task').forEach(function(el){{
    el.disabled = false; el.style.cursor='pointer';
    el.addEventListener('click', function(ev){{
      ev.preventDefault();
      var line = parseInt(el.getAttribute('data-task-line'), 10);
      el.checked = !el.checked;
      post({{type:'task_toggle', line: line, checked: el.checked}});
    }});
  }});
  document.querySelectorAll('pre code.language-mermaid').forEach(function(c, i){{
    var div = document.createElement('div');
    div.className = 'mermaid';
    div.textContent = c.textContent;
    c.parentNode.parentNode.replaceChild(div, c.parentNode);
  }});
  if (window.mermaid) {{
    try {{ mermaid.initialize({{startOnLoad:false, theme:'{mermaid_theme}', securityLevel:'loose'}}); mermaid.run(); }}
    catch(e){{}}
  }}
  if (window.renderMathInElement) {{
    try {{
      renderMathInElement(document.body, {{
        delimiters: [
          {{left: '$$', right: '$$', display: true}},
          {{left: '$', right: '$', display: false}},
          {{left: '\\\\(', right: '\\\\)', display: false}},
          {{left: '\\\\[', right: '\\\\]', display: true}}
        ],
        throwOnError: false
      }});
    }} catch(e){{}}
  }}
}})();
"""


KATEX_TAGS = (
    '<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.css">\n'
    '<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.js"></script>\n'
    '<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/contrib/auto-render.min.js"></script>\n'
)
MERMAID_TAG = (
    '<script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>\n'
)


def render(
    md_text: str,
    theme: str,
    title: str,
    base_dir: Path | None = None,
    *,
    style_path: Path,
    custom_css_path: Path,
) -> str:
    source = preprocess_transclusions(md_text, base_dir)
    source = preprocess_tasks(source)
    md = markdown.Markdown(
        extensions=MD_EXTENSIONS,
        extension_configs=MD_EXTENSION_CONFIGS,
    )
    body = md.convert(source)
    return (
        "<!DOCTYPE html>\n"
        f'<html data-theme="{theme}">\n<head>\n<meta charset="utf-8">\n'
        f"<title>{html_mod.escape(title)}</title>\n"
        f"{KATEX_TAGS}{MERMAID_TAG}"
        f"<style>{load_style(style_path, custom_css_path)}</style>\n"
        f"<style>{pygments_css(theme)}</style>\n"
        f'</head>\n<body>\n<main class="markdown-body">\n{body}\n</main>\n'
        f"<script>{_js_bridge(theme)}</script>\n"
        "</body>\n</html>"
    )


def count_words_and_read_time(text: str) -> tuple[int, int]:
    stripped = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    stripped = re.sub(r"^---\n.*?\n---\n", "", stripped, flags=re.DOTALL)
    words = len(re.findall(r"\b[\w'\-]+\b", stripped))
    minutes = max(1, round(words / 200)) if words else 0
    return words, minutes


def snapshot_slug(path: Path) -> str:
    return hashlib.sha1(str(path.resolve()).encode("utf-8")).hexdigest()[:16]


def write_snapshot(
    path: Path,
    text: str,
    *,
    snapshot_dir: Path,
    snapshot_keep: int,
) -> Path | None:
    try:
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        folder = snapshot_dir / f"{snapshot_slug(path)}-{path.stem}"
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        snap = folder / f"{stamp}.md"
        snap.write_text(text, encoding="utf-8")
        existing = sorted(folder.glob("*.md"), reverse=True)
        for extra in existing[snapshot_keep:]:
            try:
                extra.unlink()
            except OSError:
                pass
        return snap
    except OSError:
        return None


def list_snapshots(path: Path, *, snapshot_dir: Path) -> list[Path]:
    folder = snapshot_dir / f"{snapshot_slug(path)}-{path.stem}"
    if not folder.is_dir():
        return []
    return sorted(folder.glob("*.md"), reverse=True)


def looks_like_csv(text: str) -> tuple[str, bool]:
    if not text or "\n" not in text:
        return "", False
    rows = [r for r in text.split("\n") if r.strip()]
    if len(rows) < 2:
        return "", False
    for sep in ("\t", "|", ","):
        counts = [r.count(sep) for r in rows]
        if counts[0] >= 1 and all(c == counts[0] for c in counts):
            return sep, True
    return "", False


def csv_to_markdown_table(text: str, sep: str) -> str:
    rows = [r for r in text.split("\n") if r.strip()]
    cells = [[c.strip() for c in r.split(sep)] for r in rows]
    width = max(len(r) for r in cells)
    for r in cells:
        while len(r) < width:
            r.append("")

    def fmt(row):
        return "| " + " | ".join(c.replace("|", r"\|") for c in row) + " |"

    header = fmt(cells[0])
    sep_row = "| " + " | ".join(["---"] * width) + " |"
    body = "\n".join(fmt(r) for r in cells[1:])
    return f"{header}\n{sep_row}\n{body}\n"
