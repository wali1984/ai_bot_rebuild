from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.trading_configuration_inventory_v2 import (
    CLASSIFICATION_SCHEMA_VERSION,
    build_inventory,
    discover_candidates,
)


def _write_source(path: Path, source: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def test_discovers_each_declared_source_kind_deterministically(tmp_path: Path) -> None:
    source_path = tmp_path / "v2/backend/app/services/risk/policy.py"
    _write_source(
        source_path,
        """
import enum
import os
from dataclasses import dataclass

PAPER_MAX_LEVERAGE = float(os.getenv("PAPER_MAX_LEVERAGE", "2.0"))

class TradeAction(enum.StrEnum):
    REMAIN_FLAT = "remain_flat"

@dataclass(frozen=True)
class RiskPolicyConfig:
    loss_probability: float = 0.40

def admit_trade(confidence: float) -> bool:
    return confidence >= 0.65
""".lstrip(),
    )

    first = discover_candidates(tmp_path, (Path("v2/backend/app"),))
    second = discover_candidates(tmp_path, (Path("v2/backend/app"),))

    assert first == second
    assert {item.kind for item in first} == {
        "config_field",
        "constant",
        "enum",
        "environment",
        "inline_comparison",
    }
    assert len({item.configuration_id for item in first}) == len(first)
    assert all(len(item.source_sha256) == 64 for item in first)
    assert next(item for item in first if item.name == "PAPER_MAX_LEVERAGE").unit == "ratio"


def test_unreviewed_candidate_keeps_phase_one_fail_closed(tmp_path: Path) -> None:
    _write_source(
        tmp_path / "v2/backend/app/services/paper/policy.py",
        "PAPER_ENTRY_CONFIDENCE = 0.75\n",
    )
    inventory = build_inventory(
        repo_root=tmp_path,
        scan_roots=(Path("v2/backend/app"),),
        classifications={},
    )

    assert inventory["coverage"]["discovered_values"] == 1
    assert inventory["coverage"]["classified_values"] == 0
    assert inventory["coverage"]["unclassified_trading_values"] == 1
    assert inventory["coverage"]["confirmed_manual_static_trading_authorities"] == 0
    assert inventory["coverage"]["manual_static_trading_authorities"] is None
    assert inventory["acceptance_status"]["phase1_complete"] is False


def test_exact_classification_counters_and_manual_authority(tmp_path: Path) -> None:
    _write_source(
        tmp_path / "v2/backend/app/services/execution/policy.py",
        "MIN_NOTIONAL_USD = 5.0\nENTRY_SCORE = 0.60\n",
    )
    candidates = discover_candidates(tmp_path, (Path("v2/backend/app"),))
    by_name = {item.name: item for item in candidates}
    classifications = {
        by_name["MIN_NOTIONAL_USD"].configuration_id: {
            "category": "A",
            "classification_rationale": "venue minimum is a physical fact",
            "manual_static_final_authority": False,
        },
        by_name["ENTRY_SCORE"].configuration_id: {
            "category": "E",
            "classification_rationale": "score directly selects entry",
            "manual_static_final_authority": True,
        },
    }
    inventory = build_inventory(
        repo_root=tmp_path,
        scan_roots=(Path("v2/backend/app"),),
        classifications=classifications,
    )

    assert inventory["coverage"]["unclassified_trading_values"] == 0
    assert inventory["coverage"]["category_counts"] == {
        "A": 1,
        "B": 0,
        "C": 0,
        "D": 0,
        "E": 1,
    }
    assert inventory["coverage"]["manual_static_trading_authorities"] == 1
    assert inventory["acceptance_status"]["phase1_complete"] is False


def test_phase_one_pass_requires_no_unclassified_or_manual_authority(tmp_path: Path) -> None:
    _write_source(
        tmp_path / "v2/backend/app/services/execution/venue.py",
        "MIN_NOTIONAL_USD = 5.0\n",
    )
    candidate = discover_candidates(tmp_path, (Path("v2/backend/app"),))[0]
    inventory = build_inventory(
        repo_root=tmp_path,
        scan_roots=(Path("v2/backend/app"),),
        classifications={
            candidate.configuration_id: {
                "category": "A",
                "classification_rationale": "venue fact",
                "manual_static_final_authority": False,
            }
        },
    )

    assert inventory["acceptance_status"] == {
        "phase1_complete": True,
        "unclassified_trading_values": 0,
        "manual_static_trading_authorities": 0,
    }


@pytest.mark.parametrize(
    "classification",
    [
        {
            "category": "Z",
            "classification_rationale": "invalid",
            "manual_static_final_authority": False,
        },
        {
            "category": "A",
            "classification_rationale": "",
            "manual_static_final_authority": False,
        },
        {
            "category": "A",
            "classification_rationale": "venue",
            "manual_static_final_authority": True,
        },
    ],
)
def test_classification_file_rejects_invalid_authority_contract(
    tmp_path: Path,
    classification: dict[str, object],
) -> None:
    from scripts.trading_configuration_inventory_v2 import _load_classifications

    path = tmp_path / "classifications.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": CLASSIFICATION_SCHEMA_VERSION,
                "classifications": [
                    {"configuration_id": "cfg_one", **classification}
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        _load_classifications(path)
