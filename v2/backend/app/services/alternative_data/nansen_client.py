"""V2 Nansen free-tier paper/shadow client.

Plan/contract reference:
- claude_worklog/final_readiness/v2_alternative_data_integration/latest/
- Provider docs (documented only): https://docs.nansen.ai/

This client is paper/shadow only. It NEVER places, cancels, or
modifies any exchange entry. It NEVER changes leverage or margin. It
NEVER enables real or canary trading. It NEVER writes old Redis keys.
It NEVER calls paid endpoints. It NEVER logs or persists the raw API
key.

Allowed V2 Redis writes are constrained at the safe-set boundary to:
- v2:altdata:nansen:status
- v2:altdata:nansen:symbol:{symbol}

If NANSEN_API_KEY is absent from both the process env and the local
.local_secrets/alternative_data.env custody file, the client must
return the KEY_MISSING_NO_NETWORK sentinel WITHOUT opening any
network connection.
"""
from __future__ import annotations

import dataclasses
import inspect
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

V2_REDIS_PREFIX = "v2:"
KEY_STATUS = "v2:altdata:nansen:status"
KEY_PER_SYMBOL_TEMPLATE = "v2:altdata:nansen:symbol:{symbol}"

NANSEN_API_KEY_ENV_VAR = "NANSEN_API_KEY"
NANSEN_AUTH_HEADER_NAME = "apikey"
DEFAULT_VAULT_PATH = Path(".local_secrets/alternative_data.env")

NANSEN_API_BASE_URL_DOCUMENTED = "https://api.nansen.ai"
NANSEN_API_DOCS_URL_DOCUMENTED = "https://docs.nansen.ai/api/smart-money"
NANSEN_API_AUTH_DOCS_URL_DOCUMENTED = "https://docs.nansen.ai/getting-started/authentication"
NANSEN_USER_AGENT = "ai-bot-v2-altdata/1.0 (+https://local.operator)"

DEFAULT_FREE_RATE_LIMIT_PER_MINUTE = 10
DEFAULT_FREE_DAILY_BUDGET_PROVIDER = 1000
DEFAULT_FREE_DAILY_BUDGET_INTERNAL = 800
DEFAULT_FREE_CACHE_TTL_SECONDS = 600
DEFAULT_FREE_PER_SYMBOL_COOLDOWN_SECONDS = 300
DEFAULT_HTTP_TIMEOUT_SECONDS = 10

DEFAULT_REDIS_STATUS_TTL_SECONDS = 600
DEFAULT_REDIS_SYMBOL_TTL_SECONDS = 900

SOURCE_STATUS_KEY_MISSING = "KEY_MISSING_NO_NETWORK"
SOURCE_STATUS_OK = "API_OK"
SOURCE_STATUS_CACHE_HIT = "CACHE_HIT"
SOURCE_STATUS_COOLDOWN = "COOLDOWN_ACTIVE"
SOURCE_STATUS_BUDGET_EXHAUSTED = "DAILY_BUDGET_EXHAUSTED"
SOURCE_STATUS_AUTH_401 = "API_AUTH_ERROR_401"
SOURCE_STATUS_PAYMENT_REQUIRED_402 = "API_PAYMENT_REQUIRED_402"
SOURCE_STATUS_FORBIDDEN_403 = "API_FORBIDDEN_403"
SOURCE_STATUS_UNPROCESSABLE_422 = "API_UNPROCESSABLE_422"
SOURCE_STATUS_RATE_LIMITED_429 = "API_RATE_LIMITED_429"
SOURCE_STATUS_NETWORK_ERROR = "API_NETWORK_ERROR"
SOURCE_STATUS_TIMEOUT = "API_TIMEOUT"
SOURCE_STATUS_PARSE_ERROR = "API_PARSE_ERROR"
SOURCE_STATUS_DISABLED = "PROVIDER_DISABLED"
SOURCE_STATUS_ENDPOINT_NOT_ALLOWLISTED = "NANSEN_ENDPOINT_NOT_ALLOWLISTED"
SOURCE_STATUS_PAID_ENDPOINT_DISABLED = "NANSEN_PAID_ENDPOINT_DISABLED"

