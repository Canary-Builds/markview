#!/usr/bin/env bash
# Sync docs/wiki/*.md into the GitHub Wiki repo, stripping `.md` from
# inter-wiki markdown links so they render as wiki page links instead of
# raw-file references.
#
# Usage: scripts/sync-wiki.sh
# Requires:
#   - You have push access to <owner>/<repo>.wiki.git
#   - Either `gh auth status` is green, OR credentials are otherwise set up
#     for https://github.com.
set -euo pipefail

OWNER="Canary-Builds"
REPO="markview"
WIKI_URL="https://github.com/${OWNER}/${REPO}.wiki.git"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="${ROOT}/docs/wiki"
WORK="$(mktemp -d -t "${REPO}-wiki.XXXXXX")"
trap 'rm -rf "${WORK}"' EXIT

if [[ ! -d "${SRC}" ]]; then
  echo "source folder not found: ${SRC}" >&2
  exit 1
fi

echo "Cloning ${WIKI_URL}"
git clone --quiet "${WIKI_URL}" "${WORK}"

# Copy every canonical wiki page
cp -f "${SRC}"/*.md "${WORK}/"

# Build a regex that matches ](PageName.md) and ](PageName.md#anchor) for
# every page that exists in docs/wiki/. Anything else (external .md URLs,
# unrelated filenames) is left alone.
PAGES=()
for f in "${SRC}"/*.md; do
  PAGES+=("$(basename "$f" .md)")
done
ALT="$(IFS='|'; echo "${PAGES[*]}")"

# Transform links inside the wiki working copy only — docs/wiki/ stays as
# the canonical source with `.md` suffixes so in-tree browsing works.
python3 - "$WORK" "$ALT" <<'PY'
import re, sys, pathlib
work = pathlib.Path(sys.argv[1])
alt = sys.argv[2]
# matches ](PageName.md) or ](PageName.md#anchor)
pattern = re.compile(r"\]\((" + alt + r")\.md(#[^)]*)?\)")
for path in work.glob("*.md"):
    text = path.read_text(encoding="utf-8")
    new = pattern.sub(lambda m: f"]({m.group(1)}{m.group(2) or ''})", text)
    if new != text:
        path.write_text(new, encoding="utf-8")
        print(f"  rewrote links in {path.name}")
PY

cd "${WORK}"
git config user.name 'Soho'
git config user.email '262048121+cnysoho@users.noreply.github.com'

if git diff --quiet && git diff --cached --quiet; then
  echo "wiki already up to date."
  exit 0
fi

git add -A
git commit --quiet -m "Sync wiki from docs/wiki/ (${REPO}@$(git -C "${ROOT}" rev-parse --short HEAD))"
git push --quiet origin HEAD
echo "Wiki synced → https://github.com/${OWNER}/${REPO}/wiki"
