"""Fetch and cache read-only Binance USD-M leverage-bracket evidence.

This command only calls signed USER_DATA ``GET /fapi/v1/leverageBracket`` via
the existing adapter.  It never submits/cancels/modifies an order and never
changes leverage or margin mode.
"""

from __future__ import annotations

import argparse
import hmac
import json
import os
import re
import stat
import threading
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

from v2.backend.app.services.binance_usdm_leverage_bracket_evidence import (
    DEFAULT_CACHE_TTL_SECONDS,
    DEFAULT_FRESHNESS_SECONDS,
    STATUS_SCHEMA_VERSION,
    EvidenceSecurityContext,
    LeverageBracketEvidenceError,
    build_evidence_security_context,
    evidence_security_context_for_adapter,
    fetch_and_cache_leverage_brackets,
)
from v2.backend.app.services.execution.binance_usdm_adapter import BinanceUSDMAdapter

DEFAULT_INTERVAL_SECONDS = 300

SYSTEMD_CREDENTIALS_DIRECTORY_ENV = "CREDENTIALS_DIRECTORY"
TRADER_ID_ENV = "ALPHAFORGE_INITIAL_TRADER_ID"
CREDENTIAL_REF_ENV = "ALPHAFORGE_INITIAL_TRADER_BINANCE_CREDENTIAL_REF"
BASE_URL_ENV = "BINANCE_USDM_REST_BASE_URL"
EVIDENCE_AUTH_KEY_ID_ENV = "BINANCE_BRACKET_EVIDENCE_HMAC_KEY_ID"
EVIDENCE_HMAC_SYSTEMD_CREDENTIAL = "binance_bracket_evidence_hmac_key"
MAX_SYSTEMD_CREDENTIAL_BYTES = 4096
_SYSTEMD_CREDENTIAL_COMPONENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


def _binding_credential_name(*, trader_id: str, credential_ref: str, suffix: str) -> str:
    """Bind a systemd credential slot to one exact public account identity."""

    for field_name, value in (
        ("TRADER_ID", trader_id),
        ("CREDENTIAL_REF", credential_ref),
        ("CREDENTIAL_SUFFIX", suffix),
    ):
        if not isinstance(value, str) or not _SYSTEMD_CREDENTIAL_COMPONENT_RE.fullmatch(value):
            raise LeverageBracketEvidenceError(f"{field_name}_UNSAFE_FOR_SYSTEMD_CREDENTIAL")
    name = f"{trader_id}--{credential_ref}--{suffix}"
    if len(name.encode("utf-8")) > 240:
        raise LeverageBracketEvidenceError("SYSTEMD_CREDENTIAL_NAME_TOO_LONG")
    return name


def _open_systemd_credentials_directory(directory: Path) -> int:
    if not directory.is_absolute() or directory.anchor != os.sep or ".." in directory.parts:
        raise LeverageBracketEvidenceError("SYSTEMD_CREDENTIALS_DIRECTORY_INVALID")
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = -1
    try:
        descriptor = os.open(os.sep, flags)
        for component in directory.parts[1:]:
            next_descriptor = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        metadata = os.fstat(descriptor)
    except OSError as exc:
        if descriptor >= 0:
            os.close(descriptor)
        raise LeverageBracketEvidenceError("SYSTEMD_CREDENTIALS_DIRECTORY_INVALID") from exc
    if not stat.S_ISDIR(metadata.st_mode):
        os.close(descriptor)
        raise LeverageBracketEvidenceError("SYSTEMD_CREDENTIALS_DIRECTORY_INVALID")
    return descriptor


