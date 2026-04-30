# 16 Ollama Evidence Packet Plan

## Role
Ollama is a local support layer for compression, clustering, and first-pass summaries.

## Allowed uses
- summarize low-risk docs
- summarize large grep outputs
- compress monitor logs
- group repeated Redis read-only samples
- draft evidence packets
- draft anomaly clusters
- draft component summaries

## Forbidden uses
- final audit decisions
- risk approval
- live trading approval
- V2 build approval
- exchange/order safety decisions
- Redis write decisions
- trainer/runtime parameter changes
- checkpoint compatibility decisions
- margin/leverage decisions

## Evidence integrity
Ollama output is not evidence.
Every Ollama summary must include raw evidence pointers:
- source file and line/range
- raw log line
- Redis key/sample read command
- runtime process command
- verification command
- source artifact path

## Runtime monitor usage
Ollama may summarize:
- monitoring/snapshots.jsonl
- trainer_metrics.jsonl
- trader/exchange error groups
- memory pressure clusters
- signal attribution anomalies
- Redis read-only sample groups

## Failure mode
If Ollama is unavailable:
OLLAMA_OPTIONAL_NOT_BLOCKING

## Final authority
Claude/Codex/deterministic tools must verify safety-critical claims against raw evidence.
