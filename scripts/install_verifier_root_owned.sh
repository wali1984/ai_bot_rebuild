#!/usr/bin/env bash
# Run this ONCE as root (or with sudo) to install the tamper-proof verifier.
# After running this, Claude agents cannot modify the verifier script.
set -e

SRC="/home/wali/Desktop/AI BOT REBUILD/scripts/verify_claude_guardian_completion.py"
DEST_DIR="/usr/local/lib/ai-bot-guardian"
DEST="$DEST_DIR/verify_claude_guardian_completion.py"

mkdir -p "$DEST_DIR"
cp "$SRC" "$DEST"
chown -R root:root "$DEST_DIR"
chmod -R 0555 "$DEST_DIR"

echo "Verifier installed:"
ls -la "$DEST_DIR/"
echo "SHA256: $(sha256sum "$DEST")"
