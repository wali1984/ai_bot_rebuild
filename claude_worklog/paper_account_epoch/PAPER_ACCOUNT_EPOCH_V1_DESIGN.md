# PaperAccountEpochV1 — Clean $3,000 Session Rotation (Design + Spec)

Status: **DESIGN ONLY — NO STATE MUTATED.** Rotation is currently **BLOCKED** by preflight
(proof_store not initialized + 16 invalid-admission-quarantined fills + CG‑F056 phantom churn +
CG‑F063 pending fixture verification). This doc is implementation-ready so the rotation is a single
gated one-shot the moment preflight passes cleanly and the operator gives the go.

Invariants held everywhere: `paper_only=true`, `live_gate=blocked_human_only`, `routes_to_live=false`,
`places_real_order=false`, `exchange_action_taken=false`.

---

## 0. Observed current state (read-only, 2026-07-28)

- `v2:paper:session` → `paper_3000_final_pre_live_20260713T190904Z` (has `paper_session_id`, **no** `paper_account_epoch`).
- `v2:portfolio:state` → `free_margin_usd=2985.59`, `used_margin_usd=0`, `realized_pnl_usd=-14.4053`,
  `starting_equity_usd=3000`, `paper_account_epoch=null`.
- `v2:paper:closed_trades` → **92** closed trades (the historical corpus; 68 LONG / 24 SHORT, 58 symbols).
- `v2:paper:positions`/`accepted_fills` → 0 this instant but **churning** (CG‑F056).
- `v2:paper:fill_persistence_trace` → `proof_store_initialized=null`, `proof_store_backfill_complete=null`,
  `invalid_admission_quarantined=16`.

The existing keys are **global** (one account). The reset introduces **epoch-scoped** current-session
storage layered on top, so history is never emptied.

---

## 1. PaperAccountEpochV1 contract

Redis key `v2:paper:account_epoch:current` (string, JSON), plus append-only `v2:paper:account_epoch:log`:

```json
{
  "schema_version": "PaperAccountEpochV1",
  "paper_session_id": "paper_session_<sha256(prev_id|epoch|started_at)[:16]>",
  "paper_account_epoch": 2,
  "started_at": "2026-07-28T04:00:00Z",
  "starting_equity_usd": 3000.0,
  "currency": "USD",
  "paper_only": true,
  "live_gate": "blocked_human_only",
  "routes_to_live": false,
  "places_real_order": false,
  "previous_session_id": "paper_3000_final_pre_live_20260713T190904Z",
  "historical_evidence_preserved": true,
  "reset_reason": "OPERATOR_REQUESTED_CLEAN_OPERATIONAL_PAPER_SESSION",
  "archive_manifest_sha256": "<manifest hash>",
  "rotation_receipt_id": "<uuid derived, deterministic>"
}
```

`paper_account_epoch` is monotonic: `INCR v2:paper:account_epoch:counter` inside the rotation txn.
`paper_session_id` is deterministic (idempotency — test 9): a replay of the same rotation request
(same `previous_session_id` + same target epoch) yields the same id and is a no-op.

---

## 2. Three data planes (separation is the whole point)

| Plane | Storage | Written by | Read by (default) | On rotation |
|---|---|---|---|---|
| **(A) Current operational** | `v2:paper:epoch:{N}:{positions,accepted_fills,closed_trades,reservations}` + `v2:paper:epoch:{N}:portfolio_state` | new-session runtime only | frontend `scope=current_session`, current-equity calc | **new empty $3,000 set created** |
| **(B) Historical immutable** | existing global keys `v2:paper:closed_trades`, `v2:paper:accepted_fills`, reservation/receipt keys, candidate-outcome archives, training labels, quarantine/repair receipts | append-only (never rewritten) | `scope=archived`/`all`, training readers | **untouched** |
| **(C) Governed economic** | Guardian `goal_state/**` (FINDINGS/gates), cohort/checkpoint economic evidence | Guardian verifier | Guardian gates G03/G11/G13/G14, economic-readiness UI | **untouched** |

Design decisions:
- **Never `SET []` on a historical/global store.** Current session reads a *new* epoch-scoped key,
  which is empty by construction — history is a different key, so "empty current" ≠ "erased history".
- New fills/closes are written to the **epoch-scoped** (A) key **and** appended to the global historical
  (B) corpus, each row tagged `paper_session_id` + `paper_account_epoch`. Governed economic eval (C) and
  training readers keep consuming (B) → **G03/G13/G14/expectancy/PF/drawdown unchanged**.
- `v2:portfolio:state` is the *current operational* account (plane A), not evidence: rotation writes it to
  clean $3,000/0, after archiving its prior value into the manifest. Historical realized P&L is preserved
  in (B) closed_trades + the manifest — it is **not** rewritten.

---

## 3. Preflight safety gate (implemented as read-only check; must PASS before rotation)

