# Codex Review: Paper Expected-Move Coverage

Reviewed task: `claude_improve_expected_move_after_cost_coverage_from_shadow_false_blocks`

Result: `PASS_FOR_HONEST_BLOCKED_PACKET`

The Claude packet is correctly blocked, not readiness-clearing. It identifies the false-block cause as missing expected-move coverage, adds a pure V2-local classifier for native/proxy/missing expected-move evidence, and keeps unvalidated proxy values non-fill-eligible.

Validation performed:

- `.venv/bin/python3 -m py_compile v2/backend/app/composition/paper_expected_move_coverage.py`
- `.venv/bin/pytest v2/backend/tests/unit/composition/test_paper_expected_move_coverage.py v2/backend/tests/integration/cli/test_paper_shadow_outcome_observer.py v2/backend/tests/unit/services/test_decision_improvement.py v2/backend/tests/unit/composition/test_paper_edge_scoring.py v2/backend/tests/integration/cli/test_v2_paper_execution_worker.py`
- scoped forbidden-token scan of `paper_expected_move_coverage.py`

Evidence:

- Focused tests passed: `60 passed`.
- `PAPER_EXPECTED_MOVE_COVERAGE_REMEDIATION_BLOCKED` is honest because the current V2 paper trainer wrapper does not emit native `expected_move_bps`.
- Missing expected-move evidence still blocks fills.
- Future shadow outcomes are not used as entry evidence.
- Unvalidated proxy expected-move values remain non-fill-eligible.
- Live remains `blocked_human_only`; `live_symbols` remains `[]`.

Remaining blocker:

- Port or emit native/accepted expected-move evidence from trainer/feature/risk/signal payloads before any expected-move value can be fill-eligible.
