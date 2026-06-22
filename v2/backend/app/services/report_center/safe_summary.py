"""V2 Report Center — safe-summary extractor.

Pulls a minimal, sanitized summary out of a worklog markdown / JSON
artifact for the realtime report center. Redacts anything that looks
like a secret. Never emits the full file. Never emits raw logs.

Read-only with respect to filesystem outside its inputs.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

# Tokens we never publish, regardless of where they appear.
SECRET_LIKE_PATTERNS: tuple[re.Pattern[str], ...] = (
    # API keys / bearer tokens
    re.compile(r"(?i)\b(api[_-]?key|secret|token|bearer|authorization)\s*[:=]\s*\S+"),
    re.compile(r"(?i)\b(passw(?:or)?d|passcode|pin)\s*[:=]\s*\S+"),
    # AWS / GCP / generic long alnum credentials
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bASIA[0-9A-Z]{16}\b"),
    # Private key headers
    re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC |DSA |ENCRYPTED |PRIVATE) ?PRIVATE KEY-----"),
    # Long opaque hex-like strings (32+) — likely credentials/hashes
    re.compile(r"\b[a-fA-F0-9]{40,}\b"),
    # Base64ish long strings
    re.compile(r"\b[A-Za-z0-9+/]{40,}={0,2}\b"),
    # File path mentions that point at the secrets dir
    re.compile(r"(?i)\.local_secrets[^\s]*"),
    # Common exchange credentials phrasing
    re.compile(r"(?i)\b(binance|bybit|okx|exchange)[_-]?(api[_-]?key|secret)\b\s*[:=]\s*\S+"),
)

REDACTION_TOKEN = "***REDACTED***"

GO_NO_GO_RE = re.compile(
    r"(?im)^\s*(?:GO\/NO[\-_]GO|GO_NO_GO|GO NO GO)\s*[:\-]?\s*(?P<token>[A-Z0-9_]+)\s*$"
)
# Marker tokens used by our packets (V2_… and CODEX_… readiness/pass/fail states).
MARKER_TOKEN_RE = re.compile(
    r"\b(?:V2|CODEX)_[A-Z0-9_]+_"
    r"(?:READY|BLOCKED|PASS|FAIL|CODEX_PASS|CODEX_FAIL|PARTIAL_PROGRESS|REMEDIATED_READY)\b"
)

# Markdown headings we extract verbatim (after sanitization). We accept
# common headings used by our packets.
SECTION_HEADINGS: tuple[str, ...] = (
    "decision",
    "current blockers",
    "blockers",
    "next action",
    "next actions",
    "safety",
    "safety state",
    "validation",
    "validation summary",
    "non-approval items",
    "summary",
)


def sanitize_text(text: str) -> str:
    if not text:
        return ""
    sanitized = text
    for pat in SECRET_LIKE_PATTERNS:
        sanitized = pat.sub(REDACTION_TOKEN, sanitized)
    # Be paranoid about long hex/base64 substrings even after the patterns above.
    sanitized = re.sub(r"\b[A-Za-z0-9+/]{64,}={0,2}\b", REDACTION_TOKEN, sanitized)
    return sanitized


def extract_go_no_go(text: str) -> str | None:
    if not text:
        return None
    # Prefer the explicit GO/NO-GO line.
    m = GO_NO_GO_RE.search(text)
    if m:
        return m.group("token")
    # Fall back to the first marker-token in the document. This is
    # safe because the patterns are package-namespaced (V2_…_READY etc).
    m = MARKER_TOKEN_RE.search(text)
    if m:
        return m.group(0)
    return None


def status_from_marker(marker: str | None) -> str:
    if not marker:
        return "INFO"
    upper = marker.upper()
    if upper.endswith("_CODEX_FAIL"):
        return "FAIL"
    if upper.endswith("_BLOCKED"):
        return "BLOCKED"
    if upper.endswith("_CODEX_PASS"):
        return "PASS"
    if upper.endswith("_READY") or upper.endswith("_REMEDIATED_READY") or upper.endswith("_PARTIAL_PROGRESS"):
        return "READY"
    if "FULL_OBSERVATION_BUILDER_PARTIAL_MISSING_FIELDS" in upper:
        return "BLOCKED"
    if "OPERATOR_DECISION_REQUIRED" in upper or "OPERATOR_REQUIRED" in upper:
        return "OPERATOR_DECISION_REQUIRED"
    if "EXTERNAL_SOURCE_REQUIRED" in upper:
        return "OPERATOR_DECISION_REQUIRED"
    if upper.endswith("_PASS"):
        return "PASS"
    return "INFO"


def extract_markdown_sections(text: str) -> dict[str, str]:
    """Pull our well-known headings out of a sanitized markdown body.

    Returns a dict {section_lowercase: sanitized_body_excerpt}.
    Body excerpts are capped at 1200 characters to bound the public
    payload size.
    """
    if not text:
        return {}
    sanitized = sanitize_text(text)
    # Split into lines and group by `##`/`###` headings.
    lines = sanitized.splitlines()
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in lines:
        m = re.match(r"^\s*#{1,6}\s+(.+?)\s*$", line)
        if m:
            heading = m.group(1).strip().lower()
            # Normalize: drop leading numbering like "1. "
            heading = re.sub(r"^\d+[\.\)]\s+", "", heading)
            current = heading
            sections.setdefault(current, [])
            continue
        if current is not None:
            sections[current].append(line)
    out: dict[str, str] = {}
    for k, body_lines in sections.items():
        key = k.strip().lower()
        if key not in SECTION_HEADINGS:
            continue
        body = "\n".join(body_lines).strip()
        if not body:
            continue
        if len(body) > 1200:
            body = body[:1200] + "\n…"
        out[key] = body
    return out


def safe_summary_from_markdown(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        return {"error": f"unreadable: {exc}", "redaction_applied": False}
    sanitized = sanitize_text(text)
    marker = extract_go_no_go(sanitized)
    status = status_from_marker(marker)
    sections = extract_markdown_sections(text)
    return {
        "go_no_go": marker,
        "status": status,
        "sections": sections,
        "char_count": len(text),
        "redaction_applied": sanitized != text,
        "redaction_token": REDACTION_TOKEN if sanitized != text else None,
    }


_SAFE_JSON_KEYS_ALLOWLIST: tuple[str, ...] = (
    "go_no_go",
    "schema_version",
    "generated_utc",
    "generated_at",
    "generated_est",
    "timestamp_utc",
    "phase",
    "state",
    "status",
    "next_action",
    "live_gate",
    "live_symbols",
    "approves_live",
    "approves_canary",
    "approves_legacy_shutdown",
    "approves_redis_trim",
    "writes_old_redis",
    "calls_exchange_mutation",
    "places_real_order",
    "leverage_changed",
    "margin_mode_changed",
    "creates_approval_tokens",
    "creates_approval_artifacts",
    "trims_or_flushes_redis",
    "removes_legacy_redis_keys",
    "controller",
    "preflight",
    "watchdog",
    "watchdog_summary",
    "issue_summary",
    "automatable_issue_count",
    "operator_owned_issue_count",
    "selector_status",
    "selected_work",
    "operator_owned_blockers",
    "queue_loaded_task_count",
    "duplicate_suppression_count",
    "blockers",
    "id",
    "detail",
    "summary",
    "symbol_count",
    "symbol",
    "classification_counts",
    "top_positive_symbols",
    "top_negative_symbols",
    "public_intel_modes",
    "calibration_error_bps",
    "high_confidence_loser_count",
    "risk_block_category_counts",
    "best_diagnostic_strategy",
    "after_quality_fixes_expectancy_bps",
    "after_quality_fixes_ci_lower_bps",
    "pre_filter_after_cost_expectancy_bps",
    "pre_filter_after_cost_ci_lower_bps",
    "after_quality_fixes_candidate_count",
    "after_cost_proof_state",
    "mode",
    "strategy",
    "live_readiness_recommendation",
    "dynamic_symbol_count",
    "target_dynamic_symbol_count",
    "training_symbols",
    "paper_symbols",
    "live_data_symbols",
    "execution_live_symbols",
    "candidate_count",
    "candidate_state_counts",
    "trainer_row_count",
    "trainer_train_rows",
    "trainer_validation_rows",
    "trained_model_available",
    "edge_verdict",
    "edge_proven",
    "after_cost_expectancy_bps",
    "primary_live_recommendation",
    "website_sync_status",
    "recommendations",
    "live_readiness_status",
    "categories_used",
    "primary_goal",
    "primary_objectives",
    "mission",
    "overall_score",
    "categories",
    "honesty_invariant",
    "current_objective",
    "next_automatable_task",
    "next_operator_required_decision",
    "no_automatable_work_remaining_reason",
    "live_blocked",
    "shutdown_blocked",
    "paper_edge_state",
    "model_parity_state",
    "recovery_gate_state",
    "capital_protection_decisions_required",
    "honesty_invariants",
    "queue_state_after_completion",
    "test_evidence",
    "safety",
    "completed_burndown_groups",
    "completed_burndown_tasks",
    "summary_by_category",
    "aggregate_category_counts",
    "aggregate_total_observed",
    "aggregate_total_check",
    "field_spec_hold_count",
    "strict_source_contract_pass",
    "generic_source_hint_hits",
    "active_controllers",
    "stale_controllers",
    "pending_claude_count",
    "pending_codex_count",
    "stalled_claude_count",
    "stalled_codex_count",
    "codex_failure_count",
    "full_observation_builder_status",
    "target_full_observation_dim",
    "per_symbol",
    "generated_dim",
    "missing_dim",
    "missing_field_count",
    "zero_filled_field_count",
    "no_zero_fill_for_unknown_fields",
    "checkpoint_compatibility_claimed",
    "policy_architecture_parity_claimed",
    "production_equivalence_blocked",
    "plain_english_summary",
    "tokenmetrics_line",
    "live_blocked_because",
    "canary_blocked_because",
    "legacy_runtime_active_line",
    "legacy_data_preserved_line",
    "v2_primary_active_line",
    "live_blocked_line",
    "why_live_remains_blocked",
    "next_automatic_v2_fix",
    "next_operator_only_decision",
    "next_operator_decision",
    "next_automatic_action",
    "primary_recommendation",
    "primary_recommendation_reason",
    "secondary_recommendations",
    "blocker_counts",
    "total_categories",
    "blocks_canary_true_count",
    "blocks_live_true_count",
    "automatable_count",
    "operator_required_count",
    "tokenmetrics_classification",
    "tokenmetrics_blocks_live",
    "tokenmetrics_blocks_canary",
    "tokenmetrics_excluded_from_live_readiness",
    "tokenmetrics_excluded_reason",
    "production_equivalence_ready",
    "shutdown_safe",
    "canary_ready",
    "live_ready",
    "LEGACY_RUNTIME_ACTIVE",
    "LEGACY_DATA_PRESERVED",
    "V2_PRIMARY_PAPER_RUNTIME_ACTIVE",
    "LIVE_TRADING_ENABLED",
    "REAL_ORDERS_ENABLED",
    "LEGACY_REDIS_TRIMMED",
    "LEGACY_SHUTDOWN_MODE",
    "api_consuming_legacy_process_count_after",
    "trader_legacy_process_count_after",
    "trainer_legacy_process_count_after",
    "trainer_legacy_actively_training_after",
    "trainer_sleeping_post_sigterm_residual",
    "trainer_sleeping_post_sigterm_consumes_apis",
    "v2_runtime_services_active_count",
    "v2_systemd_user_timers_active_count",
    "redis_total_key_count",
    "v2_namespace_redis_key_count",
    "redis_trim_count_by_this_lane",
    "redis_delete_count_by_this_lane",
    "redis_flush_count_by_this_lane",
)


def _prune_to_allowlist(doc: Any, depth: int = 0) -> Any:
    """Walk a JSON-like structure and keep only allow-listed keys at any
    nesting level. List items keep their structure recursively.
    """
    if depth > 6:
        return None
    if isinstance(doc, dict):
        out: dict[str, Any] = {}
        for k, v in doc.items():
            if k in _SAFE_JSON_KEYS_ALLOWLIST:
                out[k] = _prune_to_allowlist(v, depth + 1)
        return out
    if isinstance(doc, list):
        return [_prune_to_allowlist(v, depth + 1) for v in doc][:64]
    if isinstance(doc, str):
        # Even allow-listed strings get sanitized.
        return sanitize_text(doc)
    return doc


def safe_summary_from_json(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        return {"error": f"unreadable: {exc}", "redaction_applied": False}
    try:
        doc = json.loads(raw)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"invalid json: {exc}", "redaction_applied": False}
    pruned = _prune_to_allowlist(doc)
    marker = None
    if isinstance(pruned, dict):
        marker = pruned.get("go_no_go") or pruned.get("status")
        if not marker:
            marker = pruned.get("state")
        if isinstance(marker, str) and not MARKER_TOKEN_RE.search(marker):
            # status text isn't a marker; try other commonly used fields
            for k in ("phase", "next_action"):
                v = pruned.get(k)
                if isinstance(v, str):
                    m = MARKER_TOKEN_RE.search(v)
                    if m:
                        marker = m.group(0)
                        break
    if isinstance(marker, str):
        status = status_from_marker(marker)
    else:
        status = "INFO"
    sanitized_raw = sanitize_text(raw)
    return {
        "go_no_go": marker if isinstance(marker, str) else None,
        "status": status,
        "pruned": pruned,
        "redaction_applied": sanitized_raw != raw,
        "redaction_token": REDACTION_TOKEN if sanitized_raw != raw else None,
    }
