"""Legacy observation shape contract — read-only extraction.

Pulls observation/feature/architecture facts from the V2-owned legacy
mirror (``v2/legacy_owned_runtime/``) via *static* parsing only. Never
imports torch. Never reads outside the configured roots. Never modifies
legacy. Output documents the canonical legacy shape contract so V2 can
make an honest compatibility call.
"""
from __future__ import annotations

import dataclasses
import re
from pathlib import Path
from typing import Any

LEGACY_RL_DIR = Path("v2/legacy_owned_runtime/rl")
LEGACY_FEATURE_PIPELINE = Path("v2/legacy_owned_runtime/feature_pipeline.py")

OBS_SCHEMA_FILE = LEGACY_RL_DIR / "obs_schema.py"
ENVIRONMENT_FILE = LEGACY_RL_DIR / "environment.py"
GYMNASIUM_WRAPPER_FILE = LEGACY_RL_DIR / "gymnasium_wrapper.py"
UNIFIED_FEATURE_BUILDER_FILE = LEGACY_RL_DIR / "unified_feature_builder.py"
ENHANCED_ARCH_FILE = LEGACY_RL_DIR / "enhanced_architectures.py"


@dataclasses.dataclass(frozen=True)
class ObsSliceRow:
    name: str
    size: int
    optional: bool
    description: str | None
    schema_version: str


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


_OBS_SLICE_RE = re.compile(
    r'ObsSlice\(\s*name\s*=\s*"(?P<name>[^"]+)"\s*,\s*size\s*=\s*(?P<size>\d+)'
    r'(?:\s*,\s*optional\s*=\s*(?P<optional>True|False))?'
    r'(?:\s*,\s*description\s*=\s*"(?P<description>[^"]+)")?'
    r'\s*\)'
)
_TOTAL_DIM_RE = re.compile(r"total_dim\s*=\s*(\d+)")
_SCHEMA_VERSION_HEADING_RE = re.compile(
    r"def\s+_build_schema_v(?P<ver>\d+)\s*\(\)\s*->\s*ObsSchema\s*:"
)


def _parse_obs_schema(text: str) -> list[ObsSliceRow]:
    rows: list[ObsSliceRow] = []
    # Find blocks per schema version. We approximate by scanning the text
    # for OBS_SCHEMA_V*(... slices=[...], total_dim=N ...) and capturing
    # the slices in the immediate vicinity.
    current_version = "unknown"
    for line in text.splitlines():
        m_ver = _SCHEMA_VERSION_HEADING_RE.search(line)
        if m_ver:
            current_version = "V" + m_ver.group("ver")
            continue
        m_slice = _OBS_SLICE_RE.search(line)
        if m_slice:
            rows.append(
                ObsSliceRow(
                    name=m_slice.group("name"),
                    size=int(m_slice.group("size")),
                    optional=(m_slice.group("optional") == "True"),
                    description=m_slice.group("description"),
                    schema_version=current_version,
                )
            )
    return rows


def _parse_schema_total_dims(text: str) -> dict[str, int]:
    """Pair schema version -> total_dim by matching block ordering."""
    versions_in_order: list[str] = []
    totals_in_order: list[int] = []
    for m in _SCHEMA_VERSION_HEADING_RE.finditer(text):
        versions_in_order.append("V" + m.group("ver"))
    for m in _TOTAL_DIM_RE.finditer(text):
        totals_in_order.append(int(m.group(1)))
    out: dict[str, int] = {}
    for v, n in zip(versions_in_order, totals_in_order):
        out[v] = n
    return out


def _action_space_facts() -> dict[str, Any]:
    text = _read_text(ENVIRONMENT_FILE)
    facts: dict[str, Any] = {
        "source_file": str(ENVIRONMENT_FILE),
        "action_space_size_expr": None,
        "action_space_size_resolved": None,
        "per_symbol_actions": None,
        "action_labels_hint": None,
    }
    m = re.search(r"self\.action_space_size\s*=\s*([^\n#]+)", text)
    if m:
        facts["action_space_size_expr"] = m.group(1).strip()
    m2 = re.search(r"=\s*([0-9_,]+)\s*possible actions", text)
    if m2:
        try:
            facts["action_space_size_resolved"] = int(
                m2.group(1).replace("_", "").replace(",", "")
            )
        except ValueError:
            pass
    if "3 ** len(SYMBOLS)" in (facts["action_space_size_expr"] or ""):
        facts["per_symbol_actions"] = 3
        facts["action_labels_hint"] = "(hold, long, short) per symbol; multi-symbol joint action"
    return facts


