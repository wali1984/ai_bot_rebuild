#!/usr/bin/env python3
from __future__ import annotations
import argparse,re
from pathlib import Path
from common_audit import resolve_path, read_text_safely, write_json, evidence_record
KEYS=["feature","observation","state","MASS","state_space","tensor","normalize","fillna","nan","zero","freshness","stale"]

def main()->int:
    ap=argparse.ArgumentParser(); ap.add_argument("--trainer-file",required=True); ap.add_argument("--out-dir",default="./claude_worklog/trainer_atlas"); args=ap.parse_args()
    t=resolve_path(args.trainer_file,Path.cwd()); out=resolve_path(args.out_dir,Path.cwd()); txt=read_text_safely(t,max_bytes=200_000_000)
    rx=re.compile("|".join(re.escape(k) for k in KEYS),re.I); matches=[]
    for i,line in enumerate(txt.splitlines(),start=1):
        if rx.search(line): matches.append({"line":i,"text":line.strip()[:500],"evidence":evidence_record(str(t),i,line.strip()[:300],"feature_path","trainer feature keyword")})
    write_json(out/"HYBRID_TRAINER_FEATURE_PATHS.json",{"matches":matches}); return 0
if __name__=="__main__": raise SystemExit(main())
