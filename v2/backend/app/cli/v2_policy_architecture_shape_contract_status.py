"""V2 policy architecture shape-contract CLI (extraction only).

Emits the worklog + public dashboard payload describing the exact
legacy policy-architecture shape contract. Does NOT implement or claim
the port. Never imports torch.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from v2.backend.app.services.rl_core.policy_architecture_shape_contract import (
    build_policy_architecture_shape_contract,
)

WORKLOG_STATUS = Path(
    "claude_worklog/final_readiness/v2_policy_architecture_shape_contract/latest/policy_architecture_shape_contract.json"
)
PUBLIC_DASHBOARD = Path(
    "v2/frontend/public/v2_policy_architecture_shape_contract/latest/operator_dashboard_payload.json"
)


def run_once() -> dict:
    payload = build_policy_architecture_shape_contract()
    payload["go_no_go"] = "V2_POLICY_ARCHITECTURE_SHAPE_CONTRACT_PREP_READY"
    body = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    WORKLOG_STATUS.parent.mkdir(parents=True, exist_ok=True)
    PUBLIC_DASHBOARD.parent.mkdir(parents=True, exist_ok=True)
    WORKLOG_STATUS.write_text(body, encoding="utf-8")
    PUBLIC_DASHBOARD.write_text(body, encoding="utf-8")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="v2_policy_architecture_shape_contract_status"
    )
    parser.add_argument("--once", action="store_true")
    parser.parse_args(argv or [])
    payload = run_once()
    print(
        json.dumps(
            {
                "go_no_go": payload["go_no_go"],
                "input_observation_target_dim": payload["input_observation"]["target_dim"],
                "action_space_size": payload["action_space"]["joint_action_count"],
                "components_present": payload["architecture_components_present"],
                "policy_port_implementation_claimed": payload[
                    "policy_port_implementation_claimed"
                ],
                "operator_decision_required_to_implement_port": payload[
                    "operator_decision_required_to_implement_port"
                ],
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
