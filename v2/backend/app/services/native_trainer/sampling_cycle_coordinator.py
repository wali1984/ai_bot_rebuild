"""Durable paper-only coordinator for one authenticated sampling cycle.

This module is deliberately below, and separate from, every publisher and
lifecycle writer.  It seals the exact authenticated plan/cohort identity,
records what an external paper publisher reports, and advances the sampling
carry head only after exact publication readback and terminal lifecycle
evidence have both been recorded.  It never reads Redis, publishes a payload,
appends a lifecycle event, or routes an order.

``PUBLICATION_COMMIT_UNKNOWN`` is a recovery fence, not a retry invitation.
Once entered, the only legal next transition requires readback evidence for
the exact publication keys and payload hashes sealed by the ambiguous commit.
Blind republishing is never authorized by this API.
"""

# ruff: noqa: S608 -- schema interpolation is exclusively module-owned constants.

from __future__ import annotations

import errno
import fcntl
import hashlib
import json
import math
import os
import re
import sqlite3
import stat
import threading
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NoReturn, cast

from v2.backend.app.services.native_trainer.adaptive_sampling_plan_contract import (
    U53_DENOMINATOR,
    is_content_addressed_checkpoint_id,
    sampling_plan_instance_id,
)

COORDINATOR_SCHEMA_VERSION = "v2_authenticated_sampling_cycle_coordinator_v1"
CYCLE_PREPARATION_SCHEMA_VERSION = "v2_authenticated_sampling_cycle_preparation_v1"
TRANSITION_EVIDENCE_SCHEMA_VERSION = "v2_sampling_cycle_transition_evidence_v1"
TRANSITION_SEAL_SCHEMA_VERSION = "v2_sampling_cycle_transition_seal_v1"
CARRY_HEAD_SCHEMA_VERSION = "v2_sampling_cycle_carry_head_v1"
CARRY_HEAD_TRANSITION_SCHEMA_VERSION = "v2_sampling_cycle_carry_head_transition_v1"

PHASE_PREPARED = "PREPARED"
PHASE_PUBLICATION_COMMIT_UNKNOWN = "PUBLICATION_COMMIT_UNKNOWN"
PHASE_PUBLICATION_READBACK_VERIFIED = "PUBLICATION_READBACK_VERIFIED"
PHASE_LIFECYCLE_VERIFIED = "LIFECYCLE_VERIFIED"
PHASE_COMPLETE = "COMPLETE"
SAMPLING_CYCLE_PHASES = (
    PHASE_PREPARED,
    PHASE_PUBLICATION_COMMIT_UNKNOWN,
    PHASE_PUBLICATION_READBACK_VERIFIED,
    PHASE_LIFECYCLE_VERIFIED,
    PHASE_COMPLETE,
)

# Serialization/resource bounds only.  They are not market thresholds.
MAX_COORDINATOR_JSON_BYTES = 512 * 1024
MAX_JSON_DEPTH = 32
MAX_JSON_ITEMS = 32_768
MAX_RESOURCE_INTEGER = (1 << 63) - 1
MAX_SAFE_OPAQUE_ID_CHARACTERS = 256
MAX_PUBLICATION_KEY_CHARACTERS = 512

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_AUTH_KEY_ID_RE = re.compile(r"^[A-Za-z0-9_.:@/-]{1,128}$")
_SAFE_OPAQUE_ID_RE = re.compile(rf"^[!-~]{{1,{MAX_SAFE_OPAQUE_ID_CHARACTERS}}}$")
_SAFE_PUBLICATION_KEY_RE = re.compile(rf"^[!-~]{{1,{MAX_PUBLICATION_KEY_CHARACTERS}}}$")
_TERMINAL_DISPOSITIONS = frozenset({"ENTRY_OUTCOME_FINALIZED", "SAMPLED_HOLD_FINALIZED"})

_CYCLE_FIELDS = frozenset(
    {
        "schema_version",
        "process_instance_id",
        "cycle_id",
        "plan_instance_id",
        "sampling_plan_envelope_auth_tag",
        "sampling_plan_auth_key_id",
        "sampling_plan_hash",
        "sampling_plan_input_hash",
        "parent_policy_fingerprint",
        "checkpoint_id",
        "checkpoint_weight_sha256",
        "manifest_digest",
        "cohort_id",
        "selected_receipts",
        "selected_receipt_count",
        "carry_in",
        "carry_out",
        "single_candidate_ordinary_credit_in",
        "single_candidate_ordinary_credit_out",
        "paper_only",
        "routes_to_live",
        "places_real_order",
    }
)
_SELECTED_RECEIPT_FIELDS = frozenset(
    {"selected_index", "receipt_hash", "draw_u53", "draw_denominator"}
)
_EVIDENCE_FIELDS = frozenset(
    {
        "schema_version",
        "cycle_identity_sha256",
        "transition_to",
        "expected_phase",
        "expected_revision",
        "observed_at",
        "selected_receipt_count",
        "publication_records",
        "publication_record_count",
        "publication_state",
        "publication_set_sha256",
        "lifecycle_records",
        "lifecycle_record_count",
        "lifecycle_state",
        "lifecycle_set_sha256",
        "zero_selected_vacuous",
        "carry_head_transition",
        "blind_republish_allowed",
        "paper_only",
        "routes_to_live",
        "places_real_order",
    }
)
_PUBLICATION_RECORD_FIELDS = frozenset(
    {"receipt_hash", "publication_key", "payload_sha256", "publication_status"}
)
_LIFECYCLE_RECORD_FIELDS = frozenset(
    {"receipt_hash", "terminal_disposition", "lifecycle_receipt_sha256"}
)
_HEAD_FIELDS = frozenset(
    {
        "schema_version",
        "process_instance_id",
        "revision",
        "carry",
        "single_candidate_ordinary_credit",
        "completed_cycle_identity_sha256",
        "updated_at",
        "paper_only",
        "routes_to_live",
        "places_real_order",
    }
)
_HEAD_TRANSITION_FIELDS = frozenset(
    {
        "schema_version",
        "process_instance_id",
        "expected_head_revision",
        "prior_head_sha256",
        "next_head_revision",
        "carry_in",
        "carry_out",
        "single_candidate_ordinary_credit_in",
        "single_candidate_ordinary_credit_out",
        "next_head_sha256",
        "paper_only",
        "routes_to_live",
        "places_real_order",
    }
)


def _terminal_capacity_material(selected_count: int) -> dict[str, Any]:
    """Build a conservative upper representation for terminal evidence.

    Backslash is the longest JSON rendering admitted by both bounded ASCII
    fields.  Float placeholders are strings one byte longer than the maximum
    finite non-negative binary64 rendering, so the result is an upper bound,
    not evidence accepted by the semantic validator.
    """

    sha256 = "f" * 64
    process_instance_id = "\\" * MAX_SAFE_OPAQUE_ID_CHARACTERS
    publication_key = "\\" * MAX_PUBLICATION_KEY_CHARACTERS
    publication_record = {
        "receipt_hash": sha256,
        "publication_key": publication_key,
        "payload_sha256": sha256,
        "publication_status": max(("COMMIT_UNKNOWN", "READBACK_VERIFIED"), key=len),
    }
    lifecycle_record = {
        "receipt_hash": sha256,
        "terminal_disposition": max(_TERMINAL_DISPOSITIONS, key=len),
        "lifecycle_receipt_sha256": sha256,
    }
    maximum_count = MAX_RESOURCE_INTEGER
    return {
        "schema_version": TRANSITION_EVIDENCE_SCHEMA_VERSION,
        "cycle_identity_sha256": sha256,
        "transition_to": max(SAMPLING_CYCLE_PHASES, key=len),
        "expected_phase": max(SAMPLING_CYCLE_PHASES, key=len),
        "expected_revision": maximum_count,
        "observed_at": "9999-12-31T23:59:59.999999Z",
        "selected_receipt_count": maximum_count,
        "publication_records": [publication_record] * selected_count,
        "publication_record_count": maximum_count,
        "publication_state": max(
            (
                "COMMIT_UNKNOWN",
                "READBACK_VERIFIED",
                "VACUOUS_NO_PUBLICATION_ATTEMPTED",
                "VACUOUS_NO_PUBLICATION_REQUIRED",
            ),
            key=len,
        ),
        "publication_set_sha256": sha256,
        "lifecycle_records": [lifecycle_record] * selected_count,
        "lifecycle_record_count": maximum_count,
        "lifecycle_state": max(
            (
                "NOT_YET_VERIFIED",
                "TERMINAL_LIFECYCLE_VERIFIED",
                "VACUOUS_NO_LIFECYCLE_REQUIRED",
            ),
            key=len,
        ),
        "lifecycle_set_sha256": sha256,
        "zero_selected_vacuous": False,
        "carry_head_transition": {
            "schema_version": CARRY_HEAD_TRANSITION_SCHEMA_VERSION,
            "process_instance_id": process_instance_id,
            "expected_head_revision": maximum_count,
            "prior_head_sha256": sha256,
            "next_head_revision": maximum_count,
            "carry_in": "9" * 24,
            "carry_out": "9" * 24,
            "single_candidate_ordinary_credit_in": maximum_count,
            "single_candidate_ordinary_credit_out": maximum_count,
            "next_head_sha256": sha256,
            "paper_only": True,
            "routes_to_live": False,
            "places_real_order": False,
        },
        "blind_republish_allowed": False,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }


def _builtin_json_item_count(value: Any) -> int:
    if type(value) is dict:
        return 1 + sum(_builtin_json_item_count(child) for child in value.values())
    if type(value) is list:
        return 1 + sum(_builtin_json_item_count(child) for child in value)
    return 1


