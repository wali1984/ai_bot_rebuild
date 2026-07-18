"""Bounded, resumable REST gap recovery for the trainer's 5m label archive.

The live WebSocket writer remains authoritative.  This module only requests
contiguous slots that the receipt-verified archive reports as absent, and the
archive's immutable unique key is the final race barrier if WebSocket data is
committed while a REST request is in flight.

Network transport is injected.  Importing this module never opens a socket,
reads credentials, starts a service, or mutates exchange/account state.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from v2.backend.app.services.market_state_integrity.canonical_candles import (
    canonical_from_binance_rest,
)
from v2.backend.app.services.native_trainer.durable_canonical_5m_label_archive import (
    ARCHIVE_SCHEMA_VERSION,
    EXACT_TAIL_TRANSACTION_ATTESTATION_SCHEMA_VERSION,
    LABEL_SLOT_MILLISECONDS,
    RETENTION_POLICY,
    Canonical5mArchiveWriterLease,
    Canonical5mArchiveWriterLeaseError,
    Canonical5mIdentityConflictError,
    DurableCanonical5mLabelArchive,
    canonical_5m_archive_writer_lease_path,
    canonical_json,
    stable_sha256,
    validate_canonical_finalized_5m_candle,
)

OUTBOX_SCHEMA_VERSION = "canonical_5m_historical_backfill_outbox_v3"
JOB_SCHEMA_VERSION = "canonical_5m_historical_backfill_job_v2"
REQUEST_SCHEMA_VERSION = "binance_usdm_public_5m_kline_gap_request_v1"
SLOT_RECEIPT_SCHEMA_VERSION = "canonical_5m_backfill_slot_receipt_v1"
AUTHORITY_CUTOFF_SCHEMA_VERSION = "canonical_5m_wss_authority_cutoff_v1"
AUTHORITY_SCOPE_SCHEMA_VERSION = "canonical_5m_wss_authority_scope_v1"
APPEND_ATTEMPT_SCHEMA_VERSION = "canonical_5m_backfill_append_attempt_v1"
APPEND_ATTEMPT_RESOLUTION_SCHEMA_VERSION = "canonical_5m_backfill_append_attempt_resolution_v1"
INVENTORY_PAGE_SCHEMA_VERSION = "canonical_5m_sparse_inventory_page_v1"
INVENTORY_MANIFEST_SCHEMA_VERSION = "canonical_5m_sparse_inventory_manifest_v1"
FINAL_VERIFICATION_SCHEMA_VERSION = "canonical_5m_backfill_final_verification_v1"
REST_INTENT_MANIFEST_SCHEMA_VERSION = "canonical_5m_rest_intent_manifest_v1"
BINANCE_USDM_REST_BASE_URL = "https://fapi.binance.com"
BINANCE_KLINE_PATH = "/fapi/v1/klines"
MAX_BINANCE_PAGE_ROWS = 1_000
MAX_RUN_PAGES = 1_000
MAX_RUN_SLOTS = 1_000_000
MAX_AUTHORITY_RECEIPTS_PER_JOB = 256
MAX_APPEND_ATTEMPTS_PER_PAGE = 16
MAX_RESPONSE_BYTES = 64 * 1024 * 1024
MAX_SQLITE_INTEGER = (1 << 63) - 1
MAX_LOCAL_REQUEST_WEIGHT_PER_UTC_MINUTE = 120
MAX_REQUEST_WEIGHT_PER_RUN = 120
MIN_HTTP_429_COOLDOWN_SECONDS = 120
MIN_HTTP_418_COOLDOWN_SECONDS = 1_800
EXPECTED_BACKFILL_SCHEMA_SHA256 = "b2f2176c6e96b08a5f532f53acde40a89410cdeebd1f3db77b3548ca3281e8dc"

MAX_WSS_INACTIVE_PROBE_AGE_MS = 30_000


class Historical5mBackfillError(RuntimeError):
    """Fail-closed historical backfill contract error."""


class Historical5mBackfillPaused(Historical5mBackfillError):
    """Safe resumable pause, normally caused by a durable cooldown."""


def historical_backfill_sqlite_artifact_paths(path: Path) -> tuple[Path, ...]:
    """Resolve a SQLite file and every path SQLite or our writer lease may own."""

    primary = Path(path).expanduser().resolve()
    candidates = (
        primary,
        Path(str(primary) + "-wal"),
        Path(str(primary) + "-shm"),
        Path(str(primary) + "-journal"),
        canonical_5m_archive_writer_lease_path(primary),
    )
    return tuple(candidate.resolve() for candidate in candidates)


def historical_backfill_paths_alias(left: Path, right: Path) -> bool:
    """Detect resolved-name, symlink, and existing hard-link aliases."""

    resolved_left = Path(left).expanduser().resolve()
    resolved_right = Path(right).expanduser().resolve()
    if resolved_left == resolved_right:
        return True
    try:
        left_stat = os.stat(resolved_left, follow_symlinks=True)
        right_stat = os.stat(resolved_right, follow_symlinks=True)
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise Historical5mBackfillError("backfill_runtime_path_identity_unreadable") from exc
    return (left_stat.st_dev, left_stat.st_ino) == (right_stat.st_dev, right_stat.st_ino)


def validate_historical_backfill_state_path(
    *,
    state_path: Path,
    archive_path: Path,
) -> Path:
    """Reject every state/archive main-file, sidecar, lease, or hard-link alias."""

    resolved_state = Path(state_path).expanduser().resolve()
    archive_artifacts = historical_backfill_sqlite_artifact_paths(archive_path)
    state_artifacts = historical_backfill_sqlite_artifact_paths(resolved_state)
    if any(
        historical_backfill_paths_alias(state_artifact, archive_artifact)
        for state_artifact in state_artifacts
        for archive_artifact in archive_artifacts
    ):
        raise Historical5mBackfillError(
            "historical_backfill_state_path_collides_with_archive_artifact"
        )
    return resolved_state


@dataclass(frozen=True)
class WssAuthorityCutoffAttestation:
    """Operator-provided authorization; no authentication is claimed here."""

    attestation_id: str
    archive_path: Path
    authority_cutoff_open_time_ms: int
    attested_at_ms: int
    valid_until_ms: int
    producer_worker_id: str = "v2_binance_kline_wss_loop"
    producer_archive_writes_inactive: bool = False
    operator_authorized: bool = False

    def validated(self, *, observed_at_ms: int) -> WssAuthorityCutoffAttestation:
        attestation_id = str(self.attestation_id).strip()
        if not attestation_id or len(attestation_id) > 256:
            raise Historical5mBackfillError("wss_inactive_attestation_id_invalid")
        archive_path = Path(self.archive_path).resolve()
        cutoff_ms = _strict_ms(self.authority_cutoff_open_time_ms)
        attested_ms = _strict_ms(self.attested_at_ms)
        valid_until_ms = _strict_ms(self.valid_until_ms)
        observed_ms = _strict_ms(observed_at_ms)
        if (
            cutoff_ms is None
            or cutoff_ms % LABEL_SLOT_MILLISECONDS != 0
            or attested_ms is None
            or valid_until_ms is None
            or observed_ms is None
            or not attested_ms <= observed_ms <= valid_until_ms
        ):
            raise Historical5mBackfillError("wss_inactive_cutoff_attestation_expired_or_invalid")
        if self.producer_worker_id != "v2_binance_kline_wss_loop":
            raise Historical5mBackfillError("wss_producer_identity_mismatch")
        if self.producer_archive_writes_inactive is not True:
            raise Historical5mBackfillError("wss_archive_producer_not_attested_inactive")
        if self.operator_authorized is not True:
            raise Historical5mBackfillError("wss_cutoff_not_operator_authorized")
        return WssAuthorityCutoffAttestation(
            attestation_id=attestation_id,
            archive_path=archive_path,
            authority_cutoff_open_time_ms=cutoff_ms,
            attested_at_ms=attested_ms,
            valid_until_ms=valid_until_ms,
            producer_worker_id=self.producer_worker_id,
            producer_archive_writes_inactive=True,
            operator_authorized=True,
        )

    def contract(self) -> dict[str, Any]:
        return {
            "schema_version": AUTHORITY_CUTOFF_SCHEMA_VERSION,
            "attestation_id": self.attestation_id,
            "archive_path": str(Path(self.archive_path).resolve()),
            "authority_cutoff_open_time_ms": self.authority_cutoff_open_time_ms,
            "attested_at_ms": self.attested_at_ms,
            "valid_until_ms": self.valid_until_ms,
            "producer_worker_id": self.producer_worker_id,
            "producer_archive_writes_inactive": (self.producer_archive_writes_inactive),
            "operator_authorized": self.operator_authorized,
            "attestation_origin": "OPERATOR_PROVIDED_AUTHORIZATION",
            "cryptographic_authentication_claimed": False,
            "historical_rest_authority_rule": "OPEN_TIME_STRICTLY_BEFORE_CUTOFF",
            "wss_activation_allowed_only_after_final_full_verify": True,
        }

    def authority_scope(self) -> dict[str, Any]:
        """Stable recovery scope; renewable receipt identity/clocks are excluded."""

        return {
            "schema_version": AUTHORITY_SCOPE_SCHEMA_VERSION,
            "archive_path": str(Path(self.archive_path).resolve()),
            "authority_cutoff_open_time_ms": self.authority_cutoff_open_time_ms,
            "producer_worker_id": self.producer_worker_id,
            "timeframe": "5m",
            "rest_authority_rule": "OPEN_TIME_STRICTLY_BEFORE_CUTOFF",
            "producer_archive_writes_must_be_inactive": True,
            "operator_authorization_required": True,
            "cryptographic_authentication_claimed": False,
        }

    @property
    def receipt_sha256(self) -> str:
        return stable_sha256(self.contract())

    @property
    def authority_scope_sha256(self) -> str:
        return stable_sha256(self.authority_scope())


def _authority_attestation_from_contract(
    contract: Mapping[str, Any],
    *,
    observed_at_ms: int,
) -> WssAuthorityCutoffAttestation:
    required = {
        "schema_version",
        "attestation_id",
        "archive_path",
        "authority_cutoff_open_time_ms",
        "attested_at_ms",
        "valid_until_ms",
        "producer_worker_id",
        "producer_archive_writes_inactive",
        "operator_authorized",
        "attestation_origin",
        "cryptographic_authentication_claimed",
        "historical_rest_authority_rule",
        "wss_activation_allowed_only_after_final_full_verify",
    }
    if set(contract) != required or contract.get("schema_version") != (
        AUTHORITY_CUTOFF_SCHEMA_VERSION
    ):
        raise Historical5mBackfillError("authority_receipt_contract_fields_invalid")
    try:
        attestation = WssAuthorityCutoffAttestation(
            attestation_id=contract["attestation_id"],
            archive_path=Path(contract["archive_path"]),
            authority_cutoff_open_time_ms=contract["authority_cutoff_open_time_ms"],
            attested_at_ms=contract["attested_at_ms"],
            valid_until_ms=contract["valid_until_ms"],
            producer_worker_id=contract["producer_worker_id"],
            producer_archive_writes_inactive=contract["producer_archive_writes_inactive"],
            operator_authorized=contract["operator_authorized"],
        ).validated(observed_at_ms=observed_at_ms)
    except (KeyError, TypeError, ValueError) as exc:
        raise Historical5mBackfillError("authority_receipt_contract_invalid") from exc
    if attestation.contract() != dict(contract):
        raise Historical5mBackfillError("authority_receipt_contract_mismatch")
    return attestation


@dataclass(frozen=True)
class BackfillJobSpec:
    archive_path: Path
    symbols: tuple[str, ...]
    start_open_time_ms: int
    end_open_time_ms_exclusive: int
    authority_cutoff: WssAuthorityCutoffAttestation
    page_limit: int = MAX_BINANCE_PAGE_ROWS

    def validated(self) -> BackfillJobSpec:
        archive_path = Path(self.archive_path).resolve()
        symbols = tuple(sorted({str(value).strip().upper() for value in self.symbols}))
        if not symbols:
            raise Historical5mBackfillError("backfill_symbol_universe_empty")
        if any(
            not symbol.isascii() or not symbol.isalnum() or not 2 <= len(symbol) <= 32
            for symbol in symbols
        ):
            raise Historical5mBackfillError("backfill_symbol_universe_invalid")
        start_ms = _strict_ms(self.start_open_time_ms)
        end_ms = _strict_ms(self.end_open_time_ms_exclusive)
        if (
            start_ms is None
            or end_ms is None
            or start_ms % LABEL_SLOT_MILLISECONDS != 0
            or end_ms % LABEL_SLOT_MILLISECONDS != 0
            or end_ms <= start_ms
        ):
            raise Historical5mBackfillError(
                "backfill_range_must_be_nonempty_half_open_utc_5m_slots"
            )
        page_limit = _strict_positive_int(self.page_limit)
        if page_limit is None or page_limit > MAX_BINANCE_PAGE_ROWS:
            raise Historical5mBackfillError("backfill_page_limit_invalid")
        cutoff = self.authority_cutoff.validated(
            observed_at_ms=self.authority_cutoff.attested_at_ms
        )
        if cutoff.archive_path != archive_path:
            raise Historical5mBackfillError("wss_cutoff_archive_path_mismatch")
        if cutoff.authority_cutoff_open_time_ms != end_ms:
            raise Historical5mBackfillError("backfill_end_must_equal_fixed_wss_authority_cutoff")
        return BackfillJobSpec(
            archive_path=archive_path,
            symbols=symbols,
            start_open_time_ms=start_ms,
            end_open_time_ms_exclusive=end_ms,
            authority_cutoff=cutoff,
            page_limit=page_limit,
        )

    def contract(self) -> dict[str, Any]:
        validated = self.validated()
        return {
            "schema_version": JOB_SCHEMA_VERSION,
            "archive_path": str(validated.archive_path),
            "symbols": list(validated.symbols),
            "timeframe": "5m",
            "range_semantics": "HALF_OPEN_CANDLE_OPEN_TIME_UTC",
            "start_open_time_ms": validated.start_open_time_ms,
            "end_open_time_ms_exclusive": validated.end_open_time_ms_exclusive,
            "page_limit": validated.page_limit,
            "authority_scope": validated.authority_cutoff.authority_scope(),
            "transport_role": "REST_ABSENT_SLOT_RECOVERY_ONLY",
            "websocket_archive_slots_authoritative": True,
            "live_execution_mutation": False,
            "credentials_required": False,
        }

    @property
    def job_id(self) -> str:
        return f"canonical_5m_backfill_{stable_sha256(self.contract())}"


@dataclass(frozen=True)
class BackfillRunBounds:
    max_pages: int = 4
    max_slots: int = 4_000
    local_weight_budget_per_minute: int = 120
    max_request_weight_per_run: int = 120

    def validated(self) -> BackfillRunBounds:
        max_pages = _strict_positive_int(self.max_pages)
        max_slots = _strict_positive_int(self.max_slots)
        budget = _strict_positive_int(self.local_weight_budget_per_minute)
        run_weight = _strict_positive_int(self.max_request_weight_per_run)
        if max_pages is None or max_pages > MAX_RUN_PAGES:
            raise Historical5mBackfillError("backfill_max_pages_invalid")
        if max_slots is None or max_slots > MAX_RUN_SLOTS:
            raise Historical5mBackfillError("backfill_max_slots_invalid")
        if budget is None or budget > MAX_LOCAL_REQUEST_WEIGHT_PER_UTC_MINUTE:
            raise Historical5mBackfillError("backfill_weight_budget_invalid")
        if run_weight is None or run_weight > MAX_REQUEST_WEIGHT_PER_RUN:
            raise Historical5mBackfillError("backfill_run_request_weight_invalid")
        return BackfillRunBounds(
            max_pages=max_pages,
            max_slots=max_slots,
            local_weight_budget_per_minute=budget,
            max_request_weight_per_run=run_weight,
        )


@dataclass(frozen=True)
class BinanceKlineRequest:
    symbol: str
    start_open_time_ms: int
    end_close_time_ms: int
    limit: int

    @property
    def weight(self) -> int:
        # Binance USD-M publishes tiered request weights for this endpoint.
        # Keeping pages <= 1000 deliberately avoids the highest >1000 tier.
        if (
            isinstance(self.limit, bool)
            or not isinstance(self.limit, int)
            or not 1 <= self.limit <= MAX_BINANCE_PAGE_ROWS
        ):
            raise Historical5mBackfillError("binance_kline_request_limit_invalid")
        if self.limit < 100:
            return 1
        if self.limit < 500:
            return 2
        return 5

    @property
    def query_pairs(self) -> tuple[tuple[str, str], ...]:
        return (
            ("symbol", self.symbol),
            ("interval", "5m"),
            ("startTime", str(self.start_open_time_ms)),
            ("endTime", str(self.end_close_time_ms)),
            ("limit", str(self.limit)),
        )

    @property
    def url(self) -> str:
        return (
            BINANCE_USDM_REST_BASE_URL
            + BINANCE_KLINE_PATH
            + "?"
            + urllib.parse.urlencode(self.query_pairs)
        )

    def contract(self) -> dict[str, Any]:
        return {
            "schema_version": REQUEST_SCHEMA_VERSION,
            "method": "GET",
            "scheme": "https",
            "host": "fapi.binance.com",
            "path": BINANCE_KLINE_PATH,
            "query_pairs": [list(pair) for pair in self.query_pairs],
            "url": self.url,
            "request_weight": self.weight,
            "auth_headers_present": False,
            "credentials_used": False,
            "places_orders": False,
        }

    @classmethod
    def from_contract(cls, contract: Mapping[str, Any]) -> BinanceKlineRequest:
        if contract.get("schema_version") != REQUEST_SCHEMA_VERSION:
            raise Historical5mBackfillError("stored_request_schema_mismatch")
        pairs = contract.get("query_pairs")
        if not isinstance(pairs, list):
            raise Historical5mBackfillError("stored_request_query_invalid")
        params = {
            str(pair[0]): str(pair[1])
            for pair in pairs
            if isinstance(pair, list) and len(pair) == 2
        }
        try:
            request = cls(
                symbol=params["symbol"],
                start_open_time_ms=int(params["startTime"]),
                end_close_time_ms=int(params["endTime"]),
                limit=int(params["limit"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise Historical5mBackfillError("stored_request_query_invalid") from exc
        if request.contract() != dict(contract):
            raise Historical5mBackfillError("stored_request_contract_tampered")
        return request


@dataclass(frozen=True)
class PublicHttpResponse:
    status_code: int
    headers: Mapping[str, str]
    body: bytes
    received_at_ms: int


class PublicKlineTransport(Protocol):
    def fetch(self, request: BinanceKlineRequest) -> PublicHttpResponse: ...


class _RejectRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Make every redirect terminal so only the validated exact endpoint is reached."""

    def redirect_request(
        self,
        req: Any,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        return None


class UrllibPublicKlineTransport:
    """Credential-free transport for one fixed public market-data endpoint."""

    def __init__(self, *, timeout_seconds: float, clock_ms: Callable[[], int]) -> None:
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, int | float)
            or not math.isfinite(float(timeout_seconds))
            or timeout_seconds <= 0.0
            or timeout_seconds > 60.0
        ):
            raise Historical5mBackfillError("backfill_http_timeout_invalid")
        self.timeout_seconds = float(timeout_seconds)
        self.clock_ms = clock_ms
        self._opener = urllib.request.build_opener(_RejectRedirectHandler())

    def fetch(self, request: BinanceKlineRequest) -> PublicHttpResponse:
        _ = request.weight
        url = request.url
        parsed = urllib.parse.urlparse(url)
        if (
            parsed.scheme != "https"
            or parsed.netloc != "fapi.binance.com"
            or parsed.path != BINANCE_KLINE_PATH
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise Historical5mBackfillError("refused_non_public_binance_kline_url")
        http_request = urllib.request.Request(  # noqa: S310 - URL allowlisted above
            url,
            method="GET",
            headers={
                "Accept": "application/json",
                "User-Agent": "v2-canonical-5m-label-gap-recovery/1.0",
            },
        )
        try:
            with self._opener.open(  # noqa: S310 - URL allowlisted above
                http_request,
                timeout=self.timeout_seconds,
            ) as response:
                return PublicHttpResponse(
                    status_code=int(response.status),
                    headers={str(k).lower(): str(v) for k, v in response.headers.items()},
                    body=response.read(MAX_RESPONSE_BYTES + 1),
                    received_at_ms=int(self.clock_ms()),
                )
        except urllib.error.HTTPError as exc:
            return PublicHttpResponse(
                status_code=int(exc.code),
                headers={str(k).lower(): str(v) for k, v in (exc.headers or {}).items()},
                body=exc.read(MAX_RESPONSE_BYTES + 1),
                received_at_ms=int(self.clock_ms()),
            )


class LocalWeightGovernor:
    """Bound both one run and each observed UTC-minute request-weight window."""

    def __init__(self, *, budget_per_minute: int, max_weight_per_run: int) -> None:
        self.budget_per_utc_minute = int(budget_per_minute)
        self.max_weight_per_run = int(max_weight_per_run)
        self.request_weight_reserved_this_run = 0
        self.request_weight_reserved_current_utc_minute = 0
        self.current_utc_minute: int | None = None
        self.last_observed_at_ms: int | None = None

    def reserve(self, request: BinanceKlineRequest, *, observed_at_ms: int) -> None:
        observed_ms = _strict_ms(observed_at_ms)
        if observed_ms is None:
            raise Historical5mBackfillError("local_request_weight_clock_invalid")
        if self.last_observed_at_ms is not None and observed_ms < self.last_observed_at_ms:
            raise Historical5mBackfillError("local_request_weight_clock_moved_backward")
        observed_minute = observed_ms // 60_000
        if self.current_utc_minute is None or observed_minute > self.current_utc_minute:
            self.current_utc_minute = observed_minute
            self.request_weight_reserved_current_utc_minute = 0
        self.last_observed_at_ms = observed_ms
        if self.request_weight_reserved_this_run + request.weight > self.max_weight_per_run:
            raise Historical5mBackfillPaused("local_request_weight_run_budget_exhausted")
        if (
            self.request_weight_reserved_current_utc_minute + request.weight
            > self.budget_per_utc_minute
        ):
            raise Historical5mBackfillPaused("local_request_weight_utc_minute_budget_exhausted")
        self.request_weight_reserved_this_run += request.weight
        self.request_weight_reserved_current_utc_minute += request.weight

    def observe(self, response: PublicHttpResponse) -> None:
        normalized = {str(k).lower(): str(v) for k, v in response.headers.items()}
        raw_used = normalized.get("x-mbx-used-weight-1m")
        if raw_used is None:
            return
        try:
            used = int(raw_used)
        except ValueError as exc:
            raise Historical5mBackfillError("binance_used_weight_header_invalid") from exc
        if used < 0:
            raise Historical5mBackfillError("binance_used_weight_header_invalid")
        if used >= self.budget_per_utc_minute:
            raise Historical5mBackfillPaused("server_reported_weight_reached_local_safety_budget")


def _strict_ms(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value >= 1_000_000_000_000 else None


def _strict_positive_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _retry_after_ms(response: PublicHttpResponse) -> int:
    if response.status_code not in {418, 429}:
        raise Historical5mBackfillError("retry_after_requested_for_non_rate_limit_response")
    received_at_ms = _strict_ms(response.received_at_ms)
    if received_at_ms is None:
        raise Historical5mBackfillError("rate_limit_response_clock_invalid")
    normalized = {str(k).lower(): str(v) for k, v in response.headers.items()}
    raw = normalized.get("retry-after")
    floor_seconds = (
        MIN_HTTP_418_COOLDOWN_SECONDS
        if response.status_code == 418
        else MIN_HTTP_429_COOLDOWN_SECONDS
    )
    try:
        parsed = float(raw) if raw is not None else float(floor_seconds)
    except (TypeError, ValueError):
        parsed = float(floor_seconds)
    if not math.isfinite(parsed) or parsed < 0.0:
        parsed = float(floor_seconds)
    seconds = max(float(floor_seconds), parsed)
    if seconds >= (MAX_SQLITE_INTEGER - received_at_ms) / 1_000.0:
        return MAX_SQLITE_INTEGER
    return int(received_at_ms + math.ceil(seconds * 1000.0))


_CURRENT_INTEGRITY_PROOF_FIELDS = (
    "archive_integrity_verified",
    "schema_version",
    "archive_path",
    "retention_policy",
    "automatic_pruning_enabled",
    "verified_rows",
    "archive_chain_sha256",
    "verified_append_receipts",
    "verified_postcommit_readback_receipts",
    "verified_max_sequence",
)


def _compact_integrity_proof(proof: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(proof, Mapping):
        raise Historical5mBackfillError("final_integrity_proof_header_missing")
    compact = {field: proof.get(field) for field in _CURRENT_INTEGRITY_PROOF_FIELDS}
    if any(field not in proof for field in _CURRENT_INTEGRITY_PROOF_FIELDS):
        raise Historical5mBackfillError("final_integrity_proof_header_incomplete")
    return compact


def _validated_inactive_probe(
    *,
    probe: Mapping[str, Any],
    spec: BackfillJobSpec,
    observed_at_ms: int,
) -> dict[str, Any]:
    if not isinstance(probe, Mapping):
        raise Historical5mBackfillError("wss_inactive_runtime_probe_missing")
    normalized = dict(probe)
    if normalized.get("wss_archive_producer_inactive") is not True:
        raise Historical5mBackfillError("wss_archive_producer_runtime_active")
    if normalized.get("producer_worker_id") != "v2_binance_kline_wss_loop":
        raise Historical5mBackfillError("wss_runtime_probe_identity_mismatch")
    if str(normalized.get("archive_path") or "") != str(spec.archive_path.resolve()):
        raise Historical5mBackfillError("wss_runtime_probe_archive_path_mismatch")
    if (
        normalized.get("process_probe_role") != "SECONDARY_EVIDENCE_ONLY"
        or normalized.get("shared_exact_archive_writer_lease_is_primary") is not True
    ):
        raise Historical5mBackfillError("wss_runtime_probe_writer_exclusion_authority_invalid")
    probe_ms = _strict_ms(normalized.get("observed_at_ms"))
    if (
        probe_ms is None
        or probe_ms > observed_at_ms
        or observed_at_ms - probe_ms > MAX_WSS_INACTIVE_PROBE_AGE_MS
    ):
        raise Historical5mBackfillError("wss_runtime_probe_clock_invalid")
    active_pids = normalized.get("active_process_ids")
    if not isinstance(active_pids, list) or active_pids:
        raise Historical5mBackfillError("wss_runtime_probe_active_process_detected")
    normalized["authority_cutoff_open_time_ms"] = (
        spec.authority_cutoff.authority_cutoff_open_time_ms
    )
    normalized["authority_scope_sha256"] = spec.authority_cutoff.authority_scope_sha256
    normalized["authority_receipt_sha256"] = spec.authority_cutoff.receipt_sha256
    normalized["probe_sha256"] = stable_sha256(
        {key: value for key, value in normalized.items() if key != "probe_sha256"}
    )
    return normalized


def _capture_inactive_probe(
    *,
    probe_callback: Callable[[], Mapping[str, Any]],
    spec: BackfillJobSpec,
    clock_ms: Callable[[], int],
) -> tuple[int, dict[str, Any]]:
    raw_probe = probe_callback()
    observed_at_ms = int(clock_ms())
    if _strict_ms(observed_at_ms) is None:
        raise Historical5mBackfillError("backfill_runtime_clock_invalid")
    spec.authority_cutoff.validated(observed_at_ms=observed_at_ms)
    return observed_at_ms, _validated_inactive_probe(
        probe=raw_probe,
        spec=spec,
        observed_at_ms=observed_at_ms,
    )


def _backfill_schema_fingerprint(connection: sqlite3.Connection) -> str | None:
    rows = list(
        connection.execute(
            """
            SELECT type, name, tbl_name, sql
            FROM sqlite_master
            WHERE name LIKE 'backfill_%' AND sql IS NOT NULL
            ORDER BY type, name
            """
        )
    )
    if not rows:
        return None
    material = [
        {
            "type": str(row[0]),
            "name": str(row[1]),
            "table": str(row[2]),
            "sql": " ".join(str(row[3]).split()),
        }
        for row in rows
    ]
    return stable_sha256(material)


class Historical5mBackfillStore:
    """Crash-safe request/response outbox and per-slot completion receipts."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(self.path), timeout=60.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=60000")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    def _preflight_existing_schema_read_only(self) -> None:
        if not self.path.exists():
            return
        try:
            connection = sqlite3.connect(
                self.path.expanduser().resolve().as_uri() + "?mode=ro",
                uri=True,
                timeout=60.0,
            )
        except sqlite3.Error as exc:
            raise Historical5mBackfillError(
                "historical_backfill_state_read_only_preflight_failed"
            ) from exc
        try:
            foreign_objects = connection.execute(
                """
                SELECT name FROM sqlite_master
                WHERE sql IS NOT NULL
                  AND name NOT LIKE 'sqlite_%'
                  AND name NOT LIKE 'backfill_%'
                LIMIT 1
                """
            ).fetchone()
            if foreign_objects is not None:
                raise Historical5mBackfillError(
                    "historical_backfill_state_path_contains_foreign_schema"
                )
            fingerprint = _backfill_schema_fingerprint(connection)
            if fingerprint is None:
                return
            if fingerprint != EXPECTED_BACKFILL_SCHEMA_SHA256:
                raise Historical5mBackfillError(
                    "historical_backfill_state_schema_migration_required"
                )
            legacy_job = connection.execute(
                """
                SELECT 1 FROM backfill_jobs
                WHERE schema_version != ? OR schema_version IS NULL
                LIMIT 1
                """,
                (OUTBOX_SCHEMA_VERSION,),
            ).fetchone()
            if legacy_job is not None:
                raise Historical5mBackfillError(
                    "historical_backfill_state_schema_migration_required"
                )
        except sqlite3.Error as exc:
            raise Historical5mBackfillError(
                "historical_backfill_state_schema_migration_required"
            ) from exc
        finally:
            connection.close()

    def initialize(self) -> None:
        self._preflight_existing_schema_read_only()
        connection = self._connect()
        try:
            pages_table_exists = connection.execute(
                """
                SELECT 1 FROM sqlite_master
                WHERE type = 'table' AND name = 'backfill_pages'
                """
            ).fetchone()
            if pages_table_exists is not None:
                page_columns = {
                    str(row["name"])
                    for row in connection.execute("PRAGMA table_info(backfill_pages)")
                }
                required_columns = {
                    "inventory_page_id",
                    "coverage_sha256",
                    "proven_absent_close_times_json",
                    "append_attempted_at_ms",
                }
                if not required_columns.issubset(page_columns):
                    raise Historical5mBackfillError(
                        "historical_backfill_state_schema_migration_required"
                    )
            inventory_table_exists = connection.execute(
                """
                SELECT 1 FROM sqlite_master
                WHERE type = 'table' AND name = 'backfill_inventory_pages'
                """
            ).fetchone()
            if inventory_table_exists is not None:
                inventory_columns = {
                    str(row["name"])
                    for row in connection.execute("PRAGMA table_info(backfill_inventory_pages)")
                }
                if not {
                    "inactive_probe_sha256",
                    "inactive_probe_json",
                }.issubset(inventory_columns):
                    raise Historical5mBackfillError(
                        "historical_backfill_state_schema_migration_required"
                    )
            cursor_table_exists = connection.execute(
                "SELECT 1 FROM sqlite_master "
                "WHERE type = 'table' AND name = 'backfill_symbol_cursors'"
            ).fetchone()
            if cursor_table_exists is not None:
                cursor_columns = {
                    str(row["name"])
                    for row in connection.execute("PRAGMA table_info(backfill_symbol_cursors)")
                }
                if "next_inventory_page_index" not in cursor_columns:
                    raise Historical5mBackfillError(
                        "historical_backfill_state_schema_migration_required"
                    )
            for table_name in (
                "backfill_inventory_manifests",
                "backfill_rest_intent_manifests",
                "backfill_final_verifications",
            ):
                table_exists = connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                    (table_name,),
                ).fetchone()
                if table_exists is not None:
                    columns = {
                        str(row["name"])
                        for row in connection.execute(f"PRAGMA table_info({table_name})")
                    }
                    if not {"header_sha256", "header_json"}.issubset(columns):
                        raise Historical5mBackfillError(
                            "historical_backfill_state_schema_migration_required"
                        )
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS backfill_jobs (
                    job_id TEXT PRIMARY KEY,
                    schema_version TEXT NOT NULL,
                    contract_sha256 TEXT NOT NULL,
                    contract_json TEXT NOT NULL,
                    created_at_ms INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS backfill_authority_receipts (
                    job_id TEXT NOT NULL,
                    receipt_sha256 TEXT NOT NULL,
                    attestation_id TEXT NOT NULL,
                    authority_scope_sha256 TEXT NOT NULL,
                    receipt_json TEXT NOT NULL,
                    attested_at_ms INTEGER NOT NULL,
                    valid_until_ms INTEGER NOT NULL,
                    first_observed_at_ms INTEGER NOT NULL,
                    PRIMARY KEY(job_id, receipt_sha256),
                    UNIQUE(job_id, attestation_id),
                    FOREIGN KEY(job_id) REFERENCES backfill_jobs(job_id)
                );
                CREATE TABLE IF NOT EXISTS backfill_symbol_cursors (
                    job_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    next_inventory_page_index INTEGER NOT NULL DEFAULT 0,
                    next_open_time_ms INTEGER NOT NULL,
                    end_open_time_ms_exclusive INTEGER NOT NULL,
                    complete INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(job_id, symbol),
                    FOREIGN KEY(job_id) REFERENCES backfill_jobs(job_id)
                );
                CREATE TABLE IF NOT EXISTS backfill_pages (
                    page_id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    start_open_time_ms INTEGER NOT NULL,
                    end_open_time_ms INTEGER NOT NULL,
                    requested_rows INTEGER NOT NULL,
                    request_sha256 TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    inventory_page_id TEXT NOT NULL,
                    coverage_sha256 TEXT NOT NULL,
                    proven_absent_close_times_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    response_body BLOB,
                    response_sha256 TEXT,
                    response_received_at_ms INTEGER,
                    retry_not_before_ms INTEGER,
                    last_error TEXT,
                    append_attempted_at_ms INTEGER,
                    FOREIGN KEY(job_id) REFERENCES backfill_jobs(job_id)
                );
                CREATE TABLE IF NOT EXISTS backfill_append_attempts (
                    attempt_id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    page_id TEXT NOT NULL,
                    attempt_ordinal INTEGER NOT NULL,
                    authority_receipt_sha256 TEXT NOT NULL,
                    inactive_probe_sha256 TEXT NOT NULL,
                    inactive_probe_json TEXT NOT NULL,
                    attempted_at_ms INTEGER NOT NULL,
                    UNIQUE(page_id, attempt_ordinal),
                    FOREIGN KEY(job_id) REFERENCES backfill_jobs(job_id),
                    FOREIGN KEY(page_id) REFERENCES backfill_pages(page_id),
                    FOREIGN KEY(job_id, authority_receipt_sha256)
                        REFERENCES backfill_authority_receipts(job_id, receipt_sha256)
                );
                CREATE TABLE IF NOT EXISTS backfill_append_attempt_resolutions (
                    attempt_id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    page_id TEXT NOT NULL,
                    resolution_kind TEXT NOT NULL,
                    resolution_evidence_sha256 TEXT NOT NULL,
                    resolution_evidence_json TEXT NOT NULL,
                    reconciliation_authority_receipt_sha256 TEXT NOT NULL,
                    reconciliation_probe_sha256 TEXT NOT NULL,
                    reconciliation_probe_json TEXT NOT NULL,
                    resolved_at_ms INTEGER NOT NULL,
                    FOREIGN KEY(attempt_id) REFERENCES backfill_append_attempts(attempt_id),
                    FOREIGN KEY(job_id) REFERENCES backfill_jobs(job_id),
                    FOREIGN KEY(page_id) REFERENCES backfill_pages(page_id),
                    FOREIGN KEY(job_id, reconciliation_authority_receipt_sha256)
                        REFERENCES backfill_authority_receipts(job_id, receipt_sha256)
                );
                CREATE TABLE IF NOT EXISTS backfill_outbox_rows (
                    page_id TEXT NOT NULL,
                    job_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    candle_open_time_ms INTEGER NOT NULL,
                    candle_close_time_ms INTEGER NOT NULL,
                    payload_sha256 TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    archive_transaction_id TEXT,
                    archive_append_receipt_sha256 TEXT,
                    terminal_receipt_sha256 TEXT,
                    terminal_receipt_json TEXT,
                    PRIMARY KEY(page_id, candle_open_time_ms),
                    UNIQUE(job_id, symbol, candle_open_time_ms),
                    FOREIGN KEY(page_id) REFERENCES backfill_pages(page_id),
                    FOREIGN KEY(job_id) REFERENCES backfill_jobs(job_id)
                );
                CREATE TABLE IF NOT EXISTS backfill_slot_receipts (
                    job_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    candle_open_time_ms INTEGER NOT NULL,
                    candle_close_time_ms INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    archive_source TEXT,
                    archive_payload_sha256 TEXT,
                    receipt_sha256 TEXT NOT NULL,
                    receipt_json TEXT NOT NULL,
                    PRIMARY KEY(job_id, symbol, candle_open_time_ms),
                    FOREIGN KEY(job_id) REFERENCES backfill_jobs(job_id)
                );
                CREATE TABLE IF NOT EXISTS backfill_inventory_checkpoints (
                    job_id TEXT PRIMARY KEY,
                    integrity_proof_sha256 TEXT NOT NULL,
                    integrity_proof_json TEXT NOT NULL,
                    authority_attestation_sha256 TEXT NOT NULL,
                    authority_attestation_json TEXT NOT NULL,
                    authority_scope_sha256 TEXT NOT NULL,
                    inactive_probe_sha256 TEXT NOT NULL,
                    inactive_probe_json TEXT NOT NULL,
                    initialization_receipt_sha256 TEXT,
                    initialization_receipt_json TEXT,
                    sealed_at_ms INTEGER NOT NULL,
                    FOREIGN KEY(job_id) REFERENCES backfill_jobs(job_id)
                );
                CREATE TABLE IF NOT EXISTS backfill_inventory_pages (
                    inventory_page_id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    page_index INTEGER NOT NULL,
                    start_close_time_ms INTEGER NOT NULL,
                    end_close_time_ms INTEGER NOT NULL,
                    expected_close_times_json TEXT NOT NULL,
                    occupied_payloads_json TEXT NOT NULL,
                    proven_absent_close_times_json TEXT NOT NULL,
                    coverage_sha256 TEXT NOT NULL,
                    coverage_proof_sha256 TEXT NOT NULL,
                    coverage_proof_json TEXT NOT NULL,
                    integrity_proof_sha256 TEXT NOT NULL,
                    inactive_probe_sha256 TEXT NOT NULL,
                    inactive_probe_json TEXT NOT NULL,
                    sealed_at_ms INTEGER NOT NULL,
                    UNIQUE(job_id, symbol, page_index),
                    FOREIGN KEY(job_id) REFERENCES backfill_jobs(job_id)
                );
                CREATE TABLE IF NOT EXISTS backfill_inventory_manifests (
                    job_id TEXT PRIMARY KEY,
                    manifest_sha256 TEXT NOT NULL,
                    manifest_json TEXT NOT NULL,
                    header_sha256 TEXT NOT NULL,
                    header_json TEXT NOT NULL,
                    sealed_at_ms INTEGER NOT NULL,
                    FOREIGN KEY(job_id) REFERENCES backfill_jobs(job_id)
                );
                CREATE TABLE IF NOT EXISTS backfill_rest_intent_manifests (
                    job_id TEXT PRIMARY KEY,
                    manifest_sha256 TEXT NOT NULL,
                    manifest_json TEXT NOT NULL,
                    header_sha256 TEXT NOT NULL,
                    header_json TEXT NOT NULL,
                    sealed_at_ms INTEGER NOT NULL,
                    FOREIGN KEY(job_id) REFERENCES backfill_jobs(job_id)
                );
                CREATE TABLE IF NOT EXISTS backfill_archive_transactions (
                    transaction_id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    page_id TEXT NOT NULL,
                    result_sha256 TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    inserted_rows INTEGER NOT NULL,
                    duplicate_rows INTEGER NOT NULL,
                    recorded_at_ms INTEGER NOT NULL,
                    UNIQUE(page_id),
                    FOREIGN KEY(job_id) REFERENCES backfill_jobs(job_id),
                    FOREIGN KEY(page_id) REFERENCES backfill_pages(page_id)
                );
                CREATE TABLE IF NOT EXISTS backfill_recovered_append_intents (
                    page_id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    recovered_rows INTEGER NOT NULL,
                    evidence_sha256 TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    recovered_at_ms INTEGER NOT NULL,
                    FOREIGN KEY(job_id) REFERENCES backfill_jobs(job_id),
                    FOREIGN KEY(page_id) REFERENCES backfill_pages(page_id)
                );
                CREATE TABLE IF NOT EXISTS backfill_final_verifications (
                    job_id TEXT PRIMARY KEY,
                    verification_sha256 TEXT NOT NULL,
                    verification_json TEXT NOT NULL,
                    header_sha256 TEXT NOT NULL,
                    header_json TEXT NOT NULL,
                    verified_at_ms INTEGER NOT NULL,
                    FOREIGN KEY(job_id) REFERENCES backfill_jobs(job_id)
                );
                CREATE TABLE IF NOT EXISTS backfill_job_progress (
                    job_id TEXT PRIMARY KEY,
                    inventory_checkpoint_sealed INTEGER NOT NULL DEFAULT 0,
                    authority_receipt_count INTEGER NOT NULL DEFAULT 0,
                    append_attempt_count INTEGER NOT NULL DEFAULT 0,
                    append_attempt_resolution_count INTEGER NOT NULL DEFAULT 0,
                    inventory_pages_sealed INTEGER NOT NULL DEFAULT 0,
                    inventory_manifest_sealed INTEGER NOT NULL DEFAULT 0,
                    rest_intent_manifest_sealed INTEGER NOT NULL DEFAULT 0,
                    page_intent_count INTEGER NOT NULL DEFAULT 0,
                    page_prepared_count INTEGER NOT NULL DEFAULT 0,
                    page_complete_count INTEGER NOT NULL DEFAULT 0,
                    slot_receipt_total INTEGER NOT NULL DEFAULT 0,
                    archive_transaction_count INTEGER NOT NULL DEFAULT 0,
                    archive_inserted_rows INTEGER NOT NULL DEFAULT 0,
                    recovered_append_count INTEGER NOT NULL DEFAULT 0,
                    recovered_rows INTEGER NOT NULL DEFAULT 0,
                    final_verification_sealed INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY(job_id) REFERENCES backfill_jobs(job_id)
                );
                CREATE TABLE IF NOT EXISTS backfill_slot_receipt_status_counts (
                    job_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    receipt_count INTEGER NOT NULL,
                    PRIMARY KEY(job_id, status),
                    FOREIGN KEY(job_id) REFERENCES backfill_jobs(job_id)
                );
                CREATE INDEX IF NOT EXISTS backfill_pages_job_status_start_page_v3
                    ON backfill_pages(job_id, status, start_open_time_ms, page_id);
                CREATE INDEX IF NOT EXISTS backfill_outbox_page_status
                    ON backfill_outbox_rows(page_id, status, candle_open_time_ms);
                CREATE INDEX IF NOT EXISTS backfill_append_attempts_page_ordinal_v3
                    ON backfill_append_attempts(page_id, attempt_ordinal DESC);
                CREATE TRIGGER IF NOT EXISTS backfill_job_progress_initialize
                AFTER INSERT ON backfill_jobs
                BEGIN
                    INSERT INTO backfill_job_progress(job_id) VALUES (NEW.job_id);
                END;
                CREATE TRIGGER IF NOT EXISTS backfill_progress_checkpoint_insert
                AFTER INSERT ON backfill_inventory_checkpoints
                BEGIN
                    UPDATE backfill_job_progress
                    SET inventory_checkpoint_sealed = 1 WHERE job_id = NEW.job_id;
                END;
                CREATE TRIGGER IF NOT EXISTS backfill_progress_authority_receipt_insert
                AFTER INSERT ON backfill_authority_receipts
                BEGIN
                    UPDATE backfill_job_progress
                    SET authority_receipt_count = authority_receipt_count + 1
                    WHERE job_id = NEW.job_id;
                END;
                CREATE TRIGGER IF NOT EXISTS backfill_progress_append_attempt_insert
                AFTER INSERT ON backfill_append_attempts
                BEGIN
                    UPDATE backfill_job_progress
                    SET append_attempt_count = append_attempt_count + 1
                    WHERE job_id = NEW.job_id;
                END;
                CREATE TRIGGER IF NOT EXISTS backfill_progress_append_resolution_insert
                AFTER INSERT ON backfill_append_attempt_resolutions
                BEGIN
                    UPDATE backfill_job_progress
                    SET append_attempt_resolution_count =
                        append_attempt_resolution_count + 1
                    WHERE job_id = NEW.job_id;
                END;
                CREATE TRIGGER IF NOT EXISTS backfill_progress_inventory_page_insert
                AFTER INSERT ON backfill_inventory_pages
                BEGIN
                    UPDATE backfill_job_progress
                    SET inventory_pages_sealed = inventory_pages_sealed + 1
                    WHERE job_id = NEW.job_id;
                END;
                CREATE TRIGGER IF NOT EXISTS backfill_progress_inventory_manifest_insert
                AFTER INSERT ON backfill_inventory_manifests
                BEGIN
                    UPDATE backfill_job_progress
                    SET inventory_manifest_sealed = 1 WHERE job_id = NEW.job_id;
                END;
                CREATE TRIGGER IF NOT EXISTS backfill_progress_rest_manifest_insert
                AFTER INSERT ON backfill_rest_intent_manifests
                BEGIN
                    UPDATE backfill_job_progress
                    SET rest_intent_manifest_sealed = 1 WHERE job_id = NEW.job_id;
                END;
                CREATE TRIGGER IF NOT EXISTS backfill_progress_page_insert
                AFTER INSERT ON backfill_pages
                BEGIN
                    UPDATE backfill_job_progress SET
                        page_intent_count = page_intent_count + (NEW.status = 'INTENT'),
                        page_prepared_count = page_prepared_count + (NEW.status = 'PREPARED'),
                        page_complete_count = page_complete_count + (NEW.status = 'COMPLETE')
                    WHERE job_id = NEW.job_id;
                END;
                CREATE TRIGGER IF NOT EXISTS backfill_progress_page_status_update
                AFTER UPDATE OF status ON backfill_pages
                WHEN OLD.status != NEW.status
                BEGIN
                    UPDATE backfill_job_progress SET
                        page_intent_count = page_intent_count
                            - (OLD.status = 'INTENT') + (NEW.status = 'INTENT'),
                        page_prepared_count = page_prepared_count
                            - (OLD.status = 'PREPARED') + (NEW.status = 'PREPARED'),
                        page_complete_count = page_complete_count
                            - (OLD.status = 'COMPLETE') + (NEW.status = 'COMPLETE')
                    WHERE job_id = NEW.job_id;
                END;
                CREATE TRIGGER IF NOT EXISTS backfill_progress_slot_receipt_insert
                AFTER INSERT ON backfill_slot_receipts
                BEGIN
                    UPDATE backfill_job_progress
                    SET slot_receipt_total = slot_receipt_total + 1
                    WHERE job_id = NEW.job_id;
                    INSERT INTO backfill_slot_receipt_status_counts(
                        job_id, status, receipt_count
                    ) VALUES (NEW.job_id, NEW.status, 1)
                    ON CONFLICT(job_id, status) DO UPDATE SET
                        receipt_count = receipt_count + 1;
                END;
                CREATE TRIGGER IF NOT EXISTS backfill_progress_archive_transaction_insert
                AFTER INSERT ON backfill_archive_transactions
                BEGIN
                    UPDATE backfill_job_progress SET
                        archive_transaction_count = archive_transaction_count + 1,
                        archive_inserted_rows = archive_inserted_rows + NEW.inserted_rows
                    WHERE job_id = NEW.job_id;
                END;
                CREATE TRIGGER IF NOT EXISTS backfill_progress_recovered_insert
                AFTER INSERT ON backfill_recovered_append_intents
                BEGIN
                    UPDATE backfill_job_progress SET
                        recovered_append_count = recovered_append_count + 1,
                        recovered_rows = recovered_rows + NEW.recovered_rows
                    WHERE job_id = NEW.job_id;
                END;
                CREATE TRIGGER IF NOT EXISTS backfill_progress_final_insert
                AFTER INSERT ON backfill_final_verifications
                BEGIN
                    UPDATE backfill_job_progress
                    SET final_verification_sealed = 1 WHERE job_id = NEW.job_id;
                END;
                CREATE TRIGGER IF NOT EXISTS backfill_pages_request_immutable
                BEFORE UPDATE OF job_id, symbol, start_open_time_ms,
                    end_open_time_ms, requested_rows, request_sha256,
                    request_json, inventory_page_id, coverage_sha256,
                    proven_absent_close_times_json ON backfill_pages
                BEGIN
                    SELECT RAISE(ABORT, 'backfill_page_request_is_immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS backfill_outbox_payload_immutable
                BEFORE UPDATE OF page_id, job_id, symbol,
                    candle_open_time_ms, candle_close_time_ms,
                    payload_sha256, payload_json ON backfill_outbox_rows
                BEGIN
                    SELECT RAISE(ABORT, 'backfill_outbox_payload_is_immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS backfill_page_no_delete
                BEFORE DELETE ON backfill_pages
                BEGIN
                    SELECT RAISE(ABORT, 'backfill_page_is_durable');
                END;
                CREATE TRIGGER IF NOT EXISTS backfill_outbox_no_delete
                BEFORE DELETE ON backfill_outbox_rows
                BEGIN
                    SELECT RAISE(ABORT, 'backfill_outbox_is_durable');
                END;
                CREATE TRIGGER IF NOT EXISTS backfill_page_status_transition_valid
                BEFORE UPDATE OF status ON backfill_pages
                WHEN NOT (
                    OLD.status = NEW.status
                    OR (OLD.status = 'INTENT' AND NEW.status = 'PREPARED')
                    OR (OLD.status = 'PREPARED' AND NEW.status = 'COMPLETE')
                )
                BEGIN
                    SELECT RAISE(ABORT, 'backfill_page_status_transition_invalid');
                END;
                CREATE TRIGGER IF NOT EXISTS backfill_slot_receipt_immutable
                BEFORE UPDATE ON backfill_slot_receipts
                BEGIN
                    SELECT RAISE(ABORT, 'backfill_slot_receipt_is_immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS backfill_slot_receipt_no_delete
                BEFORE DELETE ON backfill_slot_receipts
                BEGIN
                    SELECT RAISE(ABORT, 'backfill_slot_receipt_is_immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS backfill_checkpoint_immutable
                BEFORE UPDATE ON backfill_inventory_checkpoints
                BEGIN
                    SELECT RAISE(ABORT, 'backfill_inventory_checkpoint_immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS backfill_authority_receipt_immutable
                BEFORE UPDATE ON backfill_authority_receipts
                BEGIN
                    SELECT RAISE(ABORT, 'backfill_authority_receipt_immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS backfill_authority_receipt_no_delete
                BEFORE DELETE ON backfill_authority_receipts
                BEGIN
                    SELECT RAISE(ABORT, 'backfill_authority_receipt_immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS backfill_append_attempt_immutable
                BEFORE UPDATE ON backfill_append_attempts
                BEGIN
                    SELECT RAISE(ABORT, 'backfill_append_attempt_immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS backfill_append_attempt_no_delete
                BEFORE DELETE ON backfill_append_attempts
                BEGIN
                    SELECT RAISE(ABORT, 'backfill_append_attempt_immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS backfill_append_resolution_immutable
                BEFORE UPDATE ON backfill_append_attempt_resolutions
                BEGIN
                    SELECT RAISE(ABORT, 'backfill_append_attempt_resolution_immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS backfill_append_resolution_no_delete
                BEFORE DELETE ON backfill_append_attempt_resolutions
                BEGIN
                    SELECT RAISE(ABORT, 'backfill_append_attempt_resolution_immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS backfill_checkpoint_no_delete
                BEFORE DELETE ON backfill_inventory_checkpoints
                BEGIN
                    SELECT RAISE(ABORT, 'backfill_inventory_checkpoint_immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS backfill_inventory_page_immutable
                BEFORE UPDATE ON backfill_inventory_pages
                BEGIN
                    SELECT RAISE(ABORT, 'backfill_inventory_page_immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS backfill_inventory_page_no_delete
                BEFORE DELETE ON backfill_inventory_pages
                BEGIN
                    SELECT RAISE(ABORT, 'backfill_inventory_page_immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS backfill_inventory_manifest_immutable
                BEFORE UPDATE ON backfill_inventory_manifests
                BEGIN
                    SELECT RAISE(ABORT, 'backfill_inventory_manifest_immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS backfill_inventory_manifest_no_delete
                BEFORE DELETE ON backfill_inventory_manifests
                BEGIN
                    SELECT RAISE(ABORT, 'backfill_inventory_manifest_immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS backfill_rest_intent_manifest_immutable
                BEFORE UPDATE ON backfill_rest_intent_manifests
                BEGIN
                    SELECT RAISE(ABORT, 'backfill_rest_intent_manifest_immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS backfill_rest_intent_manifest_no_delete
                BEFORE DELETE ON backfill_rest_intent_manifests
                BEGIN
                    SELECT RAISE(ABORT, 'backfill_rest_intent_manifest_immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS backfill_archive_transaction_immutable
                BEFORE UPDATE ON backfill_archive_transactions
                BEGIN
                    SELECT RAISE(ABORT, 'backfill_archive_transaction_immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS backfill_archive_transaction_no_delete
                BEFORE DELETE ON backfill_archive_transactions
                BEGIN
                    SELECT RAISE(ABORT, 'backfill_archive_transaction_immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS backfill_recovered_intent_immutable
                BEFORE UPDATE ON backfill_recovered_append_intents
                BEGIN
                    SELECT RAISE(ABORT, 'backfill_recovered_intent_immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS backfill_recovered_intent_no_delete
                BEFORE DELETE ON backfill_recovered_append_intents
                BEGIN
                    SELECT RAISE(ABORT, 'backfill_recovered_intent_immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS backfill_final_verify_immutable
                BEFORE UPDATE ON backfill_final_verifications
                BEGIN
                    SELECT RAISE(ABORT, 'backfill_final_verification_immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS backfill_final_verify_no_delete
                BEFORE DELETE ON backfill_final_verifications
                BEGIN
                    SELECT RAISE(ABORT, 'backfill_final_verification_immutable');
                END;
                """
            )
            if _backfill_schema_fingerprint(connection) != EXPECTED_BACKFILL_SCHEMA_SHA256:
                raise Historical5mBackfillError(
                    "historical_backfill_state_schema_definition_mismatch"
                )
            connection.commit()
        finally:
            connection.close()

    def seal_inventory_checkpoint(
        self,
        *,
        job_id: str,
        integrity_proof: Mapping[str, Any],
        authority_attestation: Mapping[str, Any],
        inactive_probe: Mapping[str, Any],
        initialization_receipt: Mapping[str, Any] | None,
        sealed_at_ms: int,
    ) -> None:
        proof_json = canonical_json(dict(integrity_proof))
        attestation_json = canonical_json(dict(authority_attestation))
        authority_receipt_sha = _sha256_bytes(attestation_json.encode())
        checkpoint_authority = _authority_attestation_from_contract(
            authority_attestation,
            observed_at_ms=int(sealed_at_ms),
        )
        authority_scope_sha = checkpoint_authority.authority_scope_sha256
        probe_json = canonical_json(dict(inactive_probe))
        if (
            inactive_probe.get("authority_receipt_sha256") != authority_receipt_sha
            or inactive_probe.get("authority_scope_sha256") != authority_scope_sha
            or inactive_probe.get("probe_sha256")
            != stable_sha256(
                {key: value for key, value in inactive_probe.items() if key != "probe_sha256"}
            )
        ):
            raise Historical5mBackfillError("inventory_checkpoint_authority_probe_binding_invalid")
        initialization_json = (
            canonical_json(dict(initialization_receipt))
            if initialization_receipt is not None
            else None
        )
        values = (
            _sha256_bytes(proof_json.encode()),
            proof_json,
            authority_receipt_sha,
            attestation_json,
            authority_scope_sha,
            _sha256_bytes(probe_json.encode()),
            probe_json,
            _sha256_bytes(initialization_json.encode())
            if initialization_json is not None
            else None,
            initialization_json,
            int(sealed_at_ms),
        )
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM backfill_inventory_checkpoints WHERE job_id = ?",
                (job_id,),
            ).fetchone()
            if (
                existing is not None
                and tuple(
                    existing[key]
                    for key in (
                        "integrity_proof_sha256",
                        "integrity_proof_json",
                        "authority_attestation_sha256",
                        "authority_attestation_json",
                        "authority_scope_sha256",
                        "inactive_probe_sha256",
                        "inactive_probe_json",
                        "initialization_receipt_sha256",
                        "initialization_receipt_json",
                        "sealed_at_ms",
                    )
                )
                != values
            ):
                raise Historical5mBackfillError("inventory_checkpoint_is_immutable_and_conflicting")
            connection.execute(
                """
                INSERT OR IGNORE INTO backfill_inventory_checkpoints(
                    job_id, integrity_proof_sha256, integrity_proof_json,
                    authority_attestation_sha256, authority_attestation_json,
                    authority_scope_sha256,
                    inactive_probe_sha256, inactive_probe_json,
                    initialization_receipt_sha256,
                    initialization_receipt_json, sealed_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (job_id, *values),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def inventory_checkpoint(self, job_id: str) -> dict[str, Any] | None:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT * FROM backfill_inventory_checkpoints WHERE job_id = ?",
                (job_id,),
            ).fetchone()
            if row is None:
                return None
            for json_key, hash_key in (
                ("integrity_proof_json", "integrity_proof_sha256"),
                ("authority_attestation_json", "authority_attestation_sha256"),
                ("inactive_probe_json", "inactive_probe_sha256"),
            ):
                if _sha256_bytes(str(row[json_key]).encode()) != str(row[hash_key]):
                    raise Historical5mBackfillError("inventory_checkpoint_content_hash_mismatch")
            authority_contract = json.loads(str(row["authority_attestation_json"]))
            checkpoint_authority = _authority_attestation_from_contract(
                authority_contract,
                observed_at_ms=int(row["sealed_at_ms"]),
            )
            checkpoint_probe = json.loads(str(row["inactive_probe_json"]))
            if (
                checkpoint_authority.authority_scope_sha256 != str(row["authority_scope_sha256"])
                or checkpoint_probe.get("authority_receipt_sha256")
                != str(row["authority_attestation_sha256"])
                or checkpoint_probe.get("authority_scope_sha256")
                != str(row["authority_scope_sha256"])
                or checkpoint_probe.get("probe_sha256")
                != stable_sha256(
                    {key: value for key, value in checkpoint_probe.items() if key != "probe_sha256"}
                )
            ):
                raise Historical5mBackfillError("inventory_checkpoint_authority_binding_mismatch")
            initialization_json = row["initialization_receipt_json"]
            initialization_sha = row["initialization_receipt_sha256"]
            if (initialization_json is None) != (initialization_sha is None):
                raise Historical5mBackfillError(
                    "inventory_checkpoint_initialization_receipt_incomplete"
                )
            if initialization_json is not None and _sha256_bytes(
                str(initialization_json).encode()
            ) != str(initialization_sha):
                raise Historical5mBackfillError(
                    "inventory_checkpoint_initialization_receipt_hash_mismatch"
                )
            return {
                "integrity_proof_sha256": str(row["integrity_proof_sha256"]),
                "integrity_proof": json.loads(str(row["integrity_proof_json"])),
                "authority_attestation": authority_contract,
                "authority_attestation_sha256": str(row["authority_attestation_sha256"]),
                "authority_scope_sha256": str(row["authority_scope_sha256"]),
                "inactive_probe": checkpoint_probe,
                "initialization_receipt": (
                    json.loads(str(initialization_json))
                    if initialization_json is not None
                    else None
                ),
                "sealed_at_ms": int(row["sealed_at_ms"]),
            }
        finally:
            connection.close()

    def inventory_page_exists(self, inventory_page_id: str) -> bool:
        connection = self._connect()
        try:
            return (
                connection.execute(
                    "SELECT 1 FROM backfill_inventory_pages WHERE inventory_page_id = ?",
                    (inventory_page_id,),
                ).fetchone()
                is not None
            )
        finally:
            connection.close()

    def seal_inventory_page(
        self,
        *,
        inventory_page_id: str,
        job_id: str,
        symbol: str,
        page_index: int,
        expected_close_times: Sequence[int],
        occupied_rows: Sequence[Mapping[str, Any]],
        coverage_proof: Mapping[str, Any],
        integrity_proof_sha256: str,
        inactive_probe: Mapping[str, Any],
        sealed_at_ms: int,
    ) -> None:
        closes = [int(value) for value in expected_close_times]
        if not closes:
            raise Historical5mBackfillError("inventory_page_empty")
        absent = [int(value) for value in coverage_proof.get("proven_absent_close_time_ms") or []]
        coverage_sha = str(coverage_proof.get("coverage_sha256") or "")
        proof_json = canonical_json(dict(coverage_proof))
        inactive_probe_json = canonical_json(dict(inactive_probe))
        values = (
            inventory_page_id,
            job_id,
            symbol,
            int(page_index),
            closes[0],
            closes[-1],
            canonical_json(closes),
            canonical_json([dict(row) for row in occupied_rows]),
            canonical_json(absent),
            coverage_sha,
            _sha256_bytes(proof_json.encode()),
            proof_json,
            integrity_proof_sha256,
            _sha256_bytes(inactive_probe_json.encode()),
            inactive_probe_json,
            int(sealed_at_ms),
        )
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM backfill_inventory_pages WHERE inventory_page_id = ?",
                (inventory_page_id,),
            ).fetchone()
            columns = (
                "inventory_page_id",
                "job_id",
                "symbol",
                "page_index",
                "start_close_time_ms",
                "end_close_time_ms",
                "expected_close_times_json",
                "occupied_payloads_json",
                "proven_absent_close_times_json",
                "coverage_sha256",
                "coverage_proof_sha256",
                "coverage_proof_json",
                "integrity_proof_sha256",
                "inactive_probe_sha256",
                "inactive_probe_json",
                "sealed_at_ms",
            )
            if existing is not None and tuple(existing[key] for key in columns) != values:
                raise Historical5mBackfillError("inventory_page_is_immutable_and_conflicting")
            cursor = connection.execute(
                """
                SELECT next_inventory_page_index FROM backfill_symbol_cursors
                WHERE job_id = ? AND symbol = ?
                """,
                (job_id, symbol),
            ).fetchone()
            if cursor is None:
                raise Historical5mBackfillError("backfill_symbol_cursor_missing")
            cursor_index = int(cursor["next_inventory_page_index"])
            if existing is None and cursor_index != int(page_index):
                raise Historical5mBackfillError("inventory_page_index_path_not_contiguous")
            if existing is not None and cursor_index < int(page_index) + 1:
                raise Historical5mBackfillError("inventory_page_cursor_not_atomically_advanced")
            connection.execute(
                """
                INSERT OR IGNORE INTO backfill_inventory_pages(
                    inventory_page_id, job_id, symbol, page_index,
                    start_close_time_ms, end_close_time_ms,
                    expected_close_times_json, occupied_payloads_json,
                    proven_absent_close_times_json, coverage_sha256,
                    coverage_proof_sha256, coverage_proof_json,
                    integrity_proof_sha256, inactive_probe_sha256,
                    inactive_probe_json, sealed_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )
            inserted = int(connection.execute("SELECT changes()").fetchone()[0])
            if inserted:
                connection.execute(
                    """
                    UPDATE backfill_symbol_cursors
                    SET next_inventory_page_index = ?
                    WHERE job_id = ? AND symbol = ?
                      AND next_inventory_page_index = ?
                    """,
                    (int(page_index) + 1, job_id, symbol, int(page_index)),
                )
                if int(connection.execute("SELECT changes()").fetchone()[0]) != 1:
                    raise Historical5mBackfillError("inventory_page_cursor_atomic_advance_failed")
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def inventory_pages(self, job_id: str) -> list[dict[str, Any]]:
        connection = self._connect()
        try:
            pages: list[dict[str, Any]] = []
            for row in connection.execute(
                """
                SELECT * FROM backfill_inventory_pages
                WHERE job_id = ? ORDER BY symbol, page_index
                """,
                (job_id,),
            ):
                proof_json = str(row["coverage_proof_json"])
                if _sha256_bytes(proof_json.encode()) != str(row["coverage_proof_sha256"]):
                    raise Historical5mBackfillError("inventory_page_proof_hash_mismatch")
                inactive_probe_json = str(row["inactive_probe_json"])
                if _sha256_bytes(inactive_probe_json.encode()) != str(row["inactive_probe_sha256"]):
                    raise Historical5mBackfillError("inventory_page_inactive_probe_hash_mismatch")
                pages.append(
                    {
                        "inventory_page_id": str(row["inventory_page_id"]),
                        "symbol": str(row["symbol"]),
                        "page_index": int(row["page_index"]),
                        "expected_close_times": json.loads(str(row["expected_close_times_json"])),
                        "occupied_payloads": json.loads(str(row["occupied_payloads_json"])),
                        "proven_absent_close_times": json.loads(
                            str(row["proven_absent_close_times_json"])
                        ),
                        "coverage_sha256": str(row["coverage_sha256"]),
                        "coverage_proof": json.loads(proof_json),
                        "integrity_proof_sha256": str(row["integrity_proof_sha256"]),
                        "inactive_probe_sha256": str(row["inactive_probe_sha256"]),
                        "inactive_probe": json.loads(inactive_probe_json),
                    }
                )
            return pages
        finally:
            connection.close()

    def inventory_page_count(self, job_id: str) -> int:
        connection = self._connect()
        try:
            row = connection.execute(
                """
                SELECT inventory_pages_sealed FROM backfill_job_progress
                WHERE job_id = ?
                """,
                (job_id,),
            ).fetchone()
            if row is None:
                raise Historical5mBackfillError("backfill_job_progress_missing")
            return int(row["inventory_pages_sealed"])
        finally:
            connection.close()

    def next_inventory_page_index(self, job_id: str, *, symbol: str) -> int:
        connection = self._connect()
        try:
            row = connection.execute(
                """
                SELECT next_inventory_page_index
                FROM backfill_symbol_cursors
                WHERE job_id = ? AND symbol = ?
                """,
                (job_id, symbol),
            ).fetchone()
            if row is None:
                raise Historical5mBackfillError("backfill_symbol_cursor_missing")
            page_index = int(row["next_inventory_page_index"])
            if page_index < 0:
                raise Historical5mBackfillError("inventory_page_index_cursor_invalid")
            return page_index
        finally:
            connection.close()

    def inventory_page(self, inventory_page_id: str) -> dict[str, Any]:
        connection = self._connect()
        try:
            row = connection.execute(
                """
                SELECT * FROM backfill_inventory_pages
                WHERE inventory_page_id = ?
                """,
                (inventory_page_id,),
            ).fetchone()
            if row is None:
                raise Historical5mBackfillError("inventory_page_missing")
            proof_json = str(row["coverage_proof_json"])
            if _sha256_bytes(proof_json.encode()) != str(row["coverage_proof_sha256"]):
                raise Historical5mBackfillError("inventory_page_proof_hash_mismatch")
            inactive_probe_json = str(row["inactive_probe_json"])
            if _sha256_bytes(inactive_probe_json.encode()) != str(row["inactive_probe_sha256"]):
                raise Historical5mBackfillError("inventory_page_inactive_probe_hash_mismatch")
            return {
                "inventory_page_id": str(row["inventory_page_id"]),
                "symbol": str(row["symbol"]),
                "page_index": int(row["page_index"]),
                "expected_close_times": json.loads(str(row["expected_close_times_json"])),
                "occupied_payloads": json.loads(str(row["occupied_payloads_json"])),
                "proven_absent_close_times": json.loads(str(row["proven_absent_close_times_json"])),
                "coverage_sha256": str(row["coverage_sha256"]),
                "coverage_proof": json.loads(proof_json),
                "integrity_proof_sha256": str(row["integrity_proof_sha256"]),
                "inactive_probe_sha256": str(row["inactive_probe_sha256"]),
                "inactive_probe": json.loads(inactive_probe_json),
            }
        finally:
            connection.close()

    def seal_inventory_manifest(
        self,
        *,
        job_id: str,
        manifest: Mapping[str, Any],
        sealed_at_ms: int,
    ) -> None:
        manifest_json = canonical_json(dict(manifest))
        manifest_sha = _sha256_bytes(manifest_json.encode())
        header = {
            "kind": "INVENTORY_MANIFEST",
            "job_id": job_id,
            "manifest_sha256": manifest_sha,
            "schema_version": manifest.get("schema_version"),
            "integrity_proof_sha256": manifest.get("integrity_proof_sha256"),
            "inventory_page_count": manifest.get("inventory_page_count"),
            "expected_slot_count": manifest.get("expected_slot_count"),
            "occupied_slot_count": manifest.get("occupied_slot_count"),
            "proven_absent_slot_count": manifest.get("proven_absent_slot_count"),
            "expected_rest_intent_count": manifest.get("expected_rest_intent_count"),
            "sealed_at_ms": int(sealed_at_ms),
        }
        header_json = canonical_json(header)
        header_sha = _sha256_bytes(header_json.encode())
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM backfill_inventory_manifests WHERE job_id = ?",
                (job_id,),
            ).fetchone()
            if existing is not None and (
                str(existing["manifest_sha256"]) != manifest_sha
                or str(existing["manifest_json"]) != manifest_json
                or str(existing["header_sha256"]) != header_sha
                or str(existing["header_json"]) != header_json
                or int(existing["sealed_at_ms"]) != int(sealed_at_ms)
            ):
                raise Historical5mBackfillError("inventory_manifest_is_immutable_and_conflicting")
            connection.execute(
                """
                INSERT OR IGNORE INTO backfill_inventory_manifests(
                    job_id, manifest_sha256, manifest_json,
                    header_sha256, header_json, sealed_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    manifest_sha,
                    manifest_json,
                    header_sha,
                    header_json,
                    int(sealed_at_ms),
                ),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def inventory_manifest(self, job_id: str) -> dict[str, Any] | None:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT * FROM backfill_inventory_manifests WHERE job_id = ?",
                (job_id,),
            ).fetchone()
            if row is None:
                return None
            manifest_json = str(row["manifest_json"])
            if _sha256_bytes(manifest_json.encode()) != str(row["manifest_sha256"]):
                raise Historical5mBackfillError("inventory_manifest_hash_mismatch")
            return {
                "manifest_sha256": str(row["manifest_sha256"]),
                "manifest": json.loads(manifest_json),
                "sealed_at_ms": int(row["sealed_at_ms"]),
            }
        finally:
            connection.close()

    def inventory_manifest_header(self, job_id: str) -> dict[str, Any] | None:
        connection = self._connect()
        try:
            row = connection.execute(
                """
                SELECT manifest_sha256, header_sha256, header_json, sealed_at_ms
                FROM backfill_inventory_manifests WHERE job_id = ?
                """,
                (job_id,),
            ).fetchone()
            if row is None:
                return None
            header_json = str(row["header_json"])
            if _sha256_bytes(header_json.encode()) != str(row["header_sha256"]):
                raise Historical5mBackfillError("inventory_manifest_header_hash_mismatch")
            header = json.loads(header_json)
            if (
                not isinstance(header, Mapping)
                or header.get("kind") != "INVENTORY_MANIFEST"
                or header.get("job_id") != job_id
                or header.get("manifest_sha256") != str(row["manifest_sha256"])
                or header.get("sealed_at_ms") != int(row["sealed_at_ms"])
            ):
                raise Historical5mBackfillError("inventory_manifest_header_binding_mismatch")
            return dict(header)
        finally:
            connection.close()

    def inventory_manifest_exists(self, job_id: str) -> bool:
        return self.inventory_manifest_header(job_id) is not None

    def seal_rest_intent_manifest(
        self,
        *,
        job_id: str,
        manifest: Mapping[str, Any],
        sealed_at_ms: int,
    ) -> None:
        manifest_json = canonical_json(dict(manifest))
        manifest_sha = _sha256_bytes(manifest_json.encode())
        header = {
            "kind": "REST_INTENT_MANIFEST",
            "job_id": job_id,
            "manifest_sha256": manifest_sha,
            "schema_version": manifest.get("schema_version"),
            "inventory_manifest_sha256": manifest.get("inventory_manifest_sha256"),
            "expected_rest_intent_count": manifest.get("expected_rest_intent_count"),
            "intent_bindings_sha256": manifest.get("intent_bindings_sha256"),
            "sealed_at_ms": int(sealed_at_ms),
        }
        header_json = canonical_json(header)
        header_sha = _sha256_bytes(header_json.encode())
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM backfill_rest_intent_manifests WHERE job_id = ?",
                (job_id,),
            ).fetchone()
            if existing is not None and (
                str(existing["manifest_sha256"]) != manifest_sha
                or str(existing["manifest_json"]) != manifest_json
                or str(existing["header_sha256"]) != header_sha
                or str(existing["header_json"]) != header_json
                or int(existing["sealed_at_ms"]) != int(sealed_at_ms)
            ):
                raise Historical5mBackfillError("rest_intent_manifest_is_immutable_and_conflicting")
            connection.execute(
                """
                INSERT OR IGNORE INTO backfill_rest_intent_manifests(
                    job_id, manifest_sha256, manifest_json,
                    header_sha256, header_json, sealed_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    manifest_sha,
                    manifest_json,
                    header_sha,
                    header_json,
                    int(sealed_at_ms),
                ),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def rest_intent_manifest(self, job_id: str) -> dict[str, Any] | None:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT * FROM backfill_rest_intent_manifests WHERE job_id = ?",
                (job_id,),
            ).fetchone()
            if row is None:
                return None
            manifest_json = str(row["manifest_json"])
            if _sha256_bytes(manifest_json.encode()) != str(row["manifest_sha256"]):
                raise Historical5mBackfillError("rest_intent_manifest_hash_mismatch")
            return {
                "manifest_sha256": str(row["manifest_sha256"]),
                "manifest": json.loads(manifest_json),
                "sealed_at_ms": int(row["sealed_at_ms"]),
            }
        finally:
            connection.close()

    def rest_intent_manifest_header(self, job_id: str) -> dict[str, Any] | None:
        connection = self._connect()
        try:
            row = connection.execute(
                """
                SELECT manifest_sha256, header_sha256, header_json, sealed_at_ms
                FROM backfill_rest_intent_manifests WHERE job_id = ?
                """,
                (job_id,),
            ).fetchone()
            if row is None:
                return None
            header_json = str(row["header_json"])
            if _sha256_bytes(header_json.encode()) != str(row["header_sha256"]):
                raise Historical5mBackfillError("rest_intent_manifest_header_hash_mismatch")
            header = json.loads(header_json)
            if (
                not isinstance(header, Mapping)
                or header.get("kind") != "REST_INTENT_MANIFEST"
                or header.get("job_id") != job_id
                or header.get("manifest_sha256") != str(row["manifest_sha256"])
                or header.get("sealed_at_ms") != int(row["sealed_at_ms"])
            ):
                raise Historical5mBackfillError("rest_intent_manifest_header_binding_mismatch")
            return dict(header)
        finally:
            connection.close()

    def rest_intent_manifest_exists(self, job_id: str) -> bool:
        return self.rest_intent_manifest_header(job_id) is not None

    def page_intents(self, job_id: str) -> list[dict[str, Any]]:
        connection = self._connect()
        try:
            intents: list[dict[str, Any]] = []
            for row in connection.execute(
                """
                SELECT page_id, symbol, request_sha256, request_json,
                       inventory_page_id, coverage_sha256,
                       proven_absent_close_times_json
                FROM backfill_pages
                WHERE job_id = ? ORDER BY symbol, start_open_time_ms, page_id
                """,
                (job_id,),
            ):
                request_json = str(row["request_json"])
                if _sha256_bytes(request_json.encode()) != str(row["request_sha256"]):
                    raise Historical5mBackfillError("backfill_page_request_sha_mismatch")
                intents.append(
                    {
                        "page_id": str(row["page_id"]),
                        "symbol": str(row["symbol"]),
                        "request_sha256": str(row["request_sha256"]),
                        "request": json.loads(request_json),
                        "inventory_page_id": str(row["inventory_page_id"]),
                        "coverage_sha256": str(row["coverage_sha256"]),
                        "proven_absent_close_times": json.loads(
                            str(row["proven_absent_close_times_json"])
                        ),
                    }
                )
            return intents
        finally:
            connection.close()

    def ensure_job(self, spec: BackfillJobSpec, *, created_at_ms: int) -> str:
        validated = spec.validated()
        observed_ms = _strict_ms(created_at_ms)
        if observed_ms is None:
            raise Historical5mBackfillError("backfill_job_observed_clock_invalid")
        authority = validated.authority_cutoff.validated(observed_at_ms=observed_ms)
        contract_json = canonical_json(validated.contract())
        contract_sha = _sha256_bytes(contract_json.encode())
        authority_json = canonical_json(authority.contract())
        authority_sha = _sha256_bytes(authority_json.encode())
        authority_scope_sha = authority.authority_scope_sha256
        job_id = validated.job_id
        self.initialize()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                """
                SELECT schema_version, contract_sha256, contract_json
                FROM backfill_jobs WHERE job_id = ?
                """,
                (job_id,),
            ).fetchone()
            if existing is not None:
                if str(existing["schema_version"]) != OUTBOX_SCHEMA_VERSION:
                    raise Historical5mBackfillError(
                        "historical_backfill_state_schema_migration_required"
                    )
                if (
                    str(existing["contract_sha256"]) != contract_sha
                    or str(existing["contract_json"]) != contract_json
                ):
                    raise Historical5mBackfillError("backfill_job_contract_conflict")
            final_verification_exists = (
                connection.execute(
                    """
                    SELECT 1 FROM backfill_final_verifications
                    WHERE job_id = ?
                    """,
                    (job_id,),
                ).fetchone()
                is not None
            )
            by_id = connection.execute(
                """
                SELECT receipt_sha256, authority_scope_sha256, receipt_json
                FROM backfill_authority_receipts
                WHERE job_id = ? AND attestation_id = ?
                """,
                (job_id, authority.attestation_id),
            ).fetchone()
            if by_id is not None and (
                str(by_id["receipt_sha256"]) != authority_sha
                or str(by_id["authority_scope_sha256"]) != authority_scope_sha
                or str(by_id["receipt_json"]) != authority_json
            ):
                raise Historical5mBackfillError(
                    "authority_attestation_id_reused_with_conflicting_receipt"
                )
            by_sha = connection.execute(
                """
                SELECT attestation_id, authority_scope_sha256, receipt_json
                FROM backfill_authority_receipts
                WHERE job_id = ? AND receipt_sha256 = ?
                """,
                (job_id, authority_sha),
            ).fetchone()
            if by_sha is not None and (
                str(by_sha["attestation_id"]) != authority.attestation_id
                or str(by_sha["authority_scope_sha256"]) != authority_scope_sha
                or str(by_sha["receipt_json"]) != authority_json
            ):
                raise Historical5mBackfillError("authority_receipt_identity_conflict")
            if final_verification_exists:
                connection.commit()
                return job_id
            connection.execute(
                """
                INSERT OR IGNORE INTO backfill_jobs(
                    job_id, schema_version, contract_sha256,
                    contract_json, created_at_ms
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    OUTBOX_SCHEMA_VERSION,
                    contract_sha,
                    contract_json,
                    int(created_at_ms),
                ),
            )
            if by_sha is None:
                receipt_count = int(
                    connection.execute(
                        "SELECT COUNT(*) FROM backfill_authority_receipts WHERE job_id = ?",
                        (job_id,),
                    ).fetchone()[0]
                )
                if receipt_count >= MAX_AUTHORITY_RECEIPTS_PER_JOB:
                    raise Historical5mBackfillError("authority_receipt_job_bound_exhausted")
                connection.execute(
                    """
                    INSERT INTO backfill_authority_receipts(
                        job_id, receipt_sha256, attestation_id,
                        authority_scope_sha256, receipt_json,
                        attested_at_ms, valid_until_ms, first_observed_at_ms
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        job_id,
                        authority_sha,
                        authority.attestation_id,
                        authority_scope_sha,
                        authority_json,
                        authority.attested_at_ms,
                        authority.valid_until_ms,
                        observed_ms,
                    ),
                )
            for symbol in validated.symbols:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO backfill_symbol_cursors(
                        job_id, symbol, next_open_time_ms,
                        end_open_time_ms_exclusive, complete
                    ) VALUES (?, ?, ?, ?, 0)
                    """,
                    (
                        job_id,
                        symbol,
                        validated.start_open_time_ms,
                        validated.end_open_time_ms_exclusive,
                    ),
                )
            connection.commit()
            return job_id
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def authority_receipts(self, job_id: str) -> list[dict[str, Any]]:
        connection = self._connect()
        try:
            rows = list(
                connection.execute(
                    """
                    SELECT * FROM backfill_authority_receipts
                    WHERE job_id = ?
                    ORDER BY first_observed_at_ms, receipt_sha256
                    LIMIT ?
                    """,
                    (job_id, MAX_AUTHORITY_RECEIPTS_PER_JOB + 1),
                )
            )
            if len(rows) > MAX_AUTHORITY_RECEIPTS_PER_JOB:
                raise Historical5mBackfillError("authority_receipt_job_bound_exceeded")
            receipts: list[dict[str, Any]] = []
            for row in rows:
                receipt_json = str(row["receipt_json"])
                receipt_sha = _sha256_bytes(receipt_json.encode())
                if receipt_sha != str(row["receipt_sha256"]):
                    raise Historical5mBackfillError("authority_receipt_hash_mismatch")
                receipt = json.loads(receipt_json)
                authority = _authority_attestation_from_contract(
                    receipt,
                    observed_at_ms=int(row["first_observed_at_ms"]),
                )
                if authority.authority_scope_sha256 != str(row["authority_scope_sha256"]):
                    raise Historical5mBackfillError("authority_receipt_scope_hash_mismatch")
                receipts.append({**dict(row), "receipt": receipt})
            return receipts
        finally:
            connection.close()

    def authority_receipt_exists(
        self,
        *,
        job_id: str,
        receipt_sha256: str,
        authority_scope_sha256: str,
    ) -> bool:
        connection = self._connect()
        try:
            return (
                connection.execute(
                    """
                    SELECT 1 FROM backfill_authority_receipts
                    WHERE job_id = ? AND receipt_sha256 = ?
                      AND authority_scope_sha256 = ?
                    """,
                    (job_id, receipt_sha256, authority_scope_sha256),
                ).fetchone()
                is not None
            )
        finally:
            connection.close()

    def next_cursor(self, job_id: str) -> tuple[str, int, int] | None:
        connection = self._connect()
        try:
            row = connection.execute(
                """
                SELECT symbol, next_open_time_ms, end_open_time_ms_exclusive
                FROM backfill_symbol_cursors
                WHERE job_id = ? AND complete = 0
                ORDER BY symbol ASC
                LIMIT 1
                """,
                (job_id,),
            ).fetchone()
            if row is None:
                return None
            return (
                str(row["symbol"]),
                int(row["next_open_time_ms"]),
                int(row["end_open_time_ms_exclusive"]),
            )
        finally:
            connection.close()

    def _advance_cursor(
        self,
        connection: sqlite3.Connection,
        *,
        job_id: str,
        symbol: str,
    ) -> None:
        cursor = connection.execute(
            """
            SELECT next_open_time_ms, end_open_time_ms_exclusive
            FROM backfill_symbol_cursors
            WHERE job_id = ? AND symbol = ?
            """,
            (job_id, symbol),
        ).fetchone()
        if cursor is None:
            raise Historical5mBackfillError("backfill_symbol_cursor_missing")
        next_open = int(cursor["next_open_time_ms"])
        end_open = int(cursor["end_open_time_ms_exclusive"])
        while next_open < end_open:
            receipt = connection.execute(
                """
                SELECT 1 FROM backfill_slot_receipts
                WHERE job_id = ? AND symbol = ? AND candle_open_time_ms = ?
                """,
                (job_id, symbol, next_open),
            ).fetchone()
            if receipt is None:
                break
            next_open += LABEL_SLOT_MILLISECONDS
        connection.execute(
            """
            UPDATE backfill_symbol_cursors
            SET next_open_time_ms = ?, complete = ?
            WHERE job_id = ? AND symbol = ?
            """,
            (next_open, int(next_open >= end_open), job_id, symbol),
        )

    def ensure_page_intent(
        self,
        *,
        job_id: str,
        request: BinanceKlineRequest,
        inventory_page_id: str,
        coverage_sha256: str,
        proven_absent_close_times: Sequence[int],
    ) -> tuple[str, str, int | None]:
        request_json = canonical_json(request.contract())
        request_sha = _sha256_bytes(request_json.encode())
        absent_json = canonical_json([int(value) for value in proven_absent_close_times])
        identity_sha = stable_sha256(
            {
                "job_id": job_id,
                "request_sha256": request_sha,
                "inventory_page_id": inventory_page_id,
                "coverage_sha256": coverage_sha256,
                "proven_absent_close_times": json.loads(absent_json),
            }
        )
        page_id = f"canonical_5m_page_{identity_sha}"
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM backfill_pages WHERE page_id = ?",
                (page_id,),
            ).fetchone()
            if existing is not None and (
                str(existing["job_id"]) != job_id
                or str(existing["request_sha256"]) != request_sha
                or str(existing["request_json"]) != request_json
                or str(existing["inventory_page_id"]) != inventory_page_id
                or str(existing["coverage_sha256"]) != coverage_sha256
                or str(existing["proven_absent_close_times_json"]) != absent_json
            ):
                raise Historical5mBackfillError("backfill_page_intent_conflict")
            connection.execute(
                """
                INSERT OR IGNORE INTO backfill_pages(
                    page_id, job_id, symbol, start_open_time_ms,
                    end_open_time_ms, requested_rows, request_sha256,
                    request_json, inventory_page_id, coverage_sha256,
                    proven_absent_close_times_json, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'INTENT')
                """,
                (
                    page_id,
                    job_id,
                    request.symbol,
                    request.start_open_time_ms,
                    request.end_close_time_ms - LABEL_SLOT_MILLISECONDS + 1,
                    request.limit,
                    request_sha,
                    request_json,
                    inventory_page_id,
                    coverage_sha256,
                    absent_json,
                ),
            )
            row = connection.execute(
                "SELECT status, retry_not_before_ms FROM backfill_pages WHERE page_id = ?",
                (page_id,),
            ).fetchone()
            connection.commit()
            return (
                page_id,
                str(row["status"]),
                int(row["retry_not_before_ms"]) if row["retry_not_before_ms"] is not None else None,
            )
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def page_request(self, page_id: str) -> BinanceKlineRequest:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT request_json, request_sha256 FROM backfill_pages WHERE page_id = ?",
                (page_id,),
            ).fetchone()
            if row is None:
                raise Historical5mBackfillError("backfill_page_missing")
            request_json = str(row["request_json"])
            if _sha256_bytes(request_json.encode()) != str(row["request_sha256"]):
                raise Historical5mBackfillError("backfill_page_request_sha_mismatch")
            payload = json.loads(request_json)
            if not isinstance(payload, Mapping):
                raise Historical5mBackfillError("backfill_page_request_invalid")
            return BinanceKlineRequest.from_contract(payload)
        finally:
            connection.close()

    def page_record(self, page_id: str) -> dict[str, Any]:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT * FROM backfill_pages WHERE page_id = ?",
                (page_id,),
            ).fetchone()
            if row is None:
                raise Historical5mBackfillError("backfill_page_missing")
            return dict(row)
        finally:
            connection.close()

    def page_header(self, page_id: str) -> dict[str, Any]:
        """Read bounded resume fields without materializing response/request bytes."""

        connection = self._connect()
        try:
            row = connection.execute(
                """
                SELECT page_id, job_id, symbol, start_open_time_ms,
                       end_open_time_ms, requested_rows, inventory_page_id,
                       coverage_sha256, proven_absent_close_times_json,
                       status, response_sha256, response_received_at_ms,
                       retry_not_before_ms, last_error, append_attempted_at_ms
                FROM backfill_pages WHERE page_id = ?
                """,
                (page_id,),
            ).fetchone()
            if row is None:
                raise Historical5mBackfillError("backfill_page_missing")
            return dict(row)
        finally:
            connection.close()

    def work_pages(self, job_id: str, *, limit: int) -> list[str]:
        bounded_limit = _strict_positive_int(limit)
        if bounded_limit is None or bounded_limit > MAX_RUN_PAGES:
            raise Historical5mBackfillError("backfill_work_page_limit_invalid")
        connection = self._connect()
        try:
            prepared = [
                str(row["page_id"])
                for row in connection.execute(
                    """
                    SELECT page_id FROM backfill_pages
                    WHERE job_id = ? AND status = 'PREPARED'
                    ORDER BY start_open_time_ms, page_id
                    LIMIT ?
                    """,
                    (job_id, bounded_limit),
                )
            ]
            remaining = bounded_limit - len(prepared)
            if remaining <= 0:
                return prepared
            intents = [
                str(row["page_id"])
                for row in connection.execute(
                    """
                    SELECT page_id FROM backfill_pages
                    WHERE job_id = ? AND status = 'INTENT'
                    ORDER BY start_open_time_ms, page_id
                    LIMIT ?
                    """,
                    (job_id, remaining),
                )
            ]
            return [*prepared, *intents]
        finally:
            connection.close()

    def append_started(self, job_id: str) -> bool:
        connection = self._connect()
        try:
            return (
                connection.execute(
                    """
                    SELECT 1 FROM backfill_pages
                    WHERE job_id = ? AND append_attempted_at_ms IS NOT NULL
                    LIMIT 1
                    """,
                    (job_id,),
                ).fetchone()
                is not None
            )
        finally:
            connection.close()

    @staticmethod
    def _validate_registered_authority_probe(
        connection: sqlite3.Connection,
        *,
        job_id: str,
        authority_receipt_sha256: str,
        inactive_probe: Mapping[str, Any],
    ) -> tuple[str, str]:
        receipt = connection.execute(
            """
            SELECT authority_scope_sha256 FROM backfill_authority_receipts
            WHERE job_id = ? AND receipt_sha256 = ?
            """,
            (job_id, authority_receipt_sha256),
        ).fetchone()
        if receipt is None:
            raise Historical5mBackfillError("append_authority_receipt_not_registered")
        probe_json = canonical_json(dict(inactive_probe))
        probe_sha = _sha256_bytes(probe_json.encode())
        if (
            inactive_probe.get("authority_receipt_sha256") != authority_receipt_sha256
            or inactive_probe.get("authority_scope_sha256")
            != str(receipt["authority_scope_sha256"])
            or inactive_probe.get("probe_sha256")
            != stable_sha256(
                {key: value for key, value in inactive_probe.items() if key != "probe_sha256"}
            )
        ):
            raise Historical5mBackfillError("append_authority_probe_binding_invalid")
        return probe_sha, probe_json

    def _validate_append_attempt_row(
        self,
        connection: sqlite3.Connection,
        row: Mapping[str, Any],
    ) -> dict[str, Any]:
        try:
            inactive_probe = json.loads(str(row["inactive_probe_json"]))
            probe_sha, probe_json = self._validate_registered_authority_probe(
                connection,
                job_id=str(row["job_id"]),
                authority_receipt_sha256=str(row["authority_receipt_sha256"]),
                inactive_probe=inactive_probe,
            )
            attempted_ms = _strict_ms(row["attempted_at_ms"])
            ordinal = _strict_positive_int(row["attempt_ordinal"])
        except (KeyError, TypeError, ValueError) as exc:
            raise Historical5mBackfillError("append_attempt_row_invalid") from exc
        if (
            attempted_ms is None
            or ordinal is None
            or ordinal > MAX_APPEND_ATTEMPTS_PER_PAGE
            or probe_sha != str(row["inactive_probe_sha256"])
            or probe_json != str(row["inactive_probe_json"])
        ):
            raise Historical5mBackfillError("append_attempt_row_binding_invalid")
        material = {
            "schema_version": APPEND_ATTEMPT_SCHEMA_VERSION,
            "job_id": str(row["job_id"]),
            "page_id": str(row["page_id"]),
            "attempt_ordinal": ordinal,
            "authority_receipt_sha256": str(row["authority_receipt_sha256"]),
            "inactive_probe_sha256": probe_sha,
            "attempted_at_ms": attempted_ms,
        }
        if str(row["attempt_id"]) != ("canonical_5m_backfill_attempt_" + stable_sha256(material)):
            raise Historical5mBackfillError("append_attempt_identity_mismatch")
        return dict(row)

    def begin_append_attempt(
        self,
        *,
        job_id: str,
        page_id: str,
        authority_receipt_sha256: str,
        inactive_probe: Mapping[str, Any],
        attempted_at_ms: int,
    ) -> tuple[dict[str, Any], bool]:
        """Durably bind one possible archive side effect to its exact authority."""

        attempted_ms = _strict_ms(attempted_at_ms)
        if attempted_ms is None:
            raise Historical5mBackfillError("append_attempt_clock_invalid")
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            page = connection.execute(
                "SELECT job_id, status FROM backfill_pages WHERE page_id = ?",
                (page_id,),
            ).fetchone()
            if page is None or str(page["job_id"]) != job_id or str(page["status"]) != "PREPARED":
                raise Historical5mBackfillError("append_attempt_page_missing_or_not_prepared")
            probe_sha, probe_json = self._validate_registered_authority_probe(
                connection,
                job_id=job_id,
                authority_receipt_sha256=authority_receipt_sha256,
                inactive_probe=inactive_probe,
            )
            latest = connection.execute(
                """
                SELECT attempt.*, resolution.resolution_kind
                FROM backfill_append_attempts AS attempt
                LEFT JOIN backfill_append_attempt_resolutions AS resolution
                  ON resolution.attempt_id = attempt.attempt_id
                WHERE attempt.page_id = ?
                ORDER BY attempt.attempt_ordinal DESC
                LIMIT 1
                """,
                (page_id,),
            ).fetchone()
            if latest is not None and latest["resolution_kind"] is None:
                self._validate_append_attempt_row(connection, latest)
                connection.commit()
                return dict(latest), False
            if latest is not None and str(latest["resolution_kind"]) != (
                "PROVEN_EMPTY_NO_ARCHIVE_COMMIT"
            ):
                raise Historical5mBackfillError(
                    "prepared_page_has_terminal_append_attempt_resolution"
                )
            ordinal = 1 if latest is None else int(latest["attempt_ordinal"]) + 1
            if ordinal > MAX_APPEND_ATTEMPTS_PER_PAGE:
                raise Historical5mBackfillError("append_attempt_page_bound_exhausted")
            attempt_material = {
                "schema_version": APPEND_ATTEMPT_SCHEMA_VERSION,
                "job_id": job_id,
                "page_id": page_id,
                "attempt_ordinal": ordinal,
                "authority_receipt_sha256": authority_receipt_sha256,
                "inactive_probe_sha256": probe_sha,
                "attempted_at_ms": attempted_ms,
            }
            attempt_id = "canonical_5m_backfill_attempt_" + stable_sha256(attempt_material)
            connection.execute(
                """
                INSERT INTO backfill_append_attempts(
                    attempt_id, job_id, page_id, attempt_ordinal,
                    authority_receipt_sha256, inactive_probe_sha256,
                    inactive_probe_json, attempted_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    attempt_id,
                    job_id,
                    page_id,
                    ordinal,
                    authority_receipt_sha256,
                    probe_sha,
                    probe_json,
                    attempted_ms,
                ),
            )
            connection.execute(
                """
                UPDATE backfill_pages SET append_attempted_at_ms =
                    COALESCE(append_attempted_at_ms, ?)
                WHERE page_id = ? AND status = 'PREPARED'
                """,
                (attempted_ms, page_id),
            )
            connection.commit()
            return {
                "attempt_id": attempt_id,
                "job_id": job_id,
                "page_id": page_id,
                "attempt_ordinal": ordinal,
                "authority_receipt_sha256": authority_receipt_sha256,
                "inactive_probe_sha256": probe_sha,
                "inactive_probe_json": probe_json,
                "attempted_at_ms": attempted_ms,
                "resolution_kind": None,
            }, True
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def seal_empty_append_attempt_resolution(
        self,
        *,
        job_id: str,
        page_id: str,
        attempt_id: str,
        reconciliation_authority_receipt_sha256: str,
        reconciliation_probe: Mapping[str, Any],
        empty_range_proof: Mapping[str, Any],
        resolved_at_ms: int,
    ) -> None:
        resolved_ms = _strict_ms(resolved_at_ms)
        if resolved_ms is None:
            raise Historical5mBackfillError("append_resolution_clock_invalid")
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            attempt = connection.execute(
                """
                SELECT * FROM backfill_append_attempts
                WHERE attempt_id = ? AND job_id = ? AND page_id = ?
                """,
                (attempt_id, job_id, page_id),
            ).fetchone()
            if attempt is None:
                raise Historical5mBackfillError("append_attempt_missing_for_resolution")
            self._validate_append_attempt_row(connection, attempt)
            if (
                connection.execute(
                    "SELECT 1 FROM backfill_append_attempt_resolutions WHERE attempt_id = ?",
                    (attempt_id,),
                ).fetchone()
                is not None
            ):
                raise Historical5mBackfillError("append_attempt_already_resolved")
            probe_sha, probe_json = self._validate_registered_authority_probe(
                connection,
                job_id=job_id,
                authority_receipt_sha256=reconciliation_authority_receipt_sha256,
                inactive_probe=reconciliation_probe,
            )
            evidence = {
                "schema_version": APPEND_ATTEMPT_RESOLUTION_SCHEMA_VERSION,
                "attempt_id": attempt_id,
                "resolution_kind": "PROVEN_EMPTY_NO_ARCHIVE_COMMIT",
                "empty_range_proof": dict(empty_range_proof),
                "archive_side_effect_absent_before_retry": True,
            }
            evidence_json = canonical_json(evidence)
            connection.execute(
                """
                INSERT INTO backfill_append_attempt_resolutions(
                    attempt_id, job_id, page_id, resolution_kind,
                    resolution_evidence_sha256, resolution_evidence_json,
                    reconciliation_authority_receipt_sha256,
                    reconciliation_probe_sha256, reconciliation_probe_json,
                    resolved_at_ms
                ) VALUES (?, ?, ?, 'PROVEN_EMPTY_NO_ARCHIVE_COMMIT', ?, ?, ?, ?, ?, ?)
                """,
                (
                    attempt_id,
                    job_id,
                    page_id,
                    _sha256_bytes(evidence_json.encode()),
                    evidence_json,
                    reconciliation_authority_receipt_sha256,
                    probe_sha,
                    probe_json,
                    resolved_ms,
                ),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def append_attempt_authority_summary(
        self,
        job_id: str,
    ) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
        """Stream all immutable attempts; retain only one terminal proof per page."""

        connection = self._connect()
        try:
            page_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM backfill_pages WHERE job_id = ?",
                    (job_id,),
                ).fetchone()[0]
            )
            attempt_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM backfill_append_attempts WHERE job_id = ?",
                    (job_id,),
                ).fetchone()[0]
            )
            if attempt_count > page_count * MAX_APPEND_ATTEMPTS_PER_PAGE:
                raise Historical5mBackfillError("append_attempt_job_bound_exceeded")
            chain = stable_sha256(
                {
                    "schema_version": "canonical_5m_append_attempt_chain_v1",
                    "job_id": job_id,
                    "genesis": True,
                }
            )
            terminal_by_page: dict[str, dict[str, Any]] = {}
            empty_resolutions = 0
            observed = 0
            cursor = connection.execute(
                """
                SELECT attempt.*, resolution.resolution_kind,
                       resolution.resolution_evidence_sha256,
                       resolution.resolution_evidence_json,
                       resolution.reconciliation_authority_receipt_sha256,
                       resolution.reconciliation_probe_sha256,
                       resolution.reconciliation_probe_json,
                       resolution.resolved_at_ms,
                       authority.authority_scope_sha256 AS append_scope_sha256,
                       reconciliation.authority_scope_sha256 AS reconciliation_scope_sha256
                FROM backfill_append_attempts AS attempt
                LEFT JOIN backfill_append_attempt_resolutions AS resolution
                  ON resolution.attempt_id = attempt.attempt_id
                LEFT JOIN backfill_authority_receipts AS authority
                  ON authority.job_id = attempt.job_id
                 AND authority.receipt_sha256 = attempt.authority_receipt_sha256
                LEFT JOIN backfill_authority_receipts AS reconciliation
                  ON reconciliation.job_id = resolution.job_id
                 AND reconciliation.receipt_sha256 =
                     resolution.reconciliation_authority_receipt_sha256
                WHERE attempt.job_id = ?
                ORDER BY attempt.page_id, attempt.attempt_ordinal
                """,
                (job_id,),
            )
            for row in cursor:
                observed += 1
                self._validate_append_attempt_row(connection, row)
                if row["resolution_kind"] is None:
                    raise Historical5mBackfillError("terminal_append_attempt_remains_unresolved")
                attempt_probe_json = str(row["inactive_probe_json"])
                resolution_json = str(row["resolution_evidence_json"])
                reconciliation_probe_json = str(row["reconciliation_probe_json"])
                if (
                    _sha256_bytes(attempt_probe_json.encode()) != str(row["inactive_probe_sha256"])
                    or _sha256_bytes(resolution_json.encode())
                    != str(row["resolution_evidence_sha256"])
                    or _sha256_bytes(reconciliation_probe_json.encode())
                    != str(row["reconciliation_probe_sha256"])
                ):
                    raise Historical5mBackfillError("append_attempt_or_resolution_hash_mismatch")
                attempt_probe = json.loads(attempt_probe_json)
                resolution_evidence = json.loads(resolution_json)
                reconciliation_probe = json.loads(reconciliation_probe_json)
                if (
                    attempt_probe.get("probe_sha256")
                    != stable_sha256(
                        {
                            key: value
                            for key, value in attempt_probe.items()
                            if key != "probe_sha256"
                        }
                    )
                    or reconciliation_probe.get("probe_sha256")
                    != stable_sha256(
                        {
                            key: value
                            for key, value in reconciliation_probe.items()
                            if key != "probe_sha256"
                        }
                    )
                    or attempt_probe.get("authority_receipt_sha256")
                    != str(row["authority_receipt_sha256"])
                    or attempt_probe.get("authority_scope_sha256")
                    != str(row["append_scope_sha256"])
                    or reconciliation_probe.get("authority_receipt_sha256")
                    != str(row["reconciliation_authority_receipt_sha256"])
                    or reconciliation_probe.get("authority_scope_sha256")
                    != str(row["reconciliation_scope_sha256"])
                ):
                    raise Historical5mBackfillError(
                        "append_attempt_authority_probe_readback_invalid"
                    )
                resolution_kind = str(row["resolution_kind"])
                if (
                    resolution_evidence.get("schema_version")
                    != APPEND_ATTEMPT_RESOLUTION_SCHEMA_VERSION
                    or resolution_evidence.get("attempt_id") != str(row["attempt_id"])
                    or resolution_evidence.get("resolution_kind") != resolution_kind
                ):
                    raise Historical5mBackfillError(
                        "append_attempt_resolution_evidence_binding_invalid"
                    )
                if resolution_kind == "PROVEN_EMPTY_NO_ARCHIVE_COMMIT":
                    if (
                        set(resolution_evidence)
                        != {
                            "schema_version",
                            "attempt_id",
                            "resolution_kind",
                            "empty_range_proof",
                            "archive_side_effect_absent_before_retry",
                        }
                        or resolution_evidence.get("archive_side_effect_absent_before_retry")
                        is not True
                    ):
                        raise Historical5mBackfillError("empty_append_resolution_evidence_invalid")
                elif (
                    set(resolution_evidence)
                    != {
                        "schema_version",
                        "attempt_id",
                        "resolution_kind",
                        "archive_transaction_id",
                        "archive_append_receipt_sha256",
                        "append_authority_receipt_sha256",
                        "append_probe_sha256",
                        "terminal_authority_receipt_sha256",
                        "terminal_probe_sha256",
                        "slot_evidence_sha256",
                    }
                    or resolution_evidence.get("append_authority_receipt_sha256")
                    != str(row["authority_receipt_sha256"])
                    or resolution_evidence.get("append_probe_sha256")
                    != str(row["inactive_probe_sha256"])
                    or resolution_evidence.get("terminal_authority_receipt_sha256")
                    != str(row["reconciliation_authority_receipt_sha256"])
                    or resolution_evidence.get("terminal_probe_sha256")
                    != str(row["reconciliation_probe_sha256"])
                    or not re.fullmatch(
                        r"[0-9a-f]{64}",
                        str(resolution_evidence.get("archive_append_receipt_sha256") or ""),
                    )
                    or not re.fullmatch(
                        r"[0-9a-f]{64}",
                        str(resolution_evidence.get("slot_evidence_sha256") or ""),
                    )
                ):
                    raise Historical5mBackfillError("terminal_append_resolution_evidence_invalid")
                proof = {
                    "attempt_id": str(row["attempt_id"]),
                    "page_id": str(row["page_id"]),
                    "attempt_ordinal": int(row["attempt_ordinal"]),
                    "append_authority_receipt_sha256": str(row["authority_receipt_sha256"]),
                    "append_probe_sha256": str(row["inactive_probe_sha256"]),
                    "attempted_at_ms": int(row["attempted_at_ms"]),
                    "resolution_kind": resolution_kind,
                    "archive_transaction_id": resolution_evidence.get("archive_transaction_id"),
                    "archive_append_receipt_sha256": resolution_evidence.get(
                        "archive_append_receipt_sha256"
                    ),
                    "resolution_evidence_sha256": str(row["resolution_evidence_sha256"]),
                    "reconciliation_authority_receipt_sha256": str(
                        row["reconciliation_authority_receipt_sha256"]
                    ),
                    "reconciliation_probe_sha256": str(row["reconciliation_probe_sha256"]),
                    "resolved_at_ms": int(row["resolved_at_ms"]),
                }
                if proof["resolved_at_ms"] < proof["attempted_at_ms"]:
                    raise Historical5mBackfillError("append_attempt_resolution_clock_invalid")
                chain = stable_sha256({"previous_sha256": chain, "proof": proof})
                if proof["resolution_kind"] == "PROVEN_EMPTY_NO_ARCHIVE_COMMIT":
                    empty_resolutions += 1
                else:
                    page_id = proof["page_id"]
                    if page_id in terminal_by_page:
                        raise Historical5mBackfillError(
                            "multiple_terminal_append_attempts_for_page"
                        )
                    terminal_by_page[page_id] = proof
            if observed != attempt_count:
                raise Historical5mBackfillError("append_attempt_stream_count_mismatch")
            return (
                {
                    "schema_version": "canonical_5m_append_attempt_authority_summary_v1",
                    "job_id": job_id,
                    "attempt_count": attempt_count,
                    "empty_no_commit_resolution_count": empty_resolutions,
                    "terminal_resolution_count": len(terminal_by_page),
                    "attempt_authority_chain_sha256": chain,
                    "all_attempts_resolved": True,
                },
                terminal_by_page,
            )
        finally:
            connection.close()

    def archive_transactions(self, job_id: str) -> list[dict[str, Any]]:
        connection = self._connect()
        try:
            rows: list[dict[str, Any]] = []
            for row in connection.execute(
                """
                SELECT * FROM backfill_archive_transactions
                WHERE job_id = ? ORDER BY recorded_at_ms, transaction_id
                """,
                (job_id,),
            ):
                result_json = str(row["result_json"])
                if _sha256_bytes(result_json.encode()) != str(row["result_sha256"]):
                    raise Historical5mBackfillError("archive_transaction_receipt_hash_mismatch")
                rows.append({**dict(row), "result": json.loads(result_json)})
            return rows
        finally:
            connection.close()

    def archive_transaction_for_page(self, page_id: str) -> dict[str, Any] | None:
        connection = self._connect()
        try:
            rows = list(
                connection.execute(
                    """
                    SELECT * FROM backfill_archive_transactions
                    WHERE page_id = ? ORDER BY recorded_at_ms, transaction_id
                    LIMIT 2
                    """,
                    (page_id,),
                )
            )
            if len(rows) > 1:
                raise Historical5mBackfillError("multiple_archive_transactions_for_one_page")
            if not rows:
                return None
            row = rows[0]
            result_json = str(row["result_json"])
            if _sha256_bytes(result_json.encode()) != str(row["result_sha256"]):
                raise Historical5mBackfillError("archive_transaction_receipt_hash_mismatch")
            return {**dict(row), "result": json.loads(result_json)}
        finally:
            connection.close()

    def recovered_append_intents(self, job_id: str) -> list[dict[str, Any]]:
        connection = self._connect()
        try:
            rows: list[dict[str, Any]] = []
            for row in connection.execute(
                """
                SELECT * FROM backfill_recovered_append_intents
                WHERE job_id = ? ORDER BY recovered_at_ms, page_id
                """,
                (job_id,),
            ):
                evidence_json = str(row["evidence_json"])
                if _sha256_bytes(evidence_json.encode()) != str(row["evidence_sha256"]):
                    raise Historical5mBackfillError("recovered_append_intent_hash_mismatch")
                rows.append({**dict(row), "evidence": json.loads(evidence_json)})
            return rows
        finally:
            connection.close()

    def recovered_append_intent_for_page(self, page_id: str) -> dict[str, Any] | None:
        connection = self._connect()
        try:
            row = connection.execute(
                """
                SELECT * FROM backfill_recovered_append_intents
                WHERE page_id = ?
                """,
                (page_id,),
            ).fetchone()
            if row is None:
                return None
            evidence_json = str(row["evidence_json"])
            if _sha256_bytes(evidence_json.encode()) != str(row["evidence_sha256"]):
                raise Historical5mBackfillError("recovered_append_intent_hash_mismatch")
            return {**dict(row), "evidence": json.loads(evidence_json)}
        finally:
            connection.close()

    def seal_final_verification(
        self,
        *,
        job_id: str,
        verification: Mapping[str, Any],
        verified_at_ms: int,
    ) -> None:
        if (
            verification.get("schema_version") != FINAL_VERIFICATION_SCHEMA_VERSION
            or verification.get("job_id") != job_id
            or verification.get("status") != "READY_FOR_WSS_ACTIVATION_AND_CUTOFF_TAIL_RECOVERY"
        ):
            raise Historical5mBackfillError("final_verification_contract_invalid")
        verification_json = canonical_json(dict(verification))
        verification_sha = _sha256_bytes(verification_json.encode())
        final_proof = verification.get("final_integrity_proof")
        if not isinstance(final_proof, Mapping):
            raise Historical5mBackfillError("final_integrity_proof_header_missing")
        header = {
            "kind": "FINAL_VERIFICATION",
            "job_id": job_id,
            "verification_sha256": verification_sha,
            "schema_version": verification.get("schema_version"),
            "status": verification.get("status"),
            "inventory_manifest_sha256": verification.get("inventory_manifest_sha256"),
            "rest_intent_manifest_sha256": verification.get("rest_intent_manifest_sha256"),
            "expected_absent_rows": verification.get("expected_absent_rows"),
            "known_append_transactions": verification.get("known_append_transactions"),
            "recovered_crash_append_intents": verification.get("recovered_crash_append_intents"),
            "final_integrity_proof": _compact_integrity_proof(final_proof),
            "verified_at_ms": int(verified_at_ms),
        }
        header_json = canonical_json(header)
        header_sha = _sha256_bytes(header_json.encode())
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            job = connection.execute(
                """
                SELECT contract_sha256, contract_json
                FROM backfill_jobs WHERE job_id = ?
                """,
                (job_id,),
            ).fetchone()
            if job is None:
                raise Historical5mBackfillError("final_verification_job_missing")
            contract_json = str(job["contract_json"])
            if _sha256_bytes(contract_json.encode()) != str(job["contract_sha256"]):
                raise Historical5mBackfillError("final_verification_job_contract_hash_mismatch")
            try:
                job_contract = json.loads(contract_json)
            except (TypeError, ValueError) as exc:
                raise Historical5mBackfillError("final_verification_job_contract_invalid") from exc
            symbols = job_contract.get("symbols")
            start_open_time_ms = _strict_ms(job_contract.get("start_open_time_ms"))
            end_open_time_ms_exclusive = _strict_ms(job_contract.get("end_open_time_ms_exclusive"))
            if (
                not isinstance(symbols, list)
                or not symbols
                or any(not isinstance(symbol, str) or not symbol for symbol in symbols)
                or len(set(symbols)) != len(symbols)
                or start_open_time_ms is None
                or end_open_time_ms_exclusive is None
                or end_open_time_ms_exclusive <= start_open_time_ms
            ):
                raise Historical5mBackfillError("final_verification_job_contract_invalid")
            cursors = list(
                connection.execute(
                    """
                    SELECT symbol, next_open_time_ms,
                           end_open_time_ms_exclusive, complete
                    FROM backfill_symbol_cursors
                    WHERE job_id = ? ORDER BY symbol
                    """,
                    (job_id,),
                )
            )
            if (
                len(cursors) != len(symbols)
                or {str(row["symbol"]) for row in cursors} != set(symbols)
                or any(
                    int(row["end_open_time_ms_exclusive"]) != end_open_time_ms_exclusive
                    or int(row["next_open_time_ms"]) < start_open_time_ms
                    or int(row["next_open_time_ms"]) > end_open_time_ms_exclusive
                    or (int(row["next_open_time_ms"]) - start_open_time_ms)
                    % LABEL_SLOT_MILLISECONDS
                    != 0
                    or int(row["complete"]) not in {0, 1}
                    or (
                        int(row["complete"]) == 1
                        and int(row["next_open_time_ms"]) != end_open_time_ms_exclusive
                    )
                    for row in cursors
                )
            ):
                raise Historical5mBackfillError(
                    "final_verification_symbol_cursor_projection_invalid"
                )
            connection.execute(
                """
                UPDATE backfill_symbol_cursors
                SET next_open_time_ms = end_open_time_ms_exclusive,
                    complete = 1
                WHERE job_id = ?
                """,
                (job_id,),
            )
            existing = connection.execute(
                "SELECT * FROM backfill_final_verifications WHERE job_id = ?",
                (job_id,),
            ).fetchone()
            if existing is not None and (
                str(existing["verification_sha256"]) != verification_sha
                or str(existing["verification_json"]) != verification_json
                or str(existing["header_sha256"]) != header_sha
                or str(existing["header_json"]) != header_json
                or int(existing["verified_at_ms"]) != int(verified_at_ms)
            ):
                raise Historical5mBackfillError("final_verification_is_immutable_and_conflicting")
            connection.execute(
                """
                INSERT OR IGNORE INTO backfill_final_verifications(
                    job_id, verification_sha256, verification_json,
                    header_sha256, header_json, verified_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    verification_sha,
                    verification_json,
                    header_sha,
                    header_json,
                    int(verified_at_ms),
                ),
            )
            remaining = connection.execute(
                """
                SELECT COUNT(*) FROM backfill_symbol_cursors
                WHERE job_id = ? AND (
                    complete != 1
                    OR next_open_time_ms != end_open_time_ms_exclusive
                )
                """,
                (job_id,),
            ).fetchone()
            if remaining is None or int(remaining[0]) != 0:
                raise Historical5mBackfillError(
                    "final_verification_symbol_cursor_projection_failed"
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def final_verification(self, job_id: str) -> dict[str, Any] | None:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT * FROM backfill_final_verifications WHERE job_id = ?",
                (job_id,),
            ).fetchone()
            if row is None:
                return None
            payload = str(row["verification_json"])
            if _sha256_bytes(payload.encode()) != str(row["verification_sha256"]):
                raise Historical5mBackfillError("final_verification_hash_mismatch")
            return {
                "verification_sha256": str(row["verification_sha256"]),
                "verification": json.loads(payload),
                "verified_at_ms": int(row["verified_at_ms"]),
            }
        finally:
            connection.close()

    def final_verification_header(self, job_id: str) -> dict[str, Any] | None:
        connection = self._connect()
        try:
            row = connection.execute(
                """
                SELECT verification_sha256, header_sha256, header_json, verified_at_ms
                FROM backfill_final_verifications WHERE job_id = ?
                """,
                (job_id,),
            ).fetchone()
            if row is None:
                return None
            header_json = str(row["header_json"])
            if _sha256_bytes(header_json.encode()) != str(row["header_sha256"]):
                raise Historical5mBackfillError("final_verification_header_hash_mismatch")
            header = json.loads(header_json)
            if (
                not isinstance(header, Mapping)
                or header.get("kind") != "FINAL_VERIFICATION"
                or header.get("job_id") != job_id
                or header.get("verification_sha256") != str(row["verification_sha256"])
                or header.get("verified_at_ms") != int(row["verified_at_ms"])
            ):
                raise Historical5mBackfillError("final_verification_header_binding_mismatch")
            compact = header.get("final_integrity_proof")
            if not isinstance(compact, Mapping) or set(compact) != set(
                _CURRENT_INTEGRITY_PROOF_FIELDS
            ):
                raise Historical5mBackfillError("final_integrity_proof_header_incomplete")
            return dict(header)
        finally:
            connection.close()

    def final_verification_exists(self, job_id: str) -> bool:
        return self.final_verification_header(job_id) is not None

    def append_evidence_exists(self, job_id: str) -> bool:
        connection = self._connect()
        try:
            row = connection.execute(
                """
                SELECT archive_transaction_count, recovered_append_count
                FROM backfill_job_progress WHERE job_id = ?
                """,
                (job_id,),
            ).fetchone()
            if row is None:
                raise Historical5mBackfillError("backfill_job_progress_missing")
            return bool(int(row["archive_transaction_count"]) or int(row["recovered_append_count"]))
        finally:
            connection.close()

    def progress_header(self, job_id: str) -> dict[str, int]:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT * FROM backfill_job_progress WHERE job_id = ?",
                (job_id,),
            ).fetchone()
            if row is None:
                raise Historical5mBackfillError("backfill_job_progress_missing")
            progress = {key: int(row[key]) for key in row.keys() if key != "job_id"}
            if any(value < 0 for value in progress.values()) or any(
                progress[key] not in {0, 1}
                for key in (
                    "inventory_checkpoint_sealed",
                    "inventory_manifest_sealed",
                    "rest_intent_manifest_sealed",
                    "final_verification_sealed",
                )
            ):
                raise Historical5mBackfillError("backfill_job_progress_invalid")
            return progress
        finally:
            connection.close()

    def prepare_page(
        self,
        *,
        page_id: str,
        response: PublicHttpResponse,
        payload_json_by_open: Mapping[int, str],
    ) -> None:
        response_sha = _sha256_bytes(response.body)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            page = connection.execute(
                """
                SELECT page_id, job_id, symbol, requested_rows, status,
                       response_body, response_sha256, response_received_at_ms
                FROM backfill_pages WHERE page_id = ?
                """,
                (page_id,),
            ).fetchone()
            if page is None:
                raise Historical5mBackfillError("backfill_page_missing")
            if page["response_body"] is not None:
                if (
                    bytes(page["response_body"]) != response.body
                    or str(page["response_sha256"]) != response_sha
                    or int(page["response_received_at_ms"]) != response.received_at_ms
                ):
                    raise Historical5mBackfillError("prepared_response_bytes_cannot_be_replaced")
            else:
                connection.execute(
                    """
                    UPDATE backfill_pages
                    SET status = 'PREPARED', response_body = ?,
                        response_sha256 = ?, response_received_at_ms = ?,
                        retry_not_before_ms = NULL, last_error = NULL
                    WHERE page_id = ?
                    """,
                    (
                        response.body,
                        response_sha,
                        response.received_at_ms,
                        page_id,
                    ),
                )
            for open_ms, payload_json in sorted(payload_json_by_open.items()):
                payload_sha = _sha256_bytes(payload_json.encode())
                existing = connection.execute(
                    """
                    SELECT payload_sha256, payload_json
                    FROM backfill_outbox_rows
                    WHERE page_id = ? AND candle_open_time_ms = ?
                    """,
                    (page_id, int(open_ms)),
                ).fetchone()
                if existing is not None and (
                    str(existing["payload_sha256"]) != payload_sha
                    or str(existing["payload_json"]) != payload_json
                ):
                    raise Historical5mBackfillError("prepared_outbox_bytes_cannot_be_replaced")
                connection.execute(
                    """
                    INSERT OR IGNORE INTO backfill_outbox_rows(
                        page_id, job_id, symbol, candle_open_time_ms,
                        candle_close_time_ms, payload_sha256,
                        payload_json, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'PREPARED')
                    """,
                    (
                        page_id,
                        str(page["job_id"]),
                        str(page["symbol"]),
                        int(open_ms),
                        int(open_ms) + LABEL_SLOT_MILLISECONDS - 1,
                        payload_sha,
                        payload_json,
                    ),
                )
            count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM backfill_outbox_rows WHERE page_id = ?",
                    (page_id,),
                ).fetchone()[0]
            )
            if count != int(page["requested_rows"]):
                raise Historical5mBackfillError("prepared_outbox_row_count_mismatch")
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def record_page_error(
        self,
        *,
        page_id: str,
        error: str,
        retry_not_before_ms: int | None,
    ) -> None:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                UPDATE backfill_pages SET
                    last_error = ?,
                    retry_not_before_ms = CASE
                        WHEN ? IS NULL THEN retry_not_before_ms
                        WHEN retry_not_before_ms IS NULL THEN ?
                        ELSE MAX(retry_not_before_ms, ?)
                    END
                WHERE page_id = ? AND status = 'INTENT'
                """,
                (
                    str(error)[:512],
                    retry_not_before_ms,
                    retry_not_before_ms,
                    retry_not_before_ms,
                    page_id,
                ),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def prepared_pages(self, job_id: str, *, limit: int) -> list[str]:
        connection = self._connect()
        try:
            return [
                str(row["page_id"])
                for row in connection.execute(
                    """
                    SELECT page_id FROM backfill_pages
                    WHERE job_id = ? AND status = 'PREPARED'
                    ORDER BY start_open_time_ms ASC
                    LIMIT ?
                    """,
                    (job_id, int(limit)),
                )
            ]
        finally:
            connection.close()

    def prepared_rows(self, page_id: str) -> list[dict[str, Any]]:
        connection = self._connect()
        try:
            rows = []
            for row in connection.execute(
                """
                SELECT * FROM backfill_outbox_rows
                WHERE page_id = ? AND status = 'PREPARED'
                ORDER BY candle_open_time_ms ASC
                LIMIT ?
                """,
                (page_id, MAX_BINANCE_PAGE_ROWS + 1),
            ):
                payload_json = str(row["payload_json"])
                if _sha256_bytes(payload_json.encode()) != str(row["payload_sha256"]):
                    raise Historical5mBackfillError("backfill_outbox_payload_sha_mismatch")
                rows.append(dict(row))
            if len(rows) > MAX_BINANCE_PAGE_ROWS:
                raise Historical5mBackfillError("backfill_outbox_page_unbounded")
            return rows
        finally:
            connection.close()

    def all_page_rows(self, page_id: str) -> list[dict[str, Any]]:
        connection = self._connect()
        try:
            rows = [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT * FROM backfill_outbox_rows
                    WHERE page_id = ? ORDER BY candle_open_time_ms
                    LIMIT ?
                    """,
                    (page_id, MAX_BINANCE_PAGE_ROWS + 1),
                )
            ]
            if len(rows) > MAX_BINANCE_PAGE_ROWS:
                raise Historical5mBackfillError("backfill_outbox_page_unbounded")
            for row in rows:
                payload_json = str(row["payload_json"])
                if _sha256_bytes(payload_json.encode()) != str(row["payload_sha256"]):
                    raise Historical5mBackfillError("backfill_outbox_payload_sha_mismatch")
            return rows
        finally:
            connection.close()

    def commit_page_terminal_state(
        self,
        *,
        job_id: str,
        page_id: str,
        terminal_status: str,
        archive_transaction_id: str,
        archive_append_receipt_sha256: str,
        slot_evidence: Mapping[str, Any],
        archive_result: Any | None = None,
        archive_result_recorded_at_ms: int | None = None,
        recovered_append_evidence: Mapping[str, Any] | None = None,
        recovered_at_ms: int | None = None,
        append_attempt_id: str,
        terminal_authority_receipt_sha256: str,
        terminal_probe: Mapping[str, Any],
        terminal_recorded_at_ms: int,
    ) -> int:
        """Atomically seal evidence, all slot receipts, outbox, page, and cursor."""

        if terminal_status not in {
            "ARCHIVED_REST_PROVEN_ABSENT_SLOT",
            "RECONCILED_KNOWN_ARCHIVE_TRANSACTION",
            "RECONCILED_CRASH_COMMITTED_REST_APPEND",
        }:
            raise Historical5mBackfillError("backfill_terminal_status_invalid")
        if bool(archive_result is not None) and bool(recovered_append_evidence is not None):
            raise Historical5mBackfillError("page_terminal_evidence_kinds_mutually_exclusive")
        transaction_id = str(archive_transaction_id or "")
        append_receipt_sha = str(archive_append_receipt_sha256 or "")
        if not transaction_id or not re.fullmatch(r"[0-9a-f]{64}", append_receipt_sha):
            raise Historical5mBackfillError("page_terminal_archive_identity_invalid")
        terminal_ms = _strict_ms(terminal_recorded_at_ms)
        if terminal_ms is None:
            raise Historical5mBackfillError("page_terminal_recorded_clock_invalid")

        connection = self._connect()
        transitioned = 0
        try:
            connection.execute("BEGIN IMMEDIATE")
            page = connection.execute(
                "SELECT * FROM backfill_pages WHERE page_id = ?",
                (page_id,),
            ).fetchone()
            if page is None or str(page["job_id"]) != job_id:
                raise Historical5mBackfillError("backfill_page_missing_or_job_mismatch")
            if str(page["status"]) not in {"PREPARED", "COMPLETE"}:
                raise Historical5mBackfillError("backfill_page_not_prepared_for_terminal_commit")
            rows = list(
                connection.execute(
                    """
                    SELECT * FROM backfill_outbox_rows
                    WHERE page_id = ? ORDER BY candle_open_time_ms
                    LIMIT ?
                    """,
                    (page_id, MAX_BINANCE_PAGE_ROWS + 1),
                )
            )
            if len(rows) != int(page["requested_rows"]) or len(rows) > MAX_BINANCE_PAGE_ROWS:
                raise Historical5mBackfillError("page_terminal_outbox_row_count_mismatch")
            for row in rows:
                payload_json = str(row["payload_json"])
                if _sha256_bytes(payload_json.encode()) != str(row["payload_sha256"]):
                    raise Historical5mBackfillError("backfill_outbox_payload_sha_mismatch")

            attempt = connection.execute(
                """
                SELECT * FROM backfill_append_attempts
                WHERE attempt_id = ? AND job_id = ? AND page_id = ?
                """,
                (append_attempt_id, job_id, page_id),
            ).fetchone()
            if attempt is None or int(attempt["attempted_at_ms"]) > terminal_ms:
                raise Historical5mBackfillError(
                    "page_terminal_append_attempt_missing_or_clock_invalid"
                )
            self._validate_append_attempt_row(connection, attempt)
            terminal_probe_sha, terminal_probe_json = self._validate_registered_authority_probe(
                connection,
                job_id=job_id,
                authority_receipt_sha256=terminal_authority_receipt_sha256,
                inactive_probe=terminal_probe,
            )
            resolution_evidence = {
                "schema_version": APPEND_ATTEMPT_RESOLUTION_SCHEMA_VERSION,
                "attempt_id": append_attempt_id,
                "resolution_kind": terminal_status,
                "archive_transaction_id": transaction_id,
                "archive_append_receipt_sha256": append_receipt_sha,
                "append_authority_receipt_sha256": str(attempt["authority_receipt_sha256"]),
                "append_probe_sha256": str(attempt["inactive_probe_sha256"]),
                "terminal_authority_receipt_sha256": (terminal_authority_receipt_sha256),
                "terminal_probe_sha256": terminal_probe_sha,
                "slot_evidence_sha256": stable_sha256(dict(slot_evidence)),
            }
            resolution_json = canonical_json(resolution_evidence)
            resolution_sha = _sha256_bytes(resolution_json.encode())
            resolution_values = (
                append_attempt_id,
                job_id,
                page_id,
                terminal_status,
                resolution_sha,
                resolution_json,
                terminal_authority_receipt_sha256,
                terminal_probe_sha,
                terminal_probe_json,
                terminal_ms,
            )
            existing_resolution = connection.execute(
                """
                SELECT * FROM backfill_append_attempt_resolutions
                WHERE attempt_id = ?
                """,
                (append_attempt_id,),
            ).fetchone()
            resolution_columns = (
                "attempt_id",
                "job_id",
                "page_id",
                "resolution_kind",
                "resolution_evidence_sha256",
                "resolution_evidence_json",
                "reconciliation_authority_receipt_sha256",
                "reconciliation_probe_sha256",
                "reconciliation_probe_json",
                "resolved_at_ms",
            )
            if (
                existing_resolution is not None
                and tuple(existing_resolution[key] for key in resolution_columns)
                != resolution_values
            ):
                raise Historical5mBackfillError("page_terminal_append_attempt_resolution_conflict")
            connection.execute(
                """
                INSERT OR IGNORE INTO backfill_append_attempt_resolutions(
                    attempt_id, job_id, page_id, resolution_kind,
                    resolution_evidence_sha256, resolution_evidence_json,
                    reconciliation_authority_receipt_sha256,
                    reconciliation_probe_sha256, reconciliation_probe_json,
                    resolved_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                resolution_values,
            )

            terminal_slot_evidence = {
                **dict(slot_evidence),
                "append_attempt_id": append_attempt_id,
                "append_authority_receipt_sha256": str(attempt["authority_receipt_sha256"]),
                "append_probe_sha256": str(attempt["inactive_probe_sha256"]),
                "terminal_authority_receipt_sha256": (terminal_authority_receipt_sha256),
                "terminal_probe_sha256": terminal_probe_sha,
            }

            if archive_result is not None:
                if archive_result_recorded_at_ms is None:
                    raise Historical5mBackfillError("archive_transaction_recorded_at_missing")
                material = {
                    "transaction_id": archive_result.transaction_id,
                    "attempted_rows": archive_result.attempted_rows,
                    "inserted_rows": archive_result.inserted_rows,
                    "duplicate_rows": archive_result.duplicate_rows,
                    "total_unique_rows": archive_result.total_unique_rows,
                    "archive_chain_sha256": archive_result.archive_chain_sha256,
                    "batch_sha256": archive_result.batch_sha256,
                    "append_receipt_sha256": archive_result.append_receipt_sha256,
                    "transaction_committed": archive_result.transaction_committed,
                    "transaction_readback_verified": (archive_result.transaction_readback_verified),
                    "retention_policy": archive_result.retention_policy,
                    "automatic_pruning_enabled": archive_result.automatic_pruning_enabled,
                }
                result_json = canonical_json(material)
                result_sha = _sha256_bytes(result_json.encode())
                values = (
                    str(archive_result.transaction_id),
                    job_id,
                    page_id,
                    result_sha,
                    result_json,
                    int(archive_result.inserted_rows),
                    int(archive_result.duplicate_rows),
                    int(archive_result_recorded_at_ms),
                )
                if str(archive_result.transaction_id) != transaction_id:
                    raise Historical5mBackfillError("page_terminal_transaction_id_mismatch")
                existing = connection.execute(
                    "SELECT * FROM backfill_archive_transactions WHERE page_id = ?",
                    (page_id,),
                ).fetchone()
                columns = (
                    "transaction_id",
                    "job_id",
                    "page_id",
                    "result_sha256",
                    "result_json",
                    "inserted_rows",
                    "duplicate_rows",
                    "recorded_at_ms",
                )
                if existing is not None and tuple(existing[key] for key in columns) != values:
                    raise Historical5mBackfillError("archive_transaction_receipt_conflict")
                connection.execute(
                    """
                    INSERT OR IGNORE INTO backfill_archive_transactions(
                        transaction_id, job_id, page_id, result_sha256,
                        result_json, inserted_rows, duplicate_rows, recorded_at_ms
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    values,
                )

            if recovered_append_evidence is not None:
                if recovered_at_ms is None:
                    raise Historical5mBackfillError("recovered_append_recorded_at_missing")
                evidence_json = canonical_json(dict(recovered_append_evidence))
                evidence_sha = _sha256_bytes(evidence_json.encode())
                values = (
                    page_id,
                    job_id,
                    len(rows),
                    evidence_sha,
                    evidence_json,
                    int(recovered_at_ms),
                )
                existing = connection.execute(
                    "SELECT * FROM backfill_recovered_append_intents WHERE page_id = ?",
                    (page_id,),
                ).fetchone()
                columns = (
                    "page_id",
                    "job_id",
                    "recovered_rows",
                    "evidence_sha256",
                    "evidence_json",
                    "recovered_at_ms",
                )
                if existing is not None and tuple(existing[key] for key in columns) != values:
                    raise Historical5mBackfillError("recovered_append_intent_conflict")
                connection.execute(
                    """
                    INSERT OR IGNORE INTO backfill_recovered_append_intents(
                        page_id, job_id, recovered_rows, evidence_sha256,
                        evidence_json, recovered_at_ms
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    values,
                )

            known = connection.execute(
                "SELECT result_sha256, result_json FROM backfill_archive_transactions "
                "WHERE page_id = ?",
                (page_id,),
            ).fetchone()
            recovered = connection.execute(
                "SELECT evidence_sha256, evidence_json FROM "
                "backfill_recovered_append_intents WHERE page_id = ?",
                (page_id,),
            ).fetchone()
            if (known is None) == (recovered is None):
                raise Historical5mBackfillError(
                    "page_terminal_requires_exactly_one_archive_evidence"
                )
            if known is not None:
                known_json = str(known["result_json"])
                if _sha256_bytes(known_json.encode()) != str(known["result_sha256"]):
                    raise Historical5mBackfillError("archive_transaction_receipt_hash_mismatch")
                known_result = json.loads(known_json)
                if (
                    known_result.get("transaction_id") != transaction_id
                    or known_result.get("append_receipt_sha256") != append_receipt_sha
                ):
                    raise Historical5mBackfillError("page_terminal_known_evidence_mismatch")
            else:
                recovered_json = str(recovered["evidence_json"])
                if _sha256_bytes(recovered_json.encode()) != str(recovered["evidence_sha256"]):
                    raise Historical5mBackfillError("recovered_append_intent_hash_mismatch")
                recovered_payload = json.loads(recovered_json)
                attestation = recovered_payload.get("exact_tail_transaction_attestation")
                if not isinstance(attestation, Mapping) or (
                    attestation.get("transaction_id") != transaction_id
                    or attestation.get("append_receipt_sha256") != append_receipt_sha
                ):
                    raise Historical5mBackfillError("page_terminal_recovered_evidence_mismatch")

            for outbox in rows:
                open_ms = int(outbox["candle_open_time_ms"])
                if str(outbox["status"]) != "PREPARED":
                    receipt = connection.execute(
                        """
                        SELECT receipt_sha256, receipt_json
                        FROM backfill_slot_receipts
                        WHERE job_id = ? AND symbol = ? AND candle_open_time_ms = ?
                        """,
                        (job_id, str(outbox["symbol"]), open_ms),
                    ).fetchone()
                    if receipt is None or (
                        str(outbox["terminal_receipt_sha256"]) != str(receipt["receipt_sha256"])
                        or str(outbox["terminal_receipt_json"]) != str(receipt["receipt_json"])
                    ):
                        raise Historical5mBackfillError(
                            "terminal_outbox_slot_receipt_binding_mismatch"
                        )
                    continue
                close_ms = open_ms + LABEL_SLOT_MILLISECONDS - 1
                receipt_material = {
                    "schema_version": SLOT_RECEIPT_SCHEMA_VERSION,
                    "job_id": job_id,
                    "symbol": str(outbox["symbol"]),
                    "candle_open_time_ms": open_ms,
                    "candle_close_time_ms": close_ms,
                    "status": terminal_status,
                    "archive_source": "binance_rest",
                    "archive_payload_sha256": str(outbox["payload_sha256"]),
                    "evidence": terminal_slot_evidence,
                }
                receipt_json = canonical_json(receipt_material)
                receipt_sha = _sha256_bytes(receipt_json.encode())
                existing_receipt = connection.execute(
                    """
                    SELECT receipt_sha256, receipt_json
                    FROM backfill_slot_receipts
                    WHERE job_id = ? AND symbol = ? AND candle_open_time_ms = ?
                    """,
                    (job_id, str(outbox["symbol"]), open_ms),
                ).fetchone()
                if existing_receipt is not None and (
                    str(existing_receipt["receipt_sha256"]) != receipt_sha
                    or str(existing_receipt["receipt_json"]) != receipt_json
                ):
                    raise Historical5mBackfillError("backfill_slot_receipt_conflict")
                connection.execute(
                    """
                    INSERT OR IGNORE INTO backfill_slot_receipts(
                        job_id, symbol, candle_open_time_ms, candle_close_time_ms,
                        status, archive_source, archive_payload_sha256,
                        receipt_sha256, receipt_json
                    ) VALUES (?, ?, ?, ?, ?, 'binance_rest', ?, ?, ?)
                    """,
                    (
                        job_id,
                        str(outbox["symbol"]),
                        open_ms,
                        close_ms,
                        terminal_status,
                        str(outbox["payload_sha256"]),
                        receipt_sha,
                        receipt_json,
                    ),
                )
                connection.execute(
                    """
                    UPDATE backfill_outbox_rows SET
                        status = ?, archive_transaction_id = ?,
                        archive_append_receipt_sha256 = ?,
                        terminal_receipt_sha256 = ?, terminal_receipt_json = ?
                    WHERE page_id = ? AND candle_open_time_ms = ?
                      AND status = 'PREPARED'
                    """,
                    (
                        terminal_status,
                        transaction_id,
                        append_receipt_sha,
                        receipt_sha,
                        receipt_json,
                        page_id,
                        open_ms,
                    ),
                )
                if int(connection.execute("SELECT changes()").fetchone()[0]) != 1:
                    raise Historical5mBackfillError("terminal_outbox_atomic_update_failed")
                transitioned += 1

            pending = int(
                connection.execute(
                    "SELECT COUNT(*) FROM backfill_outbox_rows "
                    "WHERE page_id = ? AND status = 'PREPARED'",
                    (page_id,),
                ).fetchone()[0]
            )
            terminal_receipts = int(
                connection.execute(
                    """
                    SELECT COUNT(*) FROM backfill_outbox_rows AS outbox
                    JOIN backfill_slot_receipts AS receipt
                      ON receipt.job_id = outbox.job_id
                     AND receipt.symbol = outbox.symbol
                     AND receipt.candle_open_time_ms = outbox.candle_open_time_ms
                     AND receipt.receipt_sha256 = outbox.terminal_receipt_sha256
                    WHERE outbox.page_id = ?
                    """,
                    (page_id,),
                ).fetchone()[0]
            )
            if pending or terminal_receipts != len(rows):
                raise Historical5mBackfillError("page_terminal_receipt_set_incomplete")
            if str(page["status"]) == "PREPARED":
                connection.execute(
                    "UPDATE backfill_pages SET status = 'COMPLETE' "
                    "WHERE page_id = ? AND status = 'PREPARED'",
                    (page_id,),
                )
                if int(connection.execute("SELECT changes()").fetchone()[0]) != 1:
                    raise Historical5mBackfillError("page_terminal_atomic_complete_failed")
            self._advance_cursor(
                connection,
                job_id=job_id,
                symbol=str(page["symbol"]),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

        readback = self.page_header(page_id)
        if str(readback["status"]) != "COMPLETE":
            raise Historical5mBackfillError("page_terminal_postcommit_readback_failed")
        return transitioned

    def status(self, job_id: str) -> dict[str, Any]:
        connection = self._connect()
        try:
            counts = {
                str(row["status"]): int(row["receipt_count"])
                for row in connection.execute(
                    """
                    SELECT status, receipt_count
                    FROM backfill_slot_receipt_status_counts
                    WHERE job_id = ? ORDER BY status
                    """,
                    (job_id,),
                )
            }
            progress = connection.execute(
                "SELECT * FROM backfill_job_progress WHERE job_id = ?",
                (job_id,),
            ).fetchone()
            if progress is None:
                raise Historical5mBackfillError("backfill_job_progress_missing")
            page_counts = {
                status: count
                for status, count in (
                    ("INTENT", int(progress["page_intent_count"])),
                    ("PREPARED", int(progress["page_prepared_count"])),
                    ("COMPLETE", int(progress["page_complete_count"])),
                )
                if count
            }
            inventory_pages = int(progress["inventory_pages_sealed"])
            checkpoint = bool(progress["inventory_checkpoint_sealed"])
            manifest = bool(progress["inventory_manifest_sealed"])
            rest_intent_manifest = bool(progress["rest_intent_manifest_sealed"])
            final = bool(progress["final_verification_sealed"])
            pending_rest = any(page_counts.get(status, 0) for status in ("INTENT", "PREPARED"))
            phase = (
                "COMPLETE_READY_FOR_WSS_ACTIVATION"
                if final
                else "FINAL_FULL_VERIFICATION_REQUIRED"
                if rest_intent_manifest and not pending_rest
                else "REST_ABSENT_SLOT_APPEND"
                if rest_intent_manifest
                else "REST_INTENT_SET_SEAL"
                if manifest
                else "SPARSE_INVENTORY_SEAL"
                if checkpoint
                else "FULL_INTEGRITY_CHECKPOINT_REQUIRED"
            )
            return {
                "job_id": job_id,
                "job_complete": final,
                "phase": phase,
                "inventory_checkpoint_sealed": checkpoint,
                "inventory_pages_sealed": inventory_pages,
                "inventory_manifest_sealed": manifest,
                "rest_intent_manifest_sealed": rest_intent_manifest,
                "rest_page_counts": page_counts,
                "slot_receipt_counts": counts,
            }
        finally:
            connection.close()


def _slot_count(spec: BackfillJobSpec) -> int:
    return (spec.end_open_time_ms_exclusive - spec.start_open_time_ms) // LABEL_SLOT_MILLISECONDS


def _inventory_pages_per_symbol(spec: BackfillJobSpec) -> int:
    slots = _slot_count(spec)
    return (slots + spec.page_limit - 1) // spec.page_limit


def _expected_inventory_page_count(spec: BackfillJobSpec) -> int:
    return len(spec.symbols) * _inventory_pages_per_symbol(spec)


def _inventory_page_spec(
    spec: BackfillJobSpec,
    *,
    symbol: str,
    page_index: int,
    integrity_proof_sha256: str,
) -> dict[str, Any]:
    pages_per_symbol = _inventory_pages_per_symbol(spec)
    if page_index < 0 or page_index >= pages_per_symbol:
        raise Historical5mBackfillError("inventory_page_index_out_of_bounds")
    offset = page_index * spec.page_limit
    rows = min(spec.page_limit, _slot_count(spec) - offset)
    first_close = (
        spec.start_open_time_ms + offset * LABEL_SLOT_MILLISECONDS + LABEL_SLOT_MILLISECONDS - 1
    )
    closes = [first_close + index * LABEL_SLOT_MILLISECONDS for index in range(rows)]
    identity = {
        "job_id": spec.job_id,
        "symbol": symbol,
        "page_index": page_index,
        "start_close_time_ms": closes[0],
        "end_close_time_ms": closes[-1],
        "integrity_proof_sha256": integrity_proof_sha256,
    }
    return {
        **identity,
        "inventory_page_id": f"canonical_5m_inventory_{stable_sha256(identity)}",
        "expected_close_times": closes,
    }


def _inventory_page_specs(
    spec: BackfillJobSpec,
    *,
    integrity_proof_sha256: str,
) -> Iterator[dict[str, Any]]:
    for symbol in spec.symbols:
        for page_index in range(_inventory_pages_per_symbol(spec)):
            yield _inventory_page_spec(
                spec,
                symbol=symbol,
                page_index=page_index,
                integrity_proof_sha256=integrity_proof_sha256,
            )


def _validate_coverage_page(
    *,
    page_spec: Mapping[str, Any],
    occupied_rows: Sequence[Mapping[str, Any]],
    coverage_proof: Mapping[str, Any],
    checkpoint: Mapping[str, Any],
) -> None:
    expected = [int(value) for value in page_spec["expected_close_times"]]
    if coverage_proof.get("status") != "VERIFIED_CANONICAL_5M_SPARSE_COVERAGE":
        raise Historical5mBackfillError("sparse_coverage_page_unverified")
    if coverage_proof.get("rejection_reasons") != []:
        raise Historical5mBackfillError("sparse_coverage_page_has_rejections")
    if coverage_proof.get("coverage_partition_complete") is not True:
        raise Historical5mBackfillError("sparse_coverage_partition_incomplete")
    if coverage_proof.get("indexed_snapshot_verified") is not True:
        raise Historical5mBackfillError("sparse_coverage_index_unverified")
    if (
        coverage_proof.get("start_close_time_ms") != expected[0]
        or coverage_proof.get("end_close_time_ms") != expected[-1]
    ):
        raise Historical5mBackfillError("sparse_coverage_bounds_mismatch")
    if (
        coverage_proof.get("symbol") != page_spec["symbol"]
        or coverage_proof.get("expected_rows") != len(expected)
        or coverage_proof.get("occupied_rows") != len(occupied_rows)
    ):
        raise Historical5mBackfillError("sparse_coverage_page_identity_mismatch")
    proof_checkpoint = coverage_proof.get("archive_integrity_checkpoint")
    integrity = checkpoint["integrity_proof"]
    expected_checkpoint = {
        "archive_chain_sha256": integrity.get("archive_chain_sha256"),
        "verified_rows": integrity.get("verified_rows"),
        "verified_max_sequence": integrity.get("verified_max_sequence"),
        "verified_append_receipts": integrity.get("verified_append_receipts"),
        "verified_postcommit_readback_receipts": integrity.get(
            "verified_postcommit_readback_receipts"
        ),
    }
    if proof_checkpoint != expected_checkpoint:
        raise Historical5mBackfillError("sparse_coverage_checkpoint_mismatch")
    occupied_by_close: dict[int, Mapping[str, Any]] = {}
    for row in occupied_rows:
        close_ms = int(row.get("candle_close_time") or 0)
        if close_ms in occupied_by_close:
            raise Historical5mBackfillError("sparse_coverage_duplicate_occupied_slot")
        validate_canonical_finalized_5m_candle(
            row,
            expected_symbol=str(page_spec["symbol"]),
        )
        occupied_by_close[close_ms] = row
    absent = [int(value) for value in coverage_proof.get("proven_absent_close_time_ms") or []]
    if coverage_proof.get("proven_absent_rows") != len(absent):
        raise Historical5mBackfillError("sparse_coverage_absent_count_mismatch")
    if sorted([*occupied_by_close, *absent]) != sorted(expected):
        raise Historical5mBackfillError("sparse_coverage_exact_partition_mismatch")
    identities = coverage_proof.get("occupied_identities")
    if not isinstance(identities, list):
        raise Historical5mBackfillError("sparse_coverage_identities_missing")
    expected_identities = [
        {
            "symbol": str(row["symbol"]),
            "candle_close_time_ms": int(row["candle_close_time"]),
            "candle_id": str(row["candle_id"]),
            "content_sha256": _sha256_bytes(canonical_json(row).encode()),
            "source": str(row["source"]),
            "is_backfilled": bool(row["is_backfilled"]),
        }
        for row in sorted(
            occupied_rows,
            key=lambda item: int(item["candle_close_time"]),
        )
    ]
    if identities != expected_identities:
        raise Historical5mBackfillError("sparse_coverage_identity_payload_mismatch")
    range_proof = coverage_proof.get("range_proof")
    if not isinstance(range_proof, Mapping) or (
        range_proof.get("archive_integrity_proof_reused") is not True
        or range_proof.get("archive_integrity_proof_current") is not True
        or range_proof.get("sparse_coverage_rows_verified") is not True
        or range_proof.get("rejection_reasons") != []
    ):
        raise Historical5mBackfillError("sparse_coverage_range_proof_unverified")
    coverage_material = {
        "schema_version": coverage_proof.get("schema_version"),
        "archive_path": coverage_proof.get("archive_path"),
        "symbol": coverage_proof.get("symbol"),
        "start_close_time_ms": expected[0],
        "end_close_time_ms": expected[-1],
        "expected_close_times": expected,
        "occupied_identities": identities,
        "proven_absent_close_time_ms": absent,
        "range_sha256": range_proof.get("range_sha256"),
        "archive_integrity_checkpoint": expected_checkpoint,
    }
    if coverage_proof.get("archive_path") != integrity.get("archive_path") or coverage_proof.get(
        "coverage_sha256"
    ) != stable_sha256(coverage_material):
        raise Historical5mBackfillError("sparse_coverage_content_hash_mismatch")


def _seal_manifest_if_complete(
    *,
    store: Historical5mBackfillStore,
    spec: BackfillJobSpec,
    job_id: str,
    checkpoint: Mapping[str, Any],
    inactive_probe: Mapping[str, Any],
    sealed_at_ms: int,
) -> bool:
    expected_specs = list(
        _inventory_page_specs(
            spec,
            integrity_proof_sha256=str(checkpoint["integrity_proof_sha256"]),
        )
    )
    stored_pages = store.inventory_pages(job_id)
    by_id = {str(page["inventory_page_id"]): page for page in stored_pages}
    if len(by_id) != len(stored_pages):
        raise Historical5mBackfillError("duplicate_inventory_page_identity")
    if any(page["inventory_page_id"] not in by_id for page in expected_specs):
        return False
    if set(by_id) != {str(page["inventory_page_id"]) for page in expected_specs}:
        raise Historical5mBackfillError("unexpected_inventory_page_for_job")
    page_material: list[dict[str, Any]] = []
    total_expected = 0
    total_occupied = 0
    total_absent = 0
    total_rest_intents = 0
    for expected in expected_specs:
        stored = by_id[str(expected["inventory_page_id"])]
        if (
            stored["symbol"] != expected["symbol"]
            or stored["page_index"] != expected["page_index"]
            or stored["expected_close_times"] != expected["expected_close_times"]
            or stored["integrity_proof_sha256"] != checkpoint["integrity_proof_sha256"]
        ):
            raise Historical5mBackfillError("inventory_page_manifest_binding_mismatch")
        expected_count = len(stored["expected_close_times"])
        occupied_count = len(stored["occupied_payloads"])
        absent_count = len(stored["proven_absent_close_times"])
        if occupied_count + absent_count != expected_count:
            raise Historical5mBackfillError("inventory_page_partition_count_mismatch")
        total_expected += expected_count
        total_occupied += occupied_count
        total_absent += absent_count
        total_rest_intents += len(
            _contiguous_chunks(
                stored["proven_absent_close_times"],
                limit=spec.page_limit,
            )
        )
        page_material.append(
            {
                "inventory_page_id": stored["inventory_page_id"],
                "symbol": stored["symbol"],
                "page_index": stored["page_index"],
                "start_close_time_ms": stored["expected_close_times"][0],
                "end_close_time_ms": stored["expected_close_times"][-1],
                "expected_rows": expected_count,
                "occupied_rows": occupied_count,
                "proven_absent_rows": absent_count,
                "coverage_sha256": stored["coverage_sha256"],
                "proven_absent_close_times_sha256": stable_sha256(
                    stored["proven_absent_close_times"]
                ),
                "occupied_payloads_sha256": stable_sha256(stored["occupied_payloads"]),
                "inactive_probe_sha256": stored["inactive_probe_sha256"],
            }
        )
    manifest = {
        "schema_version": INVENTORY_MANIFEST_SCHEMA_VERSION,
        "job_id": job_id,
        "archive_path": str(spec.archive_path),
        "symbols": list(spec.symbols),
        "start_open_time_ms": spec.start_open_time_ms,
        "end_open_time_ms_exclusive": spec.end_open_time_ms_exclusive,
        "authority_cutoff_open_time_ms": (spec.authority_cutoff.authority_cutoff_open_time_ms),
        "authority_attestation_sha256": stable_sha256(spec.authority_cutoff.contract()),
        "integrity_proof_sha256": checkpoint["integrity_proof_sha256"],
        "inventory_pages": page_material,
        "inventory_page_count": len(page_material),
        "expected_slot_count": total_expected,
        "occupied_slot_count": total_occupied,
        "proven_absent_slot_count": total_absent,
        "expected_rest_intent_count": total_rest_intents,
        "all_inventory_pages_sealed_before_rest_append": True,
        "wss_archive_producer_inactive": True,
        "manifest_seal_inactive_probe": dict(inactive_probe),
        "manifest_seal_inactive_probe_sha256": stable_sha256(inactive_probe),
    }
    store.seal_inventory_manifest(
        job_id=job_id,
        manifest=manifest,
        sealed_at_ms=sealed_at_ms,
    )
    return True


def _contiguous_chunks(values: Sequence[int], *, limit: int) -> list[list[int]]:
    chunks: list[list[int]] = []
    current: list[int] = []
    for value in sorted(int(item) for item in values):
        if current and (value != current[-1] + LABEL_SLOT_MILLISECONDS or len(current) >= limit):
            chunks.append(current)
            current = []
        current.append(value)
    if current:
        chunks.append(current)
    return chunks


def _expected_rest_intents(
    *,
    store: Historical5mBackfillStore,
    spec: BackfillJobSpec,
    job_id: str,
) -> list[dict[str, Any]]:
    if not store.inventory_manifest_exists(job_id):
        raise Historical5mBackfillError("rest_intents_require_sealed_inventory")
    expected: list[dict[str, Any]] = []
    for page in store.inventory_pages(job_id):
        for closes in _contiguous_chunks(
            page["proven_absent_close_times"],
            limit=spec.page_limit,
        ):
            request = BinanceKlineRequest(
                symbol=str(page["symbol"]),
                start_open_time_ms=closes[0] - LABEL_SLOT_MILLISECONDS + 1,
                end_close_time_ms=closes[-1],
                limit=len(closes),
            )
            request_json = canonical_json(request.contract())
            request_sha = _sha256_bytes(request_json.encode())
            identity_sha = stable_sha256(
                {
                    "job_id": job_id,
                    "request_sha256": request_sha,
                    "inventory_page_id": page["inventory_page_id"],
                    "coverage_sha256": page["coverage_sha256"],
                    "proven_absent_close_times": closes,
                }
            )
            expected.append(
                {
                    "page_id": f"canonical_5m_page_{identity_sha}",
                    "symbol": page["symbol"],
                    "request_sha256": request_sha,
                    "request": request.contract(),
                    "inventory_page_id": page["inventory_page_id"],
                    "coverage_sha256": page["coverage_sha256"],
                    "proven_absent_close_times": closes,
                }
            )
    return expected


def _materialize_and_seal_rest_intents(
    *,
    store: Historical5mBackfillStore,
    spec: BackfillJobSpec,
    job_id: str,
    inventory_manifest_receipt: Mapping[str, Any],
    inactive_probe: Mapping[str, Any],
    sealed_at_ms: int,
) -> int:
    expected = _expected_rest_intents(store=store, spec=spec, job_id=job_id)
    for intent in expected:
        request = BinanceKlineRequest.from_contract(intent["request"])
        page_id, _, _ = store.ensure_page_intent(
            job_id=job_id,
            request=request,
            inventory_page_id=str(intent["inventory_page_id"]),
            coverage_sha256=str(intent["coverage_sha256"]),
            proven_absent_close_times=intent["proven_absent_close_times"],
        )
        if page_id != intent["page_id"]:
            raise Historical5mBackfillError("materialized_rest_intent_identity_mismatch")
    actual = store.page_intents(job_id)
    if actual != expected:
        raise Historical5mBackfillError("rest_intent_set_not_exactly_bound_to_sparse_inventory")
    manifest = inventory_manifest_receipt["manifest"]
    if manifest.get("expected_rest_intent_count") != len(expected):
        raise Historical5mBackfillError("rest_intent_manifest_count_mismatch")
    bindings = [
        {
            "page_id": intent["page_id"],
            "symbol": intent["symbol"],
            "request_sha256": intent["request_sha256"],
            "inventory_page_id": intent["inventory_page_id"],
            "coverage_sha256": intent["coverage_sha256"],
            "proven_absent_close_times_sha256": stable_sha256(intent["proven_absent_close_times"]),
        }
        for intent in expected
    ]
    store.seal_rest_intent_manifest(
        job_id=job_id,
        manifest={
            "schema_version": REST_INTENT_MANIFEST_SCHEMA_VERSION,
            "job_id": job_id,
            "inventory_manifest_sha256": inventory_manifest_receipt["manifest_sha256"],
            "expected_rest_intent_count": len(bindings),
            "intent_bindings": bindings,
            "intent_bindings_sha256": stable_sha256(bindings),
            "all_rest_intents_durable_before_first_public_request": True,
            "intent_seal_inactive_probe": dict(inactive_probe),
            "intent_seal_inactive_probe_sha256": stable_sha256(inactive_probe),
        },
        sealed_at_ms=sealed_at_ms,
    )
    return len(expected)


def _validate_response_payloads(
    *,
    request: BinanceKlineRequest,
    response: PublicHttpResponse,
) -> dict[int, str]:
    if len(response.body) > MAX_RESPONSE_BYTES:
        raise Historical5mBackfillError("binance_kline_response_bytes_exceeded")
    try:
        decoded = json.loads(response.body.decode("utf-8"))
    except (UnicodeDecodeError, TypeError, ValueError) as exc:
        raise Historical5mBackfillError("binance_kline_response_json_invalid") from exc
    if not isinstance(decoded, list) or len(decoded) != request.limit:
        raise Historical5mBackfillError("binance_kline_response_row_count_mismatch")
    expected_opens = [
        request.start_open_time_ms + index * LABEL_SLOT_MILLISECONDS
        for index in range(request.limit)
    ]
    payloads: dict[int, str] = {}
    for expected_open, raw in zip(expected_opens, decoded, strict=True):
        if not isinstance(raw, list) or len(raw) < 11:
            raise Historical5mBackfillError("binance_kline_response_row_invalid")
        if isinstance(raw[0], bool) or isinstance(raw[6], bool):
            raise Historical5mBackfillError("binance_kline_response_slot_invalid")
        try:
            open_ms = int(raw[0])
            close_ms = int(raw[6])
        except (TypeError, ValueError) as exc:
            raise Historical5mBackfillError("binance_kline_response_slot_invalid") from exc
        if (
            open_ms != expected_open
            or close_ms != open_ms + LABEL_SLOT_MILLISECONDS - 1
            or close_ms > request.end_close_time_ms
        ):
            raise Historical5mBackfillError("binance_kline_response_slot_mismatch")
        # A candle becomes final only after its close clock has passed.
        if close_ms >= response.received_at_ms:
            raise Historical5mBackfillError("binance_kline_response_contains_unfinal_candle")
        candle = canonical_from_binance_rest(
            raw,
            symbol=request.symbol,
            timeframe="5m",
            ingested_at=response.received_at_ms,
        )
        payload = candle.to_dict()
        validate_canonical_finalized_5m_candle(
            payload,
            expected_symbol=request.symbol,
        )
        payload_json = canonical_json(payload)
        if open_ms in payloads:
            raise Historical5mBackfillError("binance_kline_response_duplicate_slot")
        payloads[open_ms] = payload_json
    return payloads


def _verified_empty_retry_range(
    *,
    proof: Mapping[str, Any],
    symbol: str,
    expected_close_times: Sequence[int],
) -> bool:
    return (
        proof.get("status") == "BLOCKED_CANONICAL_5M_LABEL_RANGE_UNVERIFIED"
        and proof.get("rejection_reasons") == ["LABEL_ARCHIVE_RANGE_ROW_COUNT_MISMATCH"]
        and proof.get("symbol") == symbol
        and proof.get("start_close_time_ms") == expected_close_times[0]
        and proof.get("end_close_time_ms") == expected_close_times[-1]
        and proof.get("expected_rows") == len(expected_close_times)
        and proof.get("loaded_rows") == 0
        and proof.get("sqlite_quick_check_verified") is True
        and proof.get("symbol_close_time_index_used") is True
        and proof.get("archive_schema_and_retention_verified") is True
        and proof.get("automatic_pruning_enabled") is False
    )


def _validated_exact_tail_attestation(
    *,
    attestation: Mapping[str, Any],
    archive_path: Path,
    payloads: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    validated_payloads = [validate_canonical_finalized_5m_candle(payload) for payload in payloads]
    expected_bindings = [
        {
            "symbol": str(validated["symbol"]),
            "candle_close_time_ms": int(validated["close_time_ms"]),
            "candle_id": str(validated["candle_id"]),
            "content_sha256": str(validated["content_sha256"]),
            "market_fact_sha256": str(validated["market_fact_sha256"]),
        }
        for validated in validated_payloads
    ]
    transaction_bindings = attestation.get("transaction_bindings")
    binding_fields = {
        "sequence",
        "symbol",
        "candle_close_time_ms",
        "candle_id",
        "content_sha256",
        "market_fact_sha256",
    }
    attestation_fields = {
        "schema_version",
        "archive_schema_version",
        "archive_path",
        "status",
        "transaction_scope_verified",
        "archive_integrity_verified",
        "terminal_full_integrity_verification_required",
        "expected_rows",
        "expected_batch_sha256",
        "expected_bindings_sha256",
        "transaction_id",
        "append_receipt_sha256",
        "postcommit_readback_receipt_sha256",
        "transaction_attestation_sha256",
        "rejection_reasons",
        "postcommit_recovery",
        "transaction_bindings",
        "attempted_rows",
        "inserted_rows",
        "duplicate_rows",
        "archive_total_unique_rows",
        "archive_chain_sha256",
        "transaction_is_current_tail",
    }
    if set(attestation) != attestation_fields:
        raise Historical5mBackfillError("exact_tail_transaction_attestation_fields_invalid")
    if (
        not isinstance(transaction_bindings, list)
        or len(transaction_bindings) != len(expected_bindings)
        or not all(
            isinstance(binding, Mapping) and set(binding) == binding_fields
            for binding in transaction_bindings
        )
    ):
        raise Historical5mBackfillError("exact_tail_transaction_bindings_missing")
    normalized_transaction_bindings = [dict(binding) for binding in transaction_bindings]
    stripped_bindings = [
        {key: binding[key] for key in expected}
        for binding, expected in zip(
            normalized_transaction_bindings,
            expected_bindings,
            strict=True,
        )
    ]
    sequences = [binding["sequence"] for binding in normalized_transaction_bindings]
    if any(
        isinstance(sequence, bool) or not isinstance(sequence, int) or sequence <= 0
        for sequence in sequences
    ) or (sequences and sequences != list(range(sequences[0], sequences[0] + len(sequences)))):
        raise Historical5mBackfillError("exact_tail_transaction_binding_sequences_invalid")
    expected_batch = stable_sha256(
        [
            {
                "symbol": binding["symbol"],
                "candle_close_time_ms": binding["candle_close_time_ms"],
                "candle_id": binding["candle_id"],
                "content_sha256": binding["content_sha256"],
                "market_fact_sha256": binding["market_fact_sha256"],
            }
            for binding in expected_bindings
        ]
    )
    sha_fields = (
        "expected_batch_sha256",
        "expected_bindings_sha256",
        "append_receipt_sha256",
        "postcommit_readback_receipt_sha256",
        "archive_chain_sha256",
        "transaction_attestation_sha256",
    )
    postcommit_recovery = attestation.get("postcommit_recovery")
    recovery_valid = (
        isinstance(postcommit_recovery, Mapping)
        and set(postcommit_recovery) == {"status", "pending_transactions", "recovered_transactions"}
        and postcommit_recovery.get("status") == "POSTCOMMIT_READBACK_RECOVERY_COMPLETE"
        and isinstance(postcommit_recovery.get("pending_transactions"), int)
        and not isinstance(postcommit_recovery.get("pending_transactions"), bool)
        and postcommit_recovery.get("pending_transactions") >= 0
        and postcommit_recovery.get("pending_transactions")
        == postcommit_recovery.get("recovered_transactions")
    )
    transaction_id = str(attestation.get("transaction_id") or "")
    archive_total_unique_rows = attestation.get("archive_total_unique_rows")
    if (
        attestation.get("schema_version") != EXACT_TAIL_TRANSACTION_ATTESTATION_SCHEMA_VERSION
        or attestation.get("archive_schema_version") != ARCHIVE_SCHEMA_VERSION
        or attestation.get("status") != "VERIFIED_CANONICAL_5M_EXACT_TAIL_TRANSACTION"
        or attestation.get("rejection_reasons") != []
        or attestation.get("transaction_scope_verified") is not True
        or attestation.get("archive_integrity_verified") is not False
        or attestation.get("terminal_full_integrity_verification_required") is not True
        or attestation.get("transaction_is_current_tail") is not True
        or attestation.get("archive_path") != str(Path(archive_path).resolve())
        or attestation.get("expected_rows") != len(payloads)
        or attestation.get("attempted_rows") != len(payloads)
        or attestation.get("inserted_rows") != len(payloads)
        or attestation.get("duplicate_rows") != 0
        or attestation.get("expected_batch_sha256") != expected_batch
        or attestation.get("expected_bindings_sha256") != stable_sha256(expected_bindings)
        or stripped_bindings != expected_bindings
        or not re.fullmatch(r"canonical_5m_append_[0-9a-f]{32}", transaction_id)
        or isinstance(archive_total_unique_rows, bool)
        or not isinstance(archive_total_unique_rows, int)
        or archive_total_unique_rows < len(payloads)
        or not recovery_valid
        or any(
            not re.fullmatch(r"[0-9a-f]{64}", str(attestation.get(field) or ""))
            for field in sha_fields
        )
    ):
        raise Historical5mBackfillError("exact_tail_transaction_attestation_unverified")
    attestation_material = {
        "schema_version": EXACT_TAIL_TRANSACTION_ATTESTATION_SCHEMA_VERSION,
        "archive_schema_version": ARCHIVE_SCHEMA_VERSION,
        "archive_path": str(Path(archive_path).resolve()),
        "status": "VERIFIED_CANONICAL_5M_EXACT_TAIL_TRANSACTION",
        "transaction_scope_verified": True,
        "archive_integrity_verified": False,
        "transaction_id": transaction_id,
        "expected_batch_sha256": expected_batch,
        "expected_bindings_sha256": stable_sha256(expected_bindings),
        "transaction_bindings": normalized_transaction_bindings,
        "attempted_rows": len(payloads),
        "inserted_rows": len(payloads),
        "duplicate_rows": 0,
        "append_receipt_sha256": attestation["append_receipt_sha256"],
        "postcommit_readback_receipt_sha256": attestation["postcommit_readback_receipt_sha256"],
        "archive_total_unique_rows": archive_total_unique_rows,
        "archive_chain_sha256": attestation["archive_chain_sha256"],
        "transaction_is_current_tail": True,
        "terminal_full_integrity_verification_required": True,
        "rejection_reasons": [],
    }
    if stable_sha256(attestation_material) != attestation["transaction_attestation_sha256"]:
        raise Historical5mBackfillError("exact_tail_transaction_attestation_hash_mismatch")
    return dict(attestation)


def _finalize_prepared_page(
    *,
    store: Historical5mBackfillStore,
    archive: DurableCanonical5mLabelArchive,
    job_id: str,
    page_id: str,
    observed_at_ms: int,
    authority_receipt_sha256: str,
    append_probe: Mapping[str, Any],
    capture_authority_probe: Callable[[], tuple[int, dict[str, Any]]],
) -> int:
    page = store.page_header(page_id)
    response_received_at_ms = page["response_received_at_ms"]
    if response_received_at_ms is None or int(response_received_at_ms) > observed_at_ms:
        raise Historical5mBackfillError("prepared_response_observation_clock_after_append_clock")
    all_rows = store.all_page_rows(page_id)
    expected_closes = [int(row["candle_close_time_ms"]) for row in all_rows]
    sealed_absent = [
        int(value) for value in json.loads(str(page["proven_absent_close_times_json"]))
    ]
    if expected_closes != sealed_absent:
        raise Historical5mBackfillError("outbox_page_not_exactly_bound_to_proven_absent_slots")
    payloads = [json.loads(str(row["payload_json"])) for row in all_rows]
    append_attempt, attempt_created = store.begin_append_attempt(
        job_id=job_id,
        page_id=page_id,
        authority_receipt_sha256=authority_receipt_sha256,
        inactive_probe=append_probe,
        attempted_at_ms=observed_at_ms,
    )
    known_transaction = store.archive_transaction_for_page(page_id)
    recovered_intent = store.recovered_append_intent_for_page(page_id)
    new_recovered_evidence: dict[str, Any] | None = None
    if known_transaction is not None and recovered_intent is not None:
        raise Historical5mBackfillError(
            "known_and_recovered_append_evidence_are_mutually_exclusive"
        )
    if not attempt_created:
        postcommit_recovery = archive.recover_pending_postcommit_readbacks()
        if postcommit_recovery.get("status") not in {
            "NO_ARCHIVE_TO_RECOVER",
            "POSTCOMMIT_READBACK_RECOVERY_COMPLETE",
        } or postcommit_recovery.get("pending_transactions") != postcommit_recovery.get(
            "recovered_transactions"
        ):
            raise Historical5mBackfillError("archive_postcommit_recovery_unverified")
        if known_transaction is None and recovered_intent is None:
            tail_attestation = archive.attest_exact_tail_transaction(payloads)
            if tail_attestation.get("status") == ("VERIFIED_CANONICAL_5M_EXACT_TAIL_TRANSACTION"):
                verified_attestation = _validated_exact_tail_attestation(
                    attestation=tail_attestation,
                    archive_path=archive.path,
                    payloads=payloads,
                )
                evidence = {
                    "schema_version": ("canonical_5m_recovered_append_intent_v2"),
                    "page_id": page_id,
                    "payload_sha256": [str(row["payload_sha256"]) for row in all_rows],
                    "exact_tail_transaction_attestation": (verified_attestation),
                    "archive_rows_exactly_match_durable_precommit_intent": (True),
                    "wss_archive_producer_inactive": True,
                    "unknown_receipt_count_expected": 1,
                    "append_attempt_id": str(append_attempt["attempt_id"]),
                    "append_authority_receipt_sha256": str(
                        append_attempt["authority_receipt_sha256"]
                    ),
                }
                new_recovered_evidence = evidence
                recovered_intent = {
                    "page_id": page_id,
                    "job_id": job_id,
                    "recovered_rows": len(all_rows),
                    "evidence": evidence,
                    "recovered_at_ms": int(append_attempt["attempted_at_ms"]),
                }
        request = store.page_request(page_id)
        existing_rows, range_proof = archive.verified_range(
            symbol=request.symbol,
            start_close_time_ms=expected_closes[0],
            end_close_time_ms=expected_closes[-1],
            training_observed_at=observed_at_ms,
            limit=len(expected_closes),
        )
        if existing_rows is None:
            if known_transaction is not None or recovered_intent is not None:
                raise Historical5mBackfillError(
                    "append_evidence_exists_but_archive_range_is_missing"
                )
            if not _verified_empty_retry_range(
                proof=range_proof,
                symbol=request.symbol,
                expected_close_times=expected_closes,
            ):
                raise Historical5mBackfillError("append_retry_empty_archive_range_not_verified")
        else:
            if existing_rows != payloads:
                if any(row.get("source") == "binance_wss" for row in existing_rows):
                    raise Historical5mBackfillError(
                        "wss_authority_overlap_detected_after_fixed_cutoff_inventory"
                    )
                raise Historical5mBackfillError("append_retry_archive_payload_conflict")
            if recovered_intent is None and known_transaction is None:
                raise Historical5mBackfillError(
                    "unseen_append_requires_exact_tail_transaction_attestation"
                )
            status = (
                "RECONCILED_KNOWN_ARCHIVE_TRANSACTION"
                if known_transaction is not None
                else "RECONCILED_CRASH_COMMITTED_REST_APPEND"
            )
            transaction_id = (
                str(known_transaction["transaction_id"])
                if known_transaction is not None
                else str(
                    recovered_intent["evidence"]["exact_tail_transaction_attestation"][
                        "transaction_id"
                    ]
                )
            )
            receipt_sha = (
                str(known_transaction["result"]["append_receipt_sha256"])
                if known_transaction is not None
                else str(
                    recovered_intent["evidence"]["exact_tail_transaction_attestation"][
                        "append_receipt_sha256"
                    ]
                )
            )
            terminal_ms, terminal_probe = capture_authority_probe()
            return store.commit_page_terminal_state(
                job_id=job_id,
                page_id=page_id,
                terminal_status=status,
                archive_transaction_id=transaction_id,
                archive_append_receipt_sha256=receipt_sha,
                slot_evidence={
                    "range_sha256": range_proof.get("range_sha256"),
                    "durable_append_intent_reconciled": True,
                },
                recovered_append_evidence=new_recovered_evidence,
                recovered_at_ms=(
                    int(append_attempt["attempted_at_ms"])
                    if new_recovered_evidence is not None
                    else None
                ),
                append_attempt_id=str(append_attempt["attempt_id"]),
                terminal_authority_receipt_sha256=authority_receipt_sha256,
                terminal_probe=terminal_probe,
                terminal_recorded_at_ms=terminal_ms,
            )

        retry_ms, retry_probe = capture_authority_probe()
        store.seal_empty_append_attempt_resolution(
            job_id=job_id,
            page_id=page_id,
            attempt_id=str(append_attempt["attempt_id"]),
            reconciliation_authority_receipt_sha256=authority_receipt_sha256,
            reconciliation_probe=retry_probe,
            empty_range_proof=range_proof,
            resolved_at_ms=retry_ms,
        )
        append_attempt, attempt_created = store.begin_append_attempt(
            job_id=job_id,
            page_id=page_id,
            authority_receipt_sha256=authority_receipt_sha256,
            inactive_probe=retry_probe,
            attempted_at_ms=retry_ms,
        )
        if not attempt_created:
            raise Historical5mBackfillError("append_retry_attempt_not_durably_created")

    try:
        result = archive.append_candles(payloads)
    except Canonical5mIdentityConflictError as exc:
        request = store.page_request(page_id)
        existing_rows, proof = archive.verified_range(
            symbol=request.symbol,
            start_close_time_ms=expected_closes[0],
            end_close_time_ms=expected_closes[-1],
            training_observed_at=observed_at_ms,
            limit=len(expected_closes),
        )
        if existing_rows is not None and any(
            row.get("source") == "binance_wss" for row in existing_rows
        ):
            raise Historical5mBackfillError(
                "wss_authority_overlap_detected_at_archive_append"
            ) from exc
        raise Historical5mBackfillError(
            "archive_identity_conflict_for_proven_absent_rest_page:"
            + ",".join(proof.get("rejection_reasons") or [])
        ) from exc
    if (
        result.attempted_rows != len(all_rows)
        or result.inserted_rows != len(all_rows)
        or result.duplicate_rows != 0
        or result.transaction_committed is not True
        or result.transaction_readback_verified is not True
    ):
        raise Historical5mBackfillError("fresh_absent_slot_append_result_not_exactly_inserted")
    terminal_ms, terminal_probe = capture_authority_probe()
    return store.commit_page_terminal_state(
        job_id=job_id,
        page_id=page_id,
        terminal_status="ARCHIVED_REST_PROVEN_ABSENT_SLOT",
        archive_transaction_id=result.transaction_id,
        archive_append_receipt_sha256=result.append_receipt_sha256,
        slot_evidence={
            "batch_sha256": result.batch_sha256,
            "coverage_sha256": str(page["coverage_sha256"]),
            "transaction_readback_verified": True,
        },
        archive_result=result,
        archive_result_recorded_at_ms=terminal_ms,
        append_attempt_id=str(append_attempt["attempt_id"]),
        terminal_authority_receipt_sha256=authority_receipt_sha256,
        terminal_probe=terminal_probe,
        terminal_recorded_at_ms=terminal_ms,
    )


def _terminal_exact_transaction_identity_proofs(
    *,
    store: Historical5mBackfillStore,
    archive: DurableCanonical5mLabelArchive,
    transactions: Sequence[Mapping[str, Any]],
    recovered: Sequence[Mapping[str, Any]],
    terminal_attempts: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Rebind every durable page intent to its actual archive transaction."""

    proofs: list[dict[str, Any]] = []
    for record in [*transactions, *recovered]:
        page_id = str(record.get("page_id") or "")
        if not page_id:
            raise Historical5mBackfillError("terminal_exact_transaction_page_id_missing")
        page_rows = store.all_page_rows(page_id)
        payloads = [json.loads(str(row["payload_json"])) for row in page_rows]
        payload_sha256 = [str(row["payload_sha256"]) for row in page_rows]
        if not payloads:
            raise Historical5mBackfillError("terminal_exact_transaction_payloads_missing")
        attempt_proof = terminal_attempts.get(page_id)
        if (
            not isinstance(attempt_proof, Mapping)
            or attempt_proof.get("resolution_kind") == "PROVEN_EMPTY_NO_ARCHIVE_COMMIT"
        ):
            raise Historical5mBackfillError("terminal_exact_transaction_append_attempt_missing")

        stored_result: Mapping[str, Any] | None = None
        stored_postcommit_receipt_sha256: str | None = None
        if "result" in record:
            result = record.get("result")
            result_fields = {
                "transaction_id",
                "attempted_rows",
                "inserted_rows",
                "duplicate_rows",
                "total_unique_rows",
                "archive_chain_sha256",
                "batch_sha256",
                "append_receipt_sha256",
                "transaction_committed",
                "transaction_readback_verified",
                "retention_policy",
                "automatic_pruning_enabled",
            }
            if not isinstance(result, Mapping) or set(result) != result_fields:
                raise Historical5mBackfillError("stored_archive_transaction_result_fields_invalid")
            transaction_id = str(result.get("transaction_id") or "")
            append_receipt_sha256 = str(result.get("append_receipt_sha256") or "")
            if (
                result.get("attempted_rows") != len(payloads)
                or result.get("inserted_rows") != len(payloads)
                or result.get("duplicate_rows") != 0
                or result.get("transaction_committed") is not True
                or result.get("transaction_readback_verified") is not True
                or result.get("retention_policy") != RETENTION_POLICY
                or result.get("automatic_pruning_enabled") is not False
            ):
                raise Historical5mBackfillError("stored_archive_transaction_result_not_exact")
            stored_result = result
            evidence_kind = "KNOWN_APPEND_RESULT"
            if attempt_proof.get("resolution_kind") not in {
                "ARCHIVED_REST_PROVEN_ABSENT_SLOT",
                "RECONCILED_KNOWN_ARCHIVE_TRANSACTION",
            }:
                raise Historical5mBackfillError("known_append_attempt_resolution_kind_invalid")
        else:
            evidence = record.get("evidence")
            evidence_fields = {
                "schema_version",
                "page_id",
                "payload_sha256",
                "exact_tail_transaction_attestation",
                "archive_rows_exactly_match_durable_precommit_intent",
                "wss_archive_producer_inactive",
                "unknown_receipt_count_expected",
                "append_attempt_id",
                "append_authority_receipt_sha256",
            }
            if (
                not isinstance(evidence, Mapping)
                or set(evidence) != evidence_fields
                or evidence.get("schema_version") != "canonical_5m_recovered_append_intent_v2"
                or evidence.get("page_id") != page_id
                or evidence.get("payload_sha256") != payload_sha256
                or evidence.get("archive_rows_exactly_match_durable_precommit_intent") is not True
                or evidence.get("wss_archive_producer_inactive") is not True
                or evidence.get("unknown_receipt_count_expected") != 1
                or not str(evidence.get("append_attempt_id") or "").startswith(
                    "canonical_5m_backfill_attempt_"
                )
                or not re.fullmatch(
                    r"[0-9a-f]{64}",
                    str(evidence.get("append_authority_receipt_sha256") or ""),
                )
                or record.get("recovered_rows") != len(payloads)
            ):
                raise Historical5mBackfillError("stored_recovered_append_intent_evidence_invalid")
            stored_tail_attestation = _validated_exact_tail_attestation(
                attestation=evidence["exact_tail_transaction_attestation"],
                archive_path=archive.path,
                payloads=payloads,
            )
            transaction_id = str(stored_tail_attestation["transaction_id"])
            append_receipt_sha256 = str(stored_tail_attestation["append_receipt_sha256"])
            stored_postcommit_receipt_sha256 = str(
                stored_tail_attestation["postcommit_readback_receipt_sha256"]
            )
            evidence_kind = "RECOVERED_EXACT_TAIL_ATTESTATION"
            if attempt_proof.get("resolution_kind") != ("RECONCILED_CRASH_COMMITTED_REST_APPEND"):
                raise Historical5mBackfillError("recovered_append_attempt_resolution_kind_invalid")
            if evidence.get("append_attempt_id") != attempt_proof.get("attempt_id") or evidence.get(
                "append_authority_receipt_sha256"
            ) != attempt_proof.get("append_authority_receipt_sha256"):
                raise Historical5mBackfillError("recovered_append_attempt_authority_mismatch")

        if (
            attempt_proof.get("archive_transaction_id") != transaction_id
            or attempt_proof.get("archive_append_receipt_sha256") != append_receipt_sha256
        ):
            raise Historical5mBackfillError("terminal_append_attempt_archive_identity_mismatch")
        proof = archive.attest_exact_transaction_identity(
            transaction_id=transaction_id,
            candles=payloads,
            expected_append_receipt_sha256=append_receipt_sha256,
        )
        if (
            proof.get("status") != "VERIFIED_CANONICAL_5M_EXACT_TRANSACTION_IDENTITY"
            or proof.get("transaction_identity_verified") is not True
            or proof.get("rejection_reasons") != []
            or proof.get("archive_path") != str(archive.path)
            or proof.get("transaction_id") != transaction_id
            or proof.get("expected_rows") != len(payloads)
            or proof.get("append_receipt_sha256") != append_receipt_sha256
            or (
                stored_postcommit_receipt_sha256 is not None
                and proof.get("postcommit_readback_receipt_sha256")
                != stored_postcommit_receipt_sha256
            )
            or (
                stored_result is not None
                and (
                    proof.get("expected_batch_sha256") != stored_result.get("batch_sha256")
                    or proof.get("transaction_id") != stored_result.get("transaction_id")
                    or proof.get("transaction_total_unique_rows")
                    != stored_result.get("total_unique_rows")
                    or proof.get("transaction_archive_chain_sha256")
                    != stored_result.get("archive_chain_sha256")
                )
            )
            or not re.fullmatch(
                r"[0-9a-f]{64}",
                str(proof.get("transaction_identity_attestation_sha256") or ""),
            )
        ):
            raise Historical5mBackfillError("terminal_exact_transaction_identity_unverified")
        proofs.append(
            {
                "page_id": page_id,
                "evidence_kind": evidence_kind,
                "transaction_id": transaction_id,
                "append_receipt_sha256": append_receipt_sha256,
                "transaction_identity_attestation_sha256": proof[
                    "transaction_identity_attestation_sha256"
                ],
                "transaction_is_current_tail": proof["transaction_is_current_tail"],
                "append_attempt_id": attempt_proof["attempt_id"],
                "append_authority_receipt_sha256": attempt_proof["append_authority_receipt_sha256"],
                "append_probe_sha256": attempt_proof["append_probe_sha256"],
                "reconciliation_authority_receipt_sha256": attempt_proof[
                    "reconciliation_authority_receipt_sha256"
                ],
                "reconciliation_probe_sha256": attempt_proof["reconciliation_probe_sha256"],
            }
        )
    return sorted(proofs, key=lambda value: str(value["page_id"]))


def _run_historical_5m_backfill_locked(
    *,
    spec: BackfillJobSpec,
    bounds: BackfillRunBounds,
    state_path: Path,
    transport: PublicKlineTransport,
    clock_ms: Callable[[], int],
    wss_inactive_probe: Callable[[], Mapping[str, Any]],
    writer_lease: Canonical5mArchiveWriterLease,
    before_public_request: Callable[[BinanceKlineRequest], None] | None = None,
    on_rate_limit: Callable[[PublicHttpResponse], None] | None = None,
) -> dict[str, Any]:
    """Run one fixed-cutoff phase without concurrent WSS archive authority."""

    validated_spec = spec.validated()
    validated_bounds = bounds.validated()
    if validated_bounds.max_slots < min(
        validated_spec.page_limit,
        _slot_count(validated_spec),
    ):
        raise Historical5mBackfillError("backfill_max_slots_smaller_than_one_inventory_page")
    run_ms, initial_probe = _capture_inactive_probe(
        probe_callback=wss_inactive_probe,
        spec=validated_spec,
        clock_ms=clock_ms,
    )
    if validated_spec.end_open_time_ms_exclusive - 1 >= run_ms:
        raise Historical5mBackfillError("backfill_requested_range_not_final")
    store = Historical5mBackfillStore(state_path)
    job_id = store.ensure_job(validated_spec, created_at_ms=run_ms)
    writer_lease.validate_for(validated_spec.archive_path)
    archive = DurableCanonical5mLabelArchive(
        validated_spec.archive_path,
        writer_lease=writer_lease,
    )
    governor = LocalWeightGovernor(
        budget_per_minute=validated_bounds.local_weight_budget_per_minute,
        max_weight_per_run=validated_bounds.max_request_weight_per_run,
    )
    pages_requested = 0
    pages_recovered = 0
    inventory_pages_sealed = 0
    slots_examined = 0
    slots_terminal = 0
    full_scans = 0
    paused_reason: str | None = None

    checkpoint = store.inventory_checkpoint(job_id)
    if checkpoint is None:
        intent_id = f"historical_5m_backfill_init:{job_id[-64:]}"

        def _initialize_pristine_archive() -> tuple[Mapping[str, Any], dict[str, Any]]:
            nonlocal full_scans
            initialization = archive.initialize_empty_archive(initialization_intent_id=intent_id)
            full_scans += 1
            initialized_proof = initialization.get("archive_integrity_proof")
            initialized_receipt = {
                "initialization_intent_id": intent_id,
                "initialization_receipt_sha256": initialization.get(
                    "initialization_receipt_sha256"
                ),
                "initialization_receipt_json": initialization.get("initialization_receipt_json"),
                "empty_genesis_integrity_verified": initialization.get(
                    "empty_genesis_integrity_verified"
                ),
            }
            receipt_json = str(initialized_receipt["initialization_receipt_json"] or "")
            if (
                _sha256_bytes(receipt_json.encode())
                != initialized_receipt["initialization_receipt_sha256"]
                or initialized_receipt["empty_genesis_integrity_verified"] is not True
                or not isinstance(initialized_proof, Mapping)
            ):
                raise Historical5mBackfillError("empty_archive_initialization_receipt_unverified")
            return initialized_proof, initialized_receipt

        writer_lease.validate_for(validated_spec.archive_path)
        archive_file_exists = validated_spec.archive_path.is_file()
        archive_file_is_zero_bytes = (
            archive_file_exists and validated_spec.archive_path.stat().st_size == 0
        )
        initialization_receipt: dict[str, Any] | None = None
        if not archive_file_exists or archive_file_is_zero_bytes:
            proof, initialization_receipt = _initialize_pristine_archive()
        else:
            proof = archive.verify_integrity()
            full_scans += 1
            genesis_chain_sha256 = hashlib.sha256(
                f"{ARCHIVE_SCHEMA_VERSION}:GENESIS".encode()
            ).hexdigest()
            if (
                isinstance(proof, Mapping)
                and proof.get("status") == "VERIFIED_CANONICAL_5M_LABEL_ARCHIVE"
                and proof.get("archive_integrity_verified") is True
                and proof.get("rejection_reasons") == []
                and proof.get("verified_rows") == 0
                and proof.get("verified_max_sequence") == 0
                and proof.get("verified_append_receipts") == 0
                and proof.get("verified_postcommit_readback_receipts") == 0
                and proof.get("archive_chain_sha256") == genesis_chain_sha256
            ):
                proof, initialization_receipt = _initialize_pristine_archive()
        if not isinstance(proof, Mapping) or (
            proof.get("archive_integrity_verified") is not True
            or proof.get("status") != "VERIFIED_CANONICAL_5M_LABEL_ARCHIVE"
            or proof.get("rejection_reasons") != []
        ):
            raise Historical5mBackfillError("initial_archive_full_integrity_proof_unverified")
        store.seal_inventory_checkpoint(
            job_id=job_id,
            integrity_proof=proof,
            authority_attestation=validated_spec.authority_cutoff.contract(),
            inactive_probe=initial_probe,
            initialization_receipt=initialization_receipt,
            sealed_at_ms=run_ms,
        )
        checkpoint = store.inventory_checkpoint(job_id)
    assert checkpoint is not None
    if (
        checkpoint["authority_scope_sha256"]
        != validated_spec.authority_cutoff.authority_scope_sha256
        or not store.authority_receipt_exists(
            job_id=job_id,
            receipt_sha256=str(checkpoint["authority_attestation_sha256"]),
            authority_scope_sha256=str(checkpoint["authority_scope_sha256"]),
        )
    ):
        raise Historical5mBackfillError("stored_authority_scope_or_receipt_mismatch")

    final_header = store.final_verification_header(job_id)
    manifest_header = store.inventory_manifest_header(job_id)
    if final_header is None and manifest_header is None:
        if store.append_evidence_exists(job_id):
            raise Historical5mBackfillError("rest_append_evidence_exists_before_inventory_manifest")
        if not archive.integrity_proof_is_current(checkpoint["integrity_proof"]):
            raise Historical5mBackfillError("inventory_checkpoint_stale_before_inventory_complete")
        stop_inventory = False
        for symbol in validated_spec.symbols:
            page_index = store.next_inventory_page_index(
                job_id,
                symbol=symbol,
            )
            while page_index < _inventory_pages_per_symbol(validated_spec):
                page_spec = _inventory_page_spec(
                    validated_spec,
                    symbol=symbol,
                    page_index=page_index,
                    integrity_proof_sha256=str(checkpoint["integrity_proof_sha256"]),
                )
                page_rows = len(page_spec["expected_close_times"])
                if (
                    inventory_pages_sealed >= validated_bounds.max_pages
                    or slots_examined + page_rows > validated_bounds.max_slots
                ):
                    stop_inventory = True
                    break
                current_ms, inventory_probe = _capture_inactive_probe(
                    probe_callback=wss_inactive_probe,
                    spec=validated_spec,
                    clock_ms=clock_ms,
                )
                occupied, coverage = archive.verified_coverage(
                    symbol=symbol,
                    start_close_time_ms=int(page_spec["expected_close_times"][0]),
                    end_close_time_ms=int(page_spec["expected_close_times"][-1]),
                    training_observed_at=current_ms,
                    limit=page_rows,
                    archive_integrity_proof=checkpoint["integrity_proof"],
                )
                if occupied is None:
                    raise Historical5mBackfillError(
                        "sparse_inventory_page_blocked:"
                        + ",".join(coverage.get("rejection_reasons") or [])
                    )
                _validate_coverage_page(
                    page_spec=page_spec,
                    occupied_rows=occupied,
                    coverage_proof=coverage,
                    checkpoint=checkpoint,
                )
                store.seal_inventory_page(
                    inventory_page_id=str(page_spec["inventory_page_id"]),
                    job_id=job_id,
                    symbol=symbol,
                    page_index=page_index,
                    expected_close_times=page_spec["expected_close_times"],
                    occupied_rows=occupied,
                    coverage_proof=coverage,
                    integrity_proof_sha256=str(checkpoint["integrity_proof_sha256"]),
                    inactive_probe=inventory_probe,
                    sealed_at_ms=current_ms,
                )
                inventory_pages_sealed += 1
                slots_examined += page_rows
                page_index += 1
            if stop_inventory:
                break
        if store.inventory_page_count(job_id) == _expected_inventory_page_count(validated_spec):
            manifest_ms, manifest_probe = _capture_inactive_probe(
                probe_callback=wss_inactive_probe,
                spec=validated_spec,
                clock_ms=clock_ms,
            )
            if not archive.integrity_proof_is_current(checkpoint["integrity_proof"]):
                raise Historical5mBackfillError("inventory_checkpoint_stale_before_manifest_seal")
            _seal_manifest_if_complete(
                store=store,
                spec=validated_spec,
                job_id=job_id,
                checkpoint=checkpoint,
                inactive_probe=manifest_probe,
                sealed_at_ms=manifest_ms,
            )
            if not archive.integrity_proof_is_current(checkpoint["integrity_proof"]):
                raise Historical5mBackfillError("inventory_checkpoint_stale_after_manifest_seal")
            manifest_header = store.inventory_manifest_header(job_id)

    if manifest_header is not None and final_header is None:
        if not store.append_started(job_id) and not archive.integrity_proof_is_current(
            checkpoint["integrity_proof"]
        ):
            raise Historical5mBackfillError(
                "archive_changed_after_inventory_before_first_rest_append"
            )
        intent_manifest_header = store.rest_intent_manifest_header(job_id)
        if intent_manifest_header is None:
            if store.append_started(job_id):
                raise Historical5mBackfillError(
                    "rest_append_started_before_complete_intent_manifest"
                )
            intent_ms, intent_probe = _capture_inactive_probe(
                probe_callback=wss_inactive_probe,
                spec=validated_spec,
                clock_ms=clock_ms,
            )
            manifest_receipt_for_seal = store.inventory_manifest(job_id)
            if manifest_receipt_for_seal is None:
                raise Historical5mBackfillError("sealed_inventory_manifest_missing")
            _materialize_and_seal_rest_intents(
                store=store,
                spec=validated_spec,
                job_id=job_id,
                inventory_manifest_receipt=manifest_receipt_for_seal,
                inactive_probe=intent_probe,
                sealed_at_ms=intent_ms,
            )
            intent_manifest_header = store.rest_intent_manifest_header(job_id)
        if intent_manifest_header is None:
            raise Historical5mBackfillError("complete_rest_intent_manifest_required_before_append")
        if not store.append_started(job_id) and not archive.integrity_proof_is_current(
            checkpoint["integrity_proof"]
        ):
            raise Historical5mBackfillError(
                "archive_changed_after_intent_seal_before_first_rest_append"
            )
        for page_id in store.work_pages(job_id, limit=validated_bounds.max_pages):
            page = store.page_header(page_id)
            requested_rows = int(page["requested_rows"])
            if slots_examined + requested_rows > validated_bounds.max_slots:
                break
            current_ms, _ = _capture_inactive_probe(
                probe_callback=wss_inactive_probe,
                spec=validated_spec,
                clock_ms=clock_ms,
            )
            inventory_page = store.inventory_page(str(page["inventory_page_id"]))
            sealed_absent = json.loads(str(page["proven_absent_close_times_json"]))
            request = store.page_request(page_id)
            request_closes = [
                request.start_open_time_ms
                + index * LABEL_SLOT_MILLISECONDS
                + LABEL_SLOT_MILLISECONDS
                - 1
                for index in range(request.limit)
            ]
            if (
                str(page["coverage_sha256"]) != inventory_page["coverage_sha256"]
                or request.end_close_time_ms != request_closes[-1]
                or request_closes != sealed_absent
                or not set(sealed_absent).issubset(set(inventory_page["proven_absent_close_times"]))
            ):
                raise Historical5mBackfillError("rest_page_not_bound_to_sealed_sparse_inventory")
            response: PublicHttpResponse | None = None
            if str(page["status"]) == "INTENT":
                retry_not_before = page["retry_not_before_ms"]
                if retry_not_before is not None and current_ms < int(retry_not_before):
                    paused_reason = "durable_retry_cooldown_active"
                    break
                try:
                    governor.reserve(request, observed_at_ms=current_ms)
                    if before_public_request is not None:
                        before_public_request(request)
                    response = transport.fetch(request)
                    pages_requested += 1
                    response_received_at_ms = _strict_ms(response.received_at_ms)
                    if response_received_at_ms is None or response_received_at_ms < current_ms:
                        raise Historical5mBackfillError(
                            "binance_response_clock_moved_backward_during_request"
                        )
                    if response.status_code in {418, 429}:
                        store.record_page_error(
                            page_id=page_id,
                            error=f"binance_http_{response.status_code}",
                            retry_not_before_ms=_retry_after_ms(response),
                        )
                        if on_rate_limit is not None:
                            on_rate_limit(response)
                        paused_reason = f"binance_http_{response.status_code}_cooldown"
                        break
                    if response.status_code != 200:
                        store.record_page_error(
                            page_id=page_id,
                            error=f"binance_http_{response.status_code}",
                            retry_not_before_ms=None,
                        )
                        raise Historical5mBackfillError(
                            f"binance_public_kline_http_{response.status_code}"
                        )
                    payloads = _validate_response_payloads(
                        request=request,
                        response=response,
                    )
                    store.prepare_page(
                        page_id=page_id,
                        response=response,
                        payload_json_by_open=payloads,
                    )
                except Historical5mBackfillPaused as exc:
                    paused_reason = str(exc)
                    break
            else:
                pages_recovered += 1
            append_ms, append_probe = _capture_inactive_probe(
                probe_callback=wss_inactive_probe,
                spec=validated_spec,
                clock_ms=clock_ms,
            )
            slots_terminal += _finalize_prepared_page(
                store=store,
                archive=archive,
                job_id=job_id,
                page_id=page_id,
                observed_at_ms=append_ms,
                authority_receipt_sha256=(validated_spec.authority_cutoff.receipt_sha256),
                append_probe=append_probe,
                capture_authority_probe=lambda: _capture_inactive_probe(
                    probe_callback=wss_inactive_probe,
                    spec=validated_spec,
                    clock_ms=clock_ms,
                ),
            )
            slots_examined += requested_rows
            if response is not None:
                try:
                    governor.observe(response)
                except Historical5mBackfillPaused as exc:
                    paused_reason = str(exc)
                    break

        if not store.work_pages(job_id, limit=1) and paused_reason is None:
            manifest_receipt = store.inventory_manifest(job_id)
            intent_manifest_receipt = store.rest_intent_manifest(job_id)
            if manifest_receipt is None or intent_manifest_receipt is None:
                raise Historical5mBackfillError("terminal_full_manifests_required")
            current_ms, terminal_probe = _capture_inactive_probe(
                probe_callback=wss_inactive_probe,
                spec=validated_spec,
                clock_ms=clock_ms,
            )
            final_proof = archive.verify_integrity()
            full_scans += 1
            post_verify_ms, post_verify_probe = _capture_inactive_probe(
                probe_callback=wss_inactive_probe,
                spec=validated_spec,
                clock_ms=clock_ms,
            )
            if not archive.integrity_proof_is_current(final_proof):
                raise Historical5mBackfillError(
                    "terminal_integrity_proof_stale_before_receipt_seal"
                )
            transactions = store.archive_transactions(job_id)
            recovered = store.recovered_append_intents(job_id)
            transaction_pages = {str(row["page_id"]) for row in transactions}
            recovered_pages = {str(row["page_id"]) for row in recovered}
            expected_page_ids = {
                str(binding["page_id"])
                for binding in intent_manifest_receipt["manifest"]["intent_bindings"]
            }
            authority_receipts = store.authority_receipts(job_id)
            authority_receipt_bindings = [
                {
                    "receipt_sha256": str(row["receipt_sha256"]),
                    "attestation_id": str(row["attestation_id"]),
                    "authority_scope_sha256": str(row["authority_scope_sha256"]),
                    "attested_at_ms": int(row["attested_at_ms"]),
                    "valid_until_ms": int(row["valid_until_ms"]),
                    "first_observed_at_ms": int(row["first_observed_at_ms"]),
                }
                for row in authority_receipts
            ]
            if (
                not authority_receipt_bindings
                or any(
                    binding["authority_scope_sha256"]
                    != validated_spec.authority_cutoff.authority_scope_sha256
                    for binding in authority_receipt_bindings
                )
                or validated_spec.authority_cutoff.receipt_sha256
                not in {str(binding["receipt_sha256"]) for binding in authority_receipt_bindings}
            ):
                raise Historical5mBackfillError("terminal_authority_receipt_set_invalid")
            append_attempt_summary, terminal_attempts = store.append_attempt_authority_summary(
                job_id
            )
            if (
                transaction_pages & recovered_pages
                or transaction_pages | recovered_pages != expected_page_ids
                or set(terminal_attempts) != expected_page_ids
            ):
                raise Historical5mBackfillError(
                    "terminal_append_evidence_not_exactly_one_per_rest_intent"
                )
            progress = store.progress_header(job_id)
            if (
                progress["inventory_checkpoint_sealed"] != 1
                or progress["inventory_pages_sealed"]
                != _expected_inventory_page_count(validated_spec)
                or progress["inventory_manifest_sealed"] != 1
                or progress["rest_intent_manifest_sealed"] != 1
                or progress["page_intent_count"] != 0
                or progress["page_prepared_count"] != 0
                or progress["page_complete_count"] != len(expected_page_ids)
                or progress["slot_receipt_total"]
                != int(manifest_receipt["manifest"]["proven_absent_slot_count"])
                or progress["archive_transaction_count"] != len(transactions)
                or progress["archive_inserted_rows"]
                != sum(int(row["inserted_rows"]) for row in transactions)
                or progress["recovered_append_count"] != len(recovered)
                or progress["recovered_rows"]
                != sum(int(row["recovered_rows"]) for row in recovered)
                or progress["authority_receipt_count"] != len(authority_receipt_bindings)
                or progress["append_attempt_count"] != append_attempt_summary["attempt_count"]
                or progress["append_attempt_resolution_count"]
                != append_attempt_summary["attempt_count"]
                or progress["final_verification_sealed"] != 0
            ):
                raise Historical5mBackfillError("terminal_compact_progress_projection_mismatch")
            exact_transaction_identity_proofs = _terminal_exact_transaction_identity_proofs(
                store=store,
                archive=archive,
                transactions=transactions,
                recovered=recovered,
                terminal_attempts=terminal_attempts,
            )
            if len(exact_transaction_identity_proofs) != len(expected_page_ids):
                raise Historical5mBackfillError(
                    "terminal_exact_transaction_identity_count_mismatch"
                )
            manifest = manifest_receipt["manifest"]
            initial = checkpoint["integrity_proof"]
            inserted_rows = sum(int(row["inserted_rows"]) for row in transactions)
            recovered_rows = sum(int(row["recovered_rows"]) for row in recovered)
            expected_absent = int(manifest["proven_absent_slot_count"])
            expected_rows = int(initial["verified_rows"]) + inserted_rows + recovered_rows
            expected_max_sequence = (
                int(initial["verified_max_sequence"]) + inserted_rows + recovered_rows
            )
            expected_receipts = (
                int(initial["verified_append_receipts"]) + len(transactions) + len(recovered)
            )
            expected_postcommit = (
                int(initial["verified_postcommit_readback_receipts"])
                + len(transactions)
                + len(recovered)
            )
            if (
                final_proof.get("archive_integrity_verified") is not True
                or final_proof.get("rejection_reasons") != []
                or inserted_rows + recovered_rows != expected_absent
                or final_proof.get("verified_rows") != expected_rows
                or final_proof.get("verified_max_sequence") != expected_max_sequence
                or final_proof.get("verified_append_receipts") != expected_receipts
                or final_proof.get("verified_postcommit_readback_receipts") != expected_postcommit
            ):
                raise Historical5mBackfillError(
                    "terminal_full_integrity_or_exclusive_append_delta_mismatch"
                )
            verification = {
                "schema_version": FINAL_VERIFICATION_SCHEMA_VERSION,
                "job_id": job_id,
                "inventory_manifest_sha256": manifest_receipt["manifest_sha256"],
                "rest_intent_manifest_sha256": intent_manifest_receipt["manifest_sha256"],
                "initial_integrity_proof_sha256": checkpoint["integrity_proof_sha256"],
                "final_integrity_proof": final_proof,
                "known_append_transactions": len(transactions),
                "recovered_crash_append_intents": len(recovered),
                "inserted_rows": inserted_rows,
                "recovered_rows": recovered_rows,
                "expected_absent_rows": expected_absent,
                "exclusive_append_delta_verified": True,
                "exact_transaction_identities_verified": True,
                "exact_transaction_identity_proofs": (exact_transaction_identity_proofs),
                "exact_transaction_identity_proofs_sha256": stable_sha256(
                    exact_transaction_identity_proofs
                ),
                "terminal_wss_inactive_probe": terminal_probe,
                "post_verify_wss_inactive_probe": post_verify_probe,
                "post_verify_observed_at_ms": post_verify_ms,
                "authority_cutoff": validated_spec.authority_cutoff.contract(),
                "authority_scope": (validated_spec.authority_cutoff.authority_scope()),
                "authority_scope_sha256": (validated_spec.authority_cutoff.authority_scope_sha256),
                "current_authority_receipt_sha256": (
                    validated_spec.authority_cutoff.receipt_sha256
                ),
                "authority_receipt_bindings": authority_receipt_bindings,
                "authority_receipt_bindings_sha256": stable_sha256(authority_receipt_bindings),
                "append_attempt_authority_summary": append_attempt_summary,
                "wss_activation_performed": False,
                "status": "READY_FOR_WSS_ACTIVATION_AND_CUTOFF_TAIL_RECOVERY",
            }
            store.seal_final_verification(
                job_id=job_id,
                verification=verification,
                verified_at_ms=post_verify_ms,
            )
            final_header = store.final_verification_header(job_id)

    status = store.status(job_id)
    sealed_final_receipt = final_header or store.final_verification_header(job_id)
    wss_activation_ready = False
    archive_advanced_after_fixed_cutoff_completion = False
    post_completion_integrity_revalidation_sha256: str | None = None
    if sealed_final_receipt is not None:
        sealed_final_proof = sealed_final_receipt.get("final_integrity_proof")
        if not isinstance(sealed_final_proof, Mapping):
            raise Historical5mBackfillError("stored_final_verification_integrity_proof_missing")
        wss_activation_ready = archive.integrity_proof_is_current(sealed_final_proof)
        archive_advanced_after_fixed_cutoff_completion = not wss_activation_ready
        if archive_advanced_after_fixed_cutoff_completion:
            current_integrity = archive.verify_integrity()
            full_scans += 1
            if (
                current_integrity.get("archive_integrity_verified") is not True
                or current_integrity.get("rejection_reasons") != []
                or int(current_integrity.get("verified_rows") or -1)
                <= int(sealed_final_proof.get("verified_rows") or -1)
                or int(current_integrity.get("verified_max_sequence") or -1)
                <= int(sealed_final_proof.get("verified_max_sequence") or -1)
                or int(current_integrity.get("verified_append_receipts") or -1)
                <= int(sealed_final_proof.get("verified_append_receipts") or -1)
                or int(current_integrity.get("verified_postcommit_readback_receipts") or -1)
                <= int(sealed_final_proof.get("verified_postcommit_readback_receipts") or -1)
            ):
                raise Historical5mBackfillError(
                    "post_completion_archive_state_not_verified_monotonic_advance"
                )
            post_completion_integrity_revalidation_sha256 = stable_sha256(current_integrity)
            status["phase"] = "HISTORICAL_FIXED_CUTOFF_COMPLETE_ARCHIVE_TAIL_ADVANCED"
    return {
        "schema_version": "canonical_5m_historical_backfill_run_v2",
        **status,
        "archive_path": str(validated_spec.archive_path),
        "state_path": str(Path(state_path)),
        "pages_requested": pages_requested,
        "prepared_pages_recovered": pages_recovered,
        "inventory_pages_sealed_this_run": inventory_pages_sealed,
        "slots_examined": slots_examined,
        "slots_terminal_this_run": slots_terminal,
        "request_weight_reserved_this_run": (governor.request_weight_reserved_this_run),
        "max_request_weight_per_run": governor.max_weight_per_run,
        "request_weight_reserved_current_utc_minute": (
            governor.request_weight_reserved_current_utc_minute
        ),
        "local_request_weight_budget_per_utc_minute": (governor.budget_per_utc_minute),
        "request_weight_current_utc_minute": governor.current_utc_minute,
        "paused": paused_reason is not None,
        "paused_reason": paused_reason,
        "transport_role": "REST_PROVEN_ABSENT_SLOT_RECOVERY_ONLY",
        "authority_cutoff_open_time_ms": (
            validated_spec.authority_cutoff.authority_cutoff_open_time_ms
        ),
        "all_sparse_inventory_sealed_before_rest_append": (store.inventory_manifest_exists(job_id)),
        "all_rest_intents_sealed_before_public_request": (
            store.rest_intent_manifest_exists(job_id)
        ),
        "exact_prepared_payload_reused_on_retry": True,
        "credentials_used": False,
        "orders_or_account_mutations": False,
        "full_archive_integrity_scans_this_run": full_scans,
        "wss_activation_performed": False,
        "wss_activation_ready": wss_activation_ready,
        "archive_advanced_after_fixed_cutoff_completion": (
            archive_advanced_after_fixed_cutoff_completion
        ),
        "post_completion_integrity_revalidation_sha256": (
            post_completion_integrity_revalidation_sha256
        ),
    }


def run_historical_5m_backfill(
    *,
    spec: BackfillJobSpec,
    bounds: BackfillRunBounds,
    state_path: Path,
    transport: PublicKlineTransport,
    clock_ms: Callable[[], int],
    wss_inactive_probe: Callable[[], Mapping[str, Any]],
    before_public_request: Callable[[BinanceKlineRequest], None] | None = None,
    on_rate_limit: Callable[[PublicHttpResponse], None] | None = None,
) -> dict[str, Any]:
    """Hold the shared exact-path archive writer lease for the whole run."""

    validated_spec = spec.validated()
    validated_state_path = validate_historical_backfill_state_path(
        state_path=state_path,
        archive_path=validated_spec.archive_path,
    )
    try:
        writer_lease = Canonical5mArchiveWriterLease.acquire(validated_spec.archive_path)
    except Canonical5mArchiveWriterLeaseError as exc:
        raise Historical5mBackfillError(
            "historical_backfill_archive_writer_lease_unavailable"
        ) from exc
    with writer_lease:
        return _run_historical_5m_backfill_locked(
            spec=validated_spec,
            bounds=bounds,
            state_path=validated_state_path,
            transport=transport,
            clock_ms=clock_ms,
            wss_inactive_probe=wss_inactive_probe,
            writer_lease=writer_lease,
            before_public_request=before_public_request,
            on_rate_limit=on_rate_limit,
        )


def job_spec_as_jsonable(spec: BackfillJobSpec) -> dict[str, Any]:
    """Small CLI helper that avoids exposing Path objects in reports."""

    validated = spec.validated()
    return {
        "archive_path": str(validated.archive_path),
        "symbols": list(validated.symbols),
        "start_open_time_ms": validated.start_open_time_ms,
        "end_open_time_ms_exclusive": validated.end_open_time_ms_exclusive,
        "page_limit": validated.page_limit,
        "authority_cutoff": validated.authority_cutoff.contract(),
        "job_id": validated.job_id,
        "contract": validated.contract(),
    }