# Endpoint allowlist.
#
# Public callers select an endpoint by ID, never by raw path. The
# constructor does NOT accept ``api_base_url`` or
# ``smart_money_endpoint`` overrides; attempts to pass them raise
# ``TypeError``. Paid endpoint IDs (when added in future) are reachable
# only when both the ID is registered AND
# ``ALT_DATA_ENABLE_PAID=true`` is set in the process env.
DEFAULT_ENDPOINT_ID = "smart_money_holdings_free"
FREE_ENDPOINT_PATHS: dict[str, str] = {
    "smart_money_netflow_free": "/api/v1/smart-money/netflow",
    "smart_money_holdings_free": "/api/v1/smart-money/holdings",
}
# Paid endpoint IDs reserved for future review; intentionally empty
# today. A non-empty entry here has no effect until
# ``ALT_DATA_ENABLE_PAID=true`` is set AND a Codex review approves the
# specific endpoint ID.
PAID_ENDPOINT_PATHS: dict[str, str] = {}
PAID_ENABLED_ENV_VAR = "ALT_DATA_ENABLE_PAID"


def _paid_enabled_from_env() -> bool:
    """``True`` only when ``ALT_DATA_ENABLE_PAID=true`` (case-insensitive)."""
    value = os.environ.get(PAID_ENABLED_ENV_VAR, "")
    return value.strip().lower() == "true"


def is_free_endpoint(endpoint_id: str) -> bool:
    return endpoint_id in FREE_ENDPOINT_PATHS


def is_paid_endpoint(endpoint_id: str) -> bool:
    return endpoint_id in PAID_ENDPOINT_PATHS


def is_allowlisted_endpoint(endpoint_id: str) -> bool:
    return is_free_endpoint(endpoint_id) or is_paid_endpoint(endpoint_id)


def _utc_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _read_env_assignment(path: Path, name: str) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return None
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.removeprefix("export ").strip()
        if key != name:
            continue
        value = value.strip().strip("'\"")
        return value or None
    return None


def api_key_present(*, vault_path: Path = DEFAULT_VAULT_PATH) -> bool:
    value = os.environ.get(NANSEN_API_KEY_ENV_VAR) or _read_env_assignment(
        vault_path, NANSEN_API_KEY_ENV_VAR
    )
    return bool(value)


def safe_load_api_key(*, vault_path: Path = DEFAULT_VAULT_PATH) -> str | None:
    """Read the local key custody sources.

    The value is NEVER returned to the caller via log lines / payloads.
    It is held only inside the client and pasted into the request header.
    """
    value = os.environ.get(NANSEN_API_KEY_ENV_VAR) or _read_env_assignment(
        vault_path, NANSEN_API_KEY_ENV_VAR
    )
    if not value:
        return None
    return value


def redact_for_payload(text: str | None) -> str:
    """Redact a single value before placement in any payload or log.

    Returns a fixed placeholder string. Callers must use this any time
    they emit anything credential-shaped to a payload or stdout.
    """
    if text is None:
        return ""
    return "REDACTED"


def _safe_redis_set(redis_client: Any, key: str, value: str, ex: int | None) -> bool:
    """Refuse any write whose key falls outside this client's allowlist."""
    if redis_client is None:
        return False
    if not isinstance(key, str):
        return False
    if key != KEY_STATUS and not key.startswith("v2:altdata:nansen:symbol:"):
        return False
    if not key.startswith(V2_REDIS_PREFIX):
        return False
    try:
        if ex is not None:
            redis_client.set(key, value, ex=int(ex))
        else:
            redis_client.set(key, value)
        return True
    except Exception:
        return False


@dataclasses.dataclass
class RateLimitState:
    daily_budget_internal: int = DEFAULT_FREE_DAILY_BUDGET_INTERNAL
    daily_budget_remaining: int = DEFAULT_FREE_DAILY_BUDGET_INTERNAL
    last_request_ms: int | None = None
    last_response_status: str | None = None
    consecutive_failures: int = 0
    last_429_ms: int | None = None

    def as_payload(self) -> dict[str, Any]:
        return {
            "daily_budget_internal": int(self.daily_budget_internal),
            "daily_budget_remaining": int(self.daily_budget_remaining),
            "last_request_ms": self.last_request_ms,
            "last_response_status": self.last_response_status,
            "consecutive_failures": int(self.consecutive_failures),
            "last_429_ms": self.last_429_ms,
        }


