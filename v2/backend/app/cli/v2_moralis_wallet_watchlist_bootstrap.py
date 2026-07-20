"""Bootstrap the Moralis wallet watchlist from on-chain evidence.

For every VERIFIED+pollable token in the map, pulls top ERC20 holders and
recent transfer participants from Moralis (CU-charged against the daily
budget), classifies every address through the exclusion system (exchange /
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
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.smart_money_wallets.budgeted_http import (
    MoralisBudgetedHttpResult,
    budgeted_moralis_get_json,
)
from app.services.smart_money_wallets.endpoint_registry import moralis_endpoint_registry
from app.services.smart_money_wallets.rate_limit import MoralisRateLimiter

BASE = "https://deep-index.moralis.io/api/v2.2"
CHAIN_PARAM = {"ethereum": "eth", "arbitrum": "arbitrum", "optimism": "optimism", "bsc": "bsc"}
SEED_PATH = Path("v2/config/moralis/wallet_watchlist_seed.yaml")
_ENDPOINT_COSTS = {spec.endpoint_id: int(spec.cu_cost) for spec in moralis_endpoint_registry()}
HOLDERS_CU = _ENDPOINT_COSTS["token_holders"]
TRANSFERS_CU = _ENDPOINT_COSTS["token_address_transfers"]
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
        from v2.backend.app.services.safe_env_loader import bootstrap_process_env

        bootstrap_process_env(apply=True)
    except Exception:
        pass
    api_key = os.environ.get("MORALIS_API_KEY", "")
    if not api_key:
        print(json.dumps({"status": "BLOCKED", "reason": "MORALIS_API_KEY_ABSENT"}))
        return 2
    r = _redis_client(args.redis_url)
    report = bootstrap_watchlist(
        r,
        api_key=api_key,
        holders_per_token=args.holders_per_token,
        transfers_per_token=args.transfers_per_token,
    )
    if args.output_dir:
        out = Path(args.output_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "wallet_watchlist_bootstrap.json").write_text(
            json.dumps(report, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
        )
    print(json.dumps({k: report[k] for k in ("status", "t0_count", "t1_count", "excluded_count", "cu_spent")}, sort_keys=True))
    return 0


def bootstrap_watchlist(
    r: Any,
    *,
    api_key: str,
    holders_per_token: int = 20,
    transfers_per_token: int = 50,
    limiter: MoralisRateLimiter | None = None,
    http_client: Any | None = None,
) -> dict[str, Any]:
    from v2.backend.app.services.smart_money_wallets.address_classifier import (
        classify_address,
    )
    from v2.backend.app.services.smart_money_wallets.wallet_watchlist import (
        publish_wallet_watchlist,
    )

    now = _now()
    request_limiter = limiter or MoralisRateLimiter(redis_client=r, mode="catchup")
    tokens = _pollable_tokens(r)
    evidence: dict[str, dict[str, Any]] = {}
    excluded: list[dict[str, Any]] = []
    cu_spent = 0
    tokens_polled = 0

    for token in tokens:
        chain = CHAIN_PARAM.get(str(token["chain"]).lower())
        if chain is None:
            continue
        contract = token["contract_address"]
        symbol = token["symbol"]
        holders_outcome = _get(
            api_key,
            f"/erc20/{contract}/owners",
            endpoint_id="token_holders",
            estimated_cu=HOLDERS_CU,
            limiter=request_limiter,
            http_client=http_client,
            chain=chain,
            limit=holders_per_token,
            order="DESC",
        )
        if not holders_outcome.request_dispatched:
            break
        cu_spent += holders_outcome.accounted_cu
        tokens_polled += 1

        holders = holders_outcome.payload if holders_outcome.ok else None
        for rank, row in enumerate((holders or {}).get("result") or [], start=1):
            address = str(row.get("owner_address") or "").lower()
            if not address:
                continue
            meta = {
                "is_contract": bool(row.get("is_contract")),
                "label": row.get("owner_address_label"),
            }
            cls = classify_address(chain=chain, address=address, metadata=meta)
            if not cls.get("smart_wallet_eligible"):
                excluded.append({"address": address, "chain": chain, "category": cls.get("category"),
                                 "label": cls.get("label"), "source": f"top_holder:{symbol}:rank={rank}"})
                continue
            entry = evidence.setdefault(address, {
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

        transfers_outcome = _get(
            api_key,
            f"/erc20/{contract}/transfers",
            endpoint_id="token_address_transfers",
            estimated_cu=TRANSFERS_CU,
            limiter=request_limiter,
            http_client=http_client,
            chain=chain,
            limit=transfers_per_token,
            order="DESC",
        )
        cu_spent += transfers_outcome.accounted_cu
        transfers = transfers_outcome.payload if transfers_outcome.ok else None
        for row in (transfers or {}).get("result") or []:
            for field in ("from_address", "to_address"):
                address = str(row.get(field) or "").lower()
                if not address:
                    continue
                label_field = f"{field}_label"
                meta = {"is_contract": False, "label": row.get(label_field)}
                cls = classify_address(chain=chain, address=address, metadata=meta)
                if not cls.get("smart_wallet_eligible"):
                    if cls.get("category") not in (None, "unknown"):
                        excluded.append({"address": address, "chain": chain, "category": cls.get("category"),
                                         "label": cls.get("label"), "source": f"transfer:{symbol}"})
                    continue
                entry = evidence.setdefault(address, {
                    "address": address, "chain": chain, "sources": [], "tokens": set(),
                    "holder_best_rank": None, "holder_usd": 0.0, "transfer_hits": 0,
                    "label": row.get(label_field),
                })
                entry["transfer_hits"] += 1
                entry["tokens"].add(symbol)
                if f"transfer_participant:{symbol}" not in entry["sources"]:
                    entry["sources"].append(f"transfer_participant:{symbol}")

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
    manual = [w for w in (seed.get("wallets") or []) if str(w.get("added_by") or "") != "v2_moralis_wallet_watchlist_bootstrap"]
    seed["wallets"] = manual + wallets
    seed["bootstrap_generated_utc"] = now
    SEED_PATH.write_text(json.dumps(seed, indent=2, sort_keys=False, default=str) + "\n", encoding="utf-8")

    status = publish_wallet_watchlist(r, path=SEED_PATH)
    if excluded:
        r.set(
            "v2:moralis:excluded_addresses:bootstrap_observed",
            json.dumps({"generated_utc": now, "rows": excluded[:200]}, default=str),
            ex=7 * 86400,
        )
    t0 = sum(1 for w in wallets if w["tier"] == "T0")
    t1 = sum(1 for w in wallets if w["tier"] == "T1")
    result_status = "WATCHLIST_READY" if (t0 + t1) else "MORALIS_WATCHLIST_INSUFFICIENT_QUALIFIED_WALLETS"
    return {
        "schema_version": "moralis_wallet_watchlist_bootstrap_v1",
        "generated_utc": now,
        "status": result_status,
        "tokens_polled": tokens_polled,
        "t0_count": t0,
        "t1_count": t1,
        "excluded_count": len(excluded),
        "cu_spent": cu_spent,
        "publish_status": status,
        "no_wallet_labeled_verified_smart_money": True,
        "raw_key_exposed": False,
    }


def _pollable_tokens(r: Any) -> list[dict[str, str]]:
    tokens: list[dict[str, str]] = []
    for key in r.scan_iter("v2:moralis:token_map:*", count=500):
        if key.endswith("_status"):
            continue
        try:
            row = json.loads(r.get(key) or "{}")
        except (TypeError, ValueError):
            continue
        for contract in row.get("contracts") or []:
            if isinstance(contract, dict) and contract.get("pollable") is True:
                tokens.append({
                    "symbol": str(row.get("symbol")),
                    "chain": str(contract.get("chain")),
                    "contract_address": str(contract.get("contract_address")),
                })
    return tokens


def _get(
    api_key: str,
    path: str,
    *,
    endpoint_id: str,
    estimated_cu: int,
    limiter: MoralisRateLimiter,
    http_client: Any | None,
    **params: Any,
) -> MoralisBudgetedHttpResult:
    return budgeted_moralis_get_json(
        api_key=api_key,
        endpoint_id=endpoint_id,
        path=path,
        params=params,
        estimated_cu=estimated_cu,
        limiter=limiter,
        base_url=BASE,
        timeout_seconds=20.0,
        http_client=http_client,
    )


def _f(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _redis_client(redis_url: str) -> Any:
    import redis  # type: ignore[import-not-found]

    return redis.Redis.from_url(redis_url, decode_responses=True)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())
