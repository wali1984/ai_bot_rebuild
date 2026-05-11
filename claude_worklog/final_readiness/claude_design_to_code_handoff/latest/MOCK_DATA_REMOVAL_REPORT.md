# MOCK_DATA_REMOVAL_REPORT.md

## Claim

No design mock data ships in V2 as a result of this handoff.

## What the design shipped as mock

The Claude Design handoff includes `data.jsx` — 171 lines of fabricated illustrative numbers used by every page in the prototype. Examples:

- `NAV[i].count` — fake sidebar counts (`signals: 47`, `positions: 6`, `script-registry: 11`).
- `SUBSYSTEMS[i]` — fabricated rows with `loss 0.0382`, `step 184,201`, `queue 0`, `keys 12,481`, `lag 0ms`.
- `RISK_RULES[i]` — fabricated rule reasons like "dedup window 24h".
- `SIGNALS[i]` — fabricated rows with `model: "hybrid-v4.2-ckpt0291"`, `conf: 0.812`, `pnl: "+0.34%"`.
- `POSITIONS[i]` — fabricated entries / marks / unrealized PnL.
- The `BlockedStrip` strings inside `app.jsx` (e.g. `"policy rev 18"`, `"9 / 14 live-readiness items pending"`, the fabricated audit-chain link count, `"redis ns · aibotv2:*"`, `"paper mode · replay adapter v2"`).
- `TopBar` `Telemetry` numbers (e.g. `latency 0.42ms`).

`README.md` is explicit: "Never let `data.jsx` mock metrics appear as live runtime truth." `CLAUDE_CODE_PROMPT.md` PART C classifies every such constant as `DESIGN_MOCK_DATA_TO_REMOVE`, which "cannot ship as real."

## What V2 ships

Search across `v2/frontend/src/` for any of the design's mock identifiers returns 0 hits:

- `data\.jsx` — 0
- `TweaksPanel` — 0
- `useTweaks` — 0
- `BlockedStrip` — 0
- design's fabricated `audit-chain` link-count string — 0
- design's fabricated model checkpoint id (`hybrid-v4.2-ckpt0291`) — 0
- design's `aibotv2:metrics` namespace path — 0

V2's live-blocked banner derives only from `GET /api/v1/risk/live-readiness`, never from any string from `app.jsx`. The 33 references to live-blocked state in `v2/frontend/src/` are banner wiring plus tests verifying the banner cannot be dismissed.

## Existing V2 fixtures

V2 ships preserved proof artifacts under `v2/frontend/public/<feature>/latest/*.json` (~34 feature directories). These are `V2_PROOF_ARTIFACT` payloads — preserved runtime/proof captures from legitimate non-live runs, not fabricated illustrations. They are labelled by the `FreshnessBadge` (`mode: 'STATIC_PROOF_FIXTURE'` / `'CONTINUOUS_NON_LIVE'` / `'EVIDENCE_GAP'` / etc.) so the operator can always tell what kind of source is backing a panel.

## Changes to V2 in this pass

None required — V2 had no design mock leaks before this pass, and none were introduced. No constant, no string literal, and no JSX import was lifted from `data.jsx` or `app.jsx`.

## Reverification

To re-verify on a fresh checkout:

```bash
cd v2/frontend
grep -rnE 'data\.jsx|TweaksPanel|useTweaks|BlockedStrip|hybrid-v4.2-ckpt0291|aibotv2:metrics' src/ | wc -l   # expect 0
grep -rn  'cockpit-evidence-gap' src/ | wc -l                                                                # expect > 0
grep -rn  'live-block-banner' src/ | wc -l                                                                   # expect > 0
```
