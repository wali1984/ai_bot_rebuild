#!/usr/bin/env python3
from __future__ import annotations
import argparse,re
from pathlib import Path
from common_audit import resolve_path, read_text_safely, write_json, evidence_record
PATS=["os.getenv","os.environ","environ[","from config import","import config","config."]

def main()->int:
    ap=argparse.ArgumentParser(); ap.add_argument("--trainer-file",required=True); ap.add_argument("--out-dir",default="./claude_worklog/trainer_atlas"); args=ap.parse_args()
    t=resolve_path(args.trainer_file,Path.cwd()); out=resolve_path(args.out_dir,Path.cwd()); txt=read_text_safely(t,max_bytes=200_000_000)
    rx=re.compile("|".join(re.escape(x) for x in PATS),re.I); env=re.compile(r"\b[A-Z][A-Z0-9_]{2,}\b")
    matches=[]; keys=set()
    for i,line in enumerate(txt.splitlines(),start=1):
        if rx.search(line):
            matches.append({"line":i,"text":line.strip()[:500],"evidence":evidence_record(str(t),i,line.strip()[:300],"config_env","trainer config usage")})
        for k in env.findall(line): keys.add(k)
    write_json(out/"HYBRID_TRAINER_CONFIG_USAGE.json",{"matches":matches,"env_like_keys":sorted(keys)}); return 0
if __name__=="__main__": raise SystemExit(main())
