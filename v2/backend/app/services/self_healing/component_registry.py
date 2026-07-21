"""Registry of non-ingestor components + the pure heal-decision logic.

The decision function is deliberately pure (no IO): the CLI gathers unit state +
heartbeat age and passes them in, so the safety-critical branching is unit
testable. Heartbeat metadata per component is data, enriched over time.
"""
from __future__ import annotations

from dataclasses import dataclass
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

    ``heartbeat_redis_key`` / ``heartbeat_file`` / ``heartbeat_files`` describe
    where the component publishes a monotonically-fresh timestamp. Multiple
    files are permitted for a service whose explicitly selected resident modes
    publish distinct schemas; the supervisor uses the freshest valid clock.
    When ``max_staleness_seconds`` is None the component is
    process-liveness-only (dead-process healing only). When a heartbeat is
    declared, a live-but-stale process is also healed.
    """

    name: str
    unit: str
    category: str
    criticality: Criticality = "normal"
    heartbeat_redis_key: str | None = None
    heartbeat_field: str = "generated_utc"
    heartbeat_file: str | None = None
    heartbeat_files: tuple[str, ...] = ()
    max_staleness_seconds: int | None = None
    process_pattern: str | None = None
    heal_mode: HealMode = "auto"
    # When the heartbeat is a TTL'd Redis key, a hung process lets the key EXPIRE,
    # so a *missing* key on a long-running process is itself a hang signal. Only
    # honored once the unit has been active longer than max_staleness (startup
    # grace) so a just-restarted component is never falsely healed.
    treat_missing_heartbeat_as_stale: bool = False


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
# A live process observed stale, but not yet for enough consecutive passes to
# restart (debounce against transient lag). No action taken this pass.
ACTION_STALE_PENDING = "STALE_PENDING"

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
    active_since_seconds: float | None = None,
    consecutive_stale_count: int = 0,
    min_stale_observations: int = 2,
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
    stale_present = (
        spec.max_staleness_seconds is not None
        and heartbeat_age_seconds is not None
        and heartbeat_age_seconds > spec.max_staleness_seconds
    )
    # A missing TTL'd heartbeat on a process that has been up past the startup
    # grace is a hang signal (the key expired because the loop stopped writing).
    stale_missing = (
        spec.treat_missing_heartbeat_as_stale
        and spec.max_staleness_seconds is not None
        and heartbeat_age_seconds is None
        and active_since_seconds is not None
        and active_since_seconds > spec.max_staleness_seconds
    )
    stale = stale_present or stale_missing

    if is_dead:
        if recent_restart_count >= max_restarts_per_window:
            return _mk(ACTION_SKIP_RATE_LIMITED, "restart rate limit reached (dead)")
        action = ACTION_ALERT_DEAD if spec.heal_mode == "alert" else ACTION_RESTART_DEAD
        return _mk(action, f"process not active (state={active_state})")

    if is_active and stale:
        # Debounce: a single stale observation is often transient lag (GC, a heavy
        # cycle). Require the process to be stale for min_stale_observations
        # consecutive passes before restarting it -- one blip never restarts a
        # live, especially critical, component.
        if consecutive_stale_count + 1 < max(1, min_stale_observations):
            return _mk(
                ACTION_STALE_PENDING,
                f"stale observation {consecutive_stale_count + 1}/{min_stale_observations} -- observing",
            )
        if recent_restart_count >= max_restarts_per_window:
            return _mk(ACTION_SKIP_RATE_LIMITED, "restart rate limit reached (stale)")
        action = ACTION_ALERT_STALE if spec.heal_mode == "alert" else ACTION_RESTART_STALE
        if stale_missing:
            reason = (
                f"heartbeat missing on process up {active_since_seconds:.0f}s "
                f"(> {spec.max_staleness_seconds}s grace) -- hung"
            )
        else:
            reason = f"heartbeat stale ({heartbeat_age_seconds:.0f}s > {spec.max_staleness_seconds}s)"
        return _mk(action, reason)

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
_FE = "v2/frontend/public/operator_runtime"  # file-heartbeat prefix

NON_INGESTOR_COMPONENTS: tuple[ComponentSpec, ...] = (
    # --- trainer subsystem ---
    # Native trainer has two explicitly selected resident modes.  The legacy
    # training runtime publishes the first path; the authenticated-sample
    # waiting observer publishes the second.  Observe the freshest valid clock
    # so a stale artifact from the inactive mode cannot restart the active mode.
    # The 1800s limit remains deliberately generous for the legacy 12-26min
    # training cycle; the waiting observer currently publishes every 30s.
    _svc("native_cuda_trainer_persistent", "native-cuda-trainer-persistent", "trainer",
         criticality="critical",
         heartbeat_file="v2/frontend/public/v2_persistent_cuda_trainer_resource_utilization_and_paper_drawdown_guard/latest/native_cuda_trainer_persistent_runtime_status.json",
         heartbeat_files=(
             "v2/runtime/native_cuda_trainer_waiting_for_authenticated_samples_status.json",
         ),
         heartbeat_field="generated_utc", max_staleness_seconds=1800),
    _svc("continuous_offline_gpu_trainer", "continuous-offline-gpu-trainer", "trainer",
         criticality="normal", process_pattern="continuous_offline_gpu_trainer_loop.sh"),
    _svc("trainer_checkpoint_evidence", "trainer-checkpoint-evidence", "trainer", criticality="normal",
         heartbeat_redis_key="v2:trainer:checkpoint:heartbeat", heartbeat_field="generated_utc",
         max_staleness_seconds=900, treat_missing_heartbeat_as_stale=True),
    _svc("rl_core_inference_loop", "rl-core-inference-loop", "signal", criticality="critical",
         heartbeat_redis_key="v2:trainer:heartbeat", heartbeat_field="finished_at",
         max_staleness_seconds=600, treat_missing_heartbeat_as_stale=True),
    # No reliable single service heartbeat (per-symbol prediction keys are not a
    # dependable anchor -- observed 12min stale on a healthy publisher);
    # process-liveness-only until a real heartbeat key exists.
    _svc("all_timeframe_prediction_publisher", "all-timeframe-prediction-signal-price-target-publisher",
         "signal", criticality="high"),
    # --- risk / portfolio (TTL'd Redis heartbeats -> missing == hung) ---
    _svc("risk_gateway", "risk-gateway-live-loop", "risk", criticality="critical",
         heartbeat_redis_key="v2:risk:gateway:heartbeat", heartbeat_field="finished_at",
         max_staleness_seconds=300, treat_missing_heartbeat_as_stale=True),
    _svc("portfolio_cascade_guard", "portfolio-cascade-guard", "risk", criticality="critical",
         heartbeat_redis_key="v2:paper:portfolio_cascade_guard", heartbeat_field="generated_utc",
         max_staleness_seconds=240, treat_missing_heartbeat_as_stale=True),
    _svc("portfolio_state_publisher", "portfolio-state-publisher", "risk", criticality="high",
         heartbeat_redis_key="v2:portfolio:state", heartbeat_field="generated_utc",
         max_staleness_seconds=120, treat_missing_heartbeat_as_stale=True),
    _svc("position_history_tracker", "position-history-persistent-tracker", "risk", criticality="normal",
         heartbeat_redis_key="v2:paper:position_history:heartbeat", heartbeat_field="generated_utc",
         max_staleness_seconds=300, treat_missing_heartbeat_as_stale=True),
    # --- orchestrator / decision ---
    # Heartbeat re-enabled after the unbounded-SCAN hang fix: v2:orchestrator:heartbeat
    # (ex=300, finished_at) is now reliably published each ~18s cycle. Generous
    # threshold + debounce so only a real hang (e.g. keyspace-growth SCAN stall)
    # restarts it.
    _svc("orchestrator_arbitration", "orchestrator-arbitration-loop", "orchestrator", criticality="critical",
         heartbeat_redis_key="v2:orchestrator:heartbeat", heartbeat_field="finished_at",
         max_staleness_seconds=300, treat_missing_heartbeat_as_stale=True),
    _svc("readonly_decision_observatory", "readonly-decision-observatory", "orchestrator", criticality="normal",
         heartbeat_file="claude_worklog/codex_legacy_v2_realtime_decision_observatory/codex_legacy_v2_realtime_decision_observatory_status.json",
         heartbeat_field="generated_at", max_staleness_seconds=480),
    _svc("paper_decision_lineage", "paper-decision-lineage-publisher", "orchestrator", criticality="normal",
         heartbeat_file=f"{_FE}/v2_paper_decision_lineage/latest/v2_paper_decision_lineage.json",
         heartbeat_field="generated_utc", max_staleness_seconds=240),
    _svc("opportunity_tracker", "opportunity-tracker-publisher", "orchestrator", criticality="normal",
         heartbeat_redis_key="v2:opportunity:summary", heartbeat_field="generated_utc",
         max_staleness_seconds=900, treat_missing_heartbeat_as_stale=True),
    _svc("operator_review_publisher", "operator-review-publisher", "orchestrator", criticality="normal",
         heartbeat_redis_key="v2:operator:review:status", heartbeat_field="generated_utc",
         max_staleness_seconds=240, treat_missing_heartbeat_as_stale=True),
    _svc("cascade_context_publisher", "cascade-context-publisher", "orchestrator", criticality="normal",
         heartbeat_redis_key="v2:microstructure:cascade_context:summary", heartbeat_field="generated_at",
         max_staleness_seconds=300),
    # NOTE: ai-bot-v2-orderbook-features-publisher.service (derives
    # v2:orderbook:features:binance:* from already-ingested raw books) is
    # deliberately NOT registered here: the unit name matches the "orderbook"
    # ingestor-family denylist token above, and the self-healing scope
    # explicitly excludes that family. systemd Restart=always supervises it.
    _svc("adaptive_gate_tuner", "adaptive-gate-tuner", "orchestrator", criticality="high",
         heartbeat_redis_key="v2:orchestrator:adaptive_gate_tuning_state", heartbeat_field="generated_at",
         max_staleness_seconds=300, treat_missing_heartbeat_as_stale=True),
    # Publishes the shared dashboard capital-productivity telemetry (~10-min batch
    # loop). Process-liveness self-heal (it was previously an unsupervised orphan).
    _svc("adaptive_capital_productivity", "adaptive-capital-productivity", "publisher", criticality="high",
         process_pattern="adaptive_capital_refresh_loop.sh"),
    # --- paper / execution (hedges/stops/sizing live inside the paper loop) ---
    # Critical execution loop; generous threshold + debounce so only a real
    # multi-minute outage restarts it, never a transient cycle lag.
    _svc("trade_management_paper_loop", "trade-management-paper-loop", "execution", criticality="critical",
         heartbeat_redis_key="v2:paper:heartbeat", heartbeat_field="heartbeat_generated_at",
         max_staleness_seconds=900, treat_missing_heartbeat_as_stale=True),
    _svc("paper_shadow_observation", "paper-shadow-observation", "execution", criticality="high",
         heartbeat_file=f"{_FE}/paper_shadow_observation/latest/paper_shadow_observation_status.json",
         heartbeat_field="generated_at", max_staleness_seconds=240),
    # Heartbeat file path unverified (observed 5+ days stale on an active process);
    # process-liveness-only until confirmed.
    _svc("out_of_sample_evidence", "out-of-sample-evidence-producer", "paper", criticality="normal"),
    _svc("edge_replay_factory", "edge-replay-factory", "paper", criticality="normal",
         heartbeat_redis_key="v2:edge_factory:replay_status", heartbeat_field="generated_utc",
         max_staleness_seconds=300, treat_missing_heartbeat_as_stale=True),
    # --- edge guardian ---
    _svc("continuous_edge_guardian", "continuous-edge-guardian", "guardian", criticality="critical",
         heartbeat_redis_key="v2:continuous_edge_guardian:status", heartbeat_field="generated_utc",
         max_staleness_seconds=600, treat_missing_heartbeat_as_stale=True),
    # --- strategy / signal / feature / altdata consumers ---
    _svc("strategy_supply_publisher", "strategy-supply-publisher", "signal", criticality="high",
         heartbeat_redis_key="v2:strategy_supply:status", heartbeat_field="generated_utc",
         max_staleness_seconds=300, treat_missing_heartbeat_as_stale=True),
    _svc("a_plus_context_loop", "a-plus-context-loop", "signal", criticality="high",
         heartbeat_file=f"{_FE}/v2_a_plus_context/latest/a_plus_context_status.json",
         heartbeat_field="generated_utc", max_staleness_seconds=480),
    _svc("altdata_confluence_loop", "altdata-confluence-loop", "altdata", criticality="normal",
         heartbeat_redis_key="v2:altdata:confluence:BTCUSDT:1m", heartbeat_field="generated_utc",
         max_staleness_seconds=240),
    _svc("alt_data_candidate_publisher", "alt-data-candidate-publisher-loop", "altdata", criticality="normal"),
    _svc("alt_data_symbol_scoring", "alt-data-symbol-scoring-loop", "altdata", criticality="normal",
         heartbeat_redis_key="v2:altdata:symbol_score:BTCUSDT", heartbeat_field="generated_utc",
         max_staleness_seconds=900),
    _svc("alternative_data_status", "alternative-data-status-loop", "altdata", criticality="normal",
         heartbeat_redis_key="v2:altdata:provider_status", heartbeat_field="generated_utc",
         max_staleness_seconds=900, treat_missing_heartbeat_as_stale=True),
    _svc("arkham_presence", "arkham-presence-loop", "altdata", criticality="normal"),
    _svc("public_intel_free_tier", "public-intel-free-tier-loop", "altdata", criticality="normal"),
    # Native orderbook-derived whale-wall lane (extracted from the removed
    # combined free-tier worker, operator directive 2026-07-16).
    _svc("whale_walls_intel", "whale-walls-intel-loop", "altdata", criticality="normal",
         heartbeat_redis_key="v2:altdata:whale_walls:status", heartbeat_field="generated_utc",
         max_staleness_seconds=3600, treat_missing_heartbeat_as_stale=True),
    # Real per-exchange orderbook diff + real enhanced liquidation (per-symbol
    # output, no single heartbeat -> process-liveness self-heal).
    _svc("crossexchange_analyzer", "crossexchange-analyzer", "altdata", criticality="normal"),
    _svc("liquidation_enhanced", "liquidation-enhanced", "feature", criticality="normal"),
    _svc("feature_pipeline_native", "feature-pipeline-native-loop", "feature", criticality="high",
         heartbeat_redis_key="v2:features:pipeline:heartbeat", heartbeat_field="finished_at",
         max_staleness_seconds=600, treat_missing_heartbeat_as_stale=True),
    _svc("feature_snapshot_builder", "feature-snapshot-builder", "feature", criticality="high",
         heartbeat_file=f"{_FE}/v2_feature_snapshot_builder/latest/v2_feature_snapshot_builder_status.json",
         heartbeat_field="last_run_ts", max_staleness_seconds=240),
    _svc("full_talib_ta_loop", "full-talib-ta-loop", "feature", criticality="high",
         heartbeat_redis_key="v2:features:ta:heartbeat", heartbeat_field="finished_at",
         max_staleness_seconds=600, treat_missing_heartbeat_as_stale=True),
    _svc("technical_analysis_status", "technical-analysis-status-publisher", "feature", criticality="normal",
         heartbeat_file=f"{_FE}/v2_technical_analysis_status/latest/v2_technical_analysis_status.json",
         heartbeat_field="generated_utc", max_staleness_seconds=480),
    _svc("liquidation_levels_engine", "liquidation-levels-engine", "feature", criticality="normal",
         heartbeat_redis_key="v2:liquidations:levels:heartbeat", heartbeat_field="generated_utc",
         max_staleness_seconds=120, treat_missing_heartbeat_as_stale=True),
    _svc("liquidation_runtime_status", "liquidation-runtime-status-publisher", "feature", criticality="normal",
         heartbeat_file=f"{_FE}/v2_liquidation_runtime_status/latest/v2_liquidation_runtime_status.json",
         heartbeat_field="generated_utc", max_staleness_seconds=600),
    _svc("dynamic_symbol_discovery", "dynamic-symbol-discovery-loop", "symbol", criticality="normal",
         heartbeat_redis_key="v2:symbol_universe:dynamic_discovery_status", heartbeat_field="generated_utc",
         max_staleness_seconds=86400),
    _svc("symbol_universe_publisher", "symbol-universe-publisher", "symbol", criticality="high",
         heartbeat_file=f"{_FE}/symbol_universe/latest/symbol_universe.json",
         heartbeat_field="generated_at", max_staleness_seconds=300),
    _svc("market_chart_payload", "market-chart-payload-publisher", "publisher", criticality="normal"),
    _svc("professional_market_chart", "professional-market-chart-payload-publisher", "publisher", criticality="normal"),
    # Heartbeat file path unverified (observed 40 days stale on an active process);
    # process-liveness-only until confirmed.
    _svc("log_errors_status_publisher", "log-errors-status-publisher", "publisher", criticality="normal"),
    # --- self-heal / infra (the healers themselves; healed on death only) ---
    _svc("agent_supervisor", "agent-supervisor", "self_heal", criticality="high",
         heartbeat_file="claude_worklog/agent_supervisor/status/supervisor_heartbeat.json",
         heartbeat_field="last_loop_ts", max_staleness_seconds=600),
    _svc("worker_porting_orchestrator", "worker-porting-orchestrator", "self_heal", criticality="normal"),
    _svc("parallel_scheduler", "parallel-scheduler", "self_heal", criticality="normal",
         heartbeat_file="claude_worklog/agent_supervisor/status/parallel_capacity_scheduler_status.json",
         heartbeat_field="generated_at", max_staleness_seconds=2400),
    _svc("codex_watchdog", "codex-watchdog", "self_heal", criticality="normal"),
    _svc("memory_watchdog", "memory-watchdog", "self_heal", criticality="normal",
         heartbeat_file="v2/frontend/public/v2_memory_watchdog/latest/memory_watchdog_status.json",
         heartbeat_field="ts", max_staleness_seconds=120),
    # Heartbeat file path unverified (observed 7+ days stale on an active process);
    # process-liveness-only until confirmed.
    _svc("production_replacement_runtime_guard", "production-replacement-runtime-guard", "self_heal", criticality="normal"),
)
