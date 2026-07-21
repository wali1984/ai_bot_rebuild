from __future__ import annotations

import ast
import hashlib
import inspect
import json
import subprocess
import sys
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from v2.backend.app.services.native_trainer import feature_source_registry_v4 as registry_module
from v2.backend.app.services.native_trainer.durable_feature_snapshot_ledger import (
    OPTIONAL_EVENT_DEPENDENT_FEATURE_NAMES,
    feature_abi_contract,
    feature_requirement_classes_for_names,
    stable_sha256,
)
from v2.backend.app.services.native_trainer.feature_source_registry_v4 import (
    COINAPI_WSDS_TAPE_IMBALANCE_CONFIGURED_SOURCE_LABEL,
    COINAPI_WSDS_TAPE_IMBALANCE_OPTIONAL_FEATURE_NAMES,
    COINAPI_WSDS_TAPE_IMBALANCE_OPTIONAL_GROUP_ID,
    CONFLUENCE_CONFIGURED_SOURCE_LABEL,
    CONFLUENCE_OPTIONAL_FEATURE_NAMES,
    CONFLUENCE_OPTIONAL_GROUP_ID,
    FEATURE_SOURCE_REGISTRY_V4,
    FEATURE_SOURCE_REGISTRY_V4_ABI_SCHEMA_VERSION,
    FEATURE_SOURCE_REGISTRY_V4_ABI_SHA256,
    FEATURE_SOURCE_REGISTRY_V4_EXPECTED_CONFIGURED_SOURCE_LABELS,
    FEATURE_SOURCE_REGISTRY_V4_OPTIONAL_SLOT_COUNT,
    FEATURE_SOURCE_REGISTRY_V4_REQUIRED_SLOT_COUNT,
    FEATURE_SOURCE_REGISTRY_V4_REQUIREMENT_POLICY_ID,
    FEATURE_SOURCE_REGISTRY_V4_SCHEMA_VERSION,
    FEATURE_SOURCE_REGISTRY_V4_SHA256,
    FEATURE_SOURCE_REGISTRY_V4_SLOT_COUNT,
    FEATURE_SOURCE_REGISTRY_V4_SOURCE_LABEL_COUNT,
    MORALIS_CONFIGURED_SOURCE_LABEL,
    MORALIS_OPTIONAL_FEATURE_NAMES,
    MORALIS_OPTIONAL_GROUP_ID,
    REQUIREMENT_OPTIONAL_EVENT_DEPENDENT,
    REQUIREMENT_REQUIRED,
    FeatureSourceRegistrySlotV4,
    FeatureSourceRegistryV4ValidationError,
    build_feature_source_registry_v4,
    canonical_feature_source_registry_v4_json,
    feature_source_registry_v4_contract,
)
from v2.backend.app.services.native_trainer.ordered_feature_tensor_spec_v3 import (
    FEATURE_SPEC,
)

_NAMES = tuple(name for name, _source_label in FEATURE_SPEC)
_REQUIREMENTS = feature_requirement_classes_for_names(_NAMES)


def _spec_with(
    index: int,
    *,
    name: str | None = None,
    source: str | None = None,
) -> tuple[tuple[str, str], ...]:
    values = list(FEATURE_SPEC)
    current_name, current_source = values[index]
    values[index] = (
        current_name if name is None else name,
        current_source if source is None else source,
    )
    return tuple(values)


def _requirements_with(index: int, value: str) -> tuple[str, ...]:
    requirements = list(_REQUIREMENTS)
    requirements[index] = value
    return tuple(requirements)


def _assert_reason(
    exc_info: pytest.ExceptionInfo[FeatureSourceRegistryV4ValidationError], reason: str
) -> None:
    assert reason in exc_info.value.reasons