def _read_systemd_credential(directory_descriptor: int, name: str) -> str:
    """Read one single-line credential without ever including its value in errors."""

    if not _SYSTEMD_CREDENTIAL_COMPONENT_RE.fullmatch(name):
        raise LeverageBracketEvidenceError("SYSTEMD_CREDENTIAL_NAME_UNSAFE")
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    try:
        descriptor = os.open(name, flags, dir_fd=directory_descriptor)
    except OSError as exc:
        raise LeverageBracketEvidenceError(
            f"SYSTEMD_CREDENTIAL_UNAVAILABLE_{name.upper()}"
        ) from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise LeverageBracketEvidenceError(f"SYSTEMD_CREDENTIAL_NOT_REGULAR_{name.upper()}")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            raw = stream.read(MAX_SYSTEMD_CREDENTIAL_BYTES + 1)
    except OSError as exc:
        raise LeverageBracketEvidenceError(f"SYSTEMD_CREDENTIAL_UNREADABLE_{name.upper()}") from exc
    finally:
        os.close(descriptor)
    if len(raw) > MAX_SYSTEMD_CREDENTIAL_BYTES:
        raise LeverageBracketEvidenceError(f"SYSTEMD_CREDENTIAL_TOO_LARGE_{name.upper()}")
    try:
        value = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise LeverageBracketEvidenceError(f"SYSTEMD_CREDENTIAL_NOT_UTF8_{name.upper()}") from exc
    value = value.removesuffix("\n").removesuffix("\r")
    if not value or value != value.strip() or any(char in value for char in "\r\n\x00"):
        raise LeverageBracketEvidenceError(f"SYSTEMD_CREDENTIAL_NOT_SINGLE_LINE_{name.upper()}")
    return value


def _adapter_and_security_context_from_systemd_credentials(
    *,
    environ: Mapping[str, str] | None = None,
) -> tuple[BinanceUSDMAdapter, EvidenceSecurityContext]:
    """Build an exact binding from systemd's encrypted credential directory.

    Presence of ``CREDENTIALS_DIRECTORY`` selects this strict path. Missing or
    malformed credentials never fall back to repository env files.
    """

    values = os.environ if environ is None else environ
    directory_text = values.get(SYSTEMD_CREDENTIALS_DIRECTORY_ENV, "")
    directory = Path(directory_text)
    if not directory_text:
        raise LeverageBracketEvidenceError("SYSTEMD_CREDENTIALS_DIRECTORY_INVALID")
    trader_id = values.get(TRADER_ID_ENV, "")
    credential_ref = values.get(CREDENTIAL_REF_ENV, "")
    base_url = values.get(BASE_URL_ENV, "")
    auth_key_id = values.get(EVIDENCE_AUTH_KEY_ID_ENV, "")
    api_key_name = _binding_credential_name(
        trader_id=trader_id,
        credential_ref=credential_ref,
        suffix="api_key",
    )
    api_secret_name = _binding_credential_name(
        trader_id=trader_id,
        credential_ref=credential_ref,
        suffix="api_secret",
    )
    directory_descriptor = _open_systemd_credentials_directory(directory)
    try:
        api_key = _read_systemd_credential(directory_descriptor, api_key_name)
        api_secret = _read_systemd_credential(directory_descriptor, api_secret_name)
        evidence_hmac_key = _read_systemd_credential(
            directory_descriptor,
            EVIDENCE_HMAC_SYSTEMD_CREDENTIAL,
        )
    finally:
        os.close(directory_descriptor)
    evidence_hmac_key_bytes = evidence_hmac_key.encode("utf-8")
    if hmac.compare_digest(evidence_hmac_key_bytes, api_key.encode("utf-8")):
        raise LeverageBracketEvidenceError("EVIDENCE_HMAC_KEY_MUST_DIFFER_FROM_EXCHANGE_API_KEY")
    if hmac.compare_digest(evidence_hmac_key_bytes, api_secret.encode("utf-8")):
        raise LeverageBracketEvidenceError("EVIDENCE_HMAC_KEY_MUST_DIFFER_FROM_EXCHANGE_SECRET")
    context = build_evidence_security_context(
        trader_id=trader_id,
        credential_ref=credential_ref,
        base_url=base_url,
        credential_account_specific=True,
        hmac_key=evidence_hmac_key,
        auth_key_id=auth_key_id,
    )
    adapter = BinanceUSDMAdapter(
        api_key=api_key,
        api_secret=api_secret,
        base_url=context.base_url_origin,
    )
    return adapter, context


