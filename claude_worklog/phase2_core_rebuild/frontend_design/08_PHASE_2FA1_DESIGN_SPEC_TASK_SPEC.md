# Phase 2F.A.1 — Design-Token + Animation-Primitive Spec Task Spec

This is the authoring spec for the local-Claude documentation task that
will produce the design-token specification and the animation-primitive
specification for `v2/frontend/`. Phase 2F.A.1 is documentation only.
The implementer must NOT modify any file under `v2/frontend/`.

The design-token spec and animation-primitive spec authored in 2F.A.1
become the authoritative inputs to 2F.B.0 (design-token module
implementation) and 2F.B.1 (animation-primitive component
implementation). 2F.A.1 itself does not write any TypeScript.

## Predecessor gates

- REQ_0008 in requirements inbox.
- `claude_worklog/phase2_core_rebuild/frontend_design/00_SCOPE.md` ends
  with `PHASE2F_FRONTEND_DESIGN_SCOPE_READY`.
- `claude_worklog/phase2_core_rebuild/frontend_design/01_PHASE_BREAKDOWN.md`
  ends with `PHASE2F_FRONTEND_DESIGN_PHASE_BREAKDOWN_READY`.
- `claude_worklog/phase2_core_rebuild/frontend_design/07_FRONTEND_INVENTORY_GO_NO_GO.md`
  reads `PHASE2FA0_FRONTEND_INVENTORY_PASSED` (the 2F.A.0 sub-phase
  Codex pass; 2F.A.1 does not start until the inventory is locked in).
- `claude_worklog/phase2_core_rebuild/frontend_design/09_PHASE_2FA1_SAFETY_BOUNDARIES.md`
  ends with `PHASE2FA1_DESIGN_SPEC_SAFETY_BOUNDARIES_READY`.
- `claude_worklog/phase2_core_rebuild/frontend_design/10_PHASE_2FA1_GO_NO_GO_REQUEST.md`
  ends with `PHASE2FA1_GO_NO_GO_REQUEST_RECORDED`.

## Inputs the implementer must read

