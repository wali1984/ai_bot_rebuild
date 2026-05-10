# Operator Decision Required

Choose one before Phase 3H:

1. Keep holding. No Redis mutation occurs.
2. Copy the Phase 3F local export archive to a second disk or backup location,
   verify it, then reconsider trim approval.
3. Approve Phase 3H exactly as documented by creating the command-specific
   approval file.

Recommended conservative decision:

`COPY_ARCHIVE_TO_SECONDARY_BACKUP_BEFORE_PHASE3H`

Rationale: the local archive is complete and verified, but it is git-ignored
and currently only proven on the same machine. Redis stream trimming is
destructive and cannot be rolled back inside Redis.
