"""Sealed lineage inventory for one profiled supervised checkpoint candidate.

This module is an in-memory serialization and evidence boundary, not a trainer,
checkpoint writer, model publisher, or serving path.  It accepts only the exact
factory results produced by ``authenticated_profiled_optimizer_corpus_v1``:
two independently materialized, equal before/after corpus snapshots and their
sealed supervised-execution authorization.  All three inputs are revalidated,
including their process-private factory seals, before any candidate bytes are
built.

The candidate binds the fixed manifest and external witness completion, every
ordered sample/label/tensor/projection/target identity, the complete optimizer
input inventory, exact before/after model and optimizer tensor bytes, optimizer
implementation/configuration/environment artifacts, and strict retrospective
clocks.  The binary envelope is deterministic and content addressed.  It is not
a framework checkpoint and is deliberately not written to disk here.

Important limitation: this contract proves byte identity, lineage equality,
and clock ordering for supplied artifacts.  It does not independently observe
GPU execution or prove that an optimizer algorithm produced the after-state.
No checkpoint write, model publication, prediction, serving, PPO, paper/live
trading, exchange access, deployment, order, execution, or runtime authority is
created by this module.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
import secrets
import struct
from dataclasses import dataclass, field
from dataclasses import fields as dataclass_fields
from datetime import UTC, datetime
from typing import Any, Final, NoReturn, cast

from v2.backend.app.services.native_trainer.authenticated_profiled_optimizer_corpus_v1 import (
    AuthenticatedProfiledOptimizerCorpusV1,
    AuthenticatedProfiledOptimizerCorpusV1Error,
    AuthenticatedProfiledSupervisedOptimizerExecutionAuthorizationV1,
    validate_authenticated_profiled_optimizer_corpus_inventory_equality_v1,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_ledger import (
    stable_sha256,
)

PROFILED_SUPERVISED_TENSOR_STATE_ITEM_V1_SCHEMA_VERSION: Final = (
    "profiled_supervised_tensor_state_item_v1"
)
PROFILED_SUPERVISED_OPTIMIZATION_STATE_SNAPSHOT_V1_SCHEMA_VERSION: Final = (
    "profiled_supervised_optimization_state_snapshot_v1"
)
PROFILED_SUPERVISED_CHECKPOINT_INVENTORY_V1_SCHEMA_VERSION: Final = (
    "profiled_supervised_checkpoint_inventory_v1"
)
PROFILED_SUPERVISED_CHECKPOINT_BINARY_V1_SCHEMA_VERSION: Final = (
    "profiled_supervised_checkpoint_binary_envelope_v1"
)
PROFILED_SUPERVISED_CHECKPOINT_BINARY_MAGIC: Final = b"APSCIV1\0"
PROFILED_SUPERVISED_CHECKPOINT_STATUS: Final = (
    "IN_MEMORY_CONTENT_ADDRESSED_CANDIDATE_ONLY_NO_WRITE_OR_RUNTIME_AUTHORITY"
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_STATE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,255}$", re.ASCII)
_STATE_STAGES: Final = frozenset({"BEFORE_OPTIMIZATION", "AFTER_OPTIMIZATION"})
_STATE_ROLES: Final = frozenset({"MODEL", "OPTIMIZER"})
_DTYPE_BYTE_WIDTH: Final = {
    "bool": 1,
    "int8": 1,
    "uint8": 1,
    "int16": 2,
    "uint16": 2,
    "bfloat16": 2,
    "float16": 2,
    "int32": 4,
    "uint32": 4,
    "float32": 4,
    "int64": 8,
    "uint64": 8,
    "float64": 8,
}

# Serialization/resource constraints only.  None is a market, sample, edge,
# performance, risk, leverage, margin, or training-quality threshold.
MAX_PROFILED_STATE_ITEMS: Final = 1_000_000
MAX_PROFILED_STATE_ITEM_BYTES: Final = 2 * 1024 * 1024 * 1024
MAX_PROFILED_IMPLEMENTATION_ARTIFACT_BYTES: Final = 256 * 1024 * 1024
MAX_PROFILED_CONFIGURATION_ARTIFACT_BYTES: Final = 16 * 1024 * 1024
MAX_PROFILED_ENVIRONMENT_ARTIFACT_BYTES: Final = 16 * 1024 * 1024
MAX_PROFILED_CHECKPOINT_HEADER_BYTES: Final = 64 * 1024 * 1024

_TENSOR_ITEM_TOKEN = object()
_STATE_SNAPSHOT_TOKEN = object()
_CHECKPOINT_INVENTORY_TOKEN = object()
_FACTORY_SEAL_TOKEN = object()
_FACTORY_SEAL_KEY = secrets.token_bytes(32)
_TENSOR_ITEM_SEAL_DOMAIN = b"profiled_supervised_tensor_state_item_factory_seal_v1"
_STATE_SNAPSHOT_SEAL_DOMAIN = b"profiled_supervised_state_snapshot_factory_seal_v1"
_CHECKPOINT_INVENTORY_SEAL_DOMAIN = b"profiled_supervised_checkpoint_inventory_factory_seal_v1"

_CHECKPOINT_IMPLEMENTATION_CONTRACT: Final = {
    "schema_version": "profiled_supervised_checkpoint_inventory_implementation_contract_v1",
    "input_contract": (
        "SEALED_EQUAL_AUTHENTICATED_PROFILED_CORPUS_BEFORE_AFTER_AND_EXECUTION_AUTHORIZATION"
    ),
    "state_encoding": "NAMED_DTYPE_SHAPE_LITTLE_ENDIAN_CONTIGUOUS_BYTES",
    "checkpoint_encoding": (
        "MAGIC_UINT64_BE_HEADER_LENGTH_CANONICAL_JSON_THEN_ORDERED_LENGTH_PREFIXED_FRAMES"
    ),
    "optimizer_lane": "OUTCOME_SUPERVISED_ONLY_NO_BEHAVIOR_POLICY_TERMS",
    "retrospective_execution_proof": False,
    "writes_files": False,
    "runtime_wired": False,
}
PROFILED_SUPERVISED_CHECKPOINT_IMPLEMENTATION_CONTRACT_SHA256: Final = stable_sha256(
    _CHECKPOINT_IMPLEMENTATION_CONTRACT
)

_AUTHORITY_FALSE: Final = {
    "checkpoint_write_authorized": False,
    "model_write_authorized": False,
    "prediction_authorized": False,
    "serving_authorized": False,
    "ppo_training_authorized": False,
    "paper_trading_authorized": False,
    "live_execution_authorized": False,
    "exchange_access_authorized": False,
    "deployment_authorized": False,
    "order_submission_authorized": False,
    "execution_authorized": False,
    "runtime_wired": False,
}


class ProfiledSupervisedCheckpointInventoryV1Error(RuntimeError):
    """A checkpoint input, state artifact, clock, or identity failed closed."""

    def __init__(self, *reasons: str) -> None:
        self.reasons = tuple(dict.fromkeys(str(reason) for reason in reasons))
        super().__init__(";".join(self.reasons))


def _fail(*reasons: str) -> NoReturn:
    raise ProfiledSupervisedCheckpointInventoryV1Error(*reasons) from None


def _canonical_bytes(value: object, *, reason: str) -> bytes:
    try:
        result = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii", errors="strict")
    except (OverflowError, RecursionError, TypeError, UnicodeEncodeError, ValueError) as exc:
        raise ProfiledSupervisedCheckpointInventoryV1Error(reason) from exc
    if not result or len(result) > MAX_PROFILED_CHECKPOINT_HEADER_BYTES:
        _fail(reason)
    return result


def _valid_sha256(value: object) -> bool:
    return type(value) is str and _SHA256_RE.fullmatch(value) is not None


def _clock(value: object, *, reason: str) -> datetime:
    if type(value) is not str or not value or value != value.strip():
        _fail(reason)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (OverflowError, ValueError):
        _fail(reason)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _fail(reason)
    normalized = parsed.astimezone(UTC)
    if normalized.isoformat(timespec="microseconds").replace("+00:00", "Z") != value:
        _fail(reason)
    return normalized


def _strict_canonical_json_object(raw: object, *, maximum: int, reason: str) -> bytes:
    if type(raw) is not bytes or not raw or len(raw) > maximum:
        _fail(reason)

    def reject_constant(value: str) -> NoReturn:
        _fail(f"{reason}:NONFINITE:{value}")

    def reject_duplicate(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                _fail(f"{reason}:DUPLICATE_KEY")
            result[key] = value
        return result

    try:
        decoded = raw.decode("ascii")
        value = json.loads(
            decoded,
            object_pairs_hook=reject_duplicate,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise ProfiledSupervisedCheckpointInventoryV1Error(reason) from exc
    if type(value) is not dict or _canonical_bytes(value, reason=reason) != raw:
        _fail(reason)
    return bytes(raw)


def _artifact_bytes(value: object, *, maximum: int, reason: str) -> bytes:
    if type(value) is not bytes or not value or len(value) > maximum:
        _fail(reason)
    return bytes(value)


def _seal_value(value: object) -> object:
    if type(value) is ProfiledSupervisedTensorStateItemV1:
        return {"tensor_state_identity_sha256": cast(Any, value).tensor_state_identity_sha256}
    if type(value) is ProfiledSupervisedOptimizationStateSnapshotV1:
        return {"state_snapshot_sha256": cast(Any, value).state_snapshot_sha256}
    if type(value) is AuthenticatedProfiledOptimizerCorpusV1:
        return {"corpus_contract_sha256": cast(Any, value).corpus_contract_sha256}
    if type(value) is AuthenticatedProfiledSupervisedOptimizerExecutionAuthorizationV1:
        return {"inventory_equality_sha256": cast(Any, value).inventory_equality_sha256}
    if type(value) is bytes:
        return {
            "byte_count": len(cast(bytes, value)),
            "sha256": hashlib.sha256(cast(bytes, value)).hexdigest(),
        }
    if type(value) is tuple:
        return [_seal_value(item) for item in cast(tuple[object, ...], value)]
    if value is None or type(value) in {str, int, float, bool}:
        return value
    _fail("PROFILED_CHECKPOINT_FACTORY_SEAL_MATERIAL_INVALID")


def _seal_material(value: object) -> dict[str, object]:
    try:
        items = dataclass_fields(value)
    except TypeError:
        _fail("PROFILED_CHECKPOINT_FACTORY_SEAL_MATERIAL_INVALID")
    return {
        item.name: _seal_value(getattr(value, item.name))
        for item in items
        if not item.name.startswith("_")
    }


class _FactorySeal:
    """Process-private one-time material binding for public dataclass results."""

    __slots__ = ("_digest", "_domain", "_owner_id")

    def __init__(self, *, domain: bytes, construction_token: object) -> None:
        if construction_token is not _FACTORY_SEAL_TOKEN or type(domain) is not bytes:
            _fail("PROFILED_CHECKPOINT_FACTORY_SEAL_CONSTRUCTION_FORBIDDEN")
        object.__setattr__(self, "_domain", bytes(domain))
        object.__setattr__(self, "_digest", None)
        object.__setattr__(self, "_owner_id", None)

    def __setattr__(self, _name: str, _value: object) -> NoReturn:
        _fail("PROFILED_CHECKPOINT_FACTORY_SEAL_IMMUTABLE")

    def validate_or_bind(
        self, *, domain: bytes, owner: object, material: object, reason: str
    ) -> None:
        if self._domain != domain:
            _fail(reason)
        expected = hmac.digest(
            _FACTORY_SEAL_KEY,
            domain + b"\0" + _canonical_bytes(material, reason=reason),
            "sha256",
        )
        current = self._digest
        owner_id = self._owner_id
        if current is None and owner_id is None:
            object.__setattr__(self, "_digest", expected)
            object.__setattr__(self, "_owner_id", id(owner))
        elif (
            type(current) is not bytes
            or type(owner_id) is not int
            or owner_id != id(owner)
            or not hmac.compare_digest(current, expected)
        ):
            _fail(reason)


def _require_factory_seal(
    value: object,
    *,
    domain: bytes,
    owner: object,
    material: object,
    reason: str,
) -> None:
    if type(value) is not _FactorySeal:
        _fail(reason)
    cast(_FactorySeal, value).validate_or_bind(
        domain=domain,
        owner=owner,
        material=material,
        reason=reason,
    )


def _tensor_coordinate_material(
    *, role: str, name: str, dtype: str, shape: tuple[int, ...]
) -> dict[str, Any]:
    return {
        "role": role,
        "name": name,
        "dtype": dtype,
        "shape": list(shape),
        "byte_order": "LITTLE_ENDIAN",
        "layout": "CONTIGUOUS_C_ORDER",
    }


def _tensor_item_material(
    *,
    role: str,
    name: str,
    dtype: str,
    shape: tuple[int, ...],
    byte_count: int,
    payload_sha256: str,
    coordinate_sha256: str,
) -> dict[str, Any]:
    return {
        "schema_version": PROFILED_SUPERVISED_TENSOR_STATE_ITEM_V1_SCHEMA_VERSION,
        **_tensor_coordinate_material(role=role, name=name, dtype=dtype, shape=shape),
        "byte_count": byte_count,
        "payload_sha256": payload_sha256,
        "coordinate_sha256": coordinate_sha256,
    }


@dataclass(frozen=True, slots=True)
class ProfiledSupervisedTensorStateItemV1:
    schema_version: str
    role: str
    name: str
    dtype: str
    shape: tuple[int, ...]
    byte_order: str
    layout: str
    payload: bytes = field(repr=False)
    byte_count: int
    payload_sha256: str
    coordinate_sha256: str
    tensor_state_identity_sha256: str
    _factory_seal: _FactorySeal = field(repr=False, compare=False)
    _construction_token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if type(self.payload) is not bytes:
            _fail("PROFILED_CHECKPOINT_TENSOR_PAYLOAD_EXACT_BYTES_REQUIRED")
        if type(self.shape) is not tuple or any(
            type(dimension) is not int or dimension < 0 for dimension in self.shape
        ):
            _fail("PROFILED_CHECKPOINT_TENSOR_SHAPE_INVALID")
        width = _DTYPE_BYTE_WIDTH.get(self.dtype) if type(self.dtype) is str else None
        element_count = math.prod(self.shape)
        coordinate = _tensor_coordinate_material(
            role=self.role,
            name=self.name,
            dtype=self.dtype,
            shape=self.shape,
        )
        material = _tensor_item_material(
            role=self.role,
            name=self.name,
            dtype=self.dtype,
            shape=self.shape,
            byte_count=self.byte_count,
            payload_sha256=self.payload_sha256,
            coordinate_sha256=self.coordinate_sha256,
        )
        if (
            self._construction_token is not _TENSOR_ITEM_TOKEN
            or self.schema_version != PROFILED_SUPERVISED_TENSOR_STATE_ITEM_V1_SCHEMA_VERSION
            or type(self.role) is not str
            or self.role not in _STATE_ROLES
            or type(self.name) is not str
            or _STATE_NAME_RE.fullmatch(self.name) is None
            or type(self.dtype) is not str
            or width is None
            or self.byte_order != "LITTLE_ENDIAN"
            or self.layout != "CONTIGUOUS_C_ORDER"
            or type(self.byte_count) is not int
            or self.byte_count <= 0
            or self.byte_count > MAX_PROFILED_STATE_ITEM_BYTES
            or element_count <= 0
            or width * element_count != self.byte_count
            or len(self.payload) != self.byte_count
            or not _valid_sha256(self.payload_sha256)
            or self.payload_sha256 != hashlib.sha256(self.payload).hexdigest()
            or not _valid_sha256(self.coordinate_sha256)
            or self.coordinate_sha256 != stable_sha256(coordinate)
            or not _valid_sha256(self.tensor_state_identity_sha256)
            or self.tensor_state_identity_sha256 != stable_sha256(material)
        ):
            _fail("PROFILED_CHECKPOINT_TENSOR_STATE_ITEM_INVALID")
        _require_factory_seal(
            self._factory_seal,
            domain=_TENSOR_ITEM_SEAL_DOMAIN,
            owner=self,
            material=_seal_material(self),
            reason="PROFILED_CHECKPOINT_TENSOR_STATE_ITEM_FACTORY_SEAL_INVALID",
        )

    def __reduce_ex__(self, _protocol: int) -> NoReturn:
        _fail("PROFILED_CHECKPOINT_TENSOR_STATE_ITEM_PICKLE_OR_COPY_FORBIDDEN")


def _build_tensor_item(
    *, role: str, value: tuple[str, str, tuple[int, ...], bytes]
) -> ProfiledSupervisedTensorStateItemV1:
    if type(value) is not tuple or len(value) != 4:
        _fail("PROFILED_CHECKPOINT_TENSOR_INPUT_TUPLE_INVALID")
    name, dtype, shape, payload = value
    if type(payload) is not bytes:
        _fail("PROFILED_CHECKPOINT_TENSOR_PAYLOAD_EXACT_BYTES_REQUIRED")
    coordinate = _tensor_coordinate_material(role=role, name=name, dtype=dtype, shape=shape)
    coordinate_sha256 = stable_sha256(coordinate)
    payload_sha256 = hashlib.sha256(payload).hexdigest()
    material = _tensor_item_material(
        role=role,
        name=name,
        dtype=dtype,
        shape=shape,
        byte_count=len(payload),
        payload_sha256=payload_sha256,
        coordinate_sha256=coordinate_sha256,
    )
    return ProfiledSupervisedTensorStateItemV1(
        schema_version=PROFILED_SUPERVISED_TENSOR_STATE_ITEM_V1_SCHEMA_VERSION,
        role=role,
        name=name,
        dtype=dtype,
        shape=shape,
        byte_order="LITTLE_ENDIAN",
        layout="CONTIGUOUS_C_ORDER",
        payload=payload,
        byte_count=len(payload),
        payload_sha256=payload_sha256,
        coordinate_sha256=coordinate_sha256,
        tensor_state_identity_sha256=stable_sha256(material),
        _factory_seal=_FactorySeal(
            domain=_TENSOR_ITEM_SEAL_DOMAIN,
            construction_token=_FACTORY_SEAL_TOKEN,
        ),
        _construction_token=_TENSOR_ITEM_TOKEN,
    )


def _ordered_identity_sha256(*, domain: str, values: tuple[str, ...]) -> str:
    return stable_sha256({"domain": domain, "ordered_identities": list(values)})


def _state_snapshot_material(
    *,
    stage: str,
    captured_at: str,
    model_coordinate_inventory_sha256: str,
    model_state_content_inventory_sha256: str,
    optimizer_coordinate_inventory_sha256: str,
    optimizer_state_content_inventory_sha256: str,
    model_tensor_count: int,
    optimizer_tensor_count: int,
) -> dict[str, Any]:
    return {
        "schema_version": PROFILED_SUPERVISED_OPTIMIZATION_STATE_SNAPSHOT_V1_SCHEMA_VERSION,
        "stage": stage,
        "captured_at": captured_at,
        "model_coordinate_inventory_sha256": model_coordinate_inventory_sha256,
        "model_state_content_inventory_sha256": model_state_content_inventory_sha256,
        "optimizer_coordinate_inventory_sha256": optimizer_coordinate_inventory_sha256,
        "optimizer_state_content_inventory_sha256": optimizer_state_content_inventory_sha256,
        "model_tensor_count": model_tensor_count,
        "optimizer_tensor_count": optimizer_tensor_count,
    }


@dataclass(frozen=True, slots=True)
class ProfiledSupervisedOptimizationStateSnapshotV1:
    schema_version: str
    stage: str
    captured_at: str
    model_tensors: tuple[ProfiledSupervisedTensorStateItemV1, ...] = field(repr=False)
    optimizer_tensors: tuple[ProfiledSupervisedTensorStateItemV1, ...] = field(repr=False)
    model_tensor_count: int
    optimizer_tensor_count: int
    model_coordinate_inventory_sha256: str
    model_state_content_inventory_sha256: str
    optimizer_coordinate_inventory_sha256: str
    optimizer_state_content_inventory_sha256: str
    state_snapshot_sha256: str
    _factory_seal: _FactorySeal = field(repr=False, compare=False)
    _construction_token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        _clock(self.captured_at, reason="PROFILED_CHECKPOINT_STATE_CAPTURED_AT_INVALID")
        for role, items in (("MODEL", self.model_tensors), ("OPTIMIZER", self.optimizer_tensors)):
            if type(items) is not tuple:
                _fail("PROFILED_CHECKPOINT_STATE_ITEMS_EXACT_TUPLE_REQUIRED")
            for item in items:
                if type(item) is not ProfiledSupervisedTensorStateItemV1:
                    _fail("PROFILED_CHECKPOINT_STATE_ITEM_EXACT_TYPE_REQUIRED")
                item.__post_init__()
                if item.role != role:
                    _fail("PROFILED_CHECKPOINT_STATE_ITEM_ROLE_INVALID")
            names = tuple(item.name for item in items)
            if names != tuple(sorted(set(names))):
                _fail("PROFILED_CHECKPOINT_STATE_ITEM_ORDER_OR_UNIQUENESS_INVALID")
        if not self.model_tensors:
            _fail("PROFILED_CHECKPOINT_MODEL_STATE_REQUIRED")
        if self.model_tensor_count + self.optimizer_tensor_count > MAX_PROFILED_STATE_ITEMS:
            _fail("PROFILED_CHECKPOINT_STATE_ITEM_COUNT_INVALID")
        model_coordinates = tuple(item.coordinate_sha256 for item in self.model_tensors)
        model_states = tuple(item.tensor_state_identity_sha256 for item in self.model_tensors)
        optimizer_coordinates = tuple(item.coordinate_sha256 for item in self.optimizer_tensors)
        optimizer_states = tuple(
            item.tensor_state_identity_sha256 for item in self.optimizer_tensors
        )
        expected = {
            "model_coordinate_inventory_sha256": _ordered_identity_sha256(
                domain="v2/native-trainer/profiled-checkpoint/model-coordinates/v1",
                values=model_coordinates,
            ),
            "model_state_content_inventory_sha256": _ordered_identity_sha256(
                domain="v2/native-trainer/profiled-checkpoint/model-state/v1",
                values=model_states,
            ),
            "optimizer_coordinate_inventory_sha256": _ordered_identity_sha256(
                domain="v2/native-trainer/profiled-checkpoint/optimizer-coordinates/v1",
                values=optimizer_coordinates,
            ),
            "optimizer_state_content_inventory_sha256": _ordered_identity_sha256(
                domain="v2/native-trainer/profiled-checkpoint/optimizer-state/v1",
                values=optimizer_states,
            ),
        }
        material = _state_snapshot_material(
            stage=self.stage,
            captured_at=self.captured_at,
            model_coordinate_inventory_sha256=self.model_coordinate_inventory_sha256,
            model_state_content_inventory_sha256=self.model_state_content_inventory_sha256,
            optimizer_coordinate_inventory_sha256=self.optimizer_coordinate_inventory_sha256,
            optimizer_state_content_inventory_sha256=(
                self.optimizer_state_content_inventory_sha256
            ),
            model_tensor_count=self.model_tensor_count,
            optimizer_tensor_count=self.optimizer_tensor_count,
        )
        if (
            self._construction_token is not _STATE_SNAPSHOT_TOKEN
            or self.schema_version
            != PROFILED_SUPERVISED_OPTIMIZATION_STATE_SNAPSHOT_V1_SCHEMA_VERSION
            or type(self.stage) is not str
            or self.stage not in _STATE_STAGES
            or type(self.model_tensor_count) is not int
            or type(self.optimizer_tensor_count) is not int
            or self.model_tensor_count != len(self.model_tensors)
            or self.optimizer_tensor_count != len(self.optimizer_tensors)
            or any(getattr(self, name) != value for name, value in expected.items())
            or not _valid_sha256(self.state_snapshot_sha256)
            or self.state_snapshot_sha256 != stable_sha256(material)
        ):
            _fail("PROFILED_CHECKPOINT_STATE_SNAPSHOT_INVALID")
        _require_factory_seal(
            self._factory_seal,
            domain=_STATE_SNAPSHOT_SEAL_DOMAIN,
            owner=self,
            material=_seal_material(self),
            reason="PROFILED_CHECKPOINT_STATE_SNAPSHOT_FACTORY_SEAL_INVALID",
        )

    def __reduce_ex__(self, _protocol: int) -> NoReturn:
        _fail("PROFILED_CHECKPOINT_STATE_SNAPSHOT_PICKLE_OR_COPY_FORBIDDEN")


def capture_profiled_supervised_optimization_state_snapshot_v1(
    *,
    stage: str,
    captured_at: str,
    model_tensors: tuple[tuple[str, str, tuple[int, ...], bytes], ...],
    optimizer_tensors: tuple[tuple[str, str, tuple[int, ...], bytes], ...],
) -> ProfiledSupervisedOptimizationStateSnapshotV1:
    """Capture exact named little-endian tensor bytes without writing them."""

    if type(model_tensors) is not tuple or type(optimizer_tensors) is not tuple:
        _fail("PROFILED_CHECKPOINT_STATE_INPUT_EXACT_TUPLES_REQUIRED")
    if len(model_tensors) + len(optimizer_tensors) > MAX_PROFILED_STATE_ITEMS:
        _fail("PROFILED_CHECKPOINT_STATE_ITEM_COUNT_INVALID")
    model_items = tuple(_build_tensor_item(role="MODEL", value=item) for item in model_tensors)
    optimizer_items = tuple(
        _build_tensor_item(role="OPTIMIZER", value=item) for item in optimizer_tensors
    )
    model_coordinates = tuple(item.coordinate_sha256 for item in model_items)
    model_states = tuple(item.tensor_state_identity_sha256 for item in model_items)
    optimizer_coordinates = tuple(item.coordinate_sha256 for item in optimizer_items)
    optimizer_states = tuple(item.tensor_state_identity_sha256 for item in optimizer_items)
    identities = {
        "model_coordinate_inventory_sha256": _ordered_identity_sha256(
            domain="v2/native-trainer/profiled-checkpoint/model-coordinates/v1",
            values=model_coordinates,
        ),
        "model_state_content_inventory_sha256": _ordered_identity_sha256(
            domain="v2/native-trainer/profiled-checkpoint/model-state/v1", values=model_states
        ),
        "optimizer_coordinate_inventory_sha256": _ordered_identity_sha256(
            domain="v2/native-trainer/profiled-checkpoint/optimizer-coordinates/v1",
            values=optimizer_coordinates,
        ),
        "optimizer_state_content_inventory_sha256": _ordered_identity_sha256(
            domain="v2/native-trainer/profiled-checkpoint/optimizer-state/v1",
            values=optimizer_states,
        ),
    }
    material = _state_snapshot_material(
        stage=stage,
        captured_at=captured_at,
        model_coordinate_inventory_sha256=identities["model_coordinate_inventory_sha256"],
        model_state_content_inventory_sha256=identities["model_state_content_inventory_sha256"],
        optimizer_coordinate_inventory_sha256=identities["optimizer_coordinate_inventory_sha256"],
        optimizer_state_content_inventory_sha256=identities[
            "optimizer_state_content_inventory_sha256"
        ],
        model_tensor_count=len(model_items),
        optimizer_tensor_count=len(optimizer_items),
    )
    return ProfiledSupervisedOptimizationStateSnapshotV1(
        schema_version=PROFILED_SUPERVISED_OPTIMIZATION_STATE_SNAPSHOT_V1_SCHEMA_VERSION,
        stage=stage,
        captured_at=captured_at,
        model_tensors=model_items,
        optimizer_tensors=optimizer_items,
        model_tensor_count=len(model_items),
        optimizer_tensor_count=len(optimizer_items),
        **identities,
        state_snapshot_sha256=stable_sha256(material),
        _factory_seal=_FactorySeal(
            domain=_STATE_SNAPSHOT_SEAL_DOMAIN,
            construction_token=_FACTORY_SEAL_TOKEN,
        ),
        _construction_token=_STATE_SNAPSHOT_TOKEN,
    )


def _optimizer_input_material(corpus: AuthenticatedProfiledOptimizerCorpusV1) -> dict[str, Any]:
    return {
        "domain": "v2/native-trainer/profiled-checkpoint/optimizer-input-inventory/v1",
        "corpus_contract_sha256": corpus.corpus_contract_sha256,
        "ordered_rows": [
            {
                "ordinal": row.ordinal,
                "row_inventory_sha256": row.row_inventory_sha256,
                "sample_identity_sha256": row.sample_identity_sha256,
                "label_binding_sha256": row.label_binding_sha256,
                "tensor_binding_sha256": row.tensor_binding_sha256,
                "logical_model_vector_sha256": row.logical_model_vector_sha256,
                "logical_projection_sha256": row.logical_projection_sha256,
                "model_input_float64_sha256": row.model_input_float64_sha256,
                "supervised_target_sha256": row.supervised_target.target_sha256,
                "target_label_value_float64_sha256": (
                    row.supervised_target.label_value_float64_sha256
                ),
            }
            for row in corpus.rows
        ],
    }


def _ordered_row_field_digest(
    *, corpus: AuthenticatedProfiledOptimizerCorpusV1, domain: str, field_name: str
) -> str:
    values: list[str] = []
    for row in corpus.rows:
        if field_name == "supervised_target_sha256":
            value = row.supervised_target.target_sha256
        elif field_name == "target_label_value_float64_sha256":
            value = row.supervised_target.label_value_float64_sha256
        else:
            value = getattr(row, field_name)
        if not _valid_sha256(value):
            _fail("PROFILED_CHECKPOINT_ORDERED_ROW_IDENTITY_INVALID")
        values.append(cast(str, value))
    return stable_sha256({"domain": domain, "ordered_identities": values})


def _payload_descriptors(
    *,
    after_state: ProfiledSupervisedOptimizationStateSnapshotV1,
    implementation_sha256: str,
    implementation_bytes: bytes,
    configuration_sha256: str,
    configuration_bytes: bytes,
    environment_sha256: str,
    environment_bytes: bytes,
) -> list[dict[str, Any]]:
    descriptors = [
        {
            "frame_name": f"MODEL:{item.name}",
            "byte_count": item.byte_count,
            "sha256": item.payload_sha256,
        }
        for item in after_state.model_tensors
    ]
    descriptors.extend(
        {
            "frame_name": f"OPTIMIZER:{item.name}",
            "byte_count": item.byte_count,
            "sha256": item.payload_sha256,
        }
        for item in after_state.optimizer_tensors
    )
    descriptors.extend(
        (
            {
                "frame_name": "ARTIFACT:OPTIMIZER_IMPLEMENTATION",
                "byte_count": len(implementation_bytes),
                "sha256": implementation_sha256,
            },
            {
                "frame_name": "ARTIFACT:OPTIMIZER_CONFIGURATION",
                "byte_count": len(configuration_bytes),
                "sha256": configuration_sha256,
            },
            {
                "frame_name": "ARTIFACT:EXECUTION_ENVIRONMENT",
                "byte_count": len(environment_bytes),
                "sha256": environment_sha256,
            },
        )
    )
    return descriptors


def _checkpoint_header_material(value: ProfiledSupervisedCheckpointInventoryV1) -> dict[str, Any]:
    return {
        "schema_version": PROFILED_SUPERVISED_CHECKPOINT_BINARY_V1_SCHEMA_VERSION,
        "checkpoint_inventory_schema_version": value.schema_version,
        "checkpoint_contract_implementation_sha256": (
            value.checkpoint_contract_implementation_sha256
        ),
        "status": value.status,
        "manifest": {
            "manifest_id": value.manifest_id,
            "manifest_metadata_sha256": value.manifest_metadata_sha256,
            "manifest_observation_context_sha256": (value.manifest_observation_context_sha256),
            "manifest_entry_chain_head_sha256": value.manifest_entry_chain_head_sha256,
            "manifest_ordered_entry_identities_sha256": (
                value.manifest_ordered_entry_identities_sha256
            ),
            "completion_event_sha256": value.completion_event_sha256,
            "completion_ordered_page_root_sha256": value.completion_ordered_page_root_sha256,
        },
        "external_witness": {
            "external_authorization_envelope_sha256": (
                value.external_authorization_envelope_sha256
            ),
            "witness_id": value.witness_id,
            "witness_namespace": value.witness_namespace,
            "witness_public_key_sha256": value.witness_public_key_sha256,
            "witness_sequence": value.witness_sequence,
            "witness_previous_event_sha256": value.witness_previous_event_sha256,
            "witness_accepted_at": value.witness_accepted_at,
        },
        "optimizer_input": {
            "corpus_contract_sha256": value.corpus_contract_sha256,
            "execution_authorization_inventory_equality_sha256": (
                value.execution_authorization_inventory_equality_sha256
            ),
            "before_optimizer_input_inventory_sha256": (
                value.before_optimizer_input_inventory_sha256
            ),
            "after_optimizer_input_inventory_sha256": (
                value.after_optimizer_input_inventory_sha256
            ),
            "admitted_example_count": value.admitted_example_count,
            "admitted_ordinals": list(value.admitted_ordinals),
            "ordered_sample_identities_sha256": value.ordered_sample_identities_sha256,
            "ordered_label_bindings_sha256": value.ordered_label_bindings_sha256,
            "ordered_tensor_bindings_sha256": value.ordered_tensor_bindings_sha256,
            "ordered_logical_model_vectors_sha256": (value.ordered_logical_model_vectors_sha256),
            "ordered_logical_projections_sha256": (value.ordered_logical_projections_sha256),
            "ordered_model_inputs_sha256": value.ordered_model_inputs_sha256,
            "ordered_supervised_targets_sha256": (value.ordered_supervised_targets_sha256),
            "ordered_target_values_sha256": value.ordered_target_values_sha256,
            "ordered_row_inventories_sha256": value.ordered_row_inventories_sha256,
            "ordered_rows": _optimizer_input_material(value.before_corpus)["ordered_rows"],
        },
        "projection": {
            "feature_registry_sha256": value.feature_registry_sha256,
            "feature_registry_abi_sha256": value.feature_registry_abi_sha256,
            "logical_profile_selection_mask": list(value.logical_profile_selection_mask),
            "logical_profile_selection_mask_sha256": (value.logical_profile_selection_mask_sha256),
            "projection_schema_version": value.projection_schema_version,
            "projection_implementation_sha256": value.projection_implementation_sha256,
            "projection_configuration_sha256": value.projection_configuration_sha256,
        },
        "state": {
            "before_state_snapshot_sha256": value.before_state.state_snapshot_sha256,
            "after_state_snapshot_sha256": value.after_state.state_snapshot_sha256,
            "before_model_state_identity_sha256": (value.before_model_state_identity_sha256),
            "after_model_state_identity_sha256": value.after_model_state_identity_sha256,
            "before_optimizer_state_identity_sha256": (
                value.before_optimizer_state_identity_sha256
            ),
            "after_optimizer_state_identity_sha256": (value.after_optimizer_state_identity_sha256),
            "model_coordinate_inventory_sha256": value.model_coordinate_inventory_sha256,
        },
        "artifacts": {
            "optimizer_implementation_artifact_sha256": (
                value.optimizer_implementation_artifact_sha256
            ),
            "optimizer_implementation_artifact_byte_count": (
                value.optimizer_implementation_artifact_byte_count
            ),
            "optimizer_configuration_artifact_sha256": (
                value.optimizer_configuration_artifact_sha256
            ),
            "optimizer_configuration_artifact_byte_count": (
                value.optimizer_configuration_artifact_byte_count
            ),
            "execution_environment_artifact_sha256": (value.execution_environment_artifact_sha256),
            "execution_environment_artifact_byte_count": (
                value.execution_environment_artifact_byte_count
            ),
        },
        "clocks": {
            "observation_time": value.observation_time,
            "witness_accepted_at": value.witness_accepted_at,
            "before_input_inventory_verified_at": value.before_input_inventory_verified_at,
            "before_state_captured_at": value.before_state.captured_at,
            "optimizer_started_at": value.optimizer_started_at,
            "optimizer_completed_at": value.optimizer_completed_at,
            "after_state_captured_at": value.after_state.captured_at,
            "after_input_inventory_verified_at": value.after_input_inventory_verified_at,
            "checkpoint_created_at": value.checkpoint_created_at,
        },
        "payload_frames": _payload_descriptors(
            after_state=value.after_state,
            implementation_sha256=value.optimizer_implementation_artifact_sha256,
            implementation_bytes=value.optimizer_implementation_artifact_bytes,
            configuration_sha256=value.optimizer_configuration_artifact_sha256,
            configuration_bytes=value.optimizer_configuration_artifact_json_bytes,
            environment_sha256=value.execution_environment_artifact_sha256,
            environment_bytes=value.execution_environment_artifact_json_bytes,
        ),
        "claims": {
            "corpus_inventory_equal_before_after_optimization": (
                value.corpus_inventory_equal_before_after_optimization
            ),
            "model_coordinates_equal_before_after_optimization": (
                value.model_coordinates_equal_before_after_optimization
            ),
            "model_state_changed": value.model_state_changed,
            "optimizer_execution_independently_observed": (
                value.optimizer_execution_independently_observed
            ),
            "in_memory_checkpoint_candidate_created": (
                value.in_memory_checkpoint_candidate_created
            ),
            "outcome_supervised_objective_only": value.outcome_supervised_objective_only,
            "behavior_receipt_bound": value.behavior_receipt_bound,
            "ppo_behavior_policy_terms_enabled": value.ppo_behavior_policy_terms_enabled,
            **{name: getattr(value, name) for name in _AUTHORITY_FALSE},
        },
    }


def _frame(name: str, payload: bytes) -> bytes:
    encoded_name = name.encode("ascii", errors="strict")
    return (
        struct.pack(">I", len(encoded_name))
        + encoded_name
        + struct.pack(">Q", len(payload))
        + payload
    )


def _build_checkpoint_bytes(
    *, value: ProfiledSupervisedCheckpointInventoryV1, header_bytes: bytes
) -> bytes:
    frames = [
        _frame(f"MODEL:{item.name}", item.payload) for item in value.after_state.model_tensors
    ]
    frames.extend(
        _frame(f"OPTIMIZER:{item.name}", item.payload)
        for item in value.after_state.optimizer_tensors
    )
    frames.extend(
        (
            _frame(
                "ARTIFACT:OPTIMIZER_IMPLEMENTATION",
                value.optimizer_implementation_artifact_bytes,
            ),
            _frame(
                "ARTIFACT:OPTIMIZER_CONFIGURATION",
                value.optimizer_configuration_artifact_json_bytes,
            ),
            _frame(
                "ARTIFACT:EXECUTION_ENVIRONMENT",
                value.execution_environment_artifact_json_bytes,
            ),
        )
    )
    return (
        PROFILED_SUPERVISED_CHECKPOINT_BINARY_MAGIC
        + struct.pack(">Q", len(header_bytes))
        + header_bytes
        + b"".join(frames)
    )


def _checkpoint_inventory_material(
    value: ProfiledSupervisedCheckpointInventoryV1,
) -> dict[str, Any]:
    return {
        "schema_version": value.schema_version,
        "checkpoint_contract_implementation_sha256": (
            value.checkpoint_contract_implementation_sha256
        ),
        "checkpoint_header_json_sha256": value.checkpoint_header_json_sha256,
        "checkpoint_bytes_sha256": value.checkpoint_bytes_sha256,
        "checkpoint_byte_count": value.checkpoint_byte_count,
        "corpus_contract_sha256": value.corpus_contract_sha256,
        "execution_authorization_inventory_equality_sha256": (
            value.execution_authorization_inventory_equality_sha256
        ),
        "before_state_snapshot_sha256": value.before_state.state_snapshot_sha256,
        "after_state_snapshot_sha256": value.after_state.state_snapshot_sha256,
        "optimizer_implementation_artifact_sha256": (
            value.optimizer_implementation_artifact_sha256
        ),
        "optimizer_configuration_artifact_sha256": (value.optimizer_configuration_artifact_sha256),
        "execution_environment_artifact_sha256": value.execution_environment_artifact_sha256,
        "checkpoint_created_at": value.checkpoint_created_at,
        "status": value.status,
        **{name: getattr(value, name) for name in _AUTHORITY_FALSE},
    }


@dataclass(frozen=True, slots=True)
class ProfiledSupervisedCheckpointInventoryV1:
    schema_version: str
    status: str
    before_corpus: AuthenticatedProfiledOptimizerCorpusV1 = field(repr=False)
    after_corpus: AuthenticatedProfiledOptimizerCorpusV1 = field(repr=False)
    execution_authorization: AuthenticatedProfiledSupervisedOptimizerExecutionAuthorizationV1 = (
        field(repr=False)
    )
    before_state: ProfiledSupervisedOptimizationStateSnapshotV1 = field(repr=False)
    after_state: ProfiledSupervisedOptimizationStateSnapshotV1 = field(repr=False)
    manifest_id: str
    manifest_metadata_sha256: str
    manifest_observation_context_sha256: str
    manifest_entry_chain_head_sha256: str
    manifest_ordered_entry_identities_sha256: str
    completion_event_sha256: str
    completion_ordered_page_root_sha256: str
    external_authorization_envelope_sha256: str
    witness_id: str
    witness_namespace: str
    witness_public_key_sha256: str
    witness_sequence: int
    witness_previous_event_sha256: str
    witness_accepted_at: str
    observation_time: str
    corpus_contract_sha256: str
    execution_authorization_inventory_equality_sha256: str
    before_optimizer_input_inventory_sha256: str
    after_optimizer_input_inventory_sha256: str
    admitted_example_count: int
    admitted_ordinals: tuple[int, ...]
    ordered_sample_identities_sha256: str
    ordered_label_bindings_sha256: str
    ordered_tensor_bindings_sha256: str
    ordered_logical_model_vectors_sha256: str
    ordered_logical_projections_sha256: str
    ordered_model_inputs_sha256: str
    ordered_supervised_targets_sha256: str
    ordered_target_values_sha256: str
    ordered_row_inventories_sha256: str
    feature_registry_sha256: str
    feature_registry_abi_sha256: str
    logical_profile_selection_mask: tuple[int, ...] = field(repr=False)
    logical_profile_selection_mask_sha256: str
    projection_schema_version: str
    projection_implementation_sha256: str
    projection_configuration_sha256: str
    model_coordinate_inventory_sha256: str
    before_model_state_identity_sha256: str
    after_model_state_identity_sha256: str
    before_optimizer_state_identity_sha256: str
    after_optimizer_state_identity_sha256: str
    optimizer_implementation_artifact_bytes: bytes = field(repr=False)
    optimizer_implementation_artifact_sha256: str
    optimizer_implementation_artifact_byte_count: int
    optimizer_configuration_artifact_json_bytes: bytes = field(repr=False)
    optimizer_configuration_artifact_sha256: str
    optimizer_configuration_artifact_byte_count: int
    execution_environment_artifact_json_bytes: bytes = field(repr=False)
    execution_environment_artifact_sha256: str
    execution_environment_artifact_byte_count: int
    before_input_inventory_verified_at: str
    optimizer_started_at: str
    optimizer_completed_at: str
    after_input_inventory_verified_at: str
    checkpoint_created_at: str
    checkpoint_contract_implementation_sha256: str
    checkpoint_header_json_sha256: str
    checkpoint_bytes: bytes = field(repr=False)
    checkpoint_bytes_sha256: str
    checkpoint_byte_count: int
    checkpoint_inventory_sha256: str
    corpus_inventory_equal_before_after_optimization: bool
    model_coordinates_equal_before_after_optimization: bool
    model_state_changed: bool
    optimizer_execution_independently_observed: bool
    in_memory_checkpoint_candidate_created: bool
    outcome_supervised_objective_only: bool
    behavior_receipt_bound: bool
    ppo_behavior_policy_terms_enabled: bool
    checkpoint_write_authorized: bool
    model_write_authorized: bool
    prediction_authorized: bool
    serving_authorized: bool
    ppo_training_authorized: bool
    paper_trading_authorized: bool
    live_execution_authorized: bool
    exchange_access_authorized: bool
    deployment_authorized: bool
    order_submission_authorized: bool
    execution_authorized: bool
    runtime_wired: bool
    _factory_seal: _FactorySeal = field(repr=False, compare=False)
    _construction_token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        _validate_checkpoint_inventory(self)

    def __reduce_ex__(self, _protocol: int) -> NoReturn:
        _fail("PROFILED_CHECKPOINT_INVENTORY_PICKLE_OR_COPY_FORBIDDEN")


def _validate_checkpoint_inventory(value: ProfiledSupervisedCheckpointInventoryV1) -> None:
    if (
        type(value.before_corpus) is not AuthenticatedProfiledOptimizerCorpusV1
        or type(value.after_corpus) is not AuthenticatedProfiledOptimizerCorpusV1
        or type(value.execution_authorization)
        is not AuthenticatedProfiledSupervisedOptimizerExecutionAuthorizationV1
    ):
        _fail("PROFILED_CHECKPOINT_AUTHENTICATED_CORPUS_INPUT_TYPES_INVALID")
    try:
        value.before_corpus.__post_init__()
        value.after_corpus.__post_init__()
        value.execution_authorization.__post_init__()
        expected_authorization = (
            validate_authenticated_profiled_optimizer_corpus_inventory_equality_v1(
                before=value.before_corpus,
                after=value.after_corpus,
            )
        )
    except AuthenticatedProfiledOptimizerCorpusV1Error as exc:
        raise ProfiledSupervisedCheckpointInventoryV1Error(
            "PROFILED_CHECKPOINT_CORPUS_REAUTHENTICATION_FAILED", *exc.reasons
        ) from exc
    if value.execution_authorization != expected_authorization:
        _fail("PROFILED_CHECKPOINT_EXECUTION_AUTHORIZATION_PAIR_MISMATCH")
    if (
        type(value.before_state) is not ProfiledSupervisedOptimizationStateSnapshotV1
        or type(value.after_state) is not ProfiledSupervisedOptimizationStateSnapshotV1
    ):
        _fail("PROFILED_CHECKPOINT_STATE_SNAPSHOT_EXACT_TYPES_REQUIRED")
    value.before_state.__post_init__()
    value.after_state.__post_init__()
    before_input_material = _optimizer_input_material(value.before_corpus)
    after_input_material = _optimizer_input_material(value.after_corpus)
    before_input_sha256 = stable_sha256(before_input_material)
    after_input_sha256 = stable_sha256(after_input_material)
    if not hmac.compare_digest(
        _canonical_bytes(
            before_input_material,
            reason="PROFILED_CHECKPOINT_BEFORE_INPUT_INVENTORY_ENCODING_INVALID",
        ),
        _canonical_bytes(
            after_input_material,
            reason="PROFILED_CHECKPOINT_AFTER_INPUT_INVENTORY_ENCODING_INVALID",
        ),
    ):
        _fail("PROFILED_CHECKPOINT_CORPUS_INVENTORY_BEFORE_AFTER_MISMATCH")
    ordered_fields = {
        "ordered_sample_identities_sha256": (
            "v2/native-trainer/profiled-checkpoint/ordered-samples/v1",
            "sample_identity_sha256",
        ),
        "ordered_label_bindings_sha256": (
            "v2/native-trainer/profiled-checkpoint/ordered-labels/v1",
            "label_binding_sha256",
        ),
        "ordered_tensor_bindings_sha256": (
            "v2/native-trainer/profiled-checkpoint/ordered-tensors/v1",
            "tensor_binding_sha256",
        ),
        "ordered_logical_model_vectors_sha256": (
            "v2/native-trainer/profiled-checkpoint/ordered-logical-model-vectors/v1",
            "logical_model_vector_sha256",
        ),
        "ordered_logical_projections_sha256": (
            "v2/native-trainer/profiled-checkpoint/ordered-logical-projections/v1",
            "logical_projection_sha256",
        ),
        "ordered_model_inputs_sha256": (
            "v2/native-trainer/profiled-checkpoint/ordered-model-inputs/v1",
            "model_input_float64_sha256",
        ),
        "ordered_supervised_targets_sha256": (
            "v2/native-trainer/profiled-checkpoint/ordered-supervised-targets/v1",
            "supervised_target_sha256",
        ),
        "ordered_target_values_sha256": (
            "v2/native-trainer/profiled-checkpoint/ordered-target-values/v1",
            "target_label_value_float64_sha256",
        ),
        "ordered_row_inventories_sha256": (
            "v2/native-trainer/profiled-checkpoint/ordered-row-inventories/v1",
            "row_inventory_sha256",
        ),
    }
    expected_ordered = {
        name: _ordered_row_field_digest(
            corpus=value.before_corpus, domain=domain, field_name=field_name
        )
        for name, (domain, field_name) in ordered_fields.items()
    }
    expected_common = {
        "manifest_id": value.before_corpus.manifest_id,
        "manifest_metadata_sha256": value.before_corpus.manifest_metadata_sha256,
        "manifest_observation_context_sha256": (
            value.before_corpus.manifest_observation_context_sha256
        ),
        "manifest_entry_chain_head_sha256": (value.before_corpus.manifest_entry_chain_head_sha256),
        "manifest_ordered_entry_identities_sha256": (
            value.before_corpus.manifest_ordered_entry_identities_sha256
        ),
        "completion_event_sha256": value.before_corpus.completion_event_sha256,
        "completion_ordered_page_root_sha256": (
            value.before_corpus.completion_ordered_page_root_sha256
        ),
        "external_authorization_envelope_sha256": (
            value.before_corpus.external_authorization_envelope_sha256
        ),
        "witness_id": value.before_corpus.witness_id,
        "witness_namespace": value.before_corpus.witness_namespace,
        "witness_public_key_sha256": value.before_corpus.witness_public_key_sha256,
        "witness_sequence": value.before_corpus.witness_sequence,
        "witness_previous_event_sha256": value.before_corpus.witness_previous_event_sha256,
        "witness_accepted_at": value.before_corpus.witness_accepted_at,
        "observation_time": value.before_corpus.observation_time,
        "corpus_contract_sha256": value.before_corpus.corpus_contract_sha256,
        "execution_authorization_inventory_equality_sha256": (
            value.execution_authorization.inventory_equality_sha256
        ),
        "before_optimizer_input_inventory_sha256": before_input_sha256,
        "after_optimizer_input_inventory_sha256": after_input_sha256,
        "admitted_example_count": value.before_corpus.manifest_admitted_example_count,
        "admitted_ordinals": value.before_corpus.admitted_ordinals,
        "feature_registry_sha256": value.before_corpus.feature_registry_sha256,
        "feature_registry_abi_sha256": value.before_corpus.feature_registry_abi_sha256,
        "logical_profile_selection_mask": value.before_corpus.logical_profile_selection_mask,
        "logical_profile_selection_mask_sha256": (
            value.before_corpus.logical_profile_selection_mask_sha256
        ),
        "projection_schema_version": value.before_corpus.projection_schema_version,
        "projection_implementation_sha256": (value.before_corpus.projection_implementation_sha256),
        "projection_configuration_sha256": (value.before_corpus.projection_configuration_sha256),
        "model_coordinate_inventory_sha256": (value.before_state.model_coordinate_inventory_sha256),
        "before_model_state_identity_sha256": (
            value.before_state.model_state_content_inventory_sha256
        ),
        "after_model_state_identity_sha256": (
            value.after_state.model_state_content_inventory_sha256
        ),
        "before_optimizer_state_identity_sha256": (
            value.before_state.optimizer_state_content_inventory_sha256
        ),
        "after_optimizer_state_identity_sha256": (
            value.after_state.optimizer_state_content_inventory_sha256
        ),
    }
    implementation = _artifact_bytes(
        value.optimizer_implementation_artifact_bytes,
        maximum=MAX_PROFILED_IMPLEMENTATION_ARTIFACT_BYTES,
        reason="PROFILED_CHECKPOINT_IMPLEMENTATION_ARTIFACT_INVALID",
    )
    configuration = _strict_canonical_json_object(
        value.optimizer_configuration_artifact_json_bytes,
        maximum=MAX_PROFILED_CONFIGURATION_ARTIFACT_BYTES,
        reason="PROFILED_CHECKPOINT_CONFIGURATION_ARTIFACT_INVALID",
    )
    environment = _strict_canonical_json_object(
        value.execution_environment_artifact_json_bytes,
        maximum=MAX_PROFILED_ENVIRONMENT_ARTIFACT_BYTES,
        reason="PROFILED_CHECKPOINT_ENVIRONMENT_ARTIFACT_INVALID",
    )
    artifact_expectations = {
        "optimizer_implementation_artifact_sha256": hashlib.sha256(implementation).hexdigest(),
        "optimizer_implementation_artifact_byte_count": len(implementation),
        "optimizer_configuration_artifact_sha256": hashlib.sha256(configuration).hexdigest(),
        "optimizer_configuration_artifact_byte_count": len(configuration),
        "execution_environment_artifact_sha256": hashlib.sha256(environment).hexdigest(),
        "execution_environment_artifact_byte_count": len(environment),
    }
    clocks = tuple(
        _clock(clock_value, reason="PROFILED_CHECKPOINT_CLOCK_INVALID")
        for clock_value in (
            value.observation_time,
            value.witness_accepted_at,
            value.before_input_inventory_verified_at,
            value.before_state.captured_at,
            value.optimizer_started_at,
            value.optimizer_completed_at,
            value.after_state.captured_at,
            value.after_input_inventory_verified_at,
            value.checkpoint_created_at,
        )
    )
    header_bytes = _canonical_bytes(
        _checkpoint_header_material(value),
        reason="PROFILED_CHECKPOINT_HEADER_ENCODING_INVALID",
    )
    expected_checkpoint_bytes = _build_checkpoint_bytes(value=value, header_bytes=header_bytes)
    if (
        value._construction_token is not _CHECKPOINT_INVENTORY_TOKEN
        or value.schema_version != PROFILED_SUPERVISED_CHECKPOINT_INVENTORY_V1_SCHEMA_VERSION
        or value.status != PROFILED_SUPERVISED_CHECKPOINT_STATUS
        or any(getattr(value, name) != expected for name, expected in expected_common.items())
        or any(getattr(value, name) != expected for name, expected in expected_ordered.items())
        or any(getattr(value, name) != expected for name, expected in artifact_expectations.items())
        or value.before_state.stage != "BEFORE_OPTIMIZATION"
        or value.after_state.stage != "AFTER_OPTIMIZATION"
        or value.before_state.model_coordinate_inventory_sha256
        != value.after_state.model_coordinate_inventory_sha256
        or value.before_model_state_identity_sha256 == value.after_model_state_identity_sha256
        or clocks != tuple(sorted(set(clocks)))
        or value.checkpoint_contract_implementation_sha256
        != PROFILED_SUPERVISED_CHECKPOINT_IMPLEMENTATION_CONTRACT_SHA256
        or value.checkpoint_header_json_sha256 != hashlib.sha256(header_bytes).hexdigest()
        or type(value.checkpoint_bytes) is not bytes
        or value.checkpoint_bytes != expected_checkpoint_bytes
        or value.checkpoint_bytes_sha256 != hashlib.sha256(value.checkpoint_bytes).hexdigest()
        or value.checkpoint_byte_count != len(value.checkpoint_bytes)
        or value.checkpoint_inventory_sha256 != stable_sha256(_checkpoint_inventory_material(value))
        or value.corpus_inventory_equal_before_after_optimization is not True
        or value.model_coordinates_equal_before_after_optimization is not True
        or value.model_state_changed is not True
        or value.optimizer_execution_independently_observed is not False
        or value.in_memory_checkpoint_candidate_created is not True
        or value.outcome_supervised_objective_only is not True
        or value.behavior_receipt_bound is not False
        or value.ppo_behavior_policy_terms_enabled is not False
        or any(getattr(value, name) is not expected for name, expected in _AUTHORITY_FALSE.items())
    ):
        _fail("PROFILED_CHECKPOINT_INVENTORY_INVALID")
    _require_factory_seal(
        value._factory_seal,
        domain=_CHECKPOINT_INVENTORY_SEAL_DOMAIN,
        owner=value,
        material=_seal_material(value),
        reason="PROFILED_CHECKPOINT_INVENTORY_FACTORY_SEAL_INVALID",
    )


def build_authenticated_profiled_supervised_checkpoint_inventory_v1(
    *,
    before_corpus: AuthenticatedProfiledOptimizerCorpusV1,
    after_corpus: AuthenticatedProfiledOptimizerCorpusV1,
    execution_authorization: AuthenticatedProfiledSupervisedOptimizerExecutionAuthorizationV1,
    before_state: ProfiledSupervisedOptimizationStateSnapshotV1,
    after_state: ProfiledSupervisedOptimizationStateSnapshotV1,
    before_input_inventory_verified_at: str,
    optimizer_started_at: str,
    optimizer_completed_at: str,
    after_input_inventory_verified_at: str,
    checkpoint_created_at: str,
    optimizer_implementation_artifact_bytes: bytes,
    optimizer_configuration_artifact_json_bytes: bytes,
    execution_environment_artifact_json_bytes: bytes,
) -> ProfiledSupervisedCheckpointInventoryV1:
    """Build a deterministic in-memory checkpoint candidate with no write authority."""

    if (
        type(before_corpus) is not AuthenticatedProfiledOptimizerCorpusV1
        or type(after_corpus) is not AuthenticatedProfiledOptimizerCorpusV1
        or type(execution_authorization)
        is not AuthenticatedProfiledSupervisedOptimizerExecutionAuthorizationV1
    ):
        _fail("PROFILED_CHECKPOINT_AUTHENTICATED_CORPUS_INPUT_TYPES_INVALID")
    if (
        type(before_state) is not ProfiledSupervisedOptimizationStateSnapshotV1
        or type(after_state) is not ProfiledSupervisedOptimizationStateSnapshotV1
    ):
        _fail("PROFILED_CHECKPOINT_STATE_SNAPSHOT_EXACT_TYPES_REQUIRED")
    implementation = _artifact_bytes(
        optimizer_implementation_artifact_bytes,
        maximum=MAX_PROFILED_IMPLEMENTATION_ARTIFACT_BYTES,
        reason="PROFILED_CHECKPOINT_IMPLEMENTATION_ARTIFACT_INVALID",
    )
    configuration = _strict_canonical_json_object(
        optimizer_configuration_artifact_json_bytes,
        maximum=MAX_PROFILED_CONFIGURATION_ARTIFACT_BYTES,
        reason="PROFILED_CHECKPOINT_CONFIGURATION_ARTIFACT_INVALID",
    )
    environment = _strict_canonical_json_object(
        execution_environment_artifact_json_bytes,
        maximum=MAX_PROFILED_ENVIRONMENT_ARTIFACT_BYTES,
        reason="PROFILED_CHECKPOINT_ENVIRONMENT_ARTIFACT_INVALID",
    )
    # Reauthenticate the exact capability objects before copying any identity.
    try:
        before_corpus.__post_init__()
        after_corpus.__post_init__()
        execution_authorization.__post_init__()
    except AuthenticatedProfiledOptimizerCorpusV1Error as exc:
        raise ProfiledSupervisedCheckpointInventoryV1Error(
            "PROFILED_CHECKPOINT_CORPUS_REAUTHENTICATION_FAILED", *exc.reasons
        ) from exc
    before_state.__post_init__()
    after_state.__post_init__()
    before_input_sha256 = stable_sha256(_optimizer_input_material(before_corpus))
    after_input_sha256 = stable_sha256(_optimizer_input_material(after_corpus))
    ordered_arguments = {
        name: _ordered_row_field_digest(corpus=before_corpus, domain=domain, field_name=field_name)
        for name, (domain, field_name) in {
            "ordered_sample_identities_sha256": (
                "v2/native-trainer/profiled-checkpoint/ordered-samples/v1",
                "sample_identity_sha256",
            ),
            "ordered_label_bindings_sha256": (
                "v2/native-trainer/profiled-checkpoint/ordered-labels/v1",
                "label_binding_sha256",
            ),
            "ordered_tensor_bindings_sha256": (
                "v2/native-trainer/profiled-checkpoint/ordered-tensors/v1",
                "tensor_binding_sha256",
            ),
            "ordered_logical_model_vectors_sha256": (
                "v2/native-trainer/profiled-checkpoint/ordered-logical-model-vectors/v1",
                "logical_model_vector_sha256",
            ),
            "ordered_logical_projections_sha256": (
                "v2/native-trainer/profiled-checkpoint/ordered-logical-projections/v1",
                "logical_projection_sha256",
            ),
            "ordered_model_inputs_sha256": (
                "v2/native-trainer/profiled-checkpoint/ordered-model-inputs/v1",
                "model_input_float64_sha256",
            ),
            "ordered_supervised_targets_sha256": (
                "v2/native-trainer/profiled-checkpoint/ordered-supervised-targets/v1",
                "supervised_target_sha256",
            ),
            "ordered_target_values_sha256": (
                "v2/native-trainer/profiled-checkpoint/ordered-target-values/v1",
                "target_label_value_float64_sha256",
            ),
            "ordered_row_inventories_sha256": (
                "v2/native-trainer/profiled-checkpoint/ordered-row-inventories/v1",
                "row_inventory_sha256",
            ),
        }.items()
    }
    provisional_values: dict[str, Any] = dict(
        schema_version=PROFILED_SUPERVISED_CHECKPOINT_INVENTORY_V1_SCHEMA_VERSION,
        status=PROFILED_SUPERVISED_CHECKPOINT_STATUS,
        before_corpus=before_corpus,
        after_corpus=after_corpus,
        execution_authorization=execution_authorization,
        before_state=before_state,
        after_state=after_state,
        manifest_id=before_corpus.manifest_id,
        manifest_metadata_sha256=before_corpus.manifest_metadata_sha256,
        manifest_observation_context_sha256=before_corpus.manifest_observation_context_sha256,
        manifest_entry_chain_head_sha256=before_corpus.manifest_entry_chain_head_sha256,
        manifest_ordered_entry_identities_sha256=(
            before_corpus.manifest_ordered_entry_identities_sha256
        ),
        completion_event_sha256=before_corpus.completion_event_sha256,
        completion_ordered_page_root_sha256=before_corpus.completion_ordered_page_root_sha256,
        external_authorization_envelope_sha256=(
            before_corpus.external_authorization_envelope_sha256
        ),
        witness_id=before_corpus.witness_id,
        witness_namespace=before_corpus.witness_namespace,
        witness_public_key_sha256=before_corpus.witness_public_key_sha256,
        witness_sequence=before_corpus.witness_sequence,
        witness_previous_event_sha256=before_corpus.witness_previous_event_sha256,
        witness_accepted_at=before_corpus.witness_accepted_at,
        observation_time=before_corpus.observation_time,
        corpus_contract_sha256=before_corpus.corpus_contract_sha256,
        execution_authorization_inventory_equality_sha256=(
            execution_authorization.inventory_equality_sha256
        ),
        before_optimizer_input_inventory_sha256=before_input_sha256,
        after_optimizer_input_inventory_sha256=after_input_sha256,
        admitted_example_count=before_corpus.manifest_admitted_example_count,
        admitted_ordinals=before_corpus.admitted_ordinals,
        **ordered_arguments,
        feature_registry_sha256=before_corpus.feature_registry_sha256,
        feature_registry_abi_sha256=before_corpus.feature_registry_abi_sha256,
        logical_profile_selection_mask=before_corpus.logical_profile_selection_mask,
        logical_profile_selection_mask_sha256=(before_corpus.logical_profile_selection_mask_sha256),
        projection_schema_version=before_corpus.projection_schema_version,
        projection_implementation_sha256=before_corpus.projection_implementation_sha256,
        projection_configuration_sha256=before_corpus.projection_configuration_sha256,
        model_coordinate_inventory_sha256=(before_state.model_coordinate_inventory_sha256),
        before_model_state_identity_sha256=(before_state.model_state_content_inventory_sha256),
        after_model_state_identity_sha256=after_state.model_state_content_inventory_sha256,
        before_optimizer_state_identity_sha256=(
            before_state.optimizer_state_content_inventory_sha256
        ),
        after_optimizer_state_identity_sha256=(
            after_state.optimizer_state_content_inventory_sha256
        ),
        optimizer_implementation_artifact_bytes=implementation,
        optimizer_implementation_artifact_sha256=hashlib.sha256(implementation).hexdigest(),
        optimizer_implementation_artifact_byte_count=len(implementation),
        optimizer_configuration_artifact_json_bytes=configuration,
        optimizer_configuration_artifact_sha256=hashlib.sha256(configuration).hexdigest(),
        optimizer_configuration_artifact_byte_count=len(configuration),
        execution_environment_artifact_json_bytes=environment,
        execution_environment_artifact_sha256=hashlib.sha256(environment).hexdigest(),
        execution_environment_artifact_byte_count=len(environment),
        before_input_inventory_verified_at=before_input_inventory_verified_at,
        optimizer_started_at=optimizer_started_at,
        optimizer_completed_at=optimizer_completed_at,
        after_input_inventory_verified_at=after_input_inventory_verified_at,
        checkpoint_created_at=checkpoint_created_at,
        checkpoint_contract_implementation_sha256=(
            PROFILED_SUPERVISED_CHECKPOINT_IMPLEMENTATION_CONTRACT_SHA256
        ),
        checkpoint_header_json_sha256="0" * 64,
        checkpoint_bytes=b"placeholder",
        checkpoint_bytes_sha256="0" * 64,
        checkpoint_byte_count=len(b"placeholder"),
        checkpoint_inventory_sha256="0" * 64,
        corpus_inventory_equal_before_after_optimization=True,
        model_coordinates_equal_before_after_optimization=True,
        model_state_changed=True,
        optimizer_execution_independently_observed=False,
        in_memory_checkpoint_candidate_created=True,
        outcome_supervised_objective_only=True,
        behavior_receipt_bound=False,
        ppo_behavior_policy_terms_enabled=False,
        **_AUTHORITY_FALSE,
        _factory_seal=_FactorySeal(
            domain=_CHECKPOINT_INVENTORY_SEAL_DOMAIN,
            construction_token=_FACTORY_SEAL_TOKEN,
        ),
        _construction_token=_CHECKPOINT_INVENTORY_TOKEN,
    )
    provisional = object.__new__(ProfiledSupervisedCheckpointInventoryV1)
    for item in dataclass_fields(ProfiledSupervisedCheckpointInventoryV1):
        object.__setattr__(provisional, item.name, provisional_values[item.name])
    # Avoid calling dataclasses.replace: the final public object receives a new
    # seal, and no valid result ever exposes an unbound seal for different data.
    header_bytes = _canonical_bytes(
        _checkpoint_header_material(provisional),
        reason="PROFILED_CHECKPOINT_HEADER_ENCODING_INVALID",
    )
    checkpoint_bytes = _build_checkpoint_bytes(value=provisional, header_bytes=header_bytes)
    values = {
        item.name: getattr(provisional, item.name)
        for item in dataclass_fields(provisional)
        if item.name
        not in {
            "checkpoint_header_json_sha256",
            "checkpoint_bytes",
            "checkpoint_bytes_sha256",
            "checkpoint_byte_count",
            "checkpoint_inventory_sha256",
            "_factory_seal",
            "_construction_token",
        }
    }
    values.update(
        checkpoint_header_json_sha256=hashlib.sha256(header_bytes).hexdigest(),
        checkpoint_bytes=checkpoint_bytes,
        checkpoint_bytes_sha256=hashlib.sha256(checkpoint_bytes).hexdigest(),
        checkpoint_byte_count=len(checkpoint_bytes),
        checkpoint_inventory_sha256="0" * 64,
        _factory_seal=_FactorySeal(
            domain=_CHECKPOINT_INVENTORY_SEAL_DOMAIN,
            construction_token=_FACTORY_SEAL_TOKEN,
        ),
        _construction_token=_CHECKPOINT_INVENTORY_TOKEN,
    )
    unsealed_final = object.__new__(ProfiledSupervisedCheckpointInventoryV1)
    for item in dataclass_fields(ProfiledSupervisedCheckpointInventoryV1):
        object.__setattr__(unsealed_final, item.name, values[item.name])
    inventory_sha256 = stable_sha256(_checkpoint_inventory_material(unsealed_final))
    values["checkpoint_inventory_sha256"] = inventory_sha256
    return ProfiledSupervisedCheckpointInventoryV1(**values)


__all__ = (
    "PROFILED_SUPERVISED_CHECKPOINT_BINARY_MAGIC",
    "PROFILED_SUPERVISED_CHECKPOINT_BINARY_V1_SCHEMA_VERSION",
    "PROFILED_SUPERVISED_CHECKPOINT_IMPLEMENTATION_CONTRACT_SHA256",
    "PROFILED_SUPERVISED_CHECKPOINT_INVENTORY_V1_SCHEMA_VERSION",
    "PROFILED_SUPERVISED_CHECKPOINT_STATUS",
    "PROFILED_SUPERVISED_OPTIMIZATION_STATE_SNAPSHOT_V1_SCHEMA_VERSION",
    "PROFILED_SUPERVISED_TENSOR_STATE_ITEM_V1_SCHEMA_VERSION",
    "ProfiledSupervisedCheckpointInventoryV1",
    "ProfiledSupervisedCheckpointInventoryV1Error",
    "ProfiledSupervisedOptimizationStateSnapshotV1",
    "ProfiledSupervisedTensorStateItemV1",
    "build_authenticated_profiled_supervised_checkpoint_inventory_v1",
    "capture_profiled_supervised_optimization_state_snapshot_v1",
)