- `claude_worklog/requirements_inbox/REQ_0008_ENTERPRISE_WEBSITE_DESIGN_ANIMATION_SYSTEM.md`
- `claude_worklog/phase2_core_rebuild/frontend_design/00_SCOPE.md`
- `claude_worklog/phase2_core_rebuild/frontend_design/01_PHASE_BREAKDOWN.md`
- `claude_worklog/phase2_core_rebuild/frontend_design/03_PHASE_2FA0_SAFETY_BOUNDARIES.md`
- `claude_worklog/phase2_core_rebuild/frontend_design/05_FRONTEND_INVENTORY_REPORT.md`
- `claude_worklog/phase2_core_rebuild/frontend_design/06_FRONTEND_INVENTORY_GAP_MATRIX.md`
- `claude_worklog/phase2_core_rebuild/frontend_design/09_PHASE_2FA1_SAFETY_BOUNDARIES.md`
- `claude_worklog/phase2_core_rebuild/frontend_design/10_PHASE_2FA1_GO_NO_GO_REQUEST.md`
- `CLAUDE.md` (sections "Required V2 GUI Pages", "Monitor Center
  Requirements", "Signal Explainability Rule", "Mobile/iPhone Future
  Rule", "Admin Control Rule").
- `v2/frontend/src/styles.css` (read-only — to understand any
  baseline color or spacing variables that already exist).
- The page-level entry points referenced as P0 gaps in
  `06_FRONTEND_INVENTORY_GAP_MATRIX.md` (read-only).

## Outputs the implementer must author (exact set, no extras)

1. `claude_worklog/phase2_core_rebuild/frontend_design/11_DESIGN_TOKEN_SPEC.md`
2. `claude_worklog/phase2_core_rebuild/frontend_design/12_ANIMATION_PRIMITIVE_SPEC.md`
3. `claude_worklog/phase2_core_rebuild/frontend_design/13_2FA1_GO_NO_GO.md`

The implementer authors these via the `Write` tool or
`BEGIN_FILE` / `END_FILE` Markdown blocks. The implementer MUST NOT
author any TypeScript, TSX, CSS, JSON, or Python file under `v2/`.

## 11_DESIGN_TOKEN_SPEC.md required structure

1. Heading "Phase 2F.A.1 — Design Token Spec".
2. Section "Token kinds" — enumerate the kinds of tokens the spec
   covers: color, typography, spacing, radius, shadow, motion-duration,
   motion-easing, z-index, breakpoint, opacity. Each kind must be
   defined exactly once.
3. Section "Color tokens" — table with columns:
   - token name (snake-case, scoped by surface, e.g.
     `color_surface_primary_default`),
   - hex value (dark mode default),
   - hex value (light mode — explicitly note that V2 ships dark-mode
     first; light-mode is a fallback),
   - WCAG contrast ratio against the canonical text color in the same
     row (computed analytically, not stubbed),
   - usage description (one line).
   Required minimum: surface (primary, secondary, raised), text
   (primary, secondary, muted, inverse), accent (primary, danger,
   warning, success), border (default, focus), live-blocked banner
   foreground/background.
4. Section "Typography tokens" — table with columns: token name,
   font-family stack, font-size (`rem`), line-height, font-weight,
   letter-spacing, usage description. Required minimum: display,
   headline, title, body, caption, mono.
5. Section "Spacing tokens" — table with columns: token name (e.g.
   `space_4`), value in `rem`, value in `px` for documentation, usage
   description. Required minimum: `space_0` through `space_8` on a
   4 px geometric scale.
6. Section "Radius tokens" — table: token name, value in `rem`, usage
   description. Required minimum: `radius_sm`, `radius_md`,
   `radius_lg`, `radius_pill`, `radius_circle`.
7. Section "Shadow tokens" — table: token name, CSS shadow value,
   usage. Dark-mode-friendly only; no white-veil shadows. Required
   minimum: `shadow_sm`, `shadow_md`, `shadow_lg`, `shadow_focus_ring`.
8. Section "Motion-duration tokens" — table: token name, value in ms,
   usage. Required minimum: `motion_instant` (≤ 80 ms),
   `motion_fast` (160 ms), `motion_default` (240 ms),
   `motion_slow` (400 ms).
9. Section "Motion-easing tokens" — table: token name, cubic-bezier
   value, usage. Required minimum: `easing_standard`,
   `easing_emphasized`, `easing_decel`, `easing_accel`.
10. Section "z-index tokens" — table: token name, integer, usage.
    Required minimum: `z_base`, `z_sticky`, `z_dropdown`,
    `z_overlay`, `z_modal`, `z_toast`, `z_safety_banner` (always on
    top).
11. Section "Breakpoint tokens" — table: token name, min-width in
    `px`, usage. Required minimum: `bp_xs` (<= 360 px iPhone SE),
    `bp_sm`, `bp_md`, `bp_lg`, `bp_xl`.
12. Section "Opacity tokens" — table: token name, decimal value
    (0–1), usage. Required minimum: `opacity_disabled`,
    `opacity_muted`, `opacity_overlay_dim`.
13. Section "Token surface contract" — exact module path the 2F.B.0
    implementer will produce
    (`v2/frontend/src/design/tokens/`), the exact filename per kind
    (e.g. `color.ts`, `typography.ts`), the exported object shape
    (TypeScript interface signature, no implementation), and the
    rule "every token name in this spec maps to exactly one exported
    constant; the type signature is `Readonly<Record<string,
    string|number>>` per kind".
14. Section "Safety chrome contract" — explicit color/typography
    coverage for the always-visible LIVE TRADING: BLOCKED banner
    (foreground, background, border, font-weight, font-size in `rem`,
    minimum touch-target height in `rem` for mobile, contrast ratio
    `>= 7:1`).
15. Final marker line: `PHASE2FA1_DESIGN_TOKEN_SPEC_READY` or
    `PHASE2FA1_DESIGN_SPEC_BLOCKED`.

## 12_ANIMATION_PRIMITIVE_SPEC.md required structure

1. Heading "Phase 2F.A.1 — Animation Primitive Spec".
2. Section "Primitive kinds" — enumerate the seven primitives required
   by REQ_0008 "Animation requirements": `PageTransition`,
   `StatusPulseIndicator`, `DataFlowGraphAnimation`,
   `RiskGateBlockAnimation`, `StreamingActivityTimeline`,
   `SymbolHeatmapFocusState`, `MobileSlidePanel`. Each primitive must
   be defined exactly once.
3. Section "Per-primitive contract" — for each primitive, capture:
   - intent (one short sentence);
   - props surface (TypeScript interface signature, no implementation;
     props use design-token names from `11_DESIGN_TOKEN_SPEC.md` —
     no inline hex / px values);
   - reduced-motion behavior (must respect
     `prefers-reduced-motion: reduce` and degrade to a non-animated
     visual that still communicates the state);
   - mobile-portrait behavior (slide panels must default to right-edge
     90% width on `bp_xs`);
   - safety-banner override behavior (no primitive may obscure the
     LIVE TRADING: BLOCKED banner; banner is on `z_safety_banner`,
     primitives use `z_overlay` or below);
   - accessibility contract (focus trap rules for modal-like
     primitives, ARIA roles, focus-visible outline tokens).
4. Section "Implementation surface" — exact module path the 2F.B.1
   implementer will produce (`v2/frontend/src/components/motion/`),
   one file per primitive named after the primitive in PascalCase
   (e.g. `PageTransition.tsx`), and a colocated test file under
   `v2/frontend/tests/unit/motion/<Primitive>.test.tsx`.
5. Section "Animation budget" — total animated DOM nodes per page
   ≤ 30, total simultaneous transitions per page ≤ 8, each transition
   bounded by a duration token (no unbounded `animation-iteration-count:
   infinite` outside of `StatusPulseIndicator`, which is bounded by
   contrast and frequency rules).
6. Section "Forbidden behaviors" — restate forbidden tokens from
   `09_PHASE_2FA1_SAFETY_BOUNDARIES.md`: no Redis client, no
   subprocess, no network call, no legacy import, no live trading
   enable, no exchange API call.
7. Section "Mobile-iPhone PWA notes" — primitives must remain usable
   on iPhone SE (320 px) without horizontal scroll; tap targets meet
   the 44 × 44 px Apple HIG minimum which equals `2.75rem` at the
   default `1rem = 16px`.
8. Final marker line: `PHASE2FA1_ANIMATION_PRIMITIVE_SPEC_READY` or
   `PHASE2FA1_DESIGN_SPEC_BLOCKED`.

## 13_2FA1_GO_NO_GO.md required structure

Exactly one line: `PHASE2FA1_DESIGN_SPEC_PASSED` or
`PHASE2FA1_DESIGN_SPEC_BLOCKED`. No other content. PASSED requires:

- both `11_DESIGN_TOKEN_SPEC.md` and `12_ANIMATION_PRIMITIVE_SPEC.md`
  end with their READY markers;
- the forbidden-token grep at task time records zero hits across both
  authored spec files for: `redis`, `aioredis`, `subprocess`,
  `os.system`, `legacy_reference`, `/home/wali/Desktop/AI BOT`,
  `BINANCE_API_KEY`, `BINANCE_API_SECRET`,
  `live_trading_enabled = true`;
- no write occurred outside
  `claude_worklog/phase2_core_rebuild/frontend_design/`;
- the safety-chrome and reduced-motion sections are present.

## Hard exclusions for Phase 2F.A.1

- No write under `v2/frontend/` (or any `v2/` subtree).
- No write outside `claude_worklog/phase2_core_rebuild/frontend_design/`.
- No `npm install`, `npm run`, `npx`, `vite`, `tsc`, `playwright`,
  `pnpm`, `yarn` invocation.
- No subprocess other than `grep` / `rg`, `wc`, `python -c` for JSON
  parsing.
- No Redis client construction in any artifact.
- No exchange API call mentioned as live in any artifact.
- No legacy module import.
- No legacy file read (under `/home/wali/Desktop/AI BOT/`).
- No production secret read.
- No `.env` read.
- No deployment script invocation.
- No emoji in authored artifacts (the project policy).

## Stop conditions

The implementer halts and emits `PHASE2FA1_DESIGN_SPEC_BLOCKED` to
the GO_NO_GO marker file under any of:

- a forbidden token leak detected during the self-grep;
- a write attempt outside the allowed prefix;
- a request to mutate `v2/frontend/`;
- any directive that would require Redis, subprocess, network, GPU,
  legacy import, deployment, or live behavior;
- any directive that would weaken or remove the always-visible LIVE
  TRADING: BLOCKED banner contract.

PHASE2FA1_DESIGN_SPEC_TASK_SPEC_READY
