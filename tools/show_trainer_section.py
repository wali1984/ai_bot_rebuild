#!/usr/bin/env python3
from __future__ import annotations
import argparse
from pathlib import Path
from common_audit import resolve_path, read_text_safely, sha256_text, ensure_allowed_file, redact_text

def main()->int:
    ap=argparse.ArgumentParser(); ap.add_argument("--trainer-file",required=True); ap.add_argument("--start",type=int,required=True); ap.add_argument("--end",type=int,required=True); args=ap.parse_args()
    t=resolve_path(args.trainer_file,Path.cwd()); ensure_allowed_file(t,resolve_path("./legacy_reference",Path.cwd()))
    txt=read_text_safely(t,max_bytes=200_000_000).splitlines(); s=max(1,args.start); e=min(args.end,len(txt)); seg=txt[s-1:e]
    print(f"trainer_file: {t}"); print(f"range: {s}-{e}"); print(f"range_sha256: {sha256_text(chr(10).join(seg))}"); print("verification: deterministic read-only")
    for i,l in enumerate(seg,start=s): print(f"{i:>8}: {redact_text(l) or ''}")
    return 0
if __name__=="__main__": raise SystemExit(main())
