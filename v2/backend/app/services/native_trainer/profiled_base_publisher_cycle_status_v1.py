"""Strict local reader for one profiled base-publisher cycle status.

The base publisher atomically writes canonical JSON with a self SHA-256.  This
module verifies that exact local-file contract and exposes only the publisher
cycle identity needed by the observation coordinator.  A self-hash is local
integrity, not independent authentication or trainer authority.
"""

from __future__ import annotations

import json
import math
import os
import re
import stat
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, NoReturn, cast

from v2.backend.app.services.native_trainer.durable_feature_snapshot_ledger import (
    stable_sha256,
)
from v2.backend.app.services.native_trainer.source_provenance_ledger_v4 import (
    MAX_LEDGER_BYTES,
    MAX_LEDGER_ENTRIES,
)

PROFILED_BASE_PUBLISHER_CYCLE_STATUS_V1_SCHEMA_VERSION: Final = (
    "profiled_base_publisher_cycle_status_v1"
)
PROFILED_BASE_FEATURE_PUBLISHER_STATUS_V1_SCHEMA_VERSION: Final = (
    "profiled_base_feature_publisher_status_v1"
)
PROFILED_BASE_FEATURE_PUBLISHER_V1_SCHEMA_VERSION: Final = "profiled_base_feature_publisher_v1"
SOURCE_SHARD_PREFLIGHT_V1_SCHEMA_VERSION: Final = (
    "profiled_base_source_shard_preflight_v1"
)

# This equals the writer's existing state/status serialization ceiling. It is
# a parser/resource bound, not a market, symbol, sample, or training threshold.
MAX_PROFILED_BASE_PUBLISHER_STATUS_BYTES: Final = 16 * 1024 * 1024

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,48}$", re.ASCII)
_RESULT_TOKEN = object()

_STATUS_FIELDS: Final = {
    "authority",
    "authority_semantics",
    "classification",
    "commission_broker_reader_available",
    "commission_cost_mode",
    "commission_credentials_available",
    "coverage",
    "cycle_completed_at",
    "cycle_disk_consumption_high_water_bytes",
    "cycle_elapsed_seconds",
    "cycle_evidence_accounted_bytes",
    "cycle_materialized_artifact_bytes",
    "cycle_materialized_publication_count",
    "cycle_owned_durable_growth_bytes",
    "cycle_period_seconds",
    "cycle_started_at",
    "discovered_symbol_count",
    "discovered_symbols",
    "discovery_completed_at",
    "disk_resource_safety",
    "dynamic_selection_universe",
    "eligible_symbol_count",
    "eligible_symbols",
    "evidence_accounting_method",
    "exact_replay_symbol_count",
    "exact_replay_symbols",
    "exchange_credentials_loaded_by_publisher",
    "failed_symbol_count",
    "failed_symbols",
    "failures",
    "legacy_feature_redis_write_performed",
    "market_performance_thresholds_applied",
    "masked_cost_observation_replay_symbol_count",
    "masked_cost_observation_replay_symbols",
    "masked_cost_observation_symbol_count",
    "masked_cost_observation_symbols",
    "masked_cost_observations",
    "publications",
    "published_symbol_count",
    "published_symbols",
    "publisher_schema_version",
    "rejected_discovery_key_sha256s",
    "resource_decision",
    "resource_deferred_symbol_count",
    "resource_deferred_symbols",
    "resource_sustainability_horizon_seconds",
    "rotation_last_attempted_at",
    "schema_version",
    "selected_symbol_count",
    "selected_symbols",
    "selection_at",
    "singleton_writer_lock",
    "skips",
    "source_provenance_shard_preflight_count",
    "source_provenance_shard_preflights",
    "source_provenance_shard_rollover_count",
    "state_sha256",
    "status_sha256",
    "unchanged_symbol_count",
    "unchanged_symbols",
}

