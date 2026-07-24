from __future__ import annotations

import json
from pathlib import Path

from v2.backend.app.cli import (
    paper_online_runtime,
    v2_feature_pipeline_native_loop,
    v2_feature_snapshot_builder,
    v2_liquidation_wss_loop,
    v2_native_ingestors_live_loop,
    v2_position_history_persistent_tracker,
    v2_rl_core_inference_loop,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.config import (
    HybridTrainerConfig,
)
from v2.backend.app.services.v2_symbol_runtime_universe import (
    BASELINE_25_SYMBOLS,
    PREFERRED_MAJOR_SYMBOLS,
    SMOKE_TEST_SYMBOLS,
    SYMBOL_UNIVERSE_PUBLIC_PAYLOAD,
    resolve_symbols,
    resolve_symbols_for_purpose,
    resolve_symbols_for_purpose_with_provenance,
)


def _expected_baseline_symbols() -> set[str]:
    if SYMBOL_UNIVERSE_PUBLIC_PAYLOAD.is_file():
        payload = json.loads(SYMBOL_UNIVERSE_PUBLIC_PAYLOAD.read_text())
        confirmed = set(payload.get("binance_usdm_confirmed_symbols") or [])
        if confirmed:
            return set(BASELINE_25_SYMBOLS) & confirmed
    return set(BASELINE_25_SYMBOLS)


def _assert_dynamic_or_baseline(symbols: tuple[str, ...]) -> None:
    expected_baseline_symbols = _expected_baseline_symbols()
    assert len(symbols) >= len(expected_baseline_symbols)
    assert symbols != tuple(SMOKE_TEST_SYMBOLS)
    assert expected_baseline_symbols.issubset(set(symbols))


def test_active_multi_symbol_cli_defaults_are_not_smoke_test(monkeypatch) -> None:
    monkeypatch.delenv("V2_SYMBOL_PROFILE", raising=False)

    resolvers = (
        v2_native_ingestors_live_loop._resolve_runtime_symbols,
        v2_feature_pipeline_native_loop._resolve_runtime_symbols,
        v2_rl_core_inference_loop._resolve_runtime_symbols,
    )
    for resolver in resolvers:
        _assert_dynamic_or_baseline(resolver(None, smoke_test=False))

    _assert_dynamic_or_baseline(
        tuple(
            v2_liquidation_wss_loop.resolve_symbols(
                explicit=None, smoke_test=False, include_baseline=True
            )
        )
    )
    _assert_dynamic_or_baseline(
        tuple(
            v2_position_history_persistent_tracker.resolve_symbols(
                explicit=None, smoke_test=False, include_baseline=True
            )
        )
    )


def test_hybrid_trainer_config_default_uses_full_runtime_symbol_universe(monkeypatch) -> None:
    monkeypatch.delenv("V2_SYMBOL_PROFILE", raising=False)

    config = HybridTrainerConfig()

    _assert_dynamic_or_baseline(tuple(config.symbols))


def test_paper_online_single_symbol_default_uses_dynamic_first_symbol(monkeypatch) -> None:
    monkeypatch.delenv("V2_SYMBOL_PROFILE", raising=False)

    assert (
        paper_online_runtime._resolve_runtime_symbol(None, smoke_test=False)
        == PREFERRED_MAJOR_SYMBOLS[0]
    )


def test_feature_snapshot_builder_single_symbol_default_uses_dynamic_first_symbol(
    monkeypatch,
) -> None:
    monkeypatch.delenv("V2_SYMBOL_PROFILE", raising=False)

    args = v2_feature_snapshot_builder.parse_args(["--once", "--no-write"])
    assert args.symbol == PREFERRED_MAJOR_SYMBOLS[0]


def test_explicit_three_symbol_set_requires_smoke_opt_in(monkeypatch) -> None:
    monkeypatch.delenv("V2_SYMBOL_PROFILE", raising=False)

    try:
        resolve_symbols(explicit=SMOKE_TEST_SYMBOLS, smoke_test=False)
    except ValueError as exc:
        assert "requires --smoke-test" in str(exc)
    else:  # pragma: no cover - the assertion above is the expected branch.
        raise AssertionError("BTC/ETH/SOL explicit set must fail closed without smoke opt-in")

    assert resolve_symbols(explicit=SMOKE_TEST_SYMBOLS, smoke_test=True) == list(
        SMOKE_TEST_SYMBOLS
    )


def test_resolver_does_not_readd_unconfirmed_baseline_symbol_from_public_payload(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from v2.backend.app.services import v2_symbol_runtime_universe as svc

    payload = tmp_path / "symbol_universe_status.json"
    payload.write_text(
        json.dumps(
            {
                "training_symbols": ["BTCUSDT", "HIGHUSDT"],
                "binance_usdm_confirmed_symbols": ["BTCUSDT"],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(svc, "SYMBOL_UNIVERSE_PUBLIC_PAYLOAD", payload)

    symbols = svc.resolve_symbols(include_baseline=True)

    assert "BTCUSDT" in symbols
    assert "HIGHUSDT" not in symbols


def test_smoke_only_confirmation_does_not_override_broad_discovered_scope(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from v2.backend.app.services import v2_symbol_runtime_universe as svc

    payload = tmp_path / "symbol_universe_status.json"
    payload.write_text(
        json.dumps(
            {
                "training_symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
                "binance_usdm_confirmed_symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
                "discovered_symbols": list(BASELINE_25_SYMBOLS),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(svc, "SYMBOL_UNIVERSE_PUBLIC_PAYLOAD", payload)

    symbols = svc.resolve_symbols(include_baseline=True)

    assert tuple(symbols) != SMOKE_TEST_SYMBOLS
    assert set(BASELINE_25_SYMBOLS).issubset(set(symbols))


def test_collection_scope_does_not_fabricate_unconfirmed_preferred_majors(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from v2.backend.app.services import v2_symbol_runtime_universe as svc

    payload = tmp_path / "symbol_universe_status.json"
    payload.write_text(
        json.dumps(
            {
                "data_collection_symbols": ["BTCUSDT", "DOGEUSDT"],
                "binance_usdm_confirmed_symbols": ["BTCUSDT", "DOGEUSDT"],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(svc, "SYMBOL_UNIVERSE_PUBLIC_PAYLOAD", payload)

    symbols = svc.resolve_symbols_for_purpose(
        "data_collection", include_baseline=False
    )

    assert symbols == ["BTCUSDT", "DOGEUSDT"]
    assert "ETHUSDT" not in symbols
    assert "SOLUSDT" not in symbols


def test_preference_env_can_only_add_after_mandatory_btc_eth_sol(monkeypatch) -> None:
    from v2.backend.app.services import v2_symbol_runtime_universe as svc

    monkeypatch.setenv(
        "V2_PREFERRED_MAJOR_SYMBOLS",
        "dogeusdt,BTCUSDT,not-a-symbol,dogeusdt",
    )

    assert svc._preferred_majors() == (
        "BTCUSDT",
        "ETHUSDT",
        "SOLUSDT",
        "DOGEUSDT",
    )


def test_fresh_adaptive_purpose_scopes_are_separate_and_never_authorize_execution(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from v2.backend.app.services import v2_symbol_runtime_universe as svc

    payload = tmp_path / "symbol_universe_status.json"
    payload.write_text(
        json.dumps(
            {
                "generated_at": "2026-07-20T05:10:00Z",
                "binance_usdm_confirmed_symbols": [
                    "BTCUSDT",
                    "ETHUSDT",
                    "DOGEUSDT",
                ],
                "adaptive_training_selected_symbols": [
                    "DOGEUSDT",
                    "ETHUSDT",
                    "BTCUSDT",
                ],
                "adaptive_paper_new_entry_symbols": ["DOGEUSDT", "BTCUSDT"],
                "adaptive_scope_activation": {
                    "requested": True,
                    "scope_aware_consumers_bound": True,
                    "active": True,
                },
                "adaptive_symbol_selection": {
                    "decision_time": "2026-07-20T05:10:00Z",
                    "selection_is_execution_authorization": False,
                    "training_selected_symbols": [
                        "DOGEUSDT",
                        "ETHUSDT",
                        "BTCUSDT",
                    ],
                    "trading_selected_symbols": ["DOGEUSDT", "BTCUSDT"],
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(svc, "SYMBOL_UNIVERSE_PUBLIC_PAYLOAD", payload)
    decision = "2026-07-20T05:11:00Z"

    assert resolve_symbols_for_purpose("training", decision_time=decision) == [
        "BTCUSDT",
        "ETHUSDT",
        "DOGEUSDT",
    ]
    assert resolve_symbols_for_purpose("trading", decision_time=decision) == [
        "BTCUSDT",
        "DOGEUSDT",
    ]
    provenance = resolve_symbols_for_purpose_with_provenance(
        "trading", decision_time=decision
    )
    assert provenance["fresh"] is True
    assert provenance["selection_is_execution_authorization"] is False
    assert provenance["scope_source_mode"] == "adaptive_active"


def test_default_off_purpose_resolver_uses_authoritative_legacy_scopes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from v2.backend.app.services import v2_symbol_runtime_universe as svc

    payload = tmp_path / "symbol_universe_status.json"
    payload.write_text(
        json.dumps(
            {
                "generated_at": "2026-07-20T05:10:00Z",
                "binance_usdm_confirmed_symbols": [
                    "BTCUSDT",
                    "ETHUSDT",
                    "DOGEUSDT",
                ],
                "training_symbols": ["DOGEUSDT", "ETHUSDT"],
                "paper_symbols": ["DOGEUSDT"],
                "adaptive_training_selected_symbols": ["BTCUSDT"],
                "adaptive_paper_new_entry_symbols": ["BTCUSDT"],
                "adaptive_scope_activation": {
                    "requested": False,
                    "scope_aware_consumers_bound": False,
                    "active": False,
                },
                "adaptive_symbol_selection": {
                    "decision_time": "2026-07-20T05:10:00Z",
                    "selection_is_execution_authorization": False,
                    "training_selected_symbols": ["BTCUSDT"],
                    "trading_selected_symbols": ["BTCUSDT"],
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(svc, "SYMBOL_UNIVERSE_PUBLIC_PAYLOAD", payload)
    decision = "2026-07-20T05:11:00Z"

    assert resolve_symbols_for_purpose("training", decision_time=decision) == [
        "ETHUSDT",
        "DOGEUSDT",
    ]
    assert resolve_symbols_for_purpose("trading", decision_time=decision) == [
        "DOGEUSDT"
    ]
    provenance = resolve_symbols_for_purpose_with_provenance(
        "training", decision_time=decision
    )
    assert provenance["fresh"] is True
    assert provenance["adaptive_scope_activation_active"] is False
    assert provenance["scope_source_mode"] == "authoritative_legacy_default_off"


def test_stale_adaptive_scope_has_no_baseline_or_major_fallback(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from v2.backend.app.services import v2_symbol_runtime_universe as svc

    payload = tmp_path / "symbol_universe_status.json"
    payload.write_text(
        json.dumps(
            {
                "generated_at": "2026-07-20T05:00:00Z",
                "binance_usdm_confirmed_symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
                "adaptive_training_selected_symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
                "adaptive_paper_new_entry_symbols": ["BTCUSDT"],
                "adaptive_scope_activation": {
                    "requested": True,
                    "scope_aware_consumers_bound": True,
                    "active": True,
                },
                "adaptive_symbol_selection": {
                    "decision_time": "2026-07-20T05:00:00Z",
                    "selection_is_execution_authorization": False,
                    "training_selected_symbols": [
                        "BTCUSDT",
                        "ETHUSDT",
                        "SOLUSDT",
                    ],
                    "trading_selected_symbols": ["BTCUSDT"],
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(svc, "SYMBOL_UNIVERSE_PUBLIC_PAYLOAD", payload)

    assert resolve_symbols_for_purpose(
        "training", decision_time="2026-07-20T05:10:00Z"
    ) == []
    provenance = resolve_symbols_for_purpose_with_provenance(
        "trading", decision_time="2026-07-20T05:10:00Z"
    )
    assert provenance["symbols"] == []
    assert "adaptive_symbol_payload_stale" in provenance["blockers"]