def _terminal_capacity_fits(selected_count: int) -> bool:
    material = _terminal_capacity_material(selected_count)
    rendered = json.dumps(
        material,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    return (
        len(rendered.encode("ascii")) <= MAX_COORDINATOR_JSON_BYTES
        and _builtin_json_item_count(material) <= MAX_JSON_ITEMS
    )


def _derive_max_selected_receipts() -> int:
    lower = 0
    upper = 1
    while upper <= MAX_JSON_ITEMS and _terminal_capacity_fits(upper):
        lower = upper
        upper = min(upper * 2, MAX_JSON_ITEMS + 1)
    while lower + 1 < upper:
        candidate = (lower + upper) // 2
        if _terminal_capacity_fits(candidate):
            lower = candidate
        else:
            upper = candidate
    if lower <= 0 or _terminal_capacity_fits(lower + 1):
        raise RuntimeError("sampling_cycle_terminal_capacity_derivation_invalid")
    return lower


MAX_SELECTED_RECEIPTS = _derive_max_selected_receipts()

_SCHEMA_FINGERPRINT = hashlib.sha256(
    json.dumps(
        {
            "schema_version": COORDINATOR_SCHEMA_VERSION,
            "tables": {
                "sampling_cycle_carry_head_advances": [
                    "process_instance_id",
                    "head_revision",
                    "cycle_identity_sha256",
                    "prior_head_json",
                    "prior_head_sha256",
                    "next_head_json",
                    "next_head_sha256",
                    "advanced_at",
                    "cycle_transition_sha256",
                ],
                "sampling_cycle_carry_heads": [
                    "process_instance_id",
                    "revision",
                    "head_json",
                    "head_sha256",
                    "updated_at",
                ],
                "sampling_cycle_cycles": [
                    "cycle_identity_sha256",
                    "process_instance_id",
                    "cycle_id",
                    "plan_instance_id",
                    "phase",
                    "revision",
                    "cycle_json",
                    "cycle_sha256",
                    "prepared_at",
                    "updated_at",
                    "latest_transition_sha256",
                ],
                "sampling_cycle_evidence": [
                    "cycle_identity_sha256",
                    "revision",
                    "from_phase",
                    "to_phase",
                    "evidence_json",
                    "evidence_sha256",
                    "observed_at",
                    "previous_transition_sha256",
                    "transition_sha256",
                ],
                "sampling_cycle_metadata": ["metadata_key", "metadata_value"],
            },
            "phase_order": list(SAMPLING_CYCLE_PHASES),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
).hexdigest()

_EXPECTED_TABLE_COLUMNS: dict[str, tuple[tuple[str, str, int, int], ...]] = {
    "sampling_cycle_metadata": (
        ("metadata_key", "TEXT", 1, 1),
        ("metadata_value", "TEXT", 1, 0),
    ),
    "sampling_cycle_cycles": (
        ("cycle_identity_sha256", "TEXT", 1, 1),
        ("process_instance_id", "TEXT", 1, 0),
        ("cycle_id", "TEXT", 1, 0),
        ("plan_instance_id", "TEXT", 1, 0),
        ("phase", "TEXT", 1, 0),
        ("revision", "INTEGER", 1, 0),
        ("cycle_json", "TEXT", 1, 0),
        ("cycle_sha256", "TEXT", 1, 0),
        ("prepared_at", "TEXT", 1, 0),
        ("updated_at", "TEXT", 1, 0),
        ("latest_transition_sha256", "TEXT", 0, 0),
    ),
    "sampling_cycle_evidence": (
        ("cycle_identity_sha256", "TEXT", 1, 1),
        ("revision", "INTEGER", 1, 2),
        ("from_phase", "TEXT", 1, 0),
        ("to_phase", "TEXT", 1, 0),
        ("evidence_json", "TEXT", 1, 0),
        ("evidence_sha256", "TEXT", 1, 0),
        ("observed_at", "TEXT", 1, 0),
        ("previous_transition_sha256", "TEXT", 0, 0),
        ("transition_sha256", "TEXT", 1, 0),
    ),
    "sampling_cycle_carry_heads": (
        ("process_instance_id", "TEXT", 1, 1),
        ("revision", "INTEGER", 1, 0),
        ("head_json", "TEXT", 1, 0),
        ("head_sha256", "TEXT", 1, 0),
        ("updated_at", "TEXT", 1, 0),
    ),
    "sampling_cycle_carry_head_advances": (
        ("process_instance_id", "TEXT", 1, 1),
        ("head_revision", "INTEGER", 1, 2),
        ("cycle_identity_sha256", "TEXT", 1, 0),
        ("prior_head_json", "TEXT", 1, 0),
        ("prior_head_sha256", "TEXT", 1, 0),
        ("next_head_json", "TEXT", 1, 0),
        ("next_head_sha256", "TEXT", 1, 0),
        ("advanced_at", "TEXT", 1, 0),
        ("cycle_transition_sha256", "TEXT", 1, 0),
    ),
}

_EXPECTED_SCHEMA_OBJECTS = {
    "sampling_cycle_metadata": "table",
    "sampling_cycle_cycles": "table",
    "sampling_cycle_evidence": "table",
    "sampling_cycle_carry_heads": "table",
    "sampling_cycle_carry_head_advances": "table",
    "sampling_cycle_one_unresolved_per_process": "index",
    "sampling_cycle_metadata_no_update": "trigger",
    "sampling_cycle_metadata_no_delete": "trigger",
    "sampling_cycle_evidence_no_update": "trigger",
    "sampling_cycle_evidence_no_delete": "trigger",
    "sampling_cycle_cycles_no_delete": "trigger",
    "sampling_cycle_cycles_guard_update": "trigger",
    "sampling_cycle_carry_heads_no_delete": "trigger",
    "sampling_cycle_carry_heads_guard_update": "trigger",
    "sampling_cycle_head_advances_no_update": "trigger",
    "sampling_cycle_head_advances_no_delete": "trigger",
}

_SQLITE_APPLICATION_ID = 0x53434331
_SQLITE_USER_VERSION = 1

_DDL_METADATA = """
CREATE TABLE sampling_cycle_metadata (
    metadata_key TEXT NOT NULL PRIMARY KEY,
    metadata_value TEXT NOT NULL
) STRICT, WITHOUT ROWID
""".strip()

_DDL_CYCLES = f"""
CREATE TABLE sampling_cycle_cycles (
    cycle_identity_sha256 TEXT NOT NULL PRIMARY KEY,
    process_instance_id TEXT NOT NULL,
    cycle_id TEXT NOT NULL,
    plan_instance_id TEXT NOT NULL UNIQUE,
    phase TEXT NOT NULL CHECK (phase IN (
        '{PHASE_PREPARED}',
        '{PHASE_PUBLICATION_COMMIT_UNKNOWN}',
        '{PHASE_PUBLICATION_READBACK_VERIFIED}',
        '{PHASE_LIFECYCLE_VERIFIED}',
        '{PHASE_COMPLETE}'
    )),
    revision INTEGER NOT NULL
        CHECK (typeof(revision) = 'integer' AND revision BETWEEN 0 AND 4),
    cycle_json TEXT NOT NULL,
    cycle_sha256 TEXT NOT NULL,
    prepared_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    latest_transition_sha256 TEXT,
    UNIQUE(process_instance_id, cycle_id),
    CHECK (
        (revision = 0 AND phase = '{PHASE_PREPARED}') OR
        (revision = 1 AND phase = '{PHASE_PUBLICATION_COMMIT_UNKNOWN}') OR
        (revision = 2 AND phase = '{PHASE_PUBLICATION_READBACK_VERIFIED}') OR
        (revision = 3 AND phase = '{PHASE_LIFECYCLE_VERIFIED}') OR
        (revision = 4 AND phase = '{PHASE_COMPLETE}')
    ),
    CHECK (
        (revision = 0 AND latest_transition_sha256 IS NULL) OR
        (revision > 0 AND latest_transition_sha256 IS NOT NULL)
    )
) STRICT
""".strip()

_DDL_UNRESOLVED_INDEX = f"""
CREATE UNIQUE INDEX sampling_cycle_one_unresolved_per_process
ON sampling_cycle_cycles(process_instance_id)
WHERE phase != '{PHASE_COMPLETE}'
""".strip()

_DDL_EVIDENCE = """
CREATE TABLE sampling_cycle_evidence (
    cycle_identity_sha256 TEXT NOT NULL,
    revision INTEGER NOT NULL
        CHECK (typeof(revision) = 'integer' AND revision BETWEEN 1 AND 4),
    from_phase TEXT NOT NULL,
    to_phase TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    evidence_sha256 TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    previous_transition_sha256 TEXT,
    transition_sha256 TEXT NOT NULL,
    PRIMARY KEY(cycle_identity_sha256, revision),
    FOREIGN KEY(cycle_identity_sha256)
        REFERENCES sampling_cycle_cycles(cycle_identity_sha256)
        ON UPDATE RESTRICT ON DELETE RESTRICT
) STRICT, WITHOUT ROWID
""".strip()

_DDL_CARRY_HEADS = """
CREATE TABLE sampling_cycle_carry_heads (
    process_instance_id TEXT NOT NULL PRIMARY KEY,
    revision INTEGER NOT NULL
        CHECK (typeof(revision) = 'integer' AND revision >= 0),
    head_json TEXT NOT NULL,
    head_sha256 TEXT NOT NULL,
    updated_at TEXT NOT NULL
) STRICT, WITHOUT ROWID
""".strip()

_DDL_HEAD_ADVANCES = """
CREATE TABLE sampling_cycle_carry_head_advances (
    process_instance_id TEXT NOT NULL,
    head_revision INTEGER NOT NULL
        CHECK (typeof(head_revision) = 'integer' AND head_revision > 0),
    cycle_identity_sha256 TEXT NOT NULL UNIQUE,
    prior_head_json TEXT NOT NULL,
    prior_head_sha256 TEXT NOT NULL,
    next_head_json TEXT NOT NULL,
    next_head_sha256 TEXT NOT NULL,
    advanced_at TEXT NOT NULL,
    cycle_transition_sha256 TEXT NOT NULL,
    PRIMARY KEY(process_instance_id, head_revision),
    FOREIGN KEY(cycle_identity_sha256)
        REFERENCES sampling_cycle_cycles(cycle_identity_sha256)
        ON UPDATE RESTRICT ON DELETE RESTRICT
) STRICT, WITHOUT ROWID
""".strip()

_DDL_METADATA_NO_UPDATE = """
CREATE TRIGGER sampling_cycle_metadata_no_update
BEFORE UPDATE ON sampling_cycle_metadata BEGIN
    SELECT RAISE(ABORT, 'sampling_cycle_metadata_immutable');
END
""".strip()

_DDL_METADATA_NO_DELETE = """
CREATE TRIGGER sampling_cycle_metadata_no_delete
BEFORE DELETE ON sampling_cycle_metadata BEGIN
    SELECT RAISE(ABORT, 'sampling_cycle_metadata_immutable');
END
""".strip()

_DDL_EVIDENCE_NO_UPDATE = """
CREATE TRIGGER sampling_cycle_evidence_no_update
BEFORE UPDATE ON sampling_cycle_evidence BEGIN
    SELECT RAISE(ABORT, 'sampling_cycle_evidence_immutable');
END
""".strip()

_DDL_EVIDENCE_NO_DELETE = """
CREATE TRIGGER sampling_cycle_evidence_no_delete
BEFORE DELETE ON sampling_cycle_evidence BEGIN
    SELECT RAISE(ABORT, 'sampling_cycle_evidence_immutable');
END
""".strip()

_DDL_CYCLES_NO_DELETE = """
CREATE TRIGGER sampling_cycle_cycles_no_delete
BEFORE DELETE ON sampling_cycle_cycles BEGIN
    SELECT RAISE(ABORT, 'sampling_cycle_cycle_immutable');
END
""".strip()

_DDL_CYCLES_GUARD_UPDATE = f"""
CREATE TRIGGER sampling_cycle_cycles_guard_update
BEFORE UPDATE ON sampling_cycle_cycles
WHEN NEW.cycle_identity_sha256 != OLD.cycle_identity_sha256
  OR NEW.process_instance_id != OLD.process_instance_id
  OR NEW.cycle_id != OLD.cycle_id
  OR NEW.plan_instance_id != OLD.plan_instance_id
  OR NEW.cycle_json != OLD.cycle_json
  OR NEW.cycle_sha256 != OLD.cycle_sha256
  OR NEW.prepared_at != OLD.prepared_at
  OR NEW.revision != OLD.revision + 1
  OR NEW.updated_at < OLD.updated_at
  OR NEW.latest_transition_sha256 IS NULL
  OR NOT (
    (OLD.phase = '{PHASE_PREPARED}' AND
     NEW.phase = '{PHASE_PUBLICATION_COMMIT_UNKNOWN}') OR
    (OLD.phase = '{PHASE_PUBLICATION_COMMIT_UNKNOWN}' AND
     NEW.phase = '{PHASE_PUBLICATION_READBACK_VERIFIED}') OR
    (OLD.phase = '{PHASE_PUBLICATION_READBACK_VERIFIED}' AND
     NEW.phase = '{PHASE_LIFECYCLE_VERIFIED}') OR
    (OLD.phase = '{PHASE_LIFECYCLE_VERIFIED}' AND
     NEW.phase = '{PHASE_COMPLETE}')
  )
BEGIN
    SELECT RAISE(ABORT, 'sampling_cycle_phase_update_invalid');
END
""".strip()

_DDL_CARRY_HEADS_NO_DELETE = """
CREATE TRIGGER sampling_cycle_carry_heads_no_delete
BEFORE DELETE ON sampling_cycle_carry_heads BEGIN
    SELECT RAISE(ABORT, 'sampling_cycle_carry_head_immutable');
END
""".strip()

_DDL_CARRY_HEADS_GUARD_UPDATE = """
CREATE TRIGGER sampling_cycle_carry_heads_guard_update
BEFORE UPDATE ON sampling_cycle_carry_heads
WHEN NEW.process_instance_id != OLD.process_instance_id
  OR NEW.revision != OLD.revision + 1
  OR NEW.updated_at < OLD.updated_at
  OR NEW.head_json = OLD.head_json
  OR NEW.head_sha256 = OLD.head_sha256
BEGIN
    SELECT RAISE(ABORT, 'sampling_cycle_carry_head_update_invalid');
END
""".strip()

_DDL_HEAD_ADVANCES_NO_UPDATE = """
CREATE TRIGGER sampling_cycle_head_advances_no_update
BEFORE UPDATE ON sampling_cycle_carry_head_advances BEGIN
    SELECT RAISE(ABORT, 'sampling_cycle_head_advance_immutable');
END
""".strip()

_DDL_HEAD_ADVANCES_NO_DELETE = """
CREATE TRIGGER sampling_cycle_head_advances_no_delete
BEFORE DELETE ON sampling_cycle_carry_head_advances BEGIN
    SELECT RAISE(ABORT, 'sampling_cycle_head_advance_immutable');
END
""".strip()

_EXPECTED_DDL = {
    "sampling_cycle_metadata": _DDL_METADATA,
    "sampling_cycle_cycles": _DDL_CYCLES,
    "sampling_cycle_one_unresolved_per_process": _DDL_UNRESOLVED_INDEX,
    "sampling_cycle_evidence": _DDL_EVIDENCE,
    "sampling_cycle_carry_heads": _DDL_CARRY_HEADS,
    "sampling_cycle_carry_head_advances": _DDL_HEAD_ADVANCES,
    "sampling_cycle_metadata_no_update": _DDL_METADATA_NO_UPDATE,
    "sampling_cycle_metadata_no_delete": _DDL_METADATA_NO_DELETE,
    "sampling_cycle_evidence_no_update": _DDL_EVIDENCE_NO_UPDATE,
    "sampling_cycle_evidence_no_delete": _DDL_EVIDENCE_NO_DELETE,
    "sampling_cycle_cycles_no_delete": _DDL_CYCLES_NO_DELETE,
    "sampling_cycle_cycles_guard_update": _DDL_CYCLES_GUARD_UPDATE,
    "sampling_cycle_carry_heads_no_delete": _DDL_CARRY_HEADS_NO_DELETE,
    "sampling_cycle_carry_heads_guard_update": _DDL_CARRY_HEADS_GUARD_UPDATE,
    "sampling_cycle_head_advances_no_update": _DDL_HEAD_ADVANCES_NO_UPDATE,
    "sampling_cycle_head_advances_no_delete": _DDL_HEAD_ADVANCES_NO_DELETE,
}
_EXPECTED_DDL_SHA256 = hashlib.sha256(
    json.dumps(
        {name: " ".join(sql.split()).rstrip(";") for name, sql in sorted(_EXPECTED_DDL.items())},
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
).hexdigest()


class SamplingCycleCoordinatorError(RuntimeError):
    """A preparation, transition, or durable-integrity invariant failed."""


@dataclass(frozen=True, slots=True)
class SamplingCycleRecord:
    """Detached readback of one immutable cycle and its transition chain."""

    cycle_identity_sha256: str
    process_instance_id: str
    cycle_id: str
    plan_instance_id: str
    phase: str
    revision: int
    cycle: dict[str, Any]
    prepared_at: str
    updated_at: str
    latest_transition_sha256: str | None
    transition_evidence: tuple[dict[str, Any], ...]

    @property
    def unresolved(self) -> bool:
        return self.phase != PHASE_COMPLETE

    @property
    def blind_republish_allowed(self) -> bool:
        return False


@dataclass(frozen=True, slots=True)
class SamplingCycleCarryHead:
    """Detached readback of the process-owned durable carry head."""

    process_instance_id: str
    revision: int
    carry: float
    single_candidate_ordinary_credit: int
    completed_cycle_identity_sha256: str | None
    updated_at: str
    head_sha256: str


def _fail(code: str) -> NoReturn:
    raise SamplingCycleCoordinatorError(code)


def _is_sha256(value: object) -> bool:
    return type(value) is str and _SHA256_RE.fullmatch(value) is not None


def _strict_int(value: object) -> int | None:
    return value if type(value) is int else None


def _finite_float(value: object) -> float | None:
    if type(value) is not float or not math.isfinite(value):
        return None
    return 0.0 if value == 0.0 else value


def _canonical_time(value: object, code: str) -> str:
    if type(value) is not str or not value:
        _fail(code)
    text = value
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            _fail(code)
        return parsed.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    except (OverflowError, ValueError):
        _fail(code)


def _time_value(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _mro_contains(candidate_type: type[Any], expected_base: type[Any]) -> bool:
    """Recognize real inheritance without observing an instance hook."""

    try:
        mro = cast(
            tuple[type[Any], ...],
            type.__getattribute__(candidate_type, "__mro__"),
        )
    except (AttributeError, TypeError):
        _fail("sampling_cycle_json_type_recognition_invalid")
    return any(base is expected_base for base in mro)


def _freeze_json(value: object, *, depth: int = 0, budget: list[int] | None = None) -> Any:
    """Take one bounded snapshot without trusting Mapping length or re-reading it."""

    if budget is None:
        budget = [0]
    if depth > MAX_JSON_DEPTH:
        _fail("sampling_cycle_json_depth_exceeded")
    budget[0] += 1
    if budget[0] > MAX_JSON_ITEMS:
        _fail("sampling_cycle_json_items_exceeded")
    value_type = type(value)
    if value is None or value_type is bool or value_type is int or value_type is str:
        return value
    if value_type is float:
        float_value = cast(float, value)
        if not math.isfinite(float_value):
            _fail("sampling_cycle_json_nonfinite")
        return 0.0 if float_value == 0.0 else float_value
    if value_type is list:
        try:
            values = tuple(cast(list[Any], value))
        except Exception:
            raise SamplingCycleCoordinatorError("sampling_cycle_json_list_invalid") from None
        return [_freeze_json(item, depth=depth + 1, budget=budget) for item in values]
    if value_type is dict or _mro_contains(value_type, Mapping):
        mapping_value = cast(Mapping[Any, Any], value)
        try:
            # The generator suppresses an adversarial length hint and consumes
            # the caller-owned mapping exactly once.
            items = tuple(item for item in mapping_value.items())
        except Exception:
            raise SamplingCycleCoordinatorError("sampling_cycle_json_mapping_invalid") from None
        result: dict[str, Any] = {}
        for item in items:
            if type(item) is not tuple or len(item) != 2:
                _fail("sampling_cycle_json_mapping_invalid")
            key, child = item
            if type(key) is not str:
                _fail("sampling_cycle_json_key_invalid")
            if key in result:
                _fail("sampling_cycle_json_key_duplicate")
            result[key] = _freeze_json(child, depth=depth + 1, budget=budget)
        return result
    _fail("sampling_cycle_json_type_invalid")


def _canonical_json(value: object) -> str:
    try:
        rendered = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (OverflowError, RecursionError, TypeError, ValueError):
        raise SamplingCycleCoordinatorError("sampling_cycle_json_invalid") from None
    if not rendered or len(rendered.encode("ascii")) > MAX_COORDINATOR_JSON_BYTES:
        _fail("sampling_cycle_json_size_invalid")
    return rendered


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def _canonical_sha256(value: object) -> str:
    return _sha256_text(_canonical_json(value))


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail("sampling_cycle_stored_json_duplicate_key")
        result[key] = value
    return result


def _reject_nonfinite_json(_value: str) -> None:
    _fail("sampling_cycle_stored_json_nonfinite")


def _decode_canonical_object(value: object) -> dict[str, Any]:
    if type(value) is not str or not value:
        _fail("sampling_cycle_stored_json_invalid")
    text = value
    if len(text.encode("utf-8")) > MAX_COORDINATOR_JSON_BYTES:
        _fail("sampling_cycle_stored_json_size_invalid")
    try:
        parsed = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_json_keys,
            parse_constant=_reject_nonfinite_json,
        )
    except SamplingCycleCoordinatorError:
        raise
    except (RecursionError, TypeError, ValueError):
        raise SamplingCycleCoordinatorError("sampling_cycle_stored_json_invalid") from None
    if type(parsed) is not dict or _canonical_json(parsed) != text:
        _fail("sampling_cycle_stored_json_noncanonical")
    return cast(dict[str, Any], parsed)


def _require_exact_fields(row: Mapping[str, Any], fields: frozenset[str], code: str) -> None:
    if set(row) != fields:
        _fail(code)


def _validate_safety_flags(row: Mapping[str, Any], code: str) -> None:
    if (
        row.get("paper_only") is not True
        or row.get("routes_to_live") is not False
        or row.get("places_real_order") is not False
    ):
        _fail(code)


def _validated_cycle(value: object) -> dict[str, Any]:
    frozen = _freeze_json(value)
    if type(frozen) is not dict:
        _fail("sampling_cycle_preparation_mapping_invalid")
    row = cast(dict[str, Any], frozen)
    _require_exact_fields(row, _CYCLE_FIELDS, "sampling_cycle_preparation_shape_invalid")
    if row.get("schema_version") != CYCLE_PREPARATION_SCHEMA_VERSION:
        _fail("sampling_cycle_preparation_schema_invalid")
    _validate_safety_flags(row, "sampling_cycle_preparation_paper_safety_invalid")
    process_id = row.get("process_instance_id")
    cycle_id = row.get("cycle_id")
    if type(process_id) is not str or _SAFE_OPAQUE_ID_RE.fullmatch(process_id) is None:
        _fail("sampling_cycle_process_instance_id_invalid")
    if type(cycle_id) is not str or _SAFE_OPAQUE_ID_RE.fullmatch(cycle_id) is None:
        _fail("sampling_cycle_cycle_id_invalid")
    process_text = process_id
    cycle_text = cycle_id
    if row.get("plan_instance_id") != sampling_plan_instance_id(
        cycle_id=cycle_text, process_instance_id=process_text
    ):
        _fail("sampling_cycle_plan_instance_id_invalid")
    for field in (
        "sampling_plan_envelope_auth_tag",
        "sampling_plan_hash",
        "sampling_plan_input_hash",
        "parent_policy_fingerprint",
        "checkpoint_weight_sha256",
        "manifest_digest",
        "cohort_id",
    ):
        if not _is_sha256(row.get(field)):
            _fail(f"sampling_cycle_{field}_invalid")
    auth_key_id = row.get("sampling_plan_auth_key_id")
    if type(auth_key_id) is not str or _SAFE_AUTH_KEY_ID_RE.fullmatch(auth_key_id) is None:
        _fail("sampling_cycle_sampling_plan_auth_key_id_invalid")
    if not is_content_addressed_checkpoint_id(row.get("checkpoint_id")):
        _fail("sampling_cycle_checkpoint_id_invalid")

    selected = row.get("selected_receipts")
    selected_count = _strict_int(row.get("selected_receipt_count"))
    if type(selected) is not list or selected_count is None or selected_count < 0:
        _fail("sampling_cycle_selected_receipts_invalid")
    selected_rows = selected
    if selected_count != len(selected_rows):
        _fail("sampling_cycle_selected_receipt_count_invalid")
    if len(selected_rows) > MAX_SELECTED_RECEIPTS:
        _fail("sampling_cycle_terminal_capacity_exceeded")
    indices: list[int] = []
    receipt_hashes: list[str] = []
    for record in selected_rows:
        if type(record) is not dict:
            _fail("sampling_cycle_selected_receipt_invalid")
        _require_exact_fields(
            record, _SELECTED_RECEIPT_FIELDS, "sampling_cycle_selected_receipt_shape_invalid"
        )
        index = _strict_int(record.get("selected_index"))
        draw = _strict_int(record.get("draw_u53"))
        if index is None or not 0 <= index <= MAX_RESOURCE_INTEGER:
            _fail("sampling_cycle_selected_index_invalid")
        if draw is None or not 0 <= draw < U53_DENOMINATOR:
            _fail("sampling_cycle_selected_draw_invalid")
        if record.get("draw_denominator") != U53_DENOMINATOR:
            _fail("sampling_cycle_selected_draw_denominator_invalid")
        receipt_hash = record.get("receipt_hash")
        if not _is_sha256(receipt_hash):
            _fail("sampling_cycle_selected_receipt_hash_invalid")
        indices.append(index)
        receipt_hashes.append(cast(str, receipt_hash))
    if indices != sorted(set(indices)):
        _fail("sampling_cycle_selected_indices_noncanonical")
    if len(receipt_hashes) != len(set(receipt_hashes)):
        _fail("sampling_cycle_selected_receipt_hash_duplicate")

    carry_in = _finite_float(row.get("carry_in"))
    carry_out = _finite_float(row.get("carry_out"))
    credit_in = _strict_int(row.get("single_candidate_ordinary_credit_in"))
    credit_out = _strict_int(row.get("single_candidate_ordinary_credit_out"))
    if (
        carry_in is None
        or carry_out is None
        or not 0.0 <= carry_in <= 1.0
        or not 0.0 <= carry_out <= 1.0
    ):
        _fail("sampling_cycle_carry_invalid")
    if (
        credit_in is None
        or credit_out is None
        or not 0 <= credit_in <= MAX_RESOURCE_INTEGER
        or not 0 <= credit_out <= MAX_RESOURCE_INTEGER
    ):
        _fail("sampling_cycle_ordinary_credit_invalid")
    row["carry_in"] = carry_in
    row["carry_out"] = carry_out
    return row


def _head_material(
    *,
    process_instance_id: str,
    revision: int,
    carry: float,
    ordinary_credit: int,
    completed_cycle_identity_sha256: str | None,
    updated_at: str,
) -> dict[str, Any]:
    return {
        "schema_version": CARRY_HEAD_SCHEMA_VERSION,
        "process_instance_id": process_instance_id,
        "revision": revision,
        "carry": carry,
        "single_candidate_ordinary_credit": ordinary_credit,
        "completed_cycle_identity_sha256": completed_cycle_identity_sha256,
        "updated_at": updated_at,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }


def _validated_head_material(value: object) -> dict[str, Any]:
    if type(value) is not dict:
        _fail("sampling_cycle_carry_head_invalid")
    row = cast(dict[str, Any], value)
    _require_exact_fields(row, _HEAD_FIELDS, "sampling_cycle_carry_head_shape_invalid")
    if row.get("schema_version") != CARRY_HEAD_SCHEMA_VERSION:
        _fail("sampling_cycle_carry_head_schema_invalid")
    _validate_safety_flags(row, "sampling_cycle_carry_head_paper_safety_invalid")
    process_id = row.get("process_instance_id")
    revision = _strict_int(row.get("revision"))
    carry = _finite_float(row.get("carry"))
    credit = _strict_int(row.get("single_candidate_ordinary_credit"))
    completed = row.get("completed_cycle_identity_sha256")
    if type(process_id) is not str or _SAFE_OPAQUE_ID_RE.fullmatch(process_id) is None:
        _fail("sampling_cycle_carry_head_process_invalid")
    if revision is None or not 0 <= revision <= MAX_RESOURCE_INTEGER:
        _fail("sampling_cycle_carry_head_revision_invalid")
    head_revision = revision
    if carry is None or not 0.0 <= carry <= 1.0:
        _fail("sampling_cycle_carry_head_value_invalid")
    if credit is None or not 0 <= credit <= MAX_RESOURCE_INTEGER:
        _fail("sampling_cycle_carry_head_credit_invalid")
    if (head_revision == 0 and completed is not None) or (
        head_revision > 0 and not _is_sha256(completed)
    ):
        _fail("sampling_cycle_carry_head_completion_invalid")
    row["updated_at"] = _canonical_time(
        row.get("updated_at"), "sampling_cycle_carry_head_time_invalid"
    )
    row["carry"] = carry
    return row


def _publication_identity(record: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        cast(str, record["receipt_hash"]),
        cast(str, record["publication_key"]),
        cast(str, record["payload_sha256"]),
    )


def _expected_phase_for(target: str) -> str:
    try:
        return SAMPLING_CYCLE_PHASES[SAMPLING_CYCLE_PHASES.index(target) - 1]
    except (ValueError, IndexError):
        _fail("sampling_cycle_transition_target_invalid")


@dataclass(frozen=True, slots=True)
class _DirectoryBinding:
    parent_fd: int
    name: str
    child_fd: int
    identity: tuple[int, int]


@dataclass(frozen=True, slots=True)
class _FileDescriptorState:
    device: int
    inode: int
    mode: int
    link_count: int
    owner_uid: int
    status_flags: int
    descriptor_flags: int

    @property
    def identity(self) -> tuple[int, int]:
        return (self.device, self.inode)


_UNSUPPORTED_PATH_ERRNOS = frozenset(
    {
        errno.ENOSYS,
        getattr(errno, "ENOTSUP", errno.ENOSYS),
        getattr(errno, "EOPNOTSUPP", errno.ENOSYS),
    }
)

_PROC_SELF_FD = "/proc/self/fd"
_SQLITE_DESCRIPTOR_PROOF_LOCK = threading.RLock()
_NATIVE_PATH_TYPE = type(Path("/"))


def _exact_database_path(path: Path) -> Path:
    if type(path) is not _NATIVE_PATH_TYPE:
        _fail("sampling_cycle_db_path_must_be_explicit_absolute_path")
    raw = os.fspath(path)
    exact = Path(raw)
    if not raw or "\x00" in raw or not exact.is_absolute():
        _fail("sampling_cycle_db_path_must_be_explicit_absolute_path")
    if any(component in {"", ".", ".."} for component in exact.parts[1:]):
        _fail("sampling_cycle_db_path_lexically_invalid")
    if exact == Path(exact.anchor) or exact.name in {"", ".", ".."}:
        _fail("sampling_cycle_db_path_lexically_invalid")
    return exact


def _path_capability_failure() -> NoReturn:
    _fail("sampling_cycle_db_platform_capability_unsupported")


def _required_os_flag(name: str) -> int:
    value = getattr(os, name, None)
    if type(value) is not int or value <= 0:
        _path_capability_failure()
    return value


def _require_secure_path_capabilities() -> None:
    _required_os_flag("O_DIRECTORY")
    _required_os_flag("O_NOFOLLOW")
    supports_dir_fd: object = getattr(os, "supports_dir_fd", None)
    supports_follow_symlinks: object = getattr(os, "supports_follow_symlinks", None)
    if (
        not isinstance(supports_dir_fd, set)
        or not isinstance(supports_follow_symlinks, set)
        or os.open not in supports_dir_fd
        or os.stat not in supports_dir_fd
        or os.stat not in supports_follow_symlinks
        or not callable(getattr(os, "geteuid", None))
    ):
        _path_capability_failure()


def _snapshot_process_file_descriptors() -> dict[int, _FileDescriptorState]:
    """Return a fail-closed Linux descriptor snapshot without exposing paths."""

    try:
        names = os.listdir(_PROC_SELF_FD)
    except (OSError, NotImplementedError, TypeError, ValueError, AttributeError):
        _path_capability_failure()
    snapshot: dict[int, _FileDescriptorState] = {}
    for name in names:
        if not name.isascii() or not name.isdecimal():
            _path_capability_failure()
        descriptor = int(name)
        try:
            descriptor_stat = os.fstat(descriptor)
            status_flags = int(fcntl.fcntl(descriptor, fcntl.F_GETFL))
            descriptor_flags = int(fcntl.fcntl(descriptor, fcntl.F_GETFD))
        except OSError as exc:
            # The descriptor used internally by procfs enumeration, or a
            # descriptor closed by another thread, may disappear between the
            # directory read and fstat.  Such a descriptor cannot be retained
            # by the SQLite connection and is therefore not part of the proof.
            if exc.errno == errno.EBADF:
                continue
            _raise_path_error(exc, "sampling_cycle_db_descriptor_snapshot_failed")
        except (NotImplementedError, TypeError, ValueError, AttributeError) as exc:
            _raise_path_error(exc, "sampling_cycle_db_descriptor_snapshot_failed")
        snapshot[descriptor] = _FileDescriptorState(
            device=int(descriptor_stat.st_dev),
            inode=int(descriptor_stat.st_ino),
            mode=int(descriptor_stat.st_mode),
            link_count=int(descriptor_stat.st_nlink),
            owner_uid=int(descriptor_stat.st_uid),
            status_flags=status_flags,
            descriptor_flags=descriptor_flags,
        )
    return snapshot


def _added_descriptors(
    before: Mapping[int, _FileDescriptorState],
    after: Mapping[int, _FileDescriptorState],
    *,
    require_stable_baseline: bool = True,
) -> dict[int, _FileDescriptorState]:
    if require_stable_baseline:
        for descriptor, state in before.items():
            if after.get(descriptor) != state:
                _fail("sampling_cycle_db_descriptor_baseline_changed")
    return {descriptor: state for descriptor, state in after.items() if descriptor not in before}


def _connection_descriptor_state(descriptor: int, *, code: str) -> _FileDescriptorState:
    try:
        descriptor_stat = os.fstat(descriptor)
        status_flags = int(fcntl.fcntl(descriptor, fcntl.F_GETFL))
        descriptor_flags = int(fcntl.fcntl(descriptor, fcntl.F_GETFD))
    except (OSError, NotImplementedError, TypeError, ValueError, AttributeError) as exc:
        _raise_path_error(exc, code)
    return _FileDescriptorState(
        device=int(descriptor_stat.st_dev),
        inode=int(descriptor_stat.st_ino),
        mode=int(descriptor_stat.st_mode),
        link_count=int(descriptor_stat.st_nlink),
        owner_uid=int(descriptor_stat.st_uid),
        status_flags=status_flags,
        descriptor_flags=descriptor_flags,
    )


def _validate_connection_artifact_state(
    state: _FileDescriptorState,
    *,
    expected_identity: tuple[int, int],
    expected_owner_uid: int,
    role: str,
    expected_access_mode: int | None = None,
) -> None:
    if (
        not stat.S_ISREG(state.mode)
        or state.identity != expected_identity
        or state.link_count != 1
        or state.owner_uid != expected_owner_uid
    ):
        _fail(f"sampling_cycle_db_connection_{role}_binding_mismatch")
    if (
        expected_access_mode is not None
        and state.status_flags & os.O_ACCMODE != expected_access_mode
    ):
        _fail(f"sampling_cycle_db_connection_{role}_binding_mismatch")
    artifact_mode = stat.S_IMODE(state.mode)
    if (role == "main" and artifact_mode != 0o600) or (role != "main" and artifact_mode & 0o077):
        _fail(f"sampling_cycle_db_connection_{role}_binding_mismatch")


def _raise_path_error(exc: BaseException, code: str) -> NoReturn:
    if (
        isinstance(exc, NotImplementedError | TypeError | ValueError | AttributeError)
        or isinstance(exc, OSError)
        and exc.errno in _UNSUPPORTED_PATH_ERRNOS
    ):
        _path_capability_failure()
    raise SamplingCycleCoordinatorError(code) from None


def _directory_open_flags() -> int:
    return (
        os.O_RDONLY
        | _required_os_flag("O_DIRECTORY")
        | _required_os_flag("O_NOFOLLOW")
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )


def _file_open_flags(*, writable: bool = False) -> int:
    return (
        (os.O_RDWR if writable else os.O_RDONLY)
        | _required_os_flag("O_NOFOLLOW")
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )


def _open_parent_chain(path: Path) -> tuple[list[int], list[_DirectoryBinding]]:
    try:
        anchor_fd = os.open(path.anchor, _directory_open_flags())
    except (OSError, NotImplementedError, TypeError, ValueError, AttributeError) as exc:
        _raise_path_error(exc, "sampling_cycle_db_path_open_failed")
    descriptors = [anchor_fd]
    bindings: list[_DirectoryBinding] = []
    try:
        for component in path.parent.parts[1:]:
            parent_fd = descriptors[-1]
            child_fd = -1
            try:
                child_fd = os.open(component, _directory_open_flags(), dir_fd=parent_fd)
                descriptor_stat = os.fstat(child_fd)
                path_stat = os.stat(component, dir_fd=parent_fd, follow_symlinks=False)
            except (OSError, NotImplementedError, TypeError, ValueError, AttributeError) as exc:
                if child_fd >= 0:
                    os.close(child_fd)
                _raise_path_error(exc, "sampling_cycle_db_parent_open_failed")
            identity = (int(descriptor_stat.st_dev), int(descriptor_stat.st_ino))
            if (
                not stat.S_ISDIR(descriptor_stat.st_mode)
                or not stat.S_ISDIR(path_stat.st_mode)
                or identity != (int(path_stat.st_dev), int(path_stat.st_ino))
            ):
                os.close(child_fd)
                _fail("sampling_cycle_db_parent_binding_changed")
            descriptors.append(child_fd)
            bindings.append(
                _DirectoryBinding(
                    parent_fd=parent_fd,
                    name=component,
                    child_fd=child_fd,
                    identity=identity,
                )
            )
        return descriptors, bindings
    except BaseException:
        for descriptor in reversed(descriptors):
            os.close(descriptor)
        raise


def _validate_directory_bindings(
    bindings: list[_DirectoryBinding], *, parent_fd: int, expected_owner_uid: int
) -> None:
    for binding in bindings:
        try:
            descriptor_stat = os.fstat(binding.child_fd)
            path_stat = os.stat(
                binding.name,
                dir_fd=binding.parent_fd,
                follow_symlinks=False,
            )
        except (OSError, NotImplementedError, TypeError, ValueError, AttributeError) as exc:
            _raise_path_error(exc, "sampling_cycle_db_parent_binding_changed")
        descriptor_identity = (int(descriptor_stat.st_dev), int(descriptor_stat.st_ino))
        path_identity = (int(path_stat.st_dev), int(path_stat.st_ino))
        if (
            not stat.S_ISDIR(descriptor_stat.st_mode)
            or not stat.S_ISDIR(path_stat.st_mode)
            or descriptor_identity != binding.identity
            or path_identity != binding.identity
        ):
            _fail("sampling_cycle_db_parent_binding_changed")
    try:
        parent_stat = os.fstat(parent_fd)
    except (OSError, NotImplementedError, TypeError, ValueError, AttributeError) as exc:
        _raise_path_error(exc, "sampling_cycle_db_parent_stat_failed")
    if not stat.S_ISDIR(parent_stat.st_mode):
        _fail("sampling_cycle_db_parent_invalid")
    if parent_stat.st_uid != expected_owner_uid:
        _fail("sampling_cycle_db_parent_owner_mismatch")
    if stat.S_IMODE(parent_stat.st_mode) & 0o077:
        _fail("sampling_cycle_db_parent_not_owner_private")


def _validated_artifact_identity(
    descriptor_stat: os.stat_result,
    path_stat: os.stat_result,
    *,
    expected_owner_uid: int,
    role: str,
) -> tuple[int, int]:
    identity = (int(descriptor_stat.st_dev), int(descriptor_stat.st_ino))
    if (
        not stat.S_ISREG(descriptor_stat.st_mode)
        or not stat.S_ISREG(path_stat.st_mode)
        or identity != (int(path_stat.st_dev), int(path_stat.st_ino))
    ):
        _fail(f"sampling_cycle_db_{role}_binding_invalid")
    if descriptor_stat.st_nlink != 1 or path_stat.st_nlink != 1:
        _fail(f"sampling_cycle_db_{role}_hardlink_forbidden")
    if descriptor_stat.st_uid != expected_owner_uid or path_stat.st_uid != expected_owner_uid:
        _fail(f"sampling_cycle_db_{role}_owner_mismatch")
    descriptor_mode = stat.S_IMODE(descriptor_stat.st_mode)
    path_mode = stat.S_IMODE(path_stat.st_mode)
    if (role == "main" and (descriptor_mode != 0o600 or path_mode != 0o600)) or (
        role != "main" and (descriptor_mode & 0o077 or path_mode & 0o077)
    ):
        _fail(f"sampling_cycle_db_{role}_private_mode_required")
    return identity


def _open_artifact(
    parent_fd: int,
    name: str,
    *,
    expected_owner_uid: int,
    role: str,
    writable: bool = False,
) -> tuple[int, tuple[int, int]]:
    descriptor = -1
    try:
        descriptor = os.open(name, _file_open_flags(writable=writable), dir_fd=parent_fd)
        descriptor_stat = os.fstat(descriptor)
        path_stat = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        identity = _validated_artifact_identity(
            descriptor_stat,
            path_stat,
            expected_owner_uid=expected_owner_uid,
            role=role,
        )
        return descriptor, identity
    except SamplingCycleCoordinatorError:
        if descriptor >= 0:
            os.close(descriptor)
        raise
    except (OSError, NotImplementedError, TypeError, ValueError, AttributeError) as exc:
        if descriptor >= 0:
            os.close(descriptor)
        _raise_path_error(exc, f"sampling_cycle_db_{role}_open_failed")


def _validate_sidecars(
    parent_fd: int,
    main_name: str,
    *,
    expected_owner_uid: int,
    main_identity: tuple[int, int],
) -> dict[str, tuple[int, int]]:
    identities = {main_identity}
    sidecar_identities: dict[str, tuple[int, int]] = {}
    for role, suffix in (("journal", "-journal"), ("wal", "-wal"), ("shm", "-shm")):
        name = main_name + suffix
        try:
            os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            continue
        except (OSError, NotImplementedError, TypeError, ValueError, AttributeError) as exc:
            _raise_path_error(exc, f"sampling_cycle_db_{role}_stat_failed")
        descriptor, identity = _open_artifact(
            parent_fd,
            name,
            expected_owner_uid=expected_owner_uid,
            role=role,
        )
        try:
            if identity in identities:
                _fail("sampling_cycle_db_artifact_identity_collision")
            identities.add(identity)
            if role in {"wal", "shm"}:
                _fail("sampling_cycle_db_unexpected_wal_sidecar")
            sidecar_identities[role] = identity
        finally:
            os.close(descriptor)
    return sidecar_identities


class _StorageBinding:
    __slots__ = (
        "bindings",
        "descriptors",
        "directory_identities",
        "expected_owner_uid",
        "main_fd",
        "main_identity",
        "main_name",
        "parent_fd",
        "released",
    )

    def __init__(
        self,
        *,
        descriptors: list[int],
        bindings: list[_DirectoryBinding],
        expected_owner_uid: int,
        main_fd: int,
        main_identity: tuple[int, int],
        main_name: str,
    ) -> None:
        self.descriptors = descriptors
        self.bindings = bindings
        self.directory_identities = tuple(
            (int(os.fstat(descriptor).st_dev), int(os.fstat(descriptor).st_ino))
            for descriptor in descriptors
        )
        self.expected_owner_uid = expected_owner_uid
        self.main_fd = main_fd
        self.main_identity = main_identity
        self.main_name = main_name
        self.parent_fd = descriptors[-1]
        self.released = False

    def validate(self) -> dict[str, tuple[int, int]]:
        if self.released:
            _fail("sampling_cycle_db_storage_binding_released")
        _validate_directory_bindings(
            self.bindings,
            parent_fd=self.parent_fd,
            expected_owner_uid=self.expected_owner_uid,
        )
        try:
            descriptor_stat = os.fstat(self.main_fd)
            path_stat = os.stat(
                self.main_name,
                dir_fd=self.parent_fd,
                follow_symlinks=False,
            )
        except (OSError, NotImplementedError, TypeError, ValueError, AttributeError) as exc:
            _raise_path_error(exc, "sampling_cycle_db_main_binding_changed")
        identity = _validated_artifact_identity(
            descriptor_stat,
            path_stat,
            expected_owner_uid=self.expected_owner_uid,
            role="main",
        )
        if identity != self.main_identity:
            _fail("sampling_cycle_db_main_binding_changed")
        return _validate_sidecars(
            self.parent_fd,
            self.main_name,
            expected_owner_uid=self.expected_owner_uid,
            main_identity=self.main_identity,
        )

    def release(self) -> None:
        if self.released:
            return
        self.released = True
        os.close(self.main_fd)
        for descriptor in reversed(self.descriptors):
            os.close(descriptor)


def _acquire_storage_binding(
    path: Path,
    *,
    create_main: bool,
    expected_identity: tuple[int, int] | None,
    expected_directory_identities: tuple[tuple[int, int], ...] | None,
) -> _StorageBinding:
    try:
        expected_owner_uid = os.geteuid()
    except (OSError, NotImplementedError, TypeError, ValueError, AttributeError) as exc:
        _raise_path_error(exc, "sampling_cycle_db_effective_owner_unavailable")
    descriptors, bindings = _open_parent_chain(path)
    parent_fd = descriptors[-1]
    main_fd = -1
    try:
        _validate_directory_bindings(
            bindings,
            parent_fd=parent_fd,
            expected_owner_uid=expected_owner_uid,
        )
        directory_identities = tuple(
            (int(os.fstat(descriptor).st_dev), int(os.fstat(descriptor).st_ino))
            for descriptor in descriptors
        )
        if (
            expected_directory_identities is not None
            and directory_identities != expected_directory_identities
        ):
            _fail("sampling_cycle_db_parent_inode_changed")
        try:
            candidate_stat = os.stat(
                path.name,
                dir_fd=parent_fd,
                follow_symlinks=False,
            )
            main_exists = True
        except FileNotFoundError:
            candidate_stat = None
            main_exists = False
        except (OSError, NotImplementedError, TypeError, ValueError, AttributeError) as exc:
            _raise_path_error(exc, "sampling_cycle_db_main_stat_failed")
        if candidate_stat is not None and stat.S_ISLNK(candidate_stat.st_mode):
            _fail("sampling_cycle_db_file_invalid")
        if main_exists:
            assert candidate_stat is not None
            if not stat.S_ISREG(candidate_stat.st_mode):
                _fail("sampling_cycle_db_file_invalid")
            if candidate_stat.st_nlink != 1:
                _fail("sampling_cycle_db_main_hardlink_forbidden")
            if candidate_stat.st_uid != expected_owner_uid:
                _fail("sampling_cycle_db_main_owner_mismatch")
            if stat.S_IMODE(candidate_stat.st_mode) != 0o600:
                _fail("sampling_cycle_db_main_private_mode_required")
            main_fd, identity = _open_artifact(
                parent_fd,
                path.name,
                expected_owner_uid=expected_owner_uid,
                role="main",
                writable=create_main,
            )
        else:
            if not create_main:
                _fail("sampling_cycle_db_main_missing")
            flags = _file_open_flags(writable=True) | os.O_CREAT | os.O_EXCL
            try:
                main_fd = os.open(path.name, flags, 0o600, dir_fd=parent_fd)
                os.fchmod(main_fd, 0o600)
                descriptor_stat = os.fstat(main_fd)
                path_stat = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
            except (
                OSError,
                NotImplementedError,
                TypeError,
                ValueError,
                AttributeError,
            ) as create_exc:
                if main_fd >= 0:
                    os.close(main_fd)
                    main_fd = -1
                _raise_path_error(create_exc, "sampling_cycle_db_secure_create_failed")
            identity = _validated_artifact_identity(
                descriptor_stat,
                path_stat,
                expected_owner_uid=expected_owner_uid,
                role="main",
            )
        if expected_identity is not None and identity != expected_identity:
            _fail("sampling_cycle_db_main_inode_changed")
        _validate_sidecars(
            parent_fd,
            path.name,
            expected_owner_uid=expected_owner_uid,
            main_identity=identity,
        )
        binding = _StorageBinding(
            descriptors=descriptors,
            bindings=bindings,
            expected_owner_uid=expected_owner_uid,
            main_fd=main_fd,
            main_identity=identity,
            main_name=path.name,
        )
        binding.validate()
        return binding
    except BaseException:
        if main_fd >= 0:
            os.close(main_fd)
        for descriptor in reversed(descriptors):
            os.close(descriptor)
        raise


class _StorageGuardedSQLiteConnection(sqlite3.Connection):
    __slots__ = (
        "_sampling_cycle_binding",
        "_sampling_cycle_connection_main_fd",
        "_sampling_cycle_connection_sidecar_fds",
        "_sampling_cycle_descriptor_proof_lock_held",
        "_sampling_cycle_expected_access_mode",
        "_sampling_cycle_preconnect_fds",
    )

    def bind_storage(
        self,
        binding: _StorageBinding,
        preconnect_fds: Mapping[int, _FileDescriptorState],
        *,
        writable: bool,
    ) -> None:
        if hasattr(self, "_sampling_cycle_binding"):
            _fail("sampling_cycle_db_connection_binding_reused")
        self._sampling_cycle_binding = binding
        self._sampling_cycle_preconnect_fds = dict(preconnect_fds)
        self._sampling_cycle_connection_main_fd = -1
        self._sampling_cycle_connection_sidecar_fds: dict[str, tuple[int, tuple[int, int]]] = {}
        self._sampling_cycle_descriptor_proof_lock_held = True
        self._sampling_cycle_expected_access_mode = os.O_RDWR if writable else os.O_RDONLY
        binding.validate()
        connected_fds = _snapshot_process_file_descriptors()
        opened_fds = _added_descriptors(
            self._sampling_cycle_preconnect_fds,
            connected_fds,
        )
        if len(opened_fds) != 1:
            _fail("sampling_cycle_db_connection_main_binding_mismatch")
        connection_fd, connection_state = next(iter(opened_fds.items()))
        _validate_connection_artifact_state(
            connection_state,
            expected_identity=binding.main_identity,
            expected_owner_uid=binding.expected_owner_uid,
            role="main",
            expected_access_mode=self._sampling_cycle_expected_access_mode,
        )
        self._sampling_cycle_connection_main_fd = connection_fd
        self.validate_storage()

    def _validate_connection_descriptors(
        self,
        binding: _StorageBinding,
        sidecar_identities: Mapping[str, tuple[int, int]],
    ) -> None:
        connection_main_fd = getattr(self, "_sampling_cycle_connection_main_fd", -1)
        if type(connection_main_fd) is not int or connection_main_fd < 0:
            _fail("sampling_cycle_db_connection_main_binding_mismatch")
        main_state = _connection_descriptor_state(
            connection_main_fd,
            code="sampling_cycle_db_connection_main_binding_mismatch",
        )
        _validate_connection_artifact_state(
            main_state,
            expected_identity=binding.main_identity,
            expected_owner_uid=binding.expected_owner_uid,
            role="main",
            expected_access_mode=self._sampling_cycle_expected_access_mode,
        )

        current_fds = _snapshot_process_file_descriptors()
        opened_fds = _added_descriptors(
            self._sampling_cycle_preconnect_fds,
            current_fds,
            require_stable_baseline=False,
        )
        observed_main = opened_fds.get(connection_main_fd)
        if observed_main != main_state:
            _fail("sampling_cycle_db_connection_main_binding_mismatch")

        observed_sidecars: dict[str, tuple[int, tuple[int, int]]] = {}
        for descriptor, state in opened_fds.items():
            if descriptor == connection_main_fd:
                continue
            matching_roles = [
                role
                for role, expected_identity in sidecar_identities.items()
                if state.identity == expected_identity
            ]
            if len(matching_roles) != 1:
                _fail("sampling_cycle_db_connection_sidecar_binding_mismatch")
            role = matching_roles[0]
            expected_identity = sidecar_identities[role]
            if role in observed_sidecars:
                _fail("sampling_cycle_db_connection_sidecar_binding_mismatch")
            _validate_connection_artifact_state(
                state,
                expected_identity=expected_identity,
                expected_owner_uid=binding.expected_owner_uid,
                role=role,
            )
            observed_sidecars[role] = (descriptor, expected_identity)
        self._sampling_cycle_connection_sidecar_fds = observed_sidecars

    def validate_storage(self) -> None:
        binding = getattr(self, "_sampling_cycle_binding", None)
        if not isinstance(binding, _StorageBinding):
            _fail("sampling_cycle_db_connection_binding_missing")
        sidecar_identities = binding.validate()
        self._validate_connection_descriptors(binding, sidecar_identities)

    def execute(self, sql: str, parameters: Any = (), /) -> sqlite3.Cursor:
        self.validate_storage()
        try:
            cursor = super().execute(sql, parameters)
        except BaseException:
            self.validate_storage()
            raise
        self.validate_storage()
        return cursor

    def commit(self) -> None:
        self.validate_storage()
        try:
            super().commit()
        except BaseException:
            self.validate_storage()
            raise
        self.validate_storage()

    def rollback(self) -> None:
        self.validate_storage()
        try:
            super().rollback()
        except BaseException:
            self.validate_storage()
            raise
        self.validate_storage()

    def close(self) -> None:
        binding = getattr(self, "_sampling_cycle_binding", None)
        proof_lock_held = bool(getattr(self, "_sampling_cycle_descriptor_proof_lock_held", False))
        failure: BaseException | None = None
        if isinstance(binding, _StorageBinding):
            try:
                self.validate_storage()
            except BaseException as exc:  # preserve the first integrity failure
                failure = exc
        try:
            super().close()
        except BaseException as exc:
            if failure is None:
                failure = exc
        if isinstance(binding, _StorageBinding):
            try:
                binding.validate()
            except BaseException as exc:
                if failure is None:
                    failure = exc
            finally:
                binding.release()
        if proof_lock_held:
            self._sampling_cycle_descriptor_proof_lock_held = False
            try:
                _SQLITE_DESCRIPTOR_PROOF_LOCK.release()
            except BaseException as exc:
                if failure is None:
                    failure = exc
        if failure is not None:
            raise failure


class SamplingCycleCoordinator:
    """SQLite phase machine and carry-head journal for paper sampling."""

    __slots__ = ("_db_identity", "_directory_identities", "_path")

    def __init__(self, db_path: Path) -> None:
        self._path = _exact_database_path(db_path)
        _require_secure_path_capabilities()
        initial_binding = _acquire_storage_binding(
            self.path,
            create_main=True,
            expected_identity=None,
            expected_directory_identities=None,
        )
        self._db_identity = initial_binding.main_identity
        self._directory_identities = initial_binding.directory_identities
        initial_binding.release()
        self._initialize()

    @property
    def path(self) -> Path:
        """Return the immutable lexical database path without resolving it."""

        return self._path

    @staticmethod
    def _configure(connection: sqlite3.Connection) -> None:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=60000")
        connection.execute("PRAGMA recursive_triggers=ON")

    def _open_writable(self) -> sqlite3.Connection:
        binding: _StorageBinding | None = None
        connection: _StorageGuardedSQLiteConnection | None = None
        _SQLITE_DESCRIPTOR_PROOF_LOCK.acquire()
        proof_lock_acquired = True
        try:
            binding = _acquire_storage_binding(
                self.path,
                create_main=False,
                expected_identity=self._db_identity,
                expected_directory_identities=self._directory_identities,
            )
            preconnect_fds = _snapshot_process_file_descriptors()
            connection = sqlite3.connect(
                self.path.as_uri() + "?mode=rw",
                uri=True,
                timeout=60.0,
                isolation_level=None,
                factory=_StorageGuardedSQLiteConnection,
            )
            connection.bind_storage(binding, preconnect_fds, writable=True)
            proof_lock_acquired = False
            self._configure(connection)
            mode = str(connection.execute("PRAGMA journal_mode=DELETE").fetchone()[0]).lower()
            if mode != "delete":
                _fail("sampling_cycle_db_delete_journal_required")
            connection.execute("PRAGMA synchronous=FULL")
            if int(connection.execute("PRAGMA synchronous").fetchone()[0]) != 2:
                _fail("sampling_cycle_db_synchronous_full_required")
            connection.validate_storage()
            return connection
        except BaseException:
            if connection is not None:
                connection_holds_lock = bool(
                    getattr(
                        connection,
                        "_sampling_cycle_descriptor_proof_lock_held",
                        False,
                    )
                )
                try:
                    connection.close()
                except BaseException:  # noqa: S110 - preserve primary fixed failure
                    pass
                if connection_holds_lock:
                    proof_lock_acquired = False
            if binding is not None and not binding.released:
                binding.release()
            if proof_lock_acquired:
                _SQLITE_DESCRIPTOR_PROOF_LOCK.release()
            raise

    def _open_readonly(self) -> sqlite3.Connection:
        binding: _StorageBinding | None = None
        connection: _StorageGuardedSQLiteConnection | None = None
        _SQLITE_DESCRIPTOR_PROOF_LOCK.acquire()
        proof_lock_acquired = True
        try:
            binding = _acquire_storage_binding(
                self.path,
                create_main=False,
                expected_identity=self._db_identity,
                expected_directory_identities=self._directory_identities,
            )
            preconnect_fds = _snapshot_process_file_descriptors()
            connection = sqlite3.connect(
                self.path.as_uri() + "?mode=ro",
                uri=True,
                timeout=60.0,
                isolation_level=None,
                factory=_StorageGuardedSQLiteConnection,
            )
            connection.bind_storage(binding, preconnect_fds, writable=False)
            proof_lock_acquired = False
            self._configure(connection)
            connection.execute("PRAGMA query_only=ON")
            connection.validate_storage()
            return connection
        except BaseException:
            if connection is not None:
                connection_holds_lock = bool(
                    getattr(
                        connection,
                        "_sampling_cycle_descriptor_proof_lock_held",
                        False,
                    )
                )
                try:
                    connection.close()
                except BaseException:  # noqa: S110 - preserve primary fixed failure
                    pass
                if connection_holds_lock:
                    proof_lock_acquired = False
            if binding is not None and not binding.released:
                binding.release()
            if proof_lock_acquired:
                _SQLITE_DESCRIPTOR_PROOF_LOCK.release()
            raise

    def _initialize(self) -> None:
        connection = self._open_writable()
        try:
            existing = connection.execute(
                """
                SELECT name FROM sqlite_master
                WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%'
                LIMIT 1
                """
            ).fetchone()
            if existing is None:
                if (
                    int(connection.execute("PRAGMA application_id").fetchone()[0]) != 0
                    or int(connection.execute("PRAGMA user_version").fetchone()[0]) != 0
                ):
                    _fail("sampling_cycle_db_foreign_pristine_header")
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(f"PRAGMA application_id={_SQLITE_APPLICATION_ID}")
                connection.execute(f"PRAGMA user_version={_SQLITE_USER_VERSION}")
                for ddl in _EXPECTED_DDL.values():
                    connection.execute(ddl)
                connection.execute(
                    """
                    INSERT INTO sampling_cycle_metadata(metadata_key, metadata_value)
                    VALUES
                        ('schema_version', ?),
                        ('schema_fingerprint', ?),
                        ('sqlite_ddl_sha256', ?)
                    """,
                    (
                        COORDINATOR_SCHEMA_VERSION,
                        _SCHEMA_FINGERPRINT,
                        _EXPECTED_DDL_SHA256,
                    ),
                )
                connection.commit()
            self._verify_database_locked(connection)
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()
        readback = self._open_readonly()
        try:
            readback.execute("BEGIN")
            self._verify_database_locked(readback)
            readback.commit()
        finally:
            readback.close()

    @staticmethod
    def _verify_database_locked(connection: sqlite3.Connection) -> None:
        try:
            SamplingCycleCoordinator._verify_database_contract_locked(connection)
        except SamplingCycleCoordinatorError:
            raise
        except (IndexError, KeyError, TypeError, ValueError, sqlite3.DatabaseError):
            raise SamplingCycleCoordinatorError(
                "sampling_cycle_db_schema_verification_failed"
            ) from None

    @staticmethod
    def _verify_database_contract_locked(connection: sqlite3.Connection) -> None:
        if isinstance(connection, _StorageGuardedSQLiteConnection):
            connection.validate_storage()
        if int(connection.execute("PRAGMA application_id").fetchone()[0]) != _SQLITE_APPLICATION_ID:
            _fail("sampling_cycle_db_application_id_invalid")
        if int(connection.execute("PRAGMA user_version").fetchone()[0]) != _SQLITE_USER_VERSION:
            _fail("sampling_cycle_db_user_version_invalid")
        if int(connection.execute("PRAGMA foreign_keys").fetchone()[0]) != 1:
            _fail("sampling_cycle_db_foreign_keys_disabled")
        check = connection.execute("PRAGMA quick_check").fetchone()
        if check is None or str(check[0]) != "ok":
            _fail("sampling_cycle_db_quick_check_failed")
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            _fail("sampling_cycle_db_foreign_key_check_failed")
        metadata = {
            str(row["metadata_key"]): str(row["metadata_value"])
            for row in connection.execute(
                "SELECT metadata_key, metadata_value FROM sampling_cycle_metadata"
            )
        }
        if metadata != {
            "schema_version": COORDINATOR_SCHEMA_VERSION,
            "schema_fingerprint": _SCHEMA_FINGERPRINT,
            "sqlite_ddl_sha256": _EXPECTED_DDL_SHA256,
        }:
            _fail("sampling_cycle_db_schema_metadata_invalid")
        schema_rows = connection.execute(
            """
            SELECT name, type, sql FROM sqlite_master
            WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%'
            ORDER BY name
            """
        ).fetchall()
        observed = {str(row["name"]): str(row["type"]) for row in schema_rows}
        observed_ddl = {
            str(row["name"]): " ".join(str(row["sql"]).split()).rstrip(";") for row in schema_rows
        }
        expected_ddl = {
            name: " ".join(sql.split()).rstrip(";") for name, sql in _EXPECTED_DDL.items()
        }
        if observed != _EXPECTED_SCHEMA_OBJECTS:
            _fail("sampling_cycle_db_schema_objects_invalid")
        if observed_ddl != expected_ddl:
            _fail("sampling_cycle_db_schema_ddl_invalid")
        for table, expected_columns in _EXPECTED_TABLE_COLUMNS.items():
            observed_columns = tuple(
                (
                    str(row["name"]),
                    str(row["type"]),
                    int(row["notnull"]),
                    int(row["pk"]),
                )
                for row in connection.execute(f"PRAGMA table_info({table})")
            )
            if observed_columns != expected_columns:
                _fail("sampling_cycle_db_schema_columns_invalid")

        table_contract = {
            str(row["name"]): (
                int(row["ncol"]),
                int(row["wr"]),
                int(row["strict"]),
            )
            for row in connection.execute("PRAGMA table_list")
            if str(row["name"]) in _EXPECTED_TABLE_COLUMNS
        }
        if table_contract != {
            "sampling_cycle_metadata": (2, 1, 1),
            "sampling_cycle_cycles": (11, 0, 1),
            "sampling_cycle_evidence": (9, 1, 1),
            "sampling_cycle_carry_heads": (5, 1, 1),
            "sampling_cycle_carry_head_advances": (9, 1, 1),
        }:
            _fail("sampling_cycle_db_table_options_invalid")

        unresolved_indexes = [
            row
            for row in connection.execute("PRAGMA index_list(sampling_cycle_cycles)")
            if str(row["name"]) == "sampling_cycle_one_unresolved_per_process"
        ]
        if (
            len(unresolved_indexes) != 1
            or int(unresolved_indexes[0]["unique"]) != 1
            or int(unresolved_indexes[0]["partial"]) != 1
            or tuple(
                (int(row["seqno"]), int(row["cid"]), str(row["name"]))
                for row in connection.execute(
                    "PRAGMA index_info(sampling_cycle_one_unresolved_per_process)"
                )
            )
            != ((0, 1, "process_instance_id"),)
        ):
            _fail("sampling_cycle_db_unresolved_index_invalid")

        expected_foreign_keys = {
            "sampling_cycle_evidence": (
                (
                    "sampling_cycle_cycles",
                    "cycle_identity_sha256",
                    "cycle_identity_sha256",
                    "RESTRICT",
                    "RESTRICT",
                    "NONE",
                ),
            ),
            "sampling_cycle_carry_head_advances": (
                (
                    "sampling_cycle_cycles",
                    "cycle_identity_sha256",
                    "cycle_identity_sha256",
                    "RESTRICT",
                    "RESTRICT",
                    "NONE",
                ),
            ),
        }
        for table, expected_rows in expected_foreign_keys.items():
            observed_rows = tuple(
                (
                    str(row["table"]),
                    str(row["from"]),
                    str(row["to"]),
                    str(row["on_update"]),
                    str(row["on_delete"]),
                    str(row["match"]),
                )
                for row in connection.execute(f"PRAGMA foreign_key_list({table})")
            )
            if observed_rows != expected_rows:
                _fail("sampling_cycle_db_foreign_key_contract_invalid")

    @staticmethod
    def _cycle_identity(cycle: Mapping[str, Any]) -> str:
        return _canonical_sha256(cycle)

    @staticmethod
    def _transition_seal(
        *,
        identity: str,
        revision: int,
        from_phase: str,
        to_phase: str,
        evidence_sha256: str,
        observed_at: str,
        previous_transition_sha256: str | None,
    ) -> dict[str, Any]:
        return {
            "schema_version": TRANSITION_SEAL_SCHEMA_VERSION,
            "cycle_identity_sha256": identity,
            "revision": revision,
            "from_phase": from_phase,
            "to_phase": to_phase,
            "evidence_sha256": evidence_sha256,
            "observed_at": observed_at,
            "previous_transition_sha256": previous_transition_sha256,
            "paper_only": True,
            "routes_to_live": False,
            "places_real_order": False,
        }

    def _read_head_locked(
        self, connection: sqlite3.Connection, process_instance_id: str
    ) -> tuple[SamplingCycleCarryHead, dict[str, Any], str]:
        row = connection.execute(
            """
            SELECT revision, head_json, head_sha256, updated_at
            FROM sampling_cycle_carry_heads WHERE process_instance_id = ?
            """,
            (process_instance_id,),
        ).fetchone()
        if row is None:
            _fail("sampling_cycle_carry_head_missing")
        if type(row["revision"]) is not int:
            _fail("sampling_cycle_carry_head_revision_storage_invalid")
        head_json = row["head_json"]
        material = _validated_head_material(_decode_canonical_object(head_json))
        head_sha = row["head_sha256"]
        if (
            not _is_sha256(head_sha)
            or _sha256_text(cast(str, head_json)) != head_sha
            or material["process_instance_id"] != process_instance_id
            or material["revision"] != row["revision"]
            or material["updated_at"] != row["updated_at"]
        ):
            _fail("sampling_cycle_carry_head_row_corrupt")

        advances = connection.execute(
            """
            SELECT head_revision, cycle_identity_sha256,
                   prior_head_json, prior_head_sha256,
                   next_head_json, next_head_sha256,
                   advanced_at, cycle_transition_sha256
            FROM sampling_cycle_carry_head_advances
            WHERE process_instance_id = ? ORDER BY head_revision
            """,
            (process_instance_id,),
        ).fetchall()
        if len(advances) != material["revision"]:
            _fail("sampling_cycle_carry_head_history_incomplete")
        complete_rows = connection.execute(
            """
            SELECT * FROM sampling_cycle_cycles
            WHERE process_instance_id = ? AND phase = ?
            ORDER BY prepared_at, cycle_identity_sha256
            """,
            (process_instance_id, PHASE_COMPLETE),
        ).fetchall()
        complete_by_identity = {
            str(cycle_row["cycle_identity_sha256"]): cycle_row for cycle_row in complete_rows
        }
        advance_identities = [str(row["cycle_identity_sha256"]) for row in advances]
        if (
            len(complete_by_identity) != len(complete_rows)
            or len(complete_rows) != len(advances)
            or set(complete_by_identity) != set(advance_identities)
            or len(set(advance_identities)) != len(advance_identities)
        ):
            _fail("sampling_cycle_carry_head_completion_set_mismatch")
        prior_json: str | None = None
        prior_sha: str | None = None
        for expected_revision, advance in enumerate(advances, start=1):
            if (
                type(advance["head_revision"]) is not int
                or advance["head_revision"] != expected_revision
            ):
                _fail("sampling_cycle_carry_head_history_revision_invalid")
            before_json = advance["prior_head_json"]
            after_json = advance["next_head_json"]
            before = _validated_head_material(_decode_canonical_object(before_json))
            after = _validated_head_material(_decode_canonical_object(after_json))
            cycle_identity = str(advance["cycle_identity_sha256"])
            if (
                not _is_sha256(advance["prior_head_sha256"])
                or not _is_sha256(advance["next_head_sha256"])
                or _sha256_text(cast(str, before_json)) != advance["prior_head_sha256"]
                or _sha256_text(cast(str, after_json)) != advance["next_head_sha256"]
                or before["process_instance_id"] != process_instance_id
                or after["process_instance_id"] != process_instance_id
                or before["revision"] != expected_revision - 1
                or after["revision"] != expected_revision
                or after["updated_at"] != advance["advanced_at"]
                or not _is_sha256(cycle_identity)
                or after["completed_cycle_identity_sha256"] != cycle_identity
                or not _is_sha256(advance["cycle_transition_sha256"])
            ):
                _fail("sampling_cycle_carry_head_history_corrupt")
            complete_row = complete_by_identity.get(cycle_identity)
            if complete_row is None:
                _fail("sampling_cycle_carry_head_completion_missing")
            complete_record = self._record_from_row_locked(connection, complete_row)
            completion_evidence = complete_record.transition_evidence[-1]
            before_head = SamplingCycleCarryHead(
                process_instance_id=process_instance_id,
                revision=cast(int, before["revision"]),
                carry=cast(float, before["carry"]),
                single_candidate_ordinary_credit=cast(
                    int, before["single_candidate_ordinary_credit"]
                ),
                completed_cycle_identity_sha256=cast(
                    str | None, before["completed_cycle_identity_sha256"]
                ),
                updated_at=cast(str, before["updated_at"]),
                head_sha256=cast(str, advance["prior_head_sha256"]),
            )
            expected_head_transition = self._completion_head_transition_material(
                cycle=complete_record.cycle,
                identity=cycle_identity,
                head=before_head,
                observed_at=cast(str, advance["advanced_at"]),
            )
            if (
                complete_record.phase != PHASE_COMPLETE
                or complete_record.revision != 4
                or complete_record.process_instance_id != process_instance_id
                or complete_record.updated_at != advance["advanced_at"]
                or complete_record.latest_transition_sha256 != advance["cycle_transition_sha256"]
                or completion_evidence["observed_at"] != advance["advanced_at"]
                or completion_evidence["carry_head_transition"] != expected_head_transition
                or before["carry"] != complete_record.cycle["carry_in"]
                or before["single_candidate_ordinary_credit"]
                != complete_record.cycle["single_candidate_ordinary_credit_in"]
                or after["carry"] != complete_record.cycle["carry_out"]
                or after["single_candidate_ordinary_credit"]
                != complete_record.cycle["single_candidate_ordinary_credit_out"]
                or _time_value(cast(str, before["updated_at"]))
                > _time_value(complete_record.prepared_at)
                or after["updated_at"] != complete_record.updated_at
            ):
                _fail("sampling_cycle_carry_head_cycle_binding_invalid")
            if expected_revision > 1 and (
                before_json != prior_json or advance["prior_head_sha256"] != prior_sha
            ):
                _fail("sampling_cycle_carry_head_history_aba_detected")
            prior_json = cast(str, after_json)
            prior_sha = cast(str, advance["next_head_sha256"])
        if advances and (head_json != prior_json or head_sha != prior_sha):
            _fail("sampling_cycle_carry_head_history_tip_mismatch")
        return (
            SamplingCycleCarryHead(
                process_instance_id=process_instance_id,
                revision=cast(int, material["revision"]),
                carry=cast(float, material["carry"]),
                single_candidate_ordinary_credit=cast(
                    int, material["single_candidate_ordinary_credit"]
                ),
                completed_cycle_identity_sha256=cast(
                    str | None, material["completed_cycle_identity_sha256"]
                ),
                updated_at=cast(str, material["updated_at"]),
                head_sha256=cast(str, head_sha),
            ),
            material,
            cast(str, head_json),
        )

    def _record_from_row_locked(
        self, connection: sqlite3.Connection, row: sqlite3.Row
    ) -> SamplingCycleRecord:
        cycle_json = row["cycle_json"]
        cycle = _validated_cycle(_decode_canonical_object(cycle_json))
        identity = row["cycle_identity_sha256"]
        revision = row["revision"]
        phase = row["phase"]
        if (
            type(revision) is not int
            or revision < 0
            or revision >= len(SAMPLING_CYCLE_PHASES)
            or phase != SAMPLING_CYCLE_PHASES[revision]
            or not _is_sha256(identity)
            or _sha256_text(cast(str, cycle_json)) != identity
            or row["cycle_sha256"] != identity
            or row["process_instance_id"] != cycle["process_instance_id"]
            or row["cycle_id"] != cycle["cycle_id"]
            or row["plan_instance_id"] != cycle["plan_instance_id"]
        ):
            _fail("sampling_cycle_cycle_row_corrupt")
        prepared_at = _canonical_time(row["prepared_at"], "sampling_cycle_prepared_time_invalid")
        updated_at = _canonical_time(row["updated_at"], "sampling_cycle_updated_time_invalid")
        if _time_value(updated_at) < _time_value(prepared_at):
            _fail("sampling_cycle_cycle_time_regressed")

        evidence_rows = connection.execute(
            """
            SELECT revision, from_phase, to_phase, evidence_json,
                   evidence_sha256, observed_at,
                   previous_transition_sha256, transition_sha256
            FROM sampling_cycle_evidence
            WHERE cycle_identity_sha256 = ? ORDER BY revision
            """,
            (identity,),
        ).fetchall()
        if len(evidence_rows) != revision:
            _fail("sampling_cycle_transition_history_incomplete")
        previous_transition: str | None = None
        previous_time = prepared_at
        evidence_history: list[dict[str, Any]] = []
        for expected_revision, evidence_row in enumerate(evidence_rows, start=1):
            if type(evidence_row["revision"]) is not int:
                _fail("sampling_cycle_transition_revision_storage_invalid")
            evidence_json = evidence_row["evidence_json"]
            evidence = _decode_canonical_object(evidence_json)
            evidence_sha = evidence_row["evidence_sha256"]
            observed_at = _canonical_time(
                evidence_row["observed_at"], "sampling_cycle_evidence_time_invalid"
            )
            from_phase = SAMPLING_CYCLE_PHASES[expected_revision - 1]
            to_phase = SAMPLING_CYCLE_PHASES[expected_revision]
            if (
                evidence_row["revision"] != expected_revision
                or evidence_row["from_phase"] != from_phase
                or evidence_row["to_phase"] != to_phase
                or not _is_sha256(evidence_sha)
                or _sha256_text(cast(str, evidence_json)) != evidence_sha
                or evidence.get("cycle_identity_sha256") != identity
                or evidence.get("expected_phase") != from_phase
                or evidence.get("expected_revision") != expected_revision - 1
                or evidence.get("transition_to") != to_phase
                or evidence.get("observed_at") != observed_at
                or evidence_row["previous_transition_sha256"] != previous_transition
                or _time_value(observed_at) < _time_value(previous_time)
            ):
                _fail("sampling_cycle_transition_history_corrupt")
            self._validate_evidence_semantics(
                evidence,
                cycle=cycle,
                identity=cast(str, identity),
                target=to_phase,
                prior_evidence=evidence_history,
                head=None,
            )
            transition = self._transition_seal(
                identity=cast(str, identity),
                revision=expected_revision,
                from_phase=from_phase,
                to_phase=to_phase,
                evidence_sha256=cast(str, evidence_sha),
                observed_at=observed_at,
                previous_transition_sha256=previous_transition,
            )
            transition_sha = _canonical_sha256(transition)
            if evidence_row["transition_sha256"] != transition_sha:
                _fail("sampling_cycle_transition_seal_invalid")
            if to_phase == PHASE_COMPLETE:
                advance = connection.execute(
                    """
                    SELECT prior_head_sha256, next_head_sha256,
                           cycle_transition_sha256
                    FROM sampling_cycle_carry_head_advances
                    WHERE cycle_identity_sha256 = ?
                    """,
                    (identity,),
                ).fetchone()
                head_transition = evidence["carry_head_transition"]
                if (
                    advance is None
                    or type(head_transition) is not dict
                    or advance["prior_head_sha256"] != head_transition["prior_head_sha256"]
                    or advance["next_head_sha256"] != head_transition["next_head_sha256"]
                    or advance["cycle_transition_sha256"] != transition_sha
                ):
                    _fail("sampling_cycle_completion_head_binding_invalid")
            previous_transition = transition_sha
            previous_time = observed_at
            evidence_history.append(evidence)
        latest = row["latest_transition_sha256"]
        if (revision == 0 and latest is not None) or (
            revision > 0 and latest != previous_transition
        ):
            _fail("sampling_cycle_transition_tip_invalid")
        if updated_at != previous_time:
            _fail("sampling_cycle_transition_time_tip_invalid")
        return SamplingCycleRecord(
            cycle_identity_sha256=cast(str, identity),
            process_instance_id=cast(str, cycle["process_instance_id"]),
            cycle_id=cast(str, cycle["cycle_id"]),
            plan_instance_id=cast(str, cycle["plan_instance_id"]),
            phase=cast(str, phase),
            revision=revision,
            cycle=deepcopy(cycle),
            prepared_at=prepared_at,
            updated_at=updated_at,
            latest_transition_sha256=cast(str | None, latest),
            transition_evidence=tuple(deepcopy(evidence_history)),
        )

    def _cycle_by_identity_locked(
        self, connection: sqlite3.Connection, identity: str
    ) -> SamplingCycleRecord:
        row = connection.execute(
            "SELECT * FROM sampling_cycle_cycles WHERE cycle_identity_sha256 = ?",
            (identity,),
        ).fetchone()
        if row is None:
            _fail("sampling_cycle_unknown")
        return self._record_from_row_locked(connection, row)

    def prepare_cycle(self, cycle: Mapping[str, Any], *, prepared_at: str) -> SamplingCycleRecord:
        """Seal a cycle without advancing its carry/ordinary-credit head."""

        validated = _validated_cycle(cycle)
        timestamp = _canonical_time(prepared_at, "sampling_cycle_prepared_time_invalid")
        cycle_json = _canonical_json(validated)
        identity = _sha256_text(cycle_json)
        process_id = cast(str, validated["process_instance_id"])
        cycle_id = cast(str, validated["cycle_id"])
        connection = self._open_writable()
        try:
            connection.execute("BEGIN IMMEDIATE")
            self._verify_database_locked(connection)
            existing_row = connection.execute(
                """
                SELECT * FROM sampling_cycle_cycles
                WHERE process_instance_id = ? AND cycle_id = ?
                """,
                (process_id, cycle_id),
            ).fetchone()
            if existing_row is not None:
                existing = self._record_from_row_locked(connection, existing_row)
                if (
                    existing.cycle_identity_sha256 != identity
                    or existing.cycle != validated
                    or existing.prepared_at != timestamp
                ):
                    _fail("sampling_cycle_conflicting_retry")
                connection.commit()
                return existing
            unresolved = connection.execute(
                """
                SELECT cycle_identity_sha256 FROM sampling_cycle_cycles
                WHERE process_instance_id = ? AND phase != ?
                """,
                (process_id, PHASE_COMPLETE),
            ).fetchone()
            if unresolved is not None:
                _fail("sampling_cycle_process_already_has_unresolved_cycle")

            head_row = connection.execute(
                """
                SELECT process_instance_id FROM sampling_cycle_carry_heads
                WHERE process_instance_id = ?
                """,
                (process_id,),
            ).fetchone()
            if head_row is None:
                head = _head_material(
                    process_instance_id=process_id,
                    revision=0,
                    carry=cast(float, validated["carry_in"]),
                    ordinary_credit=cast(int, validated["single_candidate_ordinary_credit_in"]),
                    completed_cycle_identity_sha256=None,
                    updated_at=timestamp,
                )
                head_json = _canonical_json(head)
                connection.execute(
                    """
                    INSERT INTO sampling_cycle_carry_heads(
                        process_instance_id, revision, head_json,
                        head_sha256, updated_at
                    ) VALUES (?, 0, ?, ?, ?)
                    """,
                    (process_id, head_json, _sha256_text(head_json), timestamp),
                )
            else:
                current_head, _head_material_row, _head_json = self._read_head_locked(
                    connection, process_id
                )
                if (
                    current_head.carry != validated["carry_in"]
                    or current_head.single_candidate_ordinary_credit
                    != validated["single_candidate_ordinary_credit_in"]
                ):
                    _fail("sampling_cycle_carry_head_input_mismatch")
                if _time_value(timestamp) < _time_value(current_head.updated_at):
                    _fail("sampling_cycle_prepared_time_before_carry_head")
                if current_head.revision >= MAX_RESOURCE_INTEGER:
                    _fail("sampling_cycle_carry_head_capacity_exhausted")

            connection.execute(
                """
                INSERT INTO sampling_cycle_cycles(
                    cycle_identity_sha256, process_instance_id, cycle_id,
                    plan_instance_id, phase, revision, cycle_json,
                    cycle_sha256, prepared_at, updated_at,
                    latest_transition_sha256
                ) VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?, ?, NULL)
                """,
                (
                    identity,
                    process_id,
                    cycle_id,
                    validated["plan_instance_id"],
                    PHASE_PREPARED,
                    cycle_json,
                    identity,
                    timestamp,
                    timestamp,
                ),
            )
            connection.commit()
        except SamplingCycleCoordinatorError:
            if connection.in_transaction:
                connection.rollback()
            raise
        except sqlite3.IntegrityError:
            if connection.in_transaction:
                connection.rollback()
            raise SamplingCycleCoordinatorError("sampling_cycle_concurrent_conflict") from None
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()
        readback = self.get_cycle(identity)
        if readback.cycle != validated or readback.prepared_at != timestamp:
            _fail("sampling_cycle_prepare_readback_mismatch")
        return readback

    @staticmethod
    def _validated_publications(
        evidence: dict[str, Any],
        *,
        selected_hashes: list[str],
        target: str,
        zero: bool,
    ) -> list[dict[str, Any]]:
        records = evidence.get("publication_records")
        count = _strict_int(evidence.get("publication_record_count"))
        if type(records) is not list or count is None or count != len(records):
            _fail("sampling_cycle_publication_records_invalid")
        publication_rows = records
        expected_status = (
            "COMMIT_UNKNOWN" if target == PHASE_PUBLICATION_COMMIT_UNKNOWN else "READBACK_VERIFIED"
        )
        expected_state = expected_status
        if zero:
            expected_state = (
                "VACUOUS_NO_PUBLICATION_ATTEMPTED"
                if target == PHASE_PUBLICATION_COMMIT_UNKNOWN
                else "VACUOUS_NO_PUBLICATION_REQUIRED"
            )
            if publication_rows or evidence.get("publication_set_sha256") is not None:
                _fail("sampling_cycle_zero_publication_evidence_not_vacuous")
        publication_hashes: list[str] = []
        keys: list[str] = []
        validated: list[dict[str, Any]] = []
        for record in publication_rows:
            if type(record) is not dict:
                _fail("sampling_cycle_publication_record_invalid")
            _require_exact_fields(
                record,
                _PUBLICATION_RECORD_FIELDS,
                "sampling_cycle_publication_record_shape_invalid",
            )
            receipt_hash = record.get("receipt_hash")
            publication_key = record.get("publication_key")
            if not _is_sha256(receipt_hash) or not _is_sha256(record.get("payload_sha256")):
                _fail("sampling_cycle_publication_record_hash_invalid")
            if (
                type(publication_key) is not str
                or _SAFE_PUBLICATION_KEY_RE.fullmatch(publication_key) is None
            ):
                _fail("sampling_cycle_publication_key_invalid")
            if record.get("publication_status") != expected_status:
                _fail("sampling_cycle_publication_status_invalid")
            publication_hashes.append(cast(str, receipt_hash))
            keys.append(publication_key)
            validated.append(record)
        if publication_hashes != selected_hashes or len(keys) != len(set(keys)):
            _fail("sampling_cycle_publication_membership_invalid")
        if evidence.get("publication_state") != expected_state:
            _fail("sampling_cycle_publication_state_invalid")
        expected_digest = None if zero else _canonical_sha256(validated)
        if evidence.get("publication_set_sha256") != expected_digest:
            _fail("sampling_cycle_publication_set_digest_invalid")
        return validated

    @staticmethod
    def _validated_lifecycles(
        evidence: dict[str, Any],
        *,
        selected_hashes: list[str],
        target: str,
        zero: bool,
    ) -> list[dict[str, Any]]:
        records = evidence.get("lifecycle_records")
        count = _strict_int(evidence.get("lifecycle_record_count"))
        if type(records) is not list or count is None or count != len(records):
            _fail("sampling_cycle_lifecycle_records_invalid")
        lifecycle_rows = records
        needs_lifecycle = target in {PHASE_LIFECYCLE_VERIFIED, PHASE_COMPLETE}
        if not needs_lifecycle:
            if lifecycle_rows or evidence.get("lifecycle_set_sha256") is not None:
                _fail("sampling_cycle_lifecycle_evidence_premature")
            if evidence.get("lifecycle_state") != "NOT_YET_VERIFIED":
                _fail("sampling_cycle_lifecycle_state_invalid")
            return []
        if zero:
            if lifecycle_rows or evidence.get("lifecycle_set_sha256") is not None:
                _fail("sampling_cycle_zero_lifecycle_evidence_not_vacuous")
            if evidence.get("lifecycle_state") != "VACUOUS_NO_LIFECYCLE_REQUIRED":
                _fail("sampling_cycle_lifecycle_state_invalid")
            return []
        receipt_hashes: list[str] = []
        validated: list[dict[str, Any]] = []
        for record in lifecycle_rows:
            if type(record) is not dict:
                _fail("sampling_cycle_lifecycle_record_invalid")
            _require_exact_fields(
                record,
                _LIFECYCLE_RECORD_FIELDS,
                "sampling_cycle_lifecycle_record_shape_invalid",
            )
            if not _is_sha256(record.get("receipt_hash")) or not _is_sha256(
                record.get("lifecycle_receipt_sha256")
            ):
                _fail("sampling_cycle_lifecycle_record_hash_invalid")
            if record.get("terminal_disposition") not in _TERMINAL_DISPOSITIONS:
                _fail("sampling_cycle_lifecycle_terminal_disposition_invalid")
            receipt_hashes.append(cast(str, record["receipt_hash"]))
            validated.append(record)
        if receipt_hashes != selected_hashes:
            _fail("sampling_cycle_lifecycle_membership_invalid")
        if evidence.get("lifecycle_state") != "TERMINAL_LIFECYCLE_VERIFIED":
            _fail("sampling_cycle_lifecycle_state_invalid")
        if evidence.get("lifecycle_set_sha256") != _canonical_sha256(validated):
            _fail("sampling_cycle_lifecycle_set_digest_invalid")
        return validated

    def _validate_evidence_semantics(
        self,
        evidence: dict[str, Any],
        *,
        cycle: dict[str, Any],
        identity: str,
        target: str,
        prior_evidence: list[dict[str, Any]],
        head: SamplingCycleCarryHead | None,
    ) -> None:
        _require_exact_fields(evidence, _EVIDENCE_FIELDS, "sampling_cycle_evidence_shape_invalid")
        expected_phase = _expected_phase_for(target)
        expected_revision = SAMPLING_CYCLE_PHASES.index(expected_phase)
        if (
            evidence.get("schema_version") != TRANSITION_EVIDENCE_SCHEMA_VERSION
            or evidence.get("cycle_identity_sha256") != identity
            or evidence.get("transition_to") != target
            or evidence.get("expected_phase") != expected_phase
            or _strict_int(evidence.get("expected_revision")) != expected_revision
        ):
            _fail("sampling_cycle_evidence_transition_binding_invalid")
        _validate_safety_flags(evidence, "sampling_cycle_evidence_paper_safety_invalid")
        if evidence.get("blind_republish_allowed") is not False:
            _fail("sampling_cycle_blind_republish_forbidden")
        observed_at = _canonical_time(
            evidence.get("observed_at"), "sampling_cycle_evidence_time_invalid"
        )
        evidence["observed_at"] = observed_at
        selected = cast(list[dict[str, Any]], cycle["selected_receipts"])
        selected_hashes = [cast(str, record["receipt_hash"]) for record in selected]
        count = _strict_int(evidence.get("selected_receipt_count"))
        zero = not selected
        if count != len(selected) or evidence.get("zero_selected_vacuous") is not zero:
            _fail("sampling_cycle_evidence_selected_count_invalid")
        publications = self._validated_publications(
            evidence,
            selected_hashes=selected_hashes,
            target=target,
            zero=zero,
        )
        lifecycles = self._validated_lifecycles(
            evidence,
            selected_hashes=selected_hashes,
            target=target,
            zero=zero,
        )
        if prior_evidence:
            unknown_publications = cast(
                list[dict[str, Any]], prior_evidence[0]["publication_records"]
            )
            if [_publication_identity(row) for row in publications] != [
                _publication_identity(row) for row in unknown_publications
            ]:
                _fail("sampling_cycle_publication_readback_binding_mismatch")
        if target == PHASE_COMPLETE:
            if len(prior_evidence) < 3 or lifecycles != prior_evidence[2]["lifecycle_records"]:
                _fail("sampling_cycle_lifecycle_completion_binding_mismatch")
            transition = evidence.get("carry_head_transition")
            if type(transition) is not dict:
                _fail("sampling_cycle_carry_head_transition_missing")
            transition_row = cast(dict[str, Any], transition)
            _require_exact_fields(
                transition_row,
                _HEAD_TRANSITION_FIELDS,
                "sampling_cycle_carry_head_transition_shape_invalid",
            )
            _validate_safety_flags(
                transition_row, "sampling_cycle_carry_head_transition_paper_safety_invalid"
            )
            if transition_row.get("schema_version") != CARRY_HEAD_TRANSITION_SCHEMA_VERSION:
                _fail("sampling_cycle_carry_head_transition_schema_invalid")
            if head is not None:
                expected = self._completion_head_transition_material(
                    cycle=cycle,
                    identity=identity,
                    head=head,
                    observed_at=observed_at,
                )
                if transition_row != expected:
                    _fail("sampling_cycle_carry_head_transition_binding_invalid")
            else:
                if (
                    transition_row.get("process_instance_id") != cycle["process_instance_id"]
                    or _strict_int(transition_row.get("expected_head_revision")) is None
                    or _strict_int(transition_row.get("next_head_revision"))
                    != cast(int, transition_row["expected_head_revision"]) + 1
                    or not _is_sha256(transition_row.get("prior_head_sha256"))
                    or not _is_sha256(transition_row.get("next_head_sha256"))
                    or transition_row.get("carry_in") != cycle["carry_in"]
                    or transition_row.get("carry_out") != cycle["carry_out"]
                    or transition_row.get("single_candidate_ordinary_credit_in")
                    != cycle["single_candidate_ordinary_credit_in"]
                    or transition_row.get("single_candidate_ordinary_credit_out")
                    != cycle["single_candidate_ordinary_credit_out"]
                ):
                    _fail("sampling_cycle_carry_head_transition_binding_invalid")
        elif evidence.get("carry_head_transition") is not None:
            _fail("sampling_cycle_carry_head_transition_premature")

    @staticmethod
    def _completion_head_transition_material(
        *,
        cycle: dict[str, Any],
        identity: str,
        head: SamplingCycleCarryHead,
        observed_at: str,
    ) -> dict[str, Any]:
        next_material = _head_material(
            process_instance_id=head.process_instance_id,
            revision=head.revision + 1,
            carry=cast(float, cycle["carry_out"]),
            ordinary_credit=cast(int, cycle["single_candidate_ordinary_credit_out"]),
            completed_cycle_identity_sha256=identity,
            updated_at=observed_at,
        )
        return {
            "schema_version": CARRY_HEAD_TRANSITION_SCHEMA_VERSION,
            "process_instance_id": head.process_instance_id,
            "expected_head_revision": head.revision,
            "prior_head_sha256": head.head_sha256,
            "next_head_revision": head.revision + 1,
            "carry_in": cycle["carry_in"],
            "carry_out": cycle["carry_out"],
            "single_candidate_ordinary_credit_in": cycle["single_candidate_ordinary_credit_in"],
            "single_candidate_ordinary_credit_out": cycle["single_candidate_ordinary_credit_out"],
            "next_head_sha256": _canonical_sha256(next_material),
            "paper_only": True,
            "routes_to_live": False,
            "places_real_order": False,
        }

    def completion_head_transition(
        self, cycle_identity_sha256: str, *, observed_at: str
    ) -> dict[str, Any]:
        """Build the revision/hash CAS binding required by ``complete``."""

        if not _is_sha256(cycle_identity_sha256):
            _fail("sampling_cycle_identity_invalid")
        timestamp = _canonical_time(observed_at, "sampling_cycle_evidence_time_invalid")
        connection = self._open_readonly()
        try:
            connection.execute("BEGIN")
            self._verify_database_locked(connection)
            cycle_record = self._cycle_by_identity_locked(connection, cycle_identity_sha256)
            if cycle_record.phase != PHASE_LIFECYCLE_VERIFIED:
                _fail("sampling_cycle_completion_phase_invalid")
            if _time_value(timestamp) < _time_value(cycle_record.updated_at):
                _fail("sampling_cycle_evidence_time_regressed")
            head, _material, _head_json = self._read_head_locked(
                connection, cycle_record.process_instance_id
            )
            if (
                head.carry != cycle_record.cycle["carry_in"]
                or head.single_candidate_ordinary_credit
                != cycle_record.cycle["single_candidate_ordinary_credit_in"]
            ):
                _fail("sampling_cycle_completion_head_input_mismatch")
            result = self._completion_head_transition_material(
                cycle=cycle_record.cycle,
                identity=cycle_identity_sha256,
                head=head,
                observed_at=timestamp,
            )
            connection.commit()
            return deepcopy(result)
        finally:
            connection.close()

    def _transition(
        self, identity: str, evidence_value: Mapping[str, Any], *, target: str
    ) -> SamplingCycleRecord:
        if not _is_sha256(identity):
            _fail("sampling_cycle_identity_invalid")
        frozen = _freeze_json(evidence_value)
        if type(frozen) is not dict:
            _fail("sampling_cycle_evidence_mapping_invalid")
        evidence = cast(dict[str, Any], frozen)
        expected_phase = _expected_phase_for(target)
        expected_revision = SAMPLING_CYCLE_PHASES.index(expected_phase)
        connection = self._open_writable()
        try:
            connection.execute("BEGIN IMMEDIATE")
            self._verify_database_locked(connection)
            cycle_record = self._cycle_by_identity_locked(connection, identity)
            current_index = SAMPLING_CYCLE_PHASES.index(cycle_record.phase)
            target_index = SAMPLING_CYCLE_PHASES.index(target)
            if current_index > target_index:
                _fail("sampling_cycle_transition_replay_rejected")
            if current_index == target_index:
                persisted = cycle_record.transition_evidence[target_index - 1]
                normalized_retry = deepcopy(evidence)
                if "observed_at" in normalized_retry:
                    normalized_retry["observed_at"] = _canonical_time(
                        normalized_retry["observed_at"],
                        "sampling_cycle_evidence_time_invalid",
                    )
                if normalized_retry != persisted:
                    _fail("sampling_cycle_conflicting_transition_retry")
                connection.commit()
                return cycle_record
            if cycle_record.phase != expected_phase or cycle_record.revision != expected_revision:
                _fail("sampling_cycle_transition_skip_rejected")
            head: SamplingCycleCarryHead | None = None
            head_material: dict[str, Any] | None = None
            head_json: str | None = None
            if target == PHASE_COMPLETE:
                head, head_material, head_json = self._read_head_locked(
                    connection, cycle_record.process_instance_id
                )
                if (
                    head.carry != cycle_record.cycle["carry_in"]
                    or head.single_candidate_ordinary_credit
                    != cycle_record.cycle["single_candidate_ordinary_credit_in"]
                ):
                    _fail("sampling_cycle_completion_head_input_mismatch")
            self._validate_evidence_semantics(
                evidence,
                cycle=cycle_record.cycle,
                identity=identity,
                target=target,
                prior_evidence=list(cycle_record.transition_evidence),
                head=head,
            )
            observed_at = cast(str, evidence["observed_at"])
            if _time_value(observed_at) < _time_value(cycle_record.updated_at):
                _fail("sampling_cycle_evidence_time_regressed")
            evidence_json = _canonical_json(evidence)
            evidence_sha = _sha256_text(evidence_json)
            next_revision = expected_revision + 1
            seal = self._transition_seal(
                identity=identity,
                revision=next_revision,
                from_phase=expected_phase,
                to_phase=target,
                evidence_sha256=evidence_sha,
                observed_at=observed_at,
                previous_transition_sha256=cycle_record.latest_transition_sha256,
            )
            transition_sha = _canonical_sha256(seal)
            connection.execute(
                """
                INSERT INTO sampling_cycle_evidence(
                    cycle_identity_sha256, revision, from_phase, to_phase,
                    evidence_json, evidence_sha256, observed_at,
                    previous_transition_sha256, transition_sha256
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    identity,
                    next_revision,
                    expected_phase,
                    target,
                    evidence_json,
                    evidence_sha,
                    observed_at,
                    cycle_record.latest_transition_sha256,
                    transition_sha,
                ),
            )
            updated = connection.execute(
                """
                UPDATE sampling_cycle_cycles
                SET phase = ?, revision = ?, updated_at = ?,
                    latest_transition_sha256 = ?
                WHERE cycle_identity_sha256 = ? AND phase = ? AND revision = ?
                """,
                (
                    target,
                    next_revision,
                    observed_at,
                    transition_sha,
                    identity,
                    expected_phase,
                    expected_revision,
                ),
            )
            if updated.rowcount != 1:
                _fail("sampling_cycle_transition_compare_and_swap_failed")
            if target == PHASE_COMPLETE:
                assert head is not None and head_material is not None and head_json is not None
                head_transition = cast(dict[str, Any], evidence["carry_head_transition"])
                next_material = _head_material(
                    process_instance_id=head.process_instance_id,
                    revision=head.revision + 1,
                    carry=cast(float, cycle_record.cycle["carry_out"]),
                    ordinary_credit=cast(
                        int,
                        cycle_record.cycle["single_candidate_ordinary_credit_out"],
                    ),
                    completed_cycle_identity_sha256=identity,
                    updated_at=observed_at,
                )
                next_json = _canonical_json(next_material)
                next_sha = _sha256_text(next_json)
                if next_sha != head_transition["next_head_sha256"]:
                    _fail("sampling_cycle_completion_head_hash_mismatch")
                connection.execute(
                    """
                    INSERT INTO sampling_cycle_carry_head_advances(
                        process_instance_id, head_revision,
                        cycle_identity_sha256, prior_head_json,
                        prior_head_sha256, next_head_json, next_head_sha256,
                        advanced_at, cycle_transition_sha256
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        head.process_instance_id,
                        head.revision + 1,
                        identity,
                        head_json,
                        head.head_sha256,
                        next_json,
                        next_sha,
                        observed_at,
                        transition_sha,
                    ),
                )
                head_update = connection.execute(
                    """
                    UPDATE sampling_cycle_carry_heads
                    SET revision = ?, head_json = ?, head_sha256 = ?, updated_at = ?
                    WHERE process_instance_id = ? AND revision = ? AND head_sha256 = ?
                    """,
                    (
                        head.revision + 1,
                        next_json,
                        next_sha,
                        observed_at,
                        head.process_instance_id,
                        head.revision,
                        head.head_sha256,
                    ),
                )
                if head_update.rowcount != 1:
                    _fail("sampling_cycle_carry_head_compare_and_swap_failed")
            connection.commit()
        except SamplingCycleCoordinatorError:
            if connection.in_transaction:
                connection.rollback()
            raise
        except sqlite3.IntegrityError:
            if connection.in_transaction:
                connection.rollback()
            raise SamplingCycleCoordinatorError("sampling_cycle_concurrent_conflict") from None
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()
        readback = self.get_cycle(identity)
        if readback.phase != target or readback.transition_evidence[-1] != evidence:
            _fail("sampling_cycle_transition_readback_mismatch")
        if target == PHASE_COMPLETE:
            head_readback = self.carry_head(readback.process_instance_id)
            transition = cast(dict[str, Any], evidence["carry_head_transition"])
            if (
                head_readback.head_sha256 != transition["next_head_sha256"]
                or head_readback.completed_cycle_identity_sha256 != identity
            ):
                _fail("sampling_cycle_completion_readback_mismatch")
        return readback

    def mark_publication_commit_unknown(
        self, cycle_identity_sha256: str, evidence: Mapping[str, Any]
    ) -> SamplingCycleRecord:
        """Fence an ambiguous external paper publication; no retry is authorized."""

        return self._transition(
            cycle_identity_sha256,
            evidence,
            target=PHASE_PUBLICATION_COMMIT_UNKNOWN,
        )

    def mark_publication_readback_verified(
        self, cycle_identity_sha256: str, evidence: Mapping[str, Any]
    ) -> SamplingCycleRecord:
        """Record exact key/payload readback for the previously ambiguous commit."""

        return self._transition(
            cycle_identity_sha256,
            evidence,
            target=PHASE_PUBLICATION_READBACK_VERIFIED,
        )

    def mark_lifecycle_verified(
        self, cycle_identity_sha256: str, evidence: Mapping[str, Any]
    ) -> SamplingCycleRecord:
        """Record exact terminal lifecycle membership without appending events."""

        return self._transition(
            cycle_identity_sha256,
            evidence,
            target=PHASE_LIFECYCLE_VERIFIED,
        )

    def complete(
        self, cycle_identity_sha256: str, evidence: Mapping[str, Any]
    ) -> SamplingCycleRecord:
        """Atomically complete the evidenced cycle and advance its carry head once."""

        return self._transition(cycle_identity_sha256, evidence, target=PHASE_COMPLETE)

    def get_cycle(self, cycle_identity_sha256: str) -> SamplingCycleRecord:
        if not _is_sha256(cycle_identity_sha256):
            _fail("sampling_cycle_identity_invalid")
        connection = self._open_readonly()
        try:
            connection.execute("BEGIN")
            self._verify_database_locked(connection)
            record = self._cycle_by_identity_locked(connection, cycle_identity_sha256)
            connection.commit()
            return record
        finally:
            connection.close()

    def unresolved_for_process(self, process_instance_id: str) -> SamplingCycleRecord | None:
        if (
            type(process_instance_id) is not str
            or _SAFE_OPAQUE_ID_RE.fullmatch(process_instance_id) is None
        ):
            _fail("sampling_cycle_process_instance_id_invalid")
        connection = self._open_readonly()
        try:
            connection.execute("BEGIN")
            self._verify_database_locked(connection)
            rows = connection.execute(
                """
                SELECT * FROM sampling_cycle_cycles
                WHERE process_instance_id = ? AND phase != ?
                """,
                (process_instance_id, PHASE_COMPLETE),
            ).fetchall()
            if len(rows) > 1:
                _fail("sampling_cycle_multiple_unresolved_cycles_corrupt")
            result = self._record_from_row_locked(connection, rows[0]) if rows else None
            connection.commit()
            return result
        finally:
            connection.close()

    def carry_head(self, process_instance_id: str) -> SamplingCycleCarryHead:
        if (
            type(process_instance_id) is not str
            or _SAFE_OPAQUE_ID_RE.fullmatch(process_instance_id) is None
        ):
            _fail("sampling_cycle_process_instance_id_invalid")
        connection = self._open_readonly()
        try:
            connection.execute("BEGIN")
            self._verify_database_locked(connection)
            head, _material, _head_json = self._read_head_locked(connection, process_instance_id)
            connection.commit()
            return head
        finally:
            connection.close()


__all__ = [
    "CARRY_HEAD_SCHEMA_VERSION",
    "CARRY_HEAD_TRANSITION_SCHEMA_VERSION",
    "COORDINATOR_SCHEMA_VERSION",
    "CYCLE_PREPARATION_SCHEMA_VERSION",
    "PHASE_COMPLETE",
    "PHASE_LIFECYCLE_VERIFIED",
    "PHASE_PREPARED",
    "PHASE_PUBLICATION_COMMIT_UNKNOWN",
    "PHASE_PUBLICATION_READBACK_VERIFIED",
    "SAMPLING_CYCLE_PHASES",
    "TRANSITION_EVIDENCE_SCHEMA_VERSION",
    "SamplingCycleCarryHead",
    "SamplingCycleCoordinator",
    "SamplingCycleCoordinatorError",
    "SamplingCycleRecord",
]
