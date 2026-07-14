"""Registry of non-ingestor components + the pure heal-decision logic.

The decision function is deliberately pure (no IO): the CLI gathers unit state +
heartbeat age and passes them in, so the safety-critical branching is unit
testable. Heartbeat metadata per component is data, enriched over time.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Criticality = Literal["critical", "high", "normal"]
HealMode = Literal["auto", "alert"]

# Units the supervisor must NEVER restart, matched as case-insensitive
# substrings of the unit name. Ingestors are excluded by scope; live/canary and
# legacy bridges are excluded for safety; masked units are excluded structurally.
UNIT_DENYLIST_SUBSTRINGS: tuple[str, ...] = (
    "live-canary",
    "live_canary",
    "canary",
    "trainer-bridge",  # legacy, intentionally masked
    "liquidation-bridge",  # legacy, intentionally masked
    "paper-online-runtime",  # retired; v2-trade-management-paper-loop is owner
    # ingestor families (self-healing scope explicitly excludes ingestors)
    "binance",
    "kucoin",
    "coinank",
    "coinapi",
    "coinglass",
    "moralis",
    "santiment",
    "orderbook",
    "microstructure",
    "kline",
    "agg-trades",
    "metadata-ingestor",
    "public-data",
    "symbol-source",
    "data-plane-health",
    "native-ingestors",
)


@dataclass(frozen=True)
class ComponentSpec:
    """One healable component.

    ``heartbeat_redis_key`` / ``heartbeat_field`` describe where the component
    publishes a monotonically-fresh timestamp. When ``max_staleness_seconds`` is
    None the component is process-liveness-only (dead-process healing only). When
    a heartbeat is declared, a live-but-stale process is also healed.
    """

    name: str
    unit: str
    category: str
    criticality: Criticality = "normal"
    heartbeat_redis_key: str | None = None
    heartbeat_field: str = "generated_utc"
    heartbeat_file: str | None = None
    max_staleness_seconds: int | None = None
    process_pattern: str | None = None
    heal_mode: HealMode = "auto"


@dataclass(frozen=True)
class HealDecision:
    unit: str
    name: str
    action: str
    reason: str
    heartbeat_age_seconds: float | None = None
    max_staleness_seconds: int | None = None


# Decision action constants.
ACTION_OK = "OK"
ACTION_RESTART_DEAD = "RESTART_DEAD"
ACTION_RESTART_STALE = "RESTART_STALE"
ACTION_ALERT_DEAD = "ALERT_DEAD"
ACTION_ALERT_STALE = "ALERT_STALE"
ACTION_SKIP_DENYLISTED = "SKIP_DENYLISTED"
ACTION_SKIP_NOT_INSTALLED = "SKIP_NOT_INSTALLED"
ACTION_SKIP_NOT_ENABLED = "SKIP_NOT_ENABLED"
ACTION_SKIP_DELIBERATELY_STOPPED = "SKIP_DELIBERATELY_STOPPED"
ACTION_SKIP_RATE_LIMITED = "SKIP_RATE_LIMITED"

_ACTIVE_STATES = {"active", "activating", "reloading"}
_DEAD_STATES = {"inactive", "failed", "deactivating"}


def unit_is_denylisted(unit: str) -> bool:
    low = unit.lower()
    return any(token in low for token in UNIT_DENYLIST_SUBSTRINGS)


def decide_heal_action(
    spec: ComponentSpec,
    *,
    installed: bool,
    enabled: bool,
    active_state: str,
    heartbeat_age_seconds: float | None,
    deliberately_stopped: bool,
    recent_restart_count: int = 0,
    max_restarts_per_window: int = 3,
) -> HealDecision:
    """Pure heal decision. Order encodes the safety precedence.

    Precedence: denylist > not-installed > deliberately-stopped > not-enabled >
    dead > stale-heartbeat > ok. A component in ``heal_mode='alert'`` is detected
    but never auto-restarted (ALERT_* instead of RESTART_*).
    """

    def _mk(action: str, reason: str) -> HealDecision:
        return HealDecision(
            unit=spec.unit,
            name=spec.name,
            action=action,
            reason=reason,
            heartbeat_age_seconds=heartbeat_age_seconds,
            max_staleness_seconds=spec.max_staleness_seconds,
        )

    if unit_is_denylisted(spec.unit):
        return _mk(ACTION_SKIP_DENYLISTED, "unit on safety denylist")
    if not installed:
        return _mk(ACTION_SKIP_NOT_INSTALLED, "unit not installed / masked")
    if deliberately_stopped:
        return _mk(ACTION_SKIP_DELIBERATELY_STOPPED, "operator deliberately-stopped marker present")
    if not enabled:
        # Disabled == operator does not want it running; never auto-start it.
        return _mk(ACTION_SKIP_NOT_ENABLED, "unit disabled (operator intent: off)")

    is_dead = active_state in _DEAD_STATES
    is_active = active_state in _ACTIVE_STATES
    stale = (
        spec.max_staleness_seconds is not None
        and heartbeat_age_seconds is not None
        and heartbeat_age_seconds > spec.max_staleness_seconds
    )

    if is_dead:
        if recent_restart_count >= max_restarts_per_window:
            return _mk(ACTION_SKIP_RATE_LIMITED, "restart rate limit reached (dead)")
        action = ACTION_ALERT_DEAD if spec.heal_mode == "alert" else ACTION_RESTART_DEAD
        return _mk(action, f"process not active (state={active_state})")

    if is_active and stale:
        if recent_restart_count >= max_restarts_per_window:
            return _mk(ACTION_SKIP_RATE_LIMITED, "restart rate limit reached (stale)")
        action = ACTION_ALERT_STALE if spec.heal_mode == "alert" else ACTION_RESTART_STALE
        return _mk(
            action,
            f"heartbeat stale ({heartbeat_age_seconds:.0f}s > {spec.max_staleness_seconds}s)",
        )

    return _mk(ACTION_OK, f"healthy (state={active_state})")


# --------------------------------------------------------------------------- #
# Registry of non-ingestor components. Heartbeat metadata is enriched as the
# exact keys are confirmed; components without a confirmed heartbeat are
# process-liveness-only (max_staleness_seconds=None) so they still get
# dead-process healing.
# --------------------------------------------------------------------------- #

def _svc(name: str, unit_stem: str, category: str, **kw) -> ComponentSpec:
    return ComponentSpec(
        name=name,
        unit=f"ai-bot-v2-{unit_stem}.service",
        category=category,
        **kw,
    )


# Heartbeat keys/staleness are enriched as confirmed; unset heartbeat =>
# process-liveness-only (still healed on process death). Staleness thresholds are
# ~3-5x the component's publish interval. Trainer uses ~26min (its cycle is
# 12-26min, pre-existing) to avoid false positives.
NON_INGESTOR_COMPONENTS: tuple[ComponentSpec, ...] = (
    # --- trainer subsystem ---
    _svc("native_cuda_trainer_persistent", "native-cuda-trainer-persistent", "trainer",
         criticality="critical", heartbeat_redis_key="v2:trainer:hybrid_cuda:status",
         heartbeat_field="generated_utc", max_staleness_seconds=1800),
    _svc("continuous_offline_gpu_trainer", "continuous-offline-gpu-trainer", "trainer",
         criticality="normal", process_pattern="continuous_offline_gpu_trainer_loop.sh"),
    _svc("trainer_checkpoint_evidence", "trainer-checkpoint-evidence", "trainer", criticality="normal"),
    _svc("rl_core_inference_loop", "rl-core-inference-loop", "signal", criticality="critical"),
    _svc("all_timeframe_prediction_publisher", "all-timeframe-prediction-signal-price-target-publisher",
         "signal", criticality="high"),
    # --- risk / portfolio ---
    _svc("risk_gateway", "risk-gateway-live-loop", "risk", criticality="critical"),
    _svc("portfolio_cascade_guard", "portfolio-cascade-guard", "risk", criticality="critical"),
    _svc("portfolio_state_publisher", "portfolio-state-publisher", "risk", criticality="high"),
    _svc("position_history_tracker", "position-history-persistent-tracker", "risk", criticality="normal"),
    # --- orchestrator / decision ---
    _svc("orchestrator_arbitration", "orchestrator-arbitration-loop", "orchestrator", criticality="critical"),
    _svc("readonly_decision_observatory", "readonly-decision-observatory", "orchestrator", criticality="normal"),
    _svc("paper_decision_lineage", "paper-decision-lineage-publisher", "orchestrator", criticality="normal"),
    _svc("opportunity_tracker", "opportunity-tracker-publisher", "orchestrator", criticality="normal"),
    _svc("operator_review_publisher", "operator-review-publisher", "orchestrator", criticality="normal"),
    _svc("cascade_context_publisher", "cascade-context-publisher", "orchestrator", criticality="normal"),
    # --- paper / execution (hedges/stops/sizing live inside the paper loop) ---
    _svc("trade_management_paper_loop", "trade-management-paper-loop", "execution", criticality="critical"),
    _svc("paper_shadow_observation", "paper-shadow-observation", "execution", criticality="high"),
    _svc("out_of_sample_evidence", "out-of-sample-evidence-producer", "paper", criticality="normal"),
    _svc("edge_replay_factory", "edge-replay-factory", "paper", criticality="normal"),
    # --- edge guardian ---
    _svc("continuous_edge_guardian", "continuous-edge-guardian", "guardian",
         criticality="critical", heartbeat_redis_key="v2:continuous_edge_guardian:status",
         heartbeat_field="generated_utc", max_staleness_seconds=900),
    # --- strategy / signal / feature / altdata consumers ---
    _svc("strategy_supply_publisher", "strategy-supply-publisher", "signal", criticality="high"),
    _svc("a_plus_context_loop", "a-plus-context-loop", "signal", criticality="high"),
    _svc("altdata_confluence_loop", "altdata-confluence-loop", "altdata", criticality="normal"),
    _svc("alt_data_candidate_publisher", "alt-data-candidate-publisher-loop", "altdata", criticality="normal"),
    _svc("alt_data_symbol_scoring", "alt-data-symbol-scoring-loop", "altdata", criticality="normal"),
    _svc("alternative_data_status", "alternative-data-status-loop", "altdata", criticality="normal"),
    _svc("aicoin_whale_intel", "aicoin-whale-intel-loop", "altdata", criticality="normal"),
    _svc("arkham_presence", "arkham-presence-loop", "altdata", criticality="normal"),
    _svc("lunarcrush_altdata", "lunarcrush-altdata-loop", "altdata", criticality="normal"),
    _svc("nansen_altdata", "nansen-altdata-loop", "altdata", criticality="normal"),
    _svc("public_intel_free_tier", "public-intel-free-tier-loop", "altdata", criticality="normal"),
    _svc("feature_pipeline_native", "feature-pipeline-native-loop", "feature", criticality="high"),
    _svc("feature_snapshot_builder", "feature-snapshot-builder", "feature", criticality="high"),
    _svc("full_talib_ta_loop", "full-talib-ta-loop", "feature", criticality="high"),
    _svc("technical_analysis_status", "technical-analysis-status-publisher", "feature", criticality="normal"),
    _svc("liquidation_levels_engine", "liquidation-levels-engine", "feature", criticality="normal"),
    _svc("liquidation_runtime_status", "liquidation-runtime-status-publisher", "feature", criticality="normal"),
    _svc("dynamic_symbol_discovery", "dynamic-symbol-discovery-loop", "symbol", criticality="normal"),
    _svc("symbol_universe_publisher", "symbol-universe-publisher", "symbol", criticality="high"),
    _svc("market_chart_payload", "market-chart-payload-publisher", "publisher", criticality="normal"),
    _svc("professional_market_chart", "professional-market-chart-payload-publisher", "publisher", criticality="normal"),
    _svc("opportunity_review_publisher", "log-errors-status-publisher", "publisher", criticality="normal"),
    # --- self-heal / infra (the healers themselves; healed on death only) ---
    _svc("agent_supervisor", "agent-supervisor", "self_heal", criticality="high"),
    _svc("worker_porting_orchestrator", "worker-porting-orchestrator", "self_heal", criticality="normal"),
    _svc("parallel_scheduler", "parallel-scheduler", "self_heal", criticality="normal"),
    _svc("codex_watchdog", "codex-watchdog", "self_heal", criticality="normal"),
    _svc("memory_watchdog", "memory-watchdog", "self_heal", criticality="normal"),
    _svc("production_replacement_runtime_guard", "production-replacement-runtime-guard", "self_heal", criticality="normal"),
)

