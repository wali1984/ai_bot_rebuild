#!/usr/bin/env bash
# RC15 watchdog v2: detect the Codex-extension sidebar stuck on its boot race
# in Cursor and auto-clear it (see memory crash catalog RC15).
#
# v1 required TOTAL app-server silence after a single `initialize`. That
# missed the 2026-07-29 variant: headless Codex CLI agents and other clients
# (thread/resume, process/spawn, slingshot) share the same app-server via the
# IPC router, so their traffic masked the stuck sidebar.
#
# v2 rule: find the LATEST extension-style MCP initialize (request_id=
# Integer(1) - only the sidebar's CodexMcpConnection uses integer id 1;
# agents/slingshot use UUID/string ids). If that connection is >5 min old and
# has ZERO follow-up requests, the sidebar is on the infinite spinner - a
# healthy sidebar sends account/getAuthStatus/thread-list within 2 seconds.
# Remedy: kill the app-server; the extension surfaces a retry UI (it does NOT
# auto-respawn in this state). Agent clients reconnect via thread/resume, as
# observed in the ledger after prior restarts.
set -euo pipefail

PID=$(pgrep -f 'extensions/openai\.chatgpt.*app-server' | head -1 || true)
[[ -n "$PID" ]] || exit 0

START_EPOCH=$(stat -c %Y "/proc/$PID" 2>/dev/null) || exit 0
AGE=$(( $(date +%s) - START_EPOCH ))
(( AGE > 300 )) || exit 0

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
cp ~/.codex/logs_2.sqlite "$TMP/db" 2>/dev/null || exit 0
cp ~/.codex/logs_2.sqlite-wal "$TMP/db-wal" 2>/dev/null || true
cp ~/.codex/logs_2.sqlite-shm "$TMP/db-shm" 2>/dev/null || true

read -r INIT_TS CONN AGE_S FOLLOW <<<"$(sqlite3 "$TMP/db" "
WITH ext_init AS (
  SELECT ts, substr(feedback_log_body, instr(feedback_log_body,'ConnectionId(')+13,
         instr(substr(feedback_log_body, instr(feedback_log_body,'ConnectionId(')+13), ')')-1) AS conn
  FROM logs
  WHERE ts >= $START_EPOCH
    AND feedback_log_body LIKE '%app-server request: initialize%'
    AND feedback_log_body LIKE '%request_id=Integer(1)%'
  ORDER BY ts DESC LIMIT 1
)
SELECT ei.ts, ei.conn,
       strftime('%s','now') - ei.ts,
       (SELECT count(*) FROM logs l
        WHERE l.ts > ei.ts
          AND l.feedback_log_body LIKE 'app-server request:%'
          AND l.feedback_log_body LIKE '%ConnectionId(' || ei.conn || ')%')
FROM ext_init ei;" | tr '|' ' ')"

[[ -n "${INIT_TS:-}" ]] || exit 0          # no extension initialize since app-server start
(( AGE_S > 300 )) || exit 0                # sidebar connection still young - give it time
(( FOLLOW == 0 )) || exit 0                # sidebar is talking - healthy

echo "RC15 v2 detected (app-server $PID: sidebar conn=$CONN silent ${AGE_S}s after initialize); killing to surface retry UI"
kill "$PID"
# Tell the operator immediately - after the kill the Codex panel can render as
# a grey/blank page (the webview never booted, so there is no UI to show the
# retry button in). Without this notice the grey page is discovered cold.
DISPLAY=:1 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus \
  notify-send -u critical "Codex watchdog" \
  "Cleared a stuck Codex app-server in Cursor. If the Codex panel is grey/blank: close+reopen the panel, or Reload Window." 2>/dev/null || true
