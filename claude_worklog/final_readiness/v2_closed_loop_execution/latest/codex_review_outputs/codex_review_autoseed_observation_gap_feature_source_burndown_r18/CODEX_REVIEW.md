# Codex Review: codex_review_autoseed_observation_gap_feature_source_burndown_r18

GO/NO-GO: `V2_AUTONOMOUS_OBSERVATION_GAP_FEATURE_SOURCE_BURNDOWN_CODEX_FAIL`

## Command

```text
/home/wali/.local/bin/codex exec review ...
```

## Blockers

- 1. `liquidation_observation_aggregator.py` — add public `read_v2_liquidation_per_symbol_from(redis_client, symbol)` so the builder can reuse its existing Redis client (no double-connect).
- 1. `liquidation_observation_aggregator.py` — add public `read_v2_liquidation_per_symbol_from(redis_client, symbol)` so the builder can reuse its existing Redis client (no double-connect).

## Raw Output (tail)

```text
   190	        if _safe_write(
   191	            r, f"{V2_REDIS_PREFIX}orchestrator:proposals",
   192	            json.dumps(proposals_payload), ex=600,
   193	        ):
   194	            keys_written.append(f"{V2_REDIS_PREFIX}orchestrator:proposals")
   195	        if _safe_write(
   196	            r, f"{V2_REDIS_PREFIX}orchestrator:decisions",
   197	            json.dumps(decisions_payload), ex=600,
   198	        ):
   199	            keys_written.append(f"{V2_REDIS_PREFIX}orchestrator:decisions")
   200	        # Paper signals
   201	        sig_payload = [
   202	            {"side": w["side"], "symbol": w["symbol"],
   203	             "winner_proposal_id": w["winner_proposal_id"],
   204	             "expected_move_after_cost_bps": w["winner_expected_move_after_cost_bps"],
   205	             "confidence_calibrated": w["winner_confidence_calibrated"]}
   206	            for w in bucket_winners
   207	        ]
   208	        if _safe_write(
   209	            r, f"{V2_REDIS_PREFIX}signals:paper",
   210	            json.dumps(sig_payload), ex=600,
   211	        ):
   212	            keys_written.append(f"{V2_REDIS_PREFIX}signals:paper")
   213	    classification = (
   214	        "V2_ORCHESTRATOR_PRODUCTION_OK"
   215	        if proposals else
   216	        ("BLOCKED_BY_REDIS_UNAVAILABLE" if r is None else
   217	         "NO_OPEN_GATE_PROPOSALS_PAPER_ONLY")
   218	    )
   219	    status = {
   220	        "worker_id": "v2_orchestrator_arbitration_loop",
   221	        "schema_version": "v2_orchestrator_arbitration_live_v1",
   222	        "started_at": started,
   223	        "finished_at": _utc_iso(),
   224	        "predictions_seen": len(predictions),
   225	        "proposals_arbitrated": len(proposals),
   226	        "predictions_held_by_paper_fill_gate": len(held_by_gate),
   227	        "held_by_paper_fill_gate": held_by_gate,
   228	        "bucket_winners_count": len(arb.bucket_winners),
   229	        "stale_proposal_count": len(arb.stale_proposal_ids),
   230	        "deconflict_reason": getattr(deconflict, "conflict_reason", None),
   231	        "deconflict_selected_side": getattr(deconflict, "selected_side", None),
   232	        "v2_orchestrator_keys_written": keys_written,
   233	        "v2_orchestrator_keys_written_count": len(keys_written),
   234	        "classification": classification,
   235	        "live_gate": "blocked_human_only",
   236	        "live_symbols": [],
   237	        "approves_live": False,
   238	        "approves_legacy_shutdown": False,
   239	        "cannot_bypass_risk_gateway": True,
   240	        "writes_legacy_redis": False,
   241	    }
   242	    if r is not None:
   243	        _safe_write(
   244	            r, f"{V2_REDIS_PREFIX}orchestrator:heartbeat",
   245	            json.dumps(status), ex=300,
   246	        )
   247	    return status
   248	
   249	
   250	def write_payload(payload: dict, path: Path) -> None:
   251	    path.parent.mkdir(parents=True, exist_ok=True)
   252	    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
   253	
   254	
   255	def main(argv: list[str] | None = None) -> int:
   256	    parser = argparse.ArgumentParser(prog="v2_orchestrator_arbitration_loop")
   257	    parser.add_argument("--once", action="store_true")
   258	    parser.add_argument("--loop", action="store_true")
   259	    parser.add_argument("--interval-seconds", type=int, default=60)
   260	    parser.add_argument("--out", type=Path, default=DEFAULT_PAYLOAD_PATH)

codex
V2_AUTONOMOUS_OBSERVATION_GAP_FEATURE_SOURCE_BURNDOWN_CODEX_FAIL
V2_AUTONOMOUS_OBSERVATION_GAP_FEATURE_SOURCE_BURNDOWN_CODEX_FAIL
```

