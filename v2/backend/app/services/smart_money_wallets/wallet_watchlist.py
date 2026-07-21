"""Moralis candidate-wallet watchlist and durable Redis refresh contract.

The repository seed contains observation candidates.  It is not a smart-money
attestation: loading or publishing a row can never mark it verified or grant it
trainer authority.  The provider loop may poll the candidates while its normal
CU, cadence, identity, and trainer-isolation controls remain in force.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.services.smart_money_wallets.address_classifier import (
    DEFAULT_EXCHANGE_PATH,
    DEFAULT_EXCLUDED_PATH,
    SMART_BLOCKING_CATEGORIES,
)
from app.services.smart_money_wallets.endpoint_registry import (
    MORALIS_EVM_CHAIN_ALIASES,
    MORALIS_EVM_CHAIN_PARAMS,
)

WALLET_WATCHLIST_KEY = "v2:moralis:wallet_watchlist"
WALLET_WATCHLIST_STATUS_KEY = "v2:moralis:wallet_watchlist_status"
WALLET_PROFILE_KEY = "v2:moralis:wallet_profile:{chain}:{address}"
WALLET_ACTIVITY_KEY = "v2:moralis:wallet_activity:{chain}:{address}"
DEFAULT_SEED_PATH = (
    Path(__file__).resolve().parents[4] / "config" / "moralis" / "wallet_watchlist_seed.yaml"
)
_TRACKED_DEFAULT_SEED_PATH = DEFAULT_SEED_PATH
_TRACKED_DEFAULT_EXCLUDED_PATH = Path(DEFAULT_EXCLUDED_PATH)
_TRACKED_DEFAULT_EXCHANGE_PATH = Path(DEFAULT_EXCHANGE_PATH)
# These identities are reviewed code, independent of the mutable local YAML
# documents.  A schema-valid replacement at a tracked authority path therefore
# fails closed until its digest is intentionally reviewed and updated here.
_TRACKED_FILE_SHA256 = {
    _TRACKED_DEFAULT_SEED_PATH: "11f8dcf61023c0f251b1e94114e065aff004e05c6d29b7666c88dd335e407994",
    _TRACKED_DEFAULT_EXCLUDED_PATH: (
        "0dc53f2b3484334de27449d06b3381d80dfbc4690735c01509105dd0b8a5dc72"
    ),
    _TRACKED_DEFAULT_EXCHANGE_PATH: (
        "f10b02930872706dd84a075b3149e9aa8dcaa39df214024ef0d343cb3d0c2ab8"
    ),
}
SEED_SCHEMA_VERSION = "moralis_wallet_watchlist_seed_v1"
TIER_LIMITS = {"T0": 50, "T1": 250}
DEFAULT_WATCHLIST_TTL_SECONDS = 6 * 3600
_MAX_SEED_BYTES = 8 * 1024 * 1024
_EVM_ADDRESS = re.compile(r"0x[0-9a-f]{40}")


class WalletWatchlistSeedError(ValueError):
    """A bounded, non-sensitive reason that a candidate seed was rejected."""


def load_wallet_watchlist_seed(
    path: Path | str = DEFAULT_SEED_PATH,
    *,
    observed_at: datetime | None = None,
) -> list[dict[str, Any]]:
    """Load one exact, schema-valid, point-in-time-safe candidate seed."""

    return _load_seed_snapshot(path, observed_at=observed_at)["rows"]


def publish_wallet_watchlist(
    redis_client: Any,
    *,
    path: Path | str = DEFAULT_SEED_PATH,
    ttl_seconds: int = DEFAULT_WATCHLIST_TTL_SECONDS,
    observed_at: datetime | None = None,
) -> dict[str, Any]:
    """Publish the exact validated seed without making a Moralis request."""

    snapshot = _load_seed_snapshot(path, observed_at=observed_at)
    return _publish_snapshot(
        redis_client,
        snapshot=snapshot,
        ttl_seconds=ttl_seconds,
        refresh_action="PUBLISHED_EXPLICITLY",
    )


def refresh_candidate_wallet_watchlist(
    redis_client: Any | None,
    *,
    path: Path | str = DEFAULT_SEED_PATH,
    ttl_seconds: int = DEFAULT_WATCHLIST_TTL_SECONDS,
    observed_at: datetime | None = None,
) -> dict[str, Any]:
    """Restore or refresh the authoritative candidate watchlist safely.

    This is intentionally a local-file/Redis control-plane operation.  It does
    not hold a Moralis client, reserve CU, alter endpoint cadence claims, or
    release trainer isolation.  A malformed/local-future seed fails closed and
    never replaces the runtime watchlist.
    """

    now = _as_utc(observed_at)
    ttl = max(1, int(ttl_seconds))
    try:
        snapshot = _load_seed_snapshot(path, observed_at=now)
    except WalletWatchlistSeedError as exc:
        return _publish_refresh_failure_status(
            redis_client,
            reason=str(exc),
            ttl_seconds=ttl,
            generated_at=now,
        )
    except Exception:
        return _publish_refresh_failure_status(
            redis_client,
            reason="WATCHLIST_SEED_READ_FAILED",
            ttl_seconds=ttl,
            generated_at=now,
        )

    if redis_client is None:
        return _refresh_status(
            snapshot=snapshot,
            refresh_action="REDIS_UNAVAILABLE",
            refresh_succeeded=False,
            generated_at=now,
        )

    current_rows = _read_validated_wallet_watchlist(
        redis_client,
        snapshot=snapshot,
        observed_at=now,
    )
    current_status = _read_json(redis_client, WALLET_WATCHLIST_STATUS_KEY)
    main_ttl = _remaining_ttl(redis_client, WALLET_WATCHLIST_KEY)
    status_ttl = _remaining_ttl(redis_client, WALLET_WATCHLIST_STATUS_KEY)
    refresh_window = max(1, ttl // 3)
    status_matches = _status_matches_snapshot(current_status, snapshot=snapshot)
    ttl_is_durable = (
        main_ttl is not None
        and status_ttl is not None
        and main_ttl > refresh_window
        and status_ttl > refresh_window
    )
    if current_rows is not None and status_matches and ttl_is_durable:
        return _refresh_status(
            snapshot=snapshot,
            refresh_action="RETAINED_VALID_RUNTIME_COPY",
            refresh_succeeded=True,
            generated_at=now,
            remaining_ttl_seconds=min(main_ttl, status_ttl),
            refresh_before_expiry_seconds=refresh_window,
        )

    if current_rows is None:
        action = "REFRESHED_MISSING_OR_INVALID_RUNTIME_COPY"
    elif not status_matches:
        action = "REFRESHED_MISSING_OR_INVALID_STATUS"
    else:
        action = "REFRESHED_EXPIRING_RUNTIME_COPY"
    try:
        return _publish_snapshot(
            redis_client,
            snapshot=snapshot,
            ttl_seconds=ttl,
            refresh_action=action,
        )
    except Exception:
        return _refresh_status(
            snapshot=snapshot,
            refresh_action="REDIS_WRITE_FAILED",
            refresh_succeeded=False,
            generated_at=now,
            refresh_before_expiry_seconds=refresh_window,
        )


def wallet_watchlist_status(
    rows: Sequence[Mapping[str, Any]],
    *,
    source_path: str | None = None,
    source_file_sha256: str | None = None,
    canonical_rows_sha256: str | None = None,
    source_path_sha256: str | None = None,
    classifier_authority_sha256: str | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Build an address-free operational status for candidate rows.

    ``source_path`` remains accepted for API compatibility, but only its hash is
    emitted.  Host paths and raw wallet addresses do not belong in status/log
    payloads.
    """

    if source_path_sha256 is None and source_path:
        source_path_sha256 = hashlib.sha256(
            str(Path(source_path).resolve(strict=False)).encode("utf-8")
        ).hexdigest()
    counts = {
        tier: sum(1 for row in rows if row.get("tier") == tier) for tier in ("T0", "T1", "T2")
    }
    total = len(rows)
    return {
        "schema_version": "moralis_wallet_watchlist_status_v1",
        "status": "WATCHLIST_READY" if total else "CONFIGURED_NO_WATCHLIST",
        "dashboard_color": "YELLOW" if total else "GRAY",
        "generated_utc": _iso_utc(_as_utc(generated_at)),
        "source_file_sha256": source_file_sha256,
        "source_path_sha256": source_path_sha256,
        "canonical_rows_sha256": canonical_rows_sha256,
        "classifier_authority_sha256": classifier_authority_sha256,
        "wallet_watchlist_count": total,
        "candidate_wallet_count": total,
        "candidate_smart_wallet_count": total,
        "verified_smart_wallet_count": 0,
        "counts_as_smart_money_count": 0,
        "watchlist_semantics": "CANDIDATE_OBSERVATION_TARGETS_ONLY",
        "tier_counts": counts,
        "t0_max_wallets": TIER_LIMITS["T0"],
        "t1_max_wallets": TIER_LIMITS["T1"],
        "empty_wallet_list_marked_green": False,
        "wallets_added_without_source": False,
        # Cardinality alone cannot prove CU affordability.  The durable
        # scheduler computes that from endpoint costs, remaining UTC day/month
        # authority, and its fair-rotation cadence on every run.
        "starter_budget_supported": None,
        "starter_budget_support_evaluated_here": False,
        "candidate_polling_subject_to_durable_cu_ledger": True,
        "watchlist_refresh_reserves_compute_units": False,
        "unknown_wallet_called_smart_money": False,
        "all_rows_source_tagged": all(bool(str(row.get("source") or "").strip()) for row in rows),
        "all_rows_point_in_time_safe": all(row.get("point_in_time_safe") is True for row in rows),
        "raw_address_exposed_in_status": False,
        "raw_key_exposed": False,
        "trainer_authority": False,
        "prediction_authority": False,
        "risk_authority": False,
        "orchestrator_authority": False,
        "allocator_authority": False,
        "paper_authority": False,
        "live_authority": False,
        "core_system_blocked": False,
    }


