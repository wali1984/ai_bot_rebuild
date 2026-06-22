"""V2 live-canary network-safe permission probe.

Verifies real but non-mutating exchange access:

- Reads only credential PRESENCE from OS env vars; NEVER returns or
  logs raw key/secret values, never echoes the value, and refuses
  to put the value into any payload.
- Reads V2_LIVE_CANARY_* config from ``.local_secrets/live_canary.env``;
  symbol/limit values propagate, but credentials are ALWAYS sourced
  from OS env (not from the file).
- Calls Binance Futures ``/fapi/v1/exchangeInfo`` (public, read-only)
  to verify tradability + filters per symbol.
- Calls Binance Futures ``/fapi/v2/account`` (signed GET, read-only)
  to verify the account-read permission.
- Does NOT call any order-shaped endpoint by default. The documented
  no-fill ``/fapi/v1/order/test`` endpoint MAY be exercised only when
  BOTH gates are open: ``V2_LIVE_CANARY_ALLOW_TEST_ORDER=true`` in
  the env file AND a Codex test-order-docs marker file is present.
  When either gate is closed the probe reports an explicit
  NOT_CHECKED_* reason.

This module NEVER places a real order. NEVER cancels or modifies
orders. NEVER changes leverage. NEVER changes margin mode. NEVER
writes legacy Redis. NEVER reads or logs raw API key/secret values.

Allowed Redis writes: NONE in this module.
Allowed file writes: NONE in this module (the CLI writes status
files).
"""
from __future__ import annotations

import dataclasses
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

LOCAL_SECRETS_PATH = Path(".local_secrets/live_canary.env")
APPROVAL_FILE_PATH = Path(
    "claude_worklog/approvals/OPERATOR_ACCEPTS_V2_LIVE_CANARY_LIMITATIONS.md"
)
CODEX_PASS_MARKER_PATH = Path(
    "claude_worklog/final_readiness/v2_24h_live_canary_bringup/latest/codex_review/CODEX_LIVE_CANARY_PASS.marker"
)
CODEX_TEST_ORDER_DOCS_MARKER_PATH = Path(
    "claude_worklog/final_readiness/v2_live_canary_permission_probe/latest/codex_review/CODEX_TEST_ORDER_DOCS_APPROVED.marker"
)

PROBE_GO_READY = "V2_LIVE_CANARY_PERMISSION_PROBE_READY"
PROBE_GO_BLOCKED = "V2_LIVE_CANARY_PERMISSION_PROBE_BLOCKED"

ENV_VAR_BINANCE_KEY_NAME = "BINANCE_API_KEY"
ENV_VAR_BINANCE_SECRET_NAME = "BINANCE_API_SECRET"

VALID_MODES = (
    "V2_NATIVE_SIGNAL_CANARY",
    "LEGACY_SIGNAL_V2_EXECUTION_CANARY",
)
DEFAULT_MODE = "BLOCKED_UNSELECTED"

BINANCE_FUTURES_BASE_URL = "https://fapi.binance.com"
EXCHANGE_INFO_PATH = "/fapi/v1/exchangeInfo"
ACCOUNT_READ_PATH = "/fapi/v2/account"
# Binance docs: this endpoint validates parameters and returns 200
# without entering the matching engine. It is NOT an order placement
# endpoint and is the only order-shaped path the probe may invoke,
# and even then only behind the dual gate above.
TEST_ENDPOINT_PATH = "/fapi/v1/order/test"
HTTP_TIMEOUT_SECONDS = 10
HTTP_RECV_WINDOW_MS = 5000

# Recognised env-config keys. Any other key in the env file is
# dropped at parse time so accidental credential lines never reach
# the payload.
ENV_CONFIG_KEYS = (
    "V2_LIVE_CANARY_MODE",
    "V2_LIVE_CANARY_SYMBOLS",
    "V2_LIVE_CANARY_MAX_NOTIONAL_USDT",
    "V2_LIVE_CANARY_MAX_DAILY_TRADES",
    "V2_LIVE_CANARY_MAX_DAILY_LOSS_USDT",
    "V2_LIVE_CANARY_DRY_RUN",
    "V2_LIVE_CANARY_ALLOW_TEST_ORDER",
)


