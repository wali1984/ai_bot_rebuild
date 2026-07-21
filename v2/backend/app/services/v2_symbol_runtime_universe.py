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

import datetime as dt
import json
import os
import re
from pathlib import Path
from typing import Any, Iterable, List, Mapping, Optional, Sequence, Set, Tuple


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

# Preferred majors are ranked first only when the relevant health/exchange
# scope already contains them.  Preference never fabricates eligibility, and
# the operator can add preferences without replacing the mandatory majors.
MANDATORY_PREFERRED_MAJOR_SYMBOLS: Tuple[str, ...] = (
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
)


def _preferred_majors() -> Tuple[str, ...]:
    preferred = list(MANDATORY_PREFERRED_MAJOR_SYMBOLS)
    seen = set(preferred)
    raw = os.environ.get("V2_PREFERRED_MAJOR_SYMBOLS", "").strip()
    for item in raw.split(",") if raw else ():
        symbol = item.strip().upper()
        if (
            re.fullmatch(r"[A-Z0-9]+USDT", symbol)
            and symbol not in seen
        ):
            seen.add(symbol)
            preferred.append(symbol)
    return tuple(preferred)


PREFERRED_MAJOR_SYMBOLS: Tuple[str, ...] = _preferred_majors()

# Smoke-test only. NEVER the production default.
SMOKE_TEST_SYMBOLS: Tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "SOLUSDT")

SMOKE_TEST_ENV_VAR = "V2_SYMBOL_PROFILE"
SMOKE_TEST_ENV_VALUE = "smoke_test"
VALID_RUNTIME_SYMBOL_RE = re.compile(r"^[A-Z0-9]+USDT$")
ADAPTIVE_SCOPE_MAX_AGE_SECONDS = 180


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
    # Preserve the legacy-compatible authoritative training/paper resolution.
    # The staged adaptive data-collection scope is available only through
    # ``resolve_symbols_for_purpose('data_collection')``.
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


def _read_published_data_collection_symbols() -> List[str]:
    path = SYMBOL_UNIVERSE_PUBLIC_PAYLOAD
    try:
        payload = json.loads(path.read_text())
    except (OSError, ValueError, TypeError):
        return []
    if not isinstance(payload, dict):
        return []
    raw = payload.get("data_collection_symbols")
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        return []
    confirmed = _effective_binance_confirmed_symbols(payload)
    if not confirmed:
        return []
    return _prioritize_majors(
        symbol for symbol in _normalize_runtime_symbols(raw) if symbol in confirmed
    )


def _prioritize_majors(symbols: Iterable[str]) -> List[str]:
    """Rank healthy/in-scope preferred majors first without adding them.

    Preference is ordering only.  A missing/unconfirmed major must not be
    fabricated back into an eligibility or collection scope.
    """
    normalized = _normalize_runtime_symbols(symbols)
    allowed = set(normalized)
    seen: Set[str] = set()
    ordered: List[str] = []
    for s in [
        *[major for major in PREFERRED_MAJOR_SYMBOLS if major in allowed],
        *normalized,
    ]:
        text = str(s or "").upper()
        if text and is_valid_runtime_symbol(text) and text not in seen:
            seen.add(text)
            ordered.append(text)
    return ordered


