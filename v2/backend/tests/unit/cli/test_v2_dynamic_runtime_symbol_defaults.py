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
    SMOKE_TEST_SYMBOLS,
    SYMBOL_UNIVERSE_PUBLIC_PAYLOAD,
    resolve_symbols,
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
    expected_first = resolve_symbols(
        explicit=None,
        smoke_test=False,
        include_baseline=True,
    )[0]

    assert (
        paper_online_runtime._resolve_runtime_symbol(None, smoke_test=False)
        == expected_first
    )


def test_feature_snapshot_builder_single_symbol_default_uses_dynamic_first_symbol(
    monkeypatch,
) -> None:
    monkeypatch.delenv("V2_SYMBOL_PROFILE", raising=False)
    expected_first = resolve_symbols(
        explicit=None,
        smoke_test=False,
        include_baseline=True,
    )[0]

    args = v2_feature_snapshot_builder.parse_args(["--once", "--no-write"])
    assert args.symbol == expected_first


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
