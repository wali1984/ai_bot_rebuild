"""Tests for the V2 full paper-only startup manifest runtime."""
from __future__ import annotations

import json
from pathlib import Path

from v2.backend.app.services.native_runtime_migration.v2_paper_startup_manifest import (
    KNOWN_UNIVERSE,
    LIVE_GATE_BLOCKED,
    STATUS_V2_BRIDGE_READ_ONLY,
    STATUS_V2_PLACEHOLDER_BLOCKED,
    STATUS_V2_SERVICE_ACTIVE,
    SYSTEMD_TIMER_TEXT,
    SYSTEMD_UNIT_TEXT,
    V2_NATIVE_ACTIVE_SYMBOLS,
    VALID_STATUSES,
    build_api_key_presence_status,
    build_dynamic_symbol_paper_runtime_coverage,
    build_paper_runtime_process_status,
    build_v2_paper_startup_manifest_status,
    default_paths,
    run_paper_startup_packet,
)


def test_manifest_status_lists_every_role_with_valid_status(tmp_path: Path):
    status = build_v2_paper_startup_manifest_status(tmp_path)
    assert status["live_gate"] == LIVE_GATE_BLOCKED
    assert status["live_symbols"] == []
    assert status["approves_live"] is False
    assert status["role_count"] >= 25
    for r in status["roles"]:
        assert r["status"] in VALID_STATUSES, r
    assert status["claimed_trainer_native_readiness"] is False
    assert status["claimed_full_migration"] is False


def test_legacy_trader_role_is_not_marked_v2_native_active(tmp_path: Path):
    status = build_v2_paper_startup_manifest_status(tmp_path)
    by_id = {r["role_id"]: r for r in status["roles"]}
    # Trainer must stay bridge, not native.
    assert by_id["trainer"]["status"] == STATUS_V2_BRIDGE_READ_ONLY
    # OHLCV and orderbook must stay placeholder/blocked.
    assert by_id["ingest_binance_ohlcv_dynamic"]["status"] == STATUS_V2_PLACEHOLDER_BLOCKED
    assert by_id["ingest_binance_orderbook_dynamic"]["status"] == STATUS_V2_PLACEHOLDER_BLOCKED


def test_api_key_presence_does_not_read_or_emit_values():
    def stub_env(name):
        # Caller MUST NOT compare against any real value — the contract
        # is that we only return truthy/falsy, never the string itself.
        return None if name in ("COINAPI_API_KEY", "ARKHAM_API_KEY") else "x"

    status = build_api_key_presence_status(env_getter=stub_env)
    assert status["value_read_or_emitted"] is False
    by_source = {row["source"]: row for row in status["rows"]}
    # Missing keys are marked OPERATOR_DECISION_REQUIRED, not crashed.
    assert by_source["coinapi"]["status"] == "OPERATOR_DECISION_REQUIRED"
    assert by_source["arkham"]["status"] == "OPERATOR_DECISION_REQUIRED"
    # Present keys are marked by-name only — value never appears in the row.
    for row in status["rows"]:
        if row["present_by_name"] and row["env_var_name"] is not None:
            assert row["status"] == "PRESENT_BY_ENV_NAME_ONLY_VALUE_NOT_READ"
            # No value field anywhere on the row.
            for v in row.values():
                if isinstance(v, str):
                    assert "x" != v  # the stub value never leaks


