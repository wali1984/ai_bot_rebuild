# Trainer Prediction Worker Root-Cause Audit

## Incident under audit
`TRAINER_PROCESS_ALIVE_PREDICTION_WORKER_CRITICAL`

## Scope and method
- Read-only audit only (no service mutations, no Redis writes/deletes, no trading actions).
- Source evidence:
	- `claude_worklog/continuous_monitoring_impl/TRAINER_INTERNAL_LIVENESS_CRITICAL_EVIDENCE.md`
	- `legacy_reference/rl/hybrid_trainer.py` code-path inspection
	- live read-only checks of log timestamps + stream state

---

## 1) Code-path mapping (expected behavior)

### A. Heartbeat thread proves process liveness, not prediction-thread liveness
- `legacy_reference/rl/hybrid_trainer.py:50362-50467`
	- Creates trainer heartbeat key/stream and publishes every 10s.
	- This can remain healthy even if prediction worker is stalled/stopped.

### B. Prediction worker lifecycle and stop signatures
- `legacy_reference/rl/hybrid_trainer.py:50468-51563`
	- Worker starts at `prediction_worker()`.
	- Stop signatures are emitted at exit:
		- `"Worker exiting after ..."` (`51556`)
		- `"Prediction worker stopped"` (`51561-51562`)

### C. Prediction cycle trace exists independently of publish count
- `legacy_reference/rl/hybrid_trainer.py:53952-53956`
	- Emits `_generate_realtime_predictions exit: produced=... reason=...` each cycle path.

### D. Proposals/signals routing can bypass global `signals:trading`
- `legacy_reference/rl/hybrid_trainer.py:17519+` (`_emit_proposal`)
	- In orchestrator publish mode, emits to proposal stream (`wma:proposals`) with no direct fallback.
- `legacy_reference/rl/proposal_schema.py:448-500`
	- `emit_proposal_to_stream(..., stream="wma:proposals")` writes proposals there.
- `legacy_reference/rl/hybrid_trainer.py:8235-8271`
	- Per-account stream fanout (`signals:trading:primary` / `signals:trading:asjad`) vs single stream.
- `legacy_reference/rl/hybrid_trainer.py:56686-56741`
	- Guard forbids direct publish in orchestrator publish mode.

### E. Deconfliction can legitimately publish zero signals
- `legacy_reference/rl/hybrid_trainer.py:52794-52960`
	- After aggregation/gates/alignment, step 4 may publish zero (`No signals to publish after deconfliction`).

---

## 2) Observed runtime contradictions (from evidence)

1. Process and heartbeat healthy, but monitor marks worker dead.
	 - Evidence repeatedly shows:
		 - `trainer_process_alive=true`
		 - `trainer_heartbeat_fresh=true`
		 - `prediction_worker_alive=false`

2. Trainer log is actively advancing with prediction/GPU activity.
	 - Latest read-only sample includes fresh `GPU_BATCH` lines at local `17:17:43`.
	 - No `"Prediction worker stopped"` / `"Worker exiting"` / `"Broken pipe"` signatures found.

3. Time basis mismatch is explicit.
	 - System clock check:
		 - `utc_now=2026-04-30 21:17:49 UTC`
		 - `local_now=2026-04-30 17:17:49 EDT`
	 - Monitor snapshots previously compared `21:xx UTC` to parsed log timestamps `17:xx` and treated them as UTC.

4. Stream-growth heuristic is biased by capped streams.
	 - `XLEN wma:proposals = 50001`
	 - `XLEN signals:trading:primary = 50000`
	 - At maxlen, `XLEN` can remain flat despite ongoing append+trim, causing false zero-growth rates.

5. Routing contradicts global-stream assumptions.
	 - Evidence previously observed `signals:trading=0` while account/proposal streams were populated.
	 - This is compatible with orchestrator/per-account routing and not sufficient proof of worker death.

---

## 3) Ranked likely root causes

