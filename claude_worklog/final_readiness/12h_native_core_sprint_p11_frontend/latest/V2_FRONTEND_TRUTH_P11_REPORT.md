# Frontend Truth & User Pages P11

Phase P11; Sprint 12h native core migration.

Generated: 2026-05-16T05:25:00Z
Git HEAD: 31a7fd70319f0d586c454b5ea2ea530ba9cb1541

## What was built

- v2/frontend/public/12h_native_core_sprint/latest/pages_truth_overlay.json:
  per-page simple-English content for the 13 pages required by P11.

## Pages covered

| Page path | Coverage |
| --- | --- |
| /admin/permanent-migration | full sprint phase list + missing items |
| /admin/trainer-parity | trainer surface + missing PPO/checkpoint |
| /admin/paper-edge | trade-management engine + missing soak |
| /admin/decision-quality | trainer output + missing calibration vs outcome |
| /admin/codex-claude-control | sprint controller + missing Codex passes |
| /status-simple | phase READY summary + missing Codex sweep |
| /markets | native ingestor classification |
| /derivatives | funding/OI/liquidation classification |
| /chart/:symbol | V2 native OHLCV+TA |
| /bots/trainer | native trainer output |
| /paper-trading | paper-only stack verification |
| /signals | orchestrator + trainer output |
| /risk | risk gateway binding |

## Each page surfaces

- can_old_system_be_shut_down: false (BLOCK_LEGACY_SHUTDOWN_PARITY_INCOMPLETE)
- is_live_trading_allowed: false (blocked_human_only)
- what_is_complete: per-page list pulled from this sprint's READY artifacts
- what_is_still_missing: per-page list of remaining blockers
- what_is_claude_doing: phase 12 packet emitted; awaiting Codex
- what_did_codex_pass_or_fail: phase-level reviews pending
- evidence_paths: per-page
- last_updated_utc + stale_or_missing_state

## Common rules respected

- No mock current data.
- No legacy-as-current truth unless labelled LEGACY_REFERENCE_READ_ONLY
  in the underlying public payload schema.
- No live controls enabled.

## Permanent migration contract checklist

- Legacy source paths: N/A for frontend overlay.
- SHA256: N/A.
- Dependency closure: N/A.
- Config/env mapping: N/A.
- Behavior mapping: yes (overlay JSON schema documented).
- V2 implementation: yes (overlay JSON).
- Tests: existing useFrontendTruthPayload hook tests apply.
- Public payload: yes
  (v2/frontend/public/12h_native_core_sprint/latest/pages_truth_overlay.json).
- Codex review: pending.
- No old Redis writes: yes.
- No exchange mutation: yes.
- live_gate == "blocked_human_only": yes.
- live_symbols == []: yes.

## Decision

P11 READY at the overlay-payload level. The existing pages already
consume useFrontendTruthPayload(); page bodies can incrementally read
this sprint overlay to surface 12-hour sprint state without page
refactor risk.