def read_wallet_watchlist(
    redis_client: Any | None,
    *,
    path: Path | str = DEFAULT_SEED_PATH,
) -> list[dict[str, Any]]:
    """Read only an exact runtime copy of the current authoritative seed."""

    if redis_client is None:
        return []
    try:
        snapshot = _load_seed_snapshot(path)
    except (OSError, RuntimeError, ValueError):
        return []
    rows = _read_validated_wallet_watchlist(
        redis_client,
        snapshot=snapshot,
        observed_at=datetime.now(UTC),
    )
    if rows is None:
        return []
    return [
        {
            "chain": str(row["chain"]),
            "address": str(row["address"]),
            "tier": str(row["tier"]),
            "source": str(row["source"]),
        }
        for row in rows
    ]


def watchlist_counts(redis_client: Any | None) -> dict[str, Any]:
    payload = (
        _read_json(redis_client, WALLET_WATCHLIST_STATUS_KEY) if redis_client is not None else None
    )
    if isinstance(payload, Mapping):
        return {
            "status": payload.get("status") or "CONFIGURED_NO_WATCHLIST",
            "wallet_watchlist_count": int(payload.get("wallet_watchlist_count") or 0),
            "candidate_wallet_count": int(payload.get("candidate_wallet_count") or 0),
            "verified_smart_wallet_count": int(payload.get("verified_smart_wallet_count") or 0),
            "tier_counts": payload.get("tier_counts") or {},
        }
    return {
        "status": "CONFIGURED_NO_WATCHLIST",
        "wallet_watchlist_count": 0,
        "candidate_wallet_count": 0,
        "verified_smart_wallet_count": 0,
        "tier_counts": {"T0": 0, "T1": 0, "T2": 0},
    }


