# 07 Redis Memory Monitoring Plan

## Objective
Maintain safe Redis headroom and prevent memory-driven instability.

## Required metrics
- `used_memory`
- `maxmemory`
- memory ratio percent
- allocator fragmentation
- stream growth rates (critical streams)
- estimated time-to-threshold (trend-based)

## Threshold behavior
- warning/elevated/critical thresholds at 85/90/95%.
- critical threshold triggers immediate alert packet and gate review.

## Retention coordination
- Monitoring layer must report overgrowth candidates for operational streams.
- Monitoring layer must not delete keys or mutate Redis.
- Retention actions remain outside monitor and require controlled change process.

## Packet requirements
- Include ratio trend window (1h, 6h, 24h).
- Include high-growth streams contributing most to memory pressure.
- Include verification command and confidence level.
