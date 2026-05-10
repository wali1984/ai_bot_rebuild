# Export Integrity Check

A bounded compressed JSONL export proof was written. Full export was not run autonomously.

| path | entries | first_id | last_id | bytes | sha256 |
| --- | --- | --- | --- | --- | --- |
| claude_worklog/final_readiness/redis_memory_human_approval/latest/export/liquidations_events_oldest_sample.jsonl.gz | 1000 | 1772952007223-4 | 1772952038115-2 | 35326 | 9377f6e762d6a2f777e1c916ab34f36c0ff561122c809551020dfc123d4e1a88 |
| claude_worklog/final_readiness/redis_memory_human_approval/latest/export/liquidations_events_latest_sample.jsonl.gz | 1000 | 1778374816865-4 | 1778392914403-0 | 27508 | 7097eff948d5d63cc8f0348fb546332a28fce23aaf504c4ccff7cd95c5e2b181 |

REDIS_EXPORT_INTEGRITY_CHECK_READY
