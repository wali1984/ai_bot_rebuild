#!/usr/bin/env python3
from __future__ import annotations
import argparse, re
from pathlib import Path
from common_audit import resolve_path, read_text_safely, write_json, evidence_record, redact_text

TOKENS=["redis","xadd","xread","xrevrange","xlen","hset","hgetall","set(","get(","publish","subscribe","xdel","xtrim","delete","lpush","rpush","sadd","zadd","exists("]
WRITE_TOKENS=["xadd","hset","set(","publish","xdel","xtrim","delete","lpush","rpush","sadd","zadd"]
READ_TOKENS=["xread","xrevrange","xlen","hgetall","get(","subscribe","exists("]


def classify_write(line_l: str) -> str:
    if any(k in line_l for k in ["heartbeat"]):
        return "write_heartbeat"
    if any(k in line_l for k in ["signal", "action", "long", "short", "buy", "sell", "prediction", "confidence"]):
        return "write_signal"
    if any(k in line_l for k in ["checkpoint", "model", "version", "state_dict", "save", "load", "best_model"]):
        return "write_checkpoint_metadata"
    if any(k in line_l for k in ["risk", "halt", "circuit", "cooldown", "guard"]):
        return "write_risk_state"
    return "write_metric"


def classify_line(line: str) -> str:
    ll = line.lower()
    if any(t in ll for t in WRITE_TOKENS):
        return classify_write(ll)
    if any(t in ll for t in READ_TOKENS):
        return "read_only"
    if "redis" in ll:
        return "read_only"
    return "read_only"

def main()->int:
    ap=argparse.ArgumentParser(); ap.add_argument("--trainer-file",required=True); ap.add_argument("--out-dir",default="./claude_worklog/trainer_atlas"); args=ap.parse_args()
    t=resolve_path(args.trainer_file,Path.cwd()); out=resolve_path(args.out_dir,Path.cwd()); txt=read_text_safely(t,max_bytes=200_000_000)
    rx=re.compile("|".join(re.escape(x) for x in TOKENS),re.I); matches=[]; unknown_writes=0
    for i,line in enumerate(txt.splitlines(),start=1):
        if rx.search(line):
            cls=classify_line(line)
            if cls=="unknown_write":
                unknown_writes+=1
            matches.append({
                "line":i,
                "classification":cls,
                "text":(redact_text(line.strip()[:500]) or ""),
                "evidence":evidence_record(str(t),i,line.strip()[:300],cls,"trainer redis usage")
            })
    write_json(out/"HYBRID_TRAINER_REDIS_USAGE.json",{
        "matches":matches,
        "unknown_redis_writes":unknown_writes,
        "class_counts":{k:sum(1 for m in matches if m.get("classification")==k) for k in ["read_only","write_signal","write_metric","write_checkpoint_metadata","write_heartbeat","write_risk_state","unknown_write"]}
    }); return 0
if __name__=="__main__": raise SystemExit(main())