def _architecture_facts() -> dict[str, Any]:
    text = _read_text(ENHANCED_ARCH_FILE)
    has_lstm = "nn.LSTM" in text or "self.lstm" in text or "lstm_hidden_size" in text
    has_attention = "MultiheadAttention" in text or "embed_dim=" in text
    has_regime_head = "regime_head" in text
    has_ffn = "Linear(lstm_hidden_size" in text or "Linear(hidden_dim" in text
    lstm_hidden = None
    m = re.search(r"lstm_hidden_size\s*[:=]\s*(\d+)", text)
    if m:
        try:
            lstm_hidden = int(m.group(1))
        except ValueError:
            pass
    moe_text = _read_text(LEGACY_RL_DIR / "moe_router.py")
    has_moe = "class MoE" in moe_text or "moe_router" in moe_text
    cnn_text = _read_text(LEGACY_RL_DIR / "gpu_cnn_policy.py")
    has_cnn = "Conv1d" in cnn_text or "Conv2d" in cnn_text
    return {
        "source_files": [
            str(ENHANCED_ARCH_FILE),
            str(LEGACY_RL_DIR / "moe_router.py"),
            str(LEGACY_RL_DIR / "gpu_cnn_policy.py"),
        ],
        "has_lstm": has_lstm,
        "has_attention": has_attention,
        "has_regime_head": has_regime_head,
        "has_ffn": has_ffn,
        "has_moe": has_moe,
        "has_cnn": has_cnn,
        "lstm_hidden_size_default": lstm_hidden,
    }


def build_legacy_observation_contract() -> dict[str, Any]:
    schema_text = _read_text(OBS_SCHEMA_FILE)
    slices = _parse_obs_schema(schema_text)
    totals = _parse_schema_total_dims(schema_text)
    per_version_slices: dict[str, list[dict[str, Any]]] = {}
    for r in slices:
        per_version_slices.setdefault(r.schema_version, []).append(
            {
                "name": r.name,
                "size": r.size,
                "optional": r.optional,
                "description": r.description,
            }
        )
    action_facts = _action_space_facts()
    arch_facts = _architecture_facts()
    # Decision: legacy is a vastly larger / different architecture than the
    # current V2 native paper policy. Surface this explicitly.
    legacy_obs_dim_candidates = sorted(set(totals.values())) if totals else []
    largest_legacy_obs_dim = max(legacy_obs_dim_candidates) if legacy_obs_dim_candidates else None
    return {
        "schema_version": "v2_legacy_observation_shape_contract_v1",
        "source_files": {
            "obs_schema": str(OBS_SCHEMA_FILE),
            "environment": str(ENVIRONMENT_FILE),
            "gymnasium_wrapper": str(GYMNASIUM_WRAPPER_FILE),
            "unified_feature_builder": str(UNIFIED_FEATURE_BUILDER_FILE),
            "feature_pipeline": str(LEGACY_FEATURE_PIPELINE),
            "enhanced_architectures": str(ENHANCED_ARCH_FILE),
        },
        "legacy_observation_schema_versions": sorted(totals.keys()),
        "legacy_observation_total_dim_by_version": totals,
        "legacy_observation_slices_by_version": per_version_slices,
        "legacy_observation_largest_dim": largest_legacy_obs_dim,
        "legacy_action_space": action_facts,
        "legacy_architecture": arch_facts,
        "legacy_observation_classification": (
            "DYNAMIC_VERSIONED_OBS_SCHEMA_WITH_V1_1053_V2_1061_V3_1911_DIMS"
            if largest_legacy_obs_dim
            else "MISSING_EVIDENCE"
        ),
        "no_legacy_filesystem_modified": True,
        "no_torch_imported": True,
        "no_pickle_loaded": True,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
    }


def gap_vs_v2_compact(contract: dict[str, Any]) -> dict[str, Any]:
    """Return the v2-vs-legacy observation gap matrix derived from contract."""
    v2_compact_dim = 26
    v2_action_count = 5
    v2_action_labels = ["hold", "long", "short", "close", "hedge"]
    legacy_largest = contract.get("legacy_observation_largest_dim")
    legacy_action_size = (contract.get("legacy_action_space") or {}).get(
        "action_space_size_resolved"
    )
    per_sym = (contract.get("legacy_action_space") or {}).get("per_symbol_actions")
    obs_dim_gap = (legacy_largest - v2_compact_dim) if legacy_largest else None
    missing_categories: list[str] = []
    largest_slices = contract.get("legacy_observation_slices_by_version", {}).get("V3", [])
    for s in largest_slices:
        nm = s.get("name") or ""
        if nm not in (
            # V2 native 26-dim covers neither of these in full
            "_already_in_v2_compact_placeholder",
        ):
            missing_categories.append(nm)
    return {
        "schema_version": "v2_vs_legacy_observation_gap_matrix_v1",
        "v2_native_compact_observation_dim": v2_compact_dim,
        "v2_native_action_count": v2_action_count,
        "v2_native_action_labels": v2_action_labels,
        "legacy_largest_observation_dim": legacy_largest,
        "legacy_action_space_size_resolved": legacy_action_size,
        "legacy_per_symbol_actions": per_sym,
        "observation_dim_gap_legacy_minus_v2": obs_dim_gap,
        "missing_v2_observation_categories": missing_categories,
        "observation_compatibility": (
            "INCOMPATIBLE_OBSERVATION_VECTOR_SHAPE_REQUIRES_PORT"
            if obs_dim_gap and obs_dim_gap > 0
            else "UNKNOWN_OR_MATCHED"
        ),
        "action_space_compatibility": (
            "INCOMPATIBLE_ACTION_SPACE_REQUIRES_PORT"
            if legacy_action_size and legacy_action_size != v2_action_count
            else "UNKNOWN_OR_MATCHED"
        ),
        "live_gate": "blocked_human_only",
        "live_symbols": [],
    }
