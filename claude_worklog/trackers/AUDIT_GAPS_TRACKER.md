# AI BOT V2 — Persistent Audit-Gap Tracker

**Source audit:** [INDEPENDENT_FULL_AUDIT.md](../../INDEPENDENT_FULL_AUDIT.md) (2026-05-20)
**Tracker started:** 2026-05-20
**Status semantics:** `Open` · `InProgress` · `Done` · `WontFix`
**Priority semantics:**
- **P0** — blocks operator confidence in V2 as a production replacement.
- **P1** — required for V2 to function autonomously without legacy.
- **P2** — quality / parity items that can ship after P0/P1.

Each row points to (a) the corresponding `V2_*_READY` packet gate
that would close the finding and (b) the canonical evidence
location. The structured form lives in
[AUDIT_GAPS_TRACKER.json](AUDIT_GAPS_TRACKER.json).

---

## Active lanes (running now)

| Lane | Status | GO_NO_GO | Closes finding |
| --- | --- | --- | --- |
| Lane 1 | **Done** (2026-05-20) | `V2_LIVE_CANARY_DRY_RUN_APPROVAL_BINDING_REMEDIATION_READY` | AUD-013 |
| Lane 2 | **Done** (2026-05-20) | `V2_PUBLIC_WEBSITE_BACKEND_ONLINE_READY` | AUD-008, AUD-009 |

---

## Findings

### P0 — Production-replacement blockers

| ID | Title | Status | Closing gate |
| --- | --- | --- | --- |
| AUD-001 | Zero live ingestors running (Binance / KuCoin / CoinAPI / CoinAnk / LunarCrush / TokenMetrics / AlphaVantage) | Open | `V2_NATIVE_LIVE_INGESTORS_PARITY_READY` (suite of 13 individual ingestor-parity packets) |
| AUD-002 | RL trainer not ported (`hybrid_trainer.py` 57k LOC has no V2 native loop; rl_core declares itself partial) | Open | `V2_RL_TRAINER_PORT_PHASE_1_READY` (env/reward/state-space) → ...PHASE_2_READY (PPO/MASA loop) → ...PHASE_3_READY (checkpoint promotion) |
| AUD-003 | Live trader not ported (`trading/trader.py` 24k LOC; 35 trading files missing) | Open | Already gated; final approval requires the existing live-canary gate cascade + dedicated trader-port packet `V2_LIVE_TRADER_NATIVE_LANE_PHASE_1_READY` |
| AUD-004 | AI model not loaded; paper loop uses heuristic decisions, not the trained PPO/MASA policy | Open | `V2_RL_CHECKPOINT_PROMOTION_PIPELINE_READY` |
| AUD-005 | Live-canary scaffold remains dry-run only; no real order has ever shipped | Open by design | Final operator+codex flow (out of scope for any single packet; requires both operator action and dedicated `V2_LIVE_CANARY_FIRST_REAL_ORDER_READY`) |

### P1 — Autonomy / parity

| ID | Title | Status | Closing gate |
| --- | --- | --- | --- |
| AUD-006 | Trader components (stealth stops, dynamic TP, hedge engines, smart entry gate) missing | Open | `V2_TRADER_COMPONENTS_NATIVE_LANE_PHASE_*_READY` |
| AUD-007 | Feature pipeline runs from snapshots, not live feeds | Open | Tied to AUD-001 (ingestors must come up first) |
| AUD-008 | FastAPI backend was not running | **Done** | `V2_PUBLIC_WEBSITE_BACKEND_ONLINE_READY` (2026-05-20) |
| AUD-009 | `REDIS_URL` / `LEGACY_REDIS_URL` env not configured for V2 processes | **Done** | Same packet as AUD-008 (env injected via systemd unit + start script) |
| AUD-010 | No watchdog auto-restart for V2 services | Open | `V2_CONTROL_PLANE_WATCHDOG_AUTORESTART_READY` |
| AUD-011 | No Telegram alerts in V2 | Open | `V2_TELEGRAM_ALERTS_NATIVE_READY` |
| AUD-012 | No database (SQLite / Postgres) set up; `alembic` migrations never run | Open | `V2_PERSISTENCE_DB_SETUP_READY` |
| AUD-013 | Dry-run executor's approval binding broken on operator's prose file | **Done** | `V2_LIVE_CANARY_DRY_RUN_APPROVAL_BINDING_REMEDIATION_READY` (2026-05-20) |

### P2 — Package & config alignment

| ID | Title | Status | Closing gate |
| --- | --- | --- | --- |
| AUD-014 | Critical missing packages in V2 venv: `torchaudio`, `torchvision`, `pytorch_triton`, `grpcio`, `pynvml`, `nvidia_ml_py`, `trio`, `trio_websocket`, `nest_asyncio`, `tzdata`, `retrying` | Open | `V2_VENV_PARITY_PHASE_1_READY` |
| AUD-015 | Version drift: `pandas 3.0.2` (V2) vs `2.3.3` (legacy); breaks any legacy DataFrame reads | Open | `V2_PANDAS_PIN_DOWNGRADE_OR_AUDIT_READY` |
| AUD-016 | Version drift: `pydantic 2.9.2` (V2) vs `2.12.5` (legacy) | Open | bundled with AUD-014 |
| AUD-017 | Version drift: `redis-py 5.0.8` (V2) vs `7.1.0` (legacy) — async API differences | Open | bundled with AUD-014 |
| AUD-018 | Version drift: `fastapi 0.115.0` (V2) vs `0.128.0` (legacy) | Open | bundled with AUD-014 |
| AUD-019 | Version drift: `uvicorn 0.30.6` (V2) vs `0.40.0` (legacy) | Open | bundled with AUD-014 |
| AUD-020 | Torch nightly-dev (legacy) vs stable (V2): checkpoint loading risk if nightly-only APIs are used | Open | `V2_RL_CHECKPOINT_TORCH_PARITY_READY` |
| AUD-021 | Legacy `config.py` (6,006 lines) has no V2 equivalent; V2 `settings.py` is 26 lines | Open | `V2_RUNTIME_CONFIG_PARITY_PHASE_*_READY` |

---

## Tracker rules

1. Every new finding MUST get an `AUD-NNN` ID and an entry in
   `AUDIT_GAPS_TRACKER.json` BEFORE it is referenced in any
   packet.
2. A finding moves to `Done` only after a corresponding
   `V2_*_READY` packet ships, the GO_NO_GO file is written, and
   Codex passes. Reverting a finding to `Open` requires a fresh
   audit observation.
3. The tracker is append-mostly: rows are never deleted. If a
   finding turns out to be incorrect, mark it `WontFix` and link
   the supersession in the notes field.
4. Codex reviewers MUST read this tracker before issuing any
   live-canary or production-equivalence approval.

## Cross-references

- Independent audit source: [INDEPENDENT_FULL_AUDIT.md](../../INDEPENDENT_FULL_AUDIT.md)
- Lane 1 artifacts: [v2_live_canary_dry_run_approval_binding_remediation/latest/](../final_readiness/v2_live_canary_dry_run_approval_binding_remediation/latest/)
- Lane 2 artifacts: [v2_public_website_backend_online/latest/](../final_readiness/v2_public_website_backend_online/latest/)
- Prior dry-run service gate: [v2_live_canary_dry_run_service/latest/](../final_readiness/v2_live_canary_dry_run_service/latest/)
- Prior bypass-remediation gate: [v2_live_canary_execution_adapter_private_signed_post_bypass_remediation/latest/](../final_readiness/v2_live_canary_execution_adapter_private_signed_post_bypass_remediation/latest/)
