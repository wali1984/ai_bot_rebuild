# Core Completion Blocker Burndown - Truth Remediation

Generated: 2026-05-16T23:05:00Z
Git HEAD: 31a7fd70319f0d586c454b5ea2ea530ba9cb1541
Burndown GO/NO-GO: V2_CORE_COMPLETION_BLOCKER_BURNDOWN_TRUTH_REMEDIATION_READY

## Why this remediation exists

Codex review (V2_CORE_COMPLETION_BLOCKER_BURNDOWN_CODEX_FAIL)
flagged two issues:

1. CoinAPI/CoinAnk: burndown matrix said resolved but runtime
   payload still classified them BLOCKED_BY_SECRET_OR_API because
   the registry only checked process env, not the local vault.
2. The matrix used a single boolean
   "every_blocker_implemented_or_explicitly_accepted=true" that
   conflated implemented vs operator-accepted.

Both are fixed.

## Fix 1 - Vault-aware runtime classifier

- v2/backend/app/services/native_ingestors/secret_decision.py:
  new module. Reads only key NAMES (line prefixes before "=") from
  .local_secrets/legacy.env. Never reads, returns, prints, logs,
  or publishes values. Public surface: key_name_available(name),
  decision_snapshot().
- v2/backend/app/services/native_ingestors/registry.py: _has_env
  now delegates to secret_decision.key_name_available, so the
  runtime classifier sees both process env AND the redacted vault.
- 9 new tests in test_v2_native_ingestors_secret_decision.py
  cover: vault key-name detection, env overrides vault, snapshot
  hides raw values, missing vault is handled, CoinAPI/CoinAnk
  upgrade to NATIVE_V2_READONLY_PUBLIC_DATA when vault keys are
  present, downgrade to BLOCKED_BY_SECRET_OR_API when absent, paid
  WSDS stays OPERATOR_DECISION_REQUIRED_FOR_PAPER_ONLY_SHUTDOWN,
  the public payload contains no raw secret strings, and the
  module has no forbidden imports.

After regenerating v2_native_ingestors_status.json:

- live_coinank -> NATIVE_V2_READONLY_PUBLIC_DATA
- live_coinapi_v1 -> NATIVE_V2_READONLY_PUBLIC_DATA
- live_coinapi_wsds -> OPERATOR_DECISION_REQUIRED_FOR_PAPER_ONLY_SHUTDOWN
- live_coinank_global_aggregator -> OPERATOR_DECISION_REQUIRED_FOR_PAPER_ONLY_SHUTDOWN

The runtime payload now agrees with the burndown matrix.

## Fix 2 - State-category model

The single boolean was replaced with explicit categories:

- IMPLEMENTED_AND_TESTED
- CONVERTED_TO_OPERATOR_DECISION_REQUIRED
- OPERATOR_ACCEPTED
- STILL_BLOCKED
- NOT_APPLICABLE_FOR_PAPER_ONLY
- LIVE_ONLY_BLOCKER

Per-blocker truth:

| Blocker | State | operator_accepted |
| --- | --- | --- |
| CHECKPOINT_WEIGHT_BLOB_OPERATOR_REQUIRED | CONVERTED_TO_OPERATOR_DECISION_REQUIRED | false |
| LIVE_KUCOIN_MISSING_IN_V2 | IMPLEMENTED_AND_TESTED | false |
| COINAPI_AND_COINANK_SECRET_OR_OPERATOR_DECISIONS | IMPLEMENTED_AND_TESTED | false |
| READONLY_BRIDGED_INGESTORS_NOT_ACCEPTED | IMPLEMENTED_AND_TESTED | false |
| ADAPTIVE_HEDGE_FAIL_CLOSED_LIMITATION | IMPLEMENTED_AND_TESTED | false |
| FULL_LEGACY_ORCHESTRATOR_WORKER_LOGIC | IMPLEMENTED_AND_TESTED | false |
| LIVE_REDIS_PROPOSAL_BUS_NOT_PORTED | LIVE_ONLY_BLOCKER | false |
| PAPER_EDGE_CURRENT_SAMPLE_NEGATIVE | CONVERTED_TO_OPERATOR_DECISION_REQUIRED | false |

State counts:

- IMPLEMENTED_AND_TESTED: 5
- CONVERTED_TO_OPERATOR_DECISION_REQUIRED: 2
- LIVE_ONLY_BLOCKER: 1
- OPERATOR_ACCEPTED: 0

Top-line truth:

- all_blockers_addressed_by_code_or_decision_packet: true
- all_required_operator_decisions_accepted: false
- paper_only_shutdown_decision_ready: false
- live_ready: false

## Runtime truth check (matrix vs runtime payload)

| Item | Runtime classification | Matrix says |
| --- | --- | --- |
| live_coinapi_v1 | NATIVE_V2_READONLY_PUBLIC_DATA | matches |
| live_coinank | NATIVE_V2_READONLY_PUBLIC_DATA | matches |
| live_coinapi_wsds | OPERATOR_DECISION_REQUIRED_FOR_PAPER_ONLY_SHUTDOWN | matches |
| live_coinank_global_aggregator | OPERATOR_DECISION_REQUIRED_FOR_PAPER_ONLY_SHUTDOWN | matches |

matrix_agrees_with_runtime: true.

## Secret hygiene

- secret_decision.py reads NAMES only (prefix before "=").
- secret_decision.decision_snapshot() never returns values.
- The public v2_native_ingestors payload has been scanned for
  high-confidence secret patterns (API_KEY=, secret_key,
  private_key); none present.
- A high-confidence-value scan over the burndown directory and
  the operator dashboard payload found no raw secret values.

## Safety posture (unchanged)

- live_gate: blocked_human_only
- live_symbols: []
- approves_live: false
- approves_canary: false
- approves_legacy_shutdown: false
- approves_redis_trim: false
- final_approval_token_created: false
- redis_trim_approval_created: false
- no_legacy_redis_writes_attempted: true
- no_exchange_mutation_attempted: true

## Pending operator decisions

NONE of these have been accepted by the operator. The remediation
makes the truth visible; it does NOT auto-accept anything:

- CHECKPOINT_WEIGHT_BLOB_OPERATOR_REQUIRED_NOT_ACCEPTED_FOR_PAPER_ONLY_SHUTDOWN
- ADAPTIVE_HEDGE_PAPER_ENGINE_OPERATOR_APPROVAL_TO_ENABLE
- PAPER_EDGE_NO_TRADE_OPERATOR_ACCEPTANCE
- live_coinapi_wsds (paid tier)
- live_coinank_global_aggregator (scope)
- ccxt_historical (vs replay store)

## Decision

V2_CORE_COMPLETION_BLOCKER_BURNDOWN_TRUTH_REMEDIATION_READY.

The truth model now distinguishes implemented vs accepted; runtime
and matrix agree; no raw secret value leaks; no live approval;
legacy shutdown remains blocked.
