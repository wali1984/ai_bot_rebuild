from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[6]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from v2.backend.app.services.self_healing.component_registry import (
    ComponentSpec,
    decide_heal_action,
    unit_is_denylisted,
    ACTION_OK,
    ACTION_RESTART_DEAD,
    ACTION_RESTART_STALE,
    ACTION_ALERT_DEAD,
    ACTION_SKIP_DENYLISTED,
    ACTION_SKIP_NOT_INSTALLED,
    ACTION_SKIP_NOT_ENABLED,
    ACTION_SKIP_DELIBERATELY_STOPPED,
    ACTION_SKIP_RATE_LIMITED,
)


def _spec(**kw) -> ComponentSpec:
    base = dict(
        name="risk_gateway",
        unit="ai-bot-v2-risk-gateway-live-loop.service",
        category="risk",
        criticality="critical",
        heartbeat_redis_key="v2:risk:gateway:status",
        heartbeat_field="generated_utc",
        max_staleness_seconds=180,
    )
    base.update(kw)
    return ComponentSpec(**base)


def _decide(spec, **kw):
    base = dict(
        installed=True,
        enabled=True,
        active_state="active",
        heartbeat_age_seconds=10.0,
        deliberately_stopped=False,
        recent_restart_count=0,
        max_restarts_per_window=3,
    )
    base.update(kw)
    return decide_heal_action(spec, **base)


def test_healthy_active_fresh_is_ok() -> None:
    assert _decide(_spec()).action == ACTION_OK


def test_dead_process_is_restarted() -> None:
    d = _decide(_spec(), active_state="failed")
    assert d.action == ACTION_RESTART_DEAD
    d2 = _decide(_spec(), active_state="inactive")
    assert d2.action == ACTION_RESTART_DEAD


def test_alive_but_stale_heartbeat_is_restarted() -> None:
    # Second consecutive stale observation clears the debounce -> restart.
    d = _decide(_spec(), active_state="active", heartbeat_age_seconds=999.0,
                consecutive_stale_count=1)
    assert d.action == ACTION_RESTART_STALE
    assert d.heartbeat_age_seconds == 999.0


def test_fresh_heartbeat_within_threshold_is_ok() -> None:
    assert _decide(_spec(), heartbeat_age_seconds=179.0).action == ACTION_OK


def test_process_liveness_only_component_ignores_staleness() -> None:
    # No max_staleness -> a live process is never restarted for staleness.
    spec = _spec(max_staleness_seconds=None)
    assert _decide(spec, heartbeat_age_seconds=99999.0).action == ACTION_OK


def test_denylisted_units_are_never_touched() -> None:
    for unit in (
        "ai-bot-v2-live-canary-dry-run.service",
        "ai-bot-v2-binance-usdm-ingestor.service",
        "ai-bot-v2-trainer-bridge.service",
        "ai-bot-v2-paper-online-runtime.service",
        "ai-bot-v2-coinank-intel-bridge.service",
    ):
        assert unit_is_denylisted(unit) is True
        d = _decide(_spec(unit=unit), active_state="failed")
        assert d.action == ACTION_SKIP_DENYLISTED


def test_non_denylisted_core_units_are_healable() -> None:
    for unit in (
        "ai-bot-v2-risk-gateway-live-loop.service",
        "ai-bot-v2-orchestrator-arbitration-loop.service",
        "ai-bot-v2-trade-management-paper-loop.service",
        "ai-bot-v2-native-cuda-trainer-persistent.service",
    ):
        assert unit_is_denylisted(unit) is False


def test_deliberately_stopped_marker_suppresses_healing() -> None:
    d = _decide(_spec(), active_state="failed", deliberately_stopped=True)
    assert d.action == ACTION_SKIP_DELIBERATELY_STOPPED


def test_disabled_unit_is_not_auto_started() -> None:
    d = _decide(_spec(), enabled=False, active_state="inactive")
    assert d.action == ACTION_SKIP_NOT_ENABLED


def test_not_installed_is_skipped() -> None:
    assert _decide(_spec(), installed=False, active_state="inactive").action == ACTION_SKIP_NOT_INSTALLED


def test_restart_rate_limit_prevents_storm() -> None:
    d = _decide(_spec(), active_state="failed", recent_restart_count=3, max_restarts_per_window=3)
    assert d.action == ACTION_SKIP_RATE_LIMITED
    # Past the debounce (streak 1) so the stale branch reaches the rate-limit check.
    d_stale = _decide(_spec(), heartbeat_age_seconds=999.0, recent_restart_count=5,
                      consecutive_stale_count=1)
    assert d_stale.action == ACTION_SKIP_RATE_LIMITED


