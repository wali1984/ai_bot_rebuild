# Codex Review: codex_review_autoseed_observation_gap_feature_source_burndown_r17

GO/NO-GO: `V2_AUTONOMOUS_OBSERVATION_GAP_FEATURE_SOURCE_BURNDOWN_CODEX_FAIL`

## Command

```text
/home/wali/.local/bin/codex exec review ...
```

## Raw Output (tail)

```text
    "drawdown_penalty_paper",
    "no_trade_correct_credit_paper",
    "checkpoint_metadata_filename_parser",
    "temperature_calibration_math"
  ],
  "config_env_mapping": {
    "OBS_SCHEMA_VERSION": "informational only, not a V2 runtime knob",
    "rl:calibration:temperature": "legacy Redis hash key referenced; V2 does NOT read or write it",
    "rl:config:features:calibrated_confidence": "legacy Redis hash key referenced; V2 does NOT read or write it"
  },
  "evidence_classification": "PARTIALLY_MIGRATED",
  "freshness_seconds": 0,
  "generated_at": "2026-05-25T00:33:51Z",
  "generated_utc": "2026-05-16T05:16:18Z",
  "go_no_go": "SUBPROJECT_1_RL_CORE_PARTIALLY_MIGRATED_PAPER_ONLY",
  "heartbeat_at": "2026-05-25T00:33:51Z",
  "legacy_sha256_citations": {
    "rl/agents/masa_agent.py": "0c7496336ca00c0f006d9a294ea67e736e2c3f2a3e4202b98cd6925dff891080",
    "rl/calibrated_confidence.py": "03c56d7e3345444e9f285de3bee596573b3ca8d05ee4f3a26aef56e032806d90",
    "rl/constrained_reward.py": "69ff3c75b53d8d3d7844894954cf9d16f334e79e0c1bd39e9624a4482a459b2e",
    "rl/enhanced_architectures.py": "d7b2071a6c83edee5eb940d50e5578fb0b4dd14d54f9e577c65d2533409b8236",
    "rl/environment.py": "39866005417554c7f9552a64eddc14ec1024db7e22b432c844cfd1a8e7800b1d",
    "rl/fee_ratio_reward_shaping.py": "e7edce3e29a6bf7236329245ba4a14436dc6f6b0a249ad0ad3d05760570bfc06",
    "rl/gymnasium_wrapper.py": "61a086cb4a0a406ca67fe2035cf776b0c991bb9d7391572ce86e77aea0a16574",
    "rl/hybrid_trainer.py": "b7dad66b63b57c0d5c29e0fbaf67466d9c2aab81baf7a4f67b6e681e38c5b102",
    "rl/obs_schema.py": "9ec040fa1306ac28f4395aac103b104eb02644866ca8acec5577b155fd925f5f",
    "rl/reward_functions.py": "87ef4602012cbbd944bdf506fb8f1646375e7732c3a93e87b0946db7a1cca853",
    "rl/temperature_calibration.py": "302355f82bbed15dd4db75600eb058406a0a08bd44ef86ef44f19c43f54cc221"
  },
  "live_gate": "blocked_human_only",
  "live_symbols": [],
  "no_exchange_mutation": true,
  "no_old_redis_writes": true,
  "observation_schema_summary": {
    "field_count": 31,
    "freshness_required_count": 29,
    "legacy_obs_sha256": "9ec040fa1306ac28f4395aac103b104eb02644866ca8acec5577b155fd925f5f",
    "legacy_slices_covered": [
      "momentum",
      "ohlcv_multi_tf",
      "onchain_btc",
      "orderbook_depth",
      "portfolio_state",
      "position_context",
      "technical_indicators",
      "unified_features",
      "volatility",
      "volume_profile"
    ],
    "unbounded_high_fields": [
      "liquidations_1m_usd",
      "time_in_position_min"
    ]
  },
  "p0_2a_rollout": {
    "env_invariants": {
      "actions_supported": [
        "hold",
        "long",
        "short",
        "close"
      ],
      "approves_canary": false,
      "approves_legacy_shutdown": false,
      "approves_live": false,
      "approves_redis_trim": false,
      "generated_utc": "2026-05-16T05:16:18+00:00",
      "imports_exchange_sdk": false,
      "imports_gymnasium": false,
      "imports_redis": false,
      "imports_stable_baselines3": false,
      "imports_torch": false,
      "legacy_behavior_mapping": {
        "rl/environment.py": {
          "sha256": "39866005417554c7f9552a64eddc14ec1024db7e22b432c844cfd1a8e7800b1d",
          "size_bytes": 66775,
          "v2_owned_path": "v2/legacy_owned_runtime/rl/environment.py"
        },
        "rl/gymnasium_wrapper.py": {
          "sha256": "61a086cb4a0a406ca67fe2035cf7
live_gate blocked_human_only
live_symbols None

exec
/bin/bash -lc "grep -R \"v2_orchestrator_keys_written_count\" -n v2/backend/app/cli/v2_orchestrator_arbitration_loop.py v2/backend/app/services/rl_core/full_observation_builder.py 2>/dev/null || true
nl -ba v2/backend/app/cli/v2_orchestrator_arbitration_loop.py 2>/dev/null | sed -n '160,260p'" in /home/wali/Desktop/AI BOT REBUILD
 succeeded in 0ms:
v2/backend/app/cli/v2_orchestrator_arbitration_loop.py:233:        "v2_orchestrator_keys_written_count": len(keys_written),
v2/backend/app/cli/v2_orchestrator_arbitration_loop.py:273:        "v2_orchestrator_keys_written_count": hb["v2_orchestrator_keys_written_count"],
v2/backend/app/services/rl_core/full_observation_builder.py:1606:        # ``v2_orchestrator_keys_written_count``. When the key exists but the
v2/backend/app/services/rl_core/full_observation_builder.py:1609:        ("v2_orchestrator_keys_written_count",
v2/backend/app/services/rl_core/full_observation_builder.py:1611:             _coerce_float(od.get("v2_orchestrator_keys_written_count"))
v2/backend/app/services/rl_core/full_observation_builder.py:1613:             and od.get("v2_orchestrator_keys_written_count") is not None
v2/backend/app/services/rl_core/full_observation_builder.py:1620:                 and od.get("v2_orchestrator_keys_written_count") is not None
v2/backend/app/services/rl_core/full_observation_builder.py:1621:                 and _coerce_float(od.get("v2_orchestrator_keys_written_count")) is not None
   160	                "generated_utc": pr.generated_utc,
   161	            }
   162	            for pr in proposals
   163	        ]
   164	        bucket_winners = [
   165	            {
   166	                "symbol": w.symbol,
   167	                "side": w.side,
   168	                "winner_proposal_id": w.winner.proposal_id,
   169	                "winner_confidence_calibrated": w.winner.confidence_calibrated,
   170	                "winner_expected_move_after_cost_bps": w.winner.expected_move_after_cost_bps,
   171	                "winner_freshness_seconds": w.winner.freshness_seconds,
   172	                "winner_model_version": w.winner.model_version,
   173	                "considered_proposal_ids": list(w.considered_proposal_ids),
   174	                "score": w.score,
   175	            }
   176	            for w in arb.bucket_winners
   177	        ]
   178	        decisions_payload = {
   179	            "schema_version": "v2_orchestrator_decisions_v2",
   180	            "generated_utc": _utc_iso(),
   181	            "considered_count": arb.considered_count,
   182	            "bucket_winners": bucket_winners,
   183	            "stale_proposal_ids": list(arb.stale_proposal_ids),
   184	            "deconflict_reason": getattr(deconflict, "conflict_reason", None),
   185	            "deconflict_selected_side": getattr(deconflict, "selected_side", None),
   186	            "deconflict_selected_signal_id": getattr(deconflict, "selected_signal_id", None),
   187	            "held_by_paper_fill_gate": held_by_gate,
   188	            "held_by_paper_fill_gate_count": len(held_by_gate),
   189	        }
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
