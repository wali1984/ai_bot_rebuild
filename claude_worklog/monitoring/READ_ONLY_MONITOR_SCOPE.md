# Read-Only Monitor Scope

- duration: 12 hours
- interval: 60 seconds
- writes allowed only under claude_worklog/monitoring/
- Redis access read-only
- old Redis writes forbidden
- live trading control forbidden
- exchange actions forbidden
- trainer/trader restarts forbidden
- VPN/network changes forbidden
- V2 build forbidden
- Ollama optional summarization only

## Monitor targets
- runtime processes
- Redis stream lengths / last IDs / sample messages if safe
- trader heartbeat
- trainer heartbeat
- orchestrator heartbeat
- ingestor heartbeat
- signal streams
- execution streams
- positions/portfolio keys
- exchange error logs
- signal_id / decision_id completeness
- confidence attribution
- duplicate order IDs
- stale signal age
- latency spikes
- memory pressure
- PIA/VPN routing state read-only
- PPO/MASS metrics if available
- trainer stale flags
- feature freshness

## Feature/Ingestor Visibility Requirement
- monitor must inventory ingestor and feature keys
- monitor must track key freshness
- monitor must identify stale/missing feature sources
- monitor must detect feature keys that exist but are not consumed downstream
- monitor must detect trainer predictions without feature snapshot references
- monitor must detect signals without prediction_id / feature_snapshot_id
- monitor must detect trader actions without upstream attribution
- monitor must record data-flow gaps for V2
