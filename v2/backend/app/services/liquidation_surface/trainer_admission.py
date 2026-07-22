"""Point-in-time trainer admission for prospective liquidation surfaces.

The publication boundary proves immutable Redis storage but deliberately grants
no trainer authority.  This module adds a later, decision-scoped boundary.  It
adapts exact source bytes itself, consumes the authenticated Binance bracket
reader itself, binds the resulting manifest to one verified publication, and
returns either one exact trainer feature or an explicit masked absence.

Nothing in this module grants prediction, paper-trading, or live-execution
authority.  A result is valid for one symbol/timeframe/feature-ABI/decision
identity and timestamp only.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
import time
import zlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any, NoReturn, cast

from v2.backend.app.services.binance_usdm_leverage_bracket_evidence import (
    EvidenceSecurityContext,
    read_authenticated_bracket_surface_evidence,
)

from .contracts import (
    CandleObservation,
    LeverageBracket,
    MarkPriceObservation,
    OpenInterestObservation,
    SurfaceRequest,
)
from .model import MODEL_VERSION, SCHEMA_VERSION, build_liquidation_surface
from .publication import VerifiedLiquidationSurface, derive_publication_scope_sha256
from .source_adapters import (
    BINANCE_USDM_VENUE,
    RawRedisEvidence,
    SourceAdapterError,
    adapt_binance_finalized_candles,
    adapt_binance_mark_price,
    adapt_coinank_plan3_open_interest,
)

ADMISSION_SCHEMA_VERSION = "v2_liquidation_surface_trainer_admission_v1"
SOURCE_MANIFEST_SCHEMA_VERSION = "v2_liquidation_surface_source_manifest_v1"
PREPARED_SOURCE_BUNDLE_SCHEMA_VERSION = (
    "v2_liquidation_surface_prepared_source_bundle_v1"
)
SOURCE_FAMILY_ORDER = (
    "finalized_candles",
    "mark_price",
    "open_interest",
    "leverage_brackets",
    "outcome_calibration",
)
SOURCE_REQUIRED_MASK = (True, True, True, True, False)
MIN_ADMISSION_HMAC_KEY_BYTES = 32
MAX_CANONICAL_BYTES = 16 * 1024 * 1024
_MAX_SIGNED_64_BIT = (1 << 63) - 1
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,191}$", re.ASCII)
_SYMBOL_RE = re.compile(r"^[A-Z0-9]{5,30}$", re.ASCII)
_TIMEFRAME_RE = re.compile(r"^[1-9][0-9]{0,14}[smhdw]$", re.ASCII)
_PREPARED_TOKEN = object()
_LEAF_TOKEN = object()
_DECISION_TOKEN = object()
_SECURITY_TOKEN = object()
_RESULT_TOKEN = object()
_PROOF_TOKEN = object()
_GUARD_TOKEN = object()
_MAPPING_PROXY_TYPE = type(MappingProxyType({}))
_PUBLICATION_SCOPE_KEYS = (
    "credential_binding_id",
    "exchange_environment",
    "base_url_origin",
    "evidence_auth_key_id",
    "credential_account_specific",
)


class TrainerAdmissionError(RuntimeError):
    """Base admission failure."""


class TrainerAdmissionValidationError(TrainerAdmissionError):
    """Input violates the local admission contract."""


class TrainerAdmissionIntegrityError(TrainerAdmissionError):
    """Prepared, published, or re-derived evidence does not bind exactly."""


def _validation_error(reason: str) -> NoReturn:
    raise TrainerAdmissionValidationError(reason) from None


def _integrity_error(reason: str) -> NoReturn:
    raise TrainerAdmissionIntegrityError(reason) from None


def _positive_ms(value: object, *, name: str) -> int:
    if type(value) is not int or not 0 < cast(int, value) <= _MAX_SIGNED_64_BIT:
        _validation_error(f"{name}_NOT_POSITIVE_SIGNED_64_BIT_MS")
    return cast(int, value)


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _valid_sha256(value: object) -> bool:
    return type(value) is str and _SHA256_RE.fullmatch(cast(str, value)) is not None


def _require_sha256(value: object, *, name: str) -> str:
    if not _valid_sha256(value):
        _validation_error(f"{name}_INVALID")
    return cast(str, value)


def _plain_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            cast(str, key): _plain_json(nested)
            for key, nested in value.items()
        }
    if isinstance(value, tuple | list):
        return [_plain_json(nested) for nested in value]
    return value


def _canonical_json_bytes(value: object) -> bytes:
    try:
        raw = json.dumps(
            _plain_json(value),
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
    except (OverflowError, RecursionError, TypeError, UnicodeEncodeError, ValueError):
        _validation_error("TRAINER_ADMISSION_CANONICAL_JSON_INVALID")
    if not raw or len(raw) > MAX_CANONICAL_BYTES:
        _validation_error("TRAINER_ADMISSION_CANONICAL_JSON_SIZE_INVALID")
    return raw


def _stable_sha256(value: object) -> str:
    return _sha256(_canonical_json_bytes(value))


def _freeze_json(value: object) -> object:
    if type(value) is dict:
        return MappingProxyType(
            {
                cast(str, key): _freeze_json(nested)
                for key, nested in cast(dict[object, object], value).items()
            }
        )
    if type(value) is list:
        return tuple(_freeze_json(nested) for nested in cast(list[object], value))
    if type(value) is tuple:
        return tuple(_freeze_json(nested) for nested in cast(tuple[object, ...], value))
    return value


def _deeply_immutable_json(value: object) -> bool:
    stack = [value]
    nodes = 0
    while stack:
        current = stack.pop()
        nodes += 1
        if nodes > 500_000:
            return False
        if type(current) is _MAPPING_PROXY_TYPE:
            mapping = cast(Mapping[object, object], current)
            if any(type(key) is not str for key in mapping):
                return False
            stack.extend(mapping.values())
        elif type(current) is tuple:
            stack.extend(cast(tuple[object, ...], current))
        elif current is None or type(current) in (str, bool, int, float):
            continue
        else:
            return False
    return True


@dataclass(frozen=True, slots=True)
class _IntegrityGuard:
    expected_sha256: str
    _construction_token: object = field(repr=False, compare=False)

    def verify(self, material: object) -> bool:
        return bool(
            self._construction_token is _GUARD_TOKEN
            and _valid_sha256(self.expected_sha256)
            and hmac.compare_digest(self.expected_sha256, _stable_sha256(material))
        )


def _guard(material: object) -> _IntegrityGuard:
    return _IntegrityGuard(
        expected_sha256=_stable_sha256(material),
        _construction_token=_GUARD_TOKEN,
    )


def _raw_material(value: RawRedisEvidence | None) -> object:
    if value is None:
        return None
    return {
        "key": value.key,
        "raw_byte_count": len(value.raw),
        "raw_sha256": value.raw_sha256,
        "consumer_observed_at_ms": value.consumer_observed_at_ms,
    }


def _raw_source_bundle_material(value: RawRedisEvidence | None) -> object:
    """Serialize the exact Redis bytes, not merely their descriptive hash."""

    if value is None:
        return None
    compressed = zlib.compress(value.raw, level=9)
    return {
        "key": value.key,
        "encoding": "zlib_base64_v1",
        "compressed_base64": base64.b64encode(compressed).decode("ascii"),
        "compressed_byte_count": len(compressed),
        "raw_byte_count": len(value.raw),
        "raw_sha256": value.raw_sha256,
        "consumer_observed_at_ms": value.consumer_observed_at_ms,
    }


def _raw_from_source_bundle(
    value: object,
    *,
    name: str,
    optional: bool,
) -> RawRedisEvidence | None:
    if value is None:
        if optional:
            return None
        _validation_error(f"{name}_SOURCE_BUNDLE_EVIDENCE_MISSING")
    if type(value) is not dict or set(cast(dict[object, object], value)) != {
        "key",
        "encoding",
        "compressed_base64",
        "compressed_byte_count",
        "raw_byte_count",
        "raw_sha256",
        "consumer_observed_at_ms",
    }:
        _validation_error(f"{name}_SOURCE_BUNDLE_EVIDENCE_FIELDS_INVALID")
    row = cast(dict[str, Any], value)
    encoded = row.get("compressed_base64")
    if row.get("encoding") != "zlib_base64_v1" or type(encoded) is not str:
        _validation_error(f"{name}_SOURCE_BUNDLE_EVIDENCE_ENCODING_INVALID")
    try:
        compressed = base64.b64decode(cast(str, encoded), validate=True)
    except (ValueError, binascii.Error):
        _validation_error(f"{name}_SOURCE_BUNDLE_EVIDENCE_ENCODING_INVALID")
    if (
        not compressed
        or len(compressed) > MAX_CANONICAL_BYTES
        or row.get("compressed_byte_count") != len(compressed)
    ):
        _validation_error(f"{name}_SOURCE_BUNDLE_EVIDENCE_ENCODING_INVALID")
    try:
        decoder = zlib.decompressobj()
        raw = decoder.decompress(compressed, MAX_CANONICAL_BYTES + 1)
    except zlib.error:
        _validation_error(f"{name}_SOURCE_BUNDLE_EVIDENCE_ENCODING_INVALID")
    if (
        not decoder.eof
        or decoder.unused_data
        or decoder.unconsumed_tail
        or len(raw) > MAX_CANONICAL_BYTES
    ):
        _validation_error(f"{name}_SOURCE_BUNDLE_EVIDENCE_ENCODING_INVALID")
    if (
        not raw
        or row.get("raw_byte_count") != len(raw)
        or row.get("raw_sha256") != _sha256(raw)
    ):
        _validation_error(f"{name}_SOURCE_BUNDLE_EVIDENCE_HASH_INVALID")
    try:
        evidence = RawRedisEvidence.from_value(
            key=row.get("key"),
            value=raw,
            consumer_observed_at_ms=row.get("consumer_observed_at_ms"),
        )
    except SourceAdapterError as exc:
        raise TrainerAdmissionValidationError(
            f"{name}_SOURCE_BUNDLE_EVIDENCE_INVALID:{exc}"
        ) from exc
    if evidence.raw_sha256 != row.get("raw_sha256"):
        _integrity_error(f"{name}_SOURCE_BUNDLE_EVIDENCE_REOPEN_MISMATCH")
    return evidence


def _observation_material(rows: Sequence[object]) -> list[dict[str, Any]]:
    return [asdict(row) for row in rows]


@dataclass(frozen=True, slots=True)
class _AuthenticatedBracketReaderProof:
    status: str
    evidence_authenticated: bool
    observations: tuple[LeverageBracket, ...]
    safe_metadata: Mapping[str, Any]
    publication_scope_sha256: str
    evidence_key: str | None
    content_checksum_sha256: str | None
    reader_result_sha256: str
    proof_sha256: str
    _construction_token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if (
            self._construction_token is not _PROOF_TOKEN
            or not _deeply_immutable_json(self.safe_metadata)
            or self.proof_sha256
            != _stable_sha256(_bracket_proof_material(self, include_hash=False))
        ):
            _validation_error("AUTHENTICATED_BRACKET_READER_PROOF_INVALID")


def _bracket_proof_material(
    proof: _AuthenticatedBracketReaderProof,
    *,
    include_hash: bool,
) -> dict[str, Any]:
    material: dict[str, Any] = {
        "status": proof.status,
        "evidence_authenticated": proof.evidence_authenticated,
        "observations": _observation_material(proof.observations),
        "safe_metadata": dict(proof.safe_metadata),
        "publication_scope_sha256": proof.publication_scope_sha256,
        "evidence_key": proof.evidence_key,
        "content_checksum_sha256": proof.content_checksum_sha256,
        "reader_result_sha256": proof.reader_result_sha256,
    }
    if include_hash:
        material["proof_sha256"] = proof.proof_sha256
    return material


def _reader_result_material(result: Mapping[str, Any]) -> dict[str, Any]:
    material = dict(result)
    observations = material.pop("observations", ())
    if not isinstance(observations, tuple) or any(
        type(row) is not LeverageBracket for row in observations
    ):
        _validation_error("BRACKET_READER_OBSERVATIONS_INVALID")
    material["observations"] = _observation_material(observations)
    _canonical_json_bytes(material)
    return material


def _build_bracket_proof(
    result: Mapping[str, Any],
    *,
    security_context: EvidenceSecurityContext,
) -> _AuthenticatedBracketReaderProof:
    if type(result) is not dict:
        _validation_error("AUTHENTICATED_BRACKET_READER_RESULT_REQUIRED")
    safe_metadata = security_context.safe_metadata()
    for key, expected in safe_metadata.items():
        if result.get(key) != expected:
            _validation_error("BRACKET_READER_SECURITY_CONTEXT_BINDING_MISMATCH")
    if (
        result.get("read_only") is not True
        or result.get("paper_only") is not True
        or result.get("places_real_order") is not False
        or result.get("order_submitted") is not False
        or result.get("leverage_mutated") is not False
        or result.get("margin_mutated") is not False
    ):
        _validation_error("BRACKET_READER_SAFETY_CONTRACT_INVALID")
    status = result.get("status")
    authenticated = result.get("evidence_authenticated")
    observations = result.get("observations")
    if type(status) is not str or type(authenticated) is not bool:
        _validation_error("BRACKET_READER_STATUS_INVALID")
    if not isinstance(observations, tuple) or any(
        type(row) is not LeverageBracket for row in observations
    ):
        _validation_error("BRACKET_READER_OBSERVATIONS_INVALID")
    if status == "READY":
        if authenticated is not True or not observations:
            _validation_error("BRACKET_READER_READY_WITHOUT_AUTHENTICATED_EVIDENCE")
    elif authenticated is not False or observations:
        _validation_error("BRACKET_READER_BLOCKED_WITH_USABLE_EVIDENCE")
    scope_metadata = {key: result[key] for key in _PUBLICATION_SCOPE_KEYS}
    scope = derive_publication_scope_sha256(scope_metadata)
    reader_sha = _stable_sha256(_reader_result_material(result))
    values = {
        "status": status,
        "evidence_authenticated": authenticated,
        "observations": tuple(replace(row) for row in observations),
        "safe_metadata": cast(Mapping[str, Any], _freeze_json(scope_metadata)),
        "publication_scope_sha256": scope,
        "evidence_key": (
            cast(str, result["evidence_key"])
            if type(result.get("evidence_key")) is str
            else None
        ),
        "content_checksum_sha256": (
            cast(str, result["content_checksum_sha256"])
            if _valid_sha256(result.get("content_checksum_sha256"))
            else None
        ),
        "reader_result_sha256": reader_sha,
    }
    provisional = _AuthenticatedBracketReaderProof(
        **values,
        proof_sha256=_stable_sha256(
            {
                **values,
                "safe_metadata": scope_metadata,
                "observations": _observation_material(values["observations"]),
            }
        ),
        _construction_token=_PROOF_TOKEN,
    )
    return provisional


@dataclass(frozen=True, slots=True)
class _PreparationSnapshot:
    symbol: str
    timeframe: str
    as_of_time_ms: int
    generated_at_ms: int
    candle_evidence: RawRedisEvidence | None
    mark_price_evidence: tuple[RawRedisEvidence, ...]
    open_interest_evidence: RawRedisEvidence | None
    bracket_proof: _AuthenticatedBracketReaderProof
    tick_size: float | None
    max_cohorts: int
    max_leverage_scenarios: int
    max_levels_per_side: int
    max_source_rows_per_family: int
    max_expanded_candidates: int


def _snapshot_material(snapshot: _PreparationSnapshot) -> dict[str, Any]:
    return {
        "venue": BINANCE_USDM_VENUE,
        "symbol": snapshot.symbol,
        "timeframe": snapshot.timeframe,
        "as_of_time_ms": snapshot.as_of_time_ms,
        "generated_at_ms": snapshot.generated_at_ms,
        "candle_evidence": _raw_material(snapshot.candle_evidence),
        "mark_price_evidence": [
            _raw_material(row) for row in snapshot.mark_price_evidence
        ],
        "open_interest_evidence": _raw_material(snapshot.open_interest_evidence),
        "bracket_proof": _bracket_proof_material(
            snapshot.bracket_proof,
            include_hash=True,
        ),
        "tick_size": snapshot.tick_size,
        "max_cohorts": snapshot.max_cohorts,
        "max_leverage_scenarios": snapshot.max_leverage_scenarios,
        "max_levels_per_side": snapshot.max_levels_per_side,
        "max_source_rows_per_family": snapshot.max_source_rows_per_family,
        "max_expanded_candidates": snapshot.max_expanded_candidates,
    }


@dataclass(frozen=True, slots=True)
class FrozenSurfaceRequest:
    venue: str
    symbol: str
    timeframe: str
    as_of_time_ms: int
    generated_at_ms: int
    candles: tuple[CandleObservation, ...]
    mark_prices: tuple[MarkPriceObservation, ...]
    open_interest: tuple[OpenInterestObservation, ...]
    leverage_brackets: tuple[LeverageBracket, ...]
    tick_size: float | None
    max_cohorts: int
    max_leverage_scenarios: int
    max_levels_per_side: int
    max_source_rows_per_family: int
    max_expanded_candidates: int

    def to_contract(self) -> SurfaceRequest:
        return SurfaceRequest(
            venue=self.venue,
            symbol=self.symbol,
            timeframe=self.timeframe,
            as_of_time_ms=self.as_of_time_ms,
            generated_at_ms=self.generated_at_ms,
            candles=tuple(replace(row) for row in self.candles),
            mark_prices=tuple(replace(row) for row in self.mark_prices),
            open_interest=tuple(replace(row) for row in self.open_interest),
            leverage_brackets=tuple(replace(row) for row in self.leverage_brackets),
            tick_size=self.tick_size,
            max_cohorts=self.max_cohorts,
            max_leverage_scenarios=self.max_leverage_scenarios,
            max_levels_per_side=self.max_levels_per_side,
            max_source_rows_per_family=self.max_source_rows_per_family,
            max_expanded_candidates=self.max_expanded_candidates,
        )


def _request_material(request: FrozenSurfaceRequest) -> dict[str, Any]:
    return {
        "venue": request.venue,
        "symbol": request.symbol,
        "timeframe": request.timeframe,
        "as_of_time_ms": request.as_of_time_ms,
        "generated_at_ms": request.generated_at_ms,
        "candles": _observation_material(request.candles),
        "mark_prices": _observation_material(request.mark_prices),
        "open_interest": _observation_material(request.open_interest),
        "leverage_brackets": _observation_material(request.leverage_brackets),
        "outcome_calibration": None,
        "tick_size": request.tick_size,
        "max_cohorts": request.max_cohorts,
        "max_leverage_scenarios": request.max_leverage_scenarios,
        "max_levels_per_side": request.max_levels_per_side,
        "max_source_rows_per_family": request.max_source_rows_per_family,
        "max_expanded_candidates": request.max_expanded_candidates,
    }


@dataclass(frozen=True, slots=True)
class _FamilyState:
    family: str
    observations: tuple[object, ...]
    authenticated: bool
    evidence_supplied: bool
    degradation_reason: str | None
    source_bindings: tuple[tuple[str, str], ...]


def _raw_bindings(values: Sequence[RawRedisEvidence]) -> tuple[tuple[str, str], ...]:
    return tuple(sorted({(row.key, row.raw_sha256) for row in values}))


def _coinank_oi_source_timeframe(
    evidence: RawRedisEvidence,
    *,
    symbol: str,
) -> str:
    prefix = f"latest:coinank:open_interest:{symbol}:"
    if not evidence.key.startswith(prefix):
        raise SourceAdapterError("COINANK_OI_REDIS_KEY_IDENTITY_MISMATCH")
    timeframe = evidence.key.removeprefix(prefix)
    if _TIMEFRAME_RE.fullmatch(timeframe) is None:
        raise SourceAdapterError("COINANK_OI_REDIS_KEY_TIMEFRAME_INVALID")
    return timeframe


def _adapt_snapshot(
    snapshot: _PreparationSnapshot,
) -> tuple[FrozenSurfaceRequest, list[_FamilyState]]:
    states: list[_FamilyState] = []
    candles: tuple[CandleObservation, ...] = ()
    candle_reason: str | None = None
    if snapshot.candle_evidence is None:
        candle_reason = "SOURCE_EVIDENCE_MISSING"
    else:
        try:
            candles = adapt_binance_finalized_candles(
                snapshot.candle_evidence,
                symbol=snapshot.symbol,
                timeframe=snapshot.timeframe,
                max_rows=snapshot.max_source_rows_per_family,
            )
        except SourceAdapterError as exc:
            candle_reason = f"SOURCE_ADAPTER_REJECTED:{exc}"
    states.append(
        _FamilyState(
            family="finalized_candles",
            observations=cast(tuple[object, ...], candles),
            authenticated=bool(candles) and candle_reason is None,
            evidence_supplied=snapshot.candle_evidence is not None,
            degradation_reason=candle_reason,
            source_bindings=_raw_bindings(
                (snapshot.candle_evidence,) if snapshot.candle_evidence is not None else ()
            ),
        )
    )

    marks: tuple[MarkPriceObservation, ...] = ()
    mark_reason: str | None = None
    if not snapshot.mark_price_evidence:
        mark_reason = "SOURCE_EVIDENCE_MISSING"
    else:
        try:
            marks = tuple(
                adapt_binance_mark_price(row, symbol=snapshot.symbol)
                for row in snapshot.mark_price_evidence
            )
        except SourceAdapterError as exc:
            marks = ()
            mark_reason = f"SOURCE_ADAPTER_REJECTED:{exc}"
    states.append(
        _FamilyState(
            family="mark_price",
            observations=cast(tuple[object, ...], marks),
            authenticated=bool(marks) and mark_reason is None,
            evidence_supplied=bool(snapshot.mark_price_evidence),
            degradation_reason=mark_reason,
            source_bindings=_raw_bindings(snapshot.mark_price_evidence),
        )
    )

    oi_rows: tuple[OpenInterestObservation, ...] = ()
    oi_reason: str | None = None
    if snapshot.open_interest_evidence is None:
        oi_reason = "SOURCE_EVIDENCE_MISSING"
    else:
        try:
            oi_source_timeframe = _coinank_oi_source_timeframe(
                snapshot.open_interest_evidence,
                symbol=snapshot.symbol,
            )
            oi_rows = adapt_coinank_plan3_open_interest(
                snapshot.open_interest_evidence,
                symbol=snapshot.symbol,
                source_timeframe=oi_source_timeframe,
                max_rows=snapshot.max_source_rows_per_family,
            )
        except SourceAdapterError as exc:
            oi_reason = f"SOURCE_ADAPTER_REJECTED:{exc}"
    states.append(
        _FamilyState(
            family="open_interest",
            observations=cast(tuple[object, ...], oi_rows),
            authenticated=bool(oi_rows) and oi_reason is None,
            evidence_supplied=snapshot.open_interest_evidence is not None,
            degradation_reason=oi_reason,
            source_bindings=_raw_bindings(
                (snapshot.open_interest_evidence,)
                if snapshot.open_interest_evidence is not None
                else ()
            ),
        )
    )

    proof = snapshot.bracket_proof
    bracket_ready = proof.status == "READY" and proof.evidence_authenticated is True
    bracket_reason = None if bracket_ready else f"BRACKET_READER_{proof.status}"
    bracket_bindings = (
        ((proof.evidence_key, proof.content_checksum_sha256),)
        if proof.evidence_key is not None and proof.content_checksum_sha256 is not None
        else ()
    )
    states.append(
        _FamilyState(
            family="leverage_brackets",
            observations=cast(tuple[object, ...], proof.observations),
            authenticated=bracket_ready,
            evidence_supplied=proof.status != "LEVERAGE_BRACKET_EVIDENCE_MISSING",
            degradation_reason=bracket_reason,
            source_bindings=bracket_bindings,
        )
    )
    states.append(
        _FamilyState(
            family="outcome_calibration",
            observations=(),
            authenticated=False,
            evidence_supplied=False,
            degradation_reason=None,
            source_bindings=(),
        )
    )
    return (
        FrozenSurfaceRequest(
            venue=BINANCE_USDM_VENUE,
            symbol=snapshot.symbol,
            timeframe=snapshot.timeframe,
            as_of_time_ms=snapshot.as_of_time_ms,
            generated_at_ms=snapshot.generated_at_ms,
            candles=tuple(replace(row) for row in candles),
            mark_prices=tuple(replace(row) for row in marks),
            open_interest=tuple(replace(row) for row in oi_rows),
            leverage_brackets=tuple(replace(row) for row in proof.observations),
            tick_size=snapshot.tick_size,
            max_cohorts=snapshot.max_cohorts,
            max_leverage_scenarios=snapshot.max_leverage_scenarios,
            max_levels_per_side=snapshot.max_levels_per_side,
            max_source_rows_per_family=snapshot.max_source_rows_per_family,
            max_expanded_candidates=snapshot.max_expanded_candidates,
        ),
        states,
    )


@dataclass(frozen=True, slots=True)
class SourceManifestLeaf:
    ordinal: int
    family: str
    required: bool
    present: bool
    authenticated: bool
    missing: bool
    degraded: bool
    status: str
    degradation_reason: str | None
    row_count: int
    source_bindings: tuple[tuple[str, str], ...]
    feature_cutoff_ms: int | None
    event_time_ms: int | None
    ingested_at_ms: int | None
    available_at_ms: int | None
    expires_at_ms: int | None
    finality_confirmed: bool
    authentication_class: str
    leaf_sha256: str
    _construction_token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if (
            self._construction_token is not _LEAF_TOKEN
            or self.leaf_sha256
            != _stable_sha256(_leaf_material(self, include_hash=False))
        ):
            _validation_error("SOURCE_MANIFEST_LEAF_FACTORY_OR_HASH_INVALID")


def _leaf_material(leaf: SourceManifestLeaf, *, include_hash: bool) -> dict[str, Any]:
    material: dict[str, Any] = {
        "ordinal": leaf.ordinal,
        "family": leaf.family,
        "required": leaf.required,
        "present": leaf.present,
        "authenticated": leaf.authenticated,
        "missing": leaf.missing,
        "degraded": leaf.degraded,
        "status": leaf.status,
        "degradation_reason": leaf.degradation_reason,
        "row_count": leaf.row_count,
        "source_bindings": [list(binding) for binding in leaf.source_bindings],
        "feature_cutoff_ms": leaf.feature_cutoff_ms,
        "event_time_ms": leaf.event_time_ms,
        "ingested_at_ms": leaf.ingested_at_ms,
        "available_at_ms": leaf.available_at_ms,
        "expires_at_ms": leaf.expires_at_ms,
        "finality_confirmed": leaf.finality_confirmed,
        "authentication_class": leaf.authentication_class,
    }
    if include_hash:
        material["leaf_sha256"] = leaf.leaf_sha256
    return material


def _row_clock(rows: Sequence[object], name: str, *, mode: str = "max") -> int | None:
    values = [cast(int, getattr(row, name)) for row in rows if getattr(row, name, None) is not None]
    if not values:
        return None
    return min(values) if mode == "min" else max(values)


def _build_leaf(state: _FamilyState, *, ordinal: int) -> SourceManifestLeaf:
    required = SOURCE_REQUIRED_MASK[ordinal]
    present = bool(state.observations)
    missing = required and not present
    degraded = bool(state.degradation_reason) or (present and not state.authenticated)
    if missing:
        status = "MISSING_DEGRADED" if degraded else "MISSING"
    elif degraded:
        status = "DEGRADED"
    elif present:
        status = "READY"
    else:
        status = "NOT_PROVIDED"
    rows = state.observations
    if state.family == "finalized_candles":
        feature_cutoff = _row_clock(rows, "close_time_ms")
        event_time = _row_clock(rows, "event_time_ms")
        expires_at = None
        finality = present and all(cast(CandleObservation, row).is_final for row in rows)
        auth_class = "EXACT_REDIS_BYTES_STRICT_FINALIZED_CANDLE_ADAPTER"
    elif state.family == "mark_price":
        feature_cutoff = _row_clock(rows, "event_time_ms")
        event_time = feature_cutoff
        expires_at = None
        finality = present
        auth_class = "EXACT_REDIS_BYTES_STRICT_MARK_PRICE_ADAPTER"
    elif state.family == "open_interest":
        feature_cutoff = _row_clock(rows, "feature_cutoff_ms")
        event_time = _row_clock(rows, "event_time_ms")
        expires_at = None
        finality = present and all(cast(OpenInterestObservation, row).is_final for row in rows)
        auth_class = "EXACT_REDIS_BYTES_STRICT_COINANK_PLAN3_OI_ADAPTER"
    elif state.family == "leverage_brackets":
        feature_cutoff = _row_clock(rows, "fetched_at_ms")
        event_time = feature_cutoff
        expires_at = _row_clock(rows, "expires_at_ms", mode="min")
        finality = present
        auth_class = "BINANCE_ACCOUNT_SCOPED_CHECKSUM_HMAC_CONSUMER_REOPEN"
    else:
        feature_cutoff = None
        event_time = None
        expires_at = None
        finality = False
        auth_class = "AUTHENTICATED_CAUSAL_OUTCOME_CALIBRATION_RECEIPT"
    values = {
        "ordinal": ordinal,
        "family": state.family,
        "required": required,
        "present": present,
        "authenticated": state.authenticated,
        "missing": missing,
        "degraded": degraded,
        "status": status,
        "degradation_reason": state.degradation_reason,
        "row_count": len(rows),
        "source_bindings": state.source_bindings,
        "feature_cutoff_ms": feature_cutoff,
        "event_time_ms": event_time,
        "ingested_at_ms": _row_clock(rows, "ingested_at_ms"),
        "available_at_ms": _row_clock(rows, "available_at_ms"),
        "expires_at_ms": expires_at,
        "finality_confirmed": finality,
        "authentication_class": auth_class,
    }
    return SourceManifestLeaf(
        **values,
        leaf_sha256=_stable_sha256(
            {
                **values,
                "source_bindings": [list(binding) for binding in state.source_bindings],
            }
        ),
        _construction_token=_LEAF_TOKEN,
    )


@dataclass(frozen=True, slots=True)
class PreparedLiquidationSurfaceCandidate:
    request: FrozenSurfaceRequest = field(repr=False)
    source_manifest: tuple[SourceManifestLeaf, ...]
    required_mask: tuple[bool, ...]
    available_mask: tuple[bool, ...]
    missing_mask: tuple[bool, ...]
    authenticated_mask: tuple[bool, ...]
    degraded_mask: tuple[bool, ...]
    publication_scope_metadata: Mapping[str, Any] = field(repr=False)
    publication_scope_sha256: str
    source_input_sha256: str | None
    candidate_surface_payload_sha256: str | None
    candidate_archive_payload_sha256: str | None
    candidate_payload_bytes: bytes | None = field(repr=False)
    candidate_payload: Mapping[str, Any] | None = field(repr=False)
    model_rejection_reason: str | None
    manifest_sha256: str
    feature_ready: bool
    _snapshot: _PreparationSnapshot = field(repr=False, compare=False)
    _integrity_guard: _IntegrityGuard = field(repr=False, compare=False)
    _construction_token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if (
            self._construction_token is not _PREPARED_TOKEN
            or tuple(leaf.family for leaf in self.source_manifest) != SOURCE_FAMILY_ORDER
            or self.required_mask != SOURCE_REQUIRED_MASK
            or not _deeply_immutable_json(self.publication_scope_metadata)
            or (
                self.candidate_payload is not None
                and not _deeply_immutable_json(self.candidate_payload)
            )
            or not self._integrity_guard.verify(_prepared_material(self))
        ):
            _validation_error("PREPARED_SURFACE_CANONICAL_INTEGRITY_INVALID")

    def to_publication_mapping(self) -> dict[str, Any]:
        if self.candidate_payload_bytes is None:
            _validation_error("PREPARED_SURFACE_HAS_NO_MODEL_CANDIDATE")
        parsed = json.loads(self.candidate_payload_bytes.decode("ascii"))
        if type(parsed) is not dict:
            _integrity_error("PREPARED_SURFACE_CANONICAL_PAYLOAD_INVALID")
        return cast(dict[str, Any], parsed)


def _prepared_material_values(
    *,
    request: FrozenSurfaceRequest,
    source_manifest: tuple[SourceManifestLeaf, ...],
    required_mask: tuple[bool, ...],
    available_mask: tuple[bool, ...],
    missing_mask: tuple[bool, ...],
    authenticated_mask: tuple[bool, ...],
    degraded_mask: tuple[bool, ...],
    publication_scope_metadata: Mapping[str, Any],
    publication_scope_sha256: str,
    source_input_sha256: str | None,
    candidate_surface_payload_sha256: str | None,
    candidate_archive_payload_sha256: str | None,
    candidate_payload_bytes: bytes | None,
    candidate_payload: Mapping[str, Any] | None,
    model_rejection_reason: str | None,
    manifest_sha256: str,
    feature_ready: bool,
    snapshot: _PreparationSnapshot,
) -> dict[str, Any]:
    return {
        "request": _request_material(request),
        "source_manifest": [
            _leaf_material(leaf, include_hash=True) for leaf in source_manifest
        ],
        "required_mask": list(required_mask),
        "available_mask": list(available_mask),
        "missing_mask": list(missing_mask),
        "authenticated_mask": list(authenticated_mask),
        "degraded_mask": list(degraded_mask),
        "publication_scope_metadata": dict(publication_scope_metadata),
        "publication_scope_sha256": publication_scope_sha256,
        "source_input_sha256": source_input_sha256,
        "candidate_surface_payload_sha256": candidate_surface_payload_sha256,
        "candidate_archive_payload_sha256": candidate_archive_payload_sha256,
        "candidate_payload_bytes_sha256": (
            _sha256(candidate_payload_bytes) if candidate_payload_bytes is not None else None
        ),
        "candidate_payload_tree_sha256": (
            _stable_sha256(candidate_payload) if candidate_payload is not None else None
        ),
        "model_rejection_reason": model_rejection_reason,
        "manifest_sha256": manifest_sha256,
        "feature_ready": feature_ready,
        "snapshot_sha256": _stable_sha256(_snapshot_material(snapshot)),
    }


def _prepared_material(value: PreparedLiquidationSurfaceCandidate) -> dict[str, Any]:
    return _prepared_material_values(
        request=value.request,
        source_manifest=value.source_manifest,
        required_mask=value.required_mask,
        available_mask=value.available_mask,
        missing_mask=value.missing_mask,
        authenticated_mask=value.authenticated_mask,
        degraded_mask=value.degraded_mask,
        publication_scope_metadata=value.publication_scope_metadata,
        publication_scope_sha256=value.publication_scope_sha256,
        source_input_sha256=value.source_input_sha256,
        candidate_surface_payload_sha256=value.candidate_surface_payload_sha256,
        candidate_archive_payload_sha256=value.candidate_archive_payload_sha256,
        candidate_payload_bytes=value.candidate_payload_bytes,
        candidate_payload=value.candidate_payload,
        model_rejection_reason=value.model_rejection_reason,
        manifest_sha256=value.manifest_sha256,
        feature_ready=value.feature_ready,
        snapshot=value._snapshot,
    )


def _build_prepared(snapshot: _PreparationSnapshot) -> PreparedLiquidationSurfaceCandidate:
    request, states = _adapt_snapshot(snapshot)
    candidate: dict[str, Any] | None = None
    model_reason: str | None = None
    if request.candles:
        try:
            candidate = build_liquidation_surface(request.to_contract())
        except (TypeError, ValueError) as exc:
            model_reason = f"SURFACE_MODEL_REJECTED:{exc}"
            states = [
                replace(
                    state,
                    degradation_reason=(
                        state.degradation_reason or model_reason
                        if SOURCE_REQUIRED_MASK[index]
                        else state.degradation_reason
                    ),
                )
                for index, state in enumerate(states)
            ]
    else:
        model_reason = "SURFACE_MODEL_NOT_RUN:FINALIZED_CANDLES_UNAVAILABLE"
    if candidate is not None:
        freshness = candidate.get("adaptive_freshness_evidence")
        if isinstance(freshness, Mapping):
            freshness_names = {
                "finalized_candles": "candle",
                "mark_price": "mark_price",
                "open_interest": "open_interest",
            }
            for index, state in enumerate(states):
                source_name = freshness_names.get(state.family)
                detail = freshness.get(source_name) if source_name is not None else None
                if isinstance(detail, Mapping) and detail.get("fresh") is not True:
                    states[index] = replace(
                        state,
                        degradation_reason=(
                            state.degradation_reason
                            or "ADAPTIVE_SOURCE_FRESHNESS_REJECTED"
                        ),
                    )
    leaves = tuple(_build_leaf(state, ordinal=index) for index, state in enumerate(states))
    available_mask = tuple(leaf.present for leaf in leaves)
    missing_mask = tuple(leaf.missing for leaf in leaves)
    authenticated_mask = tuple(leaf.authenticated for leaf in leaves)
    degraded_mask = tuple(leaf.degraded for leaf in leaves)
    feature_ready = bool(
        candidate is not None
        and candidate.get("trainer_semantic_eligible") is True
        and all(
            leaf.present and leaf.authenticated and not leaf.degraded
            for leaf in leaves
            if leaf.required
        )
    )
    candidate_raw = _canonical_json_bytes(candidate) if candidate is not None else None
    source_input_sha = (
        cast(str, candidate["source_input_sha256"]) if candidate is not None else None
    )
    surface_sha = (
        cast(str, candidate["surface_payload_sha256"]) if candidate is not None else None
    )
    archive_sha = _sha256(candidate_raw) if candidate_raw is not None else None
    manifest_material = {
        "schema_version": SOURCE_MANIFEST_SCHEMA_VERSION,
        "model_schema_version": SCHEMA_VERSION,
        "model_version": MODEL_VERSION,
        "venue": request.venue,
        "symbol": request.symbol,
        "timeframe": request.timeframe,
        "surface_as_of": request.as_of_time_ms,
        "generated_at": request.generated_at_ms,
        "publication_scope_sha256": snapshot.bracket_proof.publication_scope_sha256,
        "bracket_reader_proof_sha256": snapshot.bracket_proof.proof_sha256,
        "source_input_sha256": source_input_sha,
        "candidate_surface_payload_sha256": surface_sha,
        "candidate_archive_payload_sha256": archive_sha,
        "family_order": list(SOURCE_FAMILY_ORDER),
        "required_mask": list(SOURCE_REQUIRED_MASK),
        "available_mask": list(available_mask),
        "missing_mask": list(missing_mask),
        "authenticated_mask": list(authenticated_mask),
        "degraded_mask": list(degraded_mask),
        "source_leaves": [_leaf_material(leaf, include_hash=True) for leaf in leaves],
        "model_rejection_reason": model_reason,
        "feature_ready": feature_ready,
        "trainer_authority": False,
    }
    manifest_sha = _stable_sha256(manifest_material)
    frozen_metadata = snapshot.bracket_proof.safe_metadata
    frozen_candidate = (
        cast(Mapping[str, Any], _freeze_json(candidate)) if candidate is not None else None
    )
    values = {
        "request": request,
        "source_manifest": leaves,
        "required_mask": SOURCE_REQUIRED_MASK,
        "available_mask": available_mask,
        "missing_mask": missing_mask,
        "authenticated_mask": authenticated_mask,
        "degraded_mask": degraded_mask,
        "publication_scope_metadata": frozen_metadata,
        "publication_scope_sha256": snapshot.bracket_proof.publication_scope_sha256,
        "source_input_sha256": source_input_sha,
        "candidate_surface_payload_sha256": surface_sha,
        "candidate_archive_payload_sha256": archive_sha,
        "candidate_payload_bytes": candidate_raw,
        "candidate_payload": frozen_candidate,
        "model_rejection_reason": model_reason,
        "manifest_sha256": manifest_sha,
        "feature_ready": feature_ready,
        "snapshot": snapshot,
    }
    guard = _guard(_prepared_material_values(**values))
    return PreparedLiquidationSurfaceCandidate(
        request=request,
        source_manifest=leaves,
        required_mask=SOURCE_REQUIRED_MASK,
        available_mask=available_mask,
        missing_mask=missing_mask,
        authenticated_mask=authenticated_mask,
        degraded_mask=degraded_mask,
        publication_scope_metadata=frozen_metadata,
        publication_scope_sha256=snapshot.bracket_proof.publication_scope_sha256,
        source_input_sha256=source_input_sha,
        candidate_surface_payload_sha256=surface_sha,
        candidate_archive_payload_sha256=archive_sha,
        candidate_payload_bytes=candidate_raw,
        candidate_payload=frozen_candidate,
        model_rejection_reason=model_reason,
        manifest_sha256=manifest_sha,
        feature_ready=feature_ready,
        _snapshot=snapshot,
        _integrity_guard=guard,
        _construction_token=_PREPARED_TOKEN,
    )


def _copy_raw(value: object, *, name: str, optional: bool) -> RawRedisEvidence | None:
    if value is None and optional:
        return None
    if type(value) is not RawRedisEvidence:
        _validation_error(f"{name}_RAW_REDIS_EVIDENCE_REQUIRED")
    row = cast(RawRedisEvidence, value)
    try:
        return RawRedisEvidence.from_value(
            key=row.key,
            value=bytes(row.raw),
            consumer_observed_at_ms=row.consumer_observed_at_ms,
        )
    except SourceAdapterError as exc:
        raise TrainerAdmissionValidationError(f"{name}_RAW_EVIDENCE_INVALID:{exc}") from exc


def prepare_liquidation_surface_candidate(
    *,
    symbol: str,
    timeframe: str,
    as_of_time_ms: int,
    generated_at_ms: int,
    candle_evidence: RawRedisEvidence | None,
    mark_price_evidence: Sequence[RawRedisEvidence],
    open_interest_evidence: RawRedisEvidence | None,
    bracket_redis_client: Any,
    bracket_security_context: EvidenceSecurityContext,
    bracket_now_fn: Callable[[], datetime] | None = None,
    tick_size: float | None = None,
    max_cohorts: int = 256,
    max_leverage_scenarios: int = 64,
    max_levels_per_side: int = 64,
    max_source_rows_per_family: int = 4_096,
    max_expanded_candidates: int = 2_000_000,
) -> PreparedLiquidationSurfaceCandidate:
    """Derive a candidate from exact bytes and authenticated bracket evidence.

    Callers cannot provide observations, source-authentication booleans, or a
    publication-scope digest.  Missing/invalid evidence is represented by the
    fixed source masks and can never become a trainer feature.
    """

    if type(symbol) is not str or _SYMBOL_RE.fullmatch(symbol) is None:
        _validation_error("TRAINER_PREPARATION_SYMBOL_INVALID")
    if type(timeframe) is not str or _TIMEFRAME_RE.fullmatch(timeframe) is None:
        _validation_error("TRAINER_PREPARATION_TIMEFRAME_INVALID")
    as_of = _positive_ms(as_of_time_ms, name="TRAINER_PREPARATION_AS_OF_TIME")
    generated = _positive_ms(generated_at_ms, name="TRAINER_PREPARATION_GENERATED_AT")
    if as_of > generated:
        _validation_error("TRAINER_PREPARATION_AS_OF_AFTER_GENERATED_AT")
    candle = _copy_raw(candle_evidence, name="CANDLE", optional=True)
    oi = _copy_raw(open_interest_evidence, name="OPEN_INTEREST", optional=True)
    if isinstance(mark_price_evidence, str | bytes | bytearray) or not isinstance(
        mark_price_evidence, Sequence
    ):
        _validation_error("MARK_PRICE_EVIDENCE_SEQUENCE_REQUIRED")
    marks = tuple(
        cast(
            RawRedisEvidence,
            _copy_raw(row, name="MARK_PRICE", optional=False),
        )
        for row in mark_price_evidence
    )
    now_fn = bracket_now_fn or (lambda: datetime.now(UTC))
    bracket_result = read_authenticated_bracket_surface_evidence(
        bracket_redis_client,
        security_context=bracket_security_context,
        symbol=symbol,
        now_fn=now_fn,
    )
    proof = _build_bracket_proof(
        bracket_result,
        security_context=bracket_security_context,
    )
    snapshot = _PreparationSnapshot(
        symbol=symbol,
        timeframe=timeframe,
        as_of_time_ms=as_of,
        generated_at_ms=generated,
        candle_evidence=candle,
        mark_price_evidence=marks,
        open_interest_evidence=oi,
        bracket_proof=proof,
        tick_size=tick_size,
        max_cohorts=max_cohorts,
        max_leverage_scenarios=max_leverage_scenarios,
        max_levels_per_side=max_levels_per_side,
        max_source_rows_per_family=max_source_rows_per_family,
        max_expanded_candidates=max_expanded_candidates,
    )
    return _build_prepared(snapshot)


@dataclass(frozen=True, slots=True)
class TrainerDecisionContext:
    decision_id: str
    decision_time_ms: int
    symbol: str
    timeframe: str
    feature_abi_sha256: str
    _construction_token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._construction_token is not _DECISION_TOKEN:
            _validation_error("TRAINER_DECISION_CONTEXT_FACTORY_REQUIRED")


def build_trainer_decision_context(
    *,
    decision_id: str,
    decision_time_ms: int,
    symbol: str,
    timeframe: str,
    feature_abi_sha256: str,
) -> TrainerDecisionContext:
    if type(decision_id) is not str or _SAFE_ID_RE.fullmatch(decision_id) is None:
        _validation_error("TRAINER_DECISION_ID_INVALID")
    decision_time = _positive_ms(decision_time_ms, name="TRAINER_DECISION_TIME")
    if type(symbol) is not str or _SYMBOL_RE.fullmatch(symbol) is None:
        _validation_error("TRAINER_DECISION_SYMBOL_INVALID")
    if type(timeframe) is not str or _TIMEFRAME_RE.fullmatch(timeframe) is None:
        _validation_error("TRAINER_DECISION_TIMEFRAME_INVALID")
    abi_hash = _require_sha256(feature_abi_sha256, name="TRAINER_FEATURE_ABI_SHA256")
    return TrainerDecisionContext(
        decision_id=decision_id,
        decision_time_ms=decision_time,
        symbol=symbol,
        timeframe=timeframe,
        feature_abi_sha256=abi_hash,
        _construction_token=_DECISION_TOKEN,
    )


@dataclass(frozen=True, slots=True)
class TrainerAdmissionSecurityContext:
    auth_key_id: str
    hmac_key: bytes = field(repr=False)
    _construction_token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._construction_token is not _SECURITY_TOKEN:
            _validation_error("TRAINER_ADMISSION_SECURITY_CONTEXT_FACTORY_REQUIRED")


def build_trainer_admission_security_context(
    *,
    auth_key_id: str,
    hmac_key: str | bytes | bytearray,
) -> TrainerAdmissionSecurityContext:
    if type(auth_key_id) is not str or _SAFE_ID_RE.fullmatch(auth_key_id) is None:
        _validation_error("TRAINER_ADMISSION_AUTH_KEY_ID_INVALID")
    if isinstance(hmac_key, str):
        key = hmac_key.encode("utf-8")
    elif isinstance(hmac_key, bytes | bytearray):
        key = bytes(hmac_key)
    else:
        key = b""
    if len(key) < MIN_ADMISSION_HMAC_KEY_BYTES:
        _validation_error("TRAINER_ADMISSION_HMAC_KEY_MISSING_OR_TOO_SHORT")
    return TrainerAdmissionSecurityContext(
        auth_key_id=auth_key_id,
        hmac_key=key,
        _construction_token=_SECURITY_TOKEN,
    )


@dataclass(frozen=True, slots=True)
class LiquidationSurfaceTrainerAdmission:
    decision_id: str
    decision_time_ms: int
    admission_checked_at_ms: int
    symbol: str
    timeframe: str
    feature_abi_sha256: str
    surface_id: str
    surface_archive_payload_sha256: str
    surface_publication_receipt_sha256: str
    source_manifest_sha256: str
    publication_scope_sha256: str
    admission_auth_key_id: str
    feature_cutoff_ms: int
    publication_available_at_ms: int
    adaptive_source_valid_until_ms: int | None
    bracket_valid_until_ms: int | None
    feature_available: bool
    trainer_authority: bool
    trainer_authority_reason: str
    required_mask: tuple[bool, ...]
    available_mask: tuple[bool, ...]
    missing_mask: tuple[bool, ...]
    authenticated_mask: tuple[bool, ...]
    degraded_mask: tuple[bool, ...]
    rejection_reasons: tuple[str, ...]
    prediction_authority: bool
    paper_trading_authority: bool
    live_execution_authority: bool
    surface_payload: Mapping[str, Any] | None = field(repr=False)
    admission_receipt: Mapping[str, Any] = field(repr=False)
    admission_receipt_sha256: str
    admission_receipt_hmac_sha256: str
    _integrity_guard: _IntegrityGuard = field(repr=False, compare=False)
    _construction_token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if (
            self._construction_token is not _RESULT_TOKEN
            or self.trainer_authority is not self.feature_available
            or self.prediction_authority is not False
            or self.paper_trading_authority is not False
            or self.live_execution_authority is not False
            or not _deeply_immutable_json(self.admission_receipt)
            or (
                self.surface_payload is not None
                and not _deeply_immutable_json(self.surface_payload)
            )
            or (not self.feature_available and self.surface_payload is not None)
            or not self._integrity_guard.verify(_result_material(self))
        ):
            _validation_error("TRAINER_ADMISSION_RESULT_CANONICAL_INTEGRITY_INVALID")

    def is_authorized_for(
        self,
        *,
        decision_id: str,
        decision_time_ms: int,
        symbol: str,
        timeframe: str,
        feature_abi_sha256: str,
    ) -> bool:
        try:
            expected_core = _result_receipt_core(self)
            receipt = dict(self.admission_receipt)
            observed_hmac = receipt.pop("admission_receipt_hmac_sha256", None)
            observed_sha = receipt.pop("admission_receipt_sha256", None)
            structurally_valid = bool(
                _canonical_json_bytes(receipt) == _canonical_json_bytes(expected_core)
                and observed_sha == _stable_sha256(expected_core)
                and observed_sha == self.admission_receipt_sha256
                and observed_hmac == self.admission_receipt_hmac_sha256
                and _valid_sha256(observed_hmac)
                and self.surface_payload is not None
                and _stable_sha256(self.surface_payload)
                == self.surface_archive_payload_sha256
                and self._integrity_guard.verify(_result_material(self))
            )
        except (TrainerAdmissionError, TypeError, ValueError):
            return False
        return bool(
            structurally_valid
            and self.trainer_authority
            and decision_id == self.decision_id
            and type(decision_time_ms) is int
            and decision_time_ms == self.decision_time_ms
            and symbol == self.symbol
            and timeframe == self.timeframe
            and feature_abi_sha256 == self.feature_abi_sha256
        )


def _result_receipt_core_values(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": ADMISSION_SCHEMA_VERSION,
        "decision_id": value["decision_id"],
        "decision_time_ms": value["decision_time_ms"],
        "admission_checked_at_ms": value["admission_checked_at_ms"],
        "symbol": value["symbol"],
        "timeframe": value["timeframe"],
        "feature_abi_sha256": value["feature_abi_sha256"],
        "surface_id": value["surface_id"],
        "surface_archive_payload_sha256": value["surface_archive_payload_sha256"],
        "surface_publication_receipt_sha256": value[
            "surface_publication_receipt_sha256"
        ],
        "source_manifest_sha256": value["source_manifest_sha256"],
        "publication_scope_sha256": value["publication_scope_sha256"],
        "admission_auth_key_id": value["admission_auth_key_id"],
        "family_order": list(SOURCE_FAMILY_ORDER),
        "required_mask": list(value["required_mask"]),
        "available_mask": list(value["available_mask"]),
        "missing_mask": list(value["missing_mask"]),
        "authenticated_mask": list(value["authenticated_mask"]),
        "degraded_mask": list(value["degraded_mask"]),
        "feature_cutoff": value["feature_cutoff_ms"],
        "publication_available_at": value["publication_available_at_ms"],
        "adaptive_source_valid_until": value["adaptive_source_valid_until_ms"],
        "adaptive_source_valid_until_inclusive": True,
        "bracket_valid_until": value["bracket_valid_until_ms"],
        "bracket_valid_until_exclusive": True,
        "feature_available": value["feature_available"],
        "trainer_authority": value["trainer_authority"],
        "trainer_authority_reason": value["trainer_authority_reason"],
        "rejection_reasons": list(value["rejection_reasons"]),
        "prediction_authority": value["prediction_authority"],
        "paper_trading_authority": value["paper_trading_authority"],
        "live_execution_authority": value["live_execution_authority"],
    }


def _result_receipt_core(value: LiquidationSurfaceTrainerAdmission) -> dict[str, Any]:
    return _result_receipt_core_values(_result_exposed(value))


def _result_material_values(
    *,
    receipt: Mapping[str, Any],
    surface_payload: Mapping[str, Any] | None,
    exposed: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "exposed": dict(exposed),
        "receipt": dict(receipt),
        "surface_payload_sha256": (
            _stable_sha256(surface_payload) if surface_payload is not None else None
        ),
    }


def _result_exposed(value: LiquidationSurfaceTrainerAdmission) -> dict[str, Any]:
    return {
        key: getattr(value, key)
        for key in (
            "decision_id",
            "decision_time_ms",
            "admission_checked_at_ms",
            "symbol",
            "timeframe",
            "feature_abi_sha256",
            "surface_id",
            "surface_archive_payload_sha256",
            "surface_publication_receipt_sha256",
            "source_manifest_sha256",
            "publication_scope_sha256",
            "admission_auth_key_id",
            "feature_cutoff_ms",
            "publication_available_at_ms",
            "adaptive_source_valid_until_ms",
            "bracket_valid_until_ms",
            "feature_available",
            "trainer_authority",
            "trainer_authority_reason",
            "required_mask",
            "available_mask",
            "missing_mask",
            "authenticated_mask",
            "degraded_mask",
            "rejection_reasons",
            "prediction_authority",
            "paper_trading_authority",
            "live_execution_authority",
            "admission_receipt_sha256",
            "admission_receipt_hmac_sha256",
        )
    }


def _result_material(value: LiquidationSurfaceTrainerAdmission) -> dict[str, Any]:
    return _result_material_values(
        receipt=value.admission_receipt,
        surface_payload=value.surface_payload,
        exposed=_result_exposed(value),
    )


def _require_prepared(
    value: object,
) -> PreparedLiquidationSurfaceCandidate:
    if (
        type(value) is not PreparedLiquidationSurfaceCandidate
        or value._construction_token is not _PREPARED_TOKEN
        or not value._integrity_guard.verify(_prepared_material(value))
    ):
        _validation_error("PREPARED_SURFACE_FACTORY_RESULT_REQUIRED")
    canonical = _build_prepared(value._snapshot)
    if _prepared_material(canonical) != _prepared_material(value):
        _integrity_error("PREPARED_SURFACE_CANONICAL_REDERIVATION_MISMATCH")
    return canonical


def _prepared_source_snapshot_material(
    prepared: PreparedLiquidationSurfaceCandidate,
) -> dict[str, Any]:
    snapshot = prepared._snapshot
    return {
        "symbol": snapshot.symbol,
        "timeframe": snapshot.timeframe,
        "as_of_time_ms": snapshot.as_of_time_ms,
        "generated_at_ms": snapshot.generated_at_ms,
        "candle_evidence": _raw_source_bundle_material(snapshot.candle_evidence),
        "mark_price_evidence": [
            _raw_source_bundle_material(row) for row in snapshot.mark_price_evidence
        ],
        "open_interest_evidence": _raw_source_bundle_material(
            snapshot.open_interest_evidence
        ),
        "bracket_proof": _bracket_proof_material(
            snapshot.bracket_proof,
            include_hash=True,
        ),
        "tick_size": snapshot.tick_size,
        "max_cohorts": snapshot.max_cohorts,
        "max_leverage_scenarios": snapshot.max_leverage_scenarios,
        "max_levels_per_side": snapshot.max_levels_per_side,
        "max_source_rows_per_family": snapshot.max_source_rows_per_family,
        "max_expanded_candidates": snapshot.max_expanded_candidates,
    }


def prepared_source_bundle_mapping(
    prepared: PreparedLiquidationSurfaceCandidate,
) -> dict[str, Any]:
    """Export exact source bytes for storage inside one signed publication.

    This mapping has no standalone authenticity.  Consumers must obtain it
    from a :class:`VerifiedLiquidationSurface`; the publication receipt HMAC
    authenticates the containing archive before this module will reopen it.
    """

    canonical = _require_prepared(prepared)
    core: dict[str, Any] = {
        "schema_version": PREPARED_SOURCE_BUNDLE_SCHEMA_VERSION,
        "publication_scope_sha256": canonical.publication_scope_sha256,
        "source_manifest_sha256": canonical.manifest_sha256,
        "source_input_sha256": canonical.source_input_sha256,
        "candidate_surface_payload_sha256": (
            canonical.candidate_surface_payload_sha256
        ),
        "candidate_archive_payload_sha256": (
            canonical.candidate_archive_payload_sha256
        ),
        "prepared_material_sha256": _stable_sha256(_prepared_material(canonical)),
        "feature_ready": canonical.feature_ready,
        "model_rejection_reason": canonical.model_rejection_reason,
        "required_mask": list(canonical.required_mask),
        "available_mask": list(canonical.available_mask),
        "missing_mask": list(canonical.missing_mask),
        "authenticated_mask": list(canonical.authenticated_mask),
        "degraded_mask": list(canonical.degraded_mask),
        "snapshot": _prepared_source_snapshot_material(canonical),
        "trainer_authority": False,
        "prediction_authority": False,
        "paper_trading_authority": False,
        "live_execution_authority": False,
    }
    core["bundle_sha256"] = _stable_sha256(core)
    _canonical_json_bytes(core)
    return core


def publication_mapping_with_prepared_source_bundle(
    prepared: PreparedLiquidationSurfaceCandidate,
) -> dict[str, Any]:
    """Return the model candidate plus its exact non-authoritative source bundle."""

    canonical = _require_prepared(prepared)
    payload = canonical.to_publication_mapping()
    payload["trainer_source_bundle"] = prepared_source_bundle_mapping(canonical)
    return payload


def _bracket_proof_from_source_bundle(value: object) -> _AuthenticatedBracketReaderProof:
    expected_fields = {
        "status",
        "evidence_authenticated",
        "observations",
        "safe_metadata",
        "publication_scope_sha256",
        "evidence_key",
        "content_checksum_sha256",
        "reader_result_sha256",
        "proof_sha256",
    }
    if type(value) is not dict or set(cast(dict[object, object], value)) != expected_fields:
        _validation_error("SOURCE_BUNDLE_BRACKET_PROOF_FIELDS_INVALID")
    material = cast(dict[str, Any], value)
    raw_observations = material.get("observations")
    if type(raw_observations) is not list:
        _validation_error("SOURCE_BUNDLE_BRACKET_OBSERVATIONS_INVALID")
    observation_fields = set(LeverageBracket.__dataclass_fields__)
    observations: list[LeverageBracket] = []
    for raw in cast(list[object], raw_observations):
        if type(raw) is not dict or set(cast(dict[object, object], raw)) != observation_fields:
            _validation_error("SOURCE_BUNDLE_BRACKET_OBSERVATION_FIELDS_INVALID")
        try:
            observations.append(LeverageBracket(**cast(dict[str, Any], raw)))
        except TypeError as exc:
            raise TrainerAdmissionValidationError(
                "SOURCE_BUNDLE_BRACKET_OBSERVATION_INVALID"
            ) from exc
    safe_metadata = material.get("safe_metadata")
    if type(safe_metadata) is not dict:
        _validation_error("SOURCE_BUNDLE_BRACKET_SCOPE_METADATA_INVALID")
    scope_metadata = cast(dict[str, Any], safe_metadata)
    scope = derive_publication_scope_sha256(scope_metadata)
    if scope != material.get("publication_scope_sha256"):
        _integrity_error("SOURCE_BUNDLE_BRACKET_SCOPE_HASH_MISMATCH")
    status = material.get("status")
    authenticated = material.get("evidence_authenticated")
    if type(status) is not str or type(authenticated) is not bool:
        _validation_error("SOURCE_BUNDLE_BRACKET_STATUS_INVALID")
    if (
        (status == "READY" and (authenticated is not True or not observations))
        or (status != "READY" and (authenticated is not False or observations))
        or not _valid_sha256(material.get("reader_result_sha256"))
        or not _valid_sha256(material.get("proof_sha256"))
    ):
        _validation_error("SOURCE_BUNDLE_BRACKET_PROOF_INVALID")
    evidence_key = material.get("evidence_key")
    checksum = material.get("content_checksum_sha256")
    if evidence_key is not None and type(evidence_key) is not str:
        _validation_error("SOURCE_BUNDLE_BRACKET_EVIDENCE_KEY_INVALID")
    if checksum is not None and not _valid_sha256(checksum):
        _validation_error("SOURCE_BUNDLE_BRACKET_CHECKSUM_INVALID")
    return _AuthenticatedBracketReaderProof(
        status=cast(str, status),
        evidence_authenticated=cast(bool, authenticated),
        observations=tuple(observations),
        safe_metadata=cast(Mapping[str, Any], _freeze_json(scope_metadata)),
        publication_scope_sha256=scope,
        evidence_key=cast(str | None, evidence_key),
        content_checksum_sha256=cast(str | None, checksum),
        reader_result_sha256=cast(str, material["reader_result_sha256"]),
        proof_sha256=cast(str, material["proof_sha256"]),
        _construction_token=_PROOF_TOKEN,
    )


def _prepared_from_source_bundle_mapping(value: object) -> PreparedLiquidationSurfaceCandidate:
    expected_fields = {
        "schema_version",
        "publication_scope_sha256",
        "source_manifest_sha256",
        "source_input_sha256",
        "candidate_surface_payload_sha256",
        "candidate_archive_payload_sha256",
        "prepared_material_sha256",
        "feature_ready",
        "model_rejection_reason",
        "required_mask",
        "available_mask",
        "missing_mask",
        "authenticated_mask",
        "degraded_mask",
        "snapshot",
        "trainer_authority",
        "prediction_authority",
        "paper_trading_authority",
        "live_execution_authority",
        "bundle_sha256",
    }
    if type(value) is not dict or set(cast(dict[object, object], value)) != expected_fields:
        _validation_error("PREPARED_SOURCE_BUNDLE_FIELDS_INVALID")
    bundle = cast(dict[str, Any], value)
    supplied_sha = bundle.get("bundle_sha256")
    unsigned = dict(bundle)
    unsigned.pop("bundle_sha256", None)
    if (
        bundle.get("schema_version") != PREPARED_SOURCE_BUNDLE_SCHEMA_VERSION
        or not _valid_sha256(supplied_sha)
        or supplied_sha != _stable_sha256(unsigned)
        or bundle.get("trainer_authority") is not False
        or bundle.get("prediction_authority") is not False
        or bundle.get("paper_trading_authority") is not False
        or bundle.get("live_execution_authority") is not False
    ):
        _integrity_error("PREPARED_SOURCE_BUNDLE_HASH_OR_AUTHORITY_INVALID")
    snapshot_value = bundle.get("snapshot")
    snapshot_fields = {
        "symbol",
        "timeframe",
        "as_of_time_ms",
        "generated_at_ms",
        "candle_evidence",
        "mark_price_evidence",
        "open_interest_evidence",
        "bracket_proof",
        "tick_size",
        "max_cohorts",
        "max_leverage_scenarios",
        "max_levels_per_side",
        "max_source_rows_per_family",
        "max_expanded_candidates",
    }
    if (
        type(snapshot_value) is not dict
        or set(cast(dict[object, object], snapshot_value)) != snapshot_fields
    ):
        _validation_error("PREPARED_SOURCE_BUNDLE_SNAPSHOT_FIELDS_INVALID")
    source = cast(dict[str, Any], snapshot_value)
    mark_values = source.get("mark_price_evidence")
    if type(mark_values) is not list:
        _validation_error("MARK_PRICE_SOURCE_BUNDLE_EVIDENCE_SEQUENCE_INVALID")
    marks = tuple(
        cast(
            RawRedisEvidence,
            _raw_from_source_bundle(
                row,
                name="MARK_PRICE",
                optional=False,
            ),
        )
        for row in cast(list[object], mark_values)
    )
    snapshot = _PreparationSnapshot(
        symbol=source.get("symbol"),
        timeframe=source.get("timeframe"),
        as_of_time_ms=source.get("as_of_time_ms"),
        generated_at_ms=source.get("generated_at_ms"),
        candle_evidence=_raw_from_source_bundle(
            source.get("candle_evidence"),
            name="CANDLE",
            optional=True,
        ),
        mark_price_evidence=marks,
        open_interest_evidence=_raw_from_source_bundle(
            source.get("open_interest_evidence"),
            name="OPEN_INTEREST",
            optional=True,
        ),
        bracket_proof=_bracket_proof_from_source_bundle(source.get("bracket_proof")),
        tick_size=source.get("tick_size"),
        max_cohorts=source.get("max_cohorts"),
        max_leverage_scenarios=source.get("max_leverage_scenarios"),
        max_levels_per_side=source.get("max_levels_per_side"),
        max_source_rows_per_family=source.get("max_source_rows_per_family"),
        max_expanded_candidates=source.get("max_expanded_candidates"),
    )
    rebuilt = _build_prepared(snapshot)
    expected = {
        "publication_scope_sha256": rebuilt.publication_scope_sha256,
        "source_manifest_sha256": rebuilt.manifest_sha256,
        "source_input_sha256": rebuilt.source_input_sha256,
        "candidate_surface_payload_sha256": rebuilt.candidate_surface_payload_sha256,
        "candidate_archive_payload_sha256": rebuilt.candidate_archive_payload_sha256,
        "prepared_material_sha256": _stable_sha256(_prepared_material(rebuilt)),
        "feature_ready": rebuilt.feature_ready,
        "model_rejection_reason": rebuilt.model_rejection_reason,
        "required_mask": list(rebuilt.required_mask),
        "available_mask": list(rebuilt.available_mask),
        "missing_mask": list(rebuilt.missing_mask),
        "authenticated_mask": list(rebuilt.authenticated_mask),
        "degraded_mask": list(rebuilt.degraded_mask),
    }
    if any(bundle.get(name) != expected_value for name, expected_value in expected.items()):
        _integrity_error("PREPARED_SOURCE_BUNDLE_REDERIVATION_MISMATCH")
    return rebuilt


def _require_decision(value: object) -> TrainerDecisionContext:
    if (
        type(value) is not TrainerDecisionContext
        or value._construction_token is not _DECISION_TOKEN
    ):
        _validation_error("TRAINER_DECISION_FACTORY_RESULT_REQUIRED")
    rebuilt = build_trainer_decision_context(
        decision_id=value.decision_id,
        decision_time_ms=value.decision_time_ms,
        symbol=value.symbol,
        timeframe=value.timeframe,
        feature_abi_sha256=value.feature_abi_sha256,
    )
    if rebuilt != value:
        _validation_error("TRAINER_DECISION_FACTORY_RESULT_REQUIRED")
    return rebuilt


def _require_security(value: object) -> TrainerAdmissionSecurityContext:
    if (
        type(value) is not TrainerAdmissionSecurityContext
        or value._construction_token is not _SECURITY_TOKEN
    ):
        _validation_error("TRAINER_ADMISSION_SECURITY_FACTORY_RESULT_REQUIRED")
    rebuilt = build_trainer_admission_security_context(
        auth_key_id=value.auth_key_id,
        hmac_key=value.hmac_key,
    )
    if rebuilt != value:
        _validation_error("TRAINER_ADMISSION_SECURITY_FACTORY_RESULT_REQUIRED")
    return rebuilt


def _require_publication(value: object) -> VerifiedLiquidationSurface:
    if type(value) is not VerifiedLiquidationSurface:
        _validation_error("VERIFIED_LIQUIDATION_SURFACE_REQUIRED")
    publication = cast(VerifiedLiquidationSurface, value)
    receipt = dict(publication.receipt)
    receipt_hmac = receipt.pop("receipt_hmac_sha256", None)
    receipt_sha = receipt.pop("receipt_sha256", None)
    if (
        publication.trainer_authority is not False
        or publication.payload.get("trainer_authority") is not False
        or publication.receipt.get("trainer_authority") is not False
        or publication.receipt.get("archived_trainer_authority") is not False
        or publication.payload.get("postcommit_receipt_bound") is not True
        or not _deeply_immutable_json(publication.payload)
        or not _deeply_immutable_json(publication.receipt)
        or receipt_sha != _stable_sha256(receipt)
        or receipt_sha != publication.receipt_sha256
        or not _valid_sha256(receipt_hmac)
        or publication.payload.get("surface_id") != publication.surface_id
        or publication.payload.get("surface_archive_key") != publication.surface_archive_key
        or publication.payload.get("surface_receipt_key") != publication.surface_receipt_key
        or publication.payload.get("publication_scope_sha256")
        != publication.publication_scope_sha256
        or publication.payload.get("publication_pointer_class") != publication.pointer_class
        or publication.payload.get("publication_archive_payload_sha256")
        != publication.archive_payload_sha256
        or publication.payload.get("publication_receipt_sha256")
        != publication.receipt_sha256
        or publication.payload.get("publication_archive_postcommit_at")
        != publication.archive_postcommit_at_ms
        or publication.payload.get("publication_redis_reopened_at")
        != publication.redis_reopened_at_ms
        or publication.payload.get("publication_consumer_reopened_at")
        != publication.consumer_reopened_at_ms
        or publication.receipt.get("surface_id") != publication.surface_id
        or publication.receipt.get("surface_archive_key") != publication.surface_archive_key
        or publication.receipt.get("surface_receipt_key") != publication.surface_receipt_key
        or publication.receipt.get("publication_scope_sha256")
        != publication.publication_scope_sha256
        or publication.receipt.get("archive_payload_sha256")
        != publication.archive_payload_sha256
        or publication.receipt.get("archive_postcommit_at")
        != publication.archive_postcommit_at_ms
    ):
        _integrity_error("PUBLICATION_EXACT_NON_AUTHORITATIVE_BINDING_INVALID")
    return publication


def reopen_prepared_source_bundle_from_publication(
    publication: VerifiedLiquidationSurface,
) -> PreparedLiquidationSurfaceCandidate:
    """Rebuild exact prepared evidence only from an HMAC-verified archive."""

    verified = _require_publication(publication)
    raw_bundle = verified.payload.get("trainer_source_bundle")
    bundle_value = _plain_json(raw_bundle)
    if type(bundle_value) is not dict:
        _validation_error("VERIFIED_PUBLICATION_PREPARED_SOURCE_BUNDLE_MISSING")
    bundle = cast(dict[str, Any], bundle_value)
    bundle_sha = bundle.get("bundle_sha256")
    if (
        not _valid_sha256(bundle_sha)
        or verified.receipt.get("trainer_source_bundle_sha256") != bundle_sha
    ):
        _integrity_error("PUBLICATION_PREPARED_SOURCE_BUNDLE_RECEIPT_MISMATCH")
    rebuilt = _prepared_from_source_bundle_mapping(bundle)
    if (
        rebuilt.publication_scope_sha256 != verified.publication_scope_sha256
        or rebuilt.request.symbol != verified.payload.get("symbol")
        or rebuilt.request.timeframe != verified.payload.get("timeframe")
        or rebuilt.request.as_of_time_ms != verified.payload.get("surface_as_of")
        or rebuilt.request.generated_at_ms != verified.payload.get("generated_at")
        or rebuilt.candidate_surface_payload_sha256
        != verified.payload.get("surface_payload_sha256")
        or rebuilt.candidate_archive_payload_sha256
        != verified.receipt.get("model_candidate_archive_payload_sha256")
    ):
        _integrity_error("PUBLICATION_PREPARED_SOURCE_BUNDLE_IDENTITY_MISMATCH")
    return rebuilt


def _bind_publication(
    publication: VerifiedLiquidationSurface,
    prepared: PreparedLiquidationSurfaceCandidate,
) -> dict[str, Any]:
    if prepared.candidate_payload_bytes is None:
        _integrity_error("PREPARED_SURFACE_HAS_NO_MODEL_CANDIDATE")
    rederived = build_liquidation_surface(prepared.request.to_contract())
    raw = _canonical_json_bytes(rederived)
    if raw != prepared.candidate_payload_bytes:
        _integrity_error("PREPARED_CANDIDATE_REDERIVATION_MISMATCH")
    archive_hash = _sha256(raw)
    if (
        archive_hash != prepared.candidate_archive_payload_sha256
        or publication.receipt.get("model_candidate_archive_payload_sha256")
        != archive_hash
        or publication.receipt.get("model_candidate_archive_payload_byte_count")
        != len(raw)
        or rederived.get("surface_payload_sha256")
        != prepared.candidate_surface_payload_sha256
        or publication.payload.get("surface_payload_sha256")
        != prepared.candidate_surface_payload_sha256
        or publication.receipt.get("model_surface_payload_sha256")
        != prepared.candidate_surface_payload_sha256
        or rederived.get("source_input_sha256") != prepared.source_input_sha256
        or publication.payload.get("source_input_sha256") != prepared.source_input_sha256
        or publication.receipt.get("source_input_sha256") != prepared.source_input_sha256
    ):
        _integrity_error("PUBLICATION_PREPARED_MODEL_HASH_BINDING_MISMATCH")
    expected_identity = {
        "venue": prepared.request.venue,
        "symbol": prepared.request.symbol,
        "timeframe": prepared.request.timeframe,
        "surface_as_of": prepared.request.as_of_time_ms,
        "generated_at": prepared.request.generated_at_ms,
    }
    if any(
        publication.payload.get(key) != expected
        or publication.receipt.get(key) != expected
        for key, expected in expected_identity.items()
    ):
        _integrity_error("PUBLICATION_PREPARED_IDENTITY_OR_CLOCK_BINDING_MISMATCH")
    if not (
        publication.publication_scope_sha256 == prepared.publication_scope_sha256
        and publication.payload.get("publication_scope_sha256")
        == prepared.publication_scope_sha256
        and publication.receipt.get("publication_scope_sha256")
        == prepared.publication_scope_sha256
    ):
        _integrity_error("ADMISSION_PUBLICATION_BRACKET_SCOPE_MISMATCH")
    return rederived


def _manifest_rejection_reasons(
    prepared: PreparedLiquidationSurfaceCandidate,
) -> list[str]:
    reasons: list[str] = []
    for leaf in prepared.source_manifest:
        if leaf.missing:
            reasons.append(f"SOURCE_MISSING:{leaf.family}")
        if leaf.degraded:
            reasons.append(f"SOURCE_DEGRADED:{leaf.family}:{leaf.degradation_reason}")
        elif leaf.required and not leaf.authenticated:
            reasons.append(f"SOURCE_NOT_AUTHENTICATED:{leaf.family}")
    return reasons


def _build_result(
    *,
    values: dict[str, Any],
    surface_payload: Mapping[str, Any] | None,
    security: TrainerAdmissionSecurityContext,
) -> LiquidationSurfaceTrainerAdmission:
    core = _result_receipt_core_values(values)
    receipt_sha = _stable_sha256(core)
    with_sha = {**core, "admission_receipt_sha256": receipt_sha}
    receipt_hmac = hmac.new(
        security.hmac_key,
        _canonical_json_bytes(with_sha),
        hashlib.sha256,
    ).hexdigest()
    receipt = cast(
        Mapping[str, Any],
        _freeze_json({**with_sha, "admission_receipt_hmac_sha256": receipt_hmac}),
    )
    values = {
        **values,
        "admission_receipt_sha256": receipt_sha,
        "admission_receipt_hmac_sha256": receipt_hmac,
    }
    exposed = dict(values)
    material = _result_material_values(
        receipt=receipt,
        surface_payload=surface_payload,
        exposed=exposed,
    )
    return LiquidationSurfaceTrainerAdmission(
        **values,
        surface_payload=surface_payload,
        admission_receipt=receipt,
        _integrity_guard=_guard(material),
        _construction_token=_RESULT_TOKEN,
    )


def _validate_result_authenticator(
    result: LiquidationSurfaceTrainerAdmission,
    *,
    security: TrainerAdmissionSecurityContext,
) -> None:
    expected_core = _result_receipt_core(result)
    expected_sha = _stable_sha256(expected_core)
    with_sha = {**expected_core, "admission_receipt_sha256": expected_sha}
    expected_hmac = hmac.new(
        security.hmac_key,
        _canonical_json_bytes(with_sha),
        hashlib.sha256,
    ).hexdigest()
    expected_receipt = {
        **with_sha,
        "admission_receipt_hmac_sha256": expected_hmac,
    }
    if (
        _canonical_json_bytes(result.admission_receipt)
        != _canonical_json_bytes(expected_receipt)
        or result.admission_receipt_sha256 != expected_sha
        or not hmac.compare_digest(result.admission_receipt_hmac_sha256, expected_hmac)
        or not result._integrity_guard.verify(_result_material(result))
        or (
            result.surface_payload is not None
            and _stable_sha256(result.surface_payload)
            != result.surface_archive_payload_sha256
        )
    ):
        _integrity_error("TRAINER_ADMISSION_RESULT_REVALIDATION_FAILED")


def evaluate_liquidation_surface_trainer_admission(
    publication: VerifiedLiquidationSurface,
    prepared: PreparedLiquidationSurfaceCandidate,
    *,
    decision_context: TrainerDecisionContext,
    admission_security_context: TrainerAdmissionSecurityContext,
    now_ms_fn: Callable[[], int] | None = None,
) -> LiquidationSurfaceTrainerAdmission:
    """Evaluate one exact, non-reusable trainer feature admission."""

    verified = _require_publication(publication)
    source_bundle = _require_prepared(prepared)
    decision = _require_decision(decision_context)
    security = _require_security(admission_security_context)
    rederived = _bind_publication(verified, source_bundle)
    if (
        decision.symbol != source_bundle.request.symbol
        or decision.timeframe != source_bundle.request.timeframe
    ):
        _validation_error("ADMISSION_DECISION_IDENTITY_MISMATCH")
    checked_at = _positive_ms(
        (time.time_ns() // 1_000_000) if now_ms_fn is None else now_ms_fn(),
        name="TRAINER_ADMISSION_CHECKED_AT",
    )
    generated_at = _positive_ms(rederived.get("generated_at"), name="ADMISSION_GENERATED_AT")
    feature_cutoff = _positive_ms(rederived.get("feature_cutoff"), name="ADMISSION_FEATURE_CUTOFF")
    publication_available_at = _positive_ms(
        verified.consumer_reopened_at_ms,
        name="ADMISSION_PUBLICATION_AVAILABLE_AT",
    )
    if not (
        generated_at
        <= verified.archive_postcommit_at_ms
        <= verified.redis_reopened_at_ms
        <= publication_available_at
    ):
        _integrity_error("ADMISSION_PUBLICATION_CLOCK_ORDER_INVALID")
    reasons = _manifest_rejection_reasons(source_bundle)
    if source_bundle.feature_ready is not True:
        reasons.append("SOURCE_MANIFEST_NOT_FEATURE_READY")
    if verified.pointer_class != "trainer_eligible":
        reasons.append("TRAINER_ELIGIBLE_PUBLICATION_POINTER_REQUIRED")
    if verified.payload.get("trainer_semantic_eligible") is not True:
        reasons.append("PUBLISHED_SURFACE_NOT_SEMANTICALLY_ELIGIBLE")
    if publication_available_at > decision.decision_time_ms:
        reasons.append("PUBLICATION_AVAILABLE_AFTER_DECISION_TIME")
    if feature_cutoff > decision.decision_time_ms:
        reasons.append("FEATURE_CUTOFF_AFTER_DECISION_TIME")
    if checked_at < publication_available_at:
        reasons.append("ADMISSION_CLOCK_BEFORE_PUBLICATION_AVAILABLE")
    if checked_at > decision.decision_time_ms:
        reasons.append("ADMISSION_CHECKED_AFTER_DECISION_TIME")
    adaptive_until = rederived.get("adaptive_source_valid_until")
    bracket_until = rederived.get("bracket_valid_until")
    if type(adaptive_until) is not int:
        reasons.append("ADAPTIVE_SOURCE_VALIDITY_MISSING")
    elif decision.decision_time_ms > adaptive_until:
        reasons.append("ADAPTIVE_SOURCE_FRESHNESS_EXPIRED")
    if type(bracket_until) is not int:
        reasons.append("BRACKET_VALIDITY_MISSING")
    elif decision.decision_time_ms >= bracket_until:
        reasons.append("BRACKET_EVIDENCE_EXPIRED")
    rejection_reasons = tuple(dict.fromkeys(reasons))
    feature_available = not rejection_reasons
    authority_reason = (
        "DECISION_SCOPED_SOURCE_PROVENANCE_ADMISSION_VERIFIED"
        if feature_available
        else rejection_reasons[0]
    )
    values: dict[str, Any] = {
        "decision_id": decision.decision_id,
        "decision_time_ms": decision.decision_time_ms,
        "admission_checked_at_ms": checked_at,
        "symbol": decision.symbol,
        "timeframe": decision.timeframe,
        "feature_abi_sha256": decision.feature_abi_sha256,
        "surface_id": verified.surface_id,
        "surface_archive_payload_sha256": cast(
            str,
            verified.receipt["model_candidate_archive_payload_sha256"],
        ),
        "surface_publication_receipt_sha256": verified.receipt_sha256,
        "source_manifest_sha256": source_bundle.manifest_sha256,
        "publication_scope_sha256": source_bundle.publication_scope_sha256,
        "admission_auth_key_id": security.auth_key_id,
        "feature_cutoff_ms": feature_cutoff,
        "publication_available_at_ms": publication_available_at,
        "adaptive_source_valid_until_ms": (
            cast(int, adaptive_until) if type(adaptive_until) is int else None
        ),
        "bracket_valid_until_ms": (
            cast(int, bracket_until) if type(bracket_until) is int else None
        ),
        "feature_available": feature_available,
        "trainer_authority": feature_available,
        "trainer_authority_reason": authority_reason,
        "required_mask": source_bundle.required_mask,
        "available_mask": source_bundle.available_mask,
        "missing_mask": source_bundle.missing_mask,
        "authenticated_mask": source_bundle.authenticated_mask,
        "degraded_mask": source_bundle.degraded_mask,
        "rejection_reasons": rejection_reasons,
        "prediction_authority": False,
        "paper_trading_authority": False,
        "live_execution_authority": False,
    }
    surface_payload = source_bundle.candidate_payload if feature_available else None
    result = _build_result(values=values, surface_payload=surface_payload, security=security)
    _validate_result_authenticator(result, security=security)
    return result


__all__ = [
    "ADMISSION_SCHEMA_VERSION",
    "MIN_ADMISSION_HMAC_KEY_BYTES",
    "PREPARED_SOURCE_BUNDLE_SCHEMA_VERSION",
    "SOURCE_FAMILY_ORDER",
    "SOURCE_MANIFEST_SCHEMA_VERSION",
    "SOURCE_REQUIRED_MASK",
    "LiquidationSurfaceTrainerAdmission",
    "PreparedLiquidationSurfaceCandidate",
    "SourceManifestLeaf",
    "TrainerAdmissionError",
    "TrainerAdmissionIntegrityError",
    "TrainerAdmissionSecurityContext",
    "TrainerAdmissionValidationError",
    "TrainerDecisionContext",
    "build_trainer_admission_security_context",
    "build_trainer_decision_context",
    "evaluate_liquidation_surface_trainer_admission",
    "prepare_liquidation_surface_candidate",
    "prepared_source_bundle_mapping",
    "publication_mapping_with_prepared_source_bundle",
    "reopen_prepared_source_bundle_from_publication",
]
