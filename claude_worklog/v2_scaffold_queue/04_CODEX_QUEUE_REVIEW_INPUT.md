# 04 — Codex Queue Review Input

This file is the slicer-input bundle for the Codex queue review. It is
consumed in two passes:

1. The Codex slicer reads `BEGIN_CODEX_BLOCK <id>` … `END_CODEX_BLOCK <id>`
   markers and yields one block per id.
2. Each block is reviewed independently by Codex; findings land in
   `06_CODEX_QUEUE_REVIEW.md` (current cycle) or
   `06_CODEX_QUEUE_REVIEW_RERUN.md` (next cycle).

## Canonical Codex GO/NO-GO marker pair (B8 closure)

The supervisor reads `06_CODEX_QUEUE_GO_NO_GO.md` and refuses to flip
any 015X task to `approved` until the file equals
`V2_SCAFFOLD_QUEUE_CODEX_REVIEW_PASS`. The only legal markers are:

- `V2_SCAFFOLD_QUEUE_CODEX_REVIEW_PASS`
- `V2_SCAFFOLD_QUEUE_CODEX_REVIEW_BLOCKED`

This pair is normative for both this review-input file and the Codex
output contract. No other marker tokens are accepted by the supervisor.

## B8 marker normalization (slicer markers)

Earlier revisions of this file used a mix of `===CODEX_BLOCK===`,
`<<<codex>>>`, and bare `---` separators. The Codex slicer rejected those
mixed markers. From this revision on, the only legal block markers are:

- `BEGIN_CODEX_BLOCK <id>` (exactly one space, lowercase id)
- `END_CODEX_BLOCK <id>` (matching id)

No other separators are permitted between blocks. Whitespace lines are
allowed; non-whitespace text outside markers MUST be parsed by the
slicer as out-of-band metadata only.

Verification:

```
grep -nE "^(BEGIN|END)_CODEX_BLOCK " claude_worklog/v2_scaffold_queue/04_CODEX_QUEUE_REVIEW_INPUT.md
grep -n "V2_SCAFFOLD_QUEUE_CODEX_REVIEW_PASS" claude_worklog/v2_scaffold_queue/04_CODEX_QUEUE_REVIEW_INPUT.md
```

The first grep MUST yield matched begin/end pairs only; any orphan marker
is a slicer-blocking defect. The second grep MUST yield at least one hit
(this section).

## Block index (this cycle)

| id | Subject | Source pointer |
| --- | --- | --- |
| 015a | V2 foundation scaffold task JSON + audit_evidence | `tasks/015a.json` |
| 015b | V2 control-plane API scaffold task JSON | `tasks/015b.json` |
| 015c | V2 audit ledger scaffold task JSON | `tasks/015c.json` |
| 015d | V2 risk gateway scaffold task JSON | `tasks/015d.json` |
| 015e | V2 monitor center scaffold task JSON | `tasks/015e.json` |
| 015f | V2 GUI shell scaffold task JSON | `tasks/015f.json` |
| dag | DAG correctness | `02_TASK_DEPENDENCY_GRAPH.md` |
| waves | Wave sequencing | `01_IMPLEMENTATION_WAVES.md` |
| guardrails | Canonical schemas | `03_SCAFFOLD_BUILD_GUARDRAILS.md` |

## Blocks

BEGIN_CODEX_BLOCK 015a
Review subject: `claude_worklog/v2_scaffold_queue/tasks/015a.json`.
Verify: status == "blocked_approval"; gate_evidence_ref length == 8;
audit_evidence schema matches `03_SCAFFOLD_BUILD_GUARDRAILS.md`;
observability.summary_json_required == true.
END_CODEX_BLOCK 015a

BEGIN_CODEX_BLOCK 015b
Review subject: `claude_worklog/v2_scaffold_queue/tasks/015b.json`.
Same checks as 015a; additionally verify depends_on includes "015a".
END_CODEX_BLOCK 015b

BEGIN_CODEX_BLOCK 015c
Review subject: `claude_worklog/v2_scaffold_queue/tasks/015c.json`.
Same checks as 015a; additionally verify depends_on includes "015a"
and the task names the audit-ledger contract pointer
`../v2_architecture/13_AUDIT_LEDGER_AND_AI_CHANGE_GOVERNANCE.md`.
END_CODEX_BLOCK 015c

BEGIN_CODEX_BLOCK 015d
Review subject: `claude_worklog/v2_scaffold_queue/tasks/015d.json`.
Same checks as 015a; additionally verify depends_on supersets
{"015a","015b","015c"} (B4 sequencing).
END_CODEX_BLOCK 015d

BEGIN_CODEX_BLOCK 015e
Review subject: `claude_worklog/v2_scaffold_queue/tasks/015e.json`.
Same checks as 015a; verify depends_on supersets
{"015a","015b","015c","015d"}.
END_CODEX_BLOCK 015e

BEGIN_CODEX_BLOCK 015f
Review subject: `claude_worklog/v2_scaffold_queue/tasks/015f.json`.
Same checks as 015a; verify depends_on supersets
{"015a","015b","015c","015d"}.
END_CODEX_BLOCK 015f

BEGIN_CODEX_BLOCK dag
Review subject: `02_TASK_DEPENDENCY_GRAPH.md`. Verify acyclicity, node
set == {015a..015f}, edges include 015c -> 015d (B4), and the mermaid
block matches the text DAG block.
END_CODEX_BLOCK dag

BEGIN_CODEX_BLOCK waves
Review subject: `01_IMPLEMENTATION_WAVES.md`. Verify W1..W4 exist; 015a
in W1; 015b and 015c in W2; 015d in W3; 015e and 015f in W4; W3
forbidden_until cites 015c audit-ledger green (B4).
END_CODEX_BLOCK waves

BEGIN_CODEX_BLOCK guardrails
Review subject: `03_SCAFFOLD_BUILD_GUARDRAILS.md`. Verify the canonical
schemas for `gate_evidence_ref` (length floor 8, ordered slots) and
`audit_evidence` (required fields, confidence enum) are present.
END_CODEX_BLOCK guardrails