@dataclasses.dataclass
class CacheEntry:
    payload: dict[str, Any]
    fetched_at_ms: int
    expires_at_ms: int


@dataclasses.dataclass
class SymbolSignalResult:
    symbol: str
    provider: str
    smart_money_score: float | None
    smart_money_flow_direction: str | None
    entity_flow_score: float | None
    provider_freshness_seconds: int | None
    missing_feature_flags: list[str]
    stale_feature_flags: list[str]
    rate_limit_state: dict[str, Any]
    source_status: str
    generated_utc: str

    def as_payload(self) -> dict[str, Any]:
        return {
            "schema_version": "v2_altdata_nansen_symbol_signal_v1",
            "symbol": self.symbol,
            "provider": self.provider,
            "smart_money_score": self.smart_money_score,
            "smart_money_flow_direction": self.smart_money_flow_direction,
            "entity_flow_score": self.entity_flow_score,
            "provider_freshness_seconds": self.provider_freshness_seconds,
            "missing_feature_flags": list(self.missing_feature_flags),
            "stale_feature_flags": list(self.stale_feature_flags),
            "rate_limit_state": dict(self.rate_limit_state),
            "source_status": self.source_status,
            "generated_utc": self.generated_utc,
            "writes_legacy_redis": False,
            "writes_exchange_orders": False,
            "gate": "blocked_human_only",
            "symbols_real": [],
            "live_gate": "blocked_human_only",
            "live_symbols": [],
            "approves_live": False,
            "approves_real": False,
            "approves_canary": False,
            "approves_legacy_shutdown": False,
            "approves_redis_trim": False,
            "paid_endpoints_enabled": False,
            "endpoint_allowlist_enforced": True,
            "constructor_accepts_api_base_url_override": False,
            "constructor_accepts_smart_money_endpoint_override": False,
            "may_not_override_strict_paper_fill_gate": True,
            "may_not_authorize_live_or_canary": True,
            "may_not_place_orders": True,
            "credential_in_payload": "NEVER",
        }


def _symbol_to_token_symbol(symbol: str) -> str:
    token = symbol.strip().upper()
    for suffix in ("USDT", "USDC", "USD"):
        if token.endswith(suffix):
            token = token[: -len(suffix)]
            break
    if token.startswith("1000") and len(token) > 4:
        token = token[4:]
    return token


