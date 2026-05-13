# V2_DATA_PLANE_AND_SCRIPT_MIGRATION_BACKLOG — Primary Objective Report

- Date: 2026-05-12
- Branch: master
- Operator: Wali
- Mode: paper / shadow / read_only
- Live trading: BLOCKED (blocked_human_only)
- Scope: AI BOT REBUILD only; legacy is read-only observed; no exchange action; no leverage/margin change; no old-Redis writes.

## 1. Purpose

Define and lock the next primary V2 live-like paper/shadow objective: the **Data Plane and Script Migration Backlog**. This backlog is the canonical, lane-grouped queue of remaining V2 work to (a) stand up a complete shadow data plane that mirrors legacy inputs without touching them and (b) migrate legacy scripts that V2 depends on into V2-owned, version-pinned, read-only-observing equivalents — preserving evidence integrity, the non-drift governor lock, and the live-blocked posture.

Website / GUI work is explicitly **support-only** for this objective. The data plane and migrated scripts must reach paper/shadow readiness before the GUI is allowed to consume them as primary surfaces.

## 2. Constraints (inherited, non-negotiable)

- Live trading remains BLOCKED — `blocked_human_only`.
- Legacy code under `./legacy_reference/**` and `../AI BOT/**` is read-only observed.
- No writes to old Redis keys. V2 uses `V2_REDIS_PREFIX` only.
- No place/cancel orders, no leverage change, no margin-mode change.
- No mutation of the legacy trainer venv / CUDA / PyTorch stack.
- Trainer access is via subprocess / file / Redis / artifact adapter only.
- Evidence Integrity Rule applies: every backlog item must land with raw evidence pointers when executed.
- Non-Drift Governor Lock remains authoritative for lane priority.
- Planner output is BEGIN_FILE / END_FILE blocks only; harness materializes.

## 3. Lanes (canonical)

The backlog is organized into seven lanes. Each lane has an owner contract, a definition of done, and a paper/shadow gate. No item promotes to "ready" without raw evidence and Codex review at the gate.

### Lane A — Shadow Ingest Plane
Mirror every legacy input stream into a V2-owned shadow path without touching legacy.

- A1. Inventory every legacy data producer (exchange WS, REST pollers, CoinAnk bridges, on-chain feeds, sentiment feeds).
- A2. For each producer, record: source URL/host, auth mode, cadence, payload schema sample, legacy Redis key, legacy log path.
- A3. Stand up a V2 shadow subscriber per producer that writes only to `V2_REDIS_PREFIX:shadow:<producer>` and a parquet/jsonl evidence sink under `./raw_evidence/shadow/<producer>/`.
- A4. Verify drift: V2 shadow vs legacy snapshot diff for at least one trading session, with freshness lag recorded.
- A5. Backpressure + reconnect policy documented and observed in a forced-disconnect drill (paper).

### Lane B — Feature Freshness & Snapshot
Make every feature used by signal/confidence/risk explainable from a V2-owned snapshot.

- B1. Enumerate every feature consumed by trainer + orchestrator + risk gateway.
- B2. For each feature, record: input producers (Lane A), transform function reference, freshness SLA, staleness alarm threshold.
- B3. V2 snapshot writer emits per-tick feature snapshot to `V2_REDIS_PREFIX:snapshot:features:<symbol>` and rolling parquet.
- B4. Snapshot replayability: any signal can be re-derived from its snapshot pointer alone.
- B5. Freshness monitor wired into Monitor Center (shadow only).

### Lane C — Script Migration Backlog
Convert legacy scripts V2 depends on into V2-owned read-only-observing equivalents.

- C1. Coverage manifest from `./audits/**` and `coverage-audit` artifacts; every legacy script classified used / unused / duplicate / unknown.
- C2. For each `used` script, decide: (i) migrate to `./v2/scripts/<name>.py`, (ii) wrap behind subprocess adapter, or (iii) deprecate after V2 native replacement.
- C3. Each migrated script ships with: input schema, output schema, evidence pointer, dry-run mode, paper-only guard, kill switch.
- C4. Legacy original remains untouched; migration parity diff is the evidence.
- C5. Codex adversarial review at lane gate.

### Lane D — Trainer Adapter Hardening
Stabilize the subprocess boundary to the legacy trainer.

