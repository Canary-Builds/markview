#!/usr/bin/env bash
set -euo pipefail

rm -f "${HOME}/.local/bin/markview"
rm -f "${HOME}/.local/share/applications/markview.desktop"
rm -f "${HOME}/.local/share/icons/hicolor/scalable/apps/markview.svg"

command -v update-desktop-database >/dev/null && \
  update-desktop-database "${HOME}/.local/share/applications" >/dev/null 2>&1 || true
command -v gtk-update-icon-cache >/dev/null && \
  gtk-update-icon-cache -f -t "${HOME}/.local/share/icons/hicolor" >/dev/null 2>&1 || true

echo "markview uninstalled. Source folder at ${HOME}/markview is untouched."
