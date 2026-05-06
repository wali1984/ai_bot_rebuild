# 2H.B Stale FAIL Classification

## Classification

The watchdog was repeatedly seeing an older auxiliary `140_2H_B_CODEX_FAIL` marker even though the canonical 2H.B paper execution ledger assembler Codex gate has already been reconciled to PASS.

## Required Automation Rule

For the same stage, a canonical Codex PASS GO/NO-GO marker supersedes older auxiliary FAIL markers.

The Codex watchdog must not keep creating or running recovery tasks for an old FAIL marker if a same-stage Codex PASS marker exists.

## Required Behavior

- Detect same-stage stale FAIL markers by phase key.
- Require a same-stage `CODEX_PASS` GO/NO-GO marker before suppressing a FAIL marker.
- Do not let generic implementation `PASSED` markers hide real Codex review failures.
- Mark stale task state as superseded by evidence through `reconcile_evidence_status.py`.
- Continue to the next paper/backtest MVP milestone.

2HB_STALE_FAIL_CLASSIFIED
