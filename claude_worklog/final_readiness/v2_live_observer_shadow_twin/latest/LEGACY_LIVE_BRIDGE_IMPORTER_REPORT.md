# Legacy Live Bridge Importer Report

Generated at: 2026-05-12T19:56:15Z

The importer used read-only process inspection and read-only Redis commands only. Redis write commands are denied by code before execution.

- Redis ping: `PONG`
- Legacy Redis writes: `false`
- Streams inspected: `6`
- Legacy trainer: `PROCESS_OBSERVED_READONLY`
- Legacy orchestrator: `PROCESS_OBSERVED_READONLY`
- Legacy trader: `PROCESS_OBSERVED_READONLY`
