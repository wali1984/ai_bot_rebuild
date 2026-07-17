"""Regression guard: every patched CLI / service that previously hard-coded
``BTCUSDT``-only or ``BTCUSDT/ETHUSDT/SOLUSDT`` defaults now routes through
:func:`v2.backend.app.services.v2_symbol_runtime_universe.resolve_symbols`.

Each test loads the module source and asserts:

- the previous hard-coded 3-symbol or 1-symbol argparse default is gone;
- the module either imports ``resolve_symbols`` or relies on a caller that
  does;
- the patched defaults still preserve fail-closed behavior for the
  smoke-test 3 set when ``V2_SYMBOL_PROFILE`` is unset.

Paper-only. No torch import. No exchange call. No Redis write. No legacy
path read.
"""
from __future__ import annotations

import importlib
import os
import re
from pathlib import Path

import pytest


REPO_ROOT = Path("/home/wali/Desktop/AI BOT REBUILD")


# (file_path, must-not-contain regexes, expected-to-contain regexes)
PATCHED_FILES: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    (
        "v2/backend/app/cli/v2_alt_data_symbol_universe_scoring.py",
        (r'symbols:\s*tuple\[str,\s*\.\.\.\]\s*=\s*\(\s*"BTCUSDT"',),
        (r"from v2\.backend\.app\.services\.v2_symbol_runtime_universe import resolve_symbols",),
    ),
    (
        "v2/backend/app/cli/v2_full_observation_builder_status.py",
        (r'default\s*=\s*"BTCUSDT,ETHUSDT,SOLUSDT"',),
        (r"resolve_symbols", r"--smoke-test"),
    ),
    (
        "v2/backend/app/cli/v2_alt_data_symbol_candidate_publisher.py",
        (r'^DEFAULT_SYMBOLS\s*=\s*\(\s*"BTCUSDT"',),
        (r"_resolve_default_symbols", r"resolve_symbols"),
    ),
    (
        "v2/backend/app/cli/v2_feature_pipeline_native.py",
        (r'add_argument\(\s*"--symbol",\s*default\s*=\s*"BTCUSDT"',),
        (r"resolve_symbols", r"--smoke-test"),
    ),
    (
        "v2/backend/app/cli/v2_market_ingestor.py",
        (r'add_argument\(\s*"--symbol",\s*default\s*=\s*"BTCUSDT"\s*\)',),
        (r"resolve_symbols", r"--smoke-test"),
    ),
    (
        "v2/backend/app/cli/v2_alternative_data_status.py",
        (
            r'symbols:\s*tuple\[str,\s*\.\.\.\]\s*=\s*\(\s*"BTCUSDT"',
            r'add_argument\(\s*"--symbols",\s*default\s*=\s*"BTCUSDT,ETHUSDT,SOLUSDT"',
        ),
        (r"resolve_symbols", r"--smoke-test"),
    ),
    (
        "v2/backend/app/cli/v2_website_redis_bridge_status.py",
        (r'symbols:\s*tuple\[str,\s*\.\.\.\]\s*=\s*\(\s*"BTCUSDT"',),
        (r"resolve_symbols",),
    ),
    (
        "v2/backend/app/cli/readonly_market_exchange_data_plane.py",
        (r'add_argument\(\s*"--symbol",\s*default\s*=\s*"BTCUSDT"\s*\)',),
        (r"resolve_symbols", r"--smoke-test"),
    ),
    (
        "v2/backend/app/services/native_runtime_migration/safety.py",
        (
            # Old single-line constant assignment without docstring is gone.
            r'^V2_NATIVE_ACTIVE_SYMBOLS\s*=\s*\(\s*"BTCUSDT",\s*"ETHUSDT",\s*"SOLUSDT"\s*\)\s*$',
        ),
        (
            r"V2_NATIVE_INITIAL_BRIDGE_SYMBOLS",
            r"v2_native_currently_active_symbols",
            r"resolve_symbols",
        ),
    ),
    (
        "v2/backend/app/services/native_runtime_migration/v2_paper_startup_manifest.py",
        (
            r'^V2_NATIVE_ACTIVE_SYMBOLS\s*=\s*\(\s*"BTCUSDT",\s*"ETHUSDT",\s*"SOLUSDT"\s*\)\s*$',
        ),
        (
            r"V2_NATIVE_INITIAL_BRIDGE_SYMBOLS",
            r"resolve_symbols",
            r"currently_active_symbols_source",
        ),
    ),
)