exec
/bin/bash -lc "nl -ba claude_worklog/agent_supervisor/tasks/claude_autoseed_observation_gap_feature_source_burndown_r18.json | sed -n '1,120p'
nl -ba claude_worklog/final_readiness/v2_closed_loop_execution/latest/logs/claude_autoseed_observation_gap_feature_source_burndown_r18.log | sed -n '1,80p'
nl -ba claude_worklog/final_readiness/v2_full_observation_builder/latest/full_observation_builder_status.json | grep -n '\"source\": \"MISSING_FROM_V2_LIQUIDATION_AGGREGATOR\"' | head" in /home/wali/Desktop/AI BOT REBUILD
 succeeded in 0ms:
     1	{
     2	  "agent": "claude",
     3	  "autoseed_metadata": {
     4	    "generated_at": "2026-05-25T00:47:15Z",
     5	    "iteration": 18,
     6	    "source": "v2_autonomous_mission_backlog_autoseed",
     7	    "task_role": "implementation",
     8	    "title": "Observation gap feature-source burndown"
     9	  },
    10	  "completed_at": "2026-05-25T00:51:57Z",
    11	  "created_at": "2026-05-25T00:47:15Z",
    12	  "current_active": true,
    13	  "cwd": "/home/wali/Desktop/AI BOT REBUILD",
    14	  "duplicate_suppression_key": "autoseed:observation_gap_feature_source_burndown:implementation:r18",
    15	  "expected_output_paths": [
    16	    "claude_worklog/final_readiness/v2_autonomous_mission_backlog/per_task/observation_gap_feature_source_burndown/IMPLEMENTATION_REPORT.md"
    17	  ],
    18	  "fail_blockers": [
    19	    "running_descriptor_without_active_lease_reset"
    20	  ],
    21	  "file_lock_group": "v2_observation_gap_feature_source_burndown",
    22	  "lease_id": "070f53d25ab1423687749fff477ac288",
    23	  "log_path": "/home/wali/Desktop/AI BOT REBUILD/claude_worklog/final_readiness/v2_closed_loop_execution/latest/logs/claude_autoseed_observation_gap_feature_source_burndown_r18.log",
    24	  "mission_categories": [
    25	    "observation completeness",
    26	    "model/policy readiness",
    27	    "decision match"
    28	  ],
    29	  "mission_progress_countable": true,
    30	  "next_action": "Run narrow V2 implementation task observation_gap_feature_source_burndown",
    31	  "owner": "CLAUDE",
    32	  "paired_codex_review_task_id": "codex_review_autoseed_observation_gap_feature_source_burndown_r18",
    33	  "pid_or_job_id": 1572990,
    34	  "prompt": "Implement the next narrow V2 observation-completeness burndown. Use the current full-observation missing-source/status payloads, select one highest-impact missing feature family with a V2-owned source path, add or wire the exact source mapping, and emit a per-task implementation report. If the source does not exist, mark MISSING_SOURCE with evidence instead of inventing values. Keep all writes V2-scoped and public-payload scoped.",
    35	  "report_only_work": false,
    36	  "risk_level": "L1",
    37	  "safety": {
    38	    "approves_canary": false,
    39	    "approves_legacy_shutdown": false,
    40	    "approves_live": false,
    41	    "approves_redis_trim": false,
    42	    "calls_exchange_mutation": false,
    43	    "live_gate": "blocked_human_only",
    44	    "live_symbols": [],
    45	    "modifies_legacy_repo": false,
    46	    "writes_old_redis": false
    47	  },
    48	  "scope_paths": [
    49	    "v2/backend/app/services/full_observation",
    50	    "claude_worklog/final_readiness/v2_full_observation_builder/latest",
    51	    "v2/frontend/public/operator_runtime/v2_rl_core/latest"
    52	  ],
    53	  "started_at": "2026-05-25T00:47:42Z",
    54	  "status": "completed",
    55	  "task_id": "claude_autoseed_observation_gap_feature_source_burndown_r18",
    56	  "task_type": "CLAUDE_IMPLEMENTATION",
    57	  "ui_only_work": false,
    58	  "updated_at": "2026-05-25T00:51:57Z",
    59	  "worker_id": "claude-2"
    60	}
     1	I'm hitting a write permission prompt for `v2/backend/app/services/rl_core/liquidation_observation_aggregator.py` (within my allowed write boundary per CLAUDE.md). The prompt has appeared three times without resolution — I'll stop retrying.
     2	
     3	Plan to wire the burndown (waiting on your approval for V2 file edits):
     4	
     5	**Selected feature family: `liquidations`** — the operator-blessed `next_required_family` per `v2/frontend/public/operator_runtime/v2_rl_core/latest/full_observation_builder_status.json`. 4 fields × 3 symbols = 12 currently-missing dims, all marked `MISSING_FROM_V2_LIQUIDATION_AGGREGATOR`.
     6	
     7	**Root cause (verified in code)**: V2 already owns the source path — `liquidations_wss.py` writes `v2:market:liquidations:latest:{sym}` / `:aggregate:{sym}` and `liquidation_observation_aggregator.build_liquidation_subfamily` accepts a `v2_liquidation_per_symbol` argument that consumes those keys. But `full_observation_builder._project_liquidations` (line 988) calls `build_liquidation_subfamily(symbol="", v2_features, coinank_intel)` and **never passes** `v2_liquidation_per_symbol`. So even after operator opt-in, the 4 fields stay missing.
     8	
     9	**Surgical wiring (3 files, ~60 LOC)**:
    10	1. `liquidation_observation_aggregator.py` — add public `read_v2_liquidation_per_symbol_from(redis_client, symbol)` so the builder can reuse its existing Redis client (no double-connect).
    11	2. `full_observation_builder.py` — thread `symbol` + optional `liquidation_per_symbol` through `_project_liquidations` → `_build_unified_features_slice` → `build_full_observation_for_symbol` → `build_full_observation_status` (which reads the two Redis keys per symbol). When the WSS opt-in is OFF, the 4 fields **remain explicitly MISSING** (evidence-honest, no fabrication).
    12	3. `test_v2_liquidation_observation_aggregator.py` — add a test confirming: (a) when `v2_liquidation_per_symbol` is provided with `any_populated=True`, the 4 wired fields fill with `V2_MARKET_LIQUIDATIONS_LATEST` / `V2_MARKET_LIQUIDATIONS_AGGREGATE` source labels; (b) when absent, they stay `MISSING_FROM_V2_LIQUIDATION_AGGREGATOR`.
    13	
    14	Plus emit a per-task implementation report at `claude_worklog/v2_observation_completeness_burndown/liquidations_per_symbol_wiring/REPORT.md` with raw evidence pointers.
    15	
    16	All writes V2-scoped, public-payload scoped, no live gate touched, no legacy mutation, no torch/pickle/zero-fill introduced.
    17	
    18	Please approve the pending V2 file write so I can proceed — or tell me to abort.