def _load_seed_snapshot(
    path: Path | str,
    *,
    observed_at: datetime | None = None,
) -> dict[str, Any]:
    now = _as_utc(observed_at)
    raw, resolved_path = _read_exact_seed_bytes(Path(path))
    _verify_tracked_file_identity(
        resolved_path=resolved_path,
        raw=raw,
        rejection_reason="WATCHLIST_SEED_AUTHENTICITY_INVALID",
    )
    try:
        payload = json.loads(raw.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WalletWatchlistSeedError("WATCHLIST_SEED_JSON_INVALID") from exc
    if not isinstance(payload, Mapping):
        raise WalletWatchlistSeedError("WATCHLIST_SEED_ROOT_INVALID")
    if payload.get("schema_version") != SEED_SCHEMA_VERSION:
        raise WalletWatchlistSeedError("WATCHLIST_SEED_SCHEMA_INVALID")
    policy = payload.get("policy")
    if not isinstance(policy, Mapping):
        raise WalletWatchlistSeedError("WATCHLIST_SEED_POLICY_INVALID")
    if (
        policy.get("empty_watchlist_status") != "CONFIGURED_NO_WATCHLIST"
        or type(policy.get("t0_max_wallets")) is not int
        or int(policy["t0_max_wallets"]) != TIER_LIMITS["T0"]
        or type(policy.get("t1_max_wallets")) is not int
        or int(policy["t1_max_wallets"]) != TIER_LIMITS["T1"]
        or policy.get("unknown_wallet_is_smart_money") is not False
    ):
        raise WalletWatchlistSeedError("WATCHLIST_SEED_POLICY_INVALID")
    raw_rows = payload.get("wallets")
    if not isinstance(raw_rows, list):
        raise WalletWatchlistSeedError("WATCHLIST_SEED_ROWS_INVALID")
    classifier_authority = _load_classifier_authority()

    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    tier_counts = {"T0": 0, "T1": 0, "T2": 0}
    for raw_row in raw_rows:
        if not isinstance(raw_row, Mapping):
            raise WalletWatchlistSeedError("WATCHLIST_SEED_ROW_INVALID")
        chain = _evm_chain(raw_row.get("chain"))
        address = str(raw_row.get("address") or "").strip().lower()
        identity = (chain, address)
        tier = str(raw_row.get("tier") or "").strip().upper()
        source = str(raw_row.get("source") or "").strip()
        if (
            chain not in MORALIS_EVM_CHAIN_PARAMS
            or _EVM_ADDRESS.fullmatch(address) is None
            or identity in seen
        ):
            raise WalletWatchlistSeedError("WATCHLIST_SEED_IDENTITY_INVALID")
        if tier not in tier_counts:
            raise WalletWatchlistSeedError("WATCHLIST_SEED_TIER_INVALID")
        if not source or len(source.encode("utf-8")) > 4096:
            raise WalletWatchlistSeedError("WATCHLIST_SEED_SOURCE_INVALID")
        if (
            raw_row.get("classification") != "CANDIDATE_SMART_WALLET"
            or raw_row.get("verified_smart_wallet") is not False
        ):
            raise WalletWatchlistSeedError("WATCHLIST_SEED_CANDIDATE_SEMANTICS_INVALID")
        if raw_row.get("added_by") != "v2_moralis_wallet_watchlist_bootstrap":
            raise WalletWatchlistSeedError("WATCHLIST_SEED_PROVENANCE_INVALID")
        added_at = _parse_utc(raw_row.get("added_utc"))
        if added_at is None or added_at > now:
            raise WalletWatchlistSeedError("WATCHLIST_SEED_POINT_IN_TIME_INVALID")
        metadata = raw_row.get("metadata")
        if metadata is not None and not isinstance(metadata, Mapping):
            raise WalletWatchlistSeedError("WATCHLIST_SEED_METADATA_INVALID")
        if (
            isinstance(metadata, Mapping)
            and "is_contract" in metadata
            and type(metadata["is_contract"]) is not bool
        ):
            raise WalletWatchlistSeedError("WATCHLIST_SEED_METADATA_INVALID")
        classification = _classify_candidate_from_snapshot(
            chain=chain,
            address=address,
            metadata=metadata or {},
            configured=classifier_authority["configured"],
        )
        if (
            classification.get("smart_wallet_eligible") is not True
            or classification.get("counts_as_smart_money") is not False
        ):
            raise WalletWatchlistSeedError("WATCHLIST_SEED_CLASSIFICATION_REJECTED")
        seen.add(identity)
        tier_counts[tier] += 1
        rows.append(
            {
                "chain": chain,
                "address": address,
                "tier": tier,
                "source": source,
                "label": raw_row.get("label"),
                "candidate_added_at": _iso_utc(added_at),
                "bootstrap_status": "SEEDED_NOT_VERIFIED",
                "candidate_wallet": True,
                "verified_smart_wallet": False,
                "counts_as_smart_money": False,
                "point_in_time_safe": True,
                "classification": classification,
                "raw_key_exposed": False,
            }
        )
    if tier_counts["T0"] > TIER_LIMITS["T0"] or tier_counts["T1"] > TIER_LIMITS["T1"]:
        raise WalletWatchlistSeedError("WATCHLIST_SEED_TIER_LIMIT_EXCEEDED")

    source_file_sha256 = hashlib.sha256(raw).hexdigest()
    canonical_rows_sha256 = _canonical_rows_sha256(rows)
    source_path_sha256 = hashlib.sha256(str(resolved_path).encode("utf-8")).hexdigest()
    return {
        "rows": rows,
        "source_file_sha256": source_file_sha256,
        "canonical_rows_sha256": canonical_rows_sha256,
        "source_path_sha256": source_path_sha256,
        "classifier_authority_sha256": classifier_authority["authority_sha256"],
    }


def _load_classifier_authority() -> dict[str, Any]:
    documents = (
        (
            "excluded",
            Path(DEFAULT_EXCLUDED_PATH),
            "moralis_excluded_addresses_v1",
        ),
        (
            "exchange",
            Path(DEFAULT_EXCHANGE_PATH),
            "moralis_exchange_wallets_v1",
        ),
    )
    configured: dict[tuple[str, str], dict[str, str | None]] = {}
    bound_parts: list[bytes] = []
    for document_kind, path, schema_version in documents:
        try:
            raw, resolved_path = _read_exact_seed_bytes(path)
            _verify_tracked_file_identity(
                resolved_path=resolved_path,
                raw=raw,
                rejection_reason="WATCHLIST_CLASSIFIER_AUTHORITY_AUTHENTICITY_INVALID",
            )
            payload = json.loads(raw.decode("utf-8", errors="strict"))
        except WalletWatchlistSeedError as exc:
            if str(exc) == "WATCHLIST_CLASSIFIER_AUTHORITY_AUTHENTICITY_INVALID":
                raise
            raise WalletWatchlistSeedError(
                "WATCHLIST_CLASSIFIER_AUTHORITY_UNAVAILABLE"
            ) from exc
        except Exception as exc:
            raise WalletWatchlistSeedError(
                "WATCHLIST_CLASSIFIER_AUTHORITY_UNAVAILABLE"
            ) from exc
        if (
            not isinstance(payload, Mapping)
            or payload.get("schema_version") != schema_version
            or not isinstance(payload.get("addresses"), list)
        ):
            raise WalletWatchlistSeedError(
                "WATCHLIST_CLASSIFIER_AUTHORITY_SCHEMA_INVALID"
            )
        if document_kind == "exchange":
            policy = payload.get("policy")
            if (
                not isinstance(policy, Mapping)
                or policy.get("exchange_wallets_are_smart_money") is not False
                or policy.get("require_source_for_exchange_wallet") is not True
            ):
                raise WalletWatchlistSeedError(
                    "WATCHLIST_CLASSIFIER_AUTHORITY_POLICY_INVALID"
                )
        for raw_row in payload["addresses"]:
            if not isinstance(raw_row, Mapping):
                raise WalletWatchlistSeedError(
                    "WATCHLIST_CLASSIFIER_AUTHORITY_ROW_INVALID"
                )
            raw_chain = str(raw_row.get("chain") or "").strip().lower()
            chain = "*" if raw_chain == "*" else _evm_chain(raw_chain)
            address = str(raw_row.get("address") or "").strip().lower()
            category = str(raw_row.get("category") or "").strip()
            source = str(raw_row.get("source") or "").strip()
            identity = (chain, address)
            if (
                (chain != "*" and chain not in MORALIS_EVM_CHAIN_PARAMS)
                or _EVM_ADDRESS.fullmatch(address) is None
                or category not in SMART_BLOCKING_CATEGORIES
                or not source
                or identity in configured
            ):
                raise WalletWatchlistSeedError(
                    "WATCHLIST_CLASSIFIER_AUTHORITY_ROW_INVALID"
                )
            configured[identity] = {
                "category": category,
                "label": (
                    None
                    if raw_row.get("label") is None
                    else str(raw_row.get("label"))
                ),
                "source": source,
            }
        bound_parts.extend(
            (
                document_kind.encode("ascii"),
                b"\0",
                str(resolved_path).encode("utf-8"),
                b"\0",
                raw,
                b"\0",
            )
        )
    return {
        "configured": configured,
        "authority_sha256": hashlib.sha256(b"".join(bound_parts)).hexdigest(),
    }


def _classify_candidate_from_snapshot(
    *,
    chain: str,
    address: str,
    metadata: Mapping[str, Any],
    configured: Mapping[tuple[str, str], Mapping[str, str | None]],
) -> dict[str, Any]:
    configured_row = configured.get((chain, address)) or configured.get(("*", address))
    if configured_row is not None:
        category = str(configured_row["category"])
        smart_wallet_eligible = False
        label = configured_row.get("label")
        source = configured_row.get("source")
    elif metadata.get("is_contract") is True:
        category = "unknown_contract"
        smart_wallet_eligible = False
        label = metadata.get("label")
        source = "metadata_is_contract"
    else:
        category = "unknown"
        smart_wallet_eligible = True
        label = metadata.get("label")
        source = "not_in_exclusion_lists"
    return {
        "schema_version": "moralis_address_classification_v1",
        "chain": chain,
        "address": address,
        "category": category,
        "label": None if label is None else str(label),
        "source": None if source is None else str(source),
        "smart_wallet_eligible": bool(
            smart_wallet_eligible and category not in SMART_BLOCKING_CATEGORIES
        ),
        "counts_as_smart_money": False,
        "raw_key_exposed": False,
        "core_system_blocked": False,
    }


def _read_exact_seed_bytes(path: Path) -> tuple[bytes, Path]:
    requested = path.expanduser()
    try:
        absolute = Path(os.path.abspath(requested))
        resolved = requested.resolve(strict=True)
    except OSError as exc:
        raise WalletWatchlistSeedError("WATCHLIST_SEED_PATH_UNAVAILABLE") from exc
    if resolved != absolute:
        raise WalletWatchlistSeedError("WATCHLIST_SEED_PATH_NOT_CANONICAL")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(resolved, flags)
    except OSError as exc:
        raise WalletWatchlistSeedError("WATCHLIST_SEED_OPEN_FAILED") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise WalletWatchlistSeedError("WATCHLIST_SEED_NOT_REGULAR_FILE")
        chunks: list[bytes] = []
        byte_count = 0
        while True:
            chunk = os.read(descriptor, min(65_536, _MAX_SEED_BYTES + 1 - byte_count))
            if not chunk:
                break
            chunks.append(chunk)
            byte_count += len(chunk)
            if byte_count > _MAX_SEED_BYTES:
                raise WalletWatchlistSeedError("WATCHLIST_SEED_TOO_LARGE")
        after = os.fstat(descriptor)
        if (metadata.st_dev, metadata.st_ino, metadata.st_size, metadata.st_mtime_ns) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            raise WalletWatchlistSeedError("WATCHLIST_SEED_CHANGED_DURING_READ")
    finally:
        os.close(descriptor)
    return b"".join(chunks), resolved


def _verify_tracked_file_identity(
    *,
    resolved_path: Path,
    raw: bytes,
    rejection_reason: str,
) -> None:
    expected_sha256 = _TRACKED_FILE_SHA256.get(resolved_path)
    if expected_sha256 is None:
        return
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise WalletWatchlistSeedError(rejection_reason)


def _publish_snapshot(
    redis_client: Any,
    *,
    snapshot: Mapping[str, Any],
    ttl_seconds: int,
    refresh_action: str,
) -> dict[str, Any]:
    ttl = max(1, int(ttl_seconds))
    # This is the publication-generation clock, not the seed validation cutoff.
    # The Redis commit occurs after this value and never inherits a historical
    # replay/validation timestamp supplied to ``load_wallet_watchlist_seed``.
    now = datetime.now(UTC)
    rows = list(snapshot["rows"])
    status = wallet_watchlist_status(
        rows,
        source_file_sha256=str(snapshot["source_file_sha256"]),
        canonical_rows_sha256=str(snapshot["canonical_rows_sha256"]),
        source_path_sha256=str(snapshot["source_path_sha256"]),
        classifier_authority_sha256=str(snapshot["classifier_authority_sha256"]),
        generated_at=now,
    )
    payload = {
        "schema_version": "moralis_wallet_watchlist_v1",
        "generated_utc": _iso_utc(now),
        "rows": rows,
        **status,
    }
    payload["schema_version"] = "moralis_wallet_watchlist_v1"
    encoded_payload = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    encoded_status = json.dumps(status, sort_keys=True, separators=(",", ":"), default=str)
    pipeline_factory = getattr(redis_client, "pipeline", None)
    if not callable(pipeline_factory):
        raise RuntimeError("WATCHLIST_REDIS_TRANSACTION_REQUIRED")
    pipeline = pipeline_factory(transaction=True)
    pipeline.set(WALLET_WATCHLIST_KEY, encoded_payload, ex=ttl)
    pipeline.set(WALLET_WATCHLIST_STATUS_KEY, encoded_status, ex=ttl)
    results = pipeline.execute()
    if not isinstance(results, list) or len(results) != 2 or not all(results):
        raise RuntimeError("WATCHLIST_REDIS_TRANSACTION_FAILED")
    return {
        **status,
        "refresh_action": refresh_action,
        "refresh_succeeded": True,
        "refresh_before_expiry_seconds": max(1, ttl // 3),
        "remaining_ttl_seconds": ttl,
        "moralis_request_count": 0,
        "compute_units_reserved": 0,
        "cadence_claims_mutated": False,
        "trainer_isolation_changed": False,
        "keys_written": [WALLET_WATCHLIST_KEY, WALLET_WATCHLIST_STATUS_KEY],
    }


def _read_validated_wallet_watchlist(
    redis_client: Any,
    *,
    snapshot: Mapping[str, Any],
    observed_at: datetime,
) -> list[dict[str, Any]] | None:
    payload = _read_json(redis_client, WALLET_WATCHLIST_KEY)
    if (
        not isinstance(payload, Mapping)
        or payload.get("schema_version") != "moralis_wallet_watchlist_v1"
        or payload.get("status") not in {"WATCHLIST_READY", "CONFIGURED_NO_WATCHLIST"}
        or payload.get("source_file_sha256") != snapshot["source_file_sha256"]
        or payload.get("canonical_rows_sha256") != snapshot["canonical_rows_sha256"]
        or payload.get("source_path_sha256") != snapshot["source_path_sha256"]
        or payload.get("classifier_authority_sha256")
        != snapshot["classifier_authority_sha256"]
        or payload.get("watchlist_semantics") != "CANDIDATE_OBSERVATION_TARGETS_ONLY"
        or payload.get("verified_smart_wallet_count") != 0
        or payload.get("counts_as_smart_money_count") != 0
    ):
        return None
    generated_at = _parse_utc(payload.get("generated_utc"))
    if generated_at is None or generated_at > _as_utc(observed_at):
        return None
    expected_rows = list(snapshot["rows"])
    rows = payload.get("rows")
    if (
        not isinstance(rows, list)
        or type(payload.get("wallet_watchlist_count")) is not int
        or payload.get("wallet_watchlist_count") != len(expected_rows)
        or type(payload.get("candidate_wallet_count")) is not int
        or payload.get("candidate_wallet_count") != len(expected_rows)
        or len(rows) != len(expected_rows)
        or rows != expected_rows
        or _canonical_rows_sha256(rows) != snapshot["canonical_rows_sha256"]
    ):
        return None
    return [dict(row) for row in rows]


def _status_matches_snapshot(
    payload: Mapping[str, Any] | None,
    *,
    snapshot: Mapping[str, Any],
) -> bool:
    rows = list(snapshot["rows"])
    expected_status = "WATCHLIST_READY" if rows else "CONFIGURED_NO_WATCHLIST"
    return bool(
        isinstance(payload, Mapping)
        and payload.get("schema_version") == "moralis_wallet_watchlist_status_v1"
        and payload.get("status") == expected_status
        and payload.get("source_file_sha256") == snapshot["source_file_sha256"]
        and payload.get("canonical_rows_sha256") == snapshot["canonical_rows_sha256"]
        and payload.get("source_path_sha256") == snapshot["source_path_sha256"]
        and payload.get("classifier_authority_sha256")
        == snapshot["classifier_authority_sha256"]
        and payload.get("wallet_watchlist_count") == len(rows)
        and payload.get("candidate_wallet_count") == len(rows)
        and payload.get("verified_smart_wallet_count") == 0
        and payload.get("counts_as_smart_money_count") == 0
        and payload.get("raw_address_exposed_in_status") is False
        and "rows" not in payload
    )


def _refresh_status(
    *,
    snapshot: Mapping[str, Any],
    refresh_action: str,
    refresh_succeeded: bool,
    generated_at: datetime,
    remaining_ttl_seconds: int | None = None,
    refresh_before_expiry_seconds: int | None = None,
) -> dict[str, Any]:
    status = wallet_watchlist_status(
        snapshot["rows"],
        source_file_sha256=str(snapshot["source_file_sha256"]),
        canonical_rows_sha256=str(snapshot["canonical_rows_sha256"]),
        source_path_sha256=str(snapshot["source_path_sha256"]),
        classifier_authority_sha256=str(snapshot["classifier_authority_sha256"]),
        generated_at=generated_at,
    )
    return {
        **status,
        "refresh_action": refresh_action,
        "refresh_succeeded": refresh_succeeded,
        "remaining_ttl_seconds": remaining_ttl_seconds,
        "refresh_before_expiry_seconds": refresh_before_expiry_seconds,
        "moralis_request_count": 0,
        "compute_units_reserved": 0,
        "cadence_claims_mutated": False,
        "trainer_isolation_changed": False,
    }


def _publish_refresh_failure_status(
    redis_client: Any | None,
    *,
    reason: str,
    ttl_seconds: int,
    generated_at: datetime,
) -> dict[str, Any]:
    status = {
        "schema_version": "moralis_wallet_watchlist_status_v1",
        "status": "WATCHLIST_SEED_REJECTED",
        "dashboard_color": "GRAY",
        "generated_utc": _iso_utc(generated_at),
        "wallet_watchlist_count": 0,
        "candidate_wallet_count": 0,
        "candidate_smart_wallet_count": 0,
        "verified_smart_wallet_count": 0,
        "counts_as_smart_money_count": 0,
        "watchlist_semantics": "CANDIDATE_OBSERVATION_TARGETS_ONLY",
        "refresh_action": "SEED_REJECTED",
        "refresh_succeeded": False,
        "rejection_reason": reason,
        "moralis_request_count": 0,
        "compute_units_reserved": 0,
        "cadence_claims_mutated": False,
        "trainer_isolation_changed": False,
        "raw_address_exposed_in_status": False,
        "raw_key_exposed": False,
        "trainer_authority": False,
        "prediction_authority": False,
        "risk_authority": False,
        "orchestrator_authority": False,
        "allocator_authority": False,
        "paper_authority": False,
        "live_authority": False,
        "core_system_blocked": False,
    }
    if redis_client is not None:
        try:
            redis_client.set(
                WALLET_WATCHLIST_STATUS_KEY,
                json.dumps(status, sort_keys=True, separators=(",", ":")),
                ex=max(1, int(ttl_seconds)),
            )
        except Exception:  # noqa: S110 - returned status remains fail-closed
            pass
    return status


def _canonical_rows_sha256(rows: Sequence[Mapping[str, Any]]) -> str:
    encoded = json.dumps(
        list(rows),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _remaining_ttl(redis_client: Any, key: str) -> int | None:
    ttl_reader = getattr(redis_client, "ttl", None)
    if not callable(ttl_reader):
        return None
    try:
        ttl = ttl_reader(key)
        if isinstance(ttl, bool):
            return None
        parsed = int(ttl)
    except Exception:
        return None
    return parsed if parsed > 0 else None


def _read_json(redis_client: Any, key: str) -> dict[str, Any] | None:
    try:
        raw = redis_client.get(key)
    except Exception:
        return None
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    try:
        payload = json.loads(str(raw))
    except (TypeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _as_utc(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if value.tzinfo is None or value.utcoffset() is None:
        raise WalletWatchlistSeedError("WATCHLIST_OBSERVED_AT_TIMEZONE_REQUIRED")
    return value.astimezone(UTC)


def _parse_utc(value: object) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _iso_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _evm_chain(value: object) -> str:
    raw = str(value or "").strip().lower()
    return MORALIS_EVM_CHAIN_ALIASES.get(raw, raw)
