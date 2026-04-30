# Claude Phase 1 Resume Context

The project is resuming after a network/VPN interruption.

Operational update:
- PIA split tunnel has been repaired.
- Fresh /usr/bin/python3.12 routes through PIA piavpnonly.
- Binance public spot/futures endpoints return 200.
- Existing bot processes were restarted into piavpnonly.
- Trader HTTP 451 restricted-location errors have been resolved.
- Do not touch VPN/network/live bot during Claude Phase 1.

Current project state:
- Deterministic coverage tools have been implemented and run.
- Trainer atlas tools have been implemented and run.
- PRE_CLAUDE_DETERMINISTIC_TOOL_REPORT.md ends with READY_FOR_CLAUDE_PHASE_1.
- Claude Phase 1 coverage verification still needs to run.
- V2 build remains blocked.

Claude Phase 1 scope:
- verify coverage artifacts
- inspect raw evidence for high-risk paths
- produce GO/NO-GO
- do not build V2
