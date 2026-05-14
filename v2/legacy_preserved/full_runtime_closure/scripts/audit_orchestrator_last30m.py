#!/usr/bin/env python3
"""
Audit Orchestrator (Last N minutes)
==================================

Produces a markdown report that summarizes:
- Orchestrator proofs from `health:events` (event=ORCHESTRATOR_PROOF)
- Published signals from `signals:trading:{primary,asjad}`
- External proposal streams (`proposals:*`)

This is a read-only audit tool.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import redis


def _now_ms() -> int:
    return int(time.time() * 1000)


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _f(x: Any, default: float = 0.0) -> float:
    try:
        if x is None:
            return float(default)
        return float(x)
    except Exception:
        return float(default)


def _to_str(x: Any) -> str:
    return str(x) if x is not None else ""


def _safe_json_loads(raw: Any) -> Optional[Dict[str, Any]]:
    try:
        if raw is None:
            return None
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8", errors="ignore")
        if not isinstance(raw, str):
            return None
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def _extract_ts_ms(payload: Dict[str, Any]) -> Optional[int]:
    # prefer explicit ms fields
    for k in ("ts_ms", "created_ts_ms"):
        v = payload.get(k)
        try:
            if v is None:
                continue
            iv = int(float(v))
            if iv > 1_000_000_000_000:  # ms epoch sanity
                return iv
        except Exception:
            continue
    # fallback to seconds timestamps
    for k in ("timestamp", "ts"):
        v = payload.get(k)
        try:
            if v is None:
                continue
            fv = float(v)
            if fv > 1_000_000_000:  # seconds epoch
                return int(fv * 1000)
        except Exception:
            continue
    return None


def _read_stream_window(
    r: redis.Redis,
    stream: str,
    cutoff_ms: int,
    *,
    max_rows: int = 5000,
    count_chunk: int = 500,
) -> List[Dict[str, Any]]:
    """
    Read entries from a stream backwards until cutoff_ms.
    We parse JSON from fields['data'] when present.
    """
    out: List[Dict[str, Any]] = []
    start_id = "+"
    remaining = max_rows
    while remaining > 0:
        rows = r.xrevrange(stream, start_id, "-", count=min(count_chunk, remaining))
        if not rows:
            break
        for sid, fields in rows:
            remaining -= 1
            # Redis returns bytes keys/values unless decode_responses=True.
            fields_norm: Dict[str, Any] = {}
            for k, v in (fields or {}).items():
                kk = k.decode("utf-8", errors="ignore") if isinstance(k, (bytes, bytearray)) else str(k)
                vv: Any = v
                if isinstance(v, (bytes, bytearray)):
                    vv = v.decode("utf-8", errors="ignore")
                fields_norm[kk] = vv

            data_raw = fields_norm.get("data")
            p = _safe_json_loads(data_raw) or {}
            # If stream does not store json, retain raw fields too
            if not p:
                p = dict(fields_norm)
            p["_stream"] = stream
            p["_stream_id"] = sid.decode() if isinstance(sid, (bytes, bytearray)) else str(sid)
            ts = _extract_ts_ms(p)
            if ts is not None and ts < cutoff_ms:
                return out
            out.append(p)
        start_id = rows[-1][0].decode() if isinstance(rows[-1][0], (bytes, bytearray)) else str(rows[-1][0])
    return out


def _md_table(rows: List[Tuple[str, str]], header: Tuple[str, str]) -> str:
    if not rows:
        return "_(none)_\n"
    out = []
    out.append(f"| {header[0]} | {header[1]} |")
    out.append("|---|---:|")
    for k, v in rows:
        out.append(f"| {k} | {v} |")
    return "\n".join(out) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=int, default=30)
    ap.add_argument("--out", type=str, required=True)
    args = ap.parse_args()

    # Redis connection: use env if set, else config.py defaults
    try:
        import config as cfg
        host = os.getenv("REDIS_HOST", getattr(cfg, "REDIS_HOST", "localhost"))
        port = int(os.getenv("REDIS_PORT", str(getattr(cfg, "REDIS_PORT", 6379))))
        db = int(os.getenv("REDIS_DB", str(getattr(cfg, "REDIS_DB", 0))))
        pwd = os.getenv("REDIS_PASSWORD", getattr(cfg, "REDIS_PASSWORD", "")) or None
    except Exception:
        host, port, db, pwd = "localhost", 6379, 0, None

    r = redis.Redis(host=host, port=port, db=db, password=pwd, decode_responses=False)

    now_ms = _now_ms()
    cutoff_ms = now_ms - int(args.minutes) * 60_000

    health = _read_stream_window(r, "health:events", cutoff_ms, max_rows=8000)
    proofs = [p for p in health if str(p.get("event") or "").upper() == "ORCHESTRATOR_PROOF"]

    signals_primary = _read_stream_window(r, "signals:trading:primary", cutoff_ms, max_rows=4000)
    signals_asjad = _read_stream_window(r, "signals:trading:asjad", cutoff_ms, max_rows=4000)

    proposals_dynamic = _read_stream_window(r, "proposals:dynamic_tp", cutoff_ms, max_rows=4000)
    proposals_stealth = _read_stream_window(r, "proposals:stealth_stops", cutoff_ms, max_rows=4000)
    proposals_trail = _read_stream_window(r, "proposals:trailing_stop", cutoff_ms, max_rows=4000)

    # Summaries
    reason_counts = Counter(str(p.get("reason") or "") for p in proofs)
    action_counts = Counter(str(p.get("winner_action") or "") for p in proofs)
    dropped = [p for p in proofs if bool(p.get("dropped"))]
    resized = [p for p in proofs if bool(p.get("resized"))]

    # Published signal action mix
    def _sig_action(x: Dict[str, Any]) -> str:
        return str(x.get("action_name") or x.get("action") or x.get("final_action") or "").upper()

    sig_actions_primary = Counter(_sig_action(x) for x in signals_primary)
    sig_actions_asjad = Counter(_sig_action(x) for x in signals_asjad)

    # Proposal action mix
    prop_actions_dynamic = Counter(str(x.get("action_name") or "").upper() for x in proposals_dynamic)
    prop_actions_stealth = Counter(str(x.get("action_name") or "").upper() for x in proposals_stealth)
    prop_actions_trail = Counter(str(x.get("action_name") or "").upper() for x in proposals_trail)

    # Feature presence checks (not just counts)
    not_triggered: List[str] = []
    def _has_action(counter: Counter, prefix: str) -> bool:
        up = prefix.upper()
        return any(k.startswith(up) for k in counter.keys())

    if len(proofs) == 0:
        not_triggered.append("No ORCHESTRATOR_PROOF events captured in window (health:events)")
    if len(proposals_dynamic) == 0:
        not_triggered.append("Dynamic TP proposals not seen (proposals:dynamic_tp)")
    if len(proposals_stealth) == 0:
        not_triggered.append("Stealth stop proposals not seen (proposals:stealth_stops) — either no triggers, or still executing locally")
    if len(proposals_trail) == 0:
        not_triggered.append("Trailing-stop proposals not seen (proposals:trailing_stop) — trailing currently implemented via stealth stops, not proposal bus")

    if "LOSS_REALIZATION_ALLOWED" not in reason_counts:
        not_triggered.append("Loss realization path not observed (reason=LOSS_REALIZATION_ALLOWED)")
    if "DROP_NO_LOSS" not in reason_counts and "DROP_NO_LOSS_UNFUNDED" not in reason_counts:
        not_triggered.append("No-loss drop path not observed for close-like actions (DROP_NO_LOSS/DROP_NO_LOSS_UNFUNDED)")
    if "SET_TAKE_PROFIT" not in sig_actions_primary and "SET_TAKE_PROFIT" not in sig_actions_asjad:
        not_triggered.append("Sidecar TP signals not observed (SET_TAKE_PROFIT)")

    # Top issues
    issue_flags: List[str] = []
    if reason_counts.get("DROP_PAIR_CAP_NO_HEADROOM", 0) > 0:
        issue_flags.append(f"DROP_PAIR_CAP_NO_HEADROOM seen {reason_counts['DROP_PAIR_CAP_NO_HEADROOM']}x (pair cap blocks still active)")
    if reason_counts.get("RESIZED_PAIR_CAP", 0) > 0:
        issue_flags.append(f"RESIZED_PAIR_CAP seen {reason_counts['RESIZED_PAIR_CAP']}x (publish-time downsize working)")

    # Compose report
    lines: List[str] = []
    lines.append("# Orchestrator Audit (Last 30 Minutes)\n")
    lines.append(f"- **Generated:** {_utc_now()}\n")
    lines.append(f"- **Window:** last {int(args.minutes)} minutes\n")
    lines.append(f"- **Redis:** {host}:{port} db={db}\n")
    lines.append("\n---\n")

    lines.append("## Orchestrator Proofs (`health:events`)\n")
    lines.append(f"- **Total proofs:** {len(proofs)}\n")
    lines.append(f"- **resized:** {len(resized)}\n")
    lines.append(f"- **dropped:** {len(dropped)}\n\n")
    lines.append("### Proof reasons (top)\n")
    lines.append(_md_table([(k or "(empty)", str(v)) for k, v in reason_counts.most_common(15)], ("reason", "count")))
    lines.append("\n### Winner actions (top)\n")
    lines.append(_md_table([(k or "(empty)", str(v)) for k, v in action_counts.most_common(15)], ("winner_action", "count")))

    lines.append("\n---\n")
    lines.append("## Published signals (`signals:trading:*`)\n")
    lines.append(f"- **primary rows:** {len(signals_primary)}\n")
    lines.append(f"- **asjad rows:** {len(signals_asjad)}\n\n")
    lines.append("### Primary action mix (top)\n")
    lines.append(_md_table([(k or "(empty)", str(v)) for k, v in sig_actions_primary.most_common(20)], ("action", "count")))
    lines.append("\n### Asjad action mix (top)\n")
    lines.append(_md_table([(k or "(empty)", str(v)) for k, v in sig_actions_asjad.most_common(20)], ("action", "count")))

    lines.append("\n---\n")
    lines.append("## External proposals (`proposals:*`)\n")
    lines.append(f"- **proposals:dynamic_tp:** {len(proposals_dynamic)}\n")
    lines.append(f"- **proposals:stealth_stops:** {len(proposals_stealth)}\n")
    lines.append(f"- **proposals:trailing_stop:** {len(proposals_trail)}\n\n")
    lines.append("### Dynamic TP proposal actions (top)\n")
    lines.append(_md_table([(k or "(empty)", str(v)) for k, v in prop_actions_dynamic.most_common(20)], ("action_name", "count")))
    lines.append("\n### Stealth stop proposal actions (top)\n")
    lines.append(_md_table([(k or "(empty)", str(v)) for k, v in prop_actions_stealth.most_common(20)], ("action_name", "count")))
    lines.append("\n### Trailing stop proposal actions (top)\n")
    lines.append(_md_table([(k or "(empty)", str(v)) for k, v in prop_actions_trail.most_common(20)], ("action_name", "count")))

    lines.append("\n---\n")
    lines.append("## Issues / flags\n")
    if not issue_flags:
        lines.append("_(none detected from proof reasons)_\n")
    else:
        for it in issue_flags:
            lines.append(f"- **{it}**\n")

    lines.append("\n---\n")
    lines.append("## Features not triggered / not observed yet\n")
    if not not_triggered:
        lines.append("_(none)_\n")
    else:
        for it in not_triggered:
            lines.append(f"- **{it}**\n")

    # Sample proofs (a few)
    lines.append("\n---\n")
    lines.append("## Sample proofs (latest 10)\n")
    for p in proofs[:10]:
        lines.append("```json\n" + json.dumps({k: p.get(k) for k in (
            "ts_ms","account_id","symbol","winner_action","winner_conf","winner_urgency","winner_profit_usd",
            "pair_margin_usd","pair_cap_usd","pair_headroom_usd","resized","dropped","reason"
        )}, indent=2, default=str) + "\n```\n")

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

