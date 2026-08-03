"""Bootstrap the Moralis wallet watchlist from on-chain evidence.

For every VERIFIED+pollable token in the map, consumes the canonical
scheduler's fresh ERC20-holder cache, classifies every address
through the exclusion system (exchange /
bridge / contract wallets are recorded as exclusions, never smart money), and
tiers the survivors:

  T0  strongest evidence (top holder rank across tokens, capped)
  T1  qualified candidates (holders/transfer participants past exclusions)

Every wallet row is source-tagged (e.g. ``top_holder:LINKUSDT:rank=3``) and
labeled CANDIDATE_SMART_WALLET at most — bootstrap NEVER mints
VERIFIED_SMART_WALLET labels; that requires behavior history via the scorer.
Writes the seed file + publishes v2:moralis:wallet_watchlist.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.services.smart_money_wallets.canonical_cache import read_canonical_records
from app.services.smart_money_wallets.client import prepare_request_identity
from app.services.smart_money_wallets.endpoint_registry import moralis_endpoint_registry
from app.services.smart_money_wallets.token_contract_mapper import read_pollable_tokens

BASE = "https://deep-index.moralis.io/api/v2.2"
SEED_PATH = Path("v2/config/moralis/wallet_watchlist_seed.yaml")
_ENDPOINT_SPECS = {spec.endpoint_id: spec for spec in moralis_endpoint_registry()}
_TOKEN_IDENTITY_SPEC = _ENDPOINT_SPECS["token_holders"]
_WALLET_IDENTITY_SPEC = _ENDPOINT_SPECS["wallet_transactions"]
_SYMBOL = re.compile(r"[A-Z0-9]{2,32}")
T0_CAP = 20
T1_CAP = 250


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v2_moralis_wallet_watchlist_bootstrap")
    parser.add_argument("--redis-url", default=os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--holders-per-token", type=int, default=20)
    parser.add_argument("--transfers-per-token", type=int, default=50)
    args = parser.parse_args(argv)
    try:
        from v2.backend.app.services.safe_env_loader import (  # type: ignore[import-untyped]
            bootstrap_process_env,
        )

        bootstrap_process_env(apply=True)
    except Exception:  # noqa: S110 - optional environment bootstrap
        pass
    r = _redis_client(args.redis_url)
    report = bootstrap_watchlist(
        r,
        holders_per_token=args.holders_per_token,
        transfers_per_token=args.transfers_per_token,
    )
    if args.output_dir:
        out = Path(args.output_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "wallet_watchlist_bootstrap.json").write_text(
            json.dumps(report, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
        )
    summary_keys = ("status", "t0_count", "t1_count", "excluded_count", "cu_spent")
    print(json.dumps({key: report[key] for key in summary_keys}, sort_keys=True))
    return 0


def bootstrap_watchlist(
    r: Any,
    *,
    api_key: str = "",
    holders_per_token: int = 20,
    transfers_per_token: int = 50,
    limiter: Any | None = None,
    http_client: Any | None = None,
) -> dict[str, Any]:
    # Kept in the callable contract for existing operators.  Token-transfer
    # polling is exclusively owned by the canonical scheduler, so bootstrap
    # never dispatches that duplicate transport.
    del api_key, transfers_per_token, limiter, http_client
    from v2.backend.app.services.smart_money_wallets.address_classifier import (  # type: ignore[import-untyped]
        classify_address,
    )
    from v2.backend.app.services.smart_money_wallets.wallet_watchlist import (  # type: ignore[import-untyped]
        publish_wallet_watchlist,
    )

    now = _now()
    tokens = _pollable_tokens(r)
    evidence: dict[tuple[str, str], dict[str, Any]] = {}
    excluded: list[dict[str, Any]] = []
    quarantined_tokens: list[dict[str, Any]] = []
    invalid_provider_address_count = 0
    cu_spent = 0
    tokens_polled = 0
    canonical_cache_hit_count = 0

    for token in tokens:
        raw_contract = token.get("contract_address")
        symbol = str(token.get("symbol") or "").strip().upper()
        identity = prepare_request_identity(
            _TOKEN_IDENTITY_SPEC,
            chain=token.get("chain"),
            token=raw_contract,
        )
        if identity.error_class is not None or _SYMBOL.fullmatch(symbol) is None:
            quarantined_tokens.append(
                {
                    "reason": identity.error_class or "SYMBOL_INVALID",
                    "target_fingerprint": _fingerprint(raw_contract),
                }
            )
            continue
        chain = identity.chain
        contract = identity.token
        if contract is None:
            quarantined_tokens.append(
                {
                    "reason": "TOKEN_REQUIRED",
                    "target_fingerprint": _fingerprint(raw_contract),
                }
            )
            continue
        cached_holders = read_canonical_records(
            r,
            endpoint_id="token_holders",
            chain=chain,
            token=contract,
        )
        if not cached_holders.ready:
            quarantined_tokens.append(
                {
                    "reason": cached_holders.reason,
                    "target_fingerprint": _fingerprint(contract),
                }
            )
            continue
        tokens_polled += 1
        canonical_cache_hit_count += 1

        for rank, row in enumerate(
            cached_holders.records[: max(0, int(holders_per_token))],
            start=1,
        ):
            address = _validated_wallet_address(chain, row.get("owner_address"))
            if address is None:
                invalid_provider_address_count += 1
                continue
            meta = {
                "is_contract": bool(row.get("is_contract")),
                "label": row.get("owner_address_label"),
            }
            cls = classify_address(chain=chain, address=address, metadata=meta)
            if not cls.get("smart_wallet_eligible"):
                excluded.append(
                    {
                        "address": address,
                        "chain": chain,
                        "category": cls.get("category"),
                        "label": cls.get("label"),
                        "source": f"top_holder:{symbol}:rank={rank}",
                    }
                )
                continue
            entry = evidence.setdefault((chain, address), {
                "address": address, "chain": chain, "sources": [], "tokens": set(),
                "holder_best_rank": None, "holder_usd": 0.0, "transfer_hits": 0,
                "label": row.get("owner_address_label"),
            })
            entry["sources"].append(f"top_holder:{symbol}:rank={rank}")
            entry["tokens"].add(symbol)
            entry["holder_best_rank"] = min(rank, entry["holder_best_rank"] or rank)
            usd = _f(row.get("usd_value"))
            if usd:
                entry["holder_usd"] = max(entry["holder_usd"], usd)

    ranked = sorted(
        evidence.values(),
        key=lambda e: (
            -(1.0 / e["holder_best_rank"] if e["holder_best_rank"] else 0.0),
            -e["holder_usd"],
            -len(e["tokens"]),
            -e["transfer_hits"],
        ),
    )
    wallets: list[dict[str, Any]] = []
    for index, entry in enumerate(ranked[: T0_CAP + T1_CAP]):
        tier = "T0" if index < T0_CAP and entry["holder_best_rank"] else "T1"
        wallets.append({
            "address": entry["address"],
            "chain": entry["chain"],
            "tier": tier,
            "classification": "CANDIDATE_SMART_WALLET",
            "verified_smart_wallet": False,
            "label": entry.get("label"),
            "source": ";".join(entry["sources"][:6]),
            "watch_tokens": sorted(entry["tokens"]),
            "holder_best_rank": entry["holder_best_rank"],
            "holder_usd_hint": entry["holder_usd"],
            "transfer_hits": entry["transfer_hits"],
            "added_utc": now,
            "added_by": "v2_moralis_wallet_watchlist_bootstrap",
        })

    seed = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    manual = [
        wallet
        for wallet in (seed.get("wallets") or [])
        if str(wallet.get("added_by") or "")
        != "v2_moralis_wallet_watchlist_bootstrap"
    ]
    seed["wallets"] = manual + wallets
    seed["bootstrap_generated_utc"] = now
    SEED_PATH.write_text(
        json.dumps(seed, indent=2, sort_keys=False, default=str) + "\n",
        encoding="utf-8",
    )

    status = publish_wallet_watchlist(r, path=SEED_PATH)
    if excluded:
        r.set(
            "v2:moralis:excluded_addresses:bootstrap_observed",
            json.dumps({"generated_utc": now, "rows": excluded[:200]}, default=str),
            ex=7 * 86400,
        )
    t0 = sum(1 for w in wallets if w["tier"] == "T0")
    t1 = sum(1 for w in wallets if w["tier"] == "T1")
    result_status = (
        "WATCHLIST_READY"
        if (t0 + t1)
        else "MORALIS_WATCHLIST_INSUFFICIENT_QUALIFIED_WALLETS"
    )
    return {
        "schema_version": "moralis_wallet_watchlist_bootstrap_v1",
        "generated_utc": now,
        "status": result_status,
        "tokens_polled": tokens_polled,
        "t0_count": t0,
        "t1_count": t1,
        "excluded_count": len(excluded),
        "quarantined_token_count": len(quarantined_tokens),
        "quarantined_tokens": quarantined_tokens,
        "invalid_provider_address_count": invalid_provider_address_count,
        "cu_spent": cu_spent,
        "canonical_holder_cache_hit_count": canonical_cache_hit_count,
        "holder_http_request_count": 0,
        "token_transfer_request_count": 0,
        "token_holder_transport_owner": "CANONICAL_PROVIDER_SCHEDULER",
        "token_transfer_transport_owner": "CANONICAL_PROVIDER_SCHEDULER",
        "publish_status": status,
        "no_wallet_labeled_verified_smart_money": True,
        "raw_key_exposed": False,
    }


def _pollable_tokens(r: Any) -> list[dict[str, str]]:
    return [
        {
            "symbol": row["symbol"],
            "chain": row["chain"],
            "contract_address": row["token"],
        }
        for row in read_pollable_tokens(r)
    ]


def _validated_wallet_address(chain: str, value: object) -> str | None:
    identity = prepare_request_identity(
        _WALLET_IDENTITY_SPEC,
        chain=chain,
        wallet=value,
    )
    return identity.wallet if identity.error_class is None else None


def _fingerprint(value: object | None) -> str | None:
    if value is None:
        return None
    return hashlib.sha256(
        str(value).encode("utf-8", errors="replace")
    ).hexdigest()[:16]


def _f(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _redis_client(redis_url: str) -> Any:
    import redis

    return redis.Redis.from_url(redis_url, decode_responses=True)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())
