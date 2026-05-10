# Optimized Export Design

```json
{
  "chunk_target_entries": 200000,
  "guards": [
    "read-only Redis commands only",
    "operator-approved runtime window",
    "stop if Redis errors increase",
    "stop if dashboard/liveness latency degrades",
    "stop if free disk falls below 50 GiB"
  ],
  "manifest_file": "export_manifest.json",
  "method": "resume_safe_chunked_xrange_to_compressed_jsonl",
  "progress_file": "export_progress.json",
  "recommended_batch_size": 10000,
  "resume_fields": [
    "last_exported_id",
    "chunk_index",
    "entries_exported",
    "sha256_per_chunk"
  ]
}
```

OPTIMIZED_EXPORT_DESIGN_READY
