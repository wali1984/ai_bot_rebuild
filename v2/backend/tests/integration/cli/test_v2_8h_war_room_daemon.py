"""Tests for the V2 8h war-room daemon.

Paper-only. No real Redis writes (FakeRedis). No torch import. No
exchange mutation. No legacy filesystem mutation.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[5]
DAEMON_PATH = ROOT / "claude_worklog/tools/v2_8h_war_room_daemon.py"


def _load_daemon():
    spec = importlib.util.spec_from_file_location(
        "v2_8h_war_room_daemon", DAEMON_PATH
    )
    assert spec and spec.loader, f"could not load daemon module from {DAEMON_PATH}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.write_log: list[tuple[str, str, int | None]] = []

    def ping(self) -> bool:
        return True

    def get(self, key: str):
        return self.store.get(key)

    def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self.store[key] = value
        self.write_log.append((key, value, ex))
        return True


def test_daemon_module_loads_without_torch_or_pickle() -> None:
    sys.modules.pop("torch", None)
    daemon = _load_daemon()
    assert "torch" not in sys.modules
    import inspect
    src = inspect.getsource(daemon)
    assert "pickle.load" not in src
    assert "pickle.loads" not in src


def test_safe_redis_set_refuses_anything_except_war_room_heartbeat() -> None:
    daemon = _load_daemon()
    r = FakeRedis()
    assert daemon.safe_redis_set(r, daemon.REDIS_HEARTBEAT_KEY, "x", ex=60) is True
    assert daemon.REDIS_HEARTBEAT_KEY in r.store
    # Refuse other v2 namespaces (so a cycle bug cannot leak writes).
    assert daemon.safe_redis_set(r, "v2:market:liquidations:heartbeat", "x", ex=60) is False
    assert daemon.safe_redis_set(r, "v2:paper:positions", "x", ex=60) is False
    assert daemon.safe_redis_set(r, "v2:altdata:provider_status", "x", ex=60) is False
    # Refuse legacy namespaces and unscoped keys.
    assert daemon.safe_redis_set(r, "prediction:BTCUSDT", "x", ex=60) is False
    assert daemon.safe_redis_set(r, "signals:trading:primary", "x", ex=60) is False


def test_tier_due_helpers_promote_first_tick_then_respect_intervals() -> None:
    daemon = _load_daemon()
    state = {}
    assert daemon.tier_15m_due(state) is True
    assert daemon.tier_30m_due(state) is True
    assert daemon.tier_60m_due(state) is True

    now_minus = lambda mins: (
        dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=mins)
    ).isoformat(timespec="seconds").replace("+00:00", "Z")

    state = {
        "last_tier_15m_at": now_minus(10),
        "last_tier_30m_at": now_minus(20),
        "last_tier_60m_at": now_minus(45),
    }
    assert daemon.tier_15m_due(state) is False
    assert daemon.tier_30m_due(state) is False
    assert daemon.tier_60m_due(state) is False

    state = {
        "last_tier_15m_at": now_minus(20),
        "last_tier_30m_at": now_minus(35),
        "last_tier_60m_at": now_minus(70),
    }
    assert daemon.tier_15m_due(state) is True
    assert daemon.tier_30m_due(state) is True
    assert daemon.tier_60m_due(state) is True


def test_deadline_exceeded_after_eight_hours() -> None:
    daemon = _load_daemon()
    past = (
        dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=9)
    ).isoformat(timespec="seconds").replace("+00:00", "Z")
    state = {"started_at": past}
    assert daemon.deadline_exceeded(state, deadline_hours=8.0) is True
    fresh = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    assert daemon.deadline_exceeded({"started_at": fresh}, deadline_hours=8.0) is False


def test_tier_60m_fix_evaluation_emits_no_action_required_with_evidence() -> None:
    daemon = _load_daemon()
    gap = {
        "aggregated_classification_counts": {
            "FULL_OBSERVATION_PARTIAL": 3,
            "V2_POSITION_HISTORY_MISSING": 2,
            "MISSING_LEGACY_LOG_ACTION_EVIDENCE": 3,
            "CHECKPOINT_WEIGHT_BLOB_OPERATOR_REQUIRED": 1,
        }
    }
    out = daemon.tier_60m_fix_evaluation(gap)
    assert out["fixes_applied"] == []
    assert out["no_action_required_with_evidence"] is True
    queue = out["codex_review_queue"]
    assert queue["paper_only_shutdown_acceptance_created"] is False
    assert queue["live_canary_shutdown_redis_trim_approval_tokens_created"] is False
    assert queue["policy_architecture_port_started"] is False
    assert queue["checkpoint_compatibility_claimed"] is False
    assert queue["policy_architecture_parity_claimed"] is False
    pre_existing_ids = {
        e["blocker_id"] for e in queue["pre_existing_blockers_not_eligible_for_new_task_creation"]
    }
    assert "CHECKPOINT_WEIGHT_BLOB_OPERATOR_REQUIRED" in pre_existing_ids
    assert "FULL_OBSERVATION_PARTIAL" in pre_existing_ids


def test_no_exchange_mutation_surface_in_daemon_source() -> None:
    import inspect
    daemon = _load_daemon()
    src = inspect.getsource(daemon)
    forbidden = (
        "create" + "_order",
        "place" + "_order",
        "cancel" + "_order",
        "modify" + "_order",
        "set" + "_leverage",
        "set" + "_margin" + "_mode",
        "futures" + "_create" + "_order",
    )
    for token in forbidden:
        assert token not in src, f"forbidden token in daemon: {token}"


def test_status_payload_carries_safety_invariants() -> None:
    daemon = _load_daemon()
    state = {"started_at": daemon.utc_iso(), "cycle_count": 0}
    cycle = {
        "cycle_id": "wr_test",
        "started_at": daemon.utc_iso(),
        "finished_at": daemon.utc_iso(),
        "tier_5m_executed": True,
        "tier_15m_executed": False,
        "tier_30m_executed": False,
        "tier_60m_executed": False,
        "cycle_count": 0,
    }
    tier_5m = {
        "tier": "5m",
        "continuous_remediation_governor": {"go_no_go": None},
        "soak_status": {},
        "systemd_services": {},
        "v2_namespace_counts": {},
        "liquidation_wss_heartbeat_ttl_seconds": -2,
        "liquidation_wss_heartbeat_payload_present": False,
        "full_observation_state": None,
        "full_observation_target_dim": None,
        "per_symbol_generated_dim": {},
    }
    payload = daemon.build_status_payload(
        state=state, cycle=cycle, tier_5m=tier_5m, tier_15m=None,
        tier_30m=None, tier_60m=None,
    )
    inv = payload["safety_invariants"]
    assert inv["gate"] == "blocked_human_only"
    assert inv["symbols_real"] == []
    assert inv["approves_real"] is False
    assert inv["approves_canary"] is False
    assert inv["approves_legacy_shutdown"] is False
    assert inv["approves_redis_trim"] is False
    assert inv["paper_only_shutdown_acceptance_created"] is False
    assert inv["writes_legacy_redis"] is False
    assert inv["writes_exchange_orders"] is False
    assert inv["checkpoint_compatibility_claimed"] is False
    assert inv["policy_architecture_parity_claimed"] is False
    assert inv["modified_outside_repo_root"] is False
    assert inv["no_silent_zero_fill"] is True
    assert inv["no_invented_outcomes"] is True
    assert payload["go_no_go"] == "V2_8H_CONTINUOUS_WAR_ROOM_READY_PROGRESS_MADE"


def test_run_one_cycle_writes_status_and_heartbeat(tmp_path, monkeypatch) -> None:
    daemon = _load_daemon()
    # Redirect all file paths into a tmp dir so the test does not stomp
    # the live war-room artifacts.
    monkeypatch.setattr(daemon, "BASE_DIR", tmp_path / "wl")
    monkeypatch.setattr(daemon, "PUBLIC_DIR", tmp_path / "pub")
    monkeypatch.setattr(daemon, "STATE_FILE", tmp_path / "wl/state.json")
    monkeypatch.setattr(daemon, "STATUS_FILE", tmp_path / "wl/status.json")
    monkeypatch.setattr(daemon, "CYCLE_HISTORY_FILE", tmp_path / "wl/cycles.jsonl")
    monkeypatch.setattr(daemon, "GAP_MATRIX_FILE", tmp_path / "wl/gap.json")
    monkeypatch.setattr(daemon, "ACTIONS_FILE", tmp_path / "wl/actions.json")
    monkeypatch.setattr(daemon, "CODEX_QUEUE_FILE", tmp_path / "wl/queue.json")
    monkeypatch.setattr(daemon, "RUNTIME_CYCLE_FILE", tmp_path / "wl/runtime.json")
    monkeypatch.setattr(daemon, "PUBLIC_PAYLOAD_FILE", tmp_path / "pub/dashboard.json")

    # Stub out the heavy probes so the cycle is fully deterministic.
    monkeypatch.setattr(daemon, "tier_5m_runtime_health", lambda r: {
        "tier": "5m",
        "continuous_remediation_governor": {
            "go_no_go": "CODEX_CONTINUOUS_REMEDIATION_REVIEW_GOVERNOR_READY",
            "fail_blockers": [],
            "v2_processes_running": 13,
            "v2_processes_required": 13,
            "soak_runtime_active": True,
            "soak_minutes_observed": 1673,
            "soak_6h_ready": True,
            "liquidation_wss_daemon": {"fresh": True, "ttl_seconds": 121},
        },
        "soak_status": {"soak_6h_ready": True},
        "systemd_services": {"ai-bot-v2-liquidation-wss-paper-shadow.service": "active"},
        "v2_namespace_counts": {"v2:*": 100},
        "liquidation_wss_heartbeat_ttl_seconds": 121,
        "liquidation_wss_heartbeat_payload_present": True,
        "full_observation_state": "FULL_OBSERVATION_BUILDER_PARTIAL_MISSING_FIELDS",
        "full_observation_target_dim": 1911,
        "per_symbol_generated_dim": {"BTCUSDT": 156, "ETHUSDT": 156, "SOLUSDT": 147},
    })
    monkeypatch.setattr(daemon, "tier_15m_gap_matrix", lambda r, s: {
        "tier": "15m",
        "schema_version": "v2_8h_war_room_model_signal_gap_matrix_v1",
        "symbols": list(s),
        "per_symbol": [],
        "aggregated_classification_counts": {
            "FULL_OBSERVATION_PARTIAL": 3,
        },
        "legacy_evidence_consumed_as_current_truth": False,
        "invented_outcomes": False,
        "missing_provider_data_converted_to_numeric_score": False,
        "gate": "blocked_human_only",
        "symbols_real": [],
        "writes_legacy_redis": False,
        "writes_exchange_orders": False,
        "approves_real": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
    })
    monkeypatch.setattr(daemon, "tier_30m_refresh_payloads", lambda r: {
        "tier": "30m",
        "refresh_results": [],
    })

    fake = FakeRedis()
    payload = daemon.run_one_cycle(
        redis_client=fake,
        symbols=("BTCUSDT", "ETHUSDT", "SOLUSDT"),
        force_tier_15m=True,
        force_tier_30m=True,
        force_tier_60m=True,
    )
    assert payload["go_no_go"] == "V2_8H_CONTINUOUS_WAR_ROOM_READY_PROGRESS_MADE"
    assert payload["cycle"]["tier_5m_executed"] is True
    assert payload["cycle"]["tier_15m_executed"] is True
    assert payload["cycle"]["tier_30m_executed"] is True
    assert payload["cycle"]["tier_60m_executed"] is True

    status = json.loads((tmp_path / "wl/status.json").read_text())
    assert status["go_no_go"] == "V2_8H_CONTINUOUS_WAR_ROOM_READY_PROGRESS_MADE"
    assert status["safety_invariants"]["gate"] == "blocked_human_only"
    assert status["lane_g_narrow_fixes"]["no_action_required_with_evidence"] is True

    # The only Redis key the daemon writes is the war-room heartbeat.
    keys_written = {k for (k, _v, _ex) in fake.write_log}
    assert keys_written == {daemon.REDIS_HEARTBEAT_KEY}

    # Cycle history is append-only JSONL.
    cycles_text = (tmp_path / "wl/cycles.jsonl").read_text()
    assert cycles_text.strip().endswith("}")
    parsed = [json.loads(line) for line in cycles_text.splitlines() if line.strip()]
    assert len(parsed) == 1
    assert parsed[0]["tier_15m_executed"] is True


def test_run_one_cycle_does_not_call_provider_oneshots(tmp_path, monkeypatch) -> None:
    daemon = _load_daemon()
    monkeypatch.setattr(daemon, "BASE_DIR", tmp_path / "wl")
    monkeypatch.setattr(daemon, "PUBLIC_DIR", tmp_path / "pub")
    monkeypatch.setattr(daemon, "STATE_FILE", tmp_path / "wl/state.json")
    monkeypatch.setattr(daemon, "STATUS_FILE", tmp_path / "wl/status.json")
    monkeypatch.setattr(daemon, "CYCLE_HISTORY_FILE", tmp_path / "wl/cycles.jsonl")
    monkeypatch.setattr(daemon, "GAP_MATRIX_FILE", tmp_path / "wl/gap.json")
    monkeypatch.setattr(daemon, "ACTIONS_FILE", tmp_path / "wl/actions.json")
    monkeypatch.setattr(daemon, "CODEX_QUEUE_FILE", tmp_path / "wl/queue.json")
    monkeypatch.setattr(daemon, "RUNTIME_CYCLE_FILE", tmp_path / "wl/runtime.json")
    monkeypatch.setattr(daemon, "PUBLIC_PAYLOAD_FILE", tmp_path / "pub/dashboard.json")
    monkeypatch.setattr(daemon, "tier_5m_runtime_health", lambda r: {
        "tier": "5m",
        "continuous_remediation_governor": {"go_no_go": None},
        "soak_status": {},
        "systemd_services": {},
        "v2_namespace_counts": {},
        "liquidation_wss_heartbeat_ttl_seconds": -2,
        "liquidation_wss_heartbeat_payload_present": False,
        "full_observation_state": None,
        "full_observation_target_dim": None,
        "per_symbol_generated_dim": {},
    })
    monkeypatch.setattr(daemon, "tier_15m_gap_matrix", lambda r, s: {
        "tier": "15m",
        "schema_version": "v2_8h_war_room_model_signal_gap_matrix_v1",
        "symbols": list(s),
        "per_symbol": [],
        "aggregated_classification_counts": {},
        "legacy_evidence_consumed_as_current_truth": False,
        "invented_outcomes": False,
        "missing_provider_data_converted_to_numeric_score": False,
    })

    invoked: list[list[str]] = []

    def fake_shell(args, timeout=30):
        invoked.append(list(args))
        return 0, "{}", ""

    monkeypatch.setattr(daemon, "shell", fake_shell)

    daemon.run_one_cycle(
        redis_client=FakeRedis(),
        symbols=("BTCUSDT",),
        force_tier_15m=True,
        force_tier_30m=True,
        force_tier_60m=False,
    )
    flat = " ".join(" ".join(a) for a in invoked)
    # The daemon must never shell out to an external alt-data provider
    # one-shot; only its own status/dashboard refreshers are allowed.
    assert "altdata_ingestor" not in flat
    assert "_altdata_" not in flat
