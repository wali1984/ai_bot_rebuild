# Rollback And Forensic Limits

Redis stream trim is destructive. There is no Redis-side rollback after `XTRIM`.

Forensic preservation currently depends on the verified Phase 3F compressed
archive:

- Exported count: 70930810
- Anchor last ID: `1778432485206-24`
- Chunk count: 710
- Compressed size: 1.601 GiB
- Manifest: `claude_worklog/final_readiness/redis_liquidations_full_export/latest/export_manifest.json`
- Integrity report: `claude_worklog/final_readiness/redis_liquidations_full_export/latest/export_integrity_check.md`

Any future trim must preserve the local export archive and manifest. If the
archive is unavailable or integrity verification fails, do not trim.

Entries written after the Phase 3F export anchor are not part of that archive.
The proposed `MINID` cutoff retains a recent window and does not remove those
newer entries.
