# PUBLIC_HOSTING_AND_TELEMETRY_BRIDGE — Primary Objective Report

- Date: 2026-05-12
- Operator: Wali (wajidali1984@hotmail.com)
- Branch: master
- Scope: AI BOT REBUILD (`./v2/**`, `./claude_worklog/**`, `./tools/**`)
- Live trading state: **BLOCKED — human-only override**
- Legacy: read-only observed; no legacy edits authorized in this run
- Website work: support-only (no design/UX scope changes; only contract for telemetry consumption)

## 1. Objective

Establish a **publicly addressable read-only telemetry bridge** that exposes V2 paper/shadow runtime state (signals, predictions, risk decisions, monitor health) to an external hosted website surface, without ever opening a write path back into V2 control plane, legacy Redis, exchange APIs, or live-trading toggles.

This is the next primary V2 live-like paper/shadow objective because:
- V2_BACKTEST_AND_PAPER_MVP_READY is Codex PASS (per project memory).
- Always-on Claude/Codex runtime guardrails landed (commits `97378f6`, `1af9dd5`, `cedaf48`).
- Operator dashboards already emit JSON payloads under `claude_worklog/final_readiness/active_autonomous_dispatch/latest/operator_dashboard_payload.json` and `claude_worklog/final_readiness/always_on_claude_codex_runtime/latest/operator_dashboard_payload.json`; the missing piece is a **safe outward-facing read channel**.

## 2. Non-Goals (explicitly excluded this primary)

- No live trading enablement.
- No order placement / cancellation / leverage / margin mutation.
- No write to old Redis keys.
- No mutation of `../AI BOT/**` or any `.env` / secrets.
- No design changes to the public website (treated per Claude Design Handoff policy: visual reference only; Code wires real V2 payloads).
- No mobile push notifications in this primary (deferred to mobile/iPhone readiness milestone).
- No authentication of viewers in this primary — public surface is **read-only sanitized**, and any operator-write surface remains local-only behind the existing approval flow.

## 3. Architecture (paper/shadow only)

```
+---------------------+        +----------------------+        +----------------------+
| V2 paper/shadow     |  --->  | Telemetry Bridge     |  --->  | Public Hosting       |
| runtime + monitors  |  read  | Exporter (local)     |  push  | Static/edge surface  |
| (FastAPI + Redis    |  only  | - sanitizer          |  only  | - JSON snapshots     |
|  v2_* prefix only)  |        | - redactor           |        | - read-only viewer   |
|                     |        | - signed snapshot    |        | - no callbacks       |
+---------------------+        +----------------------+        +----------------------+
        ^                                                                 |
        |                                                                 |
        +--------------------- NO inbound write path ---------------------+
```

Key invariants:
- **One-way push.** The exporter writes signed JSON snapshots; the public surface never opens a socket back to V2.
- **Sanitizer enforced before export.** No private keys, no exchange API keys, no internal IPs, no operator email, no Redis URLs, no checkpoint paths, no config-admin secrets.
- **V2_REDIS_PREFIX scoping.** Exporter only reads `v2_*` keys; legacy `live_*` / unprefixed keys are never read.
- **Live-blocked banner is part of the schema.** Public viewer must render `live_state: "BLOCKED_HUMAN_ONLY"` from snapshot; absence of the field invalidates the snapshot.

## 4. Bridge Components

### 4.1 Local exporter
- Path (planned): `v2/services/public_telemetry_exporter/`
- Runtime: lightweight V2 control-plane venv (subprocess boundary preserved per Protected Runtime Policy; trainer venv untouched).
- Inputs (read-only):
  - `claude_worklog/final_readiness/active_autonomous_dispatch/latest/operator_dashboard_payload.json`
  - `claude_worklog/final_readiness/always_on_claude_codex_runtime/latest/operator_dashboard_payload.json`
  - V2 paper-mode signal/prediction read API (`/v2/api/paper/signals`, `/v2/api/paper/predictions`, `/v2/api/monitors/status`) — all already read-only.
  - V2 risk gateway read API (`/v2/api/risk/state`) — must report `mode: paper`.
- Output: signed JSON snapshot bundle written to `claude_worklog/final_readiness/public_hosting_and_telemetry_bridge/latest/snapshots/` and pushed to public hosting.

### 4.2 Sanitizer / redactor
Mandatory denylist (block-export) fields:
- any field containing `api_key`, `secret`, `token`, `password`, `private`, `seed`
- any value matching exchange API key shape
- any absolute filesystem path under `/home/wali/`
- any operator email or PII
- any field under `legacy_*`, `live_*`, or unprefixed Redis keys
- any field that resolves to a credentials file or `.env`

Allowlist (export-eligible):
- signal id, symbol, side, confidence (calibrated), model version, checkpoint hash (truncated), feature freshness ms, paper PnL (paper-only), monitor name + status + last_run + last_success/failure age, risk decision (allow/block reason code), live_state banner.