def parse_smart_money_response(body: Any, *, symbol: str | None = None) -> dict[str, float | str | None]:
    """Defensive parser for Nansen smart-money responses.

    Returns a dict with three keys:
      - smart_money_score: float in [-1, 1] or None
      - smart_money_flow_direction: "long" | "short" | "neutral" | None
      - entity_flow_score: float in [-1, 1] or None
    """
    out: dict[str, float | str | None] = {
        "smart_money_score": None,
        "smart_money_flow_direction": None,
        "entity_flow_score": None,
    }
    if body is None:
        return out
    container = body
    if isinstance(body, dict) and isinstance(body.get("data"), (list, dict)):
        container = body.get("data")
    if isinstance(container, list):
        token_symbol = _symbol_to_token_symbol(symbol) if symbol else None
        net_flow_total = 0.0
        balance_change_total = 0.0
        entity_score_total = 0.0
        any_field = False
        any_balance = False
        any_entity = False
        for item in container:
            if not isinstance(item, dict):
                continue
            row_symbol = str(item.get("token_symbol") or item.get("symbol") or "").strip().upper()
            if token_symbol and row_symbol and row_symbol not in {token_symbol, f"W{token_symbol}"}:
                continue
            for candidate in (
                "net_flow_24h_usd",
                "net_flow_usd",
                "netFlowUsd",
                "net_flow",
                "netflow",
                "delta_usd",
            ):
                if candidate in item:
                    try:
                        net_flow_total += float(item[candidate])
                        any_field = True
                        break
                    except (TypeError, ValueError):
                        continue
            if "balance_24h_percent_change" in item:
                try:
                    balance_change_total += float(item["balance_24h_percent_change"])
                    any_balance = True
                except (TypeError, ValueError):
                    pass
            for candidate in ("share_of_holdings_percent", "holders_count", "trader_count"):
                if candidate in item:
                    try:
                        val = float(item[candidate])
                        entity_score_total += val / (100.0 if "percent" in candidate else 1_000.0)
                        any_entity = True
                        break
                    except (TypeError, ValueError):
                        continue
        if any_field:
            saturated = max(-1.0, min(1.0, net_flow_total / 1_000_000.0))
            out["smart_money_score"] = float(saturated)
            if net_flow_total > 0:
                out["smart_money_flow_direction"] = "long"
            elif net_flow_total < 0:
                out["smart_money_flow_direction"] = "short"
            else:
                out["smart_money_flow_direction"] = "neutral"
        elif any_balance:
            saturated = max(-1.0, min(1.0, balance_change_total / 100.0))
            out["smart_money_score"] = float(saturated)
            if balance_change_total > 0:
                out["smart_money_flow_direction"] = "long"
            elif balance_change_total < 0:
                out["smart_money_flow_direction"] = "short"
            else:
                out["smart_money_flow_direction"] = "neutral"
        if any_entity:
            out["entity_flow_score"] = max(-1.0, min(1.0, entity_score_total))
    elif isinstance(container, dict):
        for k in ("smart_money_score", "smartMoneyScore"):
            if k in container:
                try:
                    val = float(container[k])
                    out["smart_money_score"] = max(-1.0, min(1.0, val))
                    break
                except (TypeError, ValueError):
                    continue
        for k in ("smart_money_flow_direction", "flow_direction", "direction"):
            if k in container and container[k] in ("long", "short", "neutral"):
                out["smart_money_flow_direction"] = container[k]
                break
        for k in ("entity_flow_score", "entityFlowScore"):
            if k in container:
                try:
                    val = float(container[k])
                    out["entity_flow_score"] = max(-1.0, min(1.0, val))
                    break
                except (TypeError, ValueError):
                    continue
    return out


def _missing_and_stale_flags(parsed: dict[str, Any]) -> tuple[list[str], list[str]]:
    missing: list[str] = []
    stale: list[str] = []
    for field in ("smart_money_score", "smart_money_flow_direction", "entity_flow_score"):
        if parsed.get(field) is None:
            missing.append(field + "_missing")
    return missing, stale


