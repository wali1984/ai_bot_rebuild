#!/usr/bin/env python3
"""S15 stale-feature entry-prevention fault injection (Section 11).

Exercises the PRODUCTION admission predicate
`_is_policy_sampled_paper_exploration_candidate` from the paper loop with:

  fresh_row  — valid clocks, no stale markers  -> must be ACCEPTED
  stale_rows — same row with each stale marker -> every one must be REJECTED

The fresh-row acceptance is the true-failure fixture: if the predicate ever
becomes vacuous (rejects everything or ignores staleness), this test fails.
Read-only; no Redis writes; no orders. Persists results for the Phase-10 runner.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from v2.backend.app.cli.v2_trade_management_paper_loop import (  # noqa: E402
    _is_policy_sampled_paper_exploration_candidate,
)

RESULT_PATH = REPO_ROOT / "goal_state/PERMANENT_SYSTEM_RECOVERY/s15_stale_feature_result.json"


def fresh_row() -> dict:
    return {
        "trainer_source": "V2_NATIVE_RL_MASA_PPO_CUDA_TRAINER",
        "prediction_id": "v2h_s15_test_0001",
        "paper_fill_allowed": True,
        "valid_for_paper": True,
        "market_state_id": "s15-test-market-state",
        "selected_action": "long",
        "side": "long",
        "action_probabilities": [0.5, 0.3, 0.2],
        "selected_action_probability": 0.5,
        "policy_value": 0.11,
        "feature_cutoff": "2026-07-26T05:00:00Z",
        "available_at": "2026-07-26T05:00:01Z",
        "decision_time": "2026-07-26T05:00:05Z",
        "feature_freshness_state": "FRESH",
        "stale_feature_count": 0,
        "stale_feature_names": [],
        "stale_mask": None,
        "paper_fill_gate_block_reasons": [],
        "market_state_reject_reasons": [],
    }


def main() -> int:
    base = fresh_row()
    accepted_fresh = _is_policy_sampled_paper_exploration_candidate(base)

    injections = {
        "freshness_state_STALE": {"feature_freshness_state": "STALE"},
        "freshness_state_EXPIRED": {"feature_freshness_state": "EXPIRED"},
        "stale_feature_count_positive": {"stale_feature_count": 3},
        "stale_feature_names_present": {"stale_feature_names": ["rsi_14"]},
        "stale_mask_present": {"stale_mask": [0, 1, 0]},
        "feature_cutoff_after_decision": {"feature_cutoff": "2026-07-26T05:00:09Z"},
        "available_after_decision": {"available_at": "2026-07-26T05:00:09Z"},
        "missing_clock_lineage": {"feature_cutoff": None},
    }
    outcomes = {}
    for name, patch in injections.items():
        row = {**fresh_row(), **patch}
        outcomes[name] = {
            "entry_rejected": not _is_policy_sampled_paper_exploration_candidate(row),
            "reason": "STALE_FEATURE_EVIDENCE",
        }

    all_rejected = all(v["entry_rejected"] for v in outcomes.values())
    payload = {
        "schema_version": "s15_stale_feature_injection_v1",
        "run_utc": datetime.now(UTC).isoformat(),
        "production_binding": "v2_trade_management_paper_loop._is_policy_sampled_paper_exploration_candidate",
        "fresh_row_accepted": bool(accepted_fresh),
        "stale_injections_rejected": outcomes,
        "all_stale_rejected": all_rejected,
        "pass": bool(accepted_fresh) and all_rejected,
    }
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(json.dumps(payload, indent=2))
    print(json.dumps({"pass": payload["pass"], "fresh_accepted": bool(accepted_fresh),
                      "all_stale_rejected": all_rejected}, indent=2))
    return 0 if payload["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
