# Visual System + Layout Report

## Theme

- **Surface palette**: warm-dark institutional (OKLCH-tuned), background `oklch(0.135 0.006 60)`, panels `oklch(0.165 0.007 60)`, lines `oklch(0.30 0.010 60)`.
- **Accents**: amber `oklch(0.82 0.165 80)` for highlights, up `oklch(0.78 0.160 150)`, down `oklch(0.70 0.205 25)`, info `oklch(0.78 0.115 230)`.
- **Type**: editorial serif (IBM Plex Serif) for display + headings; geometric sans (IBM Plex Sans) for body; mono (IBM Plex Mono) for numbers, codes, lineage IDs, Redis keys.
- **Tabular nums everywhere on metrics**: enforces column alignment in tables and tape feeds.
- **Five-second readability**: every page surfaces gate / shutdown / observation-state chips in the upper third without scroll.

## Layout primitives

- **Sticky live-block banner**: not dismissible; renders `LIVE TRADING · BLOCKED` with `live_gate=blocked_human_only` envelope.
- **Status rail** (six cells): live gate, paper runtime, legacy bridge, supervisor snapshot, public-route status, build/validation status — each cell sources from a real V2 payload.
- **Nav**: route entries gated by RBAC level (L0 user / L2 admin / L4+ reviewer / L5 operator); the admin chip surfaces warning counts derived from the operator-truth payload.
- **Section header pattern**: `§ NN / NAME` index marker + serif h2 + lead paragraph; consistent across all routes.
- **Panel bracketed**: corner-bracket highlights for high-density "current runtime snapshot" cards (lineage IDs, IDs in mono).
- **Chip taxonomy**: `solid-block`, `solid-paper`, `solid-ok`, `solid-warn`, `solid-loading` — used by status rail, lineage card, and per-panel freshness badges.

## Page layout grids

| Route | Above-the-fold | Mid section | Lower section |
|---|---|---|---|
| /market | TradingView chart + price stats | Spot/futures top-10 dashboards × 3 metrics | Funding/OI movers + liquidation tape + altdata status |
| /bot-intelligence | trainer feed + current predictions table | full-observation builder progress + per-symbol generated dim | feature missing/stale flags + checkpoint blocker + paper-fill gate reasons |
| /paper | paper positions table + held-by-gate panel | intents table + ledger summary | running PnL panel (with explicit MISSING_ENTRY_PRICE chips) |
| /risk | live blocker matrix + risk gate status | strict paper-fill gate panel + liquidation WSS health | old-Redis / exchange-mutation status panel (all zero) |
| /automation | war-room cycle timeline + governor status | legacy log observer + comparator panels | Codex review queue table |

## Per-panel anatomy

```
┌────────────────────────────────────────────────────────────┐
│ §HEADER  Title                          [freshness chip]   │
│  source = redis:key or file path                           │
│                                                            │
│  [tabular content / chart / matrix / list]                 │
│                                                            │
│  Missing? → render MISSING/STALE chip with explicit source │
│  Never fabricate a number.                                 │
└────────────────────────────────────────────────────────────┘
```

## Mobile responsiveness

- Status rail collapses to 2-col at <1100px, single column at <720px.
- Tables expose horizontal scroll inside their container.
- Panel grids re-stack from 3-col → 2-col → 1-col.
- All buttons keep ≥44px tap height.
- Live-block banner is sticky at all viewport sizes and remains non-dismissible.

## Accessibility

- Contrast: WCAG AA on body text, AAA on lineage/audit hashes.
- Every chip pair (UP/DOWN, MATCHED/UNMATCHED) carries a glyph in addition to color so red-green color blindness does not collapse meaning.
- All interactive controls have visible focus rings.

## Real-payload binding

Each panel reads only from one of:

- A V2 Redis key (`v2:*` namespace; never legacy)
- A V2 worklog status JSON
- A V2 public mirror JSON

When a payload is absent or stale, the panel renders an explicit
MISSING / STALE / FORBIDDEN chip with the source string from the
payload (e.g. `KEY_MISSING_NO_NETWORK`, `API_FORBIDDEN_403`,
`MISSING_ENTRY_PRICE`). The reader function NEVER silently zero-fills.