def _redis_client(redis_url: str | None = None) -> Any:
    try:
        import redis
    except Exception:
        return None
    url = (
        redis_url
        or os.environ.get("V2_REDIS_URL")
        or os.environ.get("REDIS_URL")
        or "redis://127.0.0.1:6379/0"
    )
    try:
        client = redis.Redis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=2.0,
            socket_timeout=5.0,
        )
        client.ping()
        return client
    except Exception:
        return None


def _parse_symbols(values: Iterable[str]) -> tuple[str, ...]:
    symbols: list[str] = []
    for value in values:
        symbols.extend(item.strip() for item in str(value).split(",") if item.strip())
    return tuple(symbols)


def public_status(payload: dict[str, Any]) -> dict[str, Any]:
    """Return safe binding identifiers while excluding all secret material."""

    return {
        "schema_version": payload.get("schema_version"),
        "status": payload.get("status"),
        "reason": payload.get("reason"),
        "adapter_status": payload.get("adapter_status"),
        "source_endpoint": payload.get("source_endpoint"),
        "security_type": payload.get("security_type"),
        "exchange_environment": payload.get("exchange_environment"),
        "credential_binding_id": payload.get("credential_binding_id"),
        "trader_id": payload.get("trader_id"),
        "credential_ref": payload.get("credential_ref"),
        "credential_ref_read_only_assertion": payload.get("credential_ref_read_only_assertion"),
        "credential_ref_read_only_assertion_semantics": payload.get(
            "credential_ref_read_only_assertion_semantics"
        ),
        "exchange_key_permissions_proven_by_connector": payload.get(
            "exchange_key_permissions_proven_by_connector"
        ),
        "evidence_auth_algorithm": payload.get("evidence_auth_algorithm"),
        "evidence_auth_key_id": payload.get("evidence_auth_key_id"),
        "fetched_at": payload.get("fetched_at"),
        "generated_at": payload.get("generated_at"),
        "available_at": payload.get("available_at"),
        "symbols_requested": payload.get("symbols_requested", []),
        "symbols_received": payload.get("symbols_received", []),
        "symbols_published": payload.get("symbols_published", []),
        "missing_symbols": payload.get("missing_symbols", []),
        "invalid_symbols": payload.get("invalid_symbols", []),
        "redis_write_failed_symbols": payload.get("redis_write_failed_symbols", []),
        "read_only": True,
        "safe_binding_identifiers_exposed": True,
        "credential_fields_exposed": False,
        "credential_fields_exposed_semantics": (
            "NO_EXCHANGE_API_KEY_SECRET_OR_SIGNED_REQUEST_FIELDS;"
            "SAFE_BINDING_IDENTIFIERS_ARE_EXPOSED"
        ),
        "evidence_auth_key_exposed": False,
        "exchange_api_secret_exposed": False,
        "raw_response_exposed": False,
        "places_real_order": False,
        "order_submitted": False,
        "leverage_mutated": False,
        "margin_mutated": False,
    }


def run_once(
    *,
    adapter: Any,
    redis_client: Any,
    security_context: EvidenceSecurityContext | None,
    symbols: Iterable[str] = (),
    execute: bool = True,
    freshness_seconds: int = DEFAULT_FRESHNESS_SECONDS,
    cache_ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
) -> dict[str, Any]:
    return fetch_and_cache_leverage_brackets(
        adapter=adapter,
        redis_client=redis_client,
        security_context=security_context,
        symbols=symbols,
        execute=execute,
        freshness_seconds=freshness_seconds,
        cache_ttl_seconds=cache_ttl_seconds,
    )