def test_registry_freezes_exact_current_feature_abi_and_policy() -> None:
    registry = FEATURE_SOURCE_REGISTRY_V4

    assert registry.schema_version == FEATURE_SOURCE_REGISTRY_V4_SCHEMA_VERSION
    assert registry.abi_schema_version == FEATURE_SOURCE_REGISTRY_V4_ABI_SCHEMA_VERSION
    assert registry.abi_sha256 == FEATURE_SOURCE_REGISTRY_V4_ABI_SHA256
    assert (
        registry.feature_requirement_policy_id == FEATURE_SOURCE_REGISTRY_V4_REQUIREMENT_POLICY_ID
    )
    assert registry.feature_requirement_policy_id == "v2_hybrid_feature_requirements_v2"
    assert registry.registry_sha256 == FEATURE_SOURCE_REGISTRY_V4_SHA256
    assert registry.slot_count == FEATURE_SOURCE_REGISTRY_V4_SLOT_COUNT == len(FEATURE_SPEC) == 446
    assert registry.required_slot_count == FEATURE_SOURCE_REGISTRY_V4_REQUIRED_SLOT_COUNT == 383
    assert (
        registry.optional_event_dependent_slot_count
        == FEATURE_SOURCE_REGISTRY_V4_OPTIONAL_SLOT_COUNT
        == 63
    )
    assert stable_sha256(feature_abi_contract(_NAMES)) == FEATURE_SOURCE_REGISTRY_V4_ABI_SHA256


def test_every_slot_binds_ordinal_name_source_and_requirement() -> None:
    expected = tuple(
        (ordinal, name, source, _REQUIREMENTS[ordinal])
        for ordinal, (name, source) in enumerate(FEATURE_SPEC)
    )
    actual = tuple(
        (
            slot.ordinal,
            slot.feature_name,
            slot.configured_source_label,
            slot.requirement_class,
        )
        for slot in FEATURE_SOURCE_REGISTRY_V4.slots
    )

    assert actual == expected
    assert len({slot.feature_name for slot in FEATURE_SOURCE_REGISTRY_V4.slots}) == 446
    assert (
        sum(
            slot.requirement_class == REQUIREMENT_REQUIRED
            for slot in FEATURE_SOURCE_REGISTRY_V4.slots
        )
        == 383
    )
    assert (
        sum(
            slot.requirement_class == REQUIREMENT_OPTIONAL_EVENT_DEPENDENT
            for slot in FEATURE_SOURCE_REGISTRY_V4.slots
        )
        == 63
    )
    assert {
        slot.feature_name
        for slot in FEATURE_SOURCE_REGISTRY_V4.slots
        if slot.requirement_class == REQUIREMENT_OPTIONAL_EVENT_DEPENDENT
    } == OPTIONAL_EVENT_DEPENDENT_FEATURE_NAMES


def test_registry_includes_all_40_exact_configured_source_labels() -> None:
    registry = FEATURE_SOURCE_REGISTRY_V4

    assert registry.source_label_count == FEATURE_SOURCE_REGISTRY_V4_SOURCE_LABEL_COUNT == 40
    assert (
        registry.configured_source_labels
        == FEATURE_SOURCE_REGISTRY_V4_EXPECTED_CONFIGURED_SOURCE_LABELS
    )
    assert registry.configured_source_labels == tuple(
        sorted({source_label for _name, source_label in FEATURE_SPEC})
    )


@pytest.mark.parametrize(
    ("group_index", "group_id", "source_label", "feature_names", "ordinals"),
    (
        (
            0,
            COINAPI_WSDS_TAPE_IMBALANCE_OPTIONAL_GROUP_ID,
            COINAPI_WSDS_TAPE_IMBALANCE_CONFIGURED_SOURCE_LABEL,
            COINAPI_WSDS_TAPE_IMBALANCE_OPTIONAL_FEATURE_NAMES,
            (133,),
        ),
        (
            1,
            MORALIS_OPTIONAL_GROUP_ID,
            MORALIS_CONFIGURED_SOURCE_LABEL,
            MORALIS_OPTIONAL_FEATURE_NAMES,
            tuple(range(259, 266)),
        ),
        (
            2,
            CONFLUENCE_OPTIONAL_GROUP_ID,
            CONFLUENCE_CONFIGURED_SOURCE_LABEL,
            CONFLUENCE_OPTIONAL_FEATURE_NAMES,
            tuple(range(266, 281)),
        ),
    ),
)
def test_optional_groups_are_exact_name_scoped_and_optional(
    group_index: int,
    group_id: str,
    source_label: str,
    feature_names: tuple[str, ...],
    ordinals: tuple[int, ...],
) -> None:
    group = FEATURE_SOURCE_REGISTRY_V4.optional_source_groups[group_index]

    assert group.group_id == group_id
    assert group.configured_source_label == source_label
    assert group.feature_names == feature_names
    assert group.slot_ordinals == ordinals
    assert group.requirement_class == REQUIREMENT_OPTIONAL_EVENT_DEPENDENT
    assert all(
        FEATURE_SOURCE_REGISTRY_V4.slots[ordinal].requirement_class
        == REQUIREMENT_OPTIONAL_EVENT_DEPENDENT
        for ordinal in ordinals
    )