def test_alert_mode_detects_but_does_not_restart() -> None:
    spec = _spec(heal_mode="alert")
    d = _decide(spec, active_state="failed")
    assert d.action == ACTION_ALERT_DEAD


def test_precedence_denylist_beats_deliberately_stopped() -> None:
    spec = _spec(unit="ai-bot-v2-binance-ingestor.service")
    d = _decide(spec, active_state="failed", deliberately_stopped=True)
    assert d.action == ACTION_SKIP_DENYLISTED


def test_missing_ttl_heartbeat_on_long_running_process_is_hung() -> None:
    # TTL'd Redis heartbeat expired (age None) while process has been up well past
    # the grace window -> hung -> restart.
    spec = _spec(treat_missing_heartbeat_as_stale=True, max_staleness_seconds=120)
    d = _decide(spec, active_state="active", heartbeat_age_seconds=None, active_since_seconds=1000.0,
                consecutive_stale_count=1)
    assert d.action == ACTION_RESTART_STALE
    assert "hung" in d.reason


def test_missing_heartbeat_within_startup_grace_is_not_restarted() -> None:
    # Just-restarted component that has not published its first heartbeat yet.
    spec = _spec(treat_missing_heartbeat_as_stale=True, max_staleness_seconds=120)
    d = _decide(spec, active_state="active", heartbeat_age_seconds=None, active_since_seconds=30.0)
    assert d.action == ACTION_OK


def test_missing_heartbeat_without_flag_is_ignored() -> None:
    # Default conservative behavior: a missing heartbeat is not itself a restart
    # trigger unless the component opts in.
    spec = _spec(treat_missing_heartbeat_as_stale=False, max_staleness_seconds=120)
    d = _decide(spec, active_state="active", heartbeat_age_seconds=None, active_since_seconds=99999.0)
    assert d.action == ACTION_OK


def test_stale_debounce_first_observation_only_pends() -> None:
    from v2.backend.app.services.self_healing.component_registry import ACTION_STALE_PENDING

    # First stale observation (streak 0 -> 1 of 2): observe, do not restart.
    d = _decide(_spec(), active_state="active", heartbeat_age_seconds=999.0,
                consecutive_stale_count=0, min_stale_observations=2)
    assert d.action == ACTION_STALE_PENDING


def test_stale_debounce_second_observation_restarts() -> None:
    # Second consecutive stale observation (streak 1 -> 2 of 2): restart.
    d = _decide(_spec(), active_state="active", heartbeat_age_seconds=999.0,
                consecutive_stale_count=1, min_stale_observations=2)
    assert d.action == ACTION_RESTART_STALE


def test_dead_process_ignores_debounce() -> None:
    # A dead process is unambiguous -- restart immediately, no debounce.
    d = _decide(_spec(), active_state="failed", consecutive_stale_count=0, min_stale_observations=2)
    assert d.action == ACTION_RESTART_DEAD


def test_registry_is_well_formed_and_has_no_denylisted_units() -> None:
    from v2.backend.app.services.self_healing.component_registry import NON_INGESTOR_COMPONENTS

    assert len(NON_INGESTOR_COMPONENTS) >= 20
    units = [c.unit for c in NON_INGESTOR_COMPONENTS]
    # no duplicates
    assert len(units) == len(set(units)), "duplicate units in registry"
    for c in NON_INGESTOR_COMPONENTS:
        assert c.unit.startswith("ai-bot-v2-") and c.unit.endswith(".service")
        # A registered component must never itself be denylisted (would be a no-op).
        assert not unit_is_denylisted(c.unit), f"registered unit is denylisted: {c.unit}"
        assert c.category in {
            "trainer", "risk", "orchestrator", "execution", "paper",
            "guardian", "signal", "feature", "altdata", "symbol",
            "publisher", "self_heal",
        }
        if c.max_staleness_seconds is not None:
            assert c.heartbeat_redis_key or c.heartbeat_file, (
                f"{c.unit} has staleness threshold but no heartbeat source"
            )


def test_critical_components_are_registered() -> None:
    from v2.backend.app.services.self_healing.component_registry import NON_INGESTOR_COMPONENTS

    units = {c.unit for c in NON_INGESTOR_COMPONENTS}
    for required in (
        "ai-bot-v2-risk-gateway-live-loop.service",
        "ai-bot-v2-orchestrator-arbitration-loop.service",
        "ai-bot-v2-trade-management-paper-loop.service",
        "ai-bot-v2-portfolio-cascade-guard.service",
        "ai-bot-v2-native-cuda-trainer-persistent.service",
        "ai-bot-v2-continuous-edge-guardian.service",
    ):
        assert required in units, f"missing critical component: {required}"
