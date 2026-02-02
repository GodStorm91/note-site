#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EXPORT_SCRIPT="$ROOT_DIR/../Bear-Markdown-Export/bear_export_sync.py"
OUT_DIR="$ROOT_DIR/src/content/notes"
BACKUP_DIR="$ROOT_DIR/bear-sync-backup"
PUBLIC_DIR="$ROOT_DIR/public"

mkdir -p "$OUT_DIR" "$BACKUP_DIR" "$PUBLIC_DIR"

if [ ! -f "$EXPORT_SCRIPT" ]; then
  echo "bear_export_sync.py not found at $EXPORT_SCRIPT" >&2
  exit 1
fi

python3 "$EXPORT_SCRIPT" --out "$OUT_DIR" --backup "$BACKUP_DIR"

# Sync BearImages (if any) into public/BearImages so the site can serve them
if [ -d "$OUT_DIR/BearImages" ]; then
  mkdir -p "$PUBLIC_DIR/BearImages"
  rsync -r "$OUT_DIR/BearImages/" "$PUBLIC_DIR/BearImages/"
fi
