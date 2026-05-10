# Rate Limit Handoff Simulation Results

| Case | Expected | Actual | Result |
| --- | --- | --- | --- |
| Fake Claude rate-limit event | queue continues; Codex takeover starts | queue continues; Codex takeover starts | PASS |
| Fake Claude available-after-reset event | Claude handoff backlog selected | handoff condition recorded and backlog produced | PASS |
| Fake final live gate event | global stop | FINAL_LIVE_CAPITAL_APPROVAL_REQUIRED policy preserved | PASS |
| Fake Codex fail on non-live task | remediation queued | remediation policy remains Codex/Claude auto-remediation | PASS |
| Fake Redis trim hold | queue continues safe V2 work | Phase 3H remains deferred/non-blocking | PASS |
