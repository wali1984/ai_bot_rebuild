# Codex Review: codex_review_autoseed_cuda_live_gate_single_pass_binance_private_readonly_probe_failure_r1

GO/NO-GO: `V2_FULL_DYNAMIC_REBUILD_BLOCKER_EXECUTION_CODEX_FAIL`

## Command

```text
/home/wali/.local/bin/codex exec review ...
```

## Blockers

- blockers_simple: list[str] = []
- blockers_simple.append("Paper edge has not proven it can beat fees.")
- blockers_simple.append("Legacy shutdown is blocked until parity is proven.")
- blockers_simple.append("There are P0 runtime blockers still open.")
- blockers_simple.append(
- blockers: list[str] = []
- blockers_simple: list[str] = []
- blockers_simple.append("V2 is not fully migrated yet. The trainer, RL environment, feature pipeline, ingestors, orchestrator arbitration, and exit engines are missing or bridge-only.")
- blockers_simple.append("Paper edge has not proven it can beat fees.")
- blockers_simple.append("Trainer runtime is online, but full legacy shutdown parity is still not claimed.")
- blockers_simple.append("Legacy shutdown is blocked until parity is proven.")
- blockers_simple.append("There are P0 runtime blockers still open.")
- blockers_simple.append("Native algorithmic core migration is not complete.")
- blockers_simple.append("The true native-core P0 sprint is still blocked: feature pipeline, RL/MASA/PPO, orchestrator arbitration, trade management, and ingestor proof are not complete.")
- blockers_simple.append("Zero-miss legacy core lift failed Codex review: copied runtime coverage, dependency closure, parse validation, and atlas evidence are not complete.")
- blockers_simple.append(

## Raw Output (tail)

```text
   203	        # served the payload mirror from ``dist/`` the SPA would see stale
   204	        # JSON until the next ``npx vite build``. Operator runtime
   205	        # payloads are refreshed continuously by the freshness refresher
   206	        # and per-worker publishers — we must read them from ``public/``.
   207	        # Both directories are read-only mounts; no Redis or exchange
   208	        # call happens here.
   209	        if public_dir.exists():
   210	            live_candidate = public_dir / full_path
   211	            if live_candidate.is_file():
   212	                # no-store: never cache live operator payloads in
   213	                # intermediate proxies or in the browser.
   214	                return FileResponse(
   215	                    live_candidate,
   216	                    headers={
   217	                        "Cache-Control": "no-store, max-age=0",
   218	                        "Pragma": "no-cache",
   219	                    },
   220	                )
   221	        # Direct-file passthroughs from the build: index.html, favicon,
   222	        # robots.txt, anything that genuinely belongs to the bundle.
   223	        candidate = dist_dir / full_path
   224	        if candidate.is_file():
   225	            return FileResponse(candidate)
   226	        # Otherwise hand the SPA index so client-side routing takes over.
   227	        return FileResponse(
   228	            index_html,
   229	            headers={"Cache-Control": "no-store, max-age=0"},
   230	        )
   231	
   232	
   233	def create_app() -> FastAPI:
   234	    """Construct the FastAPI app. No startup side effects beyond router/middleware
   235	    registration, the middleware-order assertion, and the read-only
   236	    SPA static mount."""
   237	    app = FastAPI(title="AI BOT V2", version="0.0.0", docs_url="/api/docs")
   238	    _register_middleware(app)
   239	    _register_routers(app)
   240	    _assert_middleware_order(app)
   241	    _mount_frontend_spa(app)
   242	    return app

exec
/bin/bash -lc "rg -n \"forceOrder@arr|legacy_stream_url|market/ws|stream\\?streams\" '/home/wali/Desktop/AI BOT REBUILD/v2/backend/app/services/coinank_bridge/service.py' '/home/wali/Desktop/AI BOT REBUILD/v2/legacy_preserved/startup_baseline/ingest'" in /home/wali/Desktop/AI BOT REBUILD
 succeeded in 0ms:
/home/wali/Desktop/AI BOT REBUILD/v2/backend/app/services/coinank_bridge/service.py:142:    "legacy_stream_url": "wss://fstream.binance.com/market/ws/!forceOrder@arr",
/home/wali/Desktop/AI BOT REBUILD/v2/legacy_preserved/startup_baseline/ingest/realtime_price_provider.py:427:        stream_url = f"wss://fstream.binance.com/stream?streams={'/'.join(streams)}"
/home/wali/Desktop/AI BOT REBUILD/v2/legacy_preserved/startup_baseline/ingest/live_binance.py:458:        ws_base = "wss://dstream.binance.com/stream?streams="
/home/wali/Desktop/AI BOT REBUILD/v2/legacy_preserved/startup_baseline/ingest/live_binance.py:468:            ws_base = (creds.fut_ws_base.replace('/ws','/stream?streams=') if creds.fut_ws_base.endswith('/ws') else creds.fut_ws_base)
/home/wali/Desktop/AI BOT REBUILD/v2/legacy_preserved/startup_baseline/ingest/live_binance.py:472:                    ws_base = ws_base + 'stream?streams='
/home/wali/Desktop/AI BOT REBUILD/v2/legacy_preserved/startup_baseline/ingest/live_binance.py:474:                    ws_base = ws_base + '/stream?streams='
/home/wali/Desktop/AI BOT REBUILD/v2/legacy_preserved/startup_baseline/ingest/live_binance.py:478:            ws_base = "wss://fstream.binance.com/stream?streams="
/home/wali/Desktop/AI BOT REBUILD/v2/legacy_preserved/startup_baseline/ingest/live_binance.py:848:    stream_url = "wss://fstream.binance.com/stream?streams=" + "/".join(streams)
/home/wali/Desktop/AI BOT REBUILD/v2/legacy_preserved/startup_baseline/ingest/live_binance.py:1046:    stream_url = "wss://fstream.binance.com/stream?streams=" + "/".join(streams)
/home/wali/Desktop/AI BOT REBUILD/v2/legacy_preserved/startup_baseline/ingest/live_binance.py:1167:    # IMPORTANT: Combined streams require the `/stream?streams=` endpoint and wrap payload under `{"stream": "...", "data": {...}}`.
/home/wali/Desktop/AI BOT REBUILD/v2/legacy_preserved/startup_baseline/ingest/live_binance.py:1168:    stream_url = "wss://fstream.binance.com/stream?streams=" + "/".join(streams)
/home/wali/Desktop/AI BOT REBUILD/v2/legacy_preserved/startup_baseline/ingest/live_binance.py:1631:    # Combined streams require `/stream?streams=` and wrap payload under `data`.
/home/wali/Desktop/AI BOT REBUILD/v2/legacy_preserved/startup_baseline/ingest/live_binance.py:1632:    stream_url = "wss://fstream.binance.com/stream?streams=" + "/".join(streams)
/home/wali/Desktop/AI BOT REBUILD/v2/legacy_preserved/startup_baseline/ingest/live_binance_liquidations.py:4:Captures events via websocket (!forceOrder@arr) and maintains:
/home/wali/Desktop/AI BOT REBUILD/v2/legacy_preserved/startup_baseline/ingest/live_binance_liquidations.py:58:- Binance may return two message shapes for !forceOrder@arr:
/home/wali/Desktop/AI BOT REBUILD/v2/legacy_preserved/startup_baseline/ingest/live_binance_liquidations.py:59:        1) Combined stream envelope: {"stream":"!forceOrder@arr","data":[ {e:"forceOrder", o:{...}}, ... ]}
/home/wali/Desktop/AI BOT REBUILD/v2/legacy_preserved/startup_baseline/ingest/live_binance_liquidations.py:356:        os.getenv("BINANCE_FORCE_WS_URL", "wss://fstream.binance.com/stream?streams=!forceOrder@arr"),
/home/wali/Desktop/AI BOT REBUILD/v2/legacy_preserved/startup_baseline/ingest/live_binance_liquidations.py:357:        "wss://fstream.binance.com/ws/!forceOrder@arr",

exec
/bin/bash -lc "rg -n \"legacy_stream_url|LEGACY_BINANCE_FORCE_WS_DELEGATION\" '/home/wali/Desktop/AI BOT REBUILD/v2/backend/app/services/coinank_bridge/service.py'" in /home/wali/Desktop/AI BOT REBUILD
 succeeded in 0ms:
139:LEGACY_BINANCE_FORCE_WS_DELEGATION: Dict[str, Any] = {
142:    "legacy_stream_url": "wss://fstream.binance.com/market/ws/!forceOrder@arr",
239:    LEGACY_BINANCE_FORCE_WS_DELEGATION = LEGACY_BINANCE_FORCE_WS_DELEGATION

exec
/bin/bash -lc "sed -n '120,220p' '/home/wali/Desktop/AI BOT REBUILD/v2/backend/app/services/coinank_bridge/service.py'" in /home/wali/Desktop/AI BOT REBUILD
 succeeded in 0ms:
    "features:global_coinank:total_liquidations:latest",
    "features:global_coinank:long_short_ratio:latest",
    "features:global_coinank:funding_rate_avg:latest",
    "features:global_coinank:btc_dominance:latest",
    "features:global_coinank:eth_dominance:latest",
    "features:global_coinank:alt_season_index:latest",
    "features:global_coinank:fear_greed:latest",
    "features:global_coinank:market_sentiment:latest",
    "features:global_coinank:volatility_index:latest",
)


# ---------------------------------------------------------------------------
# WS reconnect / delegation policy — explicit contract that this CLI does NOT
# open WS sessions; the legacy WS consumer in
# live_binance_liquidations.consume_force_orders (L315+) is owned by a
# separate V2 worker.
# ---------------------------------------------------------------------------

LEGACY_BINANCE_FORCE_WS_DELEGATION: Dict[str, Any] = {
    "legacy_function": "consume_force_orders",
    "baseline_path": "v2/legacy_preserved/startup_baseline/ingest/live_binance_liquidations.py",
    "legacy_stream_url": "wss://fstream.binance.com/market/ws/!forceOrder@arr",
    "v2_bridge_mode": "in_memory_event_intake_only",
    "v2_owner": "separate_v2_ws_worker",
    "missing_api_blocker_when_unbound": "binance_force_order_ws_owner_unbound",
}


HttpGetCallable = Callable[[str], Tuple[int, Any]]
ClockCallable = Callable[[], float]


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class GlobalAggregateResult:
    """Result of the 11-key global aggregator. Mirrors the legacy
    ``live_coinank_global_aggregator.compute_and_persist`` return shape.
    """

    total_oi: float = 0.0
    total_volume: float = 0.0
    total_liquidations: float = 0.0
    long_short_ratio: float = 0.0
    funding_rate_avg: float = 0.0
    btc_dominance: float = 0.0
    eth_dominance: float = 0.0
    alt_season_index: float = 0.0
    fear_greed: float = 0.0
    market_sentiment: float = 0.0
    volatility_index: float = 0.0
    n_symbols_observed: int = 0
    v2_keys_written: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass
class LiquidationEvent:
    """V2 canonical liquidation event. Mirrors the legacy schema published by
    liquidation_bridge.publish.
    """

    ts: int
    symbol: str
    side: str  # "LONG_LIQ" | "SHORT_LIQ"
    price: float
    qty: float
    notional: float
    source: str  # "binance" | "coinank"
    src_key: str
    src_id: str
    ingest_ts: int

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass
class MissingApiBlocker:
    category: str
    detail: str
    ts: int

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class CoinankBridgeService:
    """V2 CoinAnk and liquidation bridge service.


codex
There are introduced behaviors that conflict with the stated safety goals: implicit credential environment mutation, an operational service-control endpoint, and unsafe file serving in the SPA catch-all. These are concrete regressions that need to be fixed before the remediation can be considered correct.

Full review comments:

- [P1] Stop mutating env vars on CLI package import — /home/wali/Desktop/AI BOT REBUILD/v2/backend/app/cli/__init__.py:22-22
  Importing `v2.backend.app.cli` now runs `bootstrap_process_env(apply=True)`, which writes data-provider credential values into `os.environ` at import time. Because every CLI module under this package is imported to run normal read-only workers and proofs, this silently mutates process credentials even when no command explicitly requested it, violating the immutability requirement; move this to an explicit opt-in path and keep import side effects read-only.

- [P2] Remove systemctl control from ingestor API route — /home/wali/Desktop/AI BOT REBUILD/v2/backend/app/api/v1/ingestors.py:222-231
  The new `POST /api/v1/ingestors/{service_id}/control` endpoint now executes `systemctl start/stop/restart` on allowlisted ingestor services, which enables a remote runtime control plane for service processes (even if not directly trading). This directly introduces live-path control semantics that the remediation is supposed to avoid; keep these routes read-only and expose only status/metadata.

- [P1] Restrict catch-all SPA file paths to known roots — /home/wali/Desktop/AI BOT REBUILD/v2/backend/app/main.py:210-216
  The SPA catch-all route concatenates user-controlled `full_path` directly with `public_dir` and serves it via `FileResponse` after an `is_file()` check. Path segments like `../../...` are not normalized/validated, so an attacker can escape the intended static directory and read arbitrary files under the server filesystem, including credential or config artifacts; use a normalized resolved-path containment check before serving.
There are introduced behaviors that conflict with the stated safety goals: implicit credential environment mutation, an operational service-control endpoint, and unsafe file serving in the SPA catch-all. These are concrete regressions that need to be fixed before the remediation can be considered correct.

Full review comments:

- [P1] Stop mutating env vars on CLI package import — /home/wali/Desktop/AI BOT REBUILD/v2/backend/app/cli/__init__.py:22-22
  Importing `v2.backend.app.cli` now runs `bootstrap_process_env(apply=True)`, which writes data-provider credential values into `os.environ` at import time. Because every CLI module under this package is imported to run normal read-only workers and proofs, this silently mutates process credentials even when no command explicitly requested it, violating the immutability requirement; move this to an explicit opt-in path and keep import side effects read-only.

- [P2] Remove systemctl control from ingestor API route — /home/wali/Desktop/AI BOT REBUILD/v2/backend/app/api/v1/ingestors.py:222-231
  The new `POST /api/v1/ingestors/{service_id}/control` endpoint now executes `systemctl start/stop/restart` on allowlisted ingestor services, which enables a remote runtime control plane for service processes (even if not directly trading). This directly introduces live-path control semantics that the remediation is supposed to avoid; keep these routes read-only and expose only status/metadata.

- [P1] Restrict catch-all SPA file paths to known roots — /home/wali/Desktop/AI BOT REBUILD/v2/backend/app/main.py:210-216
  The SPA catch-all route concatenates user-controlled `full_path` directly with `public_dir` and serves it via `FileResponse` after an `is_file()` check. Path segments like `../../...` are not normalized/validated, so an attacker can escape the intended static directory and read arbitrary files under the server filesystem, including credential or config artifacts; use a normalized resolved-path containment check before serving.
```
