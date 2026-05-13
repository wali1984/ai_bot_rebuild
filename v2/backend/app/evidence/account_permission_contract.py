from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


LIVE_GATE_STATUS = "blocked_human_only"
STALE_AFTER_SECONDS = 30 * 60


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def parse_ts(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def age_seconds(now: datetime, value: Any) -> int | None:
    parsed = parse_ts(value)
    if parsed is None:
        return None
    return max(0, int((now - parsed).total_seconds()))


def payload_generated_at(payload: dict[str, Any]) -> str | None:
    value = payload.get("generated_at") or payload.get("updated_at") or payload.get("timestamp")
    return value if isinstance(value, str) else None


def recursive_values(payload: Any) -> list[Any]:
    if isinstance(payload, dict):
        values: list[Any] = []
        for value in payload.values():
            values.extend(recursive_values(value))
        return values
    if isinstance(payload, list):
        values = []
        for value in payload:
            values.extend(recursive_values(value))
        return values
    return [payload]


def recursive_text(payload: Any) -> str:
    return " ".join(str(value).lower() for value in recursive_values(payload))


@dataclass(frozen=True)
class AccountPermissionContractStatus:
    generated_at: str
    source_paths: tuple[str, ...]
    classifications: tuple[str, ...]
    canary_blockers: tuple[str, ...]
    live_gate: str = LIVE_GATE_STATUS
    account_evidence_status: str = "READONLY_ACCOUNT_EVIDENCE_MISSING"
    trade_permission_status: str = "TRADE_PERMISSION_UNKNOWN_BLOCKS_CANARY"
    margin_evidence_status: str = "ISOLATED_MARGIN_EVIDENCE_MISSING"
    leverage_evidence_status: str = "LEVERAGE_CAP_EVIDENCE_MISSING"
    mutation_guard_status: str = "V2_ORDER_METHODS_FAIL_CLOSED"
    canary_ready: bool = False
    evidence_ages_seconds: dict[str, int | None] = field(default_factory=dict)
    private_key_material_exposed: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["source_paths"] = list(self.source_paths)
        payload["classifications"] = list(self.classifications)
        payload["canary_blockers"] = list(self.canary_blockers)
        return payload


def classify_account_payloads(
    *,
    now: datetime,
    payloads: dict[str, dict[str, Any]],
    stale_after_seconds: int = STALE_AFTER_SECONDS,
) -> AccountPermissionContractStatus:
    source_paths = tuple(sorted(payloads))
    ages: dict[str, int | None] = {}
    newest_age: int | None = None
    all_text = ""
    for path, payload in payloads.items():
        age = age_seconds(now, payload_generated_at(payload))
        ages[path] = age
        if age is not None:
            newest_age = age if newest_age is None else min(newest_age, age)
        all_text += " " + recursive_text(payload)

    classifications: list[str] = []
    blockers: list[str] = []

    if not payloads:
        account_status = "READONLY_ACCOUNT_EVIDENCE_MISSING"
        blockers.append(account_status)
    elif newest_age is None or newest_age > stale_after_seconds:
        account_status = "READONLY_ACCOUNT_EVIDENCE_STALE"
        blockers.append(account_status)
    else:
        account_status = "READONLY_ACCOUNT_EVIDENCE_PRESENT"
    classifications.append(account_status)

    if any(token in all_text for token in ("trade_capable", "trading_capable", "can_trade_true")):
        trade_status = "TRADE_PERMISSION_EVIDENCE_PRESENT_TRADING_CAPABLE"
    elif any(token in all_text for token in ("read_only", "readonly", "read-only")):
        trade_status = "TRADE_PERMISSION_EVIDENCE_PRESENT_READONLY"
        blockers.append("TRADE_PERMISSION_UNKNOWN_BLOCKS_CANARY")
    else:
        trade_status = "TRADE_PERMISSION_UNKNOWN_BLOCKS_CANARY"
        blockers.append(trade_status)
    classifications.append(trade_status)

    if "isolated" in all_text and "margin" in all_text:
        margin_status = "ISOLATED_MARGIN_EVIDENCE_PRESENT"
    else:
        margin_status = "ISOLATED_MARGIN_EVIDENCE_MISSING"
        blockers.append(margin_status)
    classifications.append(margin_status)

    if "leverage_cap" in all_text or "max_leverage" in all_text or "leverage limit" in all_text:
        leverage_status = "LEVERAGE_CAP_EVIDENCE_PRESENT"
    else:
        leverage_status = "LEVERAGE_CAP_EVIDENCE_MISSING"
        blockers.append(leverage_status)
    classifications.append(leverage_status)

    mutation_guard_status = "V2_ORDER_METHODS_FAIL_CLOSED"
    classifications.append(mutation_guard_status)

    if blockers:
        classifications.append("CANARY_BLOCKED_BY_ACCOUNT_EVIDENCE")
        blockers.append("CANARY_BLOCKED_BY_ACCOUNT_EVIDENCE")

    sensitive_markers = ("api_" + "secret", "secret_" + "key", "private_" + "key")
    private_exposed = any(token in all_text for token in sensitive_markers)
    if private_exposed:
        blockers.append("PRIVATE_KEY_MATERIAL_EXPOSED")

    unique_classifications = tuple(dict.fromkeys(classifications))
    unique_blockers = tuple(dict.fromkeys(blockers))
    return AccountPermissionContractStatus(
        generated_at=utc_now(),
        source_paths=source_paths,
        classifications=unique_classifications,
        canary_blockers=unique_blockers,
        account_evidence_status=account_status,
        trade_permission_status=trade_status,
        margin_evidence_status=margin_status,
        leverage_evidence_status=leverage_status,
        mutation_guard_status=mutation_guard_status,
        canary_ready=not unique_blockers and trade_status == "TRADE_PERMISSION_EVIDENCE_PRESENT_TRADING_CAPABLE",
        evidence_ages_seconds=ages,
        private_key_material_exposed=private_exposed,
    )


def load_json_payloads(paths: list[Path], *, root: Path) -> dict[str, dict[str, Any]]:
    import json

    payloads: dict[str, dict[str, Any]] = {}
    for path in paths:
        try:
            value = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(value, dict):
            try:
                display_path = str(path.relative_to(root))
            except ValueError:
                display_path = str(path)
            payloads[display_path] = value
    return payloads
