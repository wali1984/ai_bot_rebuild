#!/usr/bin/env python3
"""Dispatch the persistent native-trainer service in an explicit safe mode.

Argument validation intentionally completes before a mode implementation is
imported.  The authenticated publisher can create only a non-serving training
candidate after independently signed completion authorization; it has no
prediction, serving, paper, live, exchange, or order authority.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from enum import Enum
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT))


class NativeTrainerResidentMode(str, Enum):
    """Resident modes that are explicitly authorized by this entrypoint."""

    WAITING_FOR_AUTHENTICATED_SAMPLES = "waiting-for-authenticated-samples"
    AUTHENTICATED_PROFILED_PUBLISHER = "authenticated-profiled-publisher"
    LOCALLY_AUTHENTICATED_PROFILED_RESEARCH_PUBLISHER = (
        "locally-authenticated-profiled-research-publisher"
    )


CONFIG_EXIT_STATUS = 78

_COMMON_REQUIRED_ARGUMENTS = (
    "repo_root",
    "ledger_path",
    "trusted_cost_store_root",
    "interval_seconds",
)
_WAITING_REQUIRED_ARGUMENTS = (*_COMMON_REQUIRED_ARGUMENTS, "max_rows")
_PUBLISHER_REQUIRED_ARGUMENTS = (
    *_COMMON_REQUIRED_ARGUMENTS,
    "coordinator_runtime_root",
    "model_dir",
    "status_path",
    "namespace",
    "consumer_lane",
    "state_auth_key_id",
    "manifest_auth_key_id",
    "head_auth_key_id",
    "epoch_auth_key_id",
    "page_limit",
    "validation_fraction",
    "optimizer_input_byte_budget",
    "state_resource_budget_bytes",
    "checkpoint_serialization_byte_budget",
)
_PUBLISHER_ONLY_ARGUMENTS = tuple(
    name for name in _PUBLISHER_REQUIRED_ARGUMENTS if name not in _COMMON_REQUIRED_ARGUMENTS
)
_LOCAL_RESEARCH_REQUIRED_ARGUMENTS = (
    *_COMMON_REQUIRED_ARGUMENTS,
    "publisher_status_path",
    "label_archive_path",
    "local_research_runtime_root",
    "model_dir",
    "status_path",
    "manifest_auth_key_id",
    "local_research_auth_key_id",
    "page_limit",
    "scan_limit",
    "validation_fraction",
    "optimizer_input_byte_budget",
    "state_resource_budget_bytes",
    "checkpoint_serialization_byte_budget",
)
_LOCAL_RESEARCH_ONLY_ARGUMENTS = tuple(
    name
    for name in _LOCAL_RESEARCH_REQUIRED_ARGUMENTS
    if name not in _COMMON_REQUIRED_ARGUMENTS
    and name not in _PUBLISHER_REQUIRED_ARGUMENTS
)
_WAITING_REJECT_ARGUMENTS = tuple(
    dict.fromkeys((*_PUBLISHER_ONLY_ARGUMENTS, *_LOCAL_RESEARCH_ONLY_ARGUMENTS))
)


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        type=NativeTrainerResidentMode,
        choices=tuple(NativeTrainerResidentMode),
        required=True,
    )
    parser.add_argument("--repo-root", type=Path)
    parser.add_argument("--ledger-path", type=Path)
    parser.add_argument("--trusted-cost-store-root", type=Path)
    parser.add_argument("--interval-seconds", type=float)
    parser.add_argument("--max-rows", type=int)
    parser.add_argument("--coordinator-runtime-root", type=Path)
    parser.add_argument("--model-dir", type=Path)
    parser.add_argument("--status-path", type=Path)
    parser.add_argument("--namespace")
    parser.add_argument("--consumer-lane")
    parser.add_argument("--state-auth-key-id")
    parser.add_argument("--manifest-auth-key-id")
    parser.add_argument("--head-auth-key-id")
    parser.add_argument("--epoch-auth-key-id")
    parser.add_argument("--page-limit", type=int)
    parser.add_argument("--validation-fraction", type=float)
    parser.add_argument("--optimizer-input-byte-budget", type=int)
    parser.add_argument("--state-resource-budget-bytes", type=int)
    parser.add_argument("--checkpoint-serialization-byte-budget", type=int)
    parser.add_argument("--publisher-status-path", type=Path)
    parser.add_argument("--label-archive-path", type=Path)
    parser.add_argument("--local-research-runtime-root", type=Path)
    parser.add_argument("--local-research-auth-key-id")
    parser.add_argument("--scan-limit", type=int)
    parser.add_argument("--once", action="store_true")
    return parser


def _require_arguments(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
    names: tuple[str, ...],
) -> None:
    missing = tuple(name for name in names if getattr(args, name) is None)
    if missing:
        rendered = ", ".join(f"--{name.replace('_', '-')}" for name in missing)
        parser.error(f"{args.mode.value} requires {rendered}")


def _reject_arguments(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
    names: tuple[str, ...],
) -> None:
    supplied = tuple(name for name in names if getattr(args, name) is not None)
    if supplied:
        rendered = ", ".join(f"--{name.replace('_', '-')}" for name in supplied)
        parser.error(f"{args.mode.value} does not accept {rendered}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = _argument_parser()
    args = parser.parse_args(argv)
    if args.mode is NativeTrainerResidentMode.WAITING_FOR_AUTHENTICATED_SAMPLES:
        _require_arguments(parser, args, _WAITING_REQUIRED_ARGUMENTS)
        _reject_arguments(parser, args, _WAITING_REJECT_ARGUMENTS)
        if args.once:
            parser.error("waiting-for-authenticated-samples does not accept --once")

        # This lazy import is the safety boundary: invalid/missing modes cannot
        # import the waiting observer or the legacy CUDA trainer runtime.
        from v2.backend.app.services.native_trainer.profiled_training_waiting_runtime_v1 import (  # noqa: E501
            ProfiledTrainingWaitingConfigV1,
            run_profiled_training_waiting_loop_v1,
        )

        config = ProfiledTrainingWaitingConfigV1(
            repo_root=args.repo_root,
            ledger_path=args.ledger_path,
            trusted_cost_store_root=args.trusted_cost_store_root,
            interval_seconds=args.interval_seconds,
            scan_limit=args.max_rows,
        )
        return run_profiled_training_waiting_loop_v1(config)

    if args.mode is NativeTrainerResidentMode.AUTHENTICATED_PROFILED_PUBLISHER:
        _require_arguments(parser, args, _PUBLISHER_REQUIRED_ARGUMENTS)
        _reject_arguments(
            parser,
            args,
            ("max_rows", *_LOCAL_RESEARCH_ONLY_ARGUMENTS),
        )

        from v2.backend.app.services.native_trainer.authenticated_profiled_resident_runtime_credentials_v1 import (  # noqa: E501
            AuthenticatedProfiledResidentCredentialV1Error,
            load_authenticated_profiled_resident_runtime_credentials_v1,
        )
        from v2.backend.app.services.native_trainer.authenticated_profiled_resident_service_v1 import (  # noqa: E501
            AuthenticatedProfiledResidentServiceConfigV1,
            AuthenticatedProfiledResidentServiceV1Error,
            run_authenticated_profiled_resident_service_v1,
        )

        try:
            credentials = load_authenticated_profiled_resident_runtime_credentials_v1()
            config = AuthenticatedProfiledResidentServiceConfigV1(
                repo_root=args.repo_root,
                coordinator_runtime_root=args.coordinator_runtime_root,
                feature_ledger_path=args.ledger_path,
                trusted_immutable_cost_store_root=args.trusted_cost_store_root,
                model_dir=args.model_dir,
                status_path=args.status_path,
                namespace=args.namespace,
                consumer_lane=args.consumer_lane,
                state_auth_key_id=args.state_auth_key_id,
                manifest_auth_key_id=args.manifest_auth_key_id,
                head_auth_key_id=args.head_auth_key_id,
                epoch_auth_key_id=args.epoch_auth_key_id,
                page_limit=args.page_limit,
                validation_fraction=args.validation_fraction,
                optimizer_input_byte_budget=args.optimizer_input_byte_budget,
                state_resource_budget_bytes=args.state_resource_budget_bytes,
                checkpoint_serialization_byte_budget=(
                    args.checkpoint_serialization_byte_budget
                ),
                interval_seconds=args.interval_seconds,
            )
        except (
            AuthenticatedProfiledResidentCredentialV1Error,
            AuthenticatedProfiledResidentServiceV1Error,
        ) as exc:
            if isinstance(exc, AuthenticatedProfiledResidentCredentialV1Error):
                reason = exc.reason
            else:
                reason = ";".join(exc.reasons)
            print(f"PROFILED_RESIDENT_CONFIGURATION_ERROR:{reason}", file=sys.stderr)
            return CONFIG_EXIT_STATUS
        return run_authenticated_profiled_resident_service_v1(
            config,
            credentials,
            once=args.once,
        )

    if (
        args.mode
        is NativeTrainerResidentMode.LOCALLY_AUTHENTICATED_PROFILED_RESEARCH_PUBLISHER
    ):
        _require_arguments(parser, args, _LOCAL_RESEARCH_REQUIRED_ARGUMENTS)
        _reject_arguments(
            parser,
            args,
            (
                "max_rows",
                "coordinator_runtime_root",
                "namespace",
                "consumer_lane",
                "state_auth_key_id",
                "head_auth_key_id",
                "epoch_auth_key_id",
            ),
        )

        from v2.backend.app.services.native_trainer.authenticated_profiled_resident_runtime_credentials_v1 import (  # noqa: E501
            AuthenticatedProfiledResidentCredentialV1Error,
            load_authenticated_profiled_resident_runtime_credentials_v1,
        )
        from v2.backend.app.services.native_trainer.locally_authenticated_profiled_research_service_v1 import (  # noqa: E501
            LocallyAuthenticatedProfiledResearchServiceConfigV1,
            LocallyAuthenticatedProfiledResearchServiceV1Error,
            run_locally_authenticated_profiled_research_service_v1,
        )

        try:
            credentials = load_authenticated_profiled_resident_runtime_credentials_v1()
            if getattr(credentials, "local_research_hmac_key", None) is None:
                raise LocallyAuthenticatedProfiledResearchServiceV1Error(
                    "LOCAL_PROFILED_RESEARCH_AUTHORIZATION_CREDENTIAL_REQUIRED"
                )
            config = LocallyAuthenticatedProfiledResearchServiceConfigV1(
                repo_root=args.repo_root,
                publisher_status_path=args.publisher_status_path,
                feature_ledger_path=args.ledger_path,
                label_archive_path=args.label_archive_path,
                trusted_immutable_cost_store_root=args.trusted_cost_store_root,
                runtime_root=args.local_research_runtime_root,
                model_dir=args.model_dir,
                status_path=args.status_path,
                manifest_auth_key_id=args.manifest_auth_key_id,
                local_research_auth_key_id=args.local_research_auth_key_id,
                page_limit=args.page_limit,
                scan_limit=args.scan_limit,
                validation_fraction=args.validation_fraction,
                optimizer_input_byte_budget=args.optimizer_input_byte_budget,
                state_resource_budget_bytes=args.state_resource_budget_bytes,
                checkpoint_serialization_byte_budget=(
                    args.checkpoint_serialization_byte_budget
                ),
                interval_seconds=args.interval_seconds,
            )
        except (
            AuthenticatedProfiledResidentCredentialV1Error,
            LocallyAuthenticatedProfiledResearchServiceV1Error,
        ) as exc:
            reason = exc.reason if hasattr(exc, "reason") else ";".join(exc.reasons)
            print(f"LOCAL_PROFILED_RESEARCH_CONFIGURATION_ERROR:{reason}", file=sys.stderr)
            return CONFIG_EXIT_STATUS
        return run_locally_authenticated_profiled_research_service_v1(
            config,
            credentials,
            once=args.once,
        )

    # Keep an explicit final guard so a future enum member cannot silently
    # inherit either runtime's authority.
    raise RuntimeError("native_trainer_resident_mode_not_implemented")


if __name__ == "__main__":
    raise SystemExit(main())
