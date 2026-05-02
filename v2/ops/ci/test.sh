#!/usr/bin/env bash
# CI stage: test orchestrator
# Stages required by milestone:
#   B: (no domain tests yet)
#   C: unit, integration, contract advisory
#   D: contract mandatory; idempotency replay; ETag concurrency
#   E: frontend-unit, e2e
# Local-native only. Never targets legacy Redis, legacy DB, trainer venv,
# or any real exchange.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
V2_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$V2_ROOT"

# Hard guards: refuse to run if a legacy URL leaks into the test environment.
if [ -n "${LEGACY_REDIS_URL:-}" ]; then
  echo "[ci/test] FAIL: LEGACY_REDIS_URL is set in CI env; CI must not target legacy Redis." >&2
  exit 2
fi
if [ -n "${LEGACY_BOT_ROOT:-}" ]; then
  echo "[ci/test] FAIL: LEGACY_BOT_ROOT is set in CI env; CI must not address legacy bot." >&2
  exit 2
fi

export V2_REDIS_PREFIX="${V2_REDIS_PREFIX:-v2:test}"
export V2_MODE="${V2_MODE:-paper}"

run_unit() {
  echo "[ci/test] pytest unit"
  pytest backend/tests/unit -q
}
run_integration() {
  echo "[ci/test] pytest integration"
  pytest backend/tests/integration -q
}
run_contract() {
  echo "[ci/test] pytest contract"
  pytest backend/tests/contract -q
}
run_property() {
  echo "[ci/test] pytest property"
  pytest backend/tests/property -q
}
run_frontend_unit() {
  if [ -d frontend/node_modules ] && grep -q '"vitest"' frontend/package.json 2>/dev/null; then
    echo "[ci/test] vitest run"
    (cd frontend && npm run -s test:unit -- --run)
  else
    echo "[ci/test] vitest not installed (deferred to milestone F per 015E §13); WARN advisory"
  fi
}
run_e2e() {
  if [ -d frontend/node_modules ] && [ -x frontend/node_modules/.bin/playwright ]; then
    echo "[ci/test] playwright test"
    (cd frontend && ./node_modules/.bin/playwright test)
  else
    echo "[ci/test] playwright not installed; WARN advisory (install via 'npx playwright install')"
  fi
}

stage="${1:-all}"
case "$stage" in
  unit) run_unit ;;
  integration) run_integration ;;
  contract) run_contract ;;
  property) run_property ;;
  frontend-unit) run_frontend_unit ;;
  e2e) run_e2e ;;
  all)
    run_unit
    run_integration
    run_contract
    run_property
    run_frontend_unit
    run_e2e
    ;;
  *)
    echo "[ci/test] unknown stage: $stage (expected one of: unit|integration|contract|property|frontend-unit|e2e|all)" >&2
    exit 2
    ;;
esac

echo "[ci/test] OK ($stage)"