def _aware_clock(value: Any) -> dt.datetime | None:
    if isinstance(value, dt.datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = dt.datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(dt.timezone.utc)


def _read_adaptive_scope(
    purpose: str,
    *,
    decision_time: Any = None,
) -> tuple[List[str], dict[str, Any]]:
    adaptive_key_by_purpose = {
        "training": "adaptive_training_selected_symbols",
        "trading": "adaptive_paper_new_entry_symbols",
    }
    legacy_key_by_purpose = {
        "training": "training_symbols",
        "trading": "paper_symbols",
    }
    if purpose not in adaptive_key_by_purpose:
        raise ValueError("adaptive_symbol_purpose_must_be_training_or_trading")
    path = SYMBOL_UNIVERSE_PUBLIC_PAYLOAD
    provenance: dict[str, Any] = {
        "purpose": purpose,
        "source_path": str(path),
        "fresh": False,
        "blockers": [],
        "selection_is_execution_authorization": False,
    }
    try:
        payload = json.loads(path.read_text())
    except (OSError, ValueError, TypeError):
        provenance["blockers"] = ["adaptive_symbol_payload_missing_or_invalid"]
        return [], provenance
    if not isinstance(payload, dict):
        provenance["blockers"] = ["adaptive_symbol_payload_not_object"]
        return [], provenance

    decision = (
        _aware_clock(decision_time)
        if decision_time is not None
        else dt.datetime.now(dt.timezone.utc)
    )
    generated = _aware_clock(payload.get("generated_at"))
    blockers: list[str] = []
    warnings: list[str] = []
    activation_raw = payload.get("adaptive_scope_activation")
    activation: Mapping[str, Any] | None
    if activation_raw is None:
        activation = None
        activation_active = False
    elif not isinstance(activation_raw, dict):
        activation = None
        activation_active = False
        blockers.append("adaptive_symbol_scope_activation_contract_invalid")
    else:
        activation = activation_raw
        activation_value = activation.get("active")
        if type(activation_value) is not bool:
            blockers.append("adaptive_symbol_scope_activation_flag_invalid")
        activation_active = activation_value is True

    if activation_active:
        scope_key = adaptive_key_by_purpose[purpose]
        scope_source_mode = "adaptive_active"
        if activation is None or activation.get("requested") is not True:
            blockers.append("adaptive_symbol_scope_activation_not_explicitly_requested")
        if activation is None or activation.get("scope_aware_consumers_bound") is not True:
            blockers.append("adaptive_symbol_scope_consumers_not_explicitly_bound")
    else:
        # Default-off means purpose-aware consumers retain the publisher's
        # existing authoritative scopes.  Merely binding a new consumer to
        # this resolver must not silently activate shadow adaptive fields.
        scope_key = legacy_key_by_purpose[purpose]
        scope_source_mode = "authoritative_legacy_default_off"

    if decision is None:
        raise ValueError("adaptive_symbol_resolution_decision_time_invalid")
    if generated is None:
        blockers.append("adaptive_symbol_payload_generated_at_missing_or_invalid")
    elif generated > decision:
        blockers.append("adaptive_symbol_payload_generated_after_decision")
    elif (decision - generated).total_seconds() > ADAPTIVE_SCOPE_MAX_AGE_SECONDS:
        blockers.append("adaptive_symbol_payload_stale")

    selection = payload.get("adaptive_symbol_selection")
    selection_decision: dt.datetime | None = None
    if activation_active:
        selection_decision = (
            _aware_clock(selection.get("decision_time"))
            if isinstance(selection, dict)
            else None
        )
        if selection_decision is None:
            blockers.append("adaptive_symbol_selection_decision_time_missing_or_invalid")
        elif selection_decision > decision:
            blockers.append("adaptive_symbol_selection_available_after_decision")
        elif (
            decision - selection_decision
        ).total_seconds() > ADAPTIVE_SCOPE_MAX_AGE_SECONDS:
            blockers.append("adaptive_symbol_selection_stale")
        if (
            generated is not None
            and selection_decision is not None
            and generated < selection_decision
        ):
            blockers.append("adaptive_symbol_payload_generated_before_selection_decision")
        if (
            not isinstance(selection, dict)
            or selection.get("selection_is_execution_authorization") is not False
        ):
            blockers.append("adaptive_symbol_selection_authorization_contract_invalid")

    raw = payload.get(scope_key)
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        blockers.append("adaptive_symbol_scope_missing_or_invalid")
        scope: list[str] = []
    else:
        scope = _normalize_runtime_symbols(raw)

    if activation_active and isinstance(selection, dict):
        nested_key = (
            "training_selected_symbols"
            if purpose == "training"
            else "trading_selected_symbols"
        )
        nested = selection.get(nested_key)
        if (
            not isinstance(nested, list)
            or not all(isinstance(item, str) for item in nested)
            or _normalize_runtime_symbols(nested) != scope
        ):
            blockers.append("adaptive_symbol_scope_does_not_match_selection_receipt")
        if purpose == "trading":
            training_scope = payload.get("adaptive_training_selected_symbols")
            if (
                not isinstance(training_scope, list)
                or not all(isinstance(item, str) for item in training_scope)
                or not set(scope).issubset(
                    set(_normalize_runtime_symbols(training_scope))
                )
            ):
                blockers.append("adaptive_trading_scope_not_subset_of_training_scope")

    confirmed = _effective_binance_confirmed_symbols(payload)
    if not confirmed:
        blockers.append("adaptive_symbol_exchange_confirmation_missing")
    else:
        unconfirmed = sorted(set(scope) - confirmed)
        if unconfirmed:
            if activation_active:
                blockers.append("adaptive_symbol_scope_contains_unconfirmed_symbols")
            else:
                warnings.append("legacy_authoritative_scope_unconfirmed_symbols_filtered")
        scope = [symbol for symbol in scope if symbol in confirmed]

    provenance.update(
        generated_at=(generated.isoformat() if generated is not None else None),
        selection_decision_time=(
            selection_decision.isoformat() if selection_decision is not None else None
        ),
        adaptive_scope_activation_active=activation_active,
        scope_source_mode=scope_source_mode,
        scope_field=scope_key,
        blockers=sorted(set(blockers)),
        warnings=sorted(set(warnings)),
        fresh=not blockers,
    )
    return (_prioritize_majors(scope) if not blockers else []), provenance


def resolve_symbols_for_purpose(
    purpose: str,
    *,
    explicit: Optional[Iterable[str]] = None,
    smoke_test: bool = False,
    include_baseline: bool = True,
    decision_time: Any = None,
) -> List[str]:
    """Resolve collection or strict adaptive candidate scopes.

    Existing callers continue to use :func:`resolve_symbols`, whose behavior is
    the data-collection/legacy-compatible path.  Training and trading purposes
    consume fresh adaptive fields only when the publisher's double activation
    guard is active; while default-off they retain the authoritative legacy
    training/paper fields.  Neither path has a baseline fallback, and trading
    scope membership is never execution authorization.
    """

    normalized_purpose = str(purpose or "").strip().lower()
    if normalized_purpose in {"data", "data_collection", "collection"}:
        explicit_list = _parse_explicit(explicit)
        if explicit_list or smoke_test or os.environ.get(SMOKE_TEST_ENV_VAR) == SMOKE_TEST_ENV_VALUE:
            return resolve_symbols(
                explicit=explicit,
                smoke_test=smoke_test,
                include_baseline=include_baseline,
            )
        collection = _read_published_data_collection_symbols()
        return collection or resolve_symbols(include_baseline=include_baseline)
    if normalized_purpose not in {"training", "trading"}:
        raise ValueError("symbol_resolution_purpose_invalid")
    scope, _provenance = _read_adaptive_scope(
        normalized_purpose,
        decision_time=decision_time,
    )
    requested = _parse_explicit(explicit)
    if requested:
        allowed = set(scope)
        return [symbol for symbol in requested if symbol in allowed]
    return scope


def resolve_symbols_for_purpose_with_provenance(
    purpose: str,
    *,
    explicit: Optional[Iterable[str]] = None,
    smoke_test: bool = False,
    include_baseline: bool = True,
    decision_time: Any = None,
) -> dict[str, Any]:
    normalized_purpose = str(purpose or "").strip().lower()
    if normalized_purpose in {"data", "data_collection", "collection"}:
        symbols = resolve_symbols_for_purpose(
            "data_collection",
            explicit=explicit,
            smoke_test=smoke_test,
            include_baseline=include_baseline,
        )
        provenance = {
            "symbols": symbols,
            "symbol_profile": "adaptive_data_collection_or_legacy_fallback",
            "smoke_test": bool(
                smoke_test
                or os.environ.get(SMOKE_TEST_ENV_VAR) == SMOKE_TEST_ENV_VALUE
            ),
            "source_path": str(SYMBOL_UNIVERSE_PUBLIC_PAYLOAD),
            "count": len(symbols),
        }
        provenance["purpose"] = "data_collection"
        return provenance
    scope, provenance = _read_adaptive_scope(
        normalized_purpose,
        decision_time=decision_time,
    )
    requested = _parse_explicit(explicit)
    if requested:
        allowed = set(scope)
        scope = [symbol for symbol in requested if symbol in allowed]
        provenance["explicit_intersection_applied"] = True
    provenance["symbols"] = scope
    provenance["count"] = len(scope)
    return provenance


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
