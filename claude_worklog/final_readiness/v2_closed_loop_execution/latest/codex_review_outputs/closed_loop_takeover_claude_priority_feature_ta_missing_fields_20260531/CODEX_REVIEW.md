# Codex Review: closed_loop_takeover_claude_priority_feature_ta_missing_fields_20260531

GO/NO-GO: `CLOSED_LOOP_TAKEOVER_CLAUDE_PRIORITY_FEATURE_TA_MISSING_FIELDS_20260531_CODEX_FAIL`

## Command

```text
/home/wali/.local/bin/codex exec review ...
```

## Blockers

- 1. `live_gate.state == "ready"` (computed from monitor completeness, risk-policy signoff, audit ledger health, evidence packet freshness).
- 1. Status payload (always when --write-evidence or --emit-latest-snapshot):
- 1. If the caller passed an explicit non-empty symbol list, use it.
- 1. Status payload (always when --write-evidence or --emit-latest-snapshot):
- 1. If the caller passed an explicit non-empty symbol list, use it.

## Raw Output (tail)

```text


def resolve_symbols(
    *,
    explicit: Optional[Iterable[str]] = None,
    smoke_test: bool = False,
    include_baseline: bool = True,
) -> List[str]:
    """Return the runtime symbol list per the resolution order above."""
    env_smoke = os.environ.get(SMOKE_TEST_ENV_VAR) == SMOKE_TEST_ENV_VALUE

    # 1. Explicit caller list wins, except the 3-symbol smoke-test set
    # must still carry an explicit smoke-test opt-in.
    explicit_list = _parse_explicit(explicit)
    if explicit_list:
        if explicit_list == list(SMOKE_TEST_SYMBOLS) and not (smoke_test or env_smoke):
            raise ValueError(
                "V2_SYMBOL_DEFAULT_DRIFT: explicit BTC/ETH/SOL symbol set "
                "requires --smoke-test or V2_SYMBOL_PROFILE=smoke_test"
            )
        return explicit_list

    # 2. Smoke-test override (flag OR env).
    if smoke_test or env_smoke:
        return list(SMOKE_TEST_SYMBOLS)

    # 3. Published symbol-universe payload.
    discovered, _src = _read_published_symbols()
    if include_baseline:
        merged: List[str] = []
        seen: Set[str] = set()
        for s in list(BASELINE_25_SYMBOLS) + discovered:
            if s and s.upper() not in seen:
                seen.add(s.upper())
                merged.append(s.upper())
        if merged:
            return merged
    elif discovered:
        return list(discovered)

    # 4. Final fallback: 25-symbol baseline.
    return list(BASELINE_25_SYMBOLS)


def resolve_symbols_with_provenance(
    *,
    explicit: Optional[Iterable[str]] = None,
    smoke_test: bool = False,
    include_baseline: bool = True,
) -> dict:
    """Same as :func:`resolve_symbols` but also returns provenance."""
    explicit_list = _parse_explicit(explicit)
    env_smoke = os.environ.get(SMOKE_TEST_ENV_VAR) == SMOKE_TEST_ENV_VALUE
    if explicit_list:
        if explicit_list == list(SMOKE_TEST_SYMBOLS) and not (smoke_test or env_smoke):
            raise ValueError(
                "V2_SYMBOL_DEFAULT_DRIFT: explicit BTC/ETH/SOL symbol set "
                "requires --smoke-test or V2_SYMBOL_PROFILE=smoke_test"
            )
        return {
            "symbols": explicit_list,
            "symbol_profile": "explicit",
            "smoke_test": False,
            "source_path": None,
            "count": len(explicit_list),
        }
    if smoke_test or env_smoke:
        return {
            "symbols": list(SMOKE_TEST_SYMBOLS),
            "symbol_profile": "smoke_test",
            "smoke_test": True,
            "source_path": None,
            "count": len(SMOKE_TEST_SYMBOLS),
            "warning": (
                "smoke_test profile active; should not be used outside "
                "explicit smoke tests"
            ),
        }
    discovered, src = _read_published_symbols()
    symbols = resolve_symbols(
        explicit=None, smoke_test=False, include_baseline=include_baseline
    )
    return {
        "symbols": symbols,
        "symbol_profile": "dynamic_or_baseline",
        "smoke_test": False,
        "source_path": src,
        "discovered_count": len(discovered),
        "baseline_count": len(BASELINE_25_SYMBOLS),
        "count": len(symbols),
    }


def assert_not_smoke_default(symbols: Sequence[str]) -> None:
    """Guard helper: raise if the given list is the smoke-test 3 set
    without an explicit smoke-test opt-in.
    """
    if list(symbols) == list(SMOKE_TEST_SYMBOLS):
        if os.environ.get(SMOKE_TEST_ENV_VAR) != SMOKE_TEST_ENV_VALUE:
            raise ValueError(
                "V2_SYMBOL_DEFAULT_DRIFT: smoke-test symbol set "
                f"{list(SMOKE_TEST_SYMBOLS)} is being used outside of an "
                "explicit smoke-test opt-in; set V2_SYMBOL_PROFILE=smoke_test "
                "or pass --smoke-test to allow."
            )

exec
/bin/bash -lc 'rg -n "v2_feature_pipeline_native|FeaturePipelineNativeService" v2/backend | head -n 200' in /home/wali/Desktop/AI BOT REBUILD
 succeeded in 0ms:
v2/backend/scripts/run_v2_production_chain_once.py:19:            from v2.backend.app.cli import v2_feature_pipeline_native_loop as fp
v2/backend/scripts/run_p0_2f_emit.py:15:SNAPSHOT = Path("v2/runtime/v2_feature_pipeline_native/latest/latest_feature_snapshot.json")
v2/backend/scripts/start_v2_production_loops.sh:24:start_loop v2_feature_pipeline_native_loop
v2/backend/scripts/run_v2_replacement_readiness_scoreboard.py:18:    "v2.backend.app.cli.v2_feature_pipeline_native_loop",
v2/backend/scripts/run_p7_paper_edge_no_trade_acceptance.py:14:SNAPSHOT = Path("v2/runtime/v2_feature_pipeline_native/latest/latest_feature_snapshot.json")
v2/backend/tests/unit/cli/test_v2_full_copied_runtime_default_symbol_drift.py:52:        "v2/backend/app/cli/v2_feature_pipeline_native.py",
v2/backend/tests/unit/cli/test_v2_dynamic_runtime_symbol_defaults.py:5:    v2_feature_pipeline_native_loop,
v2/backend/tests/unit/cli/test_v2_dynamic_runtime_symbol_defaults.py:30:        v2_feature_pipeline_native_loop._resolve_runtime_symbols,
v2/backend/tests/integration/cli/test_v2_rl_core_p0_2f_trainer_output.py:15:        "worker_id": "v2_feature_pipeline_native",
v2/backend/app/services/native_runtime_migration/first_batch_executor.py:381:    "file_lock_group": "v2_feature_pipeline_native",
v2/backend/app/services/native_runtime_migration/first_batch_executor.py:448:    "file_lock_group": "v2_feature_pipeline_native",
v2/backend/app/services/native_runtime_migration/first_batch_executor.py:1125:    # v2_feature_pipeline_native deliberately: F covers feature pipeline,
v2/backend/tests/integration/cli/test_v2_rl_core_p0_2b_policy.py:22:        "worker_id": "v2_feature_pipeline_native",
v2/backend/app/services/feature_pipeline_native/__init__.py:11:    FeaturePipelineNativeService,
v2/backend/app/services/feature_pipeline_native/__init__.py:20:    "FeaturePipelineNativeService",
v2/backend/app/services/feature_pipeline_native/service.py:509:class FeaturePipelineNativeService:
v2/backend/app/services/feature_pipeline_native/service.py:562:            "worker_id": "v2_feature_pipeline_native",
v2/backend/app/services/feature_pipeline_native/service.py:642:            "worker_id": "v2_feature_pipeline_native",
v2/backend/tests/integration/cli/test_v2_feature_pipeline_native.py:10:    FeaturePipelineNativeService,
v2/backend/tests/integration/cli/test_v2_feature_pipeline_native.py:180:    svc = FeaturePipelineNativeService()
v2/backend/tests/integration/cli/test_v2_feature_pipeline_native.py:203:    svc = FeaturePipelineNativeService()
v2/backend/tests/integration/cli/test_v2_rl_core_p0_2d_training_loop.py:14:        "worker_id": "v2_feature_pipeline_native",
v2/backend/tests/integration/cli/test_v2_feature_pipeline_native_trainer_snapshot.py:24:        FeaturePipelineNativeService,
v2/backend/tests/integration/cli/test_v2_feature_pipeline_native_trainer_snapshot.py:27:    svc = FeaturePipelineNativeService()
v2/backend/tests/integration/cli/test_v2_feature_pipeline_native_trainer_snapshot.py:54:    assert out["worker_id"] == "v2_feature_pipeline_native"
v2/backend/tests/integration/cli/test_v2_feature_pipeline_native_trainer_snapshot.py:66:        FeaturePipelineNativeService,
v2/backend/tests/integration/cli/test_v2_feature_pipeline_native_trainer_snapshot.py:69:    svc = FeaturePipelineNativeService()
v2/backend/tests/integration/cli/test_v2_feature_pipeline_native_trainer_snapshot.py:78:        FeaturePipelineNativeService,
v2/backend/tests/integration/cli/test_v2_feature_pipeline_native_trainer_snapshot.py:81:    svc = FeaturePipelineNativeService()
v2/backend/tests/integration/cli/test_v2_feature_pipeline_native_trainer_snapshot.py:92:        FeaturePipelineNativeService,
v2/backend/tests/integration/cli/test_v2_feature_pipeline_native_trainer_snapshot.py:96:    svc = FeaturePipelineNativeService()
v2/backend/tests/integration/cli/test_v2_feature_pipeline_native_trainer_snapshot.py:124:        "v2.backend.app.cli.v2_feature_pipeline_native",
v2/backend/tests/integration/cli/test_v2_feature_pipeline_native_trainer_snapshot.py:161:        "v2.backend.app.cli.v2_feature_pipeline_native",
v2/backend/tests/integration/cli/test_v2_feature_pipeline_native_trainer_snapshot.py:187:        "v2.backend.app.cli.v2_feature_pipeline_native",
v2/backend/tests/integration/cli/test_v2_rl_core_p0_2e_gpu_training.py:12:        "worker_id": "v2_feature_pipeline_native",
v2/backend/app/services/rl_core/observation_builder.py:8:v2/runtime/v2_feature_pipeline_native/latest/latest_feature_snapshot.json
v2/backend/app/services/rl_core/observation_builder.py:114:    FeaturePipelineNativeService.emit_trainer_consumable_snapshot().
v2/backend/tests/integration/cli/test_v2_rl_core_p0_2a.py:104:        "worker_id": "v2_feature_pipeline_native",
v2/backend/app/cli/v2_production_replacement_soak_observer.py:34:    "v2.backend.app.cli.v2_feature_pipeline_native_loop",
v2/backend/app/cli/v2_owned_non_live_startup.py:44:    "v2/runtime/v2_feature_pipeline_native/latest/latest_feature_snapshot.json"
v2/backend/app/services/legacy_log_intelligence/service.py:670:                "recommended_claude_task": "Check v2_feature_pipeline_native_loop freshness gate for symbol.",
v2/backend/app/cli/v2_feature_pipeline_native.py:6:   v2/frontend/public/operator_runtime/v2_feature_pipeline_native/latest/v2_feature_pipeline_native_status.json
v2/backend/app/cli/v2_feature_pipeline_native.py:8:   v2/frontend/public/operator_runtime/v2_feature_pipeline_native/latest/latest_feature_snapshot.json
v2/backend/app/cli/v2_feature_pipeline_native.py:9:   v2/runtime/v2_feature_pipeline_native/latest/latest_feature_snapshot.json
v2/backend/app/cli/v2_feature_pipeline_native.py:22:    FeaturePipelineNativeService,
v2/backend/app/cli/v2_feature_pipeline_native.py:28:    / "v2/frontend/public/operator_runtime/v2_feature_pipeline_native/latest/v2_feature_pipeline_native_status.json"
v2/backend/app/cli/v2_feature_pipeline_native.py:32:    / "v2/frontend/public/operator_runtime/v2_feature_pipeline_native/latest/latest_feature_snapshot.json"
v2/backend/app/cli/v2_feature_pipeline_native.py:36:    / "v2/runtime/v2_feature_pipeline_native/latest/latest_feature_snapshot.json"
v2/backend/app/cli/v2_feature_pipeline_native.py:89:    svc = FeaturePipelineNativeService()
v2/backend/app/cli/v2_feature_pipeline_native.py:98:        print(f"v2_feature_pipeline_native_status_written path={args.out} live_gate={status['live_gate']}")
v2/backend/app/services/native_dynamic_runtime/execution.py:27:    FeaturePipelineNativeService,
v2/backend/app/services/native_dynamic_runtime/execution.py:538:    feature_service = FeaturePipelineNativeService()
v2/backend/app/cli/v2_rl_core_worker.py:67:    "v2/runtime/v2_feature_pipeline_native/latest/latest_feature_snapshot.json"
v2/backend/app/cli/v2_rl_core_worker.py:70:    "v2/frontend/public/operator_runtime/v2_feature_pipeline_native/latest/latest_feature_snapshot.json"
v2/backend/app/cli/v2_rl_core_worker.py:195:                    "v2/runtime/v2_feature_pipeline_native/latest/latest_feature_snapshot.json "
v2/backend/app/cli/v2_feature_pipeline_native_loop.py:32:    "v2/frontend/public/operator_runtime/v2_feature_pipeline_native/live/latest/v2_feature_pipeline_native_live_status.json"
v2/backend/app/cli/v2_feature_pipeline_native_loop.py:34:SNAPSHOT_PATH = Path("v2/runtime/v2_feature_pipeline_native/latest/latest_feature_snapshot.json")
v2/backend/app/cli/v2_feature_pipeline_native_loop.py:253:            "worker_id": "v2_feature_pipeline_native_loop",
v2/backend/app/cli/v2_feature_pipeline_native_loop.py:295:        "worker_id": "v2_feature_pipeline_native_loop",
v2/backend/app/cli/v2_feature_pipeline_native_loop.py:296:        "schema_version": "v2_feature_pipeline_native_live_v1",
v2/backend/app/cli/v2_feature_pipeline_native_loop.py:338:    parser = argparse.ArgumentParser(prog="v2_feature_pipeline_native_loop")
v2/backend/app/cli/v2_production_payload_freshness_refresher.py:42:        "name": "v2_feature_pipeline_native_snapshot",
v2/backend/app/cli/v2_production_payload_freshness_refresher.py:43:        "latest_path": Path("v2/frontend/public/operator_runtime/v2_feature_pipeline_native/latest/latest_feature_snapshot.json"),
v2/backend/app/cli/v2_production_payload_freshness_refresher.py:44:        "live_source": Path("v2/runtime/v2_feature_pipeline_native/latest/latest_feature_snapshot.json"),
v2/backend/app/cli/v2_production_payload_freshness_refresher.py:46:        "loop_module": "v2_feature_pipeline_native_loop",
v2/backend/app/cli/v2_production_equivalence_comparator.py:40:    "v2.backend.app.cli.v2_feature_pipeline_native_loop",
v2/backend/app/services/native_ingestors/registry.py:266:                "v2_feature_pipeline_native_trainer_snapshot. No legacy "
v2/backend/app/services/legacy_startup_parity/native_runtime_legacy_parity.py:1435:        "v2_writer": "v2_feature_pipeline_native",
v2/backend/app/services/legacy_startup_parity/native_runtime_legacy_parity.py:1471:        "v2_writer": "v2_feature_pipeline_native",
v2/backend/app/services/legacy_startup_parity/native_runtime_legacy_parity.py:1483:        "v2_writer": "v2_feature_pipeline_native",
v2/backend/app/services/legacy_startup_parity/native_runtime_legacy_parity.py:1495:        "v2_writer": "v2_feature_pipeline_native",
v2/backend/app/services/legacy_startup_parity/native_runtime_legacy_parity.py:1579:        "v2_writer": "v2_feature_pipeline_native",

exec
/bin/bash -lc "cat > claude_worklog/final_readiness/v2_closed_loop_execution/latest/codex_review_outputs/closed_loop_takeover_claude_priority_feature_ta_missing_fields_20260531/CODEX_GO_NO_GO.md <<'EOF'
CLOSED_LOOP_TAKEOVER_CLAUDE_PRIORITY_FEATURE_TA_MISSING_FIELDS_20260531_CODEX_FAIL
EOF" in /home/wali/Desktop/AI BOT REBUILD
 succeeded in 0ms:
codex
There is a real correctness regression in OHLCV-derived feature extraction when source rows are partially sparse: derived body/gap values can be miscomputed or dropped without precise missing-field signals, which undermines the task’s goal of explicit missing-field handling.

Review comment:

- [P2] Align OHLCV field lists by index before using open for derived features — /home/wali/Desktop/AI BOT REBUILD/v2/backend/app/services/feature_pipeline_native/service.py:359-367
  `compute_feature_snapshot` builds `closes`, `opens`, `highs`, and `lows` as independent filtered lists, then computes `body_pct` and `gap_pct` from `opens[-1]`/`closes[-2]` (lines 359 and 367). If the latest bar is missing `open` while older bars are complete, `opens[-1]` points to an earlier bar (or becomes empty), so `body_pct/gap_pct` are computed against the wrong timestamp or trigger the `except` path. This is a correctness issue in the missing/partial OHLCV handling this task is addressing, because it can emit wrong features instead of a deterministic missing-field flag.
There is a real correctness regression in OHLCV-derived feature extraction when source rows are partially sparse: derived body/gap values can be miscomputed or dropped without precise missing-field signals, which undermines the task’s goal of explicit missing-field handling.

Review comment:

- [P2] Align OHLCV field lists by index before using open for derived features — /home/wali/Desktop/AI BOT REBUILD/v2/backend/app/services/feature_pipeline_native/service.py:359-367
  `compute_feature_snapshot` builds `closes`, `opens`, `highs`, and `lows` as independent filtered lists, then computes `body_pct` and `gap_pct` from `opens[-1]`/`closes[-2]` (lines 359 and 367). If the latest bar is missing `open` while older bars are complete, `opens[-1]` points to an earlier bar (or becomes empty), so `body_pct/gap_pct` are computed against the wrong timestamp or trigger the `except` path. This is a correctness issue in the missing/partial OHLCV handling this task is addressing, because it can emit wrong features instead of a deterministic missing-field flag.
```
