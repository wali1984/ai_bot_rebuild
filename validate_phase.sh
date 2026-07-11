#!/usr/bin/env bash
set -uo pipefail
PHASE="$1"
FAIL=0
say() { printf '%s\n' "$*"; }

# 1. Compile check
python -m py_compile \
  v2/backend/app/cli/v2_trade_management_paper_loop.py \
  v2/backend/app/cli/v2_a_plus_candidate_inventory.py \
  v2/backend/app/cli/v2_live_canary_dry_run.py \
  v2/backend/app/services/adaptive_capital_allocator/*.py \
  v2/backend/app/services/allocator/*.py \
  v2/backend/app/services/preemptive_edge_control/*.py \
  || { say "COMPILE FAILED"; FAIL=1; }

# 2. Tests — capture real pass count
PYTEST_OUT=$(.venv/bin/pytest -q \
  v2/backend/tests/unit/cli/test_v2_trade_management_paper_loop.py \
  v2/backend/tests/unit/cli/test_v2_a_plus_candidate_inventory.py \
  v2/backend/tests/unit/cli/test_v2_live_canary_dry_run.py \
  v2/backend/tests/unit/services/adaptive_capital_allocator \
  v2/backend/tests/unit/services/allocator \
  v2/backend/tests/unit/services/preemptive_edge_control \
  v2/backend/tests/integration/cli/test_v2_trade_management_paper_strategy_router.py 2>&1)
PYTEST_CODE=$?
say "$PYTEST_OUT" | tail -5
[ $PYTEST_CODE -eq 0 ] || { say "PYTEST FAILED ($PYTEST_CODE)"; FAIL=1; }

# 3. Frontend + mobile + diff hygiene
npm --prefix v2/frontend run typecheck || { say "TYPECHECK FAILED"; FAIL=1; }
npm --prefix v2/frontend run build     || { say "BUILD FAILED"; FAIL=1; }
swift test --package-path v2/mobile     || { say "SWIFT FAILED"; FAIL=1; }
git diff --check                        || { say "WHITESPACE/CONFLICT MARKERS"; FAIL=1; }

# 4. Safety scan — MUST be zero disallowed hits in non-test code
HITS=$(rg -n "create_order|test_order|cancel_order|modify_order|change_leverage|change_margin|transfer|withdraw" \
  v2/backend/app v2/frontend/src v2/mobile \
  --glob '*.py' --glob '*.ts' --glob '*.tsx' --glob '*.swift' \
  | rg -v "would_call_endpoint|dry_run|status|reason|_test|test_|# safe|blocked_human_only" || true)
if [ -n "$HITS" ]; then say "SAFETY VIOLATION:"; say "$HITS"; FAIL=1; fi

# 5. Phase artifact must exist and be valid JSON
ARTIFACT=$(ls -1 *phase${PHASE}_* 2>/dev/null | head -1)
[ -n "$ARTIFACT" ] || { ARTIFACT=$(ls -1 FINAL_*.json 2>/dev/null | head -1); }
if [ -z "$ARTIFACT" ]; then say "NO ARTIFACT FOR PHASE $PHASE"; FAIL=1;
else python -c "import json,sys; json.load(open('$ARTIFACT'))" \
  || { say "ARTIFACT NOT VALID JSON: $ARTIFACT"; FAIL=1; }; fi

[ $FAIL -eq 0 ] && say "PHASE $PHASE: PASS" || say "PHASE $PHASE: FAIL"
exit $FAIL