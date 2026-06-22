# Codex Review: codex_review_autoseed_observation_gap_feature_source_burndown_r16

GO/NO-GO: `V2_AUTONOMOUS_OBSERVATION_GAP_FEATURE_SOURCE_BURNDOWN_CODEX_FAIL`

## Command

```text
/home/wali/.local/bin/codex exec review ...
```

## Raw Output (tail)

```text
    trainer_heartbeat: Mapping[str, Any] | None,
    prediction: Mapping[str, Any] | None,
    market_price: Mapping[str, Any] | None = None,
    market_funding: Mapping[str, Any] | None = None,
    market_open_interest: Mapping[str, Any] | None = None,
    paper_intents: list[Mapping[str, Any]] | None = None,
    paper_intents_held: list[Mapping[str, Any]] | None = None,
    position_price_track: Mapping[str, Any] | None = None,
    position_history: Mapping[str, Any] | None = None,
    altdata_symbol_score: Mapping[str, Any] | None = None,
    altdata_candidates: Mapping[str, Any] | None = None,
    position_history_consumption_allowed: bool | None = None,
    position_history_consumption_blocked_reason: str | None = None,
) -> FullObservationResult:
    fs_id = (feature_snapshot or {}).get("feature_snapshot_id")
    freshness = (feature_snapshot or {}).get("feature_freshness_state")
    uf_v, uf_n, uf_s, uf_m, sf_present, sf_target = _build_unified_features_slice(
        feature_snapshot,
        market_price,
        market_funding,
        market_open_interest,
        paper_positions,
        paper_ledger,
        risk_decisions,
        orchestrator_decisions,
        trainer_heartbeat,
    )
    ps_v, ps_n, ps_s, ps_m = _build_portfolio_state_slice(
        symbol,
        paper_positions,
        paper_ledger,
        risk_decisions,
        orchestrator_decisions,
        trainer_heartbeat,
        prediction=prediction,
        paper_intents=paper_intents,
        paper_intents_held=paper_intents_held,
        position_history=(
            position_history if position_history_consumption_allowed is not False else None
        ),
        altdata_symbol_score=altdata_symbol_score,
        altdata_candidates=altdata_candidates,
    )
    btc_v, btc_n, btc_s, btc_m = _build_onchain_slice("onchain_btc")
    eth_v, eth_n, eth_s, eth_m = _build_onchain_slice("onchain_eth")
    pc_v, pc_n, pc_s, pc_m = _build_position_context_slice(
        symbol,
        paper_positions,
        risk_decisions,
    key. Returns ``(None, None)`` if Redis is unreachable."""
    if redis_client is None:
        return None, None
    payload = _read_json(redis_client, TRACKER_HEARTBEAT_KEY)
    ttl: int | None = None
    try:
        ttl_raw = redis_client.ttl(TRACKER_HEARTBEAT_KEY)
        if isinstance(ttl_raw, (int, float)):
            ttl = int(ttl_raw)
    except Exception:
        ttl = None
    return payload if isinstance(payload, dict) else None, ttl


def build_full_observation_status(
    symbols: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "SOLUSDT"),
    timeframe: str = "1m",
) -> dict[str, Any]:
    contract = build_legacy_observation_contract()
    largest = contract.get("legacy_observation_largest_dim")
    r = _connect_redis()
    paper_positions = _read_json(r, "v2:paper:positions") if r else None
    paper_ledger = _read_json(r, "v2:paper:ledger") if r else None
    paper_intents = _read_json(r, "v2:paper:intents") if r else None
    paper_intents_held = (
        _read_json(r, "v2:paper:intents_held_by_paper_fill_gate") if r else None
    )
    risk_decisions = _read_json(r, "v2:risk:decisions") if r else None
    orch_decisions = _read_json(r, "v2:orchestrator:decisions") if r else None
    trainer_hb = _read_json(r, "v2:trainer:heartbeat") if r else None
    altdata_candidates = _read_json(r, "v2:symbol_universe:altdata_candidates") if r else None
    tracker_heartbeat, tracker_heartbeat_ttl = _read_tracker_heartbeat_with_ttl(r)
    consumption_gate = evaluate_position_history_consumption_gate(
        tracker_heartbeat=tracker_heartbeat,
        tracker_heartbeat_ttl_seconds=tracker_heartbeat_ttl,
    )
    per_symbol: list[dict[str, Any]] = []
    aggregate_state = "FULL_OBSERVATION_BUILDER_COMPLETE"
    subfamily_present_totals: dict[str, int] = {}
    subfamily_target_totals: dict[str, int] = {}
    for sym in symbols:
        fs = _read_json(r, f"v2:features:latest:{sym}:{timeframe}") if r else None
        pred = _read_json(r, f"v2:prediction:{sym}:{timeframe}") if r else None
        market_price = _read_json(r, f"v2:market:prices:{sym}") if r else None
        market_funding = _read_json(r, f"v2:market:funding:{sym}") if r else None
        market_oi = _read_json(r, f"v2:market:open_interest:{sym}") if r else None
        position_price_track = (
            _read_json(r, f"v2:paper:position_price_track:{sym}") if r else None
        )
        position_history = (
            _read_json(r, f"v2:paper:position_history:{sym}") if r else None
        )
        altdata_score = (
            _read_json(r, f"v2:altdata:symbol_score:{sym}") if r else None
        )
        result = build_full_observation_for_symbol(
            symbol=sym,
            timeframe=timeframe,
            feature_snapshot=fs,
            paper_positions=paper_positions if isinstance(paper_positions, list) else None,
            paper_ledger=paper_ledger if isinstance(paper_ledger, dict) else None,
            risk_decisions=risk_decisions if isinstance(risk_decisions, list) else None,
            orchestrator_decisions=orch_decisions if isinstance(orch_decisions, dict) else None,
            trainer_heartbeat=trainer_hb if isinstance(trainer_hb, dict) else None,
            prediction=pred if isinstance(pred, dict) else None,
            market_price=market_price if isinstance(market_price, dict) else None,
            market_funding=market_funding if isinstance(market_funding, dict) else None,
            market_open_interest=market_oi if isinstance(market_oi, dict) else None,
            paper_intents=paper_intents if isinstance(paper_intents, list) else None,
            paper_intents_held=(
                paper_intents_held if isinstance(paper_intents_held, list) else None
            ),
            position_price_track=(
                position_price_track if isinstance(position_price_track, dict) else None
            ),
            position_history=(
                position_history if isinstance(position_history, dict) else None
            ),
            altdata_symbol_score=(
                altdata_score if isinstance(altdata_score, dict) else None
            ),
            altdata_candidates=(
                altdata_candidates if isinstance(altdata_candidates, dict) else None
            ),
            position_history_consumption_allowed=consumption_gate[
                "consumption_allowed"
            ],
            position_history_consumption_blocked_reason=consumption_gate[
                "blocked_reason"
            ],
        )
        for k, v in result.subfamily_target_counts.items():
            subfamily_target_totals[k] = v
        for k, v in result.subfamily_present_counts.items():
            subfamily_present_totals[k] = subfamily_present_totals.get(k, 0) + v
        sample_present = [
            {"name": result.field_names[i], "value": result.field_values[i],
             "source": result.field_sources[i]}
            for i in range(len(result.field_values))
            if result.field_values[i] is not None
        ][:24]
        sample_missing = [
            {"name": result.field_names[i], "value": None,
             "source": result.field_sources[i]}
            for i in range(len(result.field_values))
            if result.field_values[i] is None

exec
/bin/bash -lc "ls -l claude_worklog/final_readiness/v2_autonomous_mission_backlog/per_task/observation_gap_feature_source_burndown 2>/dev/null || true; find claude_worklog/final_readiness/v2_autonomous_mission_backlog/per_task/observation_gap_feature_source_burndown -maxdepth 1 -type f -print -exec sed -n '1,120p' {} \\; 2>/dev/null" in /home/wali/Desktop/AI BOT REBUILD
 exited 1 in 0ms:
exec
/bin/bash -lc "python - <<'PY'
import json, pathlib
for p in ['v2/frontend/public/operator_runtime/v2_rl_core/latest/v2_rl_core_status.json','v2/frontend/public/operator_runtime/v2_rl_core/latest/full_observation_builder_status.json','claude_worklog/final_readiness/v2_full_observation_builder/latest/full_observation_builder_status.json']:
    path=pathlib.Path(p)
    print('---', p, path.exists())
    if path.exists():
        data=json.loads(path.read_text())
        def find(obj, key, path=''):
            if isinstance(obj, dict):
                for k,v in obj.items():
                    if k in ('live_gate','live_symbols','approves_live','operator_approval','approval','canary'):
                        print(path+'/'+k, repr(v))
                    find(v,k,path+'/'+str(k))
            elif isinstance(obj, list):
                for i,v in enumerate(obj): find(v,key,path+f'[{i}]')
        # simple
        print('top keys', list(data)[:20])
        for key in ('live_gate','live_symbols','approves_live'):
            print(key, data.get(key))
PY" in /home/wali/Desktop/AI BOT REBUILD
 succeeded in 0ms:
--- v2/frontend/public/operator_runtime/v2_rl_core/latest/v2_rl_core_status.json True
top keys ['approves_canary', 'approves_legacy_shutdown', 'approves_live', 'approves_redis_trim', 'components_missing', 'components_present', 'config_env_mapping', 'evidence_classification', 'freshness_seconds', 'generated_at', 'generated_utc', 'go_no_go', 'heartbeat_at', 'legacy_sha256_citations', 'live_gate', 'live_symbols', 'no_exchange_mutation', 'no_old_redis_writes', 'observation_schema_summary', 'p0_2a_rollout']
live_gate blocked_human_only
live_symbols []
approves_live False
--- v2/frontend/public/operator_runtime/v2_rl_core/latest/full_observation_builder_status.json True
top keys ['approves_canary', 'approves_legacy_shutdown', 'approves_live', 'approves_redis_trim', 'checkpoint_compatibility_claimed', 'compact_observation_dim', 'compact_observation_v1', 'external_source_required_families', 'full_observation_v1', 'generated_at', 'generated_utc', 'legacy_observation_largest_dim', 'legacy_observation_total_dim_by_version', 'live_gate', 'live_symbols', 'next_required_family', 'next_required_fix', 'no_legacy_features_consumed_as_current_truth', 'no_legacy_filesystem_read', 'no_pickle_loaded']
live_gate blocked_human_only
live_symbols []
approves_live False
--- claude_worklog/final_readiness/v2_full_observation_builder/latest/full_observation_builder_status.json True
top keys ['approves_canary', 'approves_legacy_shutdown', 'approves_live', 'approves_redis_trim', 'checkpoint_compatibility_claimed', 'compact_observation_dim', 'compact_observation_v1', 'external_source_required_families', 'full_observation_v1', 'generated_at', 'generated_utc', 'legacy_observation_largest_dim', 'legacy_observation_total_dim_by_version', 'live_gate', 'live_symbols', 'next_required_family', 'next_required_fix', 'no_legacy_features_consumed_as_current_truth', 'no_legacy_filesystem_read', 'no_pickle_loaded']
live_gate blocked_human_only
live_symbols []
approves_live False

codex
V2_AUTONOMOUS_OBSERVATION_GAP_FEATURE_SOURCE_BURNDOWN_CODEX_FAIL
V2_AUTONOMOUS_OBSERVATION_GAP_FEATURE_SOURCE_BURNDOWN_CODEX_FAIL
```
