#!/usr/bin/env bash
set -euo pipefail

rm -f "$HOME/.local/share/kio/servicemenus/assembly-info.desktop"
rm -f "$HOME/.local/share/applications/dll-assembly-info.desktop"
rm -f "$HOME/.local/bin/dll-assembly-info"
rm -rf "$HOME/.local/share/dll-assembly-info"
rm -rf "$HOME/.cache/dll-assembly-info"

echo "Menu Dolphin retire."
