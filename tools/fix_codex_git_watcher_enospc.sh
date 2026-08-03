#!/usr/bin/env bash
# fix_codex_git_watcher_enospc.sh
#
# Durable fix for the recurring "Codex/ChatGPT extension stuck loading" bug in
# Cursor and VS Code (RC11 in the crash catalog).
#
# ROOT CAUSE (verified 2026-07-16, extension openai.chatgpt-26.707.71524):
#   The Codex extension's `git-repo-watcher` calls Node fs.watch(repoRoot,
#   {recursive:true}). On Linux this opens ~1 inotify INSTANCE per directory and
#   IGNORES both .gitignore and VS Code's files.watcherExclude. This repo has
#   ~91,000 directories, ~65,798 of them inside the gitignored, trainer-owned
#   .local_data/v2_native_trainer/durable_feature_snapshot_archive (117 GB).
#   With fs.inotify.max_user_instances=1024 the watcher instantly hits
#   ENOSPC ("System limit for number of file watchers reached"), crash-loops
#   every ~20s, and the webview wedges at "loading".
#   It regresses after every Codex auto-update because updates wipe any
#   extension.js patch. The two fixes below are CONFIG/FILESYSTEM level and
#   therefore survive updates.
#
# This script does nothing on its own beyond printing a diagnosis. Pass a
# subcommand to apply a fix. Read each one before running.
#
#   ./fix_codex_git_watcher_enospc.sh diagnose          # default; no changes
#   sudo ./fix_codex_git_watcher_enospc.sh sysctl        # raise instance limit
#   ./fix_codex_git_watcher_enospc.sh relocate --confirm # symlink .local_data out
#
set -euo pipefail

REPO="/home/wali/Desktop/AI BOT REBUILD"
LOCAL_DATA="$REPO/.local_data"
RELOCATE_TARGET="${CODEX_LOCAL_DATA_TARGET:-/home/wali/ai_bot_local_data}"
SYSCTL_FILE="/etc/sysctl.d/60-vscode.conf"
DESIRED_INSTANCES=65536
DESIRED_WATCHES=2097152

log() { printf '  %s\n' "$*"; }
hr()  { printf '%s\n' "----------------------------------------------------------------"; }

diagnose() {
  hr; echo "DIAGNOSIS"; hr
  log "max_user_instances : $(cat /proc/sys/fs/inotify/max_user_instances) (need >= repo dir count)"
  log "max_user_watches   : $(cat /proc/sys/fs/inotify/max_user_watches)"
  local total local_dirs rest
  total=$(find "$REPO" -type d 2>/dev/null | wc -l || echo '?')
  local_dirs=$(find "$LOCAL_DATA" -type d 2>/dev/null | wc -l || echo '?')
  log "repo directories   : $total total"
  log ".local_data dirs   : $local_dirs  (recursed by Codex watcher; wasteful + churny)"
  if [ -L "$LOCAL_DATA" ]; then
    log ".local_data        : SYMLINK -> $(readlink -f "$LOCAL_DATA")  [relocate already applied]"
  elif [ -d "$LOCAL_DATA" ]; then
    log ".local_data        : real directory (relocate NOT applied)"
  fi
  echo
  log "Recommended: run 'sysctl' (immediate) AND 'relocate' (removes archive from watch set)."
}

apply_sysctl() {
  if [ "$(id -u)" -ne 0 ]; then echo "ERROR: run with sudo for 'sysctl'." >&2; exit 1; fi
  hr; echo "APPLYING sysctl: max_user_instances=$DESIRED_INSTANCES"; hr
  cat > "$SYSCTL_FILE" <<EOF
# Raised for Cursor/VS Code + Codex recursive file watchers over a large repo.
# max_user_instances must exceed the repo directory count; Node's recursive
# fs.watch opens ~1 inotify instance per directory. See RC11 crash-catalog note.
fs.inotify.max_user_watches=$DESIRED_WATCHES
fs.inotify.max_user_instances=$DESIRED_INSTANCES
EOF
  sysctl -p "$SYSCTL_FILE"
  log "Done. Reload the Cursor/VS Code window (Developer: Reload Window) to restart the watcher."
}

apply_relocate() {
  if [ "${1:-}" != "--confirm" ]; then
    echo "ERROR: 'relocate' moves the live trainer's data dir. Re-run with --confirm." >&2
    echo "       STRONGLY recommended: pause the native CUDA trainer first, then run." >&2
    exit 1
  fi
  if [ -L "$LOCAL_DATA" ]; then log ".local_data is already a symlink; nothing to do."; exit 0; fi
  if [ ! -d "$LOCAL_DATA" ]; then log "No .local_data directory found; nothing to do."; exit 0; fi
  # Same-filesystem check guarantees an instant rename (no 117 GB copy).
  local dev_src dev_dst_parent
  dev_src=$(stat -c %d "$LOCAL_DATA")
  mkdir -p "$(dirname "$RELOCATE_TARGET")"
  dev_dst_parent=$(stat -c %d "$(dirname "$RELOCATE_TARGET")")
  if [ "$dev_src" != "$dev_dst_parent" ]; then
    echo "ERROR: $RELOCATE_TARGET is on a different filesystem; this would be a slow 117 GB copy." >&2
    echo "       Choose a target on the same disk (set CODEX_LOCAL_DATA_TARGET) or copy manually." >&2
    exit 1
  fi
  if [ -e "$RELOCATE_TARGET" ]; then echo "ERROR: $RELOCATE_TARGET already exists." >&2; exit 1; fi
  hr; echo "RELOCATING .local_data -> $RELOCATE_TARGET (same-fs rename, then symlink)"; hr
  # Minimal-gap rename+symlink; trainer open FDs stay valid across a dir rename.
  mv "$LOCAL_DATA" "$RELOCATE_TARGET" && ln -s "$RELOCATE_TARGET" "$LOCAL_DATA"
  log "Done. .local_data is now a symlink; Node's recursive watcher will not descend it."
  log "Verify: ls -ld '$LOCAL_DATA'  and confirm the trainer still writes snapshots."
}

cmd="${1:-diagnose}"; shift || true
case "$cmd" in
  diagnose) diagnose ;;
  sysctl)   apply_sysctl ;;
  relocate) apply_relocate "${1:-}" ;;
  *) echo "usage: $0 {diagnose|sysctl|relocate --confirm}" >&2; exit 2 ;;
esac
