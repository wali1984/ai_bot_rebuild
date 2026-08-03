# CG-F049 / CG-F050 Independent Runtime Validation — 2026-07-30 (WQ-R34, third pass)

Guardian lane, read-only. First pass (07-17): NEGATIVE (running PID predated fix).
Second pass (07-21): SAMPLE-STARVED (0 post-restart closes). This pass: **first
post-fix closes exist — CG-F050 validates POSITIVE; CG-F049 remains unobservable.**

## CG-F050 (capital invariant): RESOLVED — runtime-validated

Both closes in the rotated session `paper_session_140989e198032b94`:

| symbol | side | exit UTC | gross_notional | margin | lev | \|gross−m·l\| | qty×entry_price check |
|---|---|---|---|---|---|---|---|
| RAVEUSDT | long | 2026-07-29T21:05:58Z | 15.0093 | 15.0093 | 1.0 | **0.0** | 51×0.2943=15.0093 ✓ |
| TUSDT | long | 2026-07-29T22:34:44Z | 16.476276 | 16.476276 | 1.0 | **0.0** | 4866×0.003386=16.476276 ✓ |

- Policy `ADAPTIVE_POLICY_EXACT_PAPER_ALLOCATION_V2`, reason
  `adaptive_policy_exact_action_physically_validated_unchanged` on both.
- All capital fields populated (no subclass-A margin==0; no subclass-B
  accumulation-freeze). Bracket evidence READY, HMAC-signed, read-only credential
  lineage, `places_real_order=false`, `leverage_mutated=false`, `margin_mutated=false`.
- Independent corroboration: G10 verifier 2026-07-30T03:01Z passes **94/94** rows,
  0 invariant violations (46 historical rows previously repaired under operator
  authorization; both new rows pass through the live verifier, not the repair script).
- Rationale for RESOLVED at N=2: the invariant is a deterministic write-path
  property, not a statistical one. Both closes traversed the fixed writer and
  produced exact coherence; the prior defect was structural (fields never set /
  frozen), which would have manifested on any row.

Caveat recorded: `notional_usd` (top-level) is null on these rows — the canonical
field is `gross_notional_usd` (+ `notional`, `order_size_usd`). Any tooling reading
`notional_usd` reads the wrong key (this validation initially did; corrected).

## CG-F049 (short admission): STAYS PENDING — no SHORT samples yet

Both new closes are LONG. New-session book: 70L/24S cumulative is historical carry;
zero SHORT closes post-fix. Cannot confirm or refute L/S rebalance at N(short)=0.
Trigger for next pass: first SHORT close in `paper_session_140989e198032b94`.

## Dependency status

- CG-F055 GPU: RESOLVED-confirmed — `nvidia-smi`: RTX 5080, 7735 MiB used, 85% util
  (trainer actively on GPU).
- Fill path: 1 open position at validation time; fills flowing again post-rotation.

## Verification commands

```
nvidia-smi --query-gpu=name,memory.used,utilization.gpu --format=csv,noheader
.venv/bin/python3 - <<'EOF'
import json, redis; r=redis.Redis(decode_responses=True)
rows=[x for x in json.loads(r.get('v2:paper:closed_trades')) if x.get('session_id')=='paper_session_140989e198032b94']
print([(x['symbol'], x['side'], abs(x['gross_notional_usd']-x['allocated_margin_usd']*x['effective_leverage'])) for x in rows])
EOF
```

## Addendum 2026-07-30T04:55Z — CG-F049 RESOLVED on first SHORT close

ZBTUSDT short, session `paper_session_140989e198032b94` (3rd close):
entry 0.10987 (2026-07-30T02:56:12Z) → exit 0.109065 (03:41:25Z), qty 325.
- Short PnL sign+arithmetic EXACT: (0.10987−0.109065)×325 = +$0.26162500 = recorded.
- Capital invariant EXACT: 35.70775 = 35.70775 × 1.0 (err 0.0).
- Close reason `TIER_2_ADAPTIVE_POLICY_PROFIT_EXIT` — managed profit-exit ladder
  operating correctly on the short side (where the sign inversion lived).
- Session PnL turned positive (+$0.0008 net, G08 exact reconciliation).
Mechanism validated ⇒ CG-F049 RESOLVED; L/S mix remains gate-enforced (G06: 50
session shorts required), so rebalance stays continuously measured.
