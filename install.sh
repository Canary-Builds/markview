#!/usr/bin/env bash
# Install VertexWrite: wire the CLI on PATH and register a desktop entry.
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
BIN_DIR="${HOME}/.local/bin"
APPS_DIR="${HOME}/.local/share/applications"
HICOLOR="${HOME}/.local/share/icons/hicolor"

mkdir -p "${BIN_DIR}" "${APPS_DIR}"

# Remove pre-rename source-install artifacts so desktop menus do not show stale
# product names after an in-place upgrade.
rm -f "${BIN_DIR}/vertexmarkdown" "${BIN_DIR}/markview"
rm -f "${APPS_DIR}/vertexmarkdown.desktop" "${APPS_DIR}/markview.desktop"

# Ensure python entrypoint is executable.
chmod +x "${APP_DIR}/vertexwrite.py"

# CLI launcher on PATH.
cat > "${BIN_DIR}/vertexwrite" <<EOF
#!/usr/bin/env bash
: "\${WEBKIT_DISABLE_DMABUF_RENDERER:=1}"
export WEBKIT_DISABLE_DMABUF_RENDERER
exec python3 "${APP_DIR}/vertexwrite.py" "\$@"
EOF
chmod +x "${BIN_DIR}/vertexwrite"

# Icon — install all hicolor sizes that exist.
for size in 16 32 48 64 128 256 512; do
  src="${APP_DIR}/icon-${size}.png"
  if [[ "${size}" == "512" ]]; then
    src="${APP_DIR}/icon.png"
  fi
  if [[ -f "${src}" ]]; then
    dest="${HICOLOR}/${size}x${size}/apps"
    mkdir -p "${dest}"
    rm -f "${dest}/vertexmarkdown.png" "${dest}/markview.png"
    cp -f "${src}" "${dest}/vertexwrite.png"
  fi
done

# Desktop entry with real paths substituted in.
sed \
  -e "s|HOME_VERTEXWRITE_PATH|${BIN_DIR}/vertexwrite|g" \
  -e "s|HOME_VERTEXWRITE_ICON|vertexwrite|g" \
  "${APP_DIR}/vertexwrite.desktop" > "${APPS_DIR}/vertexwrite.desktop"

# Refresh caches (best effort).
command -v update-desktop-database >/dev/null && \
  update-desktop-database "${APPS_DIR}" >/dev/null 2>&1 || true
command -v gtk-update-icon-cache >/dev/null && \
  gtk-update-icon-cache -f -t "${HICOLOR}" >/dev/null 2>&1 || true

echo "VertexWrite installed."
echo "  CLI:     ${BIN_DIR}/vertexwrite"
echo "  Desktop: ${APPS_DIR}/vertexwrite.desktop"
echo "  Icon:    ${HICOLOR}/<size>/apps/vertexwrite.png"
echo
case ":${PATH}:" in
  *":${BIN_DIR}:"*) ;;
  *) echo "Note: ${BIN_DIR} is not on PATH. Add it to your shell rc."
     echo "      export PATH=\"${BIN_DIR}:\$PATH\"" ;;
esac