### #1 (High confidence) — Monitor log timestamp timezone misinterpretation
- In `claude_worklog/tools/read_only_monitor.py:145-155`, `_parse_log_prefix_ts_ms()` parses naive log timestamp then forces `tzinfo=UTC`.
- Live environment shows trainer logs in local EDT; forcing UTC introduces ~4h skew.
- That skew makes `now_ms - last_prediction_entry_ts_ms` appear stale and flips:
	- `prediction_worker_alive=false` (staleness cutoff)
	- `trainer_internal_liveness_status=CRITICAL`

### #2 (High confidence) — Growth metric based on `XLEN` deltas at stream cap
- Liveness uses growth from `XLEN` deltas (`read_only_monitor.py:941-953`).
- At capped streams (`50000/50001`), `XLEN` may stay constant while writes continue.
- This can produce persistent `prediction_stream_growth_rate=0.0` and `proposal_stream_growth_rate=0.0` false stalls.

### #3 (Medium confidence) — Monitor criterion mixes incompatible publish surfaces
- Liveness currently treats proposal/prediction inactivity + growth stalls as critical (`read_only_monitor.py:983-991`).
- In orchestrator/per-account mode, activity may be visible in `wma:proposals` + account streams while `signals:trading`/prediction stream expectations differ.

### #4 (Low confidence) — True worker failure without signatures
- Less likely because:
	- no worker-stop signatures,
	- live GPU_BATCH logs continue,
	- proposal and primary stream latest IDs are current.

---

## 4) Read-only verification commands (for repeatability)

1) Clock/timezone reality check:
```bash
date -u '+utc_now=%Y-%m-%d %H:%M:%S %Z'
date '+local_now=%Y-%m-%d %H:%M:%S %Z'
```

2) Confirm active prediction-path log lines and absence of stop signatures:
```bash
tail -n 500 /home/wali/Desktop/AI\ BOT/logs/hybrid_trainer.log | grep -E "_generate_realtime_predictions|GPU_BATCH|DECONFLICT|Prediction worker stopped|Worker exiting|Broken pipe" | tail -n 50
```

3) Confirm stream cap conditions and latest IDs:
```bash
redis-cli XLEN wma:proposals
redis-cli XREVRANGE wma:proposals + - COUNT 1
redis-cli XLEN signals:trading:primary
redis-cli XREVRANGE signals:trading:primary + - COUNT 1
```

4) Correlate monitor snapshots to parsed log timestamps:
```bash
tail -n 5 claude_worklog/monitoring/snapshots.jsonl
```

---

## 5) Controlled recovery plan (NOT executed)

### Decision gate
- If #1/#2 are confirmed, treat current CRITICAL as monitoring false-positive; prioritize monitor fix before trainer restart.
- Restart trainer only if post-fix evidence still shows true worker stop or no fresh prediction-path logs.

### If restart is explicitly approved
1. Capture pre-restart evidence bundle (logs + snapshot tail + stream IDs).
2. Force-kill existing trainer process to prevent duplicates.
3. Clear Python cache (trainer workspace only).
4. Start trainer using mandated command:
```bash
source venv/bin/activate && nohup python3 -m rl.hybrid_trainer --mode hybrid --training-mode live --enhanced-features > logs/hybrid_trainer.log 2>&1 & echo "Trainer started: $!"
```
5. Post-start verification (read-only):
	 - fresh `GPU_BATCH` and `_generate_realtime_predictions` lines,
	 - advancing proposal/account-stream IDs,
	 - monitor liveness no longer CRITICAL for worker status.

---

## 6) V2 implications

1. Do **not** use current liveness CRITICAL as sole blocker signal for V2 go/no-go until timezone and capped-growth false-positive paths are fixed.
2. V2 liveness contract should:
	 - parse trainer log timestamps with explicit local timezone handling,
	 - avoid `XLEN` delta as primary growth signal at capped streams,
	 - prefer stream ID timestamp deltas and/or direct heartbeat from prediction thread.
3. Keep fail-safe behavior: still alert on explicit stop signatures and hard stale windows after corrected time basis.

---

## Final assessment

`TRAINER_WORKER_ROOT_CAUSE_IDENTIFIED`

Primary cause is monitoring logic (timezone interpretation + capped-stream growth heuristic), not confirmed trainer prediction-thread crash.
