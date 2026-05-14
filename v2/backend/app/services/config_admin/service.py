"""Fail-closed V2 config/admin manager service."""
from __future__ import annotations

import datetime as dt
import json
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple


RISK_SAFE = "safe"
RISK_SENSITIVE = "sensitive"
RISK_DANGEROUS = "dangerous"
VALIDATION_OK = "valid"
VALIDATION_PENDING_APPROVAL = "pending_human_approval"
VALIDATION_REJECTED = "rejected"

DANGEROUS_SETTING_KEYS = {
    "live_trading_enabled",
    "live_api_keys_active",
    "leverage_cap",
    "margin_mode",
    "max_position_usd",
    "daily_loss_limit_usd",
    "kill_switch_enabled",
    "mandatory_stop_enabled",
    "hedge_enabled",
    "dca_enabled",
    "adjust_leverage_enabled",
    "paper_to_live_switch",
}

SECRET_FRAGMENTS = ("secret", "api_key", "private", "password", "token")


@dataclass(frozen=True)
class ConfigSetting:
    setting_key: str
    effective_value: Any
    source: str
    staged_value: Any
    risk_class: str
    last_changed_by: str
    last_changed_at: str
    validation_status: str
    rollback_value: Any
    approval_required: bool
    approval_token_present: bool = False
    public_value_redacted: bool = False

    def to_public_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        if is_secret_key(self.setting_key):
            data["effective_value"] = "REDACTED"
            data["staged_value"] = "REDACTED" if self.staged_value is not None else None
            data["rollback_value"] = "REDACTED"
            data["public_value_redacted"] = True
        return data


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def is_secret_key(setting_key: str) -> bool:
    lower = setting_key.lower()
    return any(fragment in lower for fragment in SECRET_FRAGMENTS)


def risk_class_for_key(setting_key: str) -> str:
    if setting_key in DANGEROUS_SETTING_KEYS:
        return RISK_DANGEROUS
    if is_secret_key(setting_key):
        return RISK_SENSITIVE
    return RISK_SAFE


def default_settings(now: Optional[str] = None) -> List[ConfigSetting]:
    stamp = now or utc_now()
    raw: List[Tuple[str, Any, str]] = [
        ("paper_runtime_interval_seconds", 30, RISK_SAFE),
        ("paper_shadow_observation_interval_seconds", 60, RISK_SAFE),
        ("operator_dashboard_refresh_seconds", 15, RISK_SAFE),
        ("live_trading_enabled", False, RISK_DANGEROUS),
        ("live_api_keys_active", False, RISK_DANGEROUS),
        ("leverage_cap", 1, RISK_DANGEROUS),
        ("margin_mode", "ISOLATED_ONLY", RISK_DANGEROUS),
        ("max_position_usd", 0, RISK_DANGEROUS),
        ("daily_loss_limit_usd", 0, RISK_DANGEROUS),
        ("kill_switch_enabled", True, RISK_DANGEROUS),
        ("mandatory_stop_enabled", True, RISK_DANGEROUS),
        ("hedge_enabled", False, RISK_DANGEROUS),
        ("dca_enabled", False, RISK_DANGEROUS),
        ("adjust_leverage_enabled", False, RISK_DANGEROUS),
        ("paper_to_live_switch", "blocked_human_only", RISK_DANGEROUS),
        ("binance_api_key", "", RISK_SENSITIVE),
        ("binance_api_secret", "", RISK_SENSITIVE),
    ]
    return [
        ConfigSetting(
            setting_key=key,
            effective_value=value,
            source="v2_default_fail_closed",
            staged_value=None,
            risk_class=risk,
            last_changed_by="system",
            last_changed_at=stamp,
            validation_status=VALIDATION_OK,
            rollback_value=value,
            approval_required=risk == RISK_DANGEROUS,
        )
        for key, value, risk in raw
    ]


def settings_by_key(settings: Iterable[ConfigSetting]) -> Dict[str, ConfigSetting]:
    return {setting.setting_key: setting for setting in settings}


def validate_setting_value(setting_key: str, value: Any) -> Tuple[bool, str]:
    if setting_key == "margin_mode" and value != "ISOLATED_ONLY":
        return False, "margin_mode_must_remain_isolated_only"
    if setting_key == "paper_to_live_switch" and value != "blocked_human_only":
        return False, "paper_to_live_switch_must_remain_blocked_human_only"
    if setting_key in {"leverage_cap", "max_position_usd", "daily_loss_limit_usd"}:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return False, "numeric_value_required"
        if number < 0:
            return False, "negative_value_rejected"
    return True, VALIDATION_OK


def stage_setting(
    settings: Iterable[ConfigSetting],
    *,
    setting_key: str,
    staged_value: Any,
    actor: str,
    approval_token_present: bool = False,
    changed_at: Optional[str] = None,
) -> List[ConfigSetting]:
    by_key = settings_by_key(settings)
    if setting_key not in by_key:
        raise KeyError(setting_key)
    current = by_key[setting_key]
    ok, reason = validate_setting_value(setting_key, staged_value)
    stamp = changed_at or utc_now()
    if not ok:
        updated = replace(
            current,
            staged_value=staged_value,
            last_changed_by=actor,
            last_changed_at=stamp,
            validation_status=VALIDATION_REJECTED + ":" + reason,
            approval_token_present=approval_token_present,
        )
    elif current.risk_class == RISK_DANGEROUS:
        updated = replace(
            current,
            staged_value=staged_value,
            last_changed_by=actor,
            last_changed_at=stamp,
            validation_status=VALIDATION_PENDING_APPROVAL,
            approval_required=True,
            approval_token_present=approval_token_present,
        )
    else:
        updated = replace(
            current,
            effective_value=staged_value,
            staged_value=staged_value,
            last_changed_by=actor,
            last_changed_at=stamp,
            validation_status=VALIDATION_OK,
            rollback_value=current.effective_value,
            approval_required=False,
            approval_token_present=False,
        )
    return [updated if setting.setting_key == setting_key else setting for setting in settings]


def load_staged_changes(path: Optional[Path]) -> List[Dict[str, Any]]:
    if not path or not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return []
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict) and isinstance(data.get("staged_changes"), list):
        return [item for item in data["staged_changes"] if isinstance(item, dict)]
    return []


def apply_staged_changes(
    settings: Iterable[ConfigSetting],
    staged_changes: Iterable[Mapping[str, Any]],
) -> List[ConfigSetting]:
    current = list(settings)
    for change in staged_changes:
        key = str(change.get("setting_key") or "")
        if not key:
            continue
        current = stage_setting(
            current,
            setting_key=key,
            staged_value=change.get("staged_value"),
            actor=str(change.get("actor") or "operator"),
            approval_token_present=bool(change.get("approval_token_present")),
        )
    return current


def summarize_settings(settings: Iterable[ConfigSetting]) -> Dict[str, Any]:
    rows = [setting.to_public_dict() for setting in settings]
    by_risk = {RISK_SAFE: 0, RISK_SENSITIVE: 0, RISK_DANGEROUS: 0}
    pending: List[Dict[str, Any]] = []
    for row in rows:
        by_risk[str(row["risk_class"])] = by_risk.get(str(row["risk_class"]), 0) + 1
        if row["approval_required"] and row["validation_status"] == VALIDATION_PENDING_APPROVAL:
            pending.append(row)
    return {
        "settings": rows,
        "settings_tracked_total": len(rows),
        "settings_by_risk_class": by_risk,
        "dangerous_settings_pending_approval": pending,
        "secrets_redacted": all(
            row["public_value_redacted"]
            for row in rows
            if is_secret_key(str(row["setting_key"]))
        ),
    }