_SOURCE_SHARD_PREFLIGHT_FIELDS: Final = {
    "schema_version",
    "status_preflight_index",
    "symbol",
    "publication_attempt",
    "verification_started_at",
    "verification_completed_at",
    "active_shard_present",
    "active_shard_index",
    "active_shard_relative_path",
    "active_shard_integrity_verified_before_capture",
    "active_ledger_bytes",
    "active_ledger_entries",
    "active_head_sequence",
    "active_head_entry_sha256",
    "measured_full_verification_seconds",
    "new_append_full_verification_passes_before_transform_clock",
    "remaining_full_verification_passes_before_transform_clock",
    "projected_remaining_full_verification_seconds",
    "planned_decision_time",
    "planned_decision_budget_seconds",
    "remaining_verification_passes_fit_planned_decision",
    "adaptive_estimated_symbol_elapsed_seconds",
    "projected_verification_and_symbol_work_seconds",
    "verification_and_symbol_work_fit_planned_decision",
    "default_midpoint_decision_planner_configured",
    "rollover_projection_uses_exact_replay_safe_pass_count",
    "rollover_performed_before_capture",
    "rollover_reason",
    "preflight_selected_shard_index",
    "preflight_selected_shard_relative_path",
    "publication_shard_index",
    "publication_shard_relative_path",
    "publication_shard_selection_reconciled",
    "hard_safety_cap_rollover_after_capture",
    "ledger_byte_hard_safety_cap",
    "ledger_entry_hard_safety_cap",
    "market_or_performance_threshold_applied",
}

_PUBLISHER_AUTHORITY_FIELDS: Final = {
    "trainer_admission_authorized",
    "prediction_authorized",
    "paper_trading_authorized",
    "live_execution_authorized",
    "runtime_wired",
}

_PUBLISHER_AUTHORITY_SEMANTICS_FIELDS: Final = {
    "publisher_runtime_authority_granted",
    "published_child_trainer_admission_authorized",
    "masked_parent_trainer_admission_authorized",
    "prediction_paper_live_authority_granted",
    "automatic_trainer_transition_authorized",
}

_SYMBOL_COUNT_LIST_PAIRS: Final = (
    ("discovered_symbol_count", "discovered_symbols"),
    ("eligible_symbol_count", "eligible_symbols"),
    ("selected_symbol_count", "selected_symbols"),
    ("resource_deferred_symbol_count", "resource_deferred_symbols"),
    ("published_symbol_count", "published_symbols"),
    ("exact_replay_symbol_count", "exact_replay_symbols"),
    ("masked_cost_observation_symbol_count", "masked_cost_observation_symbols"),
    (
        "masked_cost_observation_replay_symbol_count",
        "masked_cost_observation_replay_symbols",
    ),
    ("unchanged_symbol_count", "unchanged_symbols"),
    ("failed_symbol_count", "failed_symbols"),
)


class ProfiledBasePublisherCycleStatusV1Error(RuntimeError):
    """The publisher status could not be used as a local cycle trigger."""

    def __init__(self, *reasons: str) -> None:
        self.reasons = tuple(dict.fromkeys(str(reason) for reason in reasons))
        super().__init__(";".join(self.reasons))


def _fail(*reasons: str) -> NoReturn:
    raise ProfiledBasePublisherCycleStatusV1Error(*reasons) from None


def _valid_sha256(value: object) -> bool:
    return type(value) is str and _SHA256_RE.fullmatch(value) is not None


