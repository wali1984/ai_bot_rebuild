# Final Product Audit HOLD_LIST — 2026-07-23T04:13:13Z

## Enforcement

- Branch: `codex/pipeline-trust-refresh`
- HEAD at capture: `23139acdd60f412691b5fdb05ead1e5a7a012c6a`
- Upstream: `origin/codex/pipeline-trust-refresh`
- Divergence at capture: 9 ahead / 0 behind
- Current dirty paths: 159
  - modified: 96
  - deleted: 1
  - untracked: 62
- Safe staging rule: never use `git add -A`; stage only the exact paths named
  by the current slice.
- Runtime rule: this ownership freeze authorizes no service restart, Redis
  write, exchange call, order, leverage change, or margin-mode change.

## Complete current exclusion set

The complete set is the exact union of:

1. all 155 paths recorded in
   [`FINAL_PRODUCT_AUDIT_HOLD_LIST_20260721T230728Z.md`](./FINAL_PRODUCT_AUDIT_HOLD_LIST_20260721T230728Z.md),
   whose SHA-256 is
   `af142eb1d42c989a9ee928acc9cbdf94ed44fbfb4d0399cbcbdd7c3298f5adb1`;
   and
2. the four paths below.

The set comparison proved that all 155 earlier paths are still dirty, no path
from that snapshot disappeared, and exactly four paths were added. This union
is therefore an exhaustive 159-path list rather than a sample.

| Status | Path | Ownership evidence | Disposition |
|---|---|---|---|
| `M` | `claude_worklog/codex/FINAL_PRODUCT_AUDIT_TASK_LIST_20260722T052452Z.md` | The active operator-provided task text appended 804 lines; the file is open in the operator's IDE. | User-owned instruction artifact; never stage or rewrite. |
| `M` | `v2/backend/app/services/self_healing/component_registry.py` | Diff adds the commissioned local-research trainer status path and changes trainer heartbeat interpretation. It belongs to the active trainer/supervisor lane. | Core-lane hold until its own focused review, tests, commit, and deployment proof. |
| `??` | `v2/backend/app/services/altdata/coinank_receipts.py` | New causal CoinAnk request-receipt helper; it belongs to provider provenance/native ingestion. | Provider/provenance hold; do not absorb into product projection work. |
| `M` | `v2/frontend/src/components/charts/proChartInternals.css` | The one-line malformed-comment repair exactly matches the prior product-audit checkpoint's markets/charts defect. | Product-audit-owned, but deferred until the markets page-family slice after the core-configuration gate. |

## Safe paths for the P0 evidence slice

Only these documentation paths are owned by this slice:

- `claude_worklog/codex/FINAL_PRODUCT_AUDIT_HOLD_LIST_20260723T041313Z.md`
- `claude_worklog/codex/FINAL_PRODUCT_AUDIT_PREFLIGHT_20260723T041313Z.md`
- `claude_worklog/codex/FINAL_PRODUCT_AUDIT_CHECKPOINT.md`

No production, test, mobile, frontend, service, credential, runtime payload, or
generated atlas path is safe to stage in the P0 commit.

## Service and data boundaries

- Preserve every service/timer and Redis ownership boundary in the earlier
  HOLD_LIST.
- Twelve supervisor components are explicitly held and one component is not
  installed. A held or absent service is not permission to start or install it.
- The commissioned trainer and feature publisher run from immutable release
  `974caa6c263eeadf09fad5028d0883d304a14075`; this branch does not yet contain
  that release and must reconcile it only in an explicit integration slice.
- Redis inspection remains exact-key or bounded only. `KEYS`, unbounded
  `SCAN`, and unbounded filesystem/log traversal are prohibited.
- The hardware/latency and web/iOS task is queued. It does not authorize tuning
  or product edits before core configuration completion is proved.

## Reproduction

```bash
git status --porcelain=v1 --untracked-files=all
git rev-list --left-right --count HEAD...@{upstream}
comm -23 <(git status --porcelain=v1 --untracked-files=all | sed -E 's/^.. //' | sort) <(sed -n '/^```text$/,/^```$/p' claude_worklog/codex/FINAL_PRODUCT_AUDIT_HOLD_LIST_20260721T230728Z.md | sed -E -n 's/^( M| D|\?\?) //p' | sort)
```
