# Export Durability Review

Status: `LOCAL_ONLY_EXPORT_PRESENT_BUT_SECONDARY_BACKUP_NOT_VERIFIED`

## Phase 3F Export Evidence

- Manifest path: `claude_worklog/final_readiness/redis_liquidations_full_export/latest/export_manifest.json`
- Archive path: `claude_worklog/final_readiness/redis_liquidations_full_export/latest/export/`
- Chunk files found: 710
- Manifest chunk count: 710
- Exported entries: 70,930,810
- Export anchor last ID: `1778432485206-24`
- Compressed bytes from files: 1,719,357,383
- Compressed bytes from manifest: 1,719,357,383
- Compressed size: 1.601 GiB
- Disk free at review: 760.292 GiB

## Integrity Recheck

Full Phase 3F SHA-256 integrity previously passed. This hold review also
spot-checked first, middle, and last chunks against the manifest:

- `liquidations_events_000000.jsonl.gz`: SHA-256 match
- `liquidations_events_000355.jsonl.gz`: SHA-256 match
- `liquidations_events_000709.jsonl.gz`: SHA-256 match

## Git / Durability Scope

The compressed chunk archive is intentionally local-only and git-ignored. The
manifest and reports are committed, but the large `.jsonl.gz` chunks are not in
Git.

## Recommendation

Choose `REDIS_EXPORT_BACKUP_DURABILITY_REVIEW_REQUIRED`.

The archive is present and locally verified, but because Redis trim is
irreversible, the conservative next step is to copy the archive and manifest to
a secondary/off-machine backup location and verify file count, byte count, and
SHA-256 integrity there before approving Phase 3H.

No copy to external storage was performed in this task.