def test_coinapi_optional_group_does_not_reclassify_shared_microstructure_source() -> None:
    microstructure_slots = tuple(
        slot
        for slot in FEATURE_SOURCE_REGISTRY_V4.slots
        if slot.configured_source_label
        == COINAPI_WSDS_TAPE_IMBALANCE_CONFIGURED_SOURCE_LABEL
    )

    assert tuple(
        slot.feature_name
        for slot in microstructure_slots
        if slot.requirement_class == REQUIREMENT_OPTIONAL_EVENT_DEPENDENT
    ) == COINAPI_WSDS_TAPE_IMBALANCE_OPTIONAL_FEATURE_NAMES
    assert {
        slot.feature_name
        for slot in microstructure_slots
        if slot.requirement_class == "REQUIRED"
    } == {
        "depth_vs_tape_divergence",
        "microstructure_liquidity_depth",
        "microprice",
        "micro_volatility",
        "toxicity_proxy",
        "tape_imbalance",
        "order_flow_imbalance",
        "micro_price",
    }


def test_contract_is_canonical_detached_and_digest_complete() -> None:
    contract = feature_source_registry_v4_contract(FEATURE_SOURCE_REGISTRY_V4)
    canonical = canonical_feature_source_registry_v4_json(FEATURE_SOURCE_REGISTRY_V4)

    assert json.loads(canonical) == contract
    digest_material = dict(contract)
    assert digest_material.pop("registry_sha256") == FEATURE_SOURCE_REGISTRY_V4_SHA256
    encoded = json.dumps(
        digest_material,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    assert hashlib.sha256(encoded).hexdigest() == FEATURE_SOURCE_REGISTRY_V4_SHA256
    assert len(contract["slots"]) == 446
    assert contract["slots"][133] == {
        "ordinal": 133,
        "feature_name": "coinapi_wsds_tape_imbalance",
        "configured_source_label": "v2:market:microstructure",
        "requirement_class": "OPTIONAL_EVENT_DEPENDENT",
    }
    assert contract["slots"][259] == {
        "ordinal": 259,
        "feature_name": "moralis_exchange_inflow_usd",
        "configured_source_label": "v2:features:moralis",
        "requirement_class": "OPTIONAL_EVENT_DEPENDENT",
    }
    contract["slots"][0]["feature_name"] = "caller_mutation"
    assert FEATURE_SOURCE_REGISTRY_V4.slots[0].feature_name == "last_price"


def test_registry_is_audit_only_and_all_authority_remains_false() -> None:
    registry = FEATURE_SOURCE_REGISTRY_V4
    assert registry.audit_only is True
    authority_values = (
        registry.runtime_source_reads_performed,
        registry.source_registry_authenticated,
        registry.resolver_branch_capture_authenticated,
        registry.source_receipts_authenticated,
        registry.feature_snapshot_published,
        registry.consumer_eligible,
        registry.feature_publication_authorized,
        registry.trainer_admission_authorized,
        registry.prediction_authorized,
        registry.paper_trading_authorized,
        registry.live_execution_authorized,
    )

    assert all(value is False for value in authority_values)
    contract = feature_source_registry_v4_contract(registry)
    assert contract["authorization"]["audit_only"] is True
    assert all(
        value is False for name, value in contract["authorization"].items() if name != "audit_only"
    )
    assert "UNAUTHENTICATED_UNWIRED" in registry.evidence_classification
    assert "NON_CONSUMABLE" in registry.downstream_status
    assert not {
        "event_time",
        "ingested_at",
        "available_at",
        "generated_at",
        "feature_cutoff",
        "decision_time",
        "execution_time",
        "freshness_threshold",
        "market_threshold",
    } & set(contract)


def test_module_has_no_runtime_io_or_clock_surface() -> None:
    tree = ast.parse(inspect.getsource(registry_module))
    imported_roots: set[str] = set()
    called_names: set[str] = set()
    called_attributes: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.partition(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported_roots.add(node.module.partition(".")[0])
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                called_names.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                called_attributes.add(node.func.attr)

    assert not imported_roots & {
        "aiohttp",
        "datetime",
        "httpx",
        "os",
        "pathlib",
        "redis",
        "requests",
        "socket",
        "sqlite3",
        "subprocess",
        "time",
        "urllib",
    }
    assert not called_names & {"__import__", "compile", "eval", "exec", "input", "open"}
    assert not called_attributes & {
        "connect",
        "execute",
        "get",
        "now",
        "publish",
        "read",
        "read_bytes",
        "read_text",
        "request",
        "set",
        "sleep",
        "time",
        "urlopen",
        "utcnow",
        "write",
        "write_bytes",
        "write_text",
    }


def test_registry_import_is_isolated_and_has_no_mutating_audit_events() -> None:
    repo_root = Path(__file__).resolve().parents[6]
    script = r"""
import json
import os
import sys

repo_root = sys.argv[1]
events = []
write_flags = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
forbidden_events = {
    "os.chdir",
    "os.exec",
    "os.mkdir",
    "os.posix_spawn",
    "os.remove",
    "os.rename",
    "os.rmdir",
    "os.spawn",
    "os.system",
    "socket.bind",
    "socket.connect",
    "subprocess.Popen",
}

def audit(event, args):
    if event in forbidden_events:
        events.append(event)
        return
    if event == "open":
        mode = args[1] if len(args) > 1 else None
        flags = args[2] if len(args) > 2 else None
        mode_writes = isinstance(mode, str) and any(value in mode for value in "wax+")
        flags_write = isinstance(flags, int) and bool(flags & write_flags)
        if mode_writes or flags_write:
            events.append("open:write")

sys.addaudithook(audit)
sys.path.insert(0, repo_root)

from v2.backend.app.services.native_trainer.feature_source_registry_v4 import (
    FEATURE_SOURCE_REGISTRY_V4,
)

loaded_v2_modules = sorted(
    name for name in sys.modules if name == "v2" or name.startswith("v2.")
)
print(
    json.dumps(
        {
            "events": events,
            "loaded_v2_modules": loaded_v2_modules,
            "registry_sha256": FEATURE_SOURCE_REGISTRY_V4.registry_sha256,
            "slot_count": FEATURE_SOURCE_REGISTRY_V4.slot_count,
        },
        sort_keys=True,
    )
)
"""
    completed = subprocess.run(  # noqa: S603 - fixed interpreter and static audit script
        [sys.executable, "-I", "-B", "-c", script, str(repo_root)],
        cwd="/",
        env={"PYTHONDONTWRITEBYTECODE": "1", "PYTHONHASHSEED": "0"},
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["events"] == []
    assert result["slot_count"] == 446
    assert result["registry_sha256"] == FEATURE_SOURCE_REGISTRY_V4_SHA256
    assert result["loaded_v2_modules"] == [
        "v2",
        "v2.backend",
        "v2.backend.app",
        "v2.backend.app.services",
        "v2.backend.app.services.native_trainer",
        "v2.backend.app.services.native_trainer.durable_feature_snapshot_ledger",
        "v2.backend.app.services.native_trainer.feature_source_registry_v4",
        "v2.backend.app.services.native_trainer.ordered_feature_tensor_spec_v3",
    ]


def test_registry_and_nested_records_are_immutable_and_factory_only() -> None:
    with pytest.raises(FrozenInstanceError):
        FEATURE_SOURCE_REGISTRY_V4.slot_count = 1  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        FEATURE_SOURCE_REGISTRY_V4.slots[0].feature_name = "changed"  # type: ignore[misc]
    with pytest.raises(FeatureSourceRegistryV4ValidationError) as exc_info:
        FeatureSourceRegistrySlotV4(
            ordinal=0,
            feature_name="last_price",
            configured_source_label="v2:market:prices",
            requirement_class=REQUIREMENT_REQUIRED,
            _construction_token=object(),
        )
    _assert_reason(exc_info, "FEATURE_SOURCE_REGISTRY_V4_FACTORY_CONSTRUCTION_REQUIRED")


@pytest.mark.parametrize(
    ("feature_spec", "reason"),
    (
        (list(FEATURE_SPEC), "FEATURE_SOURCE_REGISTRY_V4_FEATURE_SPEC_NOT_EXACT_TUPLE"),
        (FEATURE_SPEC[:-1], "FEATURE_SOURCE_REGISTRY_V4_SLOT_COUNT_MISMATCH"),
        (
            (list(FEATURE_SPEC[0]), *FEATURE_SPEC[1:]),
            "FEATURE_SOURCE_REGISTRY_V4_FEATURE_SPEC_ITEM_INVALID",
        ),
        (
            _spec_with(1, name=FEATURE_SPEC[0][0]),
            "FEATURE_SOURCE_REGISTRY_V4_FEATURE_NAME_DUPLICATE",
        ),
        (
            _spec_with(0, name=" leading_space"),
            "FEATURE_SOURCE_REGISTRY_V4_FEATURE_NAME_INVALID",
        ),
        (
            _spec_with(0, source="v2:market:prices\nforged"),
            "FEATURE_SOURCE_REGISTRY_V4_SOURCE_LABEL_INVALID",
        ),
    ),
)
def test_feature_spec_types_shapes_duplicates_and_labels_fail_closed(
    feature_spec: object,
    reason: str,
) -> None:
    with pytest.raises(FeatureSourceRegistryV4ValidationError) as exc_info:
        build_feature_source_registry_v4(feature_spec, _REQUIREMENTS)
    _assert_reason(exc_info, reason)


class _StringSubclass(str):
    pass


@pytest.mark.parametrize(
    ("feature_spec", "reason"),
    (
        (
            _spec_with(0, name=_StringSubclass(FEATURE_SPEC[0][0])),
            "FEATURE_SOURCE_REGISTRY_V4_FEATURE_NAME_INVALID",
        ),
        (
            _spec_with(0, source=_StringSubclass(FEATURE_SPEC[0][1])),
            "FEATURE_SOURCE_REGISTRY_V4_SOURCE_LABEL_INVALID",
        ),
    ),
)
def test_string_subclasses_are_rejected_before_hash_or_equality_hooks(
    feature_spec: object,
    reason: str,
) -> None:
    with pytest.raises(FeatureSourceRegistryV4ValidationError) as exc_info:
        build_feature_source_registry_v4(feature_spec, _REQUIREMENTS)
    _assert_reason(exc_info, reason)


@pytest.mark.parametrize(
    ("requirements", "reason"),
    (
        (list(_REQUIREMENTS), "FEATURE_SOURCE_REGISTRY_V4_REQUIREMENTS_NOT_EXACT_TUPLE"),
        (_REQUIREMENTS[:-1], "FEATURE_SOURCE_REGISTRY_V4_REQUIREMENT_DIMENSION_MISMATCH"),
        (
            _requirements_with(0, "OPTIONAL"),
            "FEATURE_SOURCE_REGISTRY_V4_REQUIREMENT_CLASS_INVALID",
        ),
        (
            _requirements_with(0, REQUIREMENT_OPTIONAL_EVENT_DEPENDENT),
            "FEATURE_SOURCE_REGISTRY_V4_REQUIREMENT_POLICY_MISMATCH",
        ),
        (
            _requirements_with(259, REQUIREMENT_REQUIRED),
            "FEATURE_SOURCE_REGISTRY_V4_REQUIREMENT_POLICY_MISMATCH",
        ),
    ),
)
def test_requirement_types_dimensions_values_and_policy_fail_closed(
    requirements: object,
    reason: str,
) -> None:
    with pytest.raises(FeatureSourceRegistryV4ValidationError) as exc_info:
        build_feature_source_registry_v4(FEATURE_SPEC, requirements)
    _assert_reason(exc_info, reason)


def test_name_or_order_change_cannot_reuse_pinned_abi() -> None:
    renamed = _spec_with(0, name="last_price_changed")
    reordered = list(FEATURE_SPEC)
    reordered[0], reordered[1] = reordered[1], reordered[0]

    for changed in (renamed, tuple(reordered)):
        changed_names = tuple(name for name, _source_label in changed)
        changed_requirements = feature_requirement_classes_for_names(changed_names)
        with pytest.raises(FeatureSourceRegistryV4ValidationError) as exc_info:
            build_feature_source_registry_v4(changed, changed_requirements)
        _assert_reason(exc_info, "FEATURE_SOURCE_REGISTRY_V4_ABI_SHA256_MISMATCH")


def test_source_label_change_is_detected_beyond_name_only_abi() -> None:
    changed = list(FEATURE_SPEC)
    changed[0] = (changed[0][0], changed[4][1])
    changed[4] = (changed[4][0], FEATURE_SPEC[0][1])
    assert tuple(name for name, _source in changed) == _NAMES
    assert stable_sha256(feature_abi_contract(_NAMES)) == FEATURE_SOURCE_REGISTRY_V4_ABI_SHA256

    with pytest.raises(FeatureSourceRegistryV4ValidationError) as exc_info:
        build_feature_source_registry_v4(tuple(changed), _REQUIREMENTS)
    _assert_reason(exc_info, "FEATURE_SOURCE_REGISTRY_V4_REGISTRY_SHA256_MISMATCH")


def test_optional_group_source_reassignment_fails_closed() -> None:
    changed = list(FEATURE_SPEC)
    changed[259] = (changed[259][0], CONFLUENCE_CONFIGURED_SOURCE_LABEL)
    changed[266] = (changed[266][0], MORALIS_CONFIGURED_SOURCE_LABEL)

    with pytest.raises(FeatureSourceRegistryV4ValidationError) as exc_info:
        build_feature_source_registry_v4(tuple(changed), _REQUIREMENTS)
    _assert_reason(exc_info, "FEATURE_SOURCE_REGISTRY_V4_OPTIONAL_GROUPS_MISMATCH")


def test_forged_authority_or_group_ordinal_fails_as_contract_error() -> None:
    with pytest.raises(FeatureSourceRegistryV4ValidationError) as authority_exc:
        replace(FEATURE_SOURCE_REGISTRY_V4, trainer_admission_authorized=True)
    _assert_reason(authority_exc, "FEATURE_SOURCE_REGISTRY_V4_AUTHORITY_MUST_REMAIN_FALSE")

    with pytest.raises(FeatureSourceRegistryV4ValidationError) as audit_only_exc:
        replace(FEATURE_SOURCE_REGISTRY_V4, audit_only=False)
    _assert_reason(audit_only_exc, "FEATURE_SOURCE_REGISTRY_V4_AUDIT_ONLY_MUST_REMAIN_TRUE")

    with pytest.raises(FeatureSourceRegistryV4ValidationError) as ordinal_exc:
        coinapi_group = FEATURE_SOURCE_REGISTRY_V4.optional_source_groups[0]
        replace(coinapi_group, slot_ordinals=(999,))
    _assert_reason(ordinal_exc, "FEATURE_SOURCE_REGISTRY_V4_OPTIONAL_GROUP_ORDINAL_INVALID")


def test_public_contract_rejects_non_registry_objects() -> None:
    for value in ({}, None, object()):
        with pytest.raises(FeatureSourceRegistryV4ValidationError) as exc_info:
            feature_source_registry_v4_contract(value)  # type: ignore[arg-type]
        _assert_reason(exc_info, "FEATURE_SOURCE_REGISTRY_V4_NOT_EXACT_REGISTRY")


def test_builder_reproduces_the_single_pinned_registry() -> None:
    rebuilt = build_feature_source_registry_v4(FEATURE_SPEC, _REQUIREMENTS)

    assert rebuilt == FEATURE_SOURCE_REGISTRY_V4
    assert rebuilt.registry_sha256 == FEATURE_SOURCE_REGISTRY_V4_SHA256
    assert feature_source_registry_v4_contract(rebuilt) == feature_source_registry_v4_contract(
        FEATURE_SOURCE_REGISTRY_V4
    )
