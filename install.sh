#!/usr/bin/env bash
# Install markview: wire the CLI on PATH and register a desktop entry.
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
BIN_DIR="${HOME}/.local/bin"
APPS_DIR="${HOME}/.local/share/applications"
ICONS_DIR="${HOME}/.local/share/icons/hicolor/scalable/apps"

mkdir -p "${BIN_DIR}" "${APPS_DIR}" "${ICONS_DIR}"

# Ensure python entrypoint is executable.
chmod +x "${APP_DIR}/markview.py"

# CLI launcher on PATH.
cat > "${BIN_DIR}/markview" <<EOF
#!/usr/bin/env bash
exec python3 "${APP_DIR}/markview.py" "\$@"
EOF
chmod +x "${BIN_DIR}/markview"

# Icon.
cp -f "${APP_DIR}/icon.svg" "${ICONS_DIR}/markview.svg"

# Desktop entry with real paths substituted in.
sed \
  -e "s|HOME_MARKVIEW_PATH|${BIN_DIR}/markview|g" \
  -e "s|HOME_MARKVIEW_ICON|markview|g" \
  "${APP_DIR}/markview.desktop" > "${APPS_DIR}/markview.desktop"

# Refresh caches (best effort).
command -v update-desktop-database >/dev/null && \
  update-desktop-database "${APPS_DIR}" >/dev/null 2>&1 || true
command -v gtk-update-icon-cache >/dev/null && \
  gtk-update-icon-cache -f -t "${HOME}/.local/share/icons/hicolor" >/dev/null 2>&1 || true

echo "markview installed."
echo "  CLI:     ${BIN_DIR}/markview"
echo "  Desktop: ${APPS_DIR}/markview.desktop"
echo
case ":${PATH}:" in
  *":${BIN_DIR}:"*) ;;
  *) echo "Note: ${BIN_DIR} is not on PATH. Add it to your shell rc."
     echo "      export PATH=\"${BIN_DIR}:\$PATH\"" ;;
esac
