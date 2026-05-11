# Freeze Backup Sync Rollback Cutover Plan

Before final legacy retirement: freeze legacy write sources, verify final backup/export, run final read-only sync into V2, compute counts/hashes, define rollback point, validate V2 readers, keep live gate blocked, then create an explicit human-reviewed cutover packet. No automatic live switch.
