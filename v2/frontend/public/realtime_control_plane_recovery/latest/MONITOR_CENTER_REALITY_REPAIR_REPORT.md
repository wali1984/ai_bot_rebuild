# Monitor Center Reality Repair Report

Generated at: 2026-05-12T20:14:37.744Z

Monitor Center now keeps actual monitor/script rows visible through the V2 cockpit payload and operator truth summary. Required fields are script path, owner/module, status, classification, last run/success/failure where available, metrics emitted, Redis/log/process watchers, alerts, evidence source, and freshness.

Critical monitor coverage expected:

- trainer prediction monitor: V2_PAPER_TRAINER_WRAPPER_CURRENT
- feature freshness monitor: PROCESS_OBSERVED_READONLY
- signal causality monitor: REALTIME_RUNTIME_EVIDENCE
- orchestrator monitor: PROCESS_OBSERVED_READONLY
- risk gateway monitor: RUNTIME_MONITOR_PAYLOAD_PRESENT
- execution latency monitor: RUNTIME_MONITOR_PAYLOAD_PRESENT
- Claude/Codex/Ollama supervision monitor: NO_SUPERVISOR_DAEMON_OBSERVED
