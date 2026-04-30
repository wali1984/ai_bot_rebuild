# 14 Continuous Monitoring and Evidence Packet Architecture

## Packet model
- hourly packets
- daily packets
- alert packets
- Claude review packets
- Codex review packets
- Ollama summarization packets

## Monitoring domains
- trainer liveness (corrected logic)
- feature flow monitoring
- signal attribution monitoring
- Redis memory monitoring
- readiness/dashboard monitoring

## Evidence storage
- Packet metadata in DB (`evidence_packets`)
- Raw payload retention with lifecycle policy
- Cross-reference by `monitor_snapshot_id` and `change_id`

## Dashboard readiness
- Real-time packet ingestion status
- confidence/evidence quality indicators
- alert classification and ack workflows
