"""V2 LunarCrush free-tier paper/shadow client.

Plan/contract reference:
- claude_worklog/final_readiness/v2_alternative_data_integration/latest/
- Provider docs (documented only): https://lunarcrush.com/developers/api

This client is paper/shadow only. It NEVER places, cancels, or
modifies any exchange entry. It NEVER changes leverage or margin. It
NEVER enables real or canary trading. It NEVER writes old Redis keys.
It NEVER calls paid endpoints. It NEVER logs or persists the raw API
key.

Allowed V2 Redis writes are constrained at the safe-set boundary to:
- v2:altdata:lunarcrush:status
- v2:altdata:lunarcrush:symbol:{symbol}

If the env var LUNARCRUSH_API_KEY is absent or empty, the client must
return the KEY_MISSING_NO_NETWORK sentinel WITHOUT opening any
network connection.
"""
from __future__ import annotations

import dataclasses
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

V2_REDIS_PREFIX = "v2:"
KEY_STATUS = "v2:altdata:lunarcrush:status"
KEY_PER_SYMBOL_TEMPLATE = "v2:altdata:lunarcrush:symbol:{symbol}"

LUNARCRUSH_API_KEY_ENV_VAR = "LUNARCRUSH_API_KEY"
LUNARCRUSH_AUTH_HEADER_NAME = "Authorization"
LUNARCRUSH_AUTH_HEADER_VALUE_PREFIX = "Bearer "
DEFAULT_VAULT_PATH = Path(".local_secrets/alternative_data.env")

LUNARCRUSH_API_BASE_URL_DOCUMENTED = "https://lunarcrush.com/api4"
LUNARCRUSH_API_DOCS_URL_DOCUMENTED = "https://lunarcrush.com/en/developers/api"
LUNARCRUSH_USER_AGENT = "ai-bot-v2-altdata/1.0 (+https://local.operator)"

DEFAULT_FREE_RATE_LIMIT_PER_MINUTE = 6
DEFAULT_FREE_DAILY_BUDGET_PROVIDER = 1000
DEFAULT_FREE_DAILY_BUDGET_INTERNAL = 500
DEFAULT_FREE_CACHE_TTL_SECONDS = 900
DEFAULT_FREE_PER_SYMBOL_COOLDOWN_SECONDS = 900
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
SOURCE_STATUS_NOT_FOUND_404 = "API_NOT_FOUND_404"
SOURCE_STATUS_RATE_LIMITED_429 = "API_RATE_LIMITED_429"
SOURCE_STATUS_NETWORK_ERROR = "API_NETWORK_ERROR"
SOURCE_STATUS_TIMEOUT = "API_TIMEOUT"
SOURCE_STATUS_PARSE_ERROR = "API_PARSE_ERROR"
SOURCE_STATUS_DISABLED = "PROVIDER_DISABLED"
SOURCE_STATUS_ENDPOINT_NOT_ALLOWLISTED = "LUNARCRUSH_ENDPOINT_NOT_ALLOWLISTED"
SOURCE_STATUS_PAID_ENDPOINT_DISABLED = "LUNARCRUSH_PAID_ENDPOINT_DISABLED"

# Endpoint allowlist.
#
# Public callers select an endpoint by ID, never by raw path. The
# constructor does NOT accept ``api_base_url`` or ``social_endpoint``
# overrides; attempts to pass them raise ``TypeError``. Paid endpoint
# IDs (if ever added) are reachable only when both the ID is
# registered in :data:`PAID_ENDPOINT_PATHS` AND
# ``ALT_DATA_ENABLE_PAID=true`` is set in the process env.
DEFAULT_ENDPOINT_ID = "public_coins_list_v2_free"
FREE_ENDPOINT_PATHS: dict[str, str] = {
    "public_coins_list_v2_free": "/public/coins/list/v2",
    "public_coins_list_v1_free": "/public/coins/list/v1",
}
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
    value = os.environ.get(LUNARCRUSH_API_KEY_ENV_VAR) or _read_env_assignment(
        vault_path, LUNARCRUSH_API_KEY_ENV_VAR
    )
    return bool(value)


def safe_load_api_key(*, vault_path: Path = DEFAULT_VAULT_PATH) -> str | None:
    value = os.environ.get(LUNARCRUSH_API_KEY_ENV_VAR) or _read_env_assignment(
        vault_path, LUNARCRUSH_API_KEY_ENV_VAR
    )
    if not value:
        return None
    return value


def redact_for_payload(text: str | None) -> str:
    if text is None:
        return ""
    return "REDACTED"