ACTIVE_RUNTIME_CLI_DRIFT_ALLOWLIST = {
    # These files are not active paper/shadow runtime defaults. They are
    # blocked live/canary proposal or documentation lanes and are reviewed by
    # separate operator gates.
    "v2/backend/app/cli/v2_live_canary_one_order_enablement.py",
    "v2/backend/app/cli/tonight_live_like_paper_shadow.py",
    "v2/backend/app/cli/paper_strategy_edge_tightening.py",
    # Backtest runner is a dev/research tool; BTCUSDT default is intentional
    # for convenience and does not feed live or paper runtime decisions.
    "v2/backend/app/cli/v2_backtest_runner.py",
    # Public-archive backfill is an explicit REST fallback/backfill operation
    # (BINANCE_REST_FALLBACK_ALLOWED-gated), not an active paper/shadow runtime
    # decision path; its BTCUSDT default is a manual-op convenience.
    "v2/backend/app/cli/v2_binance_public_data_backfill.py",
    # Day-5 feature-builder integration test harness (a --symbol "Test symbol"
    # default), not active runtime.
    "v2/backend/app/cli/day5_integration_test.py",
}

ACTIVE_RUNTIME_FORBIDDEN_DEFAULT_PATTERNS = (
    r'add_argument\([^)]*"--symbols"[^)]*default\s*=\s*"BTCUSDT',
    r'add_argument\([^)]*"--symbol"[^)]*default\s*=\s*"BTCUSDT"',
    r"DEFAULT_SYMBOLS\s*=\s*\(\s*['\"]BTCUSDT['\"]",
    r"symbols:\s*tuple\[str,\s*\.\.\.\]\s*=\s*\(\s*['\"]BTCUSDT['\"]",
    r"p\.get\([^,]+,\s*['\"]BTCUSDT['\"]\)",
    r"s\.get\([^,]+,\s*['\"]BTCUSDT['\"]\)",
)


@pytest.mark.parametrize("file_path,forbidden,required", PATCHED_FILES)
def test_module_source_no_longer_pins_three_symbol_default(
    file_path: str,
    forbidden: tuple[str, ...],
    required: tuple[str, ...],
) -> None:
    src = (REPO_ROOT / file_path).read_text(encoding="utf-8")
    for pat in forbidden:
        assert not re.search(pat, src, re.MULTILINE), (
            f"{file_path}: still contains forbidden hard-coded default "
            f"matching /{pat}/"
        )
    for pat in required:
        assert re.search(pat, src, re.MULTILINE), (
            f"{file_path}: expected to contain /{pat}/ (resolver wiring or "
            f"smoke-test flag)"
        )


def test_active_runtime_cli_source_has_no_literal_btc_or_three_symbol_default() -> None:
    for path in (REPO_ROOT / "v2/backend/app/cli").glob("*.py"):
        rel = str(path.relative_to(REPO_ROOT))
        if rel in ACTIVE_RUNTIME_CLI_DRIFT_ALLOWLIST:
            continue
        src = path.read_text(encoding="utf-8")
        for pat in ACTIVE_RUNTIME_FORBIDDEN_DEFAULT_PATTERNS:
            assert not re.search(pat, src, re.MULTILINE | re.DOTALL), (
                f"{rel}: active V2 CLI still contains a BTC-only or "
                f"BTC/ETH/SOL default matching /{pat}/"
            )