### 4.3 Snapshot signing
- Snapshot includes `snapshot_id`, `generated_at_utc`, `git_head`, `v2_mode` (must equal `paper` or `read_only`), `live_state` (must equal `BLOCKED_HUMAN_ONLY`), `schema_version`.
- Signed with a local-only Ed25519 key (key never leaves operator host; only public key shipped to viewer for verification).
- Public viewer rejects unsigned snapshots and snapshots older than configured TTL.

### 4.4 Public hosting surface (support-only scope)
- Static-only edge hosting (no server-side execution, no DB, no inbound API).
- Renders the latest valid snapshot only.
- Displays prominent `LIVE TRADING: BLOCKED` banner sourced from the snapshot, not hard-coded.
- Treats the snapshot as **navigation aid only** per Evidence Integrity Rule; raw evidence pointers (file paths inside the repo) are shown but not fetched remotely.

## 5. Evidence Integrity

Per Evidence Integrity Rule, each export field must include a raw evidence pointer when the public viewer claims a runtime fact:

| Claim                          | Raw evidence pointer                                                                                  | Verification command                                              |
|--------------------------------|-------------------------------------------------------------------------------------------------------|-------------------------------------------------------------------|
| Live trading is blocked        | `claude_worklog/final_readiness/non_drift_governor_lock/latest/CLAUDE_AUTOMATION_NON_DRIFT_GOVERNOR_LOCK_REPORT.md` | `grep -n "BLOCKED" claude_worklog/final_readiness/non_drift_governor_lock/latest/CLAUDE_AUTOMATION_NON_DRIFT_GOVERNOR_LOCK_REPORT.md` |
| Always-on runtime healthy      | `claude_worklog/final_readiness/always_on_claude_codex_runtime/latest/always_on_runtime_state.json`   | `jq '.status' claude_worklog/final_readiness/always_on_claude_codex_runtime/latest/always_on_runtime_state.json` |
| Active autonomous dispatch ok  | `claude_worklog/final_readiness/active_autonomous_dispatch/latest/primary_dispatch_state.json`        | `jq '.state' claude_worklog/final_readiness/active_autonomous_dispatch/latest/primary_dispatch_state.json` |
| Documentation governance ok    | `claude_worklog/final_readiness/documentation_governance/latest/doc_update_policy.json`               | `jq '.policy_version' claude_worklog/final_readiness/documentation_governance/latest/doc_update_policy.json` |
| V2 mode = paper                | `v2/services/public_telemetry_exporter/runtime_mode.json` (planned)                                   | `jq '.v2_mode' v2/services/public_telemetry_exporter/runtime_mode.json` |

Missing evidence (to be produced before exporter ships):
- `v2/services/public_telemetry_exporter/runtime_mode.json` — does not yet exist; first exporter run must emit it.
- Snapshot signing keypair — to be generated locally; only public key committed.

## 6. Risk Surface & Mitigations

| Risk                                              | Mitigation                                                                 |
|---------------------------------------------------|----------------------------------------------------------------------------|
| Snapshot leaks secret                             | Sanitizer denylist + unit test that asserts denylist fields never appear   |
| Public viewer becomes a control plane             | Static hosting only, no inbound API, no auth tokens accepted               |
| Stale snapshot misleads observer                  | Viewer enforces `generated_at_utc` TTL; stale → display "STALE — DO NOT TRUST" |
| Snapshot tampering in transit                     | Ed25519 signature verified client-side                                     |
| Exporter accidentally reads legacy keys           | Hard prefix filter `v2_*`; integration test asserts no legacy reads        |
| Exporter accidentally writes back to Redis        | Exporter uses Redis read-only connection; write commands raise at adapter  |
| Operator confusion paper vs live                  | `live_state: BLOCKED_HUMAN_ONLY` banner mandatory; missing → snapshot invalid |

## 7. Codex Review Gate

Before this primary is marked complete and the exporter is enabled, Codex must adversarially review:
1. Sanitizer denylist completeness
2. Snapshot schema (must include `v2_mode`, `live_state`, `git_head`, `signature`, `schema_version`)
3. Read-only assertion on all Redis/legacy access paths
4. Public viewer absence of any inbound write surface
5. Verification commands in §5 succeed against current repo

## 8. Status

- Plan: **drafted (this report)**
- Exporter scaffolding: **not yet created** (next step is to land `v2/services/public_telemetry_exporter/` with sanitizer + tests, behind paper-only gate).
- Public hosting surface: **support-only contract defined**; no website code touched in this turn.
- Live trading: **BLOCKED — human-only override**.
- Legacy: **read-only observed**; no legacy file edits in this turn.

## 9. Confidence

- Architecture invariants: **high** (one-way push, signed snapshots, denylist sanitizer)
- Coverage of evidence pointers: **medium** — runtime_mode.json and signing keypair still missing; flagged in §5.
- Readiness to ship exporter: **not yet** — this report defines the contract; implementation + Codex gate still required.

This document is a navigation aid per Evidence Integrity Rule; final acceptance requires raw verification of §5 commands and Codex review per §7.