def _utc_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _env_var_present(name: str) -> bool:
    """Return True iff env var is set AND non-empty. NEVER returns
    or logs the value."""
    return bool(os.environ.get(name))


def read_env_config(path: Path | None = None) -> dict[str, str]:
    """Parse ``.local_secrets/live_canary.env`` for V2_LIVE_CANARY_*
    keys. Returns a dict mapping recognised keys to their string
    values. The file MAY contain other keys; this parser only
    surfaces V2 canary config keys. The file's raw contents are
    NEVER returned in full and secret-shaped fields (BINANCE_API_*,
    SECRET, TOKEN, BEARER, PASSWORD) are explicitly dropped even if
    accidentally placed in the file.
    """
    secrets_path = path or LOCAL_SECRETS_PATH
    result: dict[str, str] = {}
    if not secrets_path.exists():
        return result
    try:
        text = secrets_path.read_text(encoding="utf-8")
    except Exception:
        return result
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key not in ENV_CONFIG_KEYS:
            continue
        value = value.strip().strip('"').strip("'")
        result[key] = value
    return result


def read_canary_mode_from_secrets(path: Path | None = None) -> str:
    """Backward-compatible helper: return the operator-selected canary
    mode label (or ``BLOCKED_UNSELECTED``) without ever returning the
    file contents."""
    cfg = read_env_config(path)
    mode = cfg.get("V2_LIVE_CANARY_MODE", DEFAULT_MODE)
    return mode if mode in VALID_MODES else DEFAULT_MODE


def _parse_symbol_list(raw: str) -> tuple[str, ...]:
    if not raw:
        return tuple()
    cleaned = raw.replace("[", "").replace("]", "")
    return tuple(s.strip().upper() for s in cleaned.split(",") if s.strip())


def _http_get_public_default(
    path: str,
    params: dict[str, Any] | None = None,
    timeout: int = HTTP_TIMEOUT_SECONDS,
) -> tuple[int, str]:
    url = f"{BINANCE_FUTURES_BASE_URL}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8")
        except Exception:
            body = ""
        return e.code, body
    except Exception as e:
        return 0, f"ERROR:{type(e).__name__}"


def _http_get_signed_default(
    api_key: str,
    api_secret: str,
    path: str,
    params: dict[str, Any] | None = None,
    timeout: int = HTTP_TIMEOUT_SECONDS,
) -> tuple[int, str]:
    """Signed GET to a read-only Binance Futures endpoint. Returns
    only HTTP status and a placeholder string; the response body is
    discarded so account balances / addresses / positions can never
    leak into the payload."""
    if not api_key or not api_secret:
        return 0, "NO_CREDENTIALS"
    params = dict(params or {})
    params["timestamp"] = int(time.time() * 1000)
    params["recvWindow"] = HTTP_RECV_WINDOW_MS
    qs = urllib.parse.urlencode(params)
    signature = hmac.new(api_secret.encode(), qs.encode(), hashlib.sha256).hexdigest()
    url = f"{BINANCE_FUTURES_BASE_URL}{path}?{qs}&signature={signature}"
    req = urllib.request.Request(url, headers={"X-MBX-APIKEY": api_key})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            _ = resp.read()
            return resp.status, "OK"
    except urllib.error.HTTPError as e:
        return e.code, f"HTTP_{e.code}"
    except Exception as e:
        return 0, f"ERROR:{type(e).__name__}"


