#!/usr/bin/env bash
# CI stage: type
# Required from milestone B per 07_TEST_AND_CI_PLAN.md §4.
# mypy --strict on backend; tsc --noEmit on frontend (when node_modules present).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
V2_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$V2_ROOT"

# ---- backend: mypy --strict (mandatory) -------------------------------------
echo "[ci/type] mypy --strict backend"
mypy --strict backend

# ---- frontend: tsc --noEmit (mandatory when frontend installed) -------------
if [ -d frontend/node_modules ] && [ -x frontend/node_modules/.bin/tsc ]; then
  echo "[ci/type] tsc -b --noEmit frontend"
  (cd frontend && ./node_modules/.bin/tsc -b --noEmit)
else
  echo "[ci/type] frontend node_modules absent; tsc skipped with WARN (advisory)"
fi

echo "[ci/type] OK"
