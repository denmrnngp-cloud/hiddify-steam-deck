#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PLUGIN_DIR="$ROOT_DIR/decky-hiddify"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

VERSION="$(ROOT_DIR="$ROOT_DIR" python3 - <<'PY'
import json
import os
from pathlib import Path
root = Path(os.environ["ROOT_DIR"])
print(json.loads((root / "decky-hiddify/plugin.json").read_text())["version"])
PY
)"

mkdir -p "$TMP_DIR/decky-hiddify"

cp -r \
    "$PLUGIN_DIR/bin" \
    "$PLUGIN_DIR/dist" \
    "$PLUGIN_DIR/main.py" \
    "$PLUGIN_DIR/package.json" \
    "$PLUGIN_DIR/plugin.json" \
    "$TMP_DIR/decky-hiddify/"

(
    cd "$TMP_DIR"
    zip -qr decky-hiddify.zip decky-hiddify
)

cp "$TMP_DIR/decky-hiddify.zip" "$PLUGIN_DIR/decky-hiddify.zip"
cp "$TMP_DIR/decky-hiddify.zip" "$ROOT_DIR/release/installer-src/decky-hiddify.zip"
cp "$TMP_DIR/decky-hiddify.zip" "$ROOT_DIR/release/decky-hiddify-v${VERSION}.zip"

echo "Built decky-hiddify-v${VERSION}.zip with package.json included"