def test_dynamic_symbol_coverage_covers_universe_and_families():
    coverage = build_dynamic_symbol_paper_runtime_coverage()
    assert len(coverage["universe"]) == len(KNOWN_UNIVERSE)
    table = coverage["per_symbol_table"]
    assert set(table.keys()) == set(KNOWN_UNIVERSE)
    families = coverage["families"]
    for sym in KNOWN_UNIVERSE:
        assert set(table[sym].keys()) == set(families)
        if sym in V2_NATIVE_ACTIVE_SYMBOLS:
            assert table[sym]["price"] == "V2_NATIVE_ACTIVE"
            assert table[sym]["ta"] == "V2_NATIVE_ACTIVE"
            assert table[sym]["features"] == "V2_NATIVE_ACTIVE"
            assert table[sym]["prediction"] == "V2_BRIDGE_READ_ONLY"
            assert table[sym]["coinank"] == "V2_BRIDGE_READ_ONLY"
            assert table[sym]["ohlcv"] == "PLACEHOLDER_NOT_READY"
            assert table[sym]["orderbook"] == "PLACEHOLDER_NOT_READY"
    assert coverage["bridge_data_labeled_as_v2_native"] is False


def test_runtime_proof_records_no_old_redis_or_exchange_mutation(tmp_path: Path):
    status = build_paper_runtime_process_status(tmp_path)
    assert status["old_redis_write_count"] == 0
    assert status["exchange_mutation_call_count"] == 0
    assert status["live_gate"] == LIVE_GATE_BLOCKED
    assert status["live_symbols"] == []


def test_systemd_unit_text_does_not_auto_install_and_runs_verify_only():
    assert "Type=oneshot" in SYSTEMD_UNIT_TEXT
    assert "verify-only" in SYSTEMD_UNIT_TEXT.lower()
    assert "v2_full_paper_only_startup_manifest_runtime" in SYSTEMD_UNIT_TEXT
    # The unit MUST mention that operator install is required.
    assert "systemctl --user enable" in SYSTEMD_UNIT_TEXT
    # The timer is also documented as operator-installed.
    assert "Operator-installed only" in SYSTEMD_TIMER_TEXT


def test_run_paper_startup_packet_emits_all_required_artifacts(tmp_path: Path):
    paths = default_paths(tmp_path)
    result = run_paper_startup_packet(paths, env_getter=lambda _: None)
    assert result.go_no_go == "V2_FULL_PAPER_ONLY_STARTUP_MANIFEST_RUNTIME_READY"
    assert (paths.packet_dir / "GO_NO_GO.md").read_text().strip() == result.go_no_go
    for required in [
        "V2_FULL_PAPER_ONLY_STARTUP_MANIFEST_RUNTIME_REPORT.md",
        "v2_paper_startup_manifest_status.json",
        "api_key_presence_status.json",
        "dynamic_symbol_paper_runtime_coverage.json",
        "paper_runtime_process_status.json",
    ]:
        assert (paths.packet_dir / required).exists(), required
    assert (paths.public_dir / "operator_dashboard_payload.json").exists()
    assert (paths.systemd_dir / "ai-bot-v2-full-paper-startup-runtime.service").exists()
    assert (paths.systemd_dir / "ai-bot-v2-full-paper-startup-runtime.timer").exists()


def test_packet_emits_no_truthy_approvals_or_started_daemons(tmp_path: Path):
    paths = default_paths(tmp_path)
    run_paper_startup_packet(paths, env_getter=lambda _: None)
    forbidden = [
        '"approves_live": true',
        '"approves_canary": true',
        '"approves_legacy_shutdown": true',
        '"approves_redis_trim": true',
        '"did_not_start_any_daemon": false',
        '"did_not_stop_any_daemon": false',
        '"did_not_install_systemd_units": false',
        '"did_not_run_raw_legacy_script": false',
        '"started_or_stopped_any_daemon_this_run": true',
        '"installed_systemd_units_this_run": true',
        '"ran_raw_legacy_script_this_run": true',
        '"claimed_trainer_native_readiness": true',
        '"claimed_full_migration": true',
        '"bridge_data_labeled_as_v2_native": true',
        '"value_read_or_emitted": true',
    ]
    for f in list(paths.packet_dir.rglob("*")) + list(paths.public_dir.rglob("*")):
        if not f.is_file():
            continue
        text = f.read_text(encoding="utf-8", errors="ignore")
        for token in forbidden:
            assert token not in text, f"{token} in {f}"
