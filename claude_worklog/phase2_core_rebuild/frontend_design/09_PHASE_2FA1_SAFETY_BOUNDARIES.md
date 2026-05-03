# Phase 2F.A.1 — Safety Boundaries

## Allowed write scope

The 2F.A.1 implementer may write **only** under:

- `claude_worklog/phase2_core_rebuild/frontend_design/`.

Allowed file basenames are exactly the three outputs declared in
`08_PHASE_2FA1_DESIGN_SPEC_TASK_SPEC.md`:

- `11_DESIGN_TOKEN_SPEC.md`
- `12_ANIMATION_PRIMITIVE_SPEC.md`
- `13_2FA1_GO_NO_GO.md`

Any write outside this list, including under `v2/frontend/`, is a hard
fail. The supervisor MUST refuse to commit any diff outside the
allowed prefix.

## Forbidden mutations

- Any change under `v2/`.
- Any change under `/home/wali/Desktop/AI BOT/`.
- Any change under `legacy_reference/`.
- Any change to `.env`, `secrets/`, or any file matched by the
  configured secret-scan patterns.
- Any modification to existing supervisor task definitions for
  predecessor sub-phases (063 frontend inventory).
- Any change to `CLAUDE.md`.
- Any change to `claude_worklog/requirements_inbox/`.

## Forbidden runtime behavior

- No live trading enable. `LIVE TRADING: BLOCKED` semantics MUST
  remain unchanged.
- No Redis client construction.
- No exchange API call.
- No subprocess invocation other than `grep` / `rg`, `wc`, and
  `python -c` for JSON parsing.
- No `npm`, `npx`, `vite`, `tsc`, `playwright`, `pnpm`, `yarn`
  invocation.
- No legacy module import.
- No legacy venv use.
- No GPU code path.
- No async code authored.
- No network access.
- No `.env` read.
- No emoji in authored artifacts.

## Forbidden artifacts

- No TypeScript, TSX, CSS, JSON, or Python file authored.
- No `LIVE TRADING: ENABLED` semantics introduced anywhere.
- No animation that would obscure or remove the always-visible
  LIVE TRADING: BLOCKED banner.
- No reduced-motion override that bypasses
  `prefers-reduced-motion: reduce`.
- No production secret value referenced (manifest references by
  name only are allowed).

## Required artifacts

- `claude_worklog/phase2_core_rebuild/frontend_design/11_DESIGN_TOKEN_SPEC.md`
  ending with `PHASE2FA1_DESIGN_TOKEN_SPEC_READY`.
- `claude_worklog/phase2_core_rebuild/frontend_design/12_ANIMATION_PRIMITIVE_SPEC.md`
  ending with `PHASE2FA1_ANIMATION_PRIMITIVE_SPEC_READY`.
- `claude_worklog/phase2_core_rebuild/frontend_design/13_2FA1_GO_NO_GO.md`
  containing exactly one line: `PHASE2FA1_DESIGN_SPEC_PASSED` or
  `PHASE2FA1_DESIGN_SPEC_BLOCKED`.

## Stop conditions

The 2F.A.1 implementer halts immediately and emits
`PHASE2FA1_DESIGN_SPEC_BLOCKED` to the GO/NO-GO marker file under any
of:

- a forbidden token leak detected during self-grep;
- a write attempt outside the allowed prefix;
- a directive to mutate `v2/`;
- any directive that would require Redis, subprocess (beyond the
  allowed text-search tools), network, GPU, legacy import, deployment,
  or live behavior;
- any directive that would weaken or remove the always-visible LIVE
  TRADING: BLOCKED banner contract;
- any directive that would author TypeScript / TSX / CSS / JSON /
  Python.

## Live-trading status

LIVE TRADING: BLOCKED. No phase 2F.A.1 artifact may change this.

PHASE2FA1_DESIGN_SPEC_SAFETY_BOUNDARIES_READY