All must hold (else `status=BLOCKED_RESET_PRECONDITION`, `state_mutated=false`, **do not delete anything**):
`valid_proof_backed_open_positions=0`, `pending_fills=0`, `pending_reservations=0`, `used_margin_usd=0`,
`reserved_margin_usd=0`, `unresolved_position_proof_rows=0`, `unresolved_accounting_reconciliation=0`,
`duplicate_fill_count=0`, `duplicate_close_count=0`, `proof_store_initialized=true`,
`proof_store_backfill_complete=true`. **Current status: BLOCKED** (last 4 fail).

Stability requirement (not in the raw list but implied by CG‑F056): positions/accepted_fills must be
proof-clean across **≥3 consecutive cycles**, not a single transient 0, because the phantom re-seeds.

---

## 4. Historical archive step (before rotation)

1. Snapshot current session: portfolio_state, positions, accepted_fills, closed_trades, reservations.
2. Build immutable manifest `v2:paper:account_epoch:archive:{prev_session_id}` (+ file under
   `~/ai_bot_local_data/paper_epoch_archives/`): previous `paper_session_id`; start/end account values;
   accepted-fill count + per-row SHA-256 + list hash; open/closed position counts + hashes; closed-trade
   count + hashes; reservation count + hashes; checkpoint generation/id; cohort id; economic-gate evidence
   hashes (G03/G11/G13/G14 snapshots); candidate-outcome high-watermarks; archive timestamp; **manifest SHA-256**.
3. **Read-back verification**: re-read every archived record, recompute hashes, assert byte-identical.
   On mismatch → abort, `state_mutated=false`.
4. Persist session-rotation receipt `v2:paper:account_epoch:receipt:{epoch}`.

---

## 5. Atomic rotation (single transaction — Lua `EVAL`)

One Lua script (atomic; partial rotation impossible). Pseudocode:

```
-- KEYS: current_pointer, epoch_counter, receipt, portfolio_state_new, epoch prefix
-- ARGV: expected_prev_session_id, started_at, starting_equity(3000), manifest_sha, idempotency_key
1. re-assert preconditions snapshot hash == preflight hash  (else return BLOCKED)
2. if current_pointer.paper_session_id already == deterministic_new_id: return NOOP (idempotent, test 9)
3. epoch = INCR epoch_counter
4. new_id = "paper_session_" .. sha(prev|epoch|started_at)[:16]
5. SET v2:paper:epoch:{epoch}:portfolio_state  = {equity=3000, wallet=3000, free=3000, used=0, reserved=0, realized=0, unrealized=0, session_id=new_id, epoch=epoch}
6. SET v2:paper:epoch:{epoch}:positions=[]  accepted_fills=[]  closed_trades=[]  reservations=[]
7. SET v2:portfolio:state = clean $3000 state (session_id=new_id, epoch=epoch)   -- current operational face
8. SET v2:paper:account_epoch:current = PaperAccountEpochV1 doc
9. SET v2:paper:account_epoch:receipt:{epoch} = rotation receipt
10. -- DO NOT touch v2:paper:closed_trades / accepted_fills (global history) --
return {ok=true, epoch=epoch, session_id=new_id}
```

Use `EVAL` (single round-trip atomic) or the project's canonical durable-transaction wrapper if one exists
(the reader audit will confirm; prefer it over raw Redis per project convention).

---

## 6. Runtime scoping (paper loop — Codex-owned file; coordinate before editing)

