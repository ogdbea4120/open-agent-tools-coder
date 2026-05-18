#!/usr/bin/env bash
#
# Build the Sphinx documentation locally for review.
#
# Usage:
#   ./stacks/build-docs.sh          # build + open in browser
#   ./stacks/build-docs.sh --no-open  # build only
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
DOCS_DIR="$PROJECT_DIR/docs"
BUILD_DIR="$DOCS_DIR/_build/html"

cd "$PROJECT_DIR"

echo "==> Installing docs dependencies..."
pip install -e ".[docs]" --quiet

echo "==> Cleaning previous build..."
rm -rf "$DOCS_DIR/_build"

echo "==> Building documentation..."
vc="sphinx-build -v -b html \"${DOCS_DIR}\" \"${BUILD_DIR}\""
echo "${vc}"
eval "${vc}" 2>&1 | grep -E "(WARNING|ERROR|build succeeded)" || true

echo ""
echo "==> Build complete. Output: $BUILD_DIR"
echo ""

if [[ "${1:-}" != "--no-open" ]]; then
    echo "==> Opening in browser..."
    if command -v xdg-open &>/dev/null; then
        xdg-open "$BUILD_DIR/index.html"
    elif command -v open &>/dev/null; then
        open "$BUILD_DIR/index.html"
    elif command -v gnome-open &>/dev/null; then
        gnome-open "$BUILD_DIR/index.html"
    else
        echo "==> Could not find a browser opener. Open manually:"
        echo "    file://$BUILD_DIR/index.html"
    fi
fi
