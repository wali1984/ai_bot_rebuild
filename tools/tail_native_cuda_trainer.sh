#!/usr/bin/env bash
# Thin wrapper: run the self-contained trainer monitor with the venv
# interpreter. (The old heredoc `tail | interpreter - <<EOF` design fed the
# program on stdin, so the piped log never reached the reader and nothing
# printed. Logic now lives in tail_native_cuda_trainer.py.)
set -u
ROOT="/home/wali/Desktop/AI BOT REBUILD"
PY="$ROOT/.venv/bin/python"
exec "$PY" "$ROOT/tools/tail_native_cuda_trainer.py"
