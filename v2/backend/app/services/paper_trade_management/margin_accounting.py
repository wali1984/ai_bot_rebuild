"""Authoritative account-wide margin accounting for the paper book.

The functions in this module are deterministic and side-effect free.  They
derive margin from executed notional and effective leverage; upstream margin
fields are evidence only and can never increase the paper account's buying
power.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any, TypeGuard

from .leverage_recommendation import symbol_leverage_ceiling

PAPER_MARGIN_ACCOUNTING_SCHEMA_VERSION = "paper_account_margin_v1"
PAPER_MARGIN_RESERVATION_BLOCK_REASON = "PAPER_ACCOUNT_MARGIN_RESERVATION_BLOCKED"
PAPER_INSUFFICIENT_FREE_MARGIN_REASON = "PAPER_INSUFFICIENT_FREE_MARGIN_AFTER_ADAPTIVE_BUFFER"
PAPER_EXISTING_MARGIN_INCOMPLETE_REASON = (
    "PAPER_EXISTING_OPEN_POSITION_MARGIN_ACCOUNTING_INCOMPLETE"
)
_BINANCE_USDM_BRACKET_SOURCE = "BINANCE_USDM_USER_DATA_GET_FAPI_V1_LEVERAGE_BRACKET"
_KNOWN_BINANCE_USDM_ENVIRONMENTS = frozenset({"mainnet", "testnet"})
_SHA256_HEX_CHARS = frozenset("0123456789abcdef")
_SAFE_BINDING_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_SAFE_ROW_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}$")
_PAPER_USDM_SYMBOL_RE = re.compile(r"^[A-Z0-9]{1,26}(?:USDT|USDC)$")
_AUTHORIZING_DECISION_CAP_SOURCES = frozenset(
    {
        "CURRENT_CAPITAL_DECISION_TIME_MAX_EFFECTIVE_LEVERAGE",
        "ALLOCATION_MODEL_INPUT_RISK_ENVELOPE_MAX_EFFECTIVE_LEVERAGE",
    }
)
_BRACKET_AUTHENTICATION_GAP_REASON = (
    "MAINTENANCE_BRACKET_HMAC_NOT_REVALIDATED_AT_PURE_ACCOUNTING_BOUNDARY"
)
PAPER_MARGIN_BUFFER_INVALID_REASON = "PAPER_MARGIN_BUFFER_INVALID_OR_OUT_OF_RANGE"
PAPER_MARGIN_RESERVATION_INPUT_INVALID_REASON = "PAPER_NEWLY_RESERVED_MARGIN_INVALID_OR_NEGATIVE"
PAPER_MARGIN_RESERVATION_INCLUSION_FLAG_INVALID_REASON = (
    "PAPER_MARGIN_RESERVATION_INCLUSION_FLAG_INVALID"
)
PAPER_OPEN_POSITION_COLLECTION_INVALID_REASON = "PAPER_OPEN_POSITION_COLLECTION_ROW_INVALID"
PAPER_CANDIDATE_COLLECTION_INVALID_REASON = "PAPER_CANDIDATE_COLLECTION_ROW_INVALID"
PAPER_MARGIN_COLLECTION_ITERATION_INVALID_REASON = "PAPER_MARGIN_COLLECTION_ITERATION_INVALID"
PAPER_MARGIN_DERIVED_VALUE_NONFINITE_REASON = "PAPER_MARGIN_DERIVED_VALUE_NONFINITE"
PAPER_MARGIN_MAPPING_SNAPSHOT_INVALID_REASON = "PAPER_MARGIN_MAPPING_SNAPSHOT_INVALID"
PAPER_MARGIN_ROW_IDENTITY_INVALID_REASON = "PAPER_MARGIN_ROW_IDENTITY_INVALID"
PAPER_DUPLICATE_OPEN_POSITION_IDENTITY_REASON = "PAPER_DUPLICATE_OPEN_POSITION_CANONICAL_IDENTITY"
PAPER_DUPLICATE_CANDIDATE_IDENTITY_REASON = "PAPER_DUPLICATE_CANDIDATE_CANONICAL_IDENTITY"
PAPER_CANDIDATE_OPEN_POSITION_IDENTITY_OVERLAP_REASON = (
    "PAPER_CANDIDATE_IDENTITY_OVERLAPS_EXISTING_OPEN_POSITION"
)
PAPER_MARGIN_UPSTREAM_INVALID_MARKER_REASON = "PAPER_MARGIN_UPSTREAM_INVALID_MARKER_PRESENT"
PAPER_MARGIN_ACCOUNTING_SCOPE_INVALID_REASON = "PAPER_MARGIN_ACCOUNTING_SCOPE_INVALID"
PAPER_MARGIN_FINAL_RESERVATION_RECONCILIATION_REASON = (
    "PAPER_MARGIN_FINAL_RESERVATION_RECONCILIATION_FAILED"
)
PAPER_INPUT_ROUTE_SAFETY_FLAG_INVALID_REASON = "PAPER_INPUT_ROUTE_SAFETY_FLAG_INVALID"
_PERSISTED_MAPPING_SNAPSHOT_INVALID_REASON_KEY = "_paper_margin_mapping_snapshot_invalid_reason"
_INTERNAL_MAPPING_SNAPSHOT_INVALID_SENTINEL = object()
_INTERNAL_MAPPING_SNAPSHOT_INVALID_REASON = (
    f"{PAPER_MARGIN_MAPPING_SNAPSHOT_INVALID_REASON}:"
    "INTERNAL_EXISTING_OPEN_POSITION_SNAPSHOT_FAILED"
)
_RESERVED_MAPPING_SNAPSHOT_MARKER_INJECTED_REASON = (
    f"{PAPER_MARGIN_MAPPING_SNAPSHOT_INVALID_REASON}:" "RESERVED_INTERNAL_SNAPSHOT_MARKER_INJECTED"
)
_KNOWN_SAFE_PRIOR_REASON_TOKENS = frozenset(
    {
        PAPER_CANDIDATE_COLLECTION_INVALID_REASON,
        PAPER_CANDIDATE_OPEN_POSITION_IDENTITY_OVERLAP_REASON,
        PAPER_DUPLICATE_CANDIDATE_IDENTITY_REASON,
        PAPER_DUPLICATE_OPEN_POSITION_IDENTITY_REASON,
        PAPER_EXISTING_MARGIN_INCOMPLETE_REASON,
        PAPER_INSUFFICIENT_FREE_MARGIN_REASON,
        PAPER_INPUT_ROUTE_SAFETY_FLAG_INVALID_REASON,
        PAPER_MARGIN_BUFFER_INVALID_REASON,
        PAPER_MARGIN_COLLECTION_ITERATION_INVALID_REASON,
        PAPER_MARGIN_DERIVED_VALUE_NONFINITE_REASON,
        PAPER_MARGIN_FINAL_RESERVATION_RECONCILIATION_REASON,
        PAPER_MARGIN_MAPPING_SNAPSHOT_INVALID_REASON,
        PAPER_MARGIN_RESERVATION_BLOCK_REASON,
        PAPER_MARGIN_RESERVATION_INCLUSION_FLAG_INVALID_REASON,
        PAPER_MARGIN_RESERVATION_INPUT_INVALID_REASON,
        PAPER_OPEN_POSITION_COLLECTION_INVALID_REASON,
    }
)
_KNOWN_UPSTREAM_INVALID_MARKERS = frozenset(
    {
        "EFFECTIVE_LEVERAGE_EVIDENCE_CONFLICT",
        "EFFECTIVE_LEVERAGE_EXCEEDS_DECISION_TIME_ENVELOPE",
        "EFFECTIVE_LEVERAGE_EXCEEDS_MAINTENANCE_BRACKET_MAX",
        "EFFECTIVE_LEVERAGE_EXCEEDS_OPERATOR_SYMBOL_CEILING",
        "EFFECTIVE_LEVERAGE_MISSING_AUTHORIZING_DECISION_TIME_CAP",
        "EFFECTIVE_LEVERAGE_MISSING_DECISION_TIME_CAP",
        "EFFECTIVE_LEVERAGE_SYMBOL_INVALID_OR_UNAUTHORIZED",
        "MAINTENANCE_BRACKET_STRUCTURAL_CAP_MISSING_OR_INVALID",
        PAPER_CANDIDATE_COLLECTION_INVALID_REASON,
        PAPER_EXISTING_MARGIN_INCOMPLETE_REASON,
        PAPER_MARGIN_COLLECTION_ITERATION_INVALID_REASON,
        PAPER_OPEN_POSITION_COLLECTION_INVALID_REASON,
    }
)
_ROW_IDENTITY_FIELDS = (
    "fill_id",
    "ledger_row_id",
    "paper_trade_id",
    "intent_id",
    "signal_id",
    "prediction_id",
    "source_prediction_id",
    "position_id",
)
_ROW_IDENTITY_FIELD_SET = frozenset(_ROW_IDENTITY_FIELDS)
# Only repository-defined structure names may appear in persisted snapshot
# failure paths.  An unrecognised caller key is represented by its ordinal so
# arbitrary key text cannot become error evidence.
_STRUCTURAL_SNAPSHOT_PATH_KEYS = frozenset(
    {
        *_ROW_IDENTITY_FIELD_SET,
        "adaptive_allocation",
        "allocation_input",
        "allocation_input_material",
        "bound_material",
        "fill_price",
        "current_capital_accounting",
        "final_authenticated_reread",
        "identity",
        "lineage_ids",
        "maintenance_bracket_contract",
        "maintenance_bracket_evidence",
        "model_inputs",
        "net_quantity",
        "paper_final_admission_contract",
        "paper_maintenance_margin_bracket_evidence",
        "quantity",
        "qty",
        "risk_envelope",
        "sizing",
    }
)


class _MappingSnapshotError(Exception):
    """A caller-owned mapping could not be copied into immutable read material."""

    def __init__(
        self,
        path: str,
        *,
        row_identity_invalid: bool = False,
        invalid_scalar_field: str | None = None,
    ) -> None:
        super().__init__(path)
        self.path = path
        self.row_identity_invalid = row_identity_invalid
        self.invalid_scalar_field = invalid_scalar_field


def _finite_float(value: Any) -> float | None:
    if type(value) is bool:
        return None
    try:
        parsed = float(value)
    except Exception:  # noqa: BLE001 - total untrusted scalar conversion boundary
        return None
    if not math.isfinite(parsed):
        return None
    return parsed


def _is_mapping_without_instance_metadata(value: Any) -> TypeGuard[Mapping[str, Any]]:
    """Recognize Mapping types without reading hostile instance ``__class__``."""

    value_type = type(value)
    if value_type is dict:
        return True
    try:
        return issubclass(value_type, Mapping)
    except Exception:  # noqa: BLE001 - hostile metaclass/ABC boundary
        return False


def _materialize_untrusted_iterable(
    value: Iterable[Any],
    *,
    path: str,
) -> tuple[list[Any], str | None]:
    """Read an outer caller-owned iterable without losing its safe prefix.

    A failure to create or advance the iterator is caller-input evidence, not
    an accounting implementation exception.  The returned reason is composed
    only from fixed tokens; exception text and attacker-controlled values are
    never persisted.
    """

    rows: list[Any] = []
    try:
        iterator = iter(value)
    except Exception:  # noqa: BLE001 - untrusted iterable boundary
        return rows, f"{PAPER_MARGIN_COLLECTION_ITERATION_INVALID_REASON}:{path}"
    while True:
        try:
            rows.append(next(iterator))
        except StopIteration:
            return rows, None
        except Exception:  # noqa: BLE001 - untrusted iterator boundary
            return rows, f"{PAPER_MARGIN_COLLECTION_ITERATION_INVALID_REASON}:{path}"


def _finite_sum_with_prefix(values: Iterable[float]) -> tuple[float, bool]:
    """Return a faithfully rounded finite sum and aggregation completeness."""

    materialized: list[float] = []
    for value in values:
        if not math.isfinite(value):
            prefix = math.fsum(materialized) if materialized else 0.0
            return prefix, False
        materialized.append(value)
    try:
        total = math.fsum(materialized)
    except OverflowError:
        # Preserve a finite, conservative diagnostic prefix.  The validity bit
        # prevents this number from controlling admission.
        prefix = 0.0
        for value in materialized:
            candidate = prefix + value
            if not math.isfinite(candidate):
                return prefix, False
            prefix = candidate
        return prefix, False  # pragma: no cover - defensive platform fallback
    if not math.isfinite(total):  # pragma: no cover - guarded by fsum contract
        return 0.0, False
    return total, True


def _snapshot_path(parent: str, key: str, *, ordinal: int) -> str:
    component = key if key in _STRUCTURAL_SNAPSHOT_PATH_KEYS else f"mapping_value[{ordinal}]"
    return f"{parent}.{component}"


def _snapshot_untrusted_value(
    value: Any,
    *,
    path: str,
    active_container_ids: set[int],
) -> Any:
    """Recursively snapshot caller-owned containers exactly once.

    Only container-read failures are translated to ``_MappingSnapshotError``.
    Errors in the accounting implementation itself remain visible as
    programmer errors instead of being hidden by a broad boundary catch.
    """

    if _is_mapping_without_instance_metadata(value):
        identity = id(value)
        if identity in active_container_ids:
            raise _MappingSnapshotError(f"{path}:CYCLIC_MAPPING")
        active_container_ids.add(identity)
        try:
            try:
                # Call ``items`` exactly once.  A hostile Mapping can return
                # duplicate pairs that ``dict`` would otherwise resolve with
                # unsafe last-write-wins semantics.
                items = list(value.items())
            except Exception as exc:  # noqa: BLE001 - untrusted Mapping read boundary
                raise _MappingSnapshotError(path) from exc
            validated_items: list[tuple[str, Any]] = []
            seen_keys: set[str] = set()
            try:
                for item in items:
                    if type(item) is not tuple or len(item) != 2:
                        raise _MappingSnapshotError(f"{path}:MALFORMED_MAPPING_ITEM")
                    key, nested_value = item
                    if type(key) is not str:
                        raise _MappingSnapshotError(f"{path}:MAPPING_KEY_INVALID")
                    if key in seen_keys:
                        raise _MappingSnapshotError(f"{path}:DUPLICATE_MAPPING_KEY")
                    seen_keys.add(key)
                    validated_items.append((key, nested_value))
            except _MappingSnapshotError:
                raise
            except Exception as exc:  # noqa: BLE001 - untrusted Mapping item boundary
                raise _MappingSnapshotError(f"{path}:MALFORMED_MAPPING_ITEM") from exc
            snapshot: dict[Any, Any] = {}
            try:
                for ordinal, (key, nested_value) in enumerate(validated_items):
                    try:
                        snapshot[key] = _snapshot_untrusted_value(
                            nested_value,
                            path=_snapshot_path(path, key, ordinal=ordinal),
                            active_container_ids=active_container_ids,
                        )
                    except _MappingSnapshotError as exc:
                        if key in _ROW_IDENTITY_FIELD_SET:
                            exc.row_identity_invalid = True
                        if key in {"net_quantity", "quantity", "qty", "fill_price"}:
                            exc.invalid_scalar_field = key
                        raise
            except _MappingSnapshotError:
                raise
            except Exception as exc:  # noqa: BLE001 - untrusted Mapping item boundary
                raise _MappingSnapshotError(path) from exc
            if (
                _PERSISTED_MAPPING_SNAPSHOT_INVALID_REASON_KEY in snapshot
                and snapshot[_PERSISTED_MAPPING_SNAPSHOT_INVALID_REASON_KEY]
                is not _INTERNAL_MAPPING_SNAPSHOT_INVALID_SENTINEL
            ):
                raise _MappingSnapshotError("RESERVED_INTERNAL_SNAPSHOT_MARKER_INJECTED")
            return snapshot
        finally:
            active_container_ids.remove(identity)
    if type(value) is list:
        identity = id(value)
        if identity in active_container_ids:
            raise _MappingSnapshotError(f"{path}:CYCLIC_LIST")
        active_container_ids.add(identity)
        try:
            try:
                return [
                    _snapshot_untrusted_value(
                        nested_value,
                        path=f"{path}[{index}]",
                        active_container_ids=active_container_ids,
                    )
                    for index, nested_value in enumerate(value)
                ]
            except _MappingSnapshotError:
                raise
            except Exception as exc:  # noqa: BLE001 - untrusted container read boundary
                raise _MappingSnapshotError(path) from exc
        finally:
            active_container_ids.remove(identity)
    if type(value) is tuple:
        identity = id(value)
        if identity in active_container_ids:
            raise _MappingSnapshotError(f"{path}:CYCLIC_TUPLE")
        active_container_ids.add(identity)
        try:
            try:
                return tuple(
                    _snapshot_untrusted_value(
                        nested_value,
                        path=f"{path}[{index}]",
                        active_container_ids=active_container_ids,
                    )
                    for index, nested_value in enumerate(value)
                )
            except _MappingSnapshotError:
                raise
            except Exception as exc:  # noqa: BLE001 - untrusted container read boundary
                raise _MappingSnapshotError(path) from exc
        finally:
            active_container_ids.remove(identity)
    if value is _INTERNAL_MAPPING_SNAPSHOT_INVALID_SENTINEL:
        return value
    if value is None or type(value) in {bool, int, str}:
        return value
    if type(value) is float and math.isfinite(value):
        return value
    raise _MappingSnapshotError(f"{path}:SCALAR_TYPE_INVALID")


def _snapshot_untrusted_mapping(value: Mapping[str, Any], *, path: str) -> dict[str, Any]:
    snapshot = _snapshot_untrusted_value(
        value,
        path=path,
        active_container_ids=set(),
    )
    if type(snapshot) is not dict:  # pragma: no cover - type invariant
        raise TypeError("mapping snapshot did not produce a dict")
    return snapshot


def _nested_mapping(row: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = row.get(key)
    return dict(value) if _is_mapping_without_instance_metadata(value) else {}


def _missing(value: Any) -> bool:
    return value is None or (type(value) is str and not value.strip())


def _is_lower_sha256_hex(value: Any) -> bool:
    return (
        type(value) is str and len(value) == 64 and all(char in _SHA256_HEX_CHARS for char in value)
    )


def _parse_aware_utc(value: Any) -> datetime | None:
    if type(value) is datetime:
        parsed = value
    elif type(value) is str and value.strip() == value and value:
        text = f"{value[:-1]}+00:00" if value.endswith("Z") else value
        try:
            parsed = datetime.fromisoformat(text)
        except (ValueError, OverflowError):
            return None
    else:
        return None
    try:
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return None
        return parsed.astimezone(UTC)
    except (OverflowError, ValueError):
        return None


def _valid_paper_usdm_symbol(value: Any) -> str | None:
    if type(value) is not str:
        return None
    if value != value.strip().upper() or not _PAPER_USDM_SYMBOL_RE.fullmatch(value):
        return None
    return value


def _safe_binding_identity(value: Any) -> bool:
    return type(value) is str and bool(_SAFE_BINDING_ID_RE.fullmatch(value))


def _credential_binding_matches_key(
    *,
    binding: Any,
    environment_id: Any,
    key_id: Any,
) -> bool:
    """Require ``environment:account:key`` to bind the separately named key."""

    binding_parts = binding.split(":") if type(binding) is str else []
    return bool(
        type(environment_id) is str
        and environment_id in _KNOWN_BINANCE_USDM_ENVIRONMENTS
        and len(binding_parts) == 3
        and binding_parts[0] == environment_id
        and all(_safe_binding_identity(part) for part in binding_parts[1:])
        and _safe_binding_identity(key_id)
        and binding_parts[2] == key_id
    )


def _canonical_sha256(value: Any) -> str | None:
    try:
        canonical = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError):
        return None
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _first_positive(*values: Any) -> float | None:
    for value in values:
        parsed = _finite_float(value)
        if parsed is not None and parsed > 0.0:
            return parsed
    return None


def _row_identity(
    row: Mapping[str, Any],
    *,
    accounting_scope: str = "CANDIDATE_ESTIMATE",
) -> tuple[str, str | None]:
    """Return a stable identity without leaking hostile scalar conversion text."""

    identity_fields = (
        ("position_id", *(key for key in _ROW_IDENTITY_FIELDS if key != "position_id"))
        if accounting_scope == "OPEN_EXECUTED_POSITION"
        else _ROW_IDENTITY_FIELDS
    )
    for key in identity_fields:
        if key not in row:
            continue
        value = row.get(key)
        if value is None:
            continue
        if type(value) is str and bool(_SAFE_ROW_ID_RE.fullmatch(value)):
            return value, None
        return "invalid_margin_row_identity", PAPER_MARGIN_ROW_IDENTITY_INVALID_REASON

    timeframe = row.get("timeframe")
    if timeframe is None or (isinstance(timeframe, str) and timeframe == ""):
        timeframe = row.get("thesis_timeframe")
    side = row.get("side")
    if side is None or (isinstance(side, str) and side == ""):
        side = row.get("action")
    components: list[str] = []
    for value, normalization in (
        (row.get("symbol"), "upper"),
        (timeframe, "identity"),
        (side, "lower"),
    ):
        if value is None or value == "":
            components.append("")
            continue
        if type(value) is not str or len(value) > 256:
            return "invalid_margin_row_identity", PAPER_MARGIN_ROW_IDENTITY_INVALID_REASON
        components.append(
            value.upper()
            if normalization == "upper"
            else value.lower()
            if normalization == "lower"
            else value
        )
    fallback = ":".join(components)
    if fallback == "::" or len(fallback) > 768:
        return "invalid_margin_row_identity", PAPER_MARGIN_ROW_IDENTITY_INVALID_REASON
    return fallback, None


def _canonical_identity_aliases(row: Mapping[str, Any]) -> set[str]:
    """Collect every exact bounded explicit ID for conservative overlap checks."""

    return {
        value
        for key in _ROW_IDENTITY_FIELDS
        if key in row
        and (value := row.get(key)) is not None
        and type(value) is str
        and bool(_SAFE_ROW_ID_RE.fullmatch(value))
    }


def _collision_identities(
    row: Mapping[str, Any],
    *,
    accounting_scope: str,
) -> set[str]:
    """Return all explicit aliases, or the canonical composite fallback."""

    aliases = _canonical_identity_aliases(row)
    if aliases:
        return aliases
    identity, invalid_reason = _row_identity(row, accounting_scope=accounting_scope)
    return {identity} if invalid_reason is None else set()


def _safe_prior_reason_tokens(value: Any) -> list[str]:
    """Return only bounded built-in reason codes without invoking caller magic."""

    if type(value) not in {list, tuple}:
        return []
    return [item for item in value if type(item) is str and item in _KNOWN_SAFE_PRIOR_REASON_TOKENS]


def _quantity_price_notional(
    row: Mapping[str, Any],
    quantity_price_pairs: tuple[tuple[str, tuple[str, ...]], ...],
) -> tuple[float | None, str | None, list[dict[str, Any]], list[str]]:
    invalid_reasons: list[str] = []
    quantity_values: dict[str, float] = {}
    price_values: dict[str, float] = {}
    quantity_keys = tuple(dict.fromkeys(pair[0] for pair in quantity_price_pairs))
    price_keys = tuple(
        dict.fromkeys(
            price_key
            for _, pair_price_keys in quantity_price_pairs
            for price_key in pair_price_keys
        )
    )
    for quantity_key in quantity_keys:
        if quantity_key not in row:
            continue
        raw_quantity = row.get(quantity_key)
        if raw_quantity is None:
            continue
        quantity = _finite_float(raw_quantity)
        if quantity is None or quantity <= 0.0:
            invalid_reasons.append(f"EXECUTED_QUANTITY_EVIDENCE_INVALID:{quantity_key}")
            continue
        quantity_values[quantity_key] = quantity
    for price_key in price_keys:
        if price_key not in row:
            continue
        raw_price = row.get(price_key)
        if raw_price is None:
            continue
        price = _finite_float(raw_price)
        if price is None or price <= 0.0:
            invalid_reasons.append(f"EXECUTED_PRICE_EVIDENCE_INVALID:{price_key}")
            continue
        price_values[price_key] = price

    evidence: list[dict[str, Any]] = []
    for quantity_key, quantity in quantity_values.items():
        for price_key, price in price_values.items():
            notional = abs(quantity * price)
            if not math.isfinite(notional) or notional <= 0.0:
                invalid_reasons.append(
                    f"EXECUTED_QUANTITY_PRICE_PRODUCT_INVALID:{quantity_key}:{price_key}"
                )
                continue
            evidence.append(
                {
                    "source": (f"ABS_{quantity_key.upper()}_TIMES_{price_key.upper()}"),
                    "value": notional,
                }
            )
    if not evidence:
        return None, None, [], list(dict.fromkeys(invalid_reasons))
    conservative = max(float(item["value"]) for item in evidence)
    if any(
        not math.isclose(
            float(item["value"]),
            conservative,
            rel_tol=1e-9,
            abs_tol=0.01,
        )
        for item in evidence
    ):
        invalid_reasons.append("EXECUTED_QUANTITY_PRICE_EVIDENCE_CONFLICT")
    binding_sources = [
        str(item["source"])
        for item in evidence
        if math.isclose(
            float(item["value"]),
            conservative,
            rel_tol=1e-12,
            abs_tol=1e-12,
        )
    ]
    source = (
        binding_sources[0] if len(evidence) == 1 else "RECONCILED_EXECUTED_QUANTITY_PRICE_EVIDENCE"
    )
    return conservative, source, evidence, list(dict.fromkeys(invalid_reasons))


def _open_position_executed_notional(
    row: Mapping[str, Any],
) -> tuple[float | None, str | None, list[dict[str, Any]], list[str]]:
    """Return notional only from executed open-position quantity and price.

    Target quantity, target notional, order size, and unscoped reported
    notional are proposal evidence. They must never establish used margin for
    an already-open position.
    """

    (
        quantity_notional,
        _quantity_source,
        quantity_evidence,
        quantity_invalid_reasons,
    ) = _quantity_price_notional(
        row,
        (
            ("net_quantity", ("avg_entry_price", "entry_price")),
            (
                "quantity",
                ("fill_price", "entry_price", "mark_price_at_fill", "mark_price"),
            ),
            ("qty", ("fill_price", "entry_price", "mark_price_at_fill", "mark_price")),
        ),
    )
    evidence: list[dict[str, Any]] = [
        {**item, "authority": "EXECUTED_QUANTITY_PRICE"} for item in quantity_evidence
    ]
    invalid_reasons: list[str] = [f"OPEN_{reason}" for reason in quantity_invalid_reasons]

    raw_current_capital = row.get("current_capital_accounting")
    if not _missing(raw_current_capital) and not isinstance(raw_current_capital, Mapping):
        invalid_reasons.append("OPEN_CURRENT_CAPITAL_ACCOUNTING_SHAPE_INVALID")
    current_capital = dict(raw_current_capital) if isinstance(raw_current_capital, Mapping) else {}
    current_scope_validated = (
        current_capital.get("accounting_scope")
        in {"CURRENT_EXECUTED_PAPER_POSITION", "CURRENT_EXECUTED_PAPER_FILL"}
        and current_capital.get("execution_notional_validated") is True
    )
    row_scope_validated = (
        row.get("accounting_scope")
        in {"CURRENT_EXECUTED_PAPER_POSITION", "CURRENT_EXECUTED_PAPER_FILL"}
        and row.get("execution_notional_validated") is True
    )
    current_values: list[float] = []
    row_values: list[float] = []
    for group_source, mapping, keys, scope_validated, collected_values in (
        (
            "CURRENT_CAPITAL_EXECUTED_NOTIONAL",
            current_capital,
            (
                "gross_notional_usd",
                "gross_notional",
                "notional",
                "notional_usd",
                "notional_usdt",
            ),
            current_scope_validated,
            current_values,
        ),
        (
            "ROW_EXECUTED_NOTIONAL",
            row,
            (
                "gross_notional_usd",
                "gross_notional",
                "notional",
                "notional_usd",
                "notional_usdt",
                "gross_notional_usd_upstream",
            ),
            row_scope_validated,
            row_values,
        ),
    ):
        for key in keys:
            raw = mapping.get(key)
            if _missing(raw):
                continue
            parsed = _finite_float(raw)
            if parsed is None or parsed <= 0.0:
                invalid_reasons.append(f"OPEN_EXECUTED_NOTIONAL_INVALID:{group_source}:{key}")
                continue
            collected_values.append(parsed)
            evidence.append(
                {
                    "source": f"{group_source}:{key}",
                    "value": parsed,
                    "authority": (
                        "VALIDATED_EXECUTED_NOTIONAL" if scope_validated else "RECONCILIATION_ONLY"
                    ),
                }
            )
    if quantity_notional is None and current_values and not current_scope_validated:
        invalid_reasons.append("OPEN_CURRENT_CAPITAL_EXECUTED_NOTIONAL_NOT_VALIDATED")
    if quantity_notional is None and row_values and not row_scope_validated:
        invalid_reasons.append("OPEN_ROW_EXECUTED_NOTIONAL_NOT_VALIDATED")
    values = [float(item["value"]) for item in evidence]
    if values:
        conservative = max(values)
        if any(
            not math.isclose(value, conservative, rel_tol=1e-9, abs_tol=0.01) for value in values
        ):
            invalid_reasons.append("OPEN_EXECUTED_NOTIONAL_EVIDENCE_CONFLICT")
        source = (
            str(evidence[0]["source"])
            if len(evidence) == 1
            else "RECONCILED_OPEN_EXECUTED_NOTIONAL_EVIDENCE"
        )
        return conservative, source, evidence, list(dict.fromkeys(invalid_reasons))
    return None, None, [], list(dict.fromkeys(invalid_reasons))


def _candidate_estimated_notional(
    row: Mapping[str, Any],
) -> tuple[float | None, str | None, list[dict[str, Any]], list[str]]:
    """Return executed fill notional or the maximum proposal estimate.

    Executed quantity times price is authoritative when it is present. Before
    execution, every populated proposal alias is retained and the maximum is
    used so a smaller upstream alias cannot manufacture paper buying power.
    """

    (
        executed_notional,
        _executed_source,
        executed_evidence,
        executed_invalid_reasons,
    ) = _quantity_price_notional(
        row,
        (
            ("net_quantity", ("avg_entry_price", "entry_price")),
            (
                "quantity",
                ("fill_price", "entry_price", "mark_price_at_fill", "mark_price", "price"),
            ),
            ("qty", ("fill_price", "entry_price", "mark_price", "price")),
        ),
    )
    invalid_reasons: list[str] = [f"CANDIDATE_{reason}" for reason in executed_invalid_reasons]
    raw_current_capital = row.get("current_capital_accounting")
    if not _missing(raw_current_capital) and not isinstance(raw_current_capital, Mapping):
        invalid_reasons.append("CANDIDATE_CURRENT_CAPITAL_ACCOUNTING_SHAPE_INVALID")
    current_capital = dict(raw_current_capital) if isinstance(raw_current_capital, Mapping) else {}
    raw_allocation = row.get("adaptive_allocation")
    if not _missing(raw_allocation) and not isinstance(raw_allocation, Mapping):
        invalid_reasons.append("CANDIDATE_ADAPTIVE_ALLOCATION_SHAPE_INVALID")
    allocation = dict(raw_allocation) if isinstance(raw_allocation, Mapping) else {}
    evidence: list[dict[str, Any]] = [
        {**item, "authority": "EXECUTED_QUANTITY_PRICE"} for item in executed_evidence
    ]

    target_quantity = row.get("target_quantity")
    if not _missing(target_quantity):
        quantity = _finite_float(target_quantity)
        price = _first_positive(row.get("fill_price"), row.get("entry_price"), row.get("price"))
        if quantity is None or quantity == 0.0 or price is None:
            invalid_reasons.append("CANDIDATE_TARGET_QUANTITY_PRICE_EVIDENCE_INVALID")
        else:
            target_notional = abs(quantity * price)
            if not math.isfinite(target_notional) or target_notional <= 0.0:
                invalid_reasons.append("CANDIDATE_TARGET_QUANTITY_PRICE_PRODUCT_INVALID")
            else:
                evidence.append(
                    {
                        "source": "ABS_TARGET_QUANTITY_TIMES_CANDIDATE_PRICE",
                        "value": target_notional,
                        "authority": "PROPOSAL_ESTIMATE",
                    }
                )

    for group_source, mapping, keys in (
        (
            "ADAPTIVE_ALLOCATION_NOTIONAL",
            allocation,
            (
                "gross_notional_usd",
                "target_notional_usd",
                "target_notional_usdt",
            ),
        ),
        (
            "CURRENT_CAPITAL_ACCOUNTING_NOTIONAL",
            current_capital,
            (
                "gross_notional_usd",
                "gross_notional",
                "notional",
                "notional_usd",
                "notional_usdt",
            ),
        ),
        (
            "REPORTED_EXECUTED_NOTIONAL_FALLBACK",
            row,
            (
                "gross_notional_usd",
                "gross_notional",
                "notional",
                "notional_usd",
                "notional_usdt",
                "order_size_usd",
                "target_notional_usd",
                "target_notional_usdt",
                "gross_notional_usd_upstream",
            ),
        ),
    ):
        for key in keys:
            raw = mapping.get(key)
            if _missing(raw):
                continue
            value = _finite_float(raw)
            if value is None or value <= 0.0:
                invalid_reasons.append(f"CANDIDATE_NOTIONAL_EVIDENCE_INVALID:{group_source}:{key}")
                continue
            evidence.append(
                {
                    "source": f"{group_source}:{key}",
                    "value": abs(value),
                    "authority": "PROPOSAL_ESTIMATE",
                }
            )
    final_contract = row.get("paper_final_admission_contract")
    if isinstance(final_contract, Mapping):
        bound_material = final_contract.get("bound_material")
        sizing = bound_material.get("sizing") if isinstance(bound_material, Mapping) else None
        sealed_notional = (
            _finite_float(sizing.get("notional")) if isinstance(sizing, Mapping) else None
        )
        if sealed_notional is None or sealed_notional <= 0.0:
            invalid_reasons.append("CANDIDATE_FINAL_ADMISSION_NOTIONAL_INVALID")
        else:
            evidence.append(
                {
                    "source": "FINAL_ADMISSION_BOUND_SIZING_NOTIONAL",
                    "value": sealed_notional,
                    "authority": "SEALED_PROPOSAL_ESTIMATE",
                }
            )
    if not evidence:
        return None, None, [], list(dict.fromkeys(invalid_reasons))
    conservative = max(float(item["value"]) for item in evidence)
    if executed_notional is not None and any(
        item["authority"] in {"PROPOSAL_ESTIMATE", "SEALED_PROPOSAL_ESTIMATE"}
        and not math.isclose(
            float(item["value"]),
            executed_notional,
            rel_tol=1e-9,
            abs_tol=0.01,
        )
        for item in evidence
    ):
        invalid_reasons.append("CANDIDATE_EXECUTED_AND_PROPOSAL_NOTIONAL_CONFLICT")
    binding = [
        str(item["source"])
        for item in evidence
        if math.isclose(float(item["value"]), conservative, rel_tol=1e-12, abs_tol=1e-12)
    ]
    source = binding[0] if len(evidence) == 1 else "CONSERVATIVE_MAX_CANDIDATE_NOTIONAL"
    return (
        conservative,
        source,
        evidence,
        list(dict.fromkeys(invalid_reasons)),
    )


def _decision_time_leverage_cap(
    row: Mapping[str, Any],
) -> dict[str, Any]:
    """Collect every decision-time cap and return their conservative minimum.

    A malformed populated container or scalar is retained as invalid evidence.
    It cannot be erased by another well-formed, less-conservative source.
    Different valid cap values are expected and are resolved with ``min``.
    """

    invalid_reasons: list[str] = []

    def nested(
        parent: Mapping[str, Any],
        key: str,
        *,
        path: str,
    ) -> Mapping[str, Any]:
        raw = parent.get(key)
        if _missing(raw):
            return {}
        if isinstance(raw, Mapping):
            return raw
        invalid_reasons.append(f"DECISION_TIME_LEVERAGE_CAP_SHAPE_INVALID:{path}")
        return {}

    allocation = nested(row, "adaptive_allocation", path="adaptive_allocation")
    current_capital = nested(
        row,
        "current_capital_accounting",
        path="current_capital_accounting",
    )
    model_inputs = nested(
        allocation,
        "model_inputs",
        path="adaptive_allocation.model_inputs",
    )
    risk_envelope = nested(
        model_inputs,
        "risk_envelope",
        path="adaptive_allocation.model_inputs.risk_envelope",
    )
    candidates = (
        (
            "CURRENT_CAPITAL_DECISION_TIME_MAX_EFFECTIVE_LEVERAGE",
            current_capital.get("decision_time_max_effective_leverage"),
        ),
        (
            "ALLOCATION_MODEL_INPUT_RISK_ENVELOPE_MAX_EFFECTIVE_LEVERAGE",
            risk_envelope.get("max_effective_leverage"),
        ),
        (
            "ROW_DECISION_TIME_MAX_EFFECTIVE_LEVERAGE",
            row.get("decision_time_max_effective_leverage"),
        ),
    )
    evidence: list[dict[str, Any]] = []
    for source, value in candidates:
        if _missing(value):
            continue
        parsed = _finite_float(value)
        if parsed is None or parsed < 1.0:
            invalid_reasons.append(f"DECISION_TIME_LEVERAGE_CAP_INVALID:{source}")
            continue
        evidence.append({"source": source, "value": parsed})

    conservative_cap = min(float(item["value"]) for item in evidence) if evidence else None
    binding_source = next(
        (str(item["source"]) for item in evidence if float(item["value"]) == conservative_cap),
        None,
    )
    authorizing_sources = [
        str(item["source"])
        for item in evidence
        if str(item["source"]) in _AUTHORIZING_DECISION_CAP_SOURCES
        and (
            str(item["source"]) != "CURRENT_CAPITAL_DECISION_TIME_MAX_EFFECTIVE_LEVERAGE"
            or (
                current_capital.get("accounting_scope")
                in {"CURRENT_EXECUTED_PAPER_POSITION", "CURRENT_EXECUTED_PAPER_FILL"}
                and current_capital.get("effective_leverage_validated") is True
            )
        )
    ]
    return {
        "decision_time_max_effective_leverage": conservative_cap,
        "leverage_cap_source": binding_source,
        "leverage_cap_sources": [str(item["source"]) for item in evidence],
        "decision_time_leverage_cap_evidence": evidence,
        "decision_time_leverage_cap_evidence_valid": not invalid_reasons,
        "decision_time_leverage_cap_invalid_reasons": invalid_reasons,
        "decision_time_leverage_cap_authorization_sources": authorizing_sources,
        "decision_time_leverage_cap_authorization_valid": bool(authorizing_sources),
        "row_projection_cap_can_only_lower": True,
    }


def _maintenance_bracket_leverage_cap(
    row: Mapping[str, Any],
    *,
    accounting_scope: str,
) -> dict[str, Any]:
    """Validate a prevalidated bracket's structural lower-only cap.

    The HMAC secret is intentionally unavailable here. Consequently this
    function never claims to authenticate the bracket and the bracket can
    never authorize leverage. It may only lower the independent allocator or
    validated-current-capital decision cap and the operator symbol ceiling.
    """

    raw_nested_evidence = row.get("maintenance_bracket_evidence")
    reasons: list[str] = []
    if isinstance(raw_nested_evidence, Mapping):
        nested_evidence = dict(raw_nested_evidence)
    else:
        nested_evidence = {}
        reasons.append("MAINTENANCE_BRACKET_NESTED_EVIDENCE_MISSING")

    prevalidated = row.get("maintenance_bracket_prevalidated") is True
    status = row.get("maintenance_bracket_evidence_status")
    if not prevalidated:
        reasons.append("MAINTENANCE_BRACKET_NOT_PREVALIDATED")
    if status != "READY":
        reasons.append("MAINTENANCE_BRACKET_EVIDENCE_STATUS_NOT_EXACT_READY")

    binding = row.get("maintenance_bracket_binding")
    account_binding = row.get("maintenance_bracket_account_binding_id")
    if not _missing(binding) and not _missing(account_binding) and binding != account_binding:
        reasons.append("MAINTENANCE_BRACKET_BINDING_ALIASES_CONFLICT")
    flat_binding = binding if not _missing(binding) else account_binding

    flat: dict[str, Any] = {
        "prevalidated": prevalidated,
        "bracket_id": row.get("maintenance_bracket_id"),
        "maint_margin_ratio": row.get("maintenance_bracket_maint_margin_ratio"),
        "cum": row.get("maintenance_bracket_cum"),
        "max_initial_leverage": row.get("maintenance_bracket_max_initial_leverage"),
        "evidence_hash": row.get("maintenance_bracket_evidence_hash"),
        "evidence_checksum_sha256": row.get("maintenance_bracket_evidence_checksum_sha256"),
        "evidence_hmac_sha256": row.get("maintenance_bracket_evidence_hmac_sha256"),
        "binding": flat_binding,
        "environment_id": row.get("maintenance_bracket_environment_id"),
        "key_id": row.get("maintenance_bracket_key_id"),
        "source": row.get("maintenance_bracket_source"),
        "available_at": row.get("maintenance_bracket_available_at"),
        "expires_at": row.get("maintenance_bracket_expires_at"),
        "consumer_observed_at": row.get("maintenance_bracket_consumer_observed_at"),
    }
    required_fields = (
        "bracket_id",
        "evidence_hash",
        "evidence_checksum_sha256",
        "evidence_hmac_sha256",
        "binding",
        "environment_id",
        "key_id",
        "source",
        "available_at",
        "expires_at",
        "consumer_observed_at",
    )
    for field in required_fields:
        if _missing(flat[field]):
            reasons.append(f"MAINTENANCE_BRACKET_BINDING_MISSING:{field}")

    for field in ("maint_margin_ratio", "cum", "max_initial_leverage"):
        flat_value = _finite_float(flat[field])
        nested_value = _finite_float(nested_evidence.get(field))
        if (
            flat_value is None
            or nested_value is None
            or not math.isclose(flat_value, nested_value, rel_tol=1e-12, abs_tol=1e-12)
        ):
            reasons.append(f"MAINTENANCE_BRACKET_NESTED_BINDING_MISMATCH:{field}")
    for field in required_fields:
        if nested_evidence.get(field) != flat[field]:
            reasons.append(f"MAINTENANCE_BRACKET_NESTED_BINDING_MISMATCH:{field}")
    if nested_evidence.get("prevalidated") is not True:
        reasons.append("MAINTENANCE_BRACKET_NESTED_PREVALIDATION_MISSING")

    ratio = _finite_float(flat["maint_margin_ratio"])
    cumulative = _finite_float(flat["cum"])
    maximum = _finite_float(flat["max_initial_leverage"])
    bracket_id = _finite_float(flat["bracket_id"])
    if (
        ratio is None
        or not 0.0 < ratio < 1.0
        or cumulative is None
        or cumulative < 0.0
        or maximum is None
        or maximum < 1.0
        or not maximum.is_integer()
        or bracket_id is None
        or bracket_id < 1.0
        or not bracket_id.is_integer()
    ):
        reasons.append("MAINTENANCE_BRACKET_NUMERIC_CONTRACT_INVALID")

    checksum = flat["evidence_checksum_sha256"]
    evidence_hash = flat["evidence_hash"]
    evidence_hmac = flat["evidence_hmac_sha256"]
    environment = flat["environment_id"]
    binding_text = flat["binding"]
    binding_valid = _credential_binding_matches_key(
        binding=binding_text,
        environment_id=environment,
        key_id=flat["key_id"],
    )
    if (
        not _is_lower_sha256_hex(checksum)
        or not _is_lower_sha256_hex(evidence_hmac)
        or evidence_hash != checksum
        or not binding_valid
        or flat["source"] != _BINANCE_USDM_BRACKET_SOURCE
    ):
        reasons.append("MAINTENANCE_BRACKET_PROVENANCE_STRUCTURE_INVALID")

    symbol = _valid_paper_usdm_symbol(row.get("symbol"))
    if symbol is None:
        reasons.append("MAINTENANCE_BRACKET_ROW_SYMBOL_INVALID")

    raw_context_sources: list[tuple[str, Any]] = [
        (
            "paper_maintenance_margin_bracket_evidence",
            row.get("paper_maintenance_margin_bracket_evidence"),
        )
    ]
    allocation_value = row.get("adaptive_allocation")
    if isinstance(allocation_value, Mapping):
        raw_context_sources.append(
            (
                "adaptive_allocation.paper_maintenance_margin_bracket_evidence",
                allocation_value.get("paper_maintenance_margin_bracket_evidence"),
            )
        )
    raw_contexts: list[tuple[str, Mapping[str, Any]]] = []
    raw_context_reasons: list[str] = []

    def raw_value_matches(observed: Any, expected: Any, *, numeric: bool) -> bool:
        if numeric:
            observed_number = _finite_float(observed)
            expected_number = _finite_float(expected)
            return (
                observed_number is not None
                and expected_number is not None
                and math.isclose(
                    observed_number,
                    expected_number,
                    rel_tol=1e-12,
                    abs_tol=1e-15,
                )
            )
        if isinstance(expected, bool):
            return observed is expected
        if type(observed) is not type(expected):
            return False
        try:
            return bool(observed == expected)
        except Exception:  # noqa: BLE001 - untrusted scalar comparison boundary
            return False

    raw_required_bindings = (
        ("prevalidated", prevalidated, False),
        ("status", status, False),
        ("evidence_usable", prevalidated and status == "READY", False),
        ("symbol", symbol, False),
        ("selected_bracket", flat["bracket_id"], True),
        ("maintenance_margin_rate", flat["maint_margin_ratio"], True),
        ("maintenance_margin_cum", flat["cum"], True),
        ("max_initial_leverage", flat["max_initial_leverage"], True),
        ("content_checksum_sha256", flat["evidence_checksum_sha256"], False),
        ("evidence_hmac_sha256", flat["evidence_hmac_sha256"], False),
        ("credential_binding_id", flat["binding"], False),
        ("exchange_environment", flat["environment_id"], False),
        ("evidence_auth_key_id", flat["key_id"], False),
        ("source", flat["source"], False),
        ("available_at", flat["available_at"], False),
        ("expires_at", flat["expires_at"], False),
        ("consumer_observed_at", flat["consumer_observed_at"], False),
    )
    raw_optional_alias_bindings = (
        ("bracket_id", flat["bracket_id"], True),
        ("maint_margin_ratio", flat["maint_margin_ratio"], True),
        ("cum", flat["cum"], True),
        ("evidence_hash", flat["evidence_checksum_sha256"], False),
        ("evidence_checksum_sha256", flat["evidence_checksum_sha256"], False),
        ("binding", flat["binding"], False),
        ("account_binding_id", flat["binding"], False),
        ("environment_id", flat["environment_id"], False),
        ("key_id", flat["key_id"], False),
    )
    for raw_source, raw_value in raw_context_sources:
        if _missing(raw_value):
            continue
        if not isinstance(raw_value, Mapping):
            raw_context_reasons.append(
                f"MAINTENANCE_BRACKET_RAW_CONTEXT_SHAPE_INVALID:{raw_source}"
            )
            continue
        raw_context = raw_value
        if not raw_context:
            raw_context_reasons.append(f"MAINTENANCE_BRACKET_RAW_CONTEXT_EMPTY:{raw_source}")
            continue
        raw_contexts.append((raw_source, raw_context))
        for raw_field, expected, numeric in raw_required_bindings:
            if raw_field not in raw_context or _missing(raw_context.get(raw_field)):
                raw_context_reasons.append(
                    f"MAINTENANCE_BRACKET_RAW_CONTEXT_BINDING_MISSING:{raw_source}:{raw_field}"
                )
            elif not raw_value_matches(
                raw_context.get(raw_field),
                expected,
                numeric=numeric,
            ):
                raw_context_reasons.append(
                    f"MAINTENANCE_BRACKET_RAW_CONTEXT_BINDING_MISMATCH:{raw_source}:{raw_field}"
                )
        for raw_field, expected, numeric in raw_optional_alias_bindings:
            if raw_field not in raw_context or _missing(raw_context.get(raw_field)):
                continue
            if not raw_value_matches(
                raw_context.get(raw_field),
                expected,
                numeric=numeric,
            ):
                raw_context_reasons.append(
                    f"MAINTENANCE_BRACKET_RAW_CONTEXT_BINDING_MISMATCH:{raw_source}:{raw_field}"
                )
    if len(raw_contexts) > 1:
        try:
            raw_context_copies_match = raw_contexts[0][1] == raw_contexts[1][1]
        except Exception:  # noqa: BLE001 - untrusted scalar comparison boundary
            raw_context_copies_match = False
        if not raw_context_copies_match:
            raw_context_reasons.append("MAINTENANCE_BRACKET_RAW_CONTEXT_COPIES_CONFLICT")
    reasons.extend(raw_context_reasons)

    bound_symbols: list[tuple[str, Any]] = []
    for evidence_container_name in (
        "maintenance_bracket_evidence",
        "paper_maintenance_margin_bracket_evidence",
    ):
        evidence_container = row.get(evidence_container_name)
        if not isinstance(evidence_container, Mapping):
            continue
        evidence_symbol = evidence_container.get("symbol")
        if _missing(evidence_symbol):
            reasons.append(f"MAINTENANCE_BRACKET_SYMBOL_BINDING_MISSING:{evidence_container_name}")
        else:
            bound_symbols.append((evidence_container_name, evidence_symbol))
    final_contract = row.get("paper_final_admission_contract")
    if isinstance(final_contract, Mapping):
        bound_material = final_contract.get("bound_material")
        if isinstance(bound_material, Mapping):
            maintenance_contract = bound_material.get("maintenance_bracket_contract")
            if isinstance(maintenance_contract, Mapping):
                final_reread = maintenance_contract.get("final_authenticated_reread")
                if isinstance(final_reread, Mapping) and not _missing(final_reread.get("symbol")):
                    bound_symbols.append(
                        (
                            "paper_final_admission_contract.final_authenticated_reread",
                            final_reread.get("symbol"),
                        )
                    )
    if not bound_symbols:
        reasons.append("MAINTENANCE_BRACKET_SYMBOL_BINDING_MISSING")
    for evidence_container_name, evidence_symbol in bound_symbols:
        if evidence_symbol != symbol:
            reasons.append(f"MAINTENANCE_BRACKET_SYMBOL_BINDING_MISMATCH:{evidence_container_name}")

    available = _parse_aware_utc(flat["available_at"])
    expires = _parse_aware_utc(flat["expires_at"])
    observed = _parse_aware_utc(flat["consumer_observed_at"])
    if available is None or expires is None or observed is None:
        reasons.append("MAINTENANCE_BRACKET_TIMESTAMP_INVALID_OR_NAIVE")
    elif not available <= observed < expires:
        reasons.append("MAINTENANCE_BRACKET_TIMESTAMP_ORDER_INVALID")

    if accounting_scope == "OPEN_EXECUTED_POSITION":
        reference_fields = (
            "maintenance_margin_mark_time",
            "last_mark_est",
            "position_reconstruction_generated_at",
        )
    else:
        reference_fields = (
            "paper_allocation_decision_time",
            "decision_time",
            "execution_time",
        )
    reference_source = None
    reference_time = None
    for field in reference_fields:
        if _missing(row.get(field)):
            continue
        reference_source = field
        reference_time = _parse_aware_utc(row.get(field))
        break
    if reference_source is None:
        reasons.append("MAINTENANCE_BRACKET_REFERENCE_TIME_MISSING")
    elif reference_time is None:
        reasons.append(f"MAINTENANCE_BRACKET_REFERENCE_TIME_INVALID:{reference_source}")
    elif available is not None and expires is not None and observed is not None:
        if accounting_scope == "OPEN_EXECUTED_POSITION":
            if not available <= observed <= reference_time < expires:
                reasons.append("MAINTENANCE_BRACKET_OPEN_POSITION_CLOCK_ORDER_INVALID")
        elif not available <= reference_time <= observed < expires:
            reasons.append("MAINTENANCE_BRACKET_CANDIDATE_CLOCK_ORDER_INVALID")

    structural_reasons = list(dict.fromkeys(reasons))
    structural_valid = not structural_reasons
    return {
        "maintenance_bracket_max_initial_leverage": maximum,
        "maintenance_bracket_max_leverage_source": (
            "STRUCTURALLY_BOUND_PREVALIDATED_BRACKET_LOWER_ONLY_MAX" if structural_valid else None
        ),
        "maintenance_bracket_structural_binding_valid": structural_valid,
        "maintenance_bracket_structural_binding_invalid_reasons": structural_reasons,
        "maintenance_bracket_raw_context_binding_valid": not raw_context_reasons,
        "maintenance_bracket_raw_context_binding_invalid_reasons": list(
            dict.fromkeys(raw_context_reasons)
        ),
        "maintenance_bracket_cap_usable": structural_valid,
        "maintenance_bracket_cap_effect": "LOWER_ONLY_NEVER_AUTHORIZES_LEVERAGE",
        "maintenance_bracket_authorizes_leverage": False,
        "maintenance_bracket_authentication_revalidated_here": False,
        "maintenance_bracket_authentication_gap_reasons": [_BRACKET_AUTHENTICATION_GAP_REASON],
        "maintenance_bracket_reference_time": (
            reference_time.isoformat().replace("+00:00", "Z")
            if reference_time is not None
            else None
        ),
        "maintenance_bracket_reference_time_source": reference_source,
        "maintenance_bracket_proof_required": False,
        "maintenance_bracket_proof_valid": False,
        "maintenance_bracket_proof_invalid_reasons": list(
            dict.fromkeys([*structural_reasons, _BRACKET_AUTHENTICATION_GAP_REASON])
        ),
    }


def _final_admission_leverage_authorization(
    row: Mapping[str, Any],
    *,
    requested_leverage: float,
    canonical_notional: float | None,
) -> dict[str, Any]:
    """Validate the sealed decision-time receipt that may authorize ``>1x``.

    This boundary cannot recompute the exchange HMAC because it deliberately
    has no credential access.  It can, however, replay the canonical receipt
    hashes and require the final admission contract to bind the exact current
    allocation, symbol, leverage, bracket fields, and upstream authenticated
    reread.  A plain allocation mapping is therefore evidence, never
    authorization.
    """

    reasons: list[str] = []
    contract_value = row.get("paper_final_admission_contract")
    if not isinstance(contract_value, Mapping):
        reasons.append("LEVERAGE_FINAL_ADMISSION_CONTRACT_MISSING")
        contract: Mapping[str, Any] = {}
    else:
        contract = dict(contract_value)

    receipt_hash = contract.get("receipt_hash")
    contract_material = dict(contract)
    contract_material.pop("receipt_hash", None)
    if (
        contract.get("schema_version") != "paper_final_admission_contract_v3"
        or contract.get("status") != "PASS"
        or contract.get("rejection_reasons") != []
        or row.get("paper_final_admission_status") != "PASS"
    ):
        reasons.append("LEVERAGE_FINAL_ADMISSION_STATUS_OR_SCHEMA_INVALID")
    if (
        not _is_lower_sha256_hex(receipt_hash)
        or receipt_hash != _canonical_sha256(contract_material)
        or receipt_hash != row.get("paper_final_admission_receipt_hash")
    ):
        reasons.append("LEVERAGE_FINAL_ADMISSION_RECEIPT_HASH_INVALID")

    bound_value = contract.get("bound_material")
    if not isinstance(bound_value, Mapping):
        reasons.append("LEVERAGE_FINAL_ADMISSION_BOUND_MATERIAL_MISSING")
        bound: Mapping[str, Any] = {}
    else:
        bound = dict(bound_value)
    bound_hash = contract.get("bound_material_hash")
    if (
        not bound
        or not _is_lower_sha256_hex(bound_hash)
        or bound_hash != _canonical_sha256(bound)
        or bound_hash != row.get("paper_final_admission_bound_material_hash")
    ):
        reasons.append("LEVERAGE_FINAL_ADMISSION_BOUND_MATERIAL_HASH_INVALID")

    symbol = _valid_paper_usdm_symbol(row.get("symbol"))
    identity = bound.get("identity")
    if symbol is None or not isinstance(identity, Mapping) or identity.get("symbol") != symbol:
        reasons.append("LEVERAGE_FINAL_ADMISSION_SYMBOL_BINDING_INVALID")

    allocation_value = row.get("adaptive_allocation")
    allocation = dict(allocation_value) if isinstance(allocation_value, Mapping) else {}
    allocation_hash = (
        _canonical_sha256(allocation_value) if isinstance(allocation_value, Mapping) else None
    )
    allocation_input_material_value = allocation.get("allocation_input_material")
    allocation_input_material = (
        dict(allocation_input_material_value)
        if isinstance(allocation_input_material_value, Mapping)
        else {}
    )
    allocation_input_value = allocation_input_material.get("allocation_input")
    allocation_input = (
        dict(allocation_input_value) if isinstance(allocation_input_value, Mapping) else {}
    )
    allocation_input_hash = allocation.get("allocation_input_hash")
    allocation_id = allocation.get("allocation_id")
    allocation_lineage = allocation.get("lineage_ids")
    allocation_input_lineage = allocation_input.get("lineage_ids")
    allocation_effective = _finite_float(allocation.get("effective_leverage"))
    if (
        allocation.get("allocation_input_schema_version") != "adaptive_capital_allocation_input_v1"
        or allocation.get("allocation_input_hash_algorithm") != "sha256(canonical-json-v1)"
        or allocation_input_material.get("schema_version") != "adaptive_capital_allocation_input_v1"
        or allocation_input_material.get("mode") != "paper"
        or not _is_lower_sha256_hex(allocation_input_hash)
        or allocation_input_hash != _canonical_sha256(allocation_input_material)
        or allocation_id != f"alloc_{str(allocation_input_hash)[:24]}"
        or allocation.get("allocator_decision") not in {"ALLOW_WITH_SIZE", "REDUCE_SIZE"}
        or allocation.get("symbol") != symbol
        or allocation_input.get("symbol") != symbol
        or not isinstance(allocation_lineage, Mapping)
        or not isinstance(allocation_input_lineage, Mapping)
        or dict(allocation_lineage) != dict(allocation_input_lineage)
        or allocation_effective is None
        or not math.isclose(
            allocation_effective,
            requested_leverage,
            rel_tol=1e-12,
            abs_tol=1e-12,
        )
        or allocation.get("paper_only") is not True
        or allocation.get("routes_to_live") is not False
        or allocation.get("places_real_order") is not False
    ):
        reasons.append("LEVERAGE_DECISION_TIME_ALLOCATION_IDENTITY_INVALID")
    allocator_contract = bound.get("allocator_contract")
    if (
        allocation_hash is None
        or bound.get("adaptive_allocation_hash") != allocation_hash
        or not isinstance(allocator_contract, Mapping)
        or allocator_contract.get("allocation_hash") != allocation_hash
        or allocator_contract.get("allocation_id") != allocation_id
        or allocator_contract.get("allocation_input_hash") != allocation_input_hash
        or allocator_contract.get("allocation_input_material") != allocation_input_material_value
        or not isinstance(identity, Mapping)
        or identity.get("allocation_id") != allocation_id
    ):
        reasons.append("LEVERAGE_FINAL_ADMISSION_ALLOCATION_BINDING_INVALID")

    sizing = bound.get("sizing")
    sealed_leverage = (
        _finite_float(sizing.get("effective_leverage")) if isinstance(sizing, Mapping) else None
    )
    sealed_notional = _finite_float(sizing.get("notional")) if isinstance(sizing, Mapping) else None
    if (
        sealed_leverage is None
        or sealed_leverage < 1.0
        or not math.isclose(
            sealed_leverage,
            requested_leverage,
            rel_tol=1e-12,
            abs_tol=1e-12,
        )
    ):
        reasons.append("LEVERAGE_FINAL_ADMISSION_SIZING_BINDING_INVALID")
    if sealed_notional is None or sealed_notional <= 0.0:
        reasons.append("LEVERAGE_FINAL_ADMISSION_SIZING_NOTIONAL_INVALID")
    elif canonical_notional is None or not math.isclose(
        sealed_notional,
        canonical_notional,
        rel_tol=1e-9,
        abs_tol=0.01,
    ):
        reasons.append("LEVERAGE_FINAL_ADMISSION_CANONICAL_NOTIONAL_MISMATCH")

    final_decision_raw = contract.get("final_decision_time")
    final_decision = _parse_aware_utc(final_decision_raw)
    validation_started = _parse_aware_utc(contract.get("validation_started_at"))
    if (
        final_decision is None
        or validation_started is None
        or validation_started > final_decision
        or row.get("paper_final_admission_decision_time") != final_decision_raw
        or bound.get("final_decision_time") != final_decision_raw
    ):
        reasons.append("LEVERAGE_FINAL_ADMISSION_CLOCK_BINDING_INVALID")

    bracket_value = bound.get("maintenance_bracket_contract")
    if not isinstance(bracket_value, Mapping):
        reasons.append("LEVERAGE_FINAL_ADMISSION_BRACKET_CONTRACT_MISSING")
        bracket_contract: Mapping[str, Any] = {}
    else:
        bracket_contract = dict(bracket_value)
    bracket_bindings = {
        "maintenance_bracket_id": "maintenance_bracket_id",
        "maintenance_bracket_maint_margin_ratio": ("maintenance_bracket_maint_margin_ratio"),
        "maintenance_bracket_cum": "maintenance_bracket_cum",
        "maintenance_bracket_max_initial_leverage": ("maintenance_bracket_max_initial_leverage"),
        "maintenance_bracket_evidence_checksum_sha256": (
            "maintenance_bracket_evidence_checksum_sha256"
        ),
        "maintenance_bracket_evidence_hmac_sha256": ("maintenance_bracket_evidence_hmac_sha256"),
        "maintenance_bracket_account_binding_id": ("maintenance_bracket_account_binding_id"),
        "maintenance_bracket_environment_id": "maintenance_bracket_environment_id",
        "maintenance_bracket_key_id": "maintenance_bracket_key_id",
        "maintenance_bracket_source": "maintenance_bracket_source",
        "maintenance_bracket_available_at": "maintenance_bracket_available_at",
        "maintenance_bracket_expires_at": "maintenance_bracket_expires_at",
        "maintenance_bracket_consumer_observed_at": ("maintenance_bracket_consumer_observed_at"),
    }
    if any(
        bracket_contract.get(contract_field) != row.get(row_field)
        for contract_field, row_field in bracket_bindings.items()
    ):
        reasons.append("LEVERAGE_FINAL_ADMISSION_BRACKET_BINDING_INVALID")

    reread_value = bracket_contract.get("final_authenticated_reread")
    if not isinstance(reread_value, Mapping):
        reasons.append("LEVERAGE_FINAL_ADMISSION_AUTHENTICATED_REREAD_MISSING")
        reread: Mapping[str, Any] = {}
    else:
        reread = dict(reread_value)
    expected_reread_bindings = {
        "symbol": symbol,
        "content_checksum_sha256": row.get("maintenance_bracket_evidence_checksum_sha256"),
        "evidence_hmac_sha256": row.get("maintenance_bracket_evidence_hmac_sha256"),
        "credential_binding_id": row.get("maintenance_bracket_account_binding_id"),
        "exchange_environment": row.get("maintenance_bracket_environment_id"),
        "evidence_auth_key_id": row.get("maintenance_bracket_key_id"),
        "source": row.get("maintenance_bracket_source"),
        "available_at": row.get("maintenance_bracket_available_at"),
        "expires_at": row.get("maintenance_bracket_expires_at"),
        "selected_bracket": row.get("maintenance_bracket_id"),
    }
    reread_credential_binding_valid = _credential_binding_matches_key(
        binding=reread.get("credential_binding_id"),
        environment_id=reread.get("exchange_environment"),
        key_id=reread.get("evidence_auth_key_id"),
    )
    if (
        reread.get("status") != "READY"
        or reread.get("evidence_usable") is not True
        or reread.get("candidate_notional_contract")
        != "TOTAL_ABSOLUTE_SYMBOL_POSITION_NOTIONAL_AFTER_CANDIDATE_FILL"
        or reread.get("places_real_order") is not False
        or reread.get("leverage_mutated") is not False
        or reread.get("margin_mutated") is not False
        or not reread_credential_binding_valid
        or any(
            reread.get(field) != expected for field, expected in expected_reread_bindings.items()
        )
    ):
        reasons.append("LEVERAGE_FINAL_ADMISSION_AUTHENTICATED_REREAD_BINDING_INVALID")
    reread_candidate_notional = _finite_float(reread.get("candidate_notional"))
    if (
        reread_candidate_notional is None
        or reread_candidate_notional <= 0.0
        or sealed_notional is None
        or not math.isclose(
            reread_candidate_notional,
            sealed_notional,
            rel_tol=1e-9,
            abs_tol=0.01,
        )
        or canonical_notional is None
        or not math.isclose(
            reread_candidate_notional,
            canonical_notional,
            rel_tol=1e-9,
            abs_tol=0.01,
        )
    ):
        reasons.append("LEVERAGE_FINAL_ADMISSION_AUTHENTICATED_REREAD_NOTIONAL_MISMATCH")
    for reread_field, row_field in (
        ("maintenance_margin_rate", "maintenance_bracket_maint_margin_ratio"),
        ("maintenance_margin_cum", "maintenance_bracket_cum"),
        ("max_initial_leverage", "maintenance_bracket_max_initial_leverage"),
    ):
        reread_number = _finite_float(reread.get(reread_field))
        row_number = _finite_float(row.get(row_field))
        if (
            reread_number is None
            or row_number is None
            or not math.isclose(
                reread_number,
                row_number,
                rel_tol=1e-12,
                abs_tol=1e-15,
            )
        ):
            reasons.append(
                f"LEVERAGE_FINAL_ADMISSION_AUTHENTICATED_REREAD_NUMERIC_MISMATCH:{reread_field}"
            )

    if contract.get("maintenance_bracket_revalidation") != reread_value:
        reasons.append("LEVERAGE_FINAL_ADMISSION_REREAD_RECEIPT_MISMATCH")
    available = _parse_aware_utc(row.get("maintenance_bracket_available_at"))
    allocation_decision = _parse_aware_utc(row.get("paper_allocation_decision_time"))
    reread_decision = _parse_aware_utc(reread.get("decision_time"))
    original_observed = _parse_aware_utc(row.get("maintenance_bracket_consumer_observed_at"))
    reread_observed = _parse_aware_utc(reread.get("consumer_observed_at"))
    reread_checked = _parse_aware_utc(reread.get("current_checked_at"))
    expires = _parse_aware_utc(row.get("maintenance_bracket_expires_at"))
    if (
        available is None
        or allocation_decision is None
        or reread_decision is None
        or reread_decision != allocation_decision
        or original_observed is None
        or reread_observed is None
        or reread_checked is None
        or final_decision is None
        or expires is None
        or not (
            available
            <= allocation_decision
            <= original_observed
            <= reread_observed
            <= reread_checked
            <= final_decision
            < expires
        )
    ):
        reasons.append("LEVERAGE_FINAL_ADMISSION_AUTHENTICATED_REREAD_CLOCK_INVALID")

    invalid_reasons = list(dict.fromkeys(reasons))
    return {
        "final_admission_leverage_authorization_required": requested_leverage > 1.0,
        "final_admission_leverage_authorization_valid": not invalid_reasons,
        "final_admission_leverage_authorization_invalid_reasons": invalid_reasons,
        "final_admission_receipt_hash": receipt_hash,
        "final_admission_bound_material_hash": bound_hash,
        "final_admission_allocation_hash": allocation_hash,
        "final_admission_upstream_authenticated_bracket_reread_attested": (not invalid_reasons),
        "final_admission_bracket_hmac_revalidated_here": False,
        "final_admission_bracket_hmac_revalidation_gap_reason": (
            _BRACKET_AUTHENTICATION_GAP_REASON
        ),
    }


def _effective_leverage(
    row: Mapping[str, Any],
    *,
    accounting_scope: str,
    canonical_notional: float | None,
) -> dict[str, Any]:
    allocation = _nested_mapping(row, "adaptive_allocation")
    current_capital = _nested_mapping(row, "current_capital_accounting")

    evidence: list[dict[str, Any]] = []
    evidence_invalid_reasons: list[str] = []
    current_capital_claim_validated = (
        current_capital.get("accounting_scope")
        in {"CURRENT_EXECUTED_PAPER_POSITION", "CURRENT_EXECUTED_PAPER_FILL"}
        and current_capital.get("effective_leverage_validated") is True
    )
    allocation_claim_present = not _missing(allocation.get("effective_leverage"))
    current_claim_present = current_capital_claim_validated and not _missing(
        current_capital.get("effective_leverage")
    )
    row_claim_present = not _missing(row.get("effective_leverage")) and (
        row.get("effective_leverage_validated") is True
        or allocation_claim_present
        or current_claim_present
    )
    for source, raw, present in (
        (
            "VALIDATED_CURRENT_CAPITAL_EFFECTIVE_LEVERAGE",
            current_capital.get("effective_leverage"),
            current_claim_present,
        ),
        (
            "ALLOCATION_EFFECTIVE_LEVERAGE",
            allocation.get("effective_leverage"),
            allocation_claim_present,
        ),
        (
            "VALIDATED_ROW_EFFECTIVE_LEVERAGE",
            row.get("effective_leverage"),
            row_claim_present,
        ),
    ):
        if not present:
            continue
        parsed = _finite_float(raw)
        if parsed is None or parsed < 1.0:
            evidence_invalid_reasons.append(f"EFFECTIVE_LEVERAGE_INVALID:{source}")
            continue
        evidence.append({"source": source, "value": parsed})

    requested_leverage = 1.0
    requested_source = "FAIL_SAFE_DEFAULT_1X"
    if evidence:
        values = [float(item["value"]) for item in evidence]
        requested_leverage = min(values)
        binding_sources = [
            str(item["source"])
            for item in evidence
            if math.isclose(
                float(item["value"]),
                requested_leverage,
                rel_tol=1e-12,
                abs_tol=1e-12,
            )
        ]
        requested_source = binding_sources[0]
        if any(
            not math.isclose(
                value,
                requested_leverage,
                rel_tol=1e-9,
                abs_tol=1e-9,
            )
            for value in values
        ):
            evidence_invalid_reasons.append("EFFECTIVE_LEVERAGE_EVIDENCE_CONFLICT")

    authorization = _final_admission_leverage_authorization(
        row,
        requested_leverage=requested_leverage,
        canonical_notional=canonical_notional,
    )
    leverage = requested_leverage
    source = requested_source
    authorization_downgrade_reasons: list[str] = []
    if (
        requested_leverage > 1.0
        and authorization["final_admission_leverage_authorization_valid"] is not True
    ):
        leverage = 1.0
        source = "FAIL_SAFE_DEFAULT_1X_UNAUTHENTICATED_LEVERAGE_CLAIM"
        authorization_downgrade_reasons.extend(
            authorization["final_admission_leverage_authorization_invalid_reasons"]
        )

    cap_evidence = _decision_time_leverage_cap(row)
    leverage_cap = cap_evidence["decision_time_max_effective_leverage"]
    symbol = _valid_paper_usdm_symbol(row.get("symbol"))
    authorized_symbol_ceiling = float(symbol_leverage_ceiling(symbol)) if symbol else None
    bracket_evidence = _maintenance_bracket_leverage_cap(
        row,
        accounting_scope=accounting_scope,
    )
    invalid_reasons = list(evidence_invalid_reasons)
    bracket_evidence["maintenance_bracket_proof_required"] = requested_leverage > 1.0
    cap_invalid_reasons = cap_evidence["decision_time_leverage_cap_invalid_reasons"]
    if requested_leverage > 1.0 and cap_invalid_reasons:
        invalid_reasons.extend(cap_invalid_reasons)
    if symbol is None:
        invalid_reasons.append("EFFECTIVE_LEVERAGE_SYMBOL_INVALID_OR_UNAUTHORIZED")

    authorization_valid = authorization["final_admission_leverage_authorization_valid"] is True
    if requested_leverage > 1.0 and authorization_valid:
        if cap_invalid_reasons:
            pass
        elif leverage_cap is None:
            invalid_reasons.append("EFFECTIVE_LEVERAGE_MISSING_DECISION_TIME_CAP")
        elif requested_leverage > float(leverage_cap) + 1e-9:
            invalid_reasons.append("EFFECTIVE_LEVERAGE_EXCEEDS_DECISION_TIME_ENVELOPE")
        if cap_evidence["decision_time_leverage_cap_authorization_valid"] is not True:
            invalid_reasons.append("EFFECTIVE_LEVERAGE_MISSING_AUTHORIZING_DECISION_TIME_CAP")
        if (
            authorized_symbol_ceiling is not None
            and requested_leverage > authorized_symbol_ceiling + 1e-9
        ):
            invalid_reasons.append("EFFECTIVE_LEVERAGE_EXCEEDS_OPERATOR_SYMBOL_CEILING")
        if bracket_evidence["maintenance_bracket_cap_usable"] is not True:
            invalid_reasons.append("MAINTENANCE_BRACKET_STRUCTURAL_CAP_MISSING_OR_INVALID")
        else:
            bracket_cap = bracket_evidence["maintenance_bracket_max_initial_leverage"]
            if bracket_cap is None or requested_leverage > float(bracket_cap) + 1e-9:
                invalid_reasons.append("EFFECTIVE_LEVERAGE_EXCEEDS_MAINTENANCE_BRACKET_MAX")
    elif requested_leverage > 1.0:
        # A missing receipt safely downgrades an otherwise well-formed claim
        # to 1x.  Populated malformed bracket evidence still fails closed so
        # corruption cannot be erased by the downgrade itself.
        bracket_claim_present = any(
            not _missing(row.get(field))
            for field in (
                "maintenance_bracket_evidence",
                "paper_maintenance_margin_bracket_evidence",
                "maintenance_bracket_prevalidated",
                "maintenance_bracket_evidence_status",
                "paper_final_admission_contract",
            )
        )
        if (
            bracket_claim_present
            and bracket_evidence["maintenance_bracket_structural_binding_valid"] is not True
        ):
            invalid_reasons.append("MAINTENANCE_BRACKET_STRUCTURAL_CAP_MISSING_OR_INVALID")
    invalid_reasons = list(dict.fromkeys(invalid_reasons))

    return {
        "effective_leverage": leverage,
        "leverage_source": source,
        "requested_effective_leverage": requested_leverage,
        "requested_effective_leverage_source": requested_source,
        "unauthenticated_leverage_claim_downgraded_to_one_x": (
            requested_leverage > 1.0 and leverage == 1.0
        ),
        "leverage_authorization_downgrade_reasons": list(
            dict.fromkeys(authorization_downgrade_reasons)
        ),
        "effective_leverage_evidence": evidence,
        "effective_leverage_evidence_consistent": not evidence_invalid_reasons,
        "effective_leverage_evidence_invalid_reasons": list(
            dict.fromkeys(evidence_invalid_reasons)
        ),
        **cap_evidence,
        **authorization,
        "operator_authorized_symbol_leverage_ceiling": authorized_symbol_ceiling,
        "symbol_leverage_ceiling_source": (
            "IMMUTABLE_OPERATOR_AUTHORIZED_SYMBOL_CEILING"
            if authorized_symbol_ceiling is not None
            else None
        ),
        **bracket_evidence,
        "leverage_valid": not invalid_reasons,
        "leverage_invalid_reason": invalid_reasons[0] if invalid_reasons else None,
        "leverage_invalid_reasons": invalid_reasons,
    }


def _maintenance_margin_evidence(
    row: Mapping[str, Any],
    *,
    bracket_ratio: float | None,
    bracket_structural_valid: bool,
) -> dict[str, Any]:
    allocation = _nested_mapping(row, "adaptive_allocation")
    current_capital = _nested_mapping(row, "current_capital_accounting")
    model_inputs = _nested_mapping(allocation, "model_inputs")
    evidence: list[dict[str, Any]] = []
    invalid_reasons: list[str] = []
    for source, value in (
        (
            "CURRENT_CAPITAL_MAINTENANCE_MARGIN_RATE",
            current_capital.get("maintenance_margin_rate"),
        ),
        ("POSITION_MAINTENANCE_MARGIN_RATE", row.get("maintenance_margin_rate")),
        (
            "ALLOCATION_MODEL_INPUT_MAINTENANCE_MARGIN_RATE",
            model_inputs.get("maintenance_margin_rate"),
        ),
        (
            "ALLOCATION_MAINTENANCE_MARGIN_RATE",
            allocation.get("maintenance_margin_rate"),
        ),
    ):
        if _missing(value):
            continue
        parsed = _finite_float(value)
        if parsed is None or not 0.0 < parsed < 1.0:
            invalid_reasons.append(f"MAINTENANCE_MARGIN_RATE_INVALID:{source}")
            continue
        evidence.append({"source": source, "value": parsed})
    selected = max((float(item["value"]) for item in evidence), default=None)
    if selected is not None and any(
        not math.isclose(float(item["value"]), selected, rel_tol=1e-12, abs_tol=1e-12)
        for item in evidence
    ):
        invalid_reasons.append("MAINTENANCE_MARGIN_RATE_EVIDENCE_CONFLICT")
    if (
        bracket_structural_valid
        and bracket_ratio is not None
        and selected is not None
        and not math.isclose(selected, bracket_ratio, rel_tol=1e-12, abs_tol=1e-12)
    ):
        invalid_reasons.append("MAINTENANCE_MARGIN_RATE_CONFLICTS_WITH_BRACKET")
    if not evidence:
        invalid_reasons.append("MAINTENANCE_MARGIN_RATE_MISSING_OR_INVALID")
    invalid_reasons = list(dict.fromkeys(invalid_reasons))
    binding_source = next(
        (
            str(item["source"])
            for item in evidence
            if selected is not None
            and math.isclose(float(item["value"]), selected, rel_tol=1e-12, abs_tol=1e-12)
        ),
        None,
    )
    return {
        "maintenance_margin_rate": selected,
        "maintenance_margin_rate_source": binding_source,
        "maintenance_margin_rate_evidence": evidence,
        "maintenance_margin_evidence_valid": not invalid_reasons,
        "maintenance_margin_evidence_invalid_reasons": invalid_reasons,
    }


def _paper_route_safety_evidence(row: Mapping[str, Any]) -> dict[str, Any]:
    """Reconcile every populated paper/live safety flag across trusted row views."""

    containers: list[tuple[str, Mapping[str, Any]]] = [("row", row)]
    for container_name in ("adaptive_allocation", "current_capital_accounting"):
        container = row.get(container_name)
        if isinstance(container, Mapping):
            containers.append((container_name, container))

    evidence: list[dict[str, Any]] = []
    invalid_reasons: list[str] = []
    for container_name, container in containers:
        for field, expected in (
            ("paper_only", True),
            ("routes_to_live", False),
            ("places_real_order", False),
        ):
            if field not in container:
                continue
            observed = container.get(field)
            valid = observed is expected
            evidence.append(
                {
                    "source": f"{container_name}.{field}",
                    "value": observed if type(observed) is bool else "INVALID_NON_BOOLEAN_FLAG",
                    "expected": expected,
                    "valid": valid,
                }
            )
            if not valid:
                reason_source = field if container_name == "row" else f"{container_name}.{field}"
                invalid_reasons.append(
                    f"{PAPER_INPUT_ROUTE_SAFETY_FLAG_INVALID_REASON}:{reason_source}"
                )
    return {
        "paper_input_route_safety_flag_evidence": evidence,
        "paper_input_route_safety_flags_valid": not invalid_reasons,
        "paper_input_route_safety_flag_invalid_reasons": list(dict.fromkeys(invalid_reasons)),
    }


def canonical_margin_requirement(
    row: Mapping[str, Any],
    *,
    accounting_scope: str = "CANDIDATE_ESTIMATE",
) -> dict[str, Any]:
    """Derive canonical margin without confusing proposals with execution."""

    accounting_scope_valid = type(accounting_scope) is str and accounting_scope in {
        "CANDIDATE_ESTIMATE",
        "OPEN_EXECUTED_POSITION",
    }
    if not accounting_scope_valid:
        accounting_scope = "INVALID_ACCOUNTING_SCOPE"
    mapping_snapshot_invalid_reason = None
    mapping_snapshot_invalid_scalar_field = None
    if not _is_mapping_without_instance_metadata(row):
        mapping_snapshot_invalid_reason = (
            f"{PAPER_MARGIN_MAPPING_SNAPSHOT_INVALID_REASON}:margin_row:NOT_A_MAPPING"
        )
        row = {"fill_id": "invalid_margin_mapping_snapshot"}
    else:
        try:
            row = _snapshot_untrusted_mapping(row, path="margin_row")
        except _MappingSnapshotError as exc:
            mapping_snapshot_invalid_reason = (
                f"{PAPER_MARGIN_MAPPING_SNAPSHOT_INVALID_REASON}:{exc.path}"
            )
            mapping_snapshot_invalid_scalar_field = exc.invalid_scalar_field
            row = {
                "fill_id": (
                    _INTERNAL_MAPPING_SNAPSHOT_INVALID_SENTINEL
                    if exc.row_identity_invalid
                    else "invalid_margin_mapping_snapshot"
                )
            }
    if _PERSISTED_MAPPING_SNAPSHOT_INVALID_REASON_KEY in row:
        persisted_snapshot_marker = row.pop(_PERSISTED_MAPPING_SNAPSHOT_INVALID_REASON_KEY)
        mapping_snapshot_invalid_reason = (
            _INTERNAL_MAPPING_SNAPSHOT_INVALID_REASON
            if persisted_snapshot_marker is _INTERNAL_MAPPING_SNAPSHOT_INVALID_SENTINEL
            else _RESERVED_MAPPING_SNAPSHOT_MARKER_INJECTED_REASON
        )
    row_id, row_identity_invalid_reason = _row_identity(
        row,
        accounting_scope=accounting_scope,
    )
    notional_evidence: list[dict[str, Any]] = []
    notional_invalid_reasons: list[str] = []
    if accounting_scope == "OPEN_EXECUTED_POSITION":
        (
            notional,
            notional_source,
            notional_evidence,
            notional_invalid_reasons,
        ) = _open_position_executed_notional(row)
    else:
        (
            notional,
            notional_source,
            notional_evidence,
            notional_invalid_reasons,
        ) = _candidate_estimated_notional(row)
    leverage_evidence = _effective_leverage(
        row,
        accounting_scope=accounting_scope,
        canonical_notional=notional,
    )
    leverage = float(leverage_evidence["effective_leverage"])
    bracket_ratio = _finite_float(row.get("maintenance_bracket_maint_margin_ratio"))
    maintenance_evidence = _maintenance_margin_evidence(
        row,
        bracket_ratio=bracket_ratio,
        bracket_structural_valid=(
            leverage_evidence["maintenance_bracket_structural_binding_valid"] is True
        ),
    )
    invalid_reasons: list[str] = list(notional_invalid_reasons)
    if not accounting_scope_valid:
        invalid_reasons.append(PAPER_MARGIN_ACCOUNTING_SCOPE_INVALID_REASON)
    if mapping_snapshot_invalid_scalar_field in {"net_quantity", "quantity", "qty"}:
        invalid_reasons.append(
            (
                "OPEN_EXECUTED_QUANTITY_EVIDENCE_INVALID:"
                if accounting_scope == "OPEN_EXECUTED_POSITION"
                else "CANDIDATE_EXECUTED_QUANTITY_EVIDENCE_INVALID:"
            )
            + mapping_snapshot_invalid_scalar_field
        )
    elif mapping_snapshot_invalid_scalar_field == "fill_price":
        invalid_reasons.append(
            (
                "OPEN_EXECUTED_PRICE_EVIDENCE_INVALID:"
                if accounting_scope == "OPEN_EXECUTED_POSITION"
                else "CANDIDATE_EXECUTED_PRICE_EVIDENCE_INVALID:"
            )
            + mapping_snapshot_invalid_scalar_field
        )
    if row_identity_invalid_reason is not None:
        invalid_reasons.append(row_identity_invalid_reason)
    if _valid_paper_usdm_symbol(row.get("symbol")) is None:
        invalid_reasons.append("PAPER_SYMBOL_INVALID_OR_UNAUTHORIZED")
    if notional is None or notional <= 0.0:
        invalid_reasons.append(
            "OPEN_EXECUTED_NOTIONAL_MISSING_OR_NON_POSITIVE"
            if accounting_scope == "OPEN_EXECUTED_POSITION"
            else "CANDIDATE_NOTIONAL_MISSING_OR_NON_POSITIVE"
        )
    if leverage_evidence["leverage_valid"] is not True:
        invalid_reasons.extend(leverage_evidence["leverage_invalid_reasons"])
    if maintenance_evidence["maintenance_margin_evidence_valid"] is not True:
        invalid_reasons.extend(maintenance_evidence["maintenance_margin_evidence_invalid_reasons"])
    route_safety_evidence = _paper_route_safety_evidence(row)
    route_safety_invalid_reasons = route_safety_evidence[
        "paper_input_route_safety_flag_invalid_reasons"
    ]
    invalid_reasons.extend(route_safety_invalid_reasons)
    if mapping_snapshot_invalid_reason is not None:
        invalid_reasons.append(mapping_snapshot_invalid_reason)
    invalid_marker = row.get("paper_margin_accounting_invalid_reason")
    if invalid_marker not in (None, ""):
        if type(invalid_marker) is str and invalid_marker in _KNOWN_UPSTREAM_INVALID_MARKERS:
            invalid_reasons.append(invalid_marker)
        else:
            invalid_reasons.append(PAPER_MARGIN_UPSTREAM_INVALID_MARKER_REASON)
    invalid_reasons = list(dict.fromkeys(invalid_reasons))
    margin = None
    if not invalid_reasons and notional is not None:
        derived_margin = notional / leverage
        if not math.isfinite(derived_margin) or derived_margin <= 0.0:
            invalid_reasons.append(PAPER_MARGIN_DERIVED_VALUE_NONFINITE_REASON)
        else:
            margin = derived_margin
    invalid_reasons = list(dict.fromkeys(invalid_reasons))
    valid = not invalid_reasons
    reported_margin = _finite_float(row.get("allocated_margin_usd"))
    validated_symbol = _valid_paper_usdm_symbol(row.get("symbol"))
    position_generation_id_value = row.get("position_generation_id")
    position_generation_id = (
        position_generation_id_value
        if type(position_generation_id_value) is str
        and bool(_SAFE_ROW_ID_RE.fullmatch(position_generation_id_value))
        else None
    )
    paper_session_id_value = row.get("paper_session_id")
    paper_session_id = (
        paper_session_id_value
        if type(paper_session_id_value) is str
        and bool(_SAFE_ROW_ID_RE.fullmatch(paper_session_id_value))
        else None
    )
    # These are non-authorizing echoes for strict downstream reconciliation.
    # The cascade guard must compare every value back to the exact embedded
    # open-position row; missing/invalid echoes cannot become defaults.
    maintenance_margin_cum = _finite_float(row.get("maintenance_margin_cum"))
    maintenance_margin_mark_price = _finite_float(
        row.get("maintenance_margin_mark_price")
    )
    maintenance_margin_mark_time_value = row.get("maintenance_margin_mark_time")
    maintenance_margin_mark_time = (
        maintenance_margin_mark_time_value
        if type(maintenance_margin_mark_time_value) is str
        and bool(maintenance_margin_mark_time_value.strip())
        else None
    )
    maintenance_margin_notional_usd = _finite_float(
        row.get("maintenance_margin_notional_usd")
    )
    maintenance_margin_estimate = _finite_float(
        row.get("maintenance_margin_estimate")
    )
    unrealized_pnl_usd = _finite_float(
        row.get("unrealized_pnl_usd")
        if "unrealized_pnl_usd" in row
        else row.get("unrealized_pnl")
    )
    unrealized_pnl_bps = _finite_float(row.get("unrealized_pnl_bps"))
    margin_mode_simulated = (
        str(row.get("margin_mode_simulated") or "").strip().lower() or None
    )
    return {
        "row_id": row_id,
        "position_generation_id": position_generation_id,
        "paper_session_id": paper_session_id,
        "row_identity_valid": row_identity_invalid_reason is None,
        "row_identity_invalid_reason": row_identity_invalid_reason,
        "symbol": validated_symbol or "",
        "accounting_scope": accounting_scope,
        "canonical_notional_usd": (
            round(float(notional), 8) if notional is not None and notional > 0.0 else None
        ),
        "notional_source": notional_source,
        "notional_evidence": notional_evidence,
        "notional_evidence_invalid_reasons": notional_invalid_reasons,
        "candidate_notional_evidence": notional_evidence,
        "candidate_notional_evidence_invalid_reasons": notional_invalid_reasons,
        "effective_leverage": round(float(leverage), 8),
        "leverage_source": leverage_evidence["leverage_source"],
        "requested_effective_leverage": leverage_evidence["requested_effective_leverage"],
        "requested_effective_leverage_source": leverage_evidence[
            "requested_effective_leverage_source"
        ],
        "unauthenticated_leverage_claim_downgraded_to_one_x": leverage_evidence[
            "unauthenticated_leverage_claim_downgraded_to_one_x"
        ],
        "leverage_authorization_downgrade_reasons": leverage_evidence[
            "leverage_authorization_downgrade_reasons"
        ],
        "effective_leverage_evidence": leverage_evidence["effective_leverage_evidence"],
        "effective_leverage_evidence_consistent": leverage_evidence[
            "effective_leverage_evidence_consistent"
        ],
        "effective_leverage_evidence_invalid_reasons": leverage_evidence[
            "effective_leverage_evidence_invalid_reasons"
        ],
        "decision_time_max_effective_leverage": leverage_evidence[
            "decision_time_max_effective_leverage"
        ],
        "leverage_cap_source": leverage_evidence["leverage_cap_source"],
        "leverage_cap_sources": leverage_evidence["leverage_cap_sources"],
        "decision_time_leverage_cap_evidence": leverage_evidence[
            "decision_time_leverage_cap_evidence"
        ],
        "decision_time_leverage_cap_evidence_valid": leverage_evidence[
            "decision_time_leverage_cap_evidence_valid"
        ],
        "decision_time_leverage_cap_invalid_reasons": leverage_evidence[
            "decision_time_leverage_cap_invalid_reasons"
        ],
        "decision_time_leverage_cap_authorization_sources": leverage_evidence[
            "decision_time_leverage_cap_authorization_sources"
        ],
        "decision_time_leverage_cap_authorization_valid": leverage_evidence[
            "decision_time_leverage_cap_authorization_valid"
        ],
        "row_projection_cap_can_only_lower": leverage_evidence["row_projection_cap_can_only_lower"],
        "final_admission_leverage_authorization_required": leverage_evidence[
            "final_admission_leverage_authorization_required"
        ],
        "final_admission_leverage_authorization_valid": leverage_evidence[
            "final_admission_leverage_authorization_valid"
        ],
        "final_admission_leverage_authorization_invalid_reasons": leverage_evidence[
            "final_admission_leverage_authorization_invalid_reasons"
        ],
        "final_admission_receipt_hash": leverage_evidence["final_admission_receipt_hash"],
        "final_admission_bound_material_hash": leverage_evidence[
            "final_admission_bound_material_hash"
        ],
        "final_admission_allocation_hash": leverage_evidence["final_admission_allocation_hash"],
        "final_admission_upstream_authenticated_bracket_reread_attested": (
            leverage_evidence["final_admission_upstream_authenticated_bracket_reread_attested"]
        ),
        "final_admission_bracket_hmac_revalidated_here": leverage_evidence[
            "final_admission_bracket_hmac_revalidated_here"
        ],
        "final_admission_bracket_hmac_revalidation_gap_reason": leverage_evidence[
            "final_admission_bracket_hmac_revalidation_gap_reason"
        ],
        "operator_authorized_symbol_leverage_ceiling": leverage_evidence[
            "operator_authorized_symbol_leverage_ceiling"
        ],
        "symbol_leverage_ceiling_source": leverage_evidence["symbol_leverage_ceiling_source"],
        "maintenance_bracket_max_initial_leverage": leverage_evidence[
            "maintenance_bracket_max_initial_leverage"
        ],
        "maintenance_bracket_max_leverage_source": leverage_evidence[
            "maintenance_bracket_max_leverage_source"
        ],
        "maintenance_bracket_proof_required": leverage_evidence[
            "maintenance_bracket_proof_required"
        ],
        "maintenance_bracket_proof_valid": leverage_evidence["maintenance_bracket_proof_valid"],
        "maintenance_bracket_proof_invalid_reasons": leverage_evidence[
            "maintenance_bracket_proof_invalid_reasons"
        ],
        "maintenance_bracket_structural_binding_valid": leverage_evidence[
            "maintenance_bracket_structural_binding_valid"
        ],
        "maintenance_bracket_structural_binding_invalid_reasons": leverage_evidence[
            "maintenance_bracket_structural_binding_invalid_reasons"
        ],
        "maintenance_bracket_raw_context_binding_valid": leverage_evidence[
            "maintenance_bracket_raw_context_binding_valid"
        ],
        "maintenance_bracket_raw_context_binding_invalid_reasons": leverage_evidence[
            "maintenance_bracket_raw_context_binding_invalid_reasons"
        ],
        "maintenance_bracket_cap_usable": leverage_evidence["maintenance_bracket_cap_usable"],
        "maintenance_bracket_cap_effect": leverage_evidence["maintenance_bracket_cap_effect"],
        "maintenance_bracket_authorizes_leverage": leverage_evidence[
            "maintenance_bracket_authorizes_leverage"
        ],
        "maintenance_bracket_authentication_revalidated_here": leverage_evidence[
            "maintenance_bracket_authentication_revalidated_here"
        ],
        "maintenance_bracket_authentication_gap_reasons": leverage_evidence[
            "maintenance_bracket_authentication_gap_reasons"
        ],
        "maintenance_bracket_reference_time": leverage_evidence[
            "maintenance_bracket_reference_time"
        ],
        "maintenance_bracket_reference_time_source": leverage_evidence[
            "maintenance_bracket_reference_time_source"
        ],
        **maintenance_evidence,
        "canonical_margin_usd": round(float(margin), 8) if margin is not None else None,
        "canonical_margin_unrounded_usd": margin,
        "reported_allocated_margin_usd": reported_margin,
        "reported_margin_matches_canonical": (
            reported_margin is not None
            and margin is not None
            and math.isclose(reported_margin, margin, rel_tol=1e-9, abs_tol=0.01)
        ),
        "maintenance_margin_cum": maintenance_margin_cum,
        "maintenance_margin_mark_price": maintenance_margin_mark_price,
        "maintenance_margin_mark_time": maintenance_margin_mark_time,
        "maintenance_margin_mark_event_time": row.get(
            "maintenance_margin_mark_event_time"
        ),
        "maintenance_margin_mark_generated_at": row.get(
            "maintenance_margin_mark_generated_at"
        ),
        "maintenance_margin_mark_available_at": row.get(
            "maintenance_margin_mark_available_at"
        ),
        "maintenance_margin_mark_decision_time": row.get(
            "maintenance_margin_mark_decision_time"
        ),
        "maintenance_margin_mark_source": row.get(
            "maintenance_margin_mark_source"
        ),
        "maintenance_margin_mark_evidence_sha256": row.get(
            "maintenance_margin_mark_evidence_sha256"
        ),
        "maintenance_margin_mark_contract_authoritative": row.get(
            "maintenance_margin_mark_contract_authoritative"
        )
        is True,
        "maintenance_margin_mark_freshness_budget_seconds": _finite_float(
            row.get("maintenance_margin_mark_freshness_budget_seconds")
        ),
        "maintenance_margin_mark_cadence_policy_version": row.get(
            "maintenance_margin_mark_cadence_policy_version"
        ),
        "maintenance_margin_mark_consumer_validation_boundary": row.get(
            "maintenance_margin_mark_consumer_validation_boundary"
        ),
        "margin_mode_simulated": margin_mode_simulated,
        "maintenance_margin_notional_usd": maintenance_margin_notional_usd,
        "maintenance_margin_estimate": maintenance_margin_estimate,
        "unrealized_pnl_usd": unrealized_pnl_usd,
        "unrealized_pnl_bps": unrealized_pnl_bps,
        "mapping_snapshot_valid": mapping_snapshot_invalid_reason is None,
        "mapping_snapshot_invalid_reason": mapping_snapshot_invalid_reason,
        **route_safety_evidence,
        "valid": valid,
        "invalid_reason": invalid_reasons[0] if invalid_reasons else None,
        "invalid_reasons": invalid_reasons,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }


def _margin_base(equity: Any, wallet_balance: Any) -> tuple[float, str, float, float]:
    parsed_equity = _finite_float(equity)
    parsed_wallet = _finite_float(wallet_balance)
    equity_value = parsed_equity if parsed_equity is not None else 0.0
    wallet_value = parsed_wallet if parsed_wallet is not None else 0.0
    if parsed_equity is None or parsed_equity <= 0.0:
        return (
            0.0,
            "EQUITY_MISSING_INVALID_OR_NON_POSITIVE_FAIL_CLOSED",
            equity_value,
            wallet_value,
        )
    if parsed_wallet is None or parsed_wallet <= 0.0:
        return (
            0.0,
            "WALLET_MISSING_INVALID_OR_NON_POSITIVE_FAIL_CLOSED",
            equity_value,
            wallet_value,
        )
    # Do not spend unrealized profit before it is banked, while unrealized
    # losses reduce capacity immediately.
    return (
        min(parsed_equity, parsed_wallet),
        "CONSERVATIVE_MIN_OF_EQUITY_AND_WALLET",
        equity_value,
        wallet_value,
    )


def build_paper_margin_status(
    *,
    equity: Any,
    wallet_balance: Any,
    open_positions: Iterable[Mapping[str, Any]],
    min_available_margin_buffer_pct: Any = 0.0,
    newly_reserved_margin_usd: Any = 0.0,
    reservations_included_in_open_positions: bool = False,
    expected_unrealized_pnl_usd: Any = None,
    require_ledger_reconciliation: bool = False,
) -> dict[str, Any]:
    """Build account-wide used/reserved/free paper-margin truth.

    When ``reservations_included_in_open_positions`` is false, reservations
    are pending current-cycle fills and are added to existing used margin for
    the invariant.  When true, the reservation amount is informational only:
    those fills are already represented in ``open_positions``.

    This boundary intentionally has no cash-balance input or guessed cash
    alias. Callers must pass authoritative account ``equity`` and
    ``wallet_balance`` truth.
    """

    raw_rows, collection_iteration_invalid_reason = _materialize_untrusted_iterable(
        open_positions,
        path="open_positions",
    )
    rows: list[dict[str, Any]] = []
    invalid_collection_rows: list[dict[str, Any]] = []
    if collection_iteration_invalid_reason is not None:
        invalid_collection_rows.append(
            {
                "row_id": "invalid_open_position_collection_iteration",
                "symbol": None,
                "accounting_scope": "OPEN_EXECUTED_POSITION",
                "canonical_margin_usd": None,
                "valid": False,
                "invalid_reason": PAPER_OPEN_POSITION_COLLECTION_INVALID_REASON,
                "invalid_reasons": [
                    PAPER_OPEN_POSITION_COLLECTION_INVALID_REASON,
                    collection_iteration_invalid_reason,
                ],
                "paper_only": True,
                "routes_to_live": False,
                "places_real_order": False,
            }
        )
    for index, row in enumerate(raw_rows):
        if not _is_mapping_without_instance_metadata(row):
            invalid_collection_rows.append(
                {
                    "row_id": f"invalid_open_position_collection_row:{index}",
                    "symbol": None,
                    "accounting_scope": "OPEN_EXECUTED_POSITION",
                    "canonical_margin_usd": None,
                    "valid": False,
                    "invalid_reason": PAPER_OPEN_POSITION_COLLECTION_INVALID_REASON,
                    "invalid_reasons": [PAPER_OPEN_POSITION_COLLECTION_INVALID_REASON],
                }
            )
            continue
        try:
            rows.append(
                _snapshot_untrusted_mapping(
                    row,
                    path=f"open_positions[{index}]",
                )
            )
        except _MappingSnapshotError as exc:
            invalid_collection_rows.append(
                {
                    "row_id": f"invalid_open_position_mapping_snapshot:{index}",
                    "symbol": None,
                    "accounting_scope": "OPEN_EXECUTED_POSITION",
                    "canonical_margin_usd": None,
                    "valid": False,
                    "invalid_reason": PAPER_OPEN_POSITION_COLLECTION_INVALID_REASON,
                    "invalid_reasons": [PAPER_OPEN_POSITION_COLLECTION_INVALID_REASON],
                    "mapping_snapshot_valid": False,
                    "mapping_snapshot_invalid_reason": (
                        f"{PAPER_MARGIN_MAPPING_SNAPSHOT_INVALID_REASON}:{exc.path}"
                    ),
                    "paper_only": True,
                    "routes_to_live": False,
                    "places_real_order": False,
                }
            )
    margin_rows = [
        canonical_margin_requirement(row, accounting_scope="OPEN_EXECUTED_POSITION") for row in rows
    ]
    identity_indexes: dict[str, list[int]] = {}
    for index, row in enumerate(rows):
        for identity in sorted(
            _collision_identities(
                row,
                accounting_scope="OPEN_EXECUTED_POSITION",
            )
        ):
            identity_indexes.setdefault(identity, []).append(index)
    duplicate_identity_groups = sorted(
        {tuple(indexes) for indexes in identity_indexes.values() if len(indexes) > 1}
    )
    duplicate_identity_row_indexes = {
        index for indexes in duplicate_identity_groups for index in indexes
    }
    duplicate_identity_rows = [
        {
            "row_id": f"duplicate_open_position_identity_group:{ordinal}",
            "symbol": None,
            "accounting_scope": "OPEN_EXECUTED_POSITION",
            "canonical_margin_usd": None,
            "canonical_margin_unrounded_usd": None,
            "valid": False,
            "invalid_reason": PAPER_DUPLICATE_OPEN_POSITION_IDENTITY_REASON,
            "invalid_reasons": [PAPER_DUPLICATE_OPEN_POSITION_IDENTITY_REASON],
            "duplicate_row_count": len(indexes),
            "paper_only": True,
            "routes_to_live": False,
            "places_real_order": False,
        }
        for ordinal, indexes in enumerate(duplicate_identity_groups, start=1)
    ]
    invalid_rows: list[dict[str, Any]] = [
        *invalid_collection_rows,
        *duplicate_identity_rows,
        *(row for row in margin_rows if row["valid"] is not True),
    ]
    used_margin, used_margin_aggregation_valid = _finite_sum_with_prefix(
        float(row["canonical_margin_unrounded_usd"])
        for row in margin_rows
        if row["valid"] is True and row["canonical_margin_unrounded_usd"] is not None
    )
    base, base_source, equity_value, wallet_value = _margin_base(equity, wallet_balance)
    ledger_reconciliation_reasons: list[str] = []
    row_unrealized_values = [
        _finite_float(row.get("unrealized_pnl_usd"))
        for row in margin_rows
        if row.get("valid") is True
    ]
    row_unrealized_complete = all(
        value is not None for value in row_unrealized_values
    )
    row_unrealized_pnl_usd = (
        math.fsum(float(value) for value in row_unrealized_values if value is not None)
        if row_unrealized_complete
        else None
    )
    expected_unrealized = _finite_float(expected_unrealized_pnl_usd)
    if require_ledger_reconciliation:
        if not row_unrealized_complete:
            ledger_reconciliation_reasons.append(
                "OPEN_POSITION_UNREALIZED_PNL_ROW_SUM_INCOMPLETE"
            )
        if expected_unrealized is None:
            ledger_reconciliation_reasons.append(
                "EXPECTED_LEDGER_UNREALIZED_PNL_MISSING_OR_NONFINITE"
            )
        elif (
            row_unrealized_pnl_usd is None
            or not math.isclose(
                expected_unrealized,
                row_unrealized_pnl_usd,
                rel_tol=1e-9,
                abs_tol=1e-7,
            )
        ):
            ledger_reconciliation_reasons.append(
                "EXPECTED_LEDGER_UNREALIZED_PNL_DOES_NOT_EQUAL_POSITION_ROW_SUM"
            )
        if (
            row_unrealized_pnl_usd is None
            or not math.isclose(
                equity_value,
                wallet_value + row_unrealized_pnl_usd,
                rel_tol=1e-9,
                abs_tol=1e-7,
            )
        ):
            ledger_reconciliation_reasons.append(
                "EQUITY_DOES_NOT_EQUAL_WALLET_PLUS_POSITION_ROW_PNL"
            )
        invalid_modes = [
            row.get("margin_mode_simulated")
            for row in margin_rows
            if row.get("valid") is True
            and row.get("margin_mode_simulated")
            not in {
                "cross",
                "cross_paper_simulated",
                "isolated",
                "isolated_paper_simulated",
            }
        ]
        if invalid_modes:
            ledger_reconciliation_reasons.append(
                "OPEN_POSITION_MARGIN_MODE_PARTITION_INCOMPLETE"
            )
    cross_margin_rows = [
        row
        for row in margin_rows
        if row.get("valid") is True
        and row.get("margin_mode_simulated")
        in {"cross", "cross_paper_simulated"}
    ]
    isolated_margin_rows = [
        row
        for row in margin_rows
        if row.get("valid") is True
        and row.get("margin_mode_simulated")
        in {"isolated", "isolated_paper_simulated"}
    ]
    cross_used_margin = math.fsum(
        float(row["canonical_margin_usd"]) for row in cross_margin_rows
    )
    isolated_used_margin = math.fsum(
        float(row["canonical_margin_usd"]) for row in isolated_margin_rows
    )
    cross_unrealized_pnl = math.fsum(
        float(row["unrealized_pnl_usd"])
        for row in cross_margin_rows
        if row.get("unrealized_pnl_usd") is not None
    )
    isolated_unrealized_pnl = math.fsum(
        float(row["unrealized_pnl_usd"])
        for row in isolated_margin_rows
        if row.get("unrealized_pnl_usd") is not None
    )
    cross_wallet_balance = wallet_value - isolated_used_margin
    cross_equity = cross_wallet_balance + cross_unrealized_pnl
    parsed_buffer_pct = _finite_float(min_available_margin_buffer_pct)
    buffer_valid = parsed_buffer_pct is not None and 0.0 <= parsed_buffer_pct <= 1.0
    buffer_pct = parsed_buffer_pct if parsed_buffer_pct is not None and buffer_valid else 1.0
    parsed_reserved = _finite_float(newly_reserved_margin_usd)
    reservation_input_valid = parsed_reserved is not None and parsed_reserved >= 0.0
    reserved = parsed_reserved if parsed_reserved is not None and reservation_input_valid else 0.0
    reservation_inclusion_flag_valid = type(reservations_included_in_open_positions) is bool
    reservations_included = (
        reservations_included_in_open_positions is True
        if reservation_inclusion_flag_valid
        else False
    )
    pending_reserved = 0.0 if reservations_included else reserved
    projected_used_margin, projected_used_margin_aggregation_valid = _finite_sum_with_prefix(
        (used_margin, pending_reserved)
    )
    derived_invalid_reasons: list[str] = []
    if not used_margin_aggregation_valid:
        derived_invalid_reasons.append(
            f"{PAPER_MARGIN_DERIVED_VALUE_NONFINITE_REASON}:USED_MARGIN_AGGREGATE"
        )
    if not projected_used_margin_aggregation_valid:
        derived_invalid_reasons.append(
            f"{PAPER_MARGIN_DERIVED_VALUE_NONFINITE_REASON}:PROJECTED_USED_MARGIN_AGGREGATE"
        )
    if derived_invalid_reasons:
        invalid_rows.append(
            {
                "row_id": "invalid_paper_margin_aggregate",
                "symbol": None,
                "accounting_scope": "ACCOUNT_WIDE_AGGREGATE",
                "canonical_margin_usd": None,
                "valid": False,
                "invalid_reason": derived_invalid_reasons[0],
                "invalid_reasons": list(derived_invalid_reasons),
                "paper_only": True,
                "routes_to_live": False,
                "places_real_order": False,
            }
        )
    # Unknown open-position execution truth must not become spendable cash on
    # any consumer that reads only the numeric free-margin fields. Keep the
    # measured used margin visible, but reserve all remaining capacity until
    # every open row is accountably reconstructable.
    control_inputs_valid = (
        buffer_valid and reservation_input_valid and reservation_inclusion_flag_valid
    )
    free_before_reservations = (
        0.0 if invalid_rows or not control_inputs_valid else max(0.0, base - used_margin)
    )
    buffer_usd = free_before_reservations * buffer_pct
    usable_before_reservations = max(0.0, free_before_reservations - buffer_usd)
    free_margin = (
        0.0 if invalid_rows or not control_inputs_valid else max(0.0, base - projected_used_margin)
    )
    free_after_buffer = max(0.0, usable_before_reservations - pending_reserved)
    deficit = max(0.0, projected_used_margin - base)
    buffer_deficit = max(0.0, pending_reserved - usable_before_reservations)
    reconstructed, reconstructed_aggregation_valid = _finite_sum_with_prefix(
        (projected_used_margin, free_margin)
    )
    buffer_invariant = buffer_deficit == 0.0
    numeric_invariant = (
        used_margin_aggregation_valid
        and projected_used_margin_aggregation_valid
        and reconstructed_aggregation_valid
        and deficit == 0.0
        and math.isclose(
            reconstructed,
            base,
            rel_tol=1e-9,
            abs_tol=0.01,
        )
    )
    accounting_complete = not invalid_rows
    margin_base_available = base > 0.0
    invariant = (
        numeric_invariant
        and buffer_invariant
        and accounting_complete
        and margin_base_available
        and control_inputs_valid
        and not ledger_reconciliation_reasons
    )
    failure_reasons: list[str] = []
    if not margin_base_available:
        failure_reasons.append("PAPER_MARGIN_BASE_MISSING_OR_NON_POSITIVE")
    if invalid_rows:
        failure_reasons.append(PAPER_EXISTING_MARGIN_INCOMPLETE_REASON)
    if not buffer_valid:
        failure_reasons.append(PAPER_MARGIN_BUFFER_INVALID_REASON)
    if not reservation_input_valid:
        failure_reasons.append(PAPER_MARGIN_RESERVATION_INPUT_INVALID_REASON)
    if not reservation_inclusion_flag_valid:
        failure_reasons.append(PAPER_MARGIN_RESERVATION_INCLUSION_FLAG_INVALID_REASON)
    failure_reasons.extend(derived_invalid_reasons)
    failure_reasons.extend(ledger_reconciliation_reasons)
    if deficit > 0.0:
        failure_reasons.append("PAPER_MARGIN_USED_AND_RESERVED_EXCEED_MARGIN_BASE")
    if not buffer_invariant:
        failure_reasons.append(PAPER_INSUFFICIENT_FREE_MARGIN_REASON)
    return {
        "schema_version": PAPER_MARGIN_ACCOUNTING_SCHEMA_VERSION,
        "status": "PASS" if invariant else "FAIL_CLOSED",
        "equity": round(equity_value, 8),
        "equity_usd": round(equity_value, 8),
        "wallet_balance_usd": round(wallet_value, 8),
        "unrealized_pnl_usd": (
            round(row_unrealized_pnl_usd, 8)
            if row_unrealized_pnl_usd is not None
            else None
        ),
        "expected_unrealized_pnl_usd": expected_unrealized,
        "ledger_reconciliation_required": require_ledger_reconciliation,
        "ledger_reconciliation_complete": not ledger_reconciliation_reasons,
        "ledger_reconciliation_reasons": ledger_reconciliation_reasons,
        "equity_wallet_position_pnl_reconciled": (
            require_ledger_reconciliation and not ledger_reconciliation_reasons
        ),
        "cross_used_margin_usd": round(cross_used_margin, 8),
        "isolated_used_margin_usd": round(isolated_used_margin, 8),
        "cross_unrealized_pnl_usd": round(cross_unrealized_pnl, 8),
        "isolated_unrealized_pnl_usd": round(isolated_unrealized_pnl, 8),
        "cross_wallet_balance_usd": round(cross_wallet_balance, 8),
        "cross_equity_usd": round(cross_equity, 8),
        "margin_mode_partition_complete": not any(
            reason == "OPEN_POSITION_MARGIN_MODE_PARTITION_INCOMPLETE"
            for reason in ledger_reconciliation_reasons
        ),
        "margin_base_usd": round(base, 8),
        "margin_base_source": base_source,
        "margin_base_available": margin_base_available,
        "cash_balance_input_supported": False,
        "cash_balance_alias_inferred": False,
        "account_balance_input_contract": (
            "AUTHORITATIVE_EQUITY_AND_WALLET_BALANCE_REQUIRED_FROM_CALLER"
        ),
        "open_position_count": len(raw_rows),
        "open_position_collection_complete": collection_iteration_invalid_reason is None,
        "open_position_collection_iteration_invalid_reason": (collection_iteration_invalid_reason),
        "accounted_open_position_count": sum(1 for row in margin_rows if row["valid"] is True),
        "duplicate_open_position_identity_group_count": len(duplicate_identity_groups),
        "duplicate_open_position_identity_row_count": len(duplicate_identity_row_indexes),
        "open_position_canonical_identities_unique": not duplicate_identity_groups,
        "invalid_open_position_margin_count": len(invalid_rows),
        "invalid_open_position_margin_rows": invalid_rows,
        "position_margin_rows": margin_rows,
        "accounting_complete": accounting_complete,
        "control_inputs_valid": control_inputs_valid,
        "admission_inputs_valid": invariant,
        "margin_buffer_input_valid": buffer_valid,
        "newly_reserved_margin_input_valid": reservation_input_valid,
        "reservations_included_in_open_positions_input_valid": (reservation_inclusion_flag_valid),
        "failure_reasons": failure_reasons,
        "used_margin": round(used_margin, 8),
        "used_margin_usd": round(used_margin, 8),
        "used_margin_unrounded_usd": used_margin,
        "newly_reserved_margin": round(reserved, 8),
        "newly_reserved_margin_usd": round(reserved, 8),
        "newly_reserved_margin_unrounded_usd": reserved,
        "newly_reserved_included_in_used_margin": reservations_included,
        "used_margin_aggregation_valid": used_margin_aggregation_valid,
        "projected_used_margin_aggregation_valid": (projected_used_margin_aggregation_valid),
        "projected_used_margin_usd": round(projected_used_margin, 8),
        "projected_used_margin_unrounded_usd": projected_used_margin,
        "free_margin_before_reservations_usd": round(free_before_reservations, 8),
        "free_margin_before_reservations_unrounded_usd": free_before_reservations,
        "free_margin": round(free_margin, 8),
        "free_margin_usd": round(free_margin, 8),
        "free_margin_unrounded_usd": free_margin,
        "min_available_margin_buffer_pct": round(buffer_pct, 8),
        "margin_buffer_basis": "FREE_MARGIN_BEFORE_CURRENT_CYCLE_RESERVATIONS",
        "buffer": round(buffer_usd, 8),
        "margin_buffer_usd": round(buffer_usd, 8),
        "margin_buffer_deficit_usd": round(buffer_deficit, 8),
        "margin_buffer_invariant_holds": buffer_invariant,
        "usable_margin_after_buffer_before_reservations_usd": round(
            usable_before_reservations,
            8,
        ),
        "usable_margin_after_buffer_before_reservations_unrounded_usd": (
            usable_before_reservations
        ),
        "free_margin_after_buffer_usd": round(free_after_buffer, 8),
        "margin_deficit_usd": round(deficit, 8),
        "no_negative_free_margin": free_margin >= 0.0 and free_after_buffer >= 0.0,
        "invariant": invariant,
        "invariant_holds": invariant,
        "numeric_invariant_holds": numeric_invariant,
        "invariant_formula": (
            "margin_base_usd = used_margin_usd + free_margin_usd"
            if reservations_included
            else "margin_base_usd = used_margin_usd + newly_reserved_margin_usd + free_margin_usd"
        ),
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }


def _reservation_sort_key(
    row: Mapping[str, Any],
) -> tuple[Any, ...]:
    def safe_text(value: Any, *, normalization: str = "identity") -> str:
        if value is None:
            return ""
        try:
            text = str(value)
        except Exception:  # noqa: BLE001 - untrusted sort scalar boundary
            return ""
        if normalization == "upper":
            return text.upper()
        if normalization == "lower":
            return text.lower()
        return text

    symbol = safe_text(row.get("symbol"), normalization="upper")
    raw_calibrated = row.get("confidence_calibrated")
    if _missing(raw_calibrated):
        confidence = _finite_float(row.get("confidence"))
    else:
        confidence = _finite_float(raw_calibrated)
    confidence = confidence if confidence is not None else 0.0
    timeframe = row.get("timeframe")
    if timeframe is None or (isinstance(timeframe, str) and timeframe == ""):
        timeframe = row.get("thesis_timeframe")
    side = row.get("side")
    if side is None or (isinstance(side, str) and side == ""):
        side = row.get("action")
    row_identity, _identity_invalid_reason = _row_identity(row)
    return (
        -confidence,
        symbol,
        safe_text(timeframe),
        safe_text(side, normalization="lower"),
        row_identity,
    )


def _blocked_margin_row(
    row: Mapping[str, Any],
    *,
    reason: str,
    requirement: Mapping[str, Any],
    free_after_buffer_usd: float,
    sequence: int,
) -> dict[str, Any]:
    blocked = dict(row)
    gate_reasons = sorted(
        set(
            item
            for item in (
                *_safe_prior_reason_tokens(blocked.get("paper_fill_gate_block_reasons")),
                PAPER_MARGIN_RESERVATION_BLOCK_REASON,
                reason,
            )
            if item
        )
    )
    local_reasons = sorted(
        set(
            item
            for item in (
                *_safe_prior_reason_tokens(blocked.get("local_block_reasons")),
                f"paper_margin_reservation:{reason}",
            )
            if item
        )
    )
    blocked.update(
        {
            "decision": "BLOCK_INSUFFICIENT_MARGIN",
            "paper_fill_allowed": False,
            "paper_fast_path": False,
            "paper_fill_block_reason": PAPER_MARGIN_RESERVATION_BLOCK_REASON,
            "paper_fill_gate_block_reasons": gate_reasons,
            "local_block_reasons": local_reasons,
            "paper_margin_reservation_status": "BLOCKED",
            "paper_margin_reservation_block_reasons": [reason],
            "paper_margin_reservation_sequence": sequence,
            "paper_margin_required_usd": requirement.get("canonical_margin_usd"),
            "paper_margin_free_after_buffer_before_candidate_usd": round(
                max(0.0, free_after_buffer_usd),
                8,
            ),
            "paper_margin_requirement": dict(requirement),
            "paper_only": True,
            "routes_to_live": False,
            "places_real_order": False,
        }
    )
    return blocked


def reserve_paper_candidate_margin(
    candidates: Iterable[Mapping[str, Any]],
    *,
    equity: Any,
    wallet_balance: Any,
    existing_open_positions: Iterable[Mapping[str, Any]],
    min_available_margin_buffer_pct: Any,
    preferred_symbols: Iterable[str] = (),
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Cumulatively reserve candidates within one paper-loop cycle snapshot.

    The caller must enforce a single active writer.  This function has no
    cross-process transaction or Redis compare-and-set semantics.
    """

    raw_candidate_rows, candidate_collection_iteration_invalid_reason = (
        _materialize_untrusted_iterable(
            candidates,
            path="candidates",
        )
    )
    candidate_rows: list[dict[str, Any]] = []
    candidate_source_indexes: list[int] = []
    invalid_candidate_rows: list[dict[str, Any]] = []
    for index, row in enumerate(raw_candidate_rows):
        if not _is_mapping_without_instance_metadata(row):
            invalid_candidate_rows.append(
                {
                    "row_id": f"invalid_candidate_collection_row:{index}",
                    "collection_index": index,
                    "observed_type": "NON_MAPPING",
                }
            )
            continue
        try:
            candidate_snapshot = _snapshot_untrusted_mapping(
                row,
                path=f"candidates[{index}]",
            )
            _candidate_identity, candidate_identity_invalid_reason = _row_identity(
                candidate_snapshot
            )
            if candidate_identity_invalid_reason is not None:
                invalid_candidate_rows.append(
                    {
                        "row_id": "invalid_candidate_row_identity",
                        "collection_index": index,
                        "observed_type": "MAPPING_IDENTITY_INVALID",
                        "row_identity_invalid_reason": candidate_identity_invalid_reason,
                    }
                )
                continue
            candidate_rows.append(candidate_snapshot)
            candidate_source_indexes.append(index)
        except _MappingSnapshotError as exc:
            invalid_row = {
                "row_id": f"invalid_candidate_mapping_snapshot:{index}",
                "collection_index": index,
                "observed_type": "MAPPING_SNAPSHOT_INVALID",
                "mapping_snapshot_invalid_reason": (
                    f"{PAPER_MARGIN_MAPPING_SNAPSHOT_INVALID_REASON}:{exc.path}"
                ),
            }
            if exc.row_identity_invalid:
                invalid_row["row_identity_invalid_reason"] = (
                    PAPER_MARGIN_ROW_IDENTITY_INVALID_REASON
                )
            invalid_candidate_rows.append(invalid_row)
    if candidate_collection_iteration_invalid_reason is not None:
        invalid_candidate_rows.append(
            {
                "row_id": "invalid_candidate_collection_iteration",
                "collection_index": len(raw_candidate_rows),
                "observed_type": "ITERATION_FAILURE",
                "collection_iteration_invalid_reason": (
                    candidate_collection_iteration_invalid_reason
                ),
            }
        )
    # Kept in the public signature for call-site compatibility. Static symbol
    # classes cannot influence capital reservation priority.
    del preferred_symbols
    ordered = sorted(candidate_rows, key=_reservation_sort_key)
    candidate_identity_indexes: dict[str, list[int]] = {}
    for source_index, row in zip(candidate_source_indexes, candidate_rows, strict=True):
        for identity in sorted(
            _collision_identities(
                row,
                accounting_scope="CANDIDATE_ESTIMATE",
            )
        ):
            candidate_identity_indexes.setdefault(identity, []).append(source_index)
    duplicate_candidate_indexes = {
        index
        for indexes in candidate_identity_indexes.values()
        if len(indexes) > 1
        for index in indexes
    }
    raw_existing_rows, existing_collection_iteration_invalid_reason = (
        _materialize_untrusted_iterable(
            existing_open_positions,
            path="existing_open_positions",
        )
    )
    existing_rows: list[Any] = []
    for index, existing_row in enumerate(raw_existing_rows):
        if _is_mapping_without_instance_metadata(existing_row):
            try:
                existing_rows.append(
                    _snapshot_untrusted_mapping(
                        existing_row,
                        path=f"existing_open_positions[{index}]",
                    )
                )
            except _MappingSnapshotError:
                existing_rows.append(
                    {
                        "position_id": f"invalid_existing_open_position_snapshot:{index}",
                        _PERSISTED_MAPPING_SNAPSHOT_INVALID_REASON_KEY: (
                            _INTERNAL_MAPPING_SNAPSHOT_INVALID_SENTINEL
                        ),
                        "paper_margin_accounting_invalid_reason": (
                            PAPER_OPEN_POSITION_COLLECTION_INVALID_REASON
                        ),
                        "paper_only": True,
                        "routes_to_live": False,
                        "places_real_order": False,
                    }
                )
        else:
            existing_rows.append(existing_row)
    if existing_collection_iteration_invalid_reason is not None:
        existing_rows.append(
            {
                "position_id": "invalid_existing_open_position_collection_iteration",
                "paper_margin_accounting_invalid_reason": (
                    existing_collection_iteration_invalid_reason
                ),
                "paper_only": True,
                "routes_to_live": False,
                "places_real_order": False,
            }
        )
    existing_identities: set[str] = set()
    for existing_row in existing_rows:
        if not _is_mapping_without_instance_metadata(existing_row):
            continue
        identity, identity_invalid_reason = _row_identity(
            existing_row,
            accounting_scope="OPEN_EXECUTED_POSITION",
        )
        if identity_invalid_reason is None:
            existing_identities.add(identity)
        existing_identities.update(_canonical_identity_aliases(existing_row))
    candidate_overlap_indexes: set[int] = set()
    for source_index, row in zip(candidate_source_indexes, candidate_rows, strict=True):
        candidate_identity, candidate_identity_invalid_reason = _row_identity(row)
        if candidate_identity_invalid_reason is not None:
            continue
        if (
            candidate_identity in existing_identities
            or _canonical_identity_aliases(row) & existing_identities
        ):
            candidate_overlap_indexes.add(source_index)
    candidate_collection_integrity_reasons: list[str] = []
    if invalid_candidate_rows or candidate_collection_iteration_invalid_reason is not None:
        candidate_collection_integrity_reasons.append(PAPER_CANDIDATE_COLLECTION_INVALID_REASON)
    if duplicate_candidate_indexes:
        candidate_collection_integrity_reasons.append(PAPER_DUPLICATE_CANDIDATE_IDENTITY_REASON)
    if candidate_overlap_indexes:
        candidate_collection_integrity_reasons.append(
            PAPER_CANDIDATE_OPEN_POSITION_IDENTITY_OVERLAP_REASON
        )
    candidate_collection_fail_closed = bool(candidate_collection_integrity_reasons)
    identity_invalid_candidate_indexes = duplicate_candidate_indexes | candidate_overlap_indexes
    initial = build_paper_margin_status(
        equity=equity,
        wallet_balance=wallet_balance,
        open_positions=existing_rows,
        min_available_margin_buffer_pct=min_available_margin_buffer_pct,
    )
    initial_usable = float(initial["usable_margin_after_buffer_before_reservations_unrounded_usd"])
    remaining_usable = initial_usable
    accepted: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    reserved = 0.0
    reserved_components: list[float] = []
    reservation_rows: list[dict[str, Any]] = []
    existing_complete = initial["admission_inputs_valid"] is True

    for sequence, row in enumerate(ordered, start=1):
        requirement = canonical_margin_requirement(
            row,
            accounting_scope="CANDIDATE_ESTIMATE",
        )
        required = _finite_float(requirement.get("canonical_margin_unrounded_usd"))
        reason = None
        candidate_reserved, candidate_reserved_valid = _finite_sum_with_prefix(
            (*reserved_components, required if required is not None else 0.0)
        )
        if candidate_collection_fail_closed:
            reason = PAPER_CANDIDATE_COLLECTION_INVALID_REASON
        elif not existing_complete:
            if initial["accounting_complete"] is not True:
                reason = PAPER_EXISTING_MARGIN_INCOMPLETE_REASON
            elif initial["margin_base_available"] is not True:
                reason = "PAPER_MARGIN_BASE_MISSING_OR_NON_POSITIVE"
            elif initial["margin_buffer_input_valid"] is not True:
                reason = PAPER_MARGIN_BUFFER_INVALID_REASON
            else:
                reason = PAPER_MARGIN_RESERVATION_INPUT_INVALID_REASON
        elif requirement["valid"] is not True or required is None or required <= 0.0:
            reason = "PAPER_CANDIDATE_MARGIN_REQUIREMENT_INVALID"
        elif not candidate_reserved_valid:
            reason = f"{PAPER_MARGIN_DERIVED_VALUE_NONFINITE_REASON}:RESERVATION_AGGREGATE"
        elif candidate_reserved > initial_usable:
            reason = PAPER_INSUFFICIENT_FREE_MARGIN_REASON

        free_before = remaining_usable
        if reason is not None:
            blocked_row = _blocked_margin_row(
                row,
                reason=reason,
                requirement=requirement,
                free_after_buffer_usd=free_before,
                sequence=sequence,
            )
            blocked.append(blocked_row)
            reservation_rows.append(
                {
                    "row_id": requirement["row_id"],
                    "symbol": requirement["symbol"],
                    "sequence": sequence,
                    "status": "BLOCKED",
                    "reason": reason,
                    "required_margin_usd": required,
                    "free_after_buffer_before_usd": round(free_before, 8),
                    "free_after_buffer_after_usd": round(free_before, 8),
                }
            )
            continue

        assert required is not None
        reserved_components.append(required)
        reserved = candidate_reserved
        remaining_usable = max(0.0, initial_usable - reserved)
        accepted_row = dict(row)
        accepted_row.update(
            {
                "paper_margin_reservation_status": "RESERVED",
                "paper_margin_reservation_sequence": sequence,
                "paper_margin_reserved_usd": round(required, 8),
                "paper_margin_free_after_buffer_before_candidate_usd": round(
                    free_before,
                    8,
                ),
                "paper_margin_free_after_buffer_after_candidate_usd": round(
                    remaining_usable,
                    8,
                ),
                "paper_margin_requirement": dict(requirement),
                "paper_only": True,
                "routes_to_live": False,
                "places_real_order": False,
            }
        )
        accepted.append(accepted_row)
        reservation_rows.append(
            {
                "row_id": requirement["row_id"],
                "symbol": requirement["symbol"],
                "sequence": sequence,
                "status": "RESERVED",
                "reason": None,
                "required_margin_usd": round(required, 8),
                "free_after_buffer_before_usd": round(free_before, 8),
                "free_after_buffer_after_usd": round(remaining_usable, 8),
            }
        )

    for sequence, invalid_row in enumerate(
        invalid_candidate_rows,
        start=len(ordered) + 1,
    ):
        requirement = {
            "row_id": invalid_row["row_id"],
            "symbol": "",
            "accounting_scope": "CANDIDATE_ESTIMATE",
            "canonical_notional_usd": None,
            "canonical_margin_usd": None,
            "valid": False,
            "invalid_reason": PAPER_CANDIDATE_COLLECTION_INVALID_REASON,
            "invalid_reasons": list(
                dict.fromkeys(
                    item
                    for item in (
                        PAPER_CANDIDATE_COLLECTION_INVALID_REASON,
                        invalid_row.get("row_identity_invalid_reason"),
                    )
                    if item is not None
                )
            ),
        }
        safe_row = {
            "paper_candidate_collection_index": invalid_row["collection_index"],
            "paper_candidate_collection_observed_type": invalid_row["observed_type"],
        }
        if invalid_row.get("mapping_snapshot_invalid_reason") is not None:
            safe_row["paper_candidate_mapping_snapshot_invalid_reason"] = invalid_row[
                "mapping_snapshot_invalid_reason"
            ]
        if invalid_row.get("collection_iteration_invalid_reason") is not None:
            safe_row["paper_candidate_collection_iteration_invalid_reason"] = invalid_row[
                "collection_iteration_invalid_reason"
            ]
        if invalid_row.get("row_identity_invalid_reason") is not None:
            safe_row["paper_candidate_row_identity_invalid_reason"] = invalid_row[
                "row_identity_invalid_reason"
            ]
        blocked.append(
            _blocked_margin_row(
                safe_row,
                reason=PAPER_CANDIDATE_COLLECTION_INVALID_REASON,
                requirement=requirement,
                free_after_buffer_usd=remaining_usable,
                sequence=sequence,
            )
        )
        reservation_rows.append(
            {
                "row_id": invalid_row["row_id"],
                "symbol": "",
                "sequence": sequence,
                "status": "BLOCKED",
                "reason": PAPER_CANDIDATE_COLLECTION_INVALID_REASON,
                "required_margin_usd": None,
                "free_after_buffer_before_usd": round(remaining_usable, 8),
                "free_after_buffer_after_usd": round(remaining_usable, 8),
            }
        )

    status = build_paper_margin_status(
        equity=equity,
        wallet_balance=wallet_balance,
        open_positions=existing_rows,
        min_available_margin_buffer_pct=min_available_margin_buffer_pct,
        newly_reserved_margin_usd=reserved,
    )
    reservation_reconciliation_failed = bool(accepted and status["invariant_holds"] is not True)
    reservation_reconciliation_initial_failure_reasons: list[str] = []
    post_rollback_accounting_invariant_holds = status["invariant_holds"] is True
    if reservation_reconciliation_failed:
        reservation_reconciliation_initial_failure_reasons = list(status["failure_reasons"])
        for accepted_row in accepted:
            requirement_value = accepted_row.get("paper_margin_requirement")
            requirement = (
                dict(requirement_value)
                if isinstance(requirement_value, Mapping)
                else {
                    "row_id": "invalid_final_reservation_reconciliation",
                    "symbol": "",
                    "canonical_margin_usd": None,
                    "valid": False,
                    "invalid_reason": PAPER_MARGIN_FINAL_RESERVATION_RECONCILIATION_REASON,
                    "invalid_reasons": [PAPER_MARGIN_FINAL_RESERVATION_RECONCILIATION_REASON],
                }
            )
            sequence_value = _finite_float(accepted_row.get("paper_margin_reservation_sequence"))
            sequence = int(sequence_value) if sequence_value is not None else 0
            rollback_free_before = _finite_float(
                accepted_row.get("paper_margin_free_after_buffer_before_candidate_usd")
            )
            rollback_row = dict(accepted_row)
            for field in (
                "paper_margin_reserved_usd",
                "paper_margin_free_after_buffer_after_candidate_usd",
                "paper_margin_reservation_status",
            ):
                rollback_row.pop(field, None)
            blocked.append(
                _blocked_margin_row(
                    rollback_row,
                    reason=PAPER_MARGIN_FINAL_RESERVATION_RECONCILIATION_REASON,
                    requirement=requirement,
                    free_after_buffer_usd=(
                        rollback_free_before if rollback_free_before is not None else 0.0
                    ),
                    sequence=sequence,
                )
            )
        for reservation_row in reservation_rows:
            if reservation_row.get("status") != "RESERVED":
                continue
            reservation_row.update(
                {
                    "status": "BLOCKED",
                    "reason": PAPER_MARGIN_FINAL_RESERVATION_RECONCILIATION_REASON,
                    "free_after_buffer_after_usd": reservation_row.get(
                        "free_after_buffer_before_usd"
                    ),
                }
            )
        accepted = []
        reserved = 0.0
        reserved_components = []
        blocked.sort(
            key=lambda row: int(_finite_float(row.get("paper_margin_reservation_sequence")) or 0.0)
        )
        status = build_paper_margin_status(
            equity=equity,
            wallet_balance=wallet_balance,
            open_positions=existing_rows,
            min_available_margin_buffer_pct=min_available_margin_buffer_pct,
            newly_reserved_margin_usd=reserved,
        )
        post_rollback_accounting_invariant_holds = status["invariant_holds"] is True
        status.update(
            {
                "status": "FAIL_CLOSED",
                "admission_inputs_valid": False,
                "invariant": False,
                "invariant_holds": False,
                "failure_reasons": list(
                    dict.fromkeys(
                        [
                            *status["failure_reasons"],
                            PAPER_MARGIN_FINAL_RESERVATION_RECONCILIATION_REASON,
                        ]
                    )
                ),
            }
        )
    status.update(
        {
            "reservation_status": (
                "PASS" if status["invariant_holds"] and not blocked else "PARTIAL_OR_BLOCKED"
            ),
            "reservation_order": [row["row_id"] for row in reservation_rows],
            "reservation_rows": reservation_rows,
            "candidate_count": len(raw_candidate_rows),
            "accountable_candidate_count": len(candidate_rows),
            "candidate_collection_invalid_count": (
                len(invalid_candidate_rows) + len(identity_invalid_candidate_indexes)
            ),
            "duplicate_candidate_identity_count": len(duplicate_candidate_indexes),
            "candidate_existing_identity_overlap_count": len(candidate_overlap_indexes),
            "candidate_canonical_identities_unique": not duplicate_candidate_indexes,
            "candidate_identities_disjoint_from_existing_open_positions": (
                not candidate_overlap_indexes
            ),
            "candidate_collection_integrity_reasons": candidate_collection_integrity_reasons,
            "candidate_collection_inputs_valid": not candidate_collection_fail_closed,
            "candidate_collection_complete": (
                candidate_collection_iteration_invalid_reason is None
            ),
            "candidate_collection_iteration_invalid_reason": (
                candidate_collection_iteration_invalid_reason
            ),
            "existing_open_position_collection_complete": (
                existing_collection_iteration_invalid_reason is None
            ),
            "existing_open_position_collection_iteration_invalid_reason": (
                existing_collection_iteration_invalid_reason
            ),
            "reserved_candidate_count": len(accepted),
            "blocked_candidate_count": len(blocked),
            "final_reservation_reconciliation_valid": (not reservation_reconciliation_failed),
            "final_reservation_reconciliation_failure_reason": (
                PAPER_MARGIN_FINAL_RESERVATION_RECONCILIATION_REASON
                if reservation_reconciliation_failed
                else None
            ),
            "final_reservation_reconciliation_initial_failure_reasons": (
                reservation_reconciliation_initial_failure_reasons
            ),
            "post_rollback_accounting_invariant_holds": (post_rollback_accounting_invariant_holds),
            "deterministic_order": ("calibrated_confidence_desc_then_symbol_timeframe_side_id"),
            "static_symbol_priority_applied": False,
            "atomic_scope": "CURRENT_PAPER_CYCLE_PRE_LIFECYCLE",
            "cross_process_atomic": False,
            "single_active_writer_required": True,
        }
    )
    if candidate_collection_fail_closed:
        status["failure_reasons"] = list(
            dict.fromkeys(
                [
                    *status["failure_reasons"],
                    PAPER_CANDIDATE_COLLECTION_INVALID_REASON,
                    *candidate_collection_integrity_reasons,
                ]
            )
        )
        status.update(
            {
                "status": "FAIL_CLOSED",
                "admission_inputs_valid": False,
                "invariant": False,
                "invariant_holds": False,
            }
        )
    return accepted, blocked, status
