#!/usr/bin/env python3
"""
One-time repair: deduplicate v2:paper:closed_trades by close_id.

Root cause (CG-F019): 6 duplicate close_id entries in v2:paper:closed_trades
cause the G08 accounting reconciliation gate to fail.  The portfolio publisher
already deduplicates before computing closed_ledger_net_pnl_usd, so the
verifier's raw sum (includes duplicates) diverges from the publisher's sum
(deduped) by a constant $0.028301.

This script reads v2:paper:closed_trades, removes the second occurrence of
any duplicate close_id (keeping first, matching publisher behaviour), and
writes the deduped list back.

Safe to run while paper loop is active — it overwrites the key with fewer
entries (the non-duplicated set).  The paper loop will write fresh deduped
data on its next iteration once restarted with the fixed code.

Usage:
    python3 tools/repair_dedup_closed_trades.py [--dry-run]
"""
import json
import sys
import argparse
import redis


def get_close_id(row: dict) -> str:
    for key in ("close_id", "paper_close_id"):
        v = row.get(key)
        if v:
            return str(v)
    return (
        f"{row.get('symbol')}:{row.get('entry_time')}:{row.get('exit_time')}:{row.get('side')}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Dedup v2:paper:closed_trades")
    parser.add_argument("--dry-run", action="store_true", help="Print plan without writing")
    parser.add_argument("--redis-url", default="redis://localhost:6379/0")
    args = parser.parse_args()

    r = redis.from_url(args.redis_url, decode_responses=True)
    raw = r.get("v2:paper:closed_trades")
    if not raw:
        print("v2:paper:closed_trades is empty or missing — nothing to do")
        return 0

    trades = json.loads(raw)
    before_count = len(trades)
    before_sum = sum(float(t.get("realized_pnl_usd") or 0) for t in trades)

    seen: set[str] = set()
    deduped: list[dict] = []
    removed: list[dict] = []
    for t in trades:
        cid = get_close_id(t)
        if cid in seen:
            removed.append({"close_id": cid, "pnl": t.get("realized_pnl_usd")})
        else:
            seen.add(cid)
            deduped.append(t)

    after_count = len(deduped)
    after_sum = sum(float(t.get("realized_pnl_usd") or 0) for t in deduped)

    print(f"Before: {before_count} rows, sum={before_sum:.8f}")
    print(f"After:  {after_count} rows, sum={after_sum:.8f}")
    print(f"Removed {len(removed)} duplicates:")
    for r_ in removed:
        print(f"  {r_['close_id']}: pnl={r_['pnl']}")

    if args.dry_run:
        print("[DRY RUN] Not writing.")
        return 0

    # Preserve the original TTL if any
    ttl = r.ttl("v2:paper:closed_trades")
    if ttl > 0:
        r.set("v2:paper:closed_trades", json.dumps(deduped), ex=ttl)
    else:
        r.set("v2:paper:closed_trades", json.dumps(deduped))

    verify = json.loads(r.get("v2:paper:closed_trades") or "[]")
    print(f"Verified write: {len(verify)} rows, sum={sum(float(t.get('realized_pnl_usd') or 0) for t in verify):.8f}")
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