def _http_post_signed_test_default(
    api_key: str,
    api_secret: str,
    path: str,
    params: dict[str, Any] | None = None,
    timeout: int = HTTP_TIMEOUT_SECONDS,
) -> tuple[int, str]:
    """Signed POST. Used ONLY for the documented Binance no-fill
    validation endpoint ``/fapi/v1/order/test``. NEVER used for real
    placement. The response body is discarded."""
    if not api_key or not api_secret:
        return 0, "NO_CREDENTIALS"
    params = dict(params or {})
    params["timestamp"] = int(time.time() * 1000)
    params["recvWindow"] = HTTP_RECV_WINDOW_MS
    qs = urllib.parse.urlencode(params)
    signature = hmac.new(api_secret.encode(), qs.encode(), hashlib.sha256).hexdigest()
    body = (qs + f"&signature={signature}").encode("utf-8")
    url = f"{BINANCE_FUTURES_BASE_URL}{path}"
    req = urllib.request.Request(
        url, data=body, headers={"X-MBX-APIKEY": api_key}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            _ = resp.read()
            return resp.status, "OK"
    except urllib.error.HTTPError as e:
        return e.code, f"HTTP_{e.code}"
    except Exception as e:
        return 0, f"ERROR:{type(e).__name__}"


def _probe_exchange_info(
    symbols: tuple[str, ...],
    *,
    http_get_public: Callable[..., tuple[int, str]] | None = None,
) -> tuple[str, dict[str, dict[str, Any]]]:
    """Query Binance Futures exchangeInfo (public) and return
    (status, per-symbol filter dict). Filters extracted per symbol:
    tradable, min_notional, step_size, tick_size."""
    if not symbols:
        return ("NOT_CHECKED_SYMBOLS_EMPTY", {})
    http_get_public = http_get_public or _http_get_public_default
    status, body = http_get_public(EXCHANGE_INFO_PATH)
    if status != 200:
        return (f"HTTP_{status}", {})
    try:
        data = json.loads(body)
    except (ValueError, TypeError):
        return ("PARSE_ERROR", {})
    out: dict[str, dict[str, Any]] = {}
    wanted = {s.upper() for s in symbols}
    for s in data.get("symbols", []) or []:
        sym = (s.get("symbol") or "").upper()
        if sym not in wanted:
            continue
        filters = s.get("filters", []) or []
        min_notional: float | None = None
        step_size: float | None = None
        tick_size: float | None = None
        for f in filters:
            ft = f.get("filterType")
            if ft in ("MIN_NOTIONAL", "NOTIONAL"):
                for k in ("notional", "minNotional"):
                    v = f.get(k)
                    if v is not None:
                        try:
                            min_notional = float(v)
                        except (TypeError, ValueError):
                            pass
            elif ft == "LOT_SIZE":
                v = f.get("stepSize")
                if v is not None:
                    try:
                        step_size = float(v)
                    except (TypeError, ValueError):
                        pass
            elif ft == "PRICE_FILTER":
                v = f.get("tickSize")
                if v is not None:
                    try:
                        tick_size = float(v)
                    except (TypeError, ValueError):
                        pass
        out[sym] = {
            "tradable": s.get("status") == "TRADING",
            "contract_type": s.get("contractType"),
            "min_notional": min_notional,
            "step_size": step_size,
            "tick_size": tick_size,
        }
    return ("OK", out)


def _probe_account_read_permission(
    *,
    api_key: str,
    api_secret: str,
    http_get_signed: Callable[..., tuple[int, str]] | None = None,
) -> str:
    """Signed read-only GET to verify the API key has account-read
    permission. Returns a status string only; the response body is
    discarded."""
    if not api_key or not api_secret:
        return "NOT_CHECKED_CREDENTIALS_ABSENT"
    http_get_signed = http_get_signed or _http_get_signed_default
    status, _ = http_get_signed(api_key, api_secret, ACCOUNT_READ_PATH)
    if status == 200:
        return "OK"
    if status in (401, 403):
        return f"DENIED_HTTP_{status}"
    if status == 0:
        return "NETWORK_ERROR"
    return f"HTTP_{status}"


def _probe_documented_no_fill_endpoint(
    *,
    api_key: str,
    api_secret: str,
    env_cfg: Mapping[str, str],
    symbol_info: Mapping[str, Mapping[str, Any]],
    codex_test_order_marker_path: Path,
    http_post_signed_test: Callable[..., tuple[int, str]] | None = None,
) -> tuple[str, bool]:
    """Call the documented Binance no-fill validation endpoint at
    ``/fapi/v1/order/test`` ONLY when BOTH gates are open:

    - ``V2_LIVE_CANARY_ALLOW_TEST_ORDER=true`` in the env file
    - Codex test-order-docs marker present on disk

    Returns ``(status_label, attempted_bool)``. NEVER places a real
    order. NEVER mutates leverage or margin."""
    flag = env_cfg.get("V2_LIVE_CANARY_ALLOW_TEST_ORDER", "").strip().lower()
    if flag != "true":
        return ("NOT_CHECKED_FLAG_NOT_SET", False)
    if not codex_test_order_marker_path.exists():
        return ("NOT_CHECKED_CODEX_TEST_ORDER_DOCS_MARKER_ABSENT", False)
    if not api_key or not api_secret:
        return ("NOT_CHECKED_CREDENTIALS_ABSENT", False)
    if not symbol_info:
        return ("NOT_CHECKED_NO_TRADABLE_SYMBOL_INFO", False)
    target_sym: str | None = None
    for sym, info in symbol_info.items():
        if info.get("tradable"):
            target_sym = sym
            break
    if not target_sym:
        return ("NOT_CHECKED_NO_TRADABLE_SYMBOL", False)
    # The endpoint validates parameters and returns 200 OK without
    # entering the matching engine per Binance docs. We still send
    # a notionally-tiny request so the response shape is exercised.
    params = {
        "symbol": target_sym,
        "side": "BUY",
        "type": "MARKET",
        "quantity": "0.001",
    }
    http_post_signed_test = http_post_signed_test or _http_post_signed_test_default
    status, _ = http_post_signed_test(
        api_key, api_secret, TEST_ENDPOINT_PATH, params
    )
    if status == 200:
        return ("OK_VALIDATED_NO_FILL", True)
    if status in (400, 422):
        return (f"REJECTED_VALIDATION_HTTP_{status}", True)
    if status in (401, 403):
        return (f"DENIED_HTTP_{status}", True)
    if status == 0:
        return ("NETWORK_ERROR", True)
    return (f"HTTP_{status}", True)


@dataclasses.dataclass(frozen=True)
class PermissionProbeResult:
    schema_version: str
    generated_utc: str
    go_no_go: str
    exchange_credentials_present: bool
    raw_credential_in_payload: str
    mode_selected: str
    canary_mode_selected: str
    symbols_requested: tuple[str, ...]
    symbols_tradable: dict[str, bool]
    min_notional_by_symbol: dict[str, float | None]
    step_size_by_symbol: dict[str, float | None]
    tick_size_by_symbol: dict[str, float | None]
    account_read_permission_status: str
    test_order_endpoint_status: str
    exchange_info_call_status: str
    real_order_attempted: bool
    leverage_changed: bool
    margin_mode_changed: bool
    writes_exchange_orders: bool
    writes_legacy_redis: bool
    live_gate: str
    live_symbols: tuple[str, ...]
    approves_live: bool
    approves_canary: bool
    approves_legacy_shutdown: bool
    approves_redis_trim: bool
    secrets_file_present: bool
    approval_file_present: bool
    codex_pass_marker_present: bool
    codex_test_order_docs_marker_present: bool
    binance_api_key_env_present: bool
    binance_api_secret_env_present: bool
    test_order_endpoint_attempted: bool
    fail_blockers: tuple[str, ...]
    network_probe_enabled: bool
    network_base_url_documented_only: str

    def as_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "generated_utc": self.generated_utc,
            "go_no_go": self.go_no_go,
            "exchange_credentials_present": self.exchange_credentials_present,
            "raw_credential_in_payload": self.raw_credential_in_payload,
            "mode_selected": self.mode_selected,
            "canary_mode_selected": self.canary_mode_selected,
            "symbols_requested": list(self.symbols_requested),
            "symbols_tradable": dict(self.symbols_tradable),
            "min_notional_by_symbol": dict(self.min_notional_by_symbol),
            "step_size_by_symbol": dict(self.step_size_by_symbol),
            "tick_size_by_symbol": dict(self.tick_size_by_symbol),
            "account_read_permission_status": self.account_read_permission_status,
            "test_order_endpoint_status": self.test_order_endpoint_status,
            "exchange_info_call_status": self.exchange_info_call_status,
            "real_order_attempted": self.real_order_attempted,
            "leverage_changed": self.leverage_changed,
            "margin_mode_changed": self.margin_mode_changed,
            "writes_exchange_orders": self.writes_exchange_orders,
            "writes_legacy_redis": self.writes_legacy_redis,
            "live_gate": self.live_gate,
            "live_symbols": list(self.live_symbols),
            "approves_live": self.approves_live,
            "approves_canary": self.approves_canary,
            "approves_legacy_shutdown": self.approves_legacy_shutdown,
            "approves_redis_trim": self.approves_redis_trim,
            "secrets_file_present": self.secrets_file_present,
            "approval_file_present": self.approval_file_present,
            "codex_pass_marker_present": self.codex_pass_marker_present,
            "codex_test_order_docs_marker_present": self.codex_test_order_docs_marker_present,
            "binance_api_key_env_present": self.binance_api_key_env_present,
            "binance_api_secret_env_present": self.binance_api_secret_env_present,
            "test_order_endpoint_attempted": self.test_order_endpoint_attempted,
            "fail_blockers": list(self.fail_blockers),
            "network_probe_enabled": self.network_probe_enabled,
            "network_base_url_documented_only": self.network_base_url_documented_only,
        }


