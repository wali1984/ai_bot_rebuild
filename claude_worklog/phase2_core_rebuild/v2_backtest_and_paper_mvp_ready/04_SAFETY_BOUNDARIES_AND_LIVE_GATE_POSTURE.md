# Safety Boundaries and Live-Gate Posture at V2_BACKTEST_AND_PAPER_MVP_READY

The `V2_BACKTEST_AND_PAPER_MVP_READY` marker is a non-live consolidation gate. This file restates the hard safety boundaries that apply at, and after, this gate.

## Hard forbidden actions (apply throughout)

The following actions are forbidden at this consolidation, throughout the post-consolidation evidence-collection lanes, and until explicit human approval at the separate live-readiness gate:

- Modify any file under `/home/wali/Desktop/AI BOT`.
- Write, delete, or mutate any Redis key. Read-only Redis metadata only.
- Restart any live service (live trader, live trainer, live orchestrator, live ingestors, Redis, VPN).
- Place or cancel any exchange order.
- Change leverage. Change margin mode.
- Enable live trading. Add or activate live API keys.
- Deploy. Run any production migration.
- Expose or commit secrets. Send secret values to Claude / Codex / Ollama.
- Approve the live gate. Final live trading approval is human-only and is not requested by this consolidation.
- Perform any L4 / L5 action without explicit human approval.

## Live-gate posture

`LIVE TRADING: BLOCKED` per CLAUDE.md "Default status".

The `V2_BACKTEST_AND_PAPER_MVP_READY` marker:

- Does NOT enable live trading.
- Does NOT add or activate live API keys.
- Does NOT increase leverage. Does NOT enable CROSS margin.
- Does NOT increase max position size. Does NOT increase daily loss limit.
- Does NOT disable the kill switch. Does NOT disable the mandatory stop.
- Does NOT enable hedge / DCA. Does NOT enable `ADJUST_LEVERAGE`.
- Does NOT switch paper to live.

Per REQ_0020 § "Hard live gate": no component may enable live trading, place / cancel orders, change leverage / margin, write / delete Redis live keys, restart live services, mutate `/home/wali/Desktop/AI BOT`, or deploy production changes. The consolidation marker enforces these constraints by definition; the typed surfaces it certifies are non-live by construction (no execution-side surface, no Redis adapter, no exchange adapter, no FastAPI surface, no scheduler, no background loop).

## Relation to FINAL_NON_LIVE_REBUILD_READY_FOR_LIVE_GATE_REVIEW

The marker `FINAL_NON_LIVE_REBUILD_READY_FOR_LIVE_GATE_REVIEW` at `claude_worklog/final_readiness/04_GO_NO_GO.md` is a separate downstream artifact requiring explicit human approval. The `V2_BACKTEST_AND_PAPER_MVP_READY` marker does NOT advance, replace, or substitute for that gate. The two markers certify different things:

- `V2_BACKTEST_AND_PAPER_MVP_READY` certifies that the seven REQ_0017 typed surfaces exist, are import-clean, are unit-test-covered, and have all received Codex PASS reviews.
- `FINAL_NON_LIVE_REBUILD_READY_FOR_LIVE_GATE_REVIEW` certifies (separately, downstream, and only after the post-consolidation evidence-collection lanes per REQ_0020 § "Required proof before live" produce paper / backtest / shadow evidence) that the non-live rebuild as a whole is ready for the live-gate review.

## Codex / Claude / Ollama / Copilot role discipline at and after this consolidation

Per REQ_0011 / REQ_0021:

- Claude Code remains the planner / architect / primary builder.
- Codex remains the adversarial reviewer / autofixer / watchdog / test hardener / safety auditor / regression detector. Codex retains autofix authority for non-live blockers per REQ_0007 / REQ_0014 / REQ_0016 within the allowed scope (`v2/`, `claude_worklog/phase2_core_rebuild/`, `claude_worklog/v2_scaffold_reviews/`, `claude_worklog/security/`, `claude_worklog/agent_supervisor/tasks/`, `claude_worklog/tools/` only for safety / status / review tooling, `claude_worklog/requirements_inbox/`, `claude_worklog/autonomous_control_plane/`, `claude_worklog/agent_supervisor_reliability/`).
- Ollama remains restricted to summarization / context compression. Ollama may not make final safety claims, decide risk, approve strategy, approve live trading, or mutate the legacy bot.
- Copilot remains terminal / status operator only.

V2_BACKTEST_AND_PAPER_MVP_READY_SAFETY_BOUNDARIES_AND_LIVE_GATE_POSTURE_READY
