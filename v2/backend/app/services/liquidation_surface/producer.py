"""Runtime assembly and publication for prospective liquidation surfaces.

This module reads exact Redis bytes only.  It never calls a market-data
provider, never consumes forced-liquidation events as prospective levels, and
never places or modifies an order.  Missing optional evidence produces a
degraded observation surface; invalid or missing finalized candles quarantine
only the affected symbol/timeframe lane.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any, cast

from v2.backend.app.services.binance_usdm_leverage_bracket_evidence import (
    EvidenceSecurityContext,
)

from .contracts import (
    LeverageBracket,
    MarkPriceObservation,
    OpenInterestObservation,
    SurfaceRequest,
)
from .model import build_liquidation_surface
from .publication import (
    SurfacePublicationSecurityContext,
    derive_publication_scope_sha256,
    publish_liquidation_surface,
)
from .source_adapters import (
    RawRedisEvidence,
    SourceAdapterError,
    adapt_binance_finalized_candles,
    adapt_binance_mark_price,
    adapt_coinank_plan3_open_interest,
)
from .trainer_admission import (
    PreparedLiquidationSurfaceCandidate,
    prepare_liquidation_surface_candidate,
    publication_mapping_with_prepared_source_bundle,
)

PRODUCER_SCHEMA_VERSION = "v2_liquidation_surface_producer_status_v1"
SURFACE_TIMEFRAMES = ("1m", "5m", "15m", "1h", "4h")
COINANK_OI_TIMEFRAMES = ("5m", "15m", "30m", "1h", "4h", "1d")
DEFAULT_ARCHIVE_TTL_SECONDS = 600
DEFAULT_RECEIPT_TTL_SECONDS = 180
DEFAULT_STATUS_TTL_SECONDS = 180
MAX_ERROR_SAMPLES = 32
MAX_REASON_TEXT = 192
_SYMBOL_RE = re.compile(r"^[A-Z0-9]{5,30}$", re.ASCII)
_TIMEFRAME_MS = {
    "1m": 60_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
}
_PUBLICATION_SCOPE_FIELDS = (
    "credential_binding_id",
    "exchange_environment",
    "base_url_origin",
    "evidence_auth_key_id",
    "credential_account_specific",
)


class LiquidationSurfaceProducerError(RuntimeError):
    """Producer configuration, transport, or required-source failure."""


@dataclass(frozen=True, slots=True)
class ExactRedisSnapshot:
    """One transaction-bounded exact multi-key read and its Redis clock."""

    values: Mapping[str, bytes | None]
    consumer_observed_at_ms: int


@dataclass(frozen=True, slots=True)
class AdaptiveOISelection:
    """Best valid CoinAnk OI series selected from currently available intervals."""

    observations: tuple[OpenInterestObservation, ...]
    source_timeframe: str | None
    valid_candidate_count: int
    missing_candidate_count: int
    rejection_counts: Mapping[str, int]
    evidence: RawRedisEvidence | None = None


@dataclass(slots=True)
class MarkPriceHistory:
    """Keep the latest two distinct exact mark-price payload observations."""

    _samples: dict[str, tuple[RawRedisEvidence, ...]] = field(default_factory=dict)

    def record(self, *, symbol: str, value: bytes | None, observed_at_ms: int) -> None:
        canonical = _symbol(symbol)
        if value is None:
            return
        evidence = RawRedisEvidence.from_value(
            key=f"v2:market:mark_price:{canonical}",
            value=value,
            consumer_observed_at_ms=observed_at_ms,
        )
        existing = self._samples.get(canonical, ())
        if existing and existing[-1].raw == evidence.raw:
            return
        self._samples[canonical] = (*existing, evidence)[-2:]

    def record_snapshot(
        self,
        *,
        symbols: Sequence[str],
        snapshot: ExactRedisSnapshot,
    ) -> None:
        for symbol in symbols:
            canonical = _symbol(symbol)
            self.record(
                symbol=canonical,
                value=snapshot.values.get(f"v2:market:mark_price:{canonical}"),
                observed_at_ms=snapshot.consumer_observed_at_ms,
            )

    def latest(self, symbol: str) -> tuple[RawRedisEvidence, ...]:
        return self._samples.get(_symbol(symbol), ())

    def two_sample_symbol_count(self, symbols: Iterable[str]) -> int:
        return sum(len(self.latest(symbol)) >= 2 for symbol in symbols)


def _symbol(value: object) -> str:
    if type(value) is not str or _SYMBOL_RE.fullmatch(cast(str, value)) is None:
        raise LiquidationSurfaceProducerError("PRODUCER_SYMBOL_INVALID")
    return cast(str, value)


def _timeframes(values: Sequence[str]) -> tuple[str, ...]:
    if type(values) not in (tuple, list) or not values:
        raise LiquidationSurfaceProducerError("PRODUCER_TIMEFRAMES_INVALID")
    result = tuple(values)
    if len(set(result)) != len(result) or any(value not in SURFACE_TIMEFRAMES for value in result):
        raise LiquidationSurfaceProducerError("PRODUCER_TIMEFRAMES_INVALID")
    return result


def _redis_time_parts(value: object) -> tuple[int, int]:
    if not isinstance(value, tuple | list) or len(value) != 2:
        raise LiquidationSurfaceProducerError("REDIS_TIME_REPLY_INVALID")
    seconds, microseconds = value
    if (
        type(seconds) is not int
        or type(microseconds) is not int
        or seconds <= 0
        or not 0 <= microseconds < 1_000_000
    ):
        raise LiquidationSurfaceProducerError("REDIS_TIME_REPLY_INVALID")
    return seconds, microseconds


def _redis_time_ms(value: object) -> int:
    seconds, microseconds = _redis_time_parts(value)
    # Availability and decision clocks use a conservative millisecond ceiling.
    # This prevents a microsecond event from being represented as available in
    # the preceding millisecond and preserves ordering across Redis TIME calls.
    return seconds * 1_000 + (microseconds + 999) // 1_000


def redis_now_ms(redis_client: Any) -> int:
    try:
        return _redis_time_ms(redis_client.time())
    except LiquidationSurfaceProducerError:
        raise
    except Exception as exc:
        raise LiquidationSurfaceProducerError("REDIS_TIME_UNAVAILABLE") from exc


def redis_utc_now(redis_client: Any) -> datetime:
    """Return the exact Redis server clock as an aware UTC datetime."""

    try:
        seconds, microseconds = _redis_time_parts(redis_client.time())
    except LiquidationSurfaceProducerError:
        raise
    except Exception as exc:
        raise LiquidationSurfaceProducerError("REDIS_TIME_UNAVAILABLE") from exc
    return datetime.fromtimestamp(seconds, tz=UTC).replace(microsecond=microseconds)


def read_exact_redis_snapshot(
    redis_client: Any,
    *,
    keys: Sequence[str],
) -> ExactRedisSnapshot:
    """Read exact bytes followed by Redis TIME inside one MULTI/EXEC."""

    ordered = tuple(keys)
    if not ordered or len(set(ordered)) != len(ordered):
        raise LiquidationSurfaceProducerError("REDIS_SNAPSHOT_KEYS_INVALID")
    if any(type(key) is not str or not key or key.strip() != key for key in ordered):
        raise LiquidationSurfaceProducerError("REDIS_SNAPSHOT_KEYS_INVALID")
    try:
        pipe = redis_client.pipeline(transaction=True)
        pipe.mget(ordered)
        pipe.time()
        response = pipe.execute()
    except Exception as exc:
        raise LiquidationSurfaceProducerError("REDIS_SNAPSHOT_READ_FAILED") from exc
    if not isinstance(response, tuple | list) or len(response) != 2:
        raise LiquidationSurfaceProducerError("REDIS_SNAPSHOT_REPLY_INVALID")
    raw_values, raw_clock = response
    if not isinstance(raw_values, tuple | list) or len(raw_values) != len(ordered):
        raise LiquidationSurfaceProducerError("REDIS_SNAPSHOT_REPLY_INVALID")
    values: dict[str, bytes | None] = {}
    for key, value in zip(ordered, raw_values, strict=True):
        if value is not None and type(value) is not bytes:
            raise LiquidationSurfaceProducerError(
                "REDIS_BINARY_RESPONSE_REQUIRED_FOR_EXACT_SOURCE_BYTES"
            )
        values[key] = cast(bytes | None, value)
    return ExactRedisSnapshot(
        values=MappingProxyType(values),
        consumer_observed_at_ms=_redis_time_ms(raw_clock),
    )


def publication_scope_metadata(
    bracket_security_context: EvidenceSecurityContext,
) -> Mapping[str, object]:
    safe = bracket_security_context.safe_metadata()
    try:
        material = {field: safe[field] for field in _PUBLICATION_SCOPE_FIELDS}
    except KeyError as exc:
        raise LiquidationSurfaceProducerError("BRACKET_SCOPE_METADATA_INCOMPLETE") from exc
    return MappingProxyType(material)


def require_publication_scope_binding(
    *,
    bracket_security_context: EvidenceSecurityContext,
    publication_security_context: SurfacePublicationSecurityContext,
) -> None:
    derived = derive_publication_scope_sha256(
        publication_scope_metadata(bracket_security_context)
    )
    if derived != publication_security_context.publication_scope_sha256:
        raise LiquidationSurfaceProducerError("PUBLICATION_BRACKET_SCOPE_BINDING_MISMATCH")


def select_adaptive_coinank_open_interest(
    *,
    symbol: str,
    snapshot: ExactRedisSnapshot,
    candidate_timeframes: Sequence[str] = COINANK_OI_TIMEFRAMES,
) -> AdaptiveOISelection:
    """Select the most recent valid OI cutoff, then the finest resolution.

    Selection depends only on the currently observed finalized data.  It does
    not use a fixed market-freshness threshold.  The model later derives its
    freshness budget from the selected series' observed cadence and lag.
    """

    canonical = _symbol(symbol)
    candidates: list[tuple[tuple[int, int, str], str, tuple[OpenInterestObservation, ...]]] = []
    rejections: Counter[str] = Counter()
    missing = 0
    for timeframe in tuple(candidate_timeframes):
        if timeframe not in COINANK_OI_TIMEFRAMES:
            raise LiquidationSurfaceProducerError("COINANK_OI_CANDIDATE_TIMEFRAME_INVALID")
        key = f"latest:coinank:open_interest:{canonical}:{timeframe}"
        raw = snapshot.values.get(key)
        if raw is None:
            missing += 1
            continue
        try:
            observations = adapt_coinank_plan3_open_interest(
                RawRedisEvidence.from_value(
                    key=key,
                    value=raw,
                    consumer_observed_at_ms=snapshot.consumer_observed_at_ms,
                ),
                symbol=canonical,
                source_timeframe=timeframe,
            )
        except SourceAdapterError as exc:
            rejections[str(exc)[:MAX_REASON_TEXT]] += 1
            continue
        rank = (
            observations[-1].feature_cutoff_ms,
            -_TIMEFRAME_MS[timeframe],
            timeframe,
        )
        candidates.append((rank, timeframe, observations))
    if not candidates:
        return AdaptiveOISelection(
            observations=(),
            evidence=None,
            source_timeframe=None,
            valid_candidate_count=0,
            missing_candidate_count=missing,
            rejection_counts=MappingProxyType(dict(sorted(rejections.items()))),
        )
    _rank, selected_timeframe, selected = max(candidates, key=lambda item: item[0])
    selected_key = f"latest:coinank:open_interest:{canonical}:{selected_timeframe}"
    selected_raw = snapshot.values.get(selected_key)
    if selected_raw is None:
        raise LiquidationSurfaceProducerError("SELECTED_COINANK_OI_EXACT_BYTES_MISSING")
    return AdaptiveOISelection(
        observations=selected,
        evidence=RawRedisEvidence.from_value(
            key=selected_key,
            value=selected_raw,
            consumer_observed_at_ms=snapshot.consumer_observed_at_ms,
        ),
        source_timeframe=selected_timeframe,
        valid_candidate_count=len(candidates),
        missing_candidate_count=missing,
        rejection_counts=MappingProxyType(dict(sorted(rejections.items()))),
    )


def _adapt_marks(
    *,
    symbol: str,
    history: MarkPriceHistory,
) -> tuple[tuple[MarkPriceObservation, ...], tuple[str, ...]]:
    rows: list[MarkPriceObservation] = []
    errors: list[str] = []
    for evidence in history.latest(symbol):
        try:
            rows.append(adapt_binance_mark_price(evidence, symbol=symbol))
        except SourceAdapterError as exc:
            errors.append(str(exc)[:MAX_REASON_TEXT])
    return tuple(rows[-2:]), tuple(errors)


def _bracket_observations(
    result: Mapping[str, Any],
    *,
    as_of_time_ms: int,
    generated_at_ms: int,
) -> tuple[LeverageBracket, ...]:
    observations = result.get("observations")
    if (
        result.get("status") != "READY"
        or result.get("evidence_authenticated") is not True
        or not isinstance(observations, tuple)
        or not observations
        or any(not isinstance(row, LeverageBracket) for row in observations)
    ):
        return ()
    typed = cast(tuple[LeverageBracket, ...], observations)
    if any(
        type(clock) is not int
        or not (
            bracket.fetched_at_ms
            <= bracket.ingested_at_ms
            <= bracket.available_at_ms
            <= as_of_time_ms
            <= generated_at_ms
            < bracket.expires_at_ms
        )
        for bracket in typed
        for clock in (
            bracket.fetched_at_ms,
            bracket.ingested_at_ms,
            bracket.available_at_ms,
            bracket.expires_at_ms,
        )
    ):
        # Authenticated evidence can cross its exclusive adaptive validity
        # boundary during a long universe cycle.  It is then omitted rather
        # than allowed to fail or contaminate the affected lane.
        return ()
    return typed


def build_lane_candidate(
    *,
    symbol: str,
    timeframe: str,
    candle_raw: bytes | None,
    source_observed_at_ms: int,
    mark_history: MarkPriceHistory,
    oi_selection: AdaptiveOISelection,
    bracket_result: Mapping[str, Any],
    as_of_time_ms: int,
    generated_at_ms: int,
) -> tuple[dict[str, Any], Mapping[str, object]]:
    """Build one lane, degrading optional sources but never candles."""

    canonical = _symbol(symbol)
    _timeframes((timeframe,))
    candle_key = f"v2:market:ohlcv_closed:binance:{canonical}:{timeframe}"
    if candle_raw is None:
        raise LiquidationSurfaceProducerError("FINALIZED_CANDLE_SOURCE_MISSING")
    try:
        candles = adapt_binance_finalized_candles(
            RawRedisEvidence.from_value(
                key=candle_key,
                value=candle_raw,
                consumer_observed_at_ms=source_observed_at_ms,
            ),
            symbol=canonical,
            timeframe=timeframe,
        )
    except SourceAdapterError as exc:
        raise LiquidationSurfaceProducerError(
            f"FINALIZED_CANDLE_SOURCE_INVALID:{str(exc)[:MAX_REASON_TEXT]}"
        ) from exc
    marks, mark_errors = _adapt_marks(symbol=canonical, history=mark_history)
    brackets = _bracket_observations(
        bracket_result,
        as_of_time_ms=as_of_time_ms,
        generated_at_ms=generated_at_ms,
    )
    request = SurfaceRequest(
        venue="binance_usdm",
        symbol=canonical,
        timeframe=timeframe,
        as_of_time_ms=as_of_time_ms,
        generated_at_ms=generated_at_ms,
        candles=candles,
        mark_prices=marks,
        open_interest=oi_selection.observations,
        leverage_brackets=brackets,
    )
    payload = build_liquidation_surface(request)
    diagnostics: dict[str, object] = {
        "finalized_candle_count": len(candles),
        "mark_price_count": len(marks),
        "mark_rejection_count": len(mark_errors),
        "open_interest_count": len(oi_selection.observations),
        "open_interest_source_timeframe": oi_selection.source_timeframe,
        "bracket_count": len(brackets),
        "bracket_status": str(bracket_result.get("status") or "MISSING"),
        "bracket_lane_admission_status": (
            "ADMITTED" if brackets else "OMITTED_MISSING_INVALID_OR_OUTSIDE_LANE_CLOCK"
        ),
    }
    return payload, MappingProxyType(diagnostics)


def prepare_lane_publication_candidate(
    *,
    redis_client: Any,
    bracket_security_context: EvidenceSecurityContext,
    symbol: str,
    timeframe: str,
    candle_raw: bytes | None,
    source_observed_at_ms: int,
    mark_history: MarkPriceHistory,
    oi_selection: AdaptiveOISelection,
) -> tuple[dict[str, Any], Mapping[str, object], PreparedLiquidationSurfaceCandidate]:
    """Prepare one lane and embed the exact bytes needed by trainer admission."""

    canonical = _symbol(symbol)
    _timeframes((timeframe,))
    candle_key = f"v2:market:ohlcv_closed:binance:{canonical}:{timeframe}"
    candle_evidence = (
        RawRedisEvidence.from_value(
            key=candle_key,
            value=candle_raw,
            consumer_observed_at_ms=source_observed_at_ms,
        )
        if candle_raw is not None
        else None
    )
    prepared = prepare_liquidation_surface_candidate(
        symbol=canonical,
        timeframe=timeframe,
        as_of_time_ms=None,
        generated_at_ms=None,
        candle_evidence=candle_evidence,
        mark_price_evidence=mark_history.latest(canonical),
        open_interest_evidence=oi_selection.evidence,
        bracket_redis_client=redis_client,
        bracket_security_context=bracket_security_context,
        bracket_now_fn=lambda: redis_utc_now(redis_client),
        post_bracket_clock_ms_fn=lambda: redis_now_ms(redis_client),
    )
    payload = publication_mapping_with_prepared_source_bundle(prepared)
    leaves = {leaf.family: leaf for leaf in prepared.source_manifest}
    diagnostics: dict[str, object] = {
        "finalized_candle_count": leaves["finalized_candles"].row_count,
        "mark_price_count": leaves["mark_price"].row_count,
        "mark_rejection_count": int(leaves["mark_price"].degraded),
        "open_interest_count": leaves["open_interest"].row_count,
        "open_interest_source_timeframe": oi_selection.source_timeframe,
        "bracket_count": leaves["leverage_brackets"].row_count,
        "bracket_status": leaves["leverage_brackets"].status,
        "bracket_lane_admission_status": (
            "ADMITTED"
            if leaves["leverage_brackets"].authenticated
            else "OMITTED_MISSING_INVALID_OR_OUTSIDE_LANE_CLOCK"
        ),
        "prepared_source_bundle_sha256": payload["trainer_source_bundle"][
            "bundle_sha256"
        ],
    }
    return payload, MappingProxyType(diagnostics), prepared


def _source_keys(symbol: str, timeframes: Sequence[str]) -> tuple[str, ...]:
    canonical = _symbol(symbol)
    keys = [
        f"v2:market:ohlcv_closed:binance:{canonical}:{timeframe}"
        for timeframe in timeframes
    ]
    keys.extend(
        f"latest:coinank:open_interest:{canonical}:{timeframe}"
        for timeframe in COINANK_OI_TIMEFRAMES
    )
    return tuple(keys)


def _record_error(
    samples: list[dict[str, str]],
    *,
    symbol: str,
    timeframe: str,
    stage: str,
    reason: object,
) -> None:
    if len(samples) >= MAX_ERROR_SAMPLES:
        return
    samples.append(
        {
            "symbol": symbol,
            "timeframe": timeframe,
            "stage": stage,
            "reason": str(reason)[:MAX_REASON_TEXT],
        }
    )


def _status_bytes(payload: Mapping[str, Any]) -> bytes:
    try:
        return json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
    except (TypeError, ValueError, OverflowError, UnicodeEncodeError) as exc:
        raise LiquidationSurfaceProducerError("PRODUCER_STATUS_NOT_CANONICAL_JSON") from exc


def producer_status_key(publication_scope_sha256: str) -> str:
    if not isinstance(publication_scope_sha256, str) or not re.fullmatch(
        r"[0-9a-f]{64}", publication_scope_sha256
    ):
        raise LiquidationSurfaceProducerError("PUBLICATION_SCOPE_SHA256_INVALID")
    return f"v2:liquidation_surface:producer_status:{publication_scope_sha256}"


def run_producer_cycle(
    redis_client: Any,
    *,
    symbols: Sequence[str],
    timeframes: Sequence[str],
    bracket_security_context: EvidenceSecurityContext,
    publication_security_context: SurfacePublicationSecurityContext,
    mark_history: MarkPriceHistory,
    archive_ttl_seconds: int = DEFAULT_ARCHIVE_TTL_SECONDS,
    receipt_ttl_seconds: int = DEFAULT_RECEIPT_TTL_SECONDS,
    status_ttl_seconds: int = DEFAULT_STATUS_TTL_SECONDS,
) -> dict[str, Any]:
    """Build, publish, and immediately reopen one full dynamic-universe cycle."""

    ordered_symbols = tuple(dict.fromkeys(_symbol(symbol) for symbol in symbols))
    if not ordered_symbols:
        raise LiquidationSurfaceProducerError("PRODUCER_SYMBOLS_EMPTY")
    ordered_timeframes = _timeframes(timeframes)
    require_publication_scope_binding(
        bracket_security_context=bracket_security_context,
        publication_security_context=publication_security_context,
    )
    cycle_started_at_ms = redis_now_ms(redis_client)
    lane_count = len(ordered_symbols) * len(ordered_timeframes)
    semantic_reasons: Counter[str] = Counter()
    oi_timeframes: Counter[str] = Counter()
    build_errors: Counter[str] = Counter()
    publication_errors: Counter[str] = Counter()
    timeframe_published: Counter[str] = Counter()
    timeframe_semantic: Counter[str] = Counter()
    error_samples: list[dict[str, str]] = []
    published = 0
    candidates_built = 0
    semantic_candidates = 0
    observation_pointer_count = 0
    trainer_candidate_pointer_count = 0
    verified_prepared_source_bundle_count = 0
    authenticated_bracket_symbols = 0
    oi_selected_symbols = 0

    mark_keys = tuple(f"v2:market:mark_price:{symbol}" for symbol in ordered_symbols)
    mark_history.record_snapshot(
        symbols=ordered_symbols,
        snapshot=read_exact_redis_snapshot(redis_client, keys=mark_keys),
    )

    for symbol in ordered_symbols:
        # Sampling the all-symbol WSS cache throughout the cycle preserves two
        # adjacent exact market events without one blocking sleep per symbol.
        mark_history.record_snapshot(
            symbols=ordered_symbols,
            snapshot=read_exact_redis_snapshot(redis_client, keys=mark_keys),
        )
        source_snapshot = read_exact_redis_snapshot(
            redis_client,
            keys=_source_keys(symbol, ordered_timeframes),
        )
        oi_selection = select_adaptive_coinank_open_interest(
            symbol=symbol,
            snapshot=source_snapshot,
        )
        if oi_selection.source_timeframe is not None:
            oi_selected_symbols += 1
            oi_timeframes[oi_selection.source_timeframe] += 1
        symbol_has_authenticated_brackets = False

        for timeframe in ordered_timeframes:
            current_mark = read_exact_redis_snapshot(
                redis_client,
                keys=(f"v2:market:mark_price:{symbol}",),
            )
            mark_history.record(
                symbol=symbol,
                value=current_mark.values.get(f"v2:market:mark_price:{symbol}"),
                observed_at_ms=current_mark.consumer_observed_at_ms,
            )
            candle_key = f"v2:market:ohlcv_closed:binance:{symbol}:{timeframe}"
            try:
                candidate, diagnostics, _prepared = prepare_lane_publication_candidate(
                    redis_client=redis_client,
                    bracket_security_context=bracket_security_context,
                    symbol=symbol,
                    timeframe=timeframe,
                    candle_raw=source_snapshot.values.get(candle_key),
                    source_observed_at_ms=source_snapshot.consumer_observed_at_ms,
                    mark_history=mark_history,
                    oi_selection=oi_selection,
                )
                if diagnostics["bracket_lane_admission_status"] == "ADMITTED":
                    symbol_has_authenticated_brackets = True
                candidates_built += 1
            except Exception as exc:
                reason = f"{type(exc).__name__}:{str(exc)[:MAX_REASON_TEXT]}"
                build_errors[reason] += 1
                _record_error(
                    error_samples,
                    symbol=symbol,
                    timeframe=timeframe,
                    stage="BUILD",
                    reason=reason,
                )
                continue
            semantic_reason = str(candidate.get("trainer_authority_reason") or "MISSING")
            semantic_reasons[semantic_reason] += 1
            if candidate.get("trainer_semantic_eligible") is True:
                semantic_candidates += 1
                timeframe_semantic[timeframe] += 1
            try:
                verified = publish_liquidation_surface(
                    redis_client,
                    candidate,
                    security_context=publication_security_context,
                    archive_ttl_seconds=archive_ttl_seconds,
                    receipt_ttl_seconds=receipt_ttl_seconds,
                )
            except Exception as exc:
                reason = f"{type(exc).__name__}:{str(exc)[:MAX_REASON_TEXT]}"
                publication_errors[reason] += 1
                _record_error(
                    error_samples,
                    symbol=symbol,
                    timeframe=timeframe,
                    stage="PUBLICATION",
                    reason=reason,
                )
                continue
            if verified.trainer_authority is not False:
                raise LiquidationSurfaceProducerError(
                    "PUBLICATION_UNEXPECTED_TRAINER_AUTHORITY"
                )
            receipt = getattr(verified, "receipt", {})
            if isinstance(receipt, Mapping) and receipt.get(
                "trainer_source_bundle_sha256"
            ) == candidate["trainer_source_bundle"]["bundle_sha256"]:
                verified_prepared_source_bundle_count += 1
            if verified.pointer_class == "trainer_eligible" and (
                not isinstance(receipt, Mapping)
                or receipt.get("trainer_storage_candidate_eligible") is not True
            ):
                raise LiquidationSurfaceProducerError(
                    "TRAINER_POINTER_WITHOUT_VERIFIED_PREPARED_SOURCE_BUNDLE"
                )
            published += 1
            timeframe_published[timeframe] += 1
            if verified.pointer_class == "trainer_eligible":
                trainer_candidate_pointer_count += 1
            else:
                observation_pointer_count += 1
        if symbol_has_authenticated_brackets:
            authenticated_bracket_symbols += 1

    cycle_completed_at_ms = redis_now_ms(redis_client)
    if published == lane_count:
        status = "COMPLETE"
    elif published:
        status = "PARTIAL"
    else:
        status = "BLOCKED"
    result: dict[str, Any] = {
        "schema_version": PRODUCER_SCHEMA_VERSION,
        "status": status,
        "venue": "binance_usdm",
        "publication_scope_sha256": publication_security_context.publication_scope_sha256,
        "cycle_started_at": cycle_started_at_ms,
        "cycle_completed_at": cycle_completed_at_ms,
        "cycle_duration_ms": cycle_completed_at_ms - cycle_started_at_ms,
        "symbol_count": len(ordered_symbols),
        "timeframe_count": len(ordered_timeframes),
        "lane_count": lane_count,
        "candidate_built_count": candidates_built,
        "published_lane_count": published,
        "all_lanes_published": published == lane_count,
        "trainer_semantic_candidate_count": semantic_candidates,
        "trainer_candidate_pointer_count": trainer_candidate_pointer_count,
        "verified_prepared_source_bundle_count": (
            verified_prepared_source_bundle_count
        ),
        "observation_pointer_count": observation_pointer_count,
        "trainer_authority_count": 0,
        "two_mark_sample_symbol_count": mark_history.two_sample_symbol_count(
            ordered_symbols
        ),
        "authenticated_bracket_symbol_count": authenticated_bracket_symbols,
        "adaptive_oi_selected_symbol_count": oi_selected_symbols,
        "adaptive_oi_selected_timeframes": dict(sorted(oi_timeframes.items())),
        "timeframe_published_counts": {
            timeframe: timeframe_published[timeframe]
            for timeframe in ordered_timeframes
        },
        "timeframe_semantic_candidate_counts": {
            timeframe: timeframe_semantic[timeframe]
            for timeframe in ordered_timeframes
        },
        "trainer_semantic_reason_counts": dict(sorted(semantic_reasons.items())),
        "build_error_counts": dict(sorted(build_errors.items())),
        "publication_error_counts": dict(sorted(publication_errors.items())),
        "error_samples": error_samples,
        "adaptive_market_freshness": True,
        "static_market_threshold_used": False,
        "coinank_plan": "Plan3",
        "coinank_open_interest_endpoint": "openInterest_kline",
        "coinank_liquidation_heatmap_or_map_used": False,
        "forced_liquidation_stream_used_as_level_source": False,
        "publication_is_storage_integrity_only": True,
        "trainer_admission_required_separately": True,
        "prediction_authority": False,
        "paper_trading_authority": False,
        "live_trading_authority": False,
        "places_real_order": False,
        "order_submitted": False,
        "leverage_mutated": False,
        "margin_mutated": False,
    }
    key = producer_status_key(publication_security_context.publication_scope_sha256)
    try:
        acknowledged = redis_client.set(
            key,
            _status_bytes(result),
            ex=status_ttl_seconds,
        )
    except Exception as exc:
        raise LiquidationSurfaceProducerError("PRODUCER_STATUS_WRITE_FAILED") from exc
    if acknowledged not in (True, b"OK", "OK"):
        raise LiquidationSurfaceProducerError("PRODUCER_STATUS_WRITE_NOT_ACKNOWLEDGED")
    return result


__all__ = [
    "AdaptiveOISelection",
    "COINANK_OI_TIMEFRAMES",
    "DEFAULT_ARCHIVE_TTL_SECONDS",
    "DEFAULT_RECEIPT_TTL_SECONDS",
    "DEFAULT_STATUS_TTL_SECONDS",
    "ExactRedisSnapshot",
    "LiquidationSurfaceProducerError",
    "MarkPriceHistory",
    "PRODUCER_SCHEMA_VERSION",
    "SURFACE_TIMEFRAMES",
    "build_lane_candidate",
    "prepare_lane_publication_candidate",
    "producer_status_key",
    "publication_scope_metadata",
    "read_exact_redis_snapshot",
    "redis_now_ms",
    "redis_utc_now",
    "require_publication_scope_binding",
    "run_producer_cycle",
    "select_adaptive_coinank_open_interest",
]
