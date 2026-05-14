#!/usr/bin/env python3
"""
Monitor orchestrator (shadow mode) proofs and publish stats.

Captures:
- ORCHESTRATOR_PROOF events from Redis stream (default: health:events)
- Trainer publish attempts/oks from logs (best-effort, file tail)
- Writes a markdown report for operator review.

Usage:
  python3 scripts/monitor_orchestrator_shadow.py --minutes 5 --interval 30 --out Documentation/Audits/ORCH_SHADOW_$(date +%Y%m%d_%H%M%S).md
"""

import argparse
import json
import os
import time
from datetime import datetime, timezone

import redis


def now_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=int, default=5)
    ap.add_argument("--interval", type=int, default=30)
    ap.add_argument("--stream", type=str, default=os.getenv("ORCHESTRATOR_PROOF_STREAM", "health:events"))
    ap.add_argument("--out", type=str, required=True)
    ap.add_argument("--redis-url", type=str, default=os.getenv("REDIS_URL", "redis://localhost:6379/0"))
    ap.add_argument("--log", type=str, default="logs/hybrid_trainer.log")
    return ap.parse_args()


def main():
    args = parse_args()
    r = redis.Redis.from_url(args.redis_url, decode_responses=True)

    end_ts = time.time() + (args.minutes * 60)
    last_id = "$"  # only new

    rows = []
    while time.time() < end_ts:
        try:
            resp = r.xread({args.stream: last_id}, count=500, block=1000)
            for _stream, msgs in resp:
                for msg_id, fields in msgs:
                    last_id = msg_id
                    data = fields.get("data")
                    if not data:
                        continue
                    try:
                        obj = json.loads(data)
                    except Exception:
                        continue
                    if obj.get("event") != "ORCHESTRATOR_PROOF":
                        continue
                    rows.append((msg_id, obj))
        except Exception:
            pass

        time.sleep(max(1, int(args.interval)))

    # Summaries
    by_account = {}
    by_reason = {}
    resized = 0
    dropped = 0
    total = len(rows)

    for _id, o in rows:
        acct = str(o.get("account_id", ""))
        by_account[acct] = by_account.get(acct, 0) + 1
        reason = str(o.get("reason", ""))
        by_reason[reason] = by_reason.get(reason, 0) + 1
        if o.get("resized"):
            resized += 1
        if o.get("dropped"):
            dropped += 1

    # Best-effort: tail trainer log for publish lines
    publish_lines = []
    try:
        with open(args.log, "r", encoding="utf-8", errors="ignore") as f:
            tail = f.readlines()[-2500:]
        for ln in tail:
            if "PUBLISH_ATTEMPT" in ln or "PUBLISH_OK" in ln or "[ORCH]" in ln:
                publish_lines.append(ln.rstrip())
    except Exception:
        pass

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as out:
        out.write(f"# Orchestrator Shadow Monitor Report\n\n")
        out.write(f"- **Generated:** {now_ts()}\n")
        out.write(f"- **Duration:** {args.minutes} minutes\n")
        out.write(f"- **Interval:** {args.interval} seconds\n")
        out.write(f"- **Stream:** `{args.stream}`\n")
        out.write(f"- **Total proofs captured:** {total}\n\n")

        out.write("## Summary\n\n")
        out.write(f"- **resized**: {resized}\n")
        out.write(f"- **dropped**: {dropped}\n\n")

        out.write("### Proofs by account\n\n")
        for k in sorted(by_account.keys()):
            out.write(f"- **{k}**: {by_account[k]}\n")

        out.write("\n### Proofs by reason\n\n")
        for k, v in sorted(by_reason.items(), key=lambda kv: kv[1], reverse=True)[:20]:
            out.write(f"- **{k}**: {v}\n")

        out.write("\n## Sample proofs (first 25)\n\n")
        for msg_id, o in rows[:25]:
            out.write(f"### {msg_id}\n\n")
            out.write("```json\n")
            out.write(json.dumps(o, indent=2, sort_keys=True))
            out.write("\n```\n\n")

        out.write("## Recent trainer publish log lines (best-effort tail)\n\n")
        out.write("```text\n")
        out.write("\n".join(publish_lines[-200:]))
        out.write("\n```\n")


if __name__ == "__main__":
    main()