def _clock(value: object, *, reason: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        _fail(reason)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (OverflowError, ValueError):
        _fail(reason)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _fail(reason)
    canonical = parsed.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    if canonical != value:
        _fail(reason)
    return value


def _absolute_path(value: Path) -> Path:
    if not isinstance(value, Path) or not value.is_absolute():
        _fail("PROFILED_BASE_STATUS_PATH_INVALID")
    normalized = Path(os.path.normpath(str(value)))
    if normalized != value or "\x00" in str(value):
        _fail("PROFILED_BASE_STATUS_PATH_INVALID")
    return value


def _require_regular_parent_chain(path: Path) -> None:
    current = Path(path.anchor)
    for component in path.parts[1:-1]:
        current /= component
        try:
            observed = os.lstat(current)
        except OSError as exc:
            raise ProfiledBasePublisherCycleStatusV1Error(
                "PROFILED_BASE_STATUS_PARENT_CHAIN_INVALID"
            ) from exc
        if not stat.S_ISDIR(observed.st_mode) or stat.S_ISLNK(observed.st_mode):
            _fail("PROFILED_BASE_STATUS_PARENT_CHAIN_INVALID")


def _canonical_json_bytes(value: object) -> bytes:
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
    except (OverflowError, RecursionError, TypeError, UnicodeEncodeError, ValueError) as exc:
        raise ProfiledBasePublisherCycleStatusV1Error("PROFILED_BASE_STATUS_JSON_INVALID") from exc
    if not encoded or len(encoded) > MAX_PROFILED_BASE_PUBLISHER_STATUS_BYTES:
        _fail("PROFILED_BASE_STATUS_JSON_INVALID")
    return encoded


def _strict_json(raw: bytes) -> dict[str, Any]:
    if type(raw) is not bytes or not raw or len(raw) > MAX_PROFILED_BASE_PUBLISHER_STATUS_BYTES:
        _fail("PROFILED_BASE_STATUS_JSON_INVALID")

    def reject_constant(value: str) -> NoReturn:
        _fail(f"PROFILED_BASE_STATUS_NONFINITE:{value}")

    def reject_duplicate(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for name, value in pairs:
            if type(name) is not str or name in result:
                _fail("PROFILED_BASE_STATUS_DUPLICATE_OR_INVALID_KEY")
            result[name] = value
        return result

    try:
        value = json.loads(
            raw.decode("ascii"),
            object_pairs_hook=reject_duplicate,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise ProfiledBasePublisherCycleStatusV1Error("PROFILED_BASE_STATUS_JSON_INVALID") from exc
    if type(value) is not dict or _canonical_json_bytes(value) != raw:
        _fail("PROFILED_BASE_STATUS_NOT_CANONICAL")
    return cast(dict[str, Any], value)


def _read_exact_regular_file(path: Path) -> tuple[bytes, os.stat_result]:
    _require_regular_parent_chain(path)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ProfiledBasePublisherCycleStatusV1Error("PROFILED_BASE_STATUS_OPEN_FAILED") from exc
    try:
        opened = os.fstat(descriptor)
        observed = os.lstat(path)
        if (
            not stat.S_ISREG(opened.st_mode)
            or not stat.S_ISREG(observed.st_mode)
            or stat.S_ISLNK(observed.st_mode)
            or opened.st_uid != os.geteuid()
            or observed.st_uid != os.geteuid()
            or opened.st_nlink != 1
            or observed.st_nlink != 1
            or (opened.st_dev, opened.st_ino) != (observed.st_dev, observed.st_ino)
            or stat.S_IMODE(opened.st_mode) & 0o022
            or not 1 < opened.st_size <= MAX_PROFILED_BASE_PUBLISHER_STATUS_BYTES + 1
        ):
            _fail("PROFILED_BASE_STATUS_FILE_INVALID")
        chunks: list[bytes] = []
        remaining = opened.st_size
        while remaining:
            chunk = os.read(descriptor, min(remaining, 1024 * 1024))
            if not chunk:
                _fail("PROFILED_BASE_STATUS_SHORT_READ")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            _fail("PROFILED_BASE_STATUS_GREW_DURING_READ")
        readback = os.fstat(descriptor)
        if (
            (readback.st_dev, readback.st_ino, readback.st_size)
            != (opened.st_dev, opened.st_ino, opened.st_size)
            or readback.st_mtime_ns != opened.st_mtime_ns
            or readback.st_ctime_ns != opened.st_ctime_ns
        ):
            _fail("PROFILED_BASE_STATUS_CHANGED_DURING_READ")
        _require_regular_parent_chain(path)
        return b"".join(chunks), opened
    except ProfiledBasePublisherCycleStatusV1Error:
        raise
    except OSError as exc:
        raise ProfiledBasePublisherCycleStatusV1Error("PROFILED_BASE_STATUS_READ_FAILED") from exc
    finally:
        os.close(descriptor)


def _validate_symbol_inventory(status: dict[str, Any]) -> None:
    for count_name, list_name in _SYMBOL_COUNT_LIST_PAIRS:
        count = status.get(count_name)
        values = status.get(list_name)
        if (
            type(count) is not int
            or count < 0
            or type(values) is not list
            or len(values) != count
            or any(
                type(value) is not str or _SYMBOL_RE.fullmatch(value) is None for value in values
            )
        ):
            _fail("PROFILED_BASE_STATUS_SYMBOL_INVENTORY_INVALID")
        if len(set(values)) != len(values):
            _fail("PROFILED_BASE_STATUS_SYMBOL_INVENTORY_INVALID")

    discovered = set(cast(list[str], status["discovered_symbols"]))
    eligible = set(cast(list[str], status["eligible_symbols"]))
    selected = set(cast(list[str], status["selected_symbols"]))
    resource_deferred = set(cast(list[str], status["resource_deferred_symbols"]))
    published = set(cast(list[str], status["published_symbols"]))
    replayed = set(cast(list[str], status["exact_replay_symbols"]))
    masked = set(cast(list[str], status["masked_cost_observation_symbols"]))
    masked_replayed = set(
        cast(list[str], status["masked_cost_observation_replay_symbols"])
    )
    unchanged = set(cast(list[str], status["unchanged_symbols"]))
    failed = set(cast(list[str], status["failed_symbols"]))
    outcomes = (published, replayed, masked, masked_replayed, unchanged)
    outcome_union = set().union(*outcomes)
    if (
        not eligible <= discovered
        or not selected <= eligible
        or not resource_deferred <= eligible
        or bool(selected & resource_deferred)
        or not failed <= discovered
        or not outcome_union <= selected
        or bool(outcome_union & failed)
        or not (failed & eligible) <= selected
        or any(
            left & right
            for index, left in enumerate(outcomes)
            for right in outcomes[index + 1 :]
        )
        or selected != outcome_union | (selected & failed)
    ):
        _fail("PROFILED_BASE_STATUS_SYMBOL_INVENTORY_RELATION_INVALID")


@dataclass(frozen=True, slots=True)
class VerifiedProfiledBasePublisherCycleStatusV1:
    status_path: Path
    status_file_device: int
    status_file_inode: int
    status_file_byte_count: int
    status_sha256: str
    state_sha256: str
    classification: str
    cycle_started_at: str
    discovery_completed_at: str
    selection_at: str
    cycle_completed_at: str
    discovered_symbol_count: int
    eligible_symbol_count: int
    selected_symbol_count: int
    published_symbol_count: int
    exact_replay_symbol_count: int
    masked_cost_observation_symbol_count: int
    failed_symbol_count: int
    local_status_integrity_verified: bool
    independent_status_authentication_verified: bool
    external_monotonic_manifest_head_verified: bool
    full_consumption_external_ack_verified: bool
    optimizer_admission_authorized: bool
    checkpoint_write_authorized: bool
    model_write_authorized: bool
    prediction_authorized: bool
    paper_trading_authorized: bool
    live_execution_authorized: bool
    order_submission_authorized: bool
    execution_authorized: bool
    runtime_wired: bool
    _construction_token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if (
            self._construction_token is not _RESULT_TOKEN
            or not self.status_path.is_absolute()
            or self.status_file_byte_count <= 1
            or not _valid_sha256(self.status_sha256)
            or not _valid_sha256(self.state_sha256)
            or type(self.classification) is not str
            or not self.classification
            or any(
                type(value) is not int or value < 0
                for value in (
                    self.discovered_symbol_count,
                    self.eligible_symbol_count,
                    self.selected_symbol_count,
                    self.published_symbol_count,
                    self.exact_replay_symbol_count,
                    self.masked_cost_observation_symbol_count,
                    self.failed_symbol_count,
                )
            )
            or self.local_status_integrity_verified is not True
            or any(
                type(value) is not bool or value
                for value in (
                    self.independent_status_authentication_verified,
                    self.external_monotonic_manifest_head_verified,
                    self.full_consumption_external_ack_verified,
                    self.optimizer_admission_authorized,
                    self.checkpoint_write_authorized,
                    self.model_write_authorized,
                    self.prediction_authorized,
                    self.paper_trading_authorized,
                    self.live_execution_authorized,
                    self.order_submission_authorized,
                    self.execution_authorized,
                    self.runtime_wired,
                )
            )
        ):
            _fail("PROFILED_BASE_STATUS_RESULT_INVALID")


def _validate_source_shard_preflights(status: dict[str, Any]) -> None:
    preflight_count = status.get("source_provenance_shard_preflight_count")
    rollover_count = status.get("source_provenance_shard_rollover_count")
    preflights = status.get("source_provenance_shard_preflights")
    if (
        type(preflight_count) is not int
        or preflight_count < 0
        or type(rollover_count) is not int
        or rollover_count < 0
        or type(preflights) is not list
        or preflight_count != len(preflights)
        or rollover_count > preflight_count
    ):
        _fail("PROFILED_BASE_STATUS_SOURCE_SHARD_PREFLIGHT_INVENTORY_INVALID")
    selected_symbols = status.get("selected_symbols")
    if type(selected_symbols) is not list:
        _fail("PROFILED_BASE_STATUS_SOURCE_SHARD_PREFLIGHT_INVENTORY_INVALID")
    observed_identities: set[tuple[str, int]] = set()
    observed_rollovers = 0
    for preflight in preflights:
        if type(preflight) is not dict or set(preflight) != _SOURCE_SHARD_PREFLIGHT_FIELDS:
            _fail("PROFILED_BASE_STATUS_SOURCE_SHARD_PREFLIGHT_FIELDS_INVALID")
        symbol = preflight["symbol"]
        attempt = preflight["publication_attempt"]
        active_present = preflight["active_shard_present"]
        active_index = preflight["active_shard_index"]
        active_bytes = preflight["active_ledger_bytes"]
        active_entries = preflight["active_ledger_entries"]
        head_sequence = preflight["active_head_sequence"]
        head_sha256 = preflight["active_head_entry_sha256"]
        measured_seconds = preflight["measured_full_verification_seconds"]
        new_append_passes = preflight[
            "new_append_full_verification_passes_before_transform_clock"
        ]
        remaining_passes = preflight[
            "remaining_full_verification_passes_before_transform_clock"
        ]
        projected_seconds = preflight[
            "projected_remaining_full_verification_seconds"
        ]
        planned_budget = preflight["planned_decision_budget_seconds"]
        fits_planned_decision = preflight[
            "remaining_verification_passes_fit_planned_decision"
        ]
        adaptive_symbol_seconds = preflight[
            "adaptive_estimated_symbol_elapsed_seconds"
        ]
        projected_combined_seconds = preflight[
            "projected_verification_and_symbol_work_seconds"
        ]
        combined_work_fits = preflight[
            "verification_and_symbol_work_fit_planned_decision"
        ]
        rollover = preflight["rollover_performed_before_capture"]
        selected_index = preflight["preflight_selected_shard_index"]
        publication_index = preflight["publication_shard_index"]
        publication_reconciled = preflight[
            "publication_shard_selection_reconciled"
        ]
        hard_cap_rollover = preflight["hard_safety_cap_rollover_after_capture"]
        if (
            preflight["schema_version"] != SOURCE_SHARD_PREFLIGHT_V1_SCHEMA_VERSION
            or type(symbol) is not str
            or _SYMBOL_RE.fullmatch(symbol) is None
            or symbol not in selected_symbols
            or type(attempt) is not int
            or attempt <= 0
            or attempt > 8
            or (symbol, attempt) in observed_identities
            or preflight["status_preflight_index"] != len(observed_identities)
            or type(active_present) is not bool
            or type(active_bytes) is not int
            or active_bytes < 0
            or type(active_entries) is not int
            or active_entries < 0
            or type(measured_seconds) not in {int, float}
            or not math.isfinite(measured_seconds)
            or measured_seconds < 0
            or new_append_passes != 5
            or remaining_passes != 7
            or type(projected_seconds) not in {int, float}
            or not math.isfinite(projected_seconds)
            or projected_seconds != measured_seconds * remaining_passes
            or type(planned_budget) not in {int, float}
            or not math.isfinite(planned_budget)
            or planned_budget <= 0
            or type(fits_planned_decision) is not bool
            or fits_planned_decision is not (projected_seconds < planned_budget)
            or type(adaptive_symbol_seconds) not in {int, float}
            or not math.isfinite(adaptive_symbol_seconds)
            or adaptive_symbol_seconds <= 0
            or type(projected_combined_seconds) not in {int, float}
            or not math.isfinite(projected_combined_seconds)
            or projected_combined_seconds
            != projected_seconds + adaptive_symbol_seconds
            or type(combined_work_fits) is not bool
            or combined_work_fits
            is not (projected_combined_seconds < planned_budget)
            or type(preflight["default_midpoint_decision_planner_configured"])
            is not bool
            or preflight["rollover_projection_uses_exact_replay_safe_pass_count"]
            is not True
            or type(rollover) is not bool
            or type(selected_index) is not int
            or selected_index < 0
            or type(publication_reconciled) is not bool
            or type(hard_cap_rollover) is not bool
            or preflight["ledger_byte_hard_safety_cap"] != MAX_LEDGER_BYTES
            or preflight["ledger_entry_hard_safety_cap"] != MAX_LEDGER_ENTRIES
            or preflight["market_or_performance_threshold_applied"] is not False
            or preflight["active_shard_integrity_verified_before_capture"] is not True
        ):
            _fail("PROFILED_BASE_STATUS_SOURCE_SHARD_PREFLIGHT_CONTRACT_INVALID")
        verification_started = _clock(
            preflight["verification_started_at"],
            reason="PROFILED_BASE_STATUS_SOURCE_SHARD_PREFLIGHT_CLOCK_INVALID",
        )
        verification_completed = _clock(
            preflight["verification_completed_at"],
            reason="PROFILED_BASE_STATUS_SOURCE_SHARD_PREFLIGHT_CLOCK_INVALID",
        )
        planned_decision = _clock(
            preflight["planned_decision_time"],
            reason="PROFILED_BASE_STATUS_SOURCE_SHARD_PREFLIGHT_CLOCK_INVALID",
        )
        completed_datetime = datetime.fromisoformat(
            verification_completed.replace("Z", "+00:00")
        )
        planned_datetime = datetime.fromisoformat(
            planned_decision.replace("Z", "+00:00")
        )
        if (
            not verification_started <= verification_completed < planned_decision
            or (planned_datetime - completed_datetime).total_seconds()
            != planned_budget
        ):
            _fail("PROFILED_BASE_STATUS_SOURCE_SHARD_PREFLIGHT_CLOCK_ORDER_INVALID")
        if active_present:
            if (
                type(active_index) is not int
                or active_index < 0
                or preflight["active_shard_relative_path"]
                != f"source-provenance-shards/shard-{active_index:08d}"
            ):
                _fail("PROFILED_BASE_STATUS_SOURCE_SHARD_PREFLIGHT_ACTIVE_INVALID")
        elif (
            active_index is not None
            or preflight["active_shard_relative_path"] is not None
            or active_bytes != 0
            or active_entries != 0
        ):
            _fail("PROFILED_BASE_STATUS_SOURCE_SHARD_PREFLIGHT_ACTIVE_INVALID")
        if active_entries == 0:
            if head_sequence is not None or head_sha256 is not None:
                _fail("PROFILED_BASE_STATUS_SOURCE_SHARD_PREFLIGHT_HEAD_INVALID")
        elif (
            head_sequence != active_entries
            or not _valid_sha256(head_sha256)
            or active_bytes <= 0
        ):
            _fail("PROFILED_BASE_STATUS_SOURCE_SHARD_PREFLIGHT_HEAD_INVALID")
        if preflight["preflight_selected_shard_relative_path"] != (
            f"source-provenance-shards/shard-{selected_index:08d}"
        ):
            _fail("PROFILED_BASE_STATUS_SOURCE_SHARD_PREFLIGHT_SELECTION_INVALID")
        if not active_present:
            expected_reason = "NO_ACTIVE_SOURCE_SHARD"
            expected_selected = 0
            expected_rollover = False
        elif active_entries == 0:
            expected_reason = "ACTIVE_SOURCE_SHARD_EMPTY"
            expected_selected = cast(int, active_index)
            expected_rollover = False
        elif combined_work_fits:
            expected_reason = (
                "MEASURED_VERIFICATION_AND_ADAPTIVE_SYMBOL_WORK_FIT_"
                "PLANNED_DECISION_WINDOW"
            )
            expected_selected = cast(int, active_index)
            expected_rollover = False
        else:
            expected_reason = (
                "MEASURED_VERIFICATION_AND_ADAPTIVE_SYMBOL_WORK_EXCEED_"
                "PLANNED_DECISION_WINDOW"
            )
            expected_selected = cast(int, active_index) + 1
            expected_rollover = True
        if (
            preflight["rollover_reason"] != expected_reason
            or selected_index != expected_selected
            or rollover is not expected_rollover
        ):
            _fail("PROFILED_BASE_STATUS_SOURCE_SHARD_PREFLIGHT_ROLLOVER_INVALID")
        if publication_reconciled:
            if (
                type(publication_index) is not int
                or publication_index < 0
                or preflight["publication_shard_relative_path"]
                != f"source-provenance-shards/shard-{publication_index:08d}"
                or hard_cap_rollover
                is not (publication_index != selected_index)
                or publication_index not in {selected_index, selected_index + 1}
            ):
                _fail(
                    "PROFILED_BASE_STATUS_SOURCE_SHARD_PREFLIGHT_RECONCILIATION_INVALID"
                )
        elif (
            publication_index is not None
            or preflight["publication_shard_relative_path"] is not None
            or hard_cap_rollover is not False
        ):
            _fail("PROFILED_BASE_STATUS_SOURCE_SHARD_PREFLIGHT_RECONCILIATION_INVALID")
        observed_identities.add((symbol, attempt))
        observed_rollovers += int(rollover)
    if observed_rollovers != rollover_count:
        _fail("PROFILED_BASE_STATUS_SOURCE_SHARD_PREFLIGHT_INVENTORY_INVALID")


def read_verified_profiled_base_publisher_cycle_status_v1(
    *,
    status_path: Path,
) -> VerifiedProfiledBasePublisherCycleStatusV1:
    """Read one exact canonical status file and verify its local self-hash."""

    path = _absolute_path(status_path)
    framed, file_stat = _read_exact_regular_file(path)
    if not framed.endswith(b"\n") or b"\r" in framed:
        _fail("PROFILED_BASE_STATUS_FRAMING_INVALID")
    status = _strict_json(framed[:-1])
    if set(status) != _STATUS_FIELDS:
        _fail("PROFILED_BASE_STATUS_FIELDS_INVALID")
    claimed_hash = status.get("status_sha256")
    unsigned = {name: value for name, value in status.items() if name != "status_sha256"}
    if (
        status.get("schema_version") != PROFILED_BASE_FEATURE_PUBLISHER_STATUS_V1_SCHEMA_VERSION
        or status.get("publisher_schema_version")
        != PROFILED_BASE_FEATURE_PUBLISHER_V1_SCHEMA_VERSION
        or not _valid_sha256(claimed_hash)
        or stable_sha256(unsigned) != claimed_hash
        or not _valid_sha256(status.get("state_sha256"))
    ):
        _fail("PROFILED_BASE_STATUS_IDENTITY_INVALID")
    clocks = tuple(
        _clock(status.get(name), reason="PROFILED_BASE_STATUS_CLOCK_INVALID")
        for name in (
            "cycle_started_at",
            "discovery_completed_at",
            "selection_at",
            "cycle_completed_at",
        )
    )
    parsed_clocks = tuple(datetime.fromisoformat(value.replace("Z", "+00:00")) for value in clocks)
    if parsed_clocks != tuple(sorted(parsed_clocks)):
        _fail("PROFILED_BASE_STATUS_CLOCK_ORDER_INVALID")
    elapsed = status.get("cycle_elapsed_seconds")
    if type(elapsed) not in {int, float} or not math.isfinite(elapsed) or elapsed < 0:
        _fail("PROFILED_BASE_STATUS_ELAPSED_INVALID")
    authority = status.get("authority")
    if (
        type(authority) is not dict
        or set(authority) != _PUBLISHER_AUTHORITY_FIELDS
        or any(type(authority[name]) is not bool or authority[name] for name in authority)
        or status.get("legacy_feature_redis_write_performed") is not False
        or status.get("market_performance_thresholds_applied") is not False
    ):
        _fail("PROFILED_BASE_STATUS_AUTHORITY_INVALID")
    authority_semantics = status.get("authority_semantics")
    published_child_admission_expected = bool(
        status.get("published_symbols") or status.get("exact_replay_symbols")
    )
    if (
        type(authority_semantics) is not dict
        or set(authority_semantics) != _PUBLISHER_AUTHORITY_SEMANTICS_FIELDS
        or any(type(authority_semantics[name]) is not bool for name in authority_semantics)
        or authority_semantics.get("publisher_runtime_authority_granted") is not False
        or authority_semantics.get("masked_parent_trainer_admission_authorized") is not False
        or authority_semantics.get("automatic_trainer_transition_authorized") is not False
        or authority_semantics.get("prediction_paper_live_authority_granted") is not False
        or authority_semantics.get("published_child_trainer_admission_authorized")
        is not published_child_admission_expected
    ):
        _fail("PROFILED_BASE_STATUS_AUTHORITY_SEMANTICS_INVALID")
    dynamic_universe = status.get("dynamic_selection_universe")
    if (
        type(dynamic_universe) is not dict
        or dynamic_universe.get("trainer_evidence_or_authority_conferred") is not False
    ):
        _fail("PROFILED_BASE_STATUS_DYNAMIC_UNIVERSE_AUTHORITY_INVALID")
    _validate_symbol_inventory(status)
    _validate_source_shard_preflights(status)
    classification = status.get("classification")
    if (
        type(classification) is not str
        or not classification
        or classification != classification.strip()
    ):
        _fail("PROFILED_BASE_STATUS_CLASSIFICATION_INVALID")
    return VerifiedProfiledBasePublisherCycleStatusV1(
        status_path=path,
        status_file_device=file_stat.st_dev,
        status_file_inode=file_stat.st_ino,
        status_file_byte_count=file_stat.st_size,
        status_sha256=cast(str, claimed_hash),
        state_sha256=cast(str, status["state_sha256"]),
        classification=classification,
        cycle_started_at=clocks[0],
        discovery_completed_at=clocks[1],
        selection_at=clocks[2],
        cycle_completed_at=clocks[3],
        discovered_symbol_count=cast(int, status["discovered_symbol_count"]),
        eligible_symbol_count=cast(int, status["eligible_symbol_count"]),
        selected_symbol_count=cast(int, status["selected_symbol_count"]),
        published_symbol_count=cast(int, status["published_symbol_count"]),
        exact_replay_symbol_count=cast(int, status["exact_replay_symbol_count"]),
        masked_cost_observation_symbol_count=cast(
            int,
            status["masked_cost_observation_symbol_count"],
        ),
        failed_symbol_count=cast(int, status["failed_symbol_count"]),
        local_status_integrity_verified=True,
        independent_status_authentication_verified=False,
        external_monotonic_manifest_head_verified=False,
        full_consumption_external_ack_verified=False,
        optimizer_admission_authorized=False,
        checkpoint_write_authorized=False,
        model_write_authorized=False,
        prediction_authorized=False,
        paper_trading_authorized=False,
        live_execution_authorized=False,
        order_submission_authorized=False,
        execution_authorized=False,
        runtime_wired=False,
        _construction_token=_RESULT_TOKEN,
    )


__all__ = (
    "MAX_PROFILED_BASE_PUBLISHER_STATUS_BYTES",
    "PROFILED_BASE_PUBLISHER_CYCLE_STATUS_V1_SCHEMA_VERSION",
    "ProfiledBasePublisherCycleStatusV1Error",
    "VerifiedProfiledBasePublisherCycleStatusV1",
    "read_verified_profiled_base_publisher_cycle_status_v1",
)
