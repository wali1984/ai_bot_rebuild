#!/usr/bin/env bash
# CI stage: lint
# Required from milestone B per claude_worklog/v2_scaffold_planning/07_TEST_AND_CI_PLAN.md §4.
# Local-native; no Docker; no legacy DB / Redis / exchange access.
# Boundary: scripts under v2/ops/ci act on v2/ only.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
V2_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$V2_ROOT"

# ---- backend: ruff (mandatory) ----------------------------------------------
echo "[ci/lint] ruff check backend"
if command -v ruff >/dev/null 2>&1; then
  ruff check backend
else
  python -m ruff check backend
fi

# ---- frontend: eslint (advisory until milestone F per 015E §13) -------------
ESLINT_BIN="frontend/node_modules/.bin/eslint"
ESLINT_CONFIG=""
for cand in frontend/eslint.config.js frontend/.eslintrc.cjs frontend/.eslintrc.json frontend/.eslintrc.js; do
  if [ -f "$cand" ]; then
    ESLINT_CONFIG="$cand"
    break
  fi
done
if [ -x "$ESLINT_BIN" ] && [ -n "$ESLINT_CONFIG" ]; then
  echo "[ci/lint] eslint frontend ($ESLINT_CONFIG)"
  (cd frontend && ./node_modules/.bin/eslint --max-warnings=0 src tests)
else
  echo "[ci/lint] eslint not installed or no config (deferred to milestone F per 015E §13); WARN advisory"
fi

echo "[ci/lint] OK"
