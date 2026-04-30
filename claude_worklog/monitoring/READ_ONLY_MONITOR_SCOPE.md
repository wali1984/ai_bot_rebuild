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
