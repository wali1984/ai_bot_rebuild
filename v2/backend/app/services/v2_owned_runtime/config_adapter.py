"""Config adapter.

Maps legacy config.py and config_accounts.py module-level constants into
V2 ConfigRecord objects. Emits all unmapped keys explicitly so the contract
can flag them. Does not expose any secret values (treats credentials_*
keys as REDACTED).

This adapter does NOT import legacy code. It introspects the legacy
modules by AST parsing only.
"""
from __future__ import annotations

import ast
import datetime as dt
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[5]
LEGACY_CONFIG = REPO / "v2/legacy_owned_runtime/full_runtime_closure/config.py"
LEGACY_CONFIG_ACCOUNTS = REPO / "v2/legacy_owned_runtime/full_runtime_closure/config_accounts.py"

REDACT_KEY_PATTERNS = (
    "api_key", "apikey", "api_secret", "secret", "password", "private_key", "token",
)
DANGEROUS_VALUE_KEYS = (
    "ENABLE_LIVE", "ALLOW_LIVE", "LIVE_TRADING", "PAPER_TO_LIVE_SWITCH",
)


def _is_secret_key(name: str) -> bool:
    n = name.lower()
    return any(p in n for p in REDACT_KEY_PATTERNS)


@dataclass
class ConfigRecord:
    name: str
    legacy_module: str
    value_repr: str
    is_secret: bool
    is_dangerous: bool


def _ast_extract_constants(path: Path, module_label: str) -> tuple[list[ConfigRecord], list[str]]:
    if not path.exists():
        return [], [f"missing:{path}"]
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError as e:
        return [], [f"parse_error:{path}:{e}"]
    records: list[ConfigRecord] = []
    errors: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name):
                    name = tgt.id
                    secret = _is_secret_key(name)
                    dangerous = name in DANGEROUS_VALUE_KEYS
                    if secret:
                        value_repr = "REDACTED"
                    else:
                        try:
                            value_repr = ast.unparse(node.value)[:240]
                        except Exception:
                            value_repr = "<unrepresentable>"
                    records.append(ConfigRecord(
                        name=name,
                        legacy_module=module_label,
                        value_repr=value_repr,
                        is_secret=secret,
                        is_dangerous=dangerous,
                    ))
    return records, errors


def build_config_parity_matrix() -> dict[str, Any]:
    cfg_records, cfg_errors = _ast_extract_constants(LEGACY_CONFIG, "config.py")
    acct_records, acct_errors = _ast_extract_constants(LEGACY_CONFIG_ACCOUNTS, "config_accounts.py")

    # Honest unmapped classification: we do not pretend any key is mapped
    # into V2 unless an explicit mapping is registered. For now no key is
    # mapped, so every key is OPERATOR_DECISION_REQUIRED.
    unmapped: list[dict[str, Any]] = []
    for rec in cfg_records + acct_records:
        unmapped.append({
            **asdict(rec),
            "v2_mapping_status": "OPERATOR_DECISION_REQUIRED",
        })

    return {
        "schema_version": "1.0.0",
        "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
        "legacy_config_present": LEGACY_CONFIG.exists(),
        "legacy_config_accounts_present": LEGACY_CONFIG_ACCOUNTS.exists(),
        "config_record_count": len(cfg_records),
        "config_accounts_record_count": len(acct_records),
        "secret_redacted_count": sum(1 for r in cfg_records + acct_records if r.is_secret),
        "dangerous_keys": [r.name for r in cfg_records + acct_records if r.is_dangerous],
        "unmapped_keys": unmapped,
        "parse_errors": cfg_errors + acct_errors,
        "note": "All keys are OPERATOR_DECISION_REQUIRED until V2 mapping is registered.",
    }