def run_probe(
    *,
    secrets_path: Path | None = None,
    approval_path: Path | None = None,
    codex_pass_marker_path: Path | None = None,
    codex_test_order_marker_path: Path | None = None,
    network_probe_enabled: bool = True,
    http_get_public_fn: Callable[..., tuple[int, str]] | None = None,
    http_get_signed_fn: Callable[..., tuple[int, str]] | None = None,
    http_post_signed_test_fn: Callable[..., tuple[int, str]] | None = None,
    env_overrides: Mapping[str, str] | None = None,
) -> PermissionProbeResult:
    """Run the network-safe permission probe.

    The probe NEVER places a real order. The only order-shaped path
    even potentially reached is the documented Binance no-fill
    validation endpoint, and that requires both a Codex docs marker
    and an explicit env-config flag. Network calls are skipped when
    credentials are absent (signed) or symbols are empty (public).
    """
    secrets_path = secrets_path or LOCAL_SECRETS_PATH
    approval_path = approval_path or APPROVAL_FILE_PATH
    codex_pass_marker_path = codex_pass_marker_path or CODEX_PASS_MARKER_PATH
    codex_test_order_marker_path = (
        codex_test_order_marker_path or CODEX_TEST_ORDER_DOCS_MARKER_PATH
    )
    env_cfg = dict(read_env_config(secrets_path))
    if env_overrides:
        for k, v in env_overrides.items():
            env_cfg[k] = v
    mode = env_cfg.get("V2_LIVE_CANARY_MODE", DEFAULT_MODE)
    if mode not in VALID_MODES:
        mode = DEFAULT_MODE
    symbols = _parse_symbol_list(env_cfg.get("V2_LIVE_CANARY_SYMBOLS", ""))
    api_key_present = _env_var_present(ENV_VAR_BINANCE_KEY_NAME)
    api_secret_present = _env_var_present(ENV_VAR_BINANCE_SECRET_NAME)
    credentials_present = api_key_present and api_secret_present
    if network_probe_enabled and symbols:
        exch_status, exch_data = _probe_exchange_info(
            symbols, http_get_public=http_get_public_fn
        )
    else:
        exch_status, exch_data = "NOT_CHECKED_NETWORK_PROBE_DISABLED", {}
        if not symbols:
            exch_status = "NOT_CHECKED_SYMBOLS_EMPTY"
    symbols_tradable: dict[str, bool] = {}
    min_notional_by_symbol: dict[str, float | None] = {}
    step_size_by_symbol: dict[str, float | None] = {}
    tick_size_by_symbol: dict[str, float | None] = {}
    for s in symbols:
        info = (exch_data or {}).get(s)
        symbols_tradable[s] = bool(info and info.get("tradable"))
        min_notional_by_symbol[s] = info.get("min_notional") if info else None
        step_size_by_symbol[s] = info.get("step_size") if info else None
        tick_size_by_symbol[s] = info.get("tick_size") if info else None
    if network_probe_enabled and credentials_present:
        api_key = os.environ.get(ENV_VAR_BINANCE_KEY_NAME, "")
        api_secret = os.environ.get(ENV_VAR_BINANCE_SECRET_NAME, "")
        account_status = _probe_account_read_permission(
            api_key=api_key,
            api_secret=api_secret,
            http_get_signed=http_get_signed_fn,
        )
    elif not credentials_present:
        account_status = "NOT_CHECKED_CREDENTIALS_ABSENT"
    else:
        account_status = "NOT_CHECKED_NETWORK_PROBE_DISABLED"
    if network_probe_enabled:
        api_key = os.environ.get(ENV_VAR_BINANCE_KEY_NAME, "")
        api_secret = os.environ.get(ENV_VAR_BINANCE_SECRET_NAME, "")
        test_order_status, test_order_attempted = _probe_documented_no_fill_endpoint(
            api_key=api_key,
            api_secret=api_secret,
            env_cfg=env_cfg,
            symbol_info=exch_data,
            codex_test_order_marker_path=codex_test_order_marker_path,
            http_post_signed_test=http_post_signed_test_fn,
        )
    else:
        test_order_status, test_order_attempted = (
            "NOT_CHECKED_NETWORK_PROBE_DISABLED",
            False,
        )
    blockers: list[str] = []
    if not api_key_present:
        blockers.append("BINANCE_API_KEY_ENV_VAR_ABSENT")
    if not api_secret_present:
        blockers.append("BINANCE_API_SECRET_ENV_VAR_ABSENT")
    if mode == DEFAULT_MODE:
        blockers.append("V2_LIVE_CANARY_MODE_NOT_SELECTED_OR_INVALID")
    if not symbols:
        blockers.append("V2_LIVE_CANARY_SYMBOLS_WHITELIST_EMPTY")
    if exch_status not in (
        "OK",
        "NOT_CHECKED_NETWORK_PROBE_DISABLED",
        "NOT_CHECKED_SYMBOLS_EMPTY",
    ):
        blockers.append(f"EXCHANGE_INFO_CALL_FAILED:{exch_status}")
    for s in symbols:
        if exch_status != "OK":
            continue
        if not symbols_tradable.get(s):
            blockers.append(f"SYMBOL_NOT_TRADABLE:{s}")
            continue
        if min_notional_by_symbol.get(s) is None:
            blockers.append(f"MIN_NOTIONAL_MISSING_FOR_SYMBOL:{s}")
        if step_size_by_symbol.get(s) is None:
            blockers.append(f"STEP_SIZE_MISSING_FOR_SYMBOL:{s}")
        if tick_size_by_symbol.get(s) is None:
            blockers.append(f"TICK_SIZE_MISSING_FOR_SYMBOL:{s}")
    if credentials_present:
        if account_status not in ("OK",):
            if account_status.startswith("DENIED"):
                blockers.append(
                    f"ACCOUNT_READ_PERMISSION_DENIED:{account_status}"
                )
            elif account_status.startswith(("HTTP_", "NETWORK_ERROR")):
                blockers.append(
                    f"ACCOUNT_READ_PERMISSION_ERROR:{account_status}"
                )
    if test_order_attempted and not test_order_status.startswith("OK_"):
        blockers.append(f"TEST_ORDER_ENDPOINT_FAILED:{test_order_status}")
    if not network_probe_enabled:
        blockers.append("NETWORK_PROBE_DISABLED")
    go = PROBE_GO_READY if not blockers else PROBE_GO_BLOCKED
    return PermissionProbeResult(
        schema_version="v2_live_canary_permission_probe_status_v2",
        generated_utc=_utc_iso(),
        go_no_go=go,
        exchange_credentials_present=credentials_present,
        raw_credential_in_payload="NEVER",
        mode_selected=mode,
        canary_mode_selected=mode,
        symbols_requested=symbols,
        symbols_tradable=symbols_tradable,
        min_notional_by_symbol=min_notional_by_symbol,
        step_size_by_symbol=step_size_by_symbol,
        tick_size_by_symbol=tick_size_by_symbol,
        account_read_permission_status=account_status,
        test_order_endpoint_status=test_order_status,
        exchange_info_call_status=exch_status,
        real_order_attempted=False,
        leverage_changed=False,
        margin_mode_changed=False,
        writes_exchange_orders=False,
        writes_legacy_redis=False,
        live_gate="blocked_human_only",
        live_symbols=tuple(),
        approves_live=False,
        approves_canary=False,
        approves_legacy_shutdown=False,
        approves_redis_trim=False,
        secrets_file_present=secrets_path.exists(),
        approval_file_present=approval_path.exists(),
        codex_pass_marker_present=codex_pass_marker_path.exists(),
        codex_test_order_docs_marker_present=codex_test_order_marker_path.exists(),
        binance_api_key_env_present=api_key_present,
        binance_api_secret_env_present=api_secret_present,
        test_order_endpoint_attempted=test_order_attempted,
        fail_blockers=tuple(blockers),
        network_probe_enabled=network_probe_enabled,
        network_base_url_documented_only=BINANCE_FUTURES_BASE_URL,
    )
