# 01 Continuous Monitoring Architecture

## Objective
Provide a 24/7 local, read-only monitoring architecture that produces structured evidence packets for Claude and Codex without constant token burn.

## Core operating principles
- Monitor runs locally 24/7 in read-only mode.
- Primary output is structured files (JSONL + packet markdown/json), not direct model prompts every minute.
- Claude consumes hourly/daily/alert packets.
- Codex consumes gate packets for implementation/schema review.
- No mutation actions are permitted.

## Hard safety boundaries (must never happen)
- No Redis writes.
- No Redis key deletion.
- No service restart/stop/start.
- No order placement/cancel.
- No leverage/margin changes.
- No mutation of /home/wali/Desktop/AI BOT.

## Logical architecture
1. Collector layer (read-only probes)
   - Redis read probes, stream counters, key freshness probes, heartbeat checks, system memory, VPN route checks.
2. Normalizer layer
   - Canonical schema normalization for timestamps, symbols, components, alert classes.
3. Evidence compiler layer
   - Builds packet-ready summaries from raw snapshots over time windows.
4. Packet publisher layer
   - Writes hourly, daily, and alert evidence packets to disk.
5. Review gates
   - Claude: operational interpretation and risk narrative.
   - Codex: schema correctness, linkage completeness, implementation consistency.

## File outputs (proposed)
- `continuous_monitoring/raw/*.jsonl` (rolling raw facts)
- `continuous_monitoring/packets/hourly/*.json`
- `continuous_monitoring/packets/daily/*.json`
- `continuous_monitoring/packets/alerts/*.json`
- `continuous_monitoring/reviews/claude/*.md`
- `continuous_monitoring/reviews/codex/*.md`

## Cadence
- Probe cadence: 30s–60s.
- Hourly packet generation: top of hour.
- Daily packet generation: UTC day boundary.
- Alert packet generation: immediate on threshold breach.

## Link to existing baseline
Design extends current `read_only_monitor.py` + dashboard pattern and post-monitor findings, including `FEATURE_KEY_MONITORING_PARTIAL` and Redis high-memory observations.