def run_loop(
    *,
    adapter: Any,
    redis_client: Any,
    security_context: EvidenceSecurityContext | None,
    symbols: Iterable[str] = (),
    execute: bool = True,
    freshness_seconds: int = DEFAULT_FRESHNESS_SECONDS,
    cache_ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
    interval_seconds: float = DEFAULT_INTERVAL_SECONDS,
    stop_event: threading.Event | None = None,
    max_cycles: int | None = None,
    on_result: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    if interval_seconds <= 0:
        raise ValueError("INTERVAL_SECONDS_MUST_BE_POSITIVE")
    stopper = stop_event or threading.Event()
    cycles = 0
    latest: dict[str, Any] = {}
    while not stopper.is_set():
        latest = run_once(
            adapter=adapter,
            redis_client=redis_client,
            security_context=security_context,
            symbols=symbols,
            execute=execute,
            freshness_seconds=freshness_seconds,
            cache_ttl_seconds=cache_ttl_seconds,
        )
        cycles += 1
        if on_result is not None:
            on_result(latest)
        if max_cycles is not None and cycles >= max_cycles:
            break
        stopper.wait(interval_seconds)
    return latest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true", help="run one cycle (default)")
    mode.add_argument("--loop", action="store_true", help="poll until interrupted")
    parser.add_argument(
        "--symbols",
        action="append",
        default=[],
        help="comma-separated symbols; omitted requests the account's full bracket list",
    )
    parser.add_argument("--redis-url", default=None)
    parser.add_argument("--freshness-seconds", type=int, default=DEFAULT_FRESHNESS_SECONDS)
    parser.add_argument("--cache-ttl-seconds", type=int, default=DEFAULT_CACHE_TTL_SECONDS)
    parser.add_argument("--interval-seconds", type=float, default=DEFAULT_INTERVAL_SECONDS)
    parser.add_argument(
        "--no-execute",
        action="store_true",
        help="build the signed adapter contract without making the read-only GET",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    symbols = _parse_symbols(args.symbols)

    def emit(payload: dict[str, Any]) -> None:
        view = public_status(payload)
        print(json.dumps(view, indent=2 if args.json else None, sort_keys=True))

    try:
        if SYSTEMD_CREDENTIALS_DIRECTORY_ENV in os.environ:
            adapter, security_context = _adapter_and_security_context_from_systemd_credentials()
        else:
            adapter = BinanceUSDMAdapter.from_env()
            security_context = evidence_security_context_for_adapter(adapter)
    except LeverageBracketEvidenceError as exc:
        emit(
            {
                "schema_version": STATUS_SCHEMA_VERSION,
                "status": "BLOCKED",
                "reason": str(exc),
                "source_endpoint": "/fapi/v1/leverageBracket",
                "security_type": "USER_DATA",
                "symbols_requested": list(symbols),
                "symbols_received": [],
                "symbols_published": [],
                "missing_symbols": [],
                "invalid_symbols": [],
                "redis_write_failed_symbols": [],
            }
        )
        return 2
    redis_client = _redis_client(args.redis_url)

    if args.loop:
        try:
            payload = run_loop(
                adapter=adapter,
                redis_client=redis_client,
                security_context=security_context,
                symbols=symbols,
                execute=not args.no_execute,
                freshness_seconds=args.freshness_seconds,
                cache_ttl_seconds=args.cache_ttl_seconds,
                interval_seconds=args.interval_seconds,
                on_result=emit,
            )
        except KeyboardInterrupt:
            return 130
    else:
        payload = run_once(
            adapter=adapter,
            redis_client=redis_client,
            security_context=security_context,
            symbols=symbols,
            execute=not args.no_execute,
            freshness_seconds=args.freshness_seconds,
            cache_ttl_seconds=args.cache_ttl_seconds,
        )
        emit(payload)
    return 0 if payload.get("status") == "READY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