- D1. Read-only status endpoint: returns model version, checkpoint hash, last update, freshness.
- D2. Export endpoint: emits prediction stream to V2 shadow Redis only.
- D3. No-write contract: adapter refuses any mode other than `read_only` / `status` / `export`.
- D4. Watchdog: stale prediction stream raises Monitor Center alarm; signals derived from stale predictions are blocked at risk gateway in paper.
- D5. Checkpoint promotion path is documented but DISABLED for live.

### Lane E — Risk Gateway Shadow
Make the risk gateway evaluate every shadow signal as if live, but emit only paper verdicts.

- E1. Rule set parity check against legacy risk: each rule has source legacy line range or "V2-new" tag.
- E2. Mandatory rules: kill switch on, stop required, leverage cap, daily loss cap, liquidation-distance floor, cross-margin block.
- E3. Every verdict logged to audit ledger with: rule id, inputs, decision, reason, config version.
- E4. Override path requires explicit human approval token; default deny.
- E5. Live-trading toggle remains hard-coded BLOCKED.

### Lane F — Audit Ledger & Replay
Make every paper/shadow action reconstructible.

- F1. Append-only ledger schema: event id, ts, actor, action, inputs hash, outputs hash, evidence pointer.
- F2. Replay tool: from ledger + snapshots, reproduce signal → risk → (paper) execution decision deterministically.
- F3. Divergence report: any non-deterministic replay flags a P0 evidence-integrity defect.
- F4. Retention + integrity hash chain.

### Lane G — Monitor Center Wiring (support-only for GUI)
Surface lanes A–F in Monitor Center as read-only panels. GUI is **support-only** here.

- G1. Per-lane health card: green/yellow/red with raw evidence pointer.
- G2. No GUI control writes; all panels are read-only against `V2_REDIS_PREFIX:*` and ledger.
- G3. Mobile-safe layout deferred; desktop-first acceptable for this milestone.

## 4. Prioritization (paper/shadow first)

Order of execution for the next milestone window:

1. Lane A — Shadow Ingest Plane (blocks everything downstream).
2. Lane B — Feature Freshness & Snapshot.
3. Lane D — Trainer Adapter Hardening (parallelizable with B).
4. Lane C — Script Migration Backlog (parallelizable with A/B once inventory exists).
5. Lane E — Risk Gateway Shadow.
6. Lane F — Audit Ledger & Replay.
7. Lane G — Monitor Center wiring (support-only; last).

## 5. Definition of Done (per lane)

A lane is "ready" only when:

- All items above are completed with raw evidence under `./raw_evidence/**` or `./claude_worklog/**`.
- Codex adversarial review report stored at `claude_worklog/final_readiness/v2_data_plane_and_script_migration_backlog/<lane>/CODEX_REVIEW.md`.
- A forced-failure drill has been run in paper/shadow.
- The non-drift governor lock has been re-asserted with this lane's outputs.
- Live-trading remains BLOCKED in the resulting state.

## 6. Evidence pointers (to be filled at execution time)

Each backlog item, when executed, must land with:
- claim
- raw evidence pointer (file:line / Redis key / log path / command output)
- verification command
- confidence
- missing evidence (if any)

This planner emits the backlog itself; raw evidence is collected at item execution and recorded in the lane subfolders.

## 7. Out of scope for this objective

- Any live order flow, leverage change, or margin change.
- Any mutation of legacy code, legacy Redis, legacy venv, or `../AI BOT/**`.
- Any GUI feature beyond read-only Monitor Center panels (Lane G).
- Any mobile/iPhone packaging (deferred; APIs must remain mobile-safe).
- Any model retraining decisions (trainer remains read-only observed).

## 8. Governor & policy alignment

- Non-Drift Governor Lock: this objective is the lane-priority head item for the next milestone window.
- Documentation Governance: this report is the canonical entry; lane subfolders inherit policy.
- Always-On Claude/Codex Runtime: utilization allowed only on lane execution tasks with raw-evidence outputs.
- Planner Output Policy: BEGIN_FILE / END_FILE only.

## 9. Readiness statement

The backlog is defined, lane-grouped, prioritized, and gated. No execution claims are made in this planner emission; readiness for execution is what is being asserted. Live remains BLOCKED. Legacy remains read-only observed. AI BOT REBUILD is the only writable workspace.

V2_DATA_PLANE_AND_SCRIPT_MIGRATION_BACKLOG is **defined and ready for lane-by-lane execution**.