def _safe_redis_set(redis_client: Any, key: str, value: str, ex: int | None) -> bool:
    if redis_client is None:
        return False
    if not isinstance(key, str):
        return False
    if key != KEY_STATUS and not key.startswith("v2:altdata:lunarcrush:symbol:"):
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
    social_momentum_score: float | None
    social_volume_velocity: float | None
    sentiment_score: float | None
    galaxy_or_equivalent_score: float | None
    provider_freshness_seconds: int | None
    missing_feature_flags: list[str]
    stale_feature_flags: list[str]
    rate_limit_state: dict[str, Any]
    source_status: str
    generated_utc: str

    def as_payload(self) -> dict[str, Any]:
        return {
            "schema_version": "v2_altdata_lunarcrush_symbol_signal_v1",
            "symbol": self.symbol,
            "provider": self.provider,
            "social_momentum_score": self.social_momentum_score,
            "social_volume_velocity": self.social_volume_velocity,
            "sentiment_score": self.sentiment_score,
            "galaxy_or_equivalent_score": self.galaxy_or_equivalent_score,
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
            "constructor_accepts_social_endpoint_override": False,
            "may_not_override_strict_paper_fill_gate": True,
            "may_not_authorize_live_or_canary": True,
            "may_not_place_orders": True,
            "credential_in_payload": "NEVER",
        }


def _symbol_to_coin_symbol(symbol: str) -> str:
    token = symbol.strip().upper()
    for suffix in ("USDT", "USDC", "USD"):
        if token.endswith(suffix):
            token = token[: -len(suffix)]
            break
    if token.startswith("1000") and len(token) > 4:
        token = token[4:]
    return token


def parse_social_response(body: Any, *, symbol: str | None = None) -> dict[str, float | None]:
    """Defensive parser for LunarCrush social responses.

    Returns four keys:
      - social_momentum_score: float in [0, 1] or None
      - social_volume_velocity: float (signed) or None
      - sentiment_score: float in [-1, 1] or None
      - galaxy_or_equivalent_score: float in [0, 100] or None
    """
    out: dict[str, float | None] = {
        "social_momentum_score": None,
        "social_volume_velocity": None,
        "sentiment_score": None,
        "galaxy_or_equivalent_score": None,
    }
    if body is None:
        return out
    container = body
    if isinstance(body, dict) and isinstance(body.get("data"), (list, dict)):
        container = body.get("data")
    if isinstance(container, list):
        token_symbol = _symbol_to_coin_symbol(symbol) if symbol else None
        if token_symbol:
            matching = next(
                (
                    item
                    for item in container
                    if isinstance(item, dict)
                    and str(item.get("symbol") or item.get("coin_symbol") or "").strip().upper()
                    in {token_symbol, f"W{token_symbol}"}
                ),
                None,
            )
            if matching is not None:
                container = matching
            elif len(container) == 1 and isinstance(container[0], dict) and not (
                container[0].get("symbol") or container[0].get("coin_symbol")
            ):
                container = container[0]
            else:
                container = None
        else:
            container = container[0] if container else None
    if not isinstance(container, dict):
        return out
    for k in ("social_momentum_score", "social_score", "social_score_24h", "social_dominance"):
        if k in container:
            try:
                val = float(container[k])
                out["social_momentum_score"] = max(0.0, min(1.0, val / 100.0))
                break
            except (TypeError, ValueError):
                continue
    for k in (
        "social_volume_velocity",
        "social_volume_24h_change_pct",
        "social_volume_change",
        "num_posts_24h_change_pct",
        "interactions_24h_change_pct",
        "percent_change_24h",
    ):
        if k in container:
            try:
                out["social_volume_velocity"] = float(container[k])
                break
            except (TypeError, ValueError):
                continue
    for k in ("sentiment_score", "sentiment"):
        if k in container:
            try:
                raw = float(container[k])
                if -1.0 <= raw <= 1.0:
                    out["sentiment_score"] = raw
                elif 0.0 <= raw <= 5.0:
                    out["sentiment_score"] = (raw - 2.5) / 2.5
                elif 0.0 <= raw <= 100.0:
                    out["sentiment_score"] = (raw - 50.0) / 50.0
                break
            except (TypeError, ValueError):
                continue
    for k in ("galaxy_score", "galaxy_or_equivalent_score", "social_index", "alt_rank"):
        if k in container:
            try:
                val = float(container[k])
                if k == "alt_rank":
                    val = max(0.0, min(100.0, 100.0 - min(val, 1000.0) / 10.0))
                out["galaxy_or_equivalent_score"] = max(0.0, min(100.0, val))
                break
            except (TypeError, ValueError):
                continue
    return out


def _missing_and_stale_flags(parsed: dict[str, Any]) -> tuple[list[str], list[str]]:
    missing: list[str] = []
    stale: list[str] = []
    for field in (
        "social_momentum_score",
        "social_volume_velocity",
        "sentiment_score",
        "galaxy_or_equivalent_score",
    ):
        if parsed.get(field) is None:
            missing.append(field + "_missing")
    return missing, stale


