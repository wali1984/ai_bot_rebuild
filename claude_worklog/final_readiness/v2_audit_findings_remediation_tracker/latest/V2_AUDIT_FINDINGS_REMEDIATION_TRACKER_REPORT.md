# V2 Audit Findings Remediation Tracker Packet

**Generated:** 2026-05-20 (UTC)
**GO_NO_GO:** `V2_AUDIT_FINDINGS_REMEDIATION_TRACKER_READY`
**Source audit:** [../../../../INDEPENDENT_FULL_AUDIT.md](../../../../INDEPENDENT_FULL_AUDIT.md)

This packet converts the independent audit into 8 explicit
remediation lanes with owners, status, and the next concrete
`V2_*_READY` task per lane. The tracker is the working document;
the audit is the snapshot.

## The 8 lanes

| Lane | Name | Open findings | Next task |
| --- | --- | --- | --- |
| 1 | native ingestors missing | AUD-001, AUD-007 | `V2_NATIVE_INGESTOR_BINANCE_USDM_OHLCV_READY` |
| 2 | trainer / checkpoint missing | AUD-002, AUD-004, AUD-020 | `V2_RL_TRAINER_PORT_PHASE_1_READY` |
| 3 | trader / stops / TP / hedge missing | AUD-003, AUD-005, AUD-006 | `V2_LIVE_CANARY_FIRST_REAL_ORDER_READY` (operator + Codex final approval out of scope) |
| 4 | dependency parity | AUD-014, AUD-015, AUD-016, AUD-017, AUD-018, AUD-019 | `V2_DEPENDENCY_MATRIX_AND_FREEZE_READY` (matrix BEFORE installs) |
| 5 | Telegram alerts | AUD-011 | `V2_TELEGRAM_ALERTS_NATIVE_READY` |
| 6 | watchdog / restart policy | AUD-010 | `V2_CONTROL_PLANE_WATCHDOG_AUTORESTART_READY` |
| 7 | config parity | AUD-021 | `V2_RUNTIME_CONFIG_PARITY_PHASE_1_READY` |
| 8 | DB decision | AUD-012 | `V2_PERSISTENCE_DB_DECISION_READY` (SQLite vs Postgres BEFORE migrations) |

## Status summary

| Status | Count |
| --- | --- |
| Done | 3 (AUD-008, AUD-009, AUD-013) |
| Open | 18 |
| **Total findings tracked** | **21** |

## Tracker invariants

The tracker NEVER:

- auto-installs pip packages (matrix-first per AUD-014);
- auto-enables a credentialed systemd timer;
- claims a finding closed without a `V2_*_READY` packet + Codex
  pass;
- modifies `/home/wali/Desktop/AI BOT`;
- writes legacy Redis keys;
- issues live-trading or canary approvals;
- promises a date for any Open finding.

## Operator do-NOT list (carried forward verbatim)

From the user instruction, the tracker preserves these guard
rails for all future packets:

- Do not "fix everything" before canary.
- Do not shut down legacy.
- Do not pretend V2 is migrated.
- Do not create more dashboard-only packets.
- Do not add more alternative data.
- Do not restart broad auditing.
- Do not let Claude/Codex chase package installs before the
  dependency matrix.

## What this tracker packet did NOT do

- Did NOT claim any Open finding is fixed.
- Did NOT enable any live timer/service.
- Did NOT install any pip package.
- Did NOT modify the legacy bot tree.
- Did NOT call any exchange endpoint.
- Did NOT create a Codex final live-canary pass marker.
- Did NOT flip `live_gate` or `live_symbols`.
- Did NOT create a dashboard-only packet (this is a tracker, not a
  dashboard).
- Did NOT touch alternative-data ingestors (that work is paused
  per operator instruction).

## Where the tracker lives

- Authoritative markdown:
  [claude_worklog/trackers/V2_AUDIT_FINDINGS_REMEDIATION_TRACKER.md](../../../trackers/V2_AUDIT_FINDINGS_REMEDIATION_TRACKER.md)
- Authoritative JSON:
  [claude_worklog/trackers/V2_AUDIT_FINDINGS_REMEDIATION_TRACKER.json](../../../trackers/V2_AUDIT_FINDINGS_REMEDIATION_TRACKER.json)
- Operator dashboard payload:
  [v2/frontend/public/v2_audit_findings_remediation_tracker/latest/operator_dashboard_payload.json](../../../../v2/frontend/public/v2_audit_findings_remediation_tracker/latest/operator_dashboard_payload.json)

## How future packets must use the tracker

1. Before opening a new `V2_*_READY` packet, scan the tracker for
   an existing finding ID. Reuse the ID; do not create a duplicate.
2. The packet's REPORT must cite the AUD-NNN it closes.
3. On Codex pass, append the AUD-NNN to the "Done" table in the
   tracker markdown AND update the JSON `status` to `"Done"` plus
   `closing_gate` and `completed_utc`.
4. If a packet opens a new audit finding (i.e. discovers a fresh
   gap), append it as the next AUD-NNN with status `Open`.
5. The independent audit document
   ([INDEPENDENT_FULL_AUDIT.md](../../../../INDEPENDENT_FULL_AUDIT.md))
   stays a frozen snapshot; subsequent fresh audits should be
   filed as separate dated documents and cross-linked here.