149:   149	          "source": "MISSING_FROM_V2_LIQUIDATION_AGGREGATOR",
154:   154	          "source": "MISSING_FROM_V2_LIQUIDATION_AGGREGATOR",
399:   399	          "source": "MISSING_FROM_V2_LIQUIDATION_AGGREGATOR",
404:   404	          "source": "MISSING_FROM_V2_LIQUIDATION_AGGREGATOR",
649:   649	          "source": "MISSING_FROM_V2_LIQUIDATION_AGGREGATOR",
654:   654	          "source": "MISSING_FROM_V2_LIQUIDATION_AGGREGATOR",

exec
/bin/bash -lc 'for r in r15 r16 r17; do echo $r; tail -5 claude_worklog/final_readiness/v2_closed_loop_execution/latest/logs/codex_review_autoseed_observation_gap_feature_source_burndown_${r}_codex.log | sed -n '"'1,20p'; done" in /home/wali/Desktop/AI BOT REBUILD
 succeeded in 0ms:
r15
?? v2/frontend/public/v2_full_observation_liquidation_burndown/latest/

codex
V2_AUTONOMOUS_OBSERVATION_GAP_FEATURE_SOURCE_BURNDOWN_CODEX_FAIL
V2_AUTONOMOUS_OBSERVATION_GAP_FEATURE_SOURCE_BURNDOWN_CODEX_FAIL
r16
approves_live False

codex
V2_AUTONOMOUS_OBSERVATION_GAP_FEATURE_SOURCE_BURNDOWN_CODEX_FAIL
V2_AUTONOMOUS_OBSERVATION_GAP_FEATURE_SOURCE_BURNDOWN_CODEX_FAIL
r17
   260	    parser.add_argument("--out", type=Path, default=DEFAULT_PAYLOAD_PATH)

codex
V2_AUTONOMOUS_OBSERVATION_GAP_FEATURE_SOURCE_BURNDOWN_CODEX_FAIL
V2_AUTONOMOUS_OBSERVATION_GAP_FEATURE_SOURCE_BURNDOWN_CODEX_FAIL

exec
/bin/bash -lc "find claude_worklog -type f \\( -name 'IMPLEMENTATION_REPORT.md' -o -name 'REPORT.md' \\) | grep -E 'observation|liquidation|feature_source|source_burndown' | tail -100" in /home/wali/Desktop/AI BOT REBUILD
 succeeded in 0ms:
exec
/bin/bash -lc 'test -e claude_worklog/final_readiness/v2_autonomous_mission_backlog/per_task/observation_gap_feature_source_burndown/IMPLEMENTATION_REPORT.md; echo $?' in /home/wali/Desktop/AI BOT REBUILD
 succeeded in 0ms:
1

codex
V2_AUTONOMOUS_OBSERVATION_GAP_FEATURE_SOURCE_BURNDOWN_CODEX_FAIL
V2_AUTONOMOUS_OBSERVATION_GAP_FEATURE_SOURCE_BURNDOWN_CODEX_FAIL
```