Every new fill/position/close/reservation/wallet-mutation/accounting-receipt must carry `paper_session_id`
+ `paper_account_epoch`, and write to the epoch-scoped (A) keys. Current operational equity is computed
**only** from the current epoch; training + economic readers keep reading global (B)/(C). This is the one
change inside `v2_trade_management_paper_loop.py` — **must be coordinated with the Codex paper-loop owner**
(they're mid-fix on CG‑F056), and gated behind the same "proof-store regression verified fixed" bar.

---

## 7. Frontend + API

- Endpoints gain `scope ∈ {current_session, archived, all}`, default **current_session**; response adds
  `paper_session_id`, `paper_account_epoch`, `scope`, `starting_equity_usd`,
  `historical_rows_excluded_from_current_view`, `historical_evidence_preserved`.
- React Query/SWR/`useRealtimeResource` cache keys **include `paper_session_id`**; on pointer change,
  invalidate portfolio/trade/chart/P&L queries; realtime WS payloads carry `paper_session_id`; frontend
  **ignores** any payload whose session id ≠ current. (Reader audit enumerates every key to change.)
- Dashboard shows **Current paper session** (equity/free/used/reserved/realized/unrealized/positions/trades
  + "Current paper session" badge) **separately** from **Governed economic evidence** (historical closes,
  expectancy, PF — unchanged, "not reset"). A clean session must never read as economically certified.

---

## 8. Required tests (12) — authored against a Redis fixture, `state_mutated=false` in dry-run

1 clean-start→$3000 · 2 history byte/hash-identical · 3 default scope hides old rows · 4 archived scope
retrievable · 5 training reader intact · 6 governed cohort unchanged · 7 open-position precondition blocks
(no mutation) · 8 uninitialized proof-store blocks (no removal) · 9 idempotent replay = 1 session · 10
accounting: $3000/0/0 + conservation · 11 session isolation (new fill ≠ archived totals) · 12 frontend
cache: no old-session rows leak.

---

## 9. Deployment sequence (gated)

1 reader audit (running) → 2 implement session-aware storage/APIs → 3 run 12 tests → 4 **dry-run report,
state_mutated=false** → 5 independent verify (history preserved, gates unchanged, preconditions pass) →
6 one immutable build → 7 capture pre-rotation state+hashes → 8 execute atomic rotation → 9 restart only
services that need it, after cred + proof-store preflight → 10 observe ≥3 paper cycles.

**Blocking gate before step 8:** preflight PASS (§3) which today requires the Codex lane to land
CG‑F056/CG‑F063 (phantom churn → 0 quarantined, proof_store initialized+backfilled, ≥3 clean cycles).

---

## 10. Rollback

- Rotation writes only new keys + `v2:portfolio:state`. Rollback = restore `v2:portfolio:state` and
  `v2:paper:account_epoch:current` from the pre-rotation snapshot captured in step 7; delete the new
  `v2:paper:epoch:{N}:*` keys and the receipt; the epoch counter stays advanced (monotonic, harmless).
- Global historical (B) and governed (C) planes are never touched, so there is nothing to roll back there.
- Frontend rolls back by pointer restore (session id reverts → caches invalidate to prior session).

---

## Appendix A — Reader map (audit results, read-only)

**Core finding:** the *writer* already stamps `paper_session_id` on every row
(`cli/v2_portfolio_state_publisher.py:455,672,993`) and scalars are session-scoped at the source
(`clean_session_valid_equity_usd`, `services/portfolio/canonical_pnl.py:120-292`). The leak is that
*readers pull raw lists with no session filter*. So the whole surface becomes session-scoped by
**filtering on the already-present `paper_session_id`** + stamping it into payloads that lack it.

**Backend — highest-risk raw-list readers (session-scope + tag + add `scope`, default current_session):**
1. `GET /api/v2/paper/status` — `market_contracts.py:13326` (closed_trades[:200], equity_curve, counts) — #1 most-consumed.
2. `_redis_pnl_windows` / `_redis_accuracy_status` — `:3197` / `:3287` (feed `/ai/predictions`, `/adaptive-capital/dashboard`, portfolio overlay) — win-rate/PF over all epochs.
3. `_load_paper_activity_payload` — `:13164` (`/paper/activity` + WS, `/account/positions`, `/execution/{orders,executions,audit-events}`).
4. `GET /api/v2/paper/fills` `:16075`; `/api/v1/paper-trades` `api/v1/paper.py:97`; iOS `mobile.py:1388-1568`.
5. `GET /api/v2/account/positions` `:7873` (account-scoped ≠ session-scoped).

**Frontend — single choke point:** `hooks/useRealtimeResource.ts:65-67` cacheKey `${mode}:${shape}:${url}`
→ inject active `paper_session_id`; also bootstrap key `lib/realtime/resourceClient.ts:65`, the 90-sec
`lastGoodRef` (`hooks/usePaperActivityStream.ts:68-88`), and module singleton `stores/traderRealtimeStore.ts:33`
→ clear/invalidate on session change. No React Query/SWR — this hook is the whole surface.

**WS:** the shared `/api/v2/realtime/ws` `?path=` dispatch streams any leaky GET, so tag payloads at source
(#3,#4,#6,#7 in the audit) — paper-activity WS (`:13248`) and streamed `/paper/status` (`:13501`) carry NO session id today.

**Seed point:** `v2:paper:session` pointer has `paper_session_id` but **no `paper_account_epoch`** — add that field
here (`read at mobile.py:1696`, `market_contracts.py:4020`) and readers pick up the new epoch.

**Governed-gate decision (locked per task intent):** Guardian G13/G14 + expectancy/PF/drawdown stay
**`scope=all` (UNCHANGED, not reset)** — the task explicitly forbids resetting them. Only the CURRENT operational
view is session-scoped; governed economic readers keep reading full history. This resolves the one ambiguity the audit flagged (`admin.py:1566-1577,1625-1632`).

**Do NOT use the existing destructive reset tools** (they wipe, violating preserve-history): `POST /api/v2/admin/paper/session-reset`
(`admin.py:1465-1472` deletes 6 keys) and `cli/v2_final_pre_live_3000_paper_reset.py`. The epoch rotation replaces them.

## Appendix B — Preflight tool

`tools/paper_epoch_preflight.py` — read-only, reproducible gate (run under the backend venv). Current verdict:
**BLOCKED** on `unresolved_position_proof_rows` (16 quarantined), `reserved_margin_usd` (null),
`proof_store_initialized` (null), `proof_store_backfill_complete` (null). Reconciliation basis =
`realized_net_pnl_usd` (matches Guardian G08 at $0.00). Re-run each cycle; PASS requires ≥3 consecutive clean cycles.
