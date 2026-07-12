"""WI-5: alt-data freshness + consumption diagnostic (READ-ONLY, no build).

The DL-crypto review says external data (sentiment/on-chain) improves models, but
only if it is actually present + fresh at decision time. This reports, over recent
trusted decision rows, the per-feature missing / stale / zero rate using the exact
decision-time lineage the trainer sees (FeatureTensorRecord.missing_mask /
stale_mask / source_availability). It flags external alt-data features that are
chronically dead (missing/stale/zero), so a freshness fix can be targeted -- it
never adds a provider and changes no decision (guardrail: WI-5 is diagnostic only).
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from typing import Any, Sequence

# External alt-data providers named in the review (sentiment/on-chain/social).
EXTERNAL_ALTDATA_PREFIXES = (
    "nansen", "lunarcrush", "santiment", "moralis", "whale", "coingecko",
    "aicoin", "fear_greed", "social", "sentiment", "onchain", "on_chain",
    "galaxy", "altrank", "tweet", "reddit", "coinglass",
)
# Derivatives microstructure (our own venue data, reported separately).
DERIVATIVES_PREFIXES = ("funding", "open_interest", "oi_", "liquidation")
# Providers intentionally DISABLED (free tier / no valid subscription -> never
# poll data). Their features are legitimately absent, NOT a freshness bug: they
# are reported as "disabled" so they don't inflate the fixable "dead" count.
# Operator-configurable via V2_ALTDATA_DISABLED_PROVIDERS (comma-separated).
_DEFAULT_DISABLED = "nansen,lunarcrush,aicoin,coingecko"
DISABLED_PROVIDER_PREFIXES = tuple(
    p.strip().lower()
    for p in (os.getenv("V2_ALTDATA_DISABLED_PROVIDERS", _DEFAULT_DISABLED) or _DEFAULT_DISABLED).split(",")
    if p.strip()
)


def _is_disabled(name: str) -> bool:
    low = name.lower()
    return any(k in low for k in DISABLED_PROVIDER_PREFIXES)


def _category(name: str) -> str:
    low = name.lower()
    if any(k in low for k in EXTERNAL_ALTDATA_PREFIXES):
        # Split intentionally-off (free tier) from fixable external alt-data.
        return "disabled_altdata" if _is_disabled(name) else "external_altdata"
    if any(low.startswith(k) or k in low for k in DERIVATIVES_PREFIXES):
        return "derivatives_microstructure"
    return "core"


def analyze_freshness(examples: Sequence[Any]) -> dict[str, Any]:
    if not examples:
        return {"error": "no examples", "rows": 0}
    names = list(examples[0].tensor.feature_names)
    n = len(names)
    rows = 0
    miss = [0] * n
    stale = [0] * n
    zero = [0] * n
    src_unavail = [0] * n
    for ex in examples:
        t = ex.tensor
        vals = list(t.values)
        mm = list(t.missing_mask)
        sm = list(t.stale_mask)
        sa = list(t.source_availability)
        if len(vals) != n:
            continue
        rows += 1
        for i in range(n):
            if i < len(mm) and mm[i]:
                miss[i] += 1
            if i < len(sm) and sm[i]:
                stale[i] += 1
            if i < len(vals) and vals[i] == 0:
                zero[i] += 1
            if i < len(sa) and not sa[i]:
                src_unavail[i] += 1
    rows = max(1, rows)

    per_feature = []
    for i, name in enumerate(names):
        per_feature.append({
            "feature": name,
            "category": _category(name),
            "missing_rate": round(miss[i] / rows, 4),
            "stale_rate": round(stale[i] / rows, 4),
            "zero_rate": round(zero[i] / rows, 4),
            "source_unavailable_rate": round(src_unavail[i] / rows, 4),
            "present_and_fresh_rate": round(1.0 - max(miss[i], stale[i]) / rows, 4),
        })

    def _cat_summary(cat: str) -> dict[str, Any]:
        feats = [f for f in per_feature if f["category"] == cat]
        if not feats:
            return {"feature_count": 0}
        # A feature is "dead" if it is missing/stale most of the time.
        dead = [f for f in feats if f["present_and_fresh_rate"] < 0.10]
        weak = [f for f in feats if 0.10 <= f["present_and_fresh_rate"] < 0.50]
        healthy = [f for f in feats if f["present_and_fresh_rate"] >= 0.50]
        return {
            "feature_count": len(feats),
            "dead_count": len(dead),
            "weak_count": len(weak),
            "healthy_count": len(healthy),
            "mean_present_and_fresh_rate": round(sum(f["present_and_fresh_rate"] for f in feats) / len(feats), 4),
            "dead_features": sorted(f["feature"] for f in dead)[:40],
            "weak_features": sorted(f["feature"] for f in weak)[:40],
        }

    return {
        "schema_version": "trainer_altdata_freshness_diagnostic_v1",
        "generated_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "rows_analyzed": rows,
        "feature_count": n,
        "disabled_providers": list(DISABLED_PROVIDER_PREFIXES),
        "summary_by_category": {
            "external_altdata": _cat_summary("external_altdata"),
            "disabled_altdata": _cat_summary("disabled_altdata"),
            "derivatives_microstructure": _cat_summary("derivatives_microstructure"),
            "core": _cat_summary("core"),
        },
        "worst_external_altdata": sorted(
            (f for f in per_feature if f["category"] == "external_altdata"),
            key=lambda f: f["present_and_fresh_rate"],
        )[:25],
        "read_only": True,
        "changes_no_decision": True,
        "live_gate": "blocked_human_only",
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--symbols", default=None,
                   help="comma-separated symbols; default = dynamic universe resolver (adaptive)")
    p.add_argument("--smoke-test", action="store_true",
                   help="use the BTC/ETH/SOL smoke-test set (test only)")
    p.add_argument("--timeframes", default="1m,5m,15m,1h")
    p.add_argument("--limit", type=int, default=8000)
    p.add_argument("--cache-path", default="claude_worklog/trainer_atlas/altdata_freshness_cache.pkl")
    p.add_argument("--output", default="claude_worklog/trainer_atlas/altdata_freshness_report.json")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    from pathlib import Path  # noqa: PLC0415

    from v2.backend.app.cli.v2_trainer_offline_batch_train import load_or_build_examples  # noqa: PLC0415
    from v2.backend.app.services.v2_symbol_runtime_universe import resolve_symbols  # noqa: PLC0415

    args = parse_args(argv)
    examples, _ = load_or_build_examples(
        symbols=resolve_symbols(explicit=args.symbols, smoke_test=args.smoke_test),
        timeframes=[t.strip().lower() for t in args.timeframes.split(",") if t.strip()],
        limit=args.limit,
        cache_path=args.cache_path,
        rebuild_cache=False,
    )
    report = analyze_freshness(examples)
    text = json.dumps(report, indent=2, default=str)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(text)
    ext = report.get("summary_by_category", {}).get("external_altdata", {})
    print(text[:2000])
    print(
        "ALTDATA_FRESHNESS:",
        f"rows={report.get('rows_analyzed')}",
        f"external: healthy={ext.get('healthy_count')} weak={ext.get('weak_count')} dead={ext.get('dead_count')}",
        f"mean_fresh={ext.get('mean_present_and_fresh_rate')}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