def test_resolver_returns_baseline_when_no_explicit_or_smoke() -> None:
    """The resolver itself returns the 25-symbol baseline by default."""
    os.environ.pop("V2_SYMBOL_PROFILE", None)
    svc = importlib.import_module(
        "v2.backend.app.services.v2_symbol_runtime_universe"
    )
    symbols = svc.resolve_symbols()
    assert len(symbols) >= 25
    assert "BTCUSDT" in symbols and "ETHUSDT" in symbols and "SOLUSDT" in symbols
    # Critical: the resolver default must NOT be just the smoke-test 3.
    assert tuple(symbols[:3]) != svc.SMOKE_TEST_SYMBOLS or len(symbols) > 3


def test_resolver_rejects_explicit_three_symbol_set_without_smoke_optin() -> None:
    os.environ.pop("V2_SYMBOL_PROFILE", None)
    svc = importlib.import_module(
        "v2.backend.app.services.v2_symbol_runtime_universe"
    )
    with pytest.raises(ValueError, match="V2_SYMBOL_DEFAULT_DRIFT"):
        svc.resolve_symbols(
            explicit=["BTCUSDT", "ETHUSDT", "SOLUSDT"], smoke_test=False
        )


def test_resolver_accepts_smoke_optin_via_flag() -> None:
    os.environ.pop("V2_SYMBOL_PROFILE", None)
    svc = importlib.import_module(
        "v2.backend.app.services.v2_symbol_runtime_universe"
    )
    symbols = svc.resolve_symbols(smoke_test=True)
    assert tuple(symbols) == svc.SMOKE_TEST_SYMBOLS


def test_resolver_accepts_smoke_optin_via_env() -> None:
    svc = importlib.import_module(
        "v2.backend.app.services.v2_symbol_runtime_universe"
    )
    os.environ["V2_SYMBOL_PROFILE"] = "smoke_test"
    try:
        symbols = svc.resolve_symbols()
    finally:
        os.environ.pop("V2_SYMBOL_PROFILE", None)
    assert tuple(symbols) == svc.SMOKE_TEST_SYMBOLS


def test_native_runtime_migration_payload_emits_dynamic_currently_active() -> None:
    """The startup-manifest payload must report dynamically resolved
    currently_active_symbols (not the legacy 3-symbol pin), plus expose the
    historical initial-bridge set under a distinct key.
    """
    os.environ.pop("V2_SYMBOL_PROFILE", None)
    mod = importlib.import_module(
        "v2.backend.app.services.native_runtime_migration.v2_paper_startup_manifest"
    )
    payload = mod.build_dynamic_symbol_paper_runtime_coverage()
    assert "currently_active_symbols" in payload
    assert "initial_bridge_migration_symbols" in payload
    assert payload["initial_bridge_migration_symbols"] == list(
        ("BTCUSDT", "ETHUSDT", "SOLUSDT")
    )
    # Dynamic resolver should return more than the 3 initial bridge symbols.
    assert len(payload["currently_active_symbols"]) >= 25
    assert (
        payload["currently_active_symbols_source"]
        == "v2_symbol_runtime_universe.resolve_symbols(baseline+published)"
    )


def test_safety_module_exposes_initial_bridge_constant() -> None:
    mod = importlib.import_module(
        "v2.backend.app.services.native_runtime_migration.safety"
    )
    assert mod.V2_NATIVE_INITIAL_BRIDGE_SYMBOLS == ("BTCUSDT", "ETHUSDT", "SOLUSDT")
    # Backwards-compat alias preserved.
    assert mod.V2_NATIVE_ACTIVE_SYMBOLS == mod.V2_NATIVE_INITIAL_BRIDGE_SYMBOLS
    # Dynamic helper exists and returns >=25 by default.
    os.environ.pop("V2_SYMBOL_PROFILE", None)
    assert len(mod.v2_native_currently_active_symbols()) >= 25
