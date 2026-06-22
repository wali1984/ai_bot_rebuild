# Recurring Monitor — audit_stealth_profit_profit_taking

## Scope
- Non-live recurring monitor execution under always-on Claude/Codex runtime.
- Working directory: `/home/wali/Desktop/AI BOT REBUILD` only.
- Legacy processes / logs / Redis treated as read-only reference; no mutation attempted.
- No exchange order, leverage, margin, or live-trading state changes performed.

## Non-Live Guardrails (Reaffirmed)
- LIVE TRADING: BLOCKED (default per CLAUDE.md).
- No writes to legacy Redis keys, legacy bot, trainer venv, or `.env` / secrets.
- No process restarts of live trader / live trainer.
- All artifacts emitted under `./claude_worklog/**` per write-boundary policy.

## Monitor Subject
`audit_stealth_profit_profit_taking` — audits the legacy stealth profit-taking
behavior (silent / hidden TP rungs that close fractions of a position without
publishing user-visible TP orders) to detect drift, missed exits, or
unaccounted profit being left on the table.

## Read-Only Evidence Pass
- Source corpus: `./legacy_reference/**` (read-only) — stealth TP / profit-taking
  paths are the canonical evidence target. No file mutated.
- Runtime corpus: legacy Redis / logs treated as observational only; no
  subscribe-and-ack, no key writes, no admin commands issued.
- Evidence destination (writable per policy):
  `./claude_worklog/final_readiness/always_on_claude_codex_runtime/recurring/audit_stealth_profit_profit_taking/`.

## Health Findings
- Monitor harness invocation: OK (non-live, read-only).
- Write boundary compliance: OK (output confined to allowed `claude_worklog/**`).
- Legacy mutation attempts: NONE.
- Live-trading toggle interactions: NONE.
- Evidence integrity: this report is a navigation aid; any final stealth-TP
  finding must still be backed by raw source line ranges, raw Redis events, or
  raw log lines per CLAUDE.md Evidence Integrity Rule.

## Status
- Recurring monitor `audit_stealth_profit_profit_taking`: READY (non-live).
- No blockers detected for this recurring tick.
- No remediation required this cycle.

## Remediation Recommendation (Conditional)
If a future tick of this monitor flags a stealth profit-taking discrepancy
(e.g., partial close executed without corresponding ledger / Redis evidence),
the required remediation path is:
1. Capture raw evidence pointer (file:line, Redis key, log line, DB row).
2. File an `unsafe_unknown` entry blocking V2 progress until resolved.
3. Route a Codex adversarial review against the stealth-TP code path.
4. Keep LIVE TRADING: BLOCKED until reconciled.
No remediation ticket is opened this cycle because no blocker was observed.

## Next Tick
Re-run on the always-on recurring schedule; continue read-only legacy posture.
