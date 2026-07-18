"""V2 dynamic symbol-universe runtime resolver.

Single source of truth that every V2 ingestor / feature / TA / liquidation
worker uses to pick its default symbol set. Replaces hard-coded
``BTCUSDT/ETHUSDT/SOLUSDT`` or ``BTCUSDT`` defaults that Codex 5.5
flagged as a 3-symbol/BTC-only drift in
``V2_FULL_DYNAMIC_REBUILD_BLOCKER_EXECUTION_CODEX_FAIL``.

Resolution order
----------------
1. If the caller passed an explicit non-empty symbol list, use it.
2. If ``V2_SYMBOL_PROFILE=smoke_test`` or ``--smoke-test`` flag is set,
   return :data:`SMOKE_TEST_SYMBOLS` (3 symbols, smoke-test only).
3. If the symbol-universe publisher payload at
   :data:`SYMBOL_UNIVERSE_PUBLIC_PAYLOAD` exists, read its
   ``discovered_symbols`` (or fallback fields) and merge with the
   25-symbol baseline.
4. Otherwise fall back to the 25-symbol legacy baseline.

The resolver never returns the smoke-test 3 set unless the caller
explicitly opted into smoke-test mode.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Set, Tuple


REPO = Path("/home/wali/Desktop/AI BOT REBUILD")

SYMBOL_UNIVERSE_PUBLIC_PAYLOAD = (
    REPO
    / "v2/frontend/public/operator_runtime/symbol_universe/latest/"
      "symbol_universe_status.json"
)

# 25-symbol legacy migration baseline.
BASELINE_25_SYMBOLS: Tuple[str, ...] = (
    "1000BONKUSDT", "1000FLOKIUSDT", "1000PEPEUSDT", "1000SHIBUSDT",
    "ALICEUSDT", "ASTERUSDT", "AUCTIONUSDT", "AVNTUSDT",
    "BANKUSDT", "BARDUSDT", "BTCUSDT", "DOGEUSDT",
    "ETHUSDT", "FARTCOINUSDT", "HIGHUSDT", "LINKUSDT",
    "LTCUSDT", "PENGUUSDT", "PIPPINUSDT", "RAVEUSDT",
    "RIVERUSDT", "SOLUSDT", "UNIUSDT", "WIFUSDT", "XRPUSDT",
)

# Preferred majors — ALWAYS included and ranked FIRST in the runtime universe
# (operator directive 2026-07-18: BTC/ETH/SOL are the first symbols to trade).
# This is an ORDERING PREFERENCE, not an exclusive whitelist: the full adaptive
# universe still follows, no static threshold or universe restriction is implied.
# Operator-tunable via env (comma-separated) without a code change.
def _preferred_majors() -> Tuple[str, ...]:
    raw = os.environ.get("V2_PREFERRED_MAJOR_SYMBOLS", "").strip()
    if raw:
        vals = tuple(s.strip().upper() for s in raw.split(",") if s.strip())
        if vals:
            return vals
    return ("BTCUSDT", "ETHUSDT", "SOLUSDT")


PREFERRED_MAJOR_SYMBOLS: Tuple[str, ...] = _preferred_majors()

# Smoke-test only. NEVER the production default.
SMOKE_TEST_SYMBOLS: Tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "SOLUSDT")

SMOKE_TEST_ENV_VAR = "V2_SYMBOL_PROFILE"
SMOKE_TEST_ENV_VALUE = "smoke_test"
VALID_RUNTIME_SYMBOL_RE = re.compile(r"^[A-Z0-9]+USDT$")


def is_valid_runtime_symbol(symbol: str) -> bool:
    """Return true for the V2 production USDT symbol contract.

    Dynamic discovery can see non-trading labels from external providers.
    Runtime ingestors, trainers, and liquidation engines must not treat
    those labels as tradable symbols.
    """
    return bool(VALID_RUNTIME_SYMBOL_RE.fullmatch(str(symbol or "").strip().upper()))


def _normalize_runtime_symbols(symbols: Iterable[str]) -> List[str]:
    out: List[str] = []
    seen: Set[str] = set()
    for symbol in symbols:
        text = str(symbol or "").strip().upper()
        if not text or not is_valid_runtime_symbol(text) or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _parse_explicit(symbols: Optional[Iterable[str]]) -> List[str]:
    if symbols is None:
        return []
    if isinstance(symbols, str):
        return _normalize_runtime_symbols(s.strip().upper() for s in symbols.split(",") if s.strip())
    return _normalize_runtime_symbols(s.strip().upper() for s in symbols if s and s.strip())


def _payload_has_broad_discovered_scope(payload: dict) -> bool:
    baseline = set(BASELINE_25_SYMBOLS)
    for key in (
        "discovered_symbols",
        "dynamic_discovered_symbols",
        "observed_symbols",
        "symbols",
        "universe",
    ):
        value = payload.get(key)
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            continue
        symbols = set(_normalize_runtime_symbols(value))
        if len(symbols) > len(SMOKE_TEST_SYMBOLS) and len(symbols & baseline) >= 10:
            return True
    return False


def _effective_binance_confirmed_symbols(payload: dict) -> Set[str]:
    confirmed = set(
        _normalize_runtime_symbols(
            payload.get("binance_usdm_confirmed_symbols")
            or payload.get("tradable_symbols")
            or []
        )
    )
    if confirmed and confirmed.issubset(set(SMOKE_TEST_SYMBOLS)) and _payload_has_broad_discovered_scope(payload):
        return set()
    return confirmed


def _read_published_symbols() -> Tuple[List[str], Optional[str], Set[str]]:
    p = SYMBOL_UNIVERSE_PUBLIC_PAYLOAD
    if not p.is_file():
        return [], None, set()
    try:
        d = json.loads(p.read_text())
    except Exception:
        return [], None, set()
    binance_confirmed = _effective_binance_confirmed_symbols(d)
    # Prefer the exchange-confirmed training/paper scope for live data workers.
    # ``discovered_symbols`` can include market-intelligence-only or stale
    # observed symbols that should not be fetched by Binance ingestors.
    for key in (
        "training_symbols",
        "paper_symbols",
        "live_data_symbols",
        "trainer_live_symbols",
        "paper_shadow_live_symbols",
        "discovered_symbols",
        "dynamic_discovered_symbols",
        "observed_symbols",
        "symbols",
        "universe",
    ):
        v = d.get(key)
        if isinstance(v, list) and all(isinstance(x, str) for x in v) and v:
            symbols = _normalize_runtime_symbols(v)
            if binance_confirmed:
                symbols = [symbol for symbol in symbols if symbol in binance_confirmed]
            return symbols, str(p), binance_confirmed
    return [], str(p), binance_confirmed


def _prioritize_majors(symbols: Iterable[str]) -> List[str]:
    """Rank preferred majors (BTC/ETH/SOL) FIRST, always included, then the rest
    in their existing (market-driven) order. De-dupes and validates. Ordering
    preference only — never removes or restricts the discovered universe."""
    seen: Set[str] = set()
    ordered: List[str] = []
    for s in list(PREFERRED_MAJOR_SYMBOLS) + list(symbols):
        text = str(s or "").upper()
        if text and is_valid_runtime_symbol(text) and text not in seen:
            seen.add(text)
            ordered.append(text)
    return ordered


def resolve_symbols(
    *,
    explicit: Optional[Iterable[str]] = None,
    smoke_test: bool = False,
    include_baseline: bool = True,
) -> List[str]:
    """Return the runtime symbol list per the resolution order above.

    Production paths rank preferred majors (BTC/ETH/SOL) first; explicit and
    smoke-test overrides are returned verbatim (deliberate caller intent)."""
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
    discovered, _src, binance_confirmed = _read_published_symbols()
    if include_baseline:
        merged: List[str] = []
        seen: Set[str] = set()
        baseline_symbols = [
            symbol
            for symbol in BASELINE_25_SYMBOLS
            if not binance_confirmed or symbol in binance_confirmed
        ]
        for s in list(baseline_symbols) + discovered:
            text = str(s or "").upper()
            if text and is_valid_runtime_symbol(text) and text not in seen:
                seen.add(text)
                merged.append(text)
        if merged:
            return _prioritize_majors(merged)
    elif discovered:
        return _prioritize_majors(discovered)

    # 4. Final fallback: 25-symbol baseline.
    return _prioritize_majors(BASELINE_25_SYMBOLS)


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
    discovered, src, binance_confirmed = _read_published_symbols()
    symbols = resolve_symbols(
        explicit=None, smoke_test=False, include_baseline=include_baseline
    )
    return {
        "symbols": symbols,
        "symbol_profile": "dynamic_or_baseline",
        "smoke_test": False,
        "source_path": src,
        "discovered_count": len(discovered),
        "binance_usdm_confirmed_count": len(binance_confirmed),
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