class LunarCrushClient:
    """Bounded paper/shadow LunarCrush client.

    The auth scheme is `Authorization: Bearer <key>` per the
    documented LunarCrush developer API. The key is loaded from the
    process env at fetch time only, never stored as an attribute, and
    never returned to callers.
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
        """Construct a paper/shadow LunarCrush client.

        The constructor refuses ``api_base_url`` and ``social_endpoint``
        overrides: a caller cannot point the client at an arbitrary
        URL. Endpoints are selected by ``endpoint_id`` from the
        internal allowlist (:data:`FREE_ENDPOINT_PATHS` and
        :data:`PAID_ENDPOINT_PATHS`). Unknown IDs are accepted at
        construction time and short-circuited at fetch time with
        ``LUNARCRUSH_ENDPOINT_NOT_ALLOWLISTED`` and
        ``network_call_attempted=false``.

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
        symbol = symbol.upper()
        now_ms = self._now_ms()
        # 0. Endpoint allowlist short-circuit. Unknown or paid-but-disabled
        # endpoints exit BEFORE the key lookup and BEFORE any HTTP. This
        # is the contract that closes the constructor-override bypass.
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
        url = self._build_url(endpoint_path)
        cache_key = url
        cached = self._cache.get(cache_key)
        if cached and cached.expires_at_ms > now_ms:
            parsed = parse_social_response(cached.payload, symbol=symbol)
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
        headers = {
            LUNARCRUSH_AUTH_HEADER_NAME: LUNARCRUSH_AUTH_HEADER_VALUE_PREFIX + key,
            "Accept": "application/json",
            "User-Agent": LUNARCRUSH_USER_AGENT,
        }
        self._cooldown_until[symbol] = now_ms + self._cooldown_seconds * 1000
        self._rate_limit.last_request_ms = now_ms
        self._rate_limit.daily_budget_remaining -= 1
        try:
            status_code, body = self._http_get(url, headers, self._http_timeout_seconds)
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
        del key
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
            parsed = parse_social_response(payload_for_cache, symbol=symbol)
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
        if status_code == 404:
            self._rate_limit.consecutive_failures += 1
            self._rate_limit.last_response_status = SOURCE_STATUS_NOT_FOUND_404
            return self._result(
                symbol=symbol,
                parsed=None,
                freshness_seconds=None,
                source_status=SOURCE_STATUS_NOT_FOUND_404,
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
        return f"{LUNARCRUSH_API_BASE_URL_DOCUMENTED}{endpoint_path}?limit=1000"

    def _result(
        self,
        *,
        symbol: str,
        parsed: dict[str, Any] | None,
        freshness_seconds: int | None,
        source_status: str,
    ) -> SymbolSignalResult:
        parsed = parsed or {
            "social_momentum_score": None,
            "social_volume_velocity": None,
            "sentiment_score": None,
            "galaxy_or_equivalent_score": None,
        }
        missing, stale = _missing_and_stale_flags(parsed)
        return SymbolSignalResult(
            symbol=symbol,
            provider="lunarcrush",
            social_momentum_score=parsed.get("social_momentum_score"),
            social_volume_velocity=parsed.get("social_volume_velocity"),
            sentiment_score=parsed.get("sentiment_score"),
            galaxy_or_equivalent_score=parsed.get("galaxy_or_equivalent_score"),
            provider_freshness_seconds=freshness_seconds,
            missing_feature_flags=missing,
            stale_feature_flags=stale,
            rate_limit_state=self._rate_limit.as_payload(),
            source_status=source_status,
            generated_utc=_utc_iso(),
        )


def _default_http_get(
    url: str, headers: dict[str, str], timeout: float
) -> tuple[int, Any]:  # pragma: no cover - real HTTP not exercised in tests
    import urllib.error
    import urllib.request

    req = urllib.request.Request(url, headers=headers, method="GET")
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
        "schema_version": "v2_altdata_lunarcrush_status_v1",
        "generated_utc": _utc_iso(),
        "provider": "lunarcrush",
        "go_no_go": go_no_go,
        "tier": "free",
        "paid_endpoints_enabled": False,
        "paid_endpoints_env_var": PAID_ENABLED_ENV_VAR,
        "paid_endpoints_env_value": _paid_enabled_from_env(),
        "endpoint_allowlist_enforced": True,
        "free_endpoint_ids_allowed": sorted(FREE_ENDPOINT_PATHS.keys()),
        "paid_endpoint_ids_registered": sorted(PAID_ENDPOINT_PATHS.keys()),
        "constructor_accepts_api_base_url_override": False,
        "constructor_accepts_social_endpoint_override": False,
        "key_present": key_present,
        "credential_in_payload": "NEVER",
        "network_call_attempted": bool(network_call_attempted),
        "provider_network_calls_attempted": bool(network_call_attempted),
        "auth_header_name_documented_only": LUNARCRUSH_AUTH_HEADER_NAME,
        "auth_header_scheme_documented_only": "Bearer",
        "user_agent_set": True,
        "user_agent_value_redacted": "ai-bot-v2-altdata/1.0",
        "api_docs_url_documented": LUNARCRUSH_API_DOCS_URL_DOCUMENTED,
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