class NansenClient:
    """Bounded paper/shadow Nansen client.

    The client is constructed without a key argument: it loads the key
    from local custody at fetch time only, never holds it as an
    attribute long-term, and never returns it to callers. All network IO
    is routed through the injected http_get callable so tests can
    simulate provider responses without real HTTP.
    """

    def __init__(
        self,
        *,
        http_get: Callable[[str, dict[str, str], float], tuple[int, Any]] | None = None,
        now_ms_func: Callable[[], int] | None = None,
        rate_limit: RateLimitState | None = None,
        cache_ttl_seconds: int = DEFAULT_FREE_CACHE_TTL_SECONDS,
        per_symbol_cooldown_seconds: int = DEFAULT_FREE_PER_SYMBOL_COOLDOWN_SECONDS,
        endpoint_id: str = DEFAULT_ENDPOINT_ID,
        allow_paid: bool | None = None,
        http_timeout_seconds: float = DEFAULT_HTTP_TIMEOUT_SECONDS,
        vault_path: Path | str = DEFAULT_VAULT_PATH,
    ) -> None:
        """Construct a paper/shadow Nansen client.

        The constructor refuses ``api_base_url`` and
        ``smart_money_endpoint`` overrides: a caller cannot point the
        client at an arbitrary URL. Endpoints are selected by
        ``endpoint_id`` from the internal allowlist
        (:data:`FREE_ENDPOINT_PATHS` and :data:`PAID_ENDPOINT_PATHS`).
        Unknown IDs are accepted at construction time and short-
        circuited at fetch time with ``NANSEN_ENDPOINT_NOT_ALLOWLISTED``
        and ``network_call_attempted=false``.

        Paid endpoints are unreachable unless ``allow_paid`` is True
        (or ``ALT_DATA_ENABLE_PAID=true`` in the env when
        ``allow_paid`` is ``None``).
        """
        self._http_get = http_get or _default_http_get
        self._now_ms = now_ms_func or (lambda: int(time.time() * 1000))
        self._rate_limit = rate_limit or RateLimitState()
        self._cache_ttl_seconds = int(cache_ttl_seconds)
        self._cooldown_seconds = int(per_symbol_cooldown_seconds)
        self._endpoint_id = str(endpoint_id)
        self._allow_paid = (
            bool(allow_paid) if allow_paid is not None else _paid_enabled_from_env()
        )
        self._http_timeout_seconds = float(http_timeout_seconds)
        self._vault_path = Path(vault_path)
        self._cache: dict[str, CacheEntry] = {}
        self._cooldown_until: dict[str, int] = {}
        self._global_refusal_status: str | None = None

    @property
    def endpoint_id(self) -> str:
        return self._endpoint_id

    @property
    def allow_paid(self) -> bool:
        return self._allow_paid

    def _endpoint_decision(self) -> tuple[str | None, str | None]:
        """Return ``(endpoint_path, refusal_status)``.

        Exactly one of the two is ``None``: an allowlisted free
        endpoint (or an allowlisted paid endpoint with paid enabled)
        returns the path; otherwise it returns a refusal sentinel.
        """
        if self._endpoint_id in FREE_ENDPOINT_PATHS:
            return FREE_ENDPOINT_PATHS[self._endpoint_id], None
        if self._endpoint_id in PAID_ENDPOINT_PATHS:
            if not self._allow_paid:
                return None, SOURCE_STATUS_PAID_ENDPOINT_DISABLED
            return PAID_ENDPOINT_PATHS[self._endpoint_id], None
        return None, SOURCE_STATUS_ENDPOINT_NOT_ALLOWLISTED

    @property
    def rate_limit(self) -> RateLimitState:
        return self._rate_limit

    def fetch_symbol(self, symbol: str) -> SymbolSignalResult:
        """Fetch one symbol's smart-money signals.

        Strict precedence:
          1. If env key absent: return KEY_MISSING_NO_NETWORK with no
             network call.
          2. If cache fresh: return CACHE_HIT.
          3. If cooldown active for this symbol: return COOLDOWN_ACTIVE.
          4. If daily budget exhausted: return DAILY_BUDGET_EXHAUSTED.
          5. Otherwise: issue one bounded HTTP GET with the auth header,
             classify 401/403/429/other explicitly, parse defensively,
             cache, set cooldown, decrement budget.
        """
        symbol = symbol.upper()
        now_ms = self._now_ms()
        # 0. Endpoint allowlist short-circuit. Unknown or paid-but-disabled
        # endpoints exit BEFORE the key lookup and BEFORE any HTTP. This is
        # the contract Codex required: paid/unreviewed endpoints must be
        # unreachable from the client surface.
        endpoint_path, endpoint_refusal = self._endpoint_decision()
        if endpoint_refusal is not None:
            return self._result(
                symbol=symbol,
                parsed=None,
                freshness_seconds=None,
                source_status=endpoint_refusal,
            )
        if not api_key_present(vault_path=self._vault_path):
            return self._result(
                symbol=symbol,
                parsed=None,
                freshness_seconds=None,
                source_status=SOURCE_STATUS_KEY_MISSING,
            )
        if self._global_refusal_status is not None:
            return self._result(
                symbol=symbol,
                parsed=None,
                freshness_seconds=None,
                source_status=self._global_refusal_status,
            )
        request_body = self._build_request_body(symbol, self._endpoint_id)
        cache_key = self._cache_key(endpoint_path, request_body)
        cached = self._cache.get(cache_key)
        if cached and cached.expires_at_ms > now_ms:
            parsed = parse_smart_money_response(cached.payload, symbol=symbol)
            freshness = max(0, (now_ms - cached.fetched_at_ms) // 1000)
            return self._result(
                symbol=symbol,
                parsed=parsed,
                freshness_seconds=int(freshness),
                source_status=SOURCE_STATUS_CACHE_HIT,
            )
        cooldown_until = self._cooldown_until.get(symbol, 0)
        if cooldown_until > now_ms:
            return self._result(
                symbol=symbol,
                parsed=None,
                freshness_seconds=None,
                source_status=SOURCE_STATUS_COOLDOWN,
            )
        if self._rate_limit.daily_budget_remaining <= 0:
            return self._result(
                symbol=symbol,
                parsed=None,
                freshness_seconds=None,
                source_status=SOURCE_STATUS_BUDGET_EXHAUSTED,
            )
        key = safe_load_api_key(vault_path=self._vault_path)
        if key is None:
            return self._result(
                symbol=symbol,
                parsed=None,
                freshness_seconds=None,
                source_status=SOURCE_STATUS_KEY_MISSING,
            )
        url = self._build_url(endpoint_path)
        headers = {
            NANSEN_AUTH_HEADER_NAME: key,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": NANSEN_USER_AGENT,
        }
        self._cooldown_until[symbol] = now_ms + self._cooldown_seconds * 1000
        self._rate_limit.last_request_ms = now_ms
        self._rate_limit.daily_budget_remaining -= 1
        try:
            status_code, body = self._call_http(url, headers, request_body)
        except TimeoutError:
            self._rate_limit.consecutive_failures += 1
            self._rate_limit.last_response_status = SOURCE_STATUS_TIMEOUT
            return self._result(
                symbol=symbol,
                parsed=None,
                freshness_seconds=None,
                source_status=SOURCE_STATUS_TIMEOUT,
            )
        except Exception:
            self._rate_limit.consecutive_failures += 1
            self._rate_limit.last_response_status = SOURCE_STATUS_NETWORK_ERROR
            return self._result(
                symbol=symbol,
                parsed=None,
                freshness_seconds=None,
                source_status=SOURCE_STATUS_NETWORK_ERROR,
            )
        del key  # ensure the local goes out of scope as soon as possible
        if status_code == 200:
            self._rate_limit.consecutive_failures = 0
            self._rate_limit.last_response_status = SOURCE_STATUS_OK
            payload_for_cache: dict[str, Any]
            if isinstance(body, (dict, list)):
                payload_for_cache = {"data": body} if isinstance(body, list) else body
            else:
                self._rate_limit.last_response_status = SOURCE_STATUS_PARSE_ERROR
                return self._result(
                    symbol=symbol,
                    parsed=None,
                    freshness_seconds=None,
                    source_status=SOURCE_STATUS_PARSE_ERROR,
                )
            self._cache[cache_key] = CacheEntry(
                payload=payload_for_cache,
                fetched_at_ms=now_ms,
                expires_at_ms=now_ms + self._cache_ttl_seconds * 1000,
            )
            parsed = parse_smart_money_response(payload_for_cache, symbol=symbol)
            return self._result(
                symbol=symbol,
                parsed=parsed,
                freshness_seconds=0,
                source_status=SOURCE_STATUS_OK,
            )
        if status_code == 401:
            self._rate_limit.consecutive_failures += 1
            self._rate_limit.last_response_status = SOURCE_STATUS_AUTH_401
            self._global_refusal_status = SOURCE_STATUS_AUTH_401
            return self._result(
                symbol=symbol,
                parsed=None,
                freshness_seconds=None,
                source_status=SOURCE_STATUS_AUTH_401,
            )
        if status_code == 402:
            self._rate_limit.consecutive_failures += 1
            self._rate_limit.last_response_status = SOURCE_STATUS_PAYMENT_REQUIRED_402
            self._global_refusal_status = SOURCE_STATUS_PAYMENT_REQUIRED_402
            return self._result(
                symbol=symbol,
                parsed=None,
                freshness_seconds=None,
                source_status=SOURCE_STATUS_PAYMENT_REQUIRED_402,
            )
        if status_code == 403:
            self._rate_limit.consecutive_failures += 1
            self._rate_limit.last_response_status = SOURCE_STATUS_FORBIDDEN_403
            self._global_refusal_status = SOURCE_STATUS_FORBIDDEN_403
            return self._result(
                symbol=symbol,
                parsed=None,
                freshness_seconds=None,
                source_status=SOURCE_STATUS_FORBIDDEN_403,
            )
        if status_code == 422:
            self._rate_limit.consecutive_failures += 1
            self._rate_limit.last_response_status = SOURCE_STATUS_UNPROCESSABLE_422
            return self._result(
                symbol=symbol,
                parsed=None,
                freshness_seconds=None,
                source_status=SOURCE_STATUS_UNPROCESSABLE_422,
            )
        if status_code == 429:
            self._rate_limit.consecutive_failures += 1
            self._rate_limit.last_response_status = SOURCE_STATUS_RATE_LIMITED_429
            self._rate_limit.last_429_ms = now_ms
            self._global_refusal_status = SOURCE_STATUS_RATE_LIMITED_429
            return self._result(
                symbol=symbol,
                parsed=None,
                freshness_seconds=None,
                source_status=SOURCE_STATUS_RATE_LIMITED_429,
            )
        self._rate_limit.consecutive_failures += 1
        self._rate_limit.last_response_status = SOURCE_STATUS_NETWORK_ERROR
        return self._result(
            symbol=symbol,
            parsed=None,
            freshness_seconds=None,
            source_status=SOURCE_STATUS_NETWORK_ERROR,
        )

    def _build_url(self, endpoint_path: str) -> str:
        # The base URL is a module-level constant and is NEVER taken
        # from caller-supplied arguments.
        return f"{NANSEN_API_BASE_URL_DOCUMENTED}{endpoint_path}"

    def _build_request_body(self, symbol: str, endpoint_id: str) -> dict[str, Any]:
        filters = {
            "include_smart_money_labels": ["Fund", "Smart Trader"],
            "include_native_tokens": True,
            "include_stablecoins": False,
        }
        if endpoint_id == "smart_money_holdings_free":
            return {
                "chains": ["ethereum", "solana", "base", "bnb", "arbitrum", "polygon"],
                "filters": filters,
                "premium_labels": False,
                "pagination": {"page": 1, "per_page": 100},
                "order_by": [{"field": "value_usd", "direction": "DESC"}],
            }
        return {
            "chains": ["ethereum", "solana", "base", "bnb", "arbitrum", "polygon"],
            "filters": filters,
            "premium_labels": False,
            "pagination": {"page": 1, "per_page": 100},
            "order_by": [{"field": "net_flow_24h_usd", "direction": "DESC"}],
        }

    def _cache_key(self, endpoint_path: str, request_body: dict[str, Any]) -> str:
        return json.dumps(
            {"endpoint_path": endpoint_path, "request_body": request_body},
            sort_keys=True,
            separators=(",", ":"),
        )

    def _call_http(
        self,
        url: str,
        headers: dict[str, str],
        request_body: dict[str, Any],
    ) -> tuple[int, Any]:
        signature = inspect.signature(self._http_get)
        parameters = list(signature.parameters.values())
        has_varargs = any(param.kind is inspect.Parameter.VAR_POSITIONAL for param in parameters)
        accepts_body = has_varargs or any(
            param.name in {"body", "json_body", "request_body", "payload", "data"}
            for param in parameters[2:3]
        )
        if accepts_body:
            return self._http_get(url, headers, request_body, self._http_timeout_seconds)  # type: ignore[misc]
        return self._http_get(url, headers, self._http_timeout_seconds)  # type: ignore[misc]

    def _result(
        self,
        *,
        symbol: str,
        parsed: dict[str, Any] | None,
        freshness_seconds: int | None,
        source_status: str,
    ) -> SymbolSignalResult:
        parsed = parsed or {
            "smart_money_score": None,
            "smart_money_flow_direction": None,
            "entity_flow_score": None,
        }
        missing, stale = _missing_and_stale_flags(parsed)
        return SymbolSignalResult(
            symbol=symbol,
            provider="nansen",
            smart_money_score=parsed.get("smart_money_score"),
            smart_money_flow_direction=parsed.get("smart_money_flow_direction"),
            entity_flow_score=parsed.get("entity_flow_score"),
            provider_freshness_seconds=freshness_seconds,
            missing_feature_flags=missing,
            stale_feature_flags=stale,
            rate_limit_state=self._rate_limit.as_payload(),
            source_status=source_status,
            generated_utc=_utc_iso(),
        )


def _default_http_get(
    url: str, headers: dict[str, str], body: dict[str, Any], timeout: float
) -> tuple[int, Any]:  # pragma: no cover - real HTTP not exercised in tests
    import urllib.error
    import urllib.request

    payload = json.dumps(body, separators=(",", ":"), sort_keys=True).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = int(getattr(resp, "status", resp.getcode() or 0))
            try:
                body = json.loads(resp.read().decode("utf-8"))
            except (ValueError, TypeError):
                body = None
            return status, body
    except urllib.error.HTTPError as e:
        return int(e.code), None
    except TimeoutError:
        raise
    except Exception:
        raise


def write_status_payload(
    redis_client: Any,
    *,
    go_no_go: str,
    rate_limit_state: RateLimitState,
    symbol_count: int,
    successful_symbol_count: int,
    source_status_counts: dict[str, int],
    key_present: bool,
    network_call_attempted: bool = False,
) -> dict[str, Any]:
    payload = {
        "schema_version": "v2_altdata_nansen_status_v1",
        "generated_utc": _utc_iso(),
        "provider": "nansen",
        "go_no_go": go_no_go,
        "tier": "free",
        "paid_endpoints_enabled": False,
        "paid_endpoints_env_var": PAID_ENABLED_ENV_VAR,
        "paid_endpoints_env_value": _paid_enabled_from_env(),
        "endpoint_allowlist_enforced": True,
        "free_endpoint_ids_allowed": sorted(FREE_ENDPOINT_PATHS.keys()),
        "paid_endpoint_ids_registered": sorted(PAID_ENDPOINT_PATHS.keys()),
        "constructor_accepts_api_base_url_override": False,
        "constructor_accepts_smart_money_endpoint_override": False,
        "key_present": key_present,
        "credential_in_payload": "NEVER",
        "network_call_attempted": bool(network_call_attempted),
        "provider_network_calls_attempted": bool(network_call_attempted),
        "auth_header_name_documented_only": NANSEN_AUTH_HEADER_NAME,
        "user_agent_set": True,
        "user_agent_value_redacted": "ai-bot-v2-altdata/1.0",
        "api_docs_url_documented": NANSEN_API_DOCS_URL_DOCUMENTED,
        "api_auth_docs_url_documented": NANSEN_API_AUTH_DOCS_URL_DOCUMENTED,
        "rate_limit_state": rate_limit_state.as_payload(),
        "symbol_count": int(symbol_count),
        "successful_symbol_count": int(successful_symbol_count),
        "source_status_counts": dict(source_status_counts),
        "writes_legacy_redis": False,
        "writes_exchange_orders": False,
        "no_synthetic_signals": True,
        "no_torch_imported": True,
        "no_pickle_loaded": True,
        "no_legacy_filesystem_modified": True,
        "gate": "blocked_human_only",
        "symbols_real": [],
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "may_not_override_strict_paper_fill_gate": True,
        "may_not_authorize_live_or_canary": True,
        "may_not_place_orders": True,
        "approves_live": False,
        "approves_real": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
    }
    _safe_redis_set(
        redis_client,
        KEY_STATUS,
        json.dumps(payload, sort_keys=True),
        ex=DEFAULT_REDIS_STATUS_TTL_SECONDS,
    )
    return payload


def write_symbol_payload(redis_client: Any, result: SymbolSignalResult) -> bool:
    key = KEY_PER_SYMBOL_TEMPLATE.format(symbol=result.symbol)
    return _safe_redis_set(
        redis_client,
        key,
        json.dumps(result.as_payload(), sort_keys=True),
        ex=DEFAULT_REDIS_SYMBOL_TTL_SECONDS,
    )
