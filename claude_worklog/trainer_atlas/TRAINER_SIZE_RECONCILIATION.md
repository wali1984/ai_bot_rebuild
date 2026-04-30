# Trainer Size Reconciliation

## Measured primary trainer file
- File: `legacy_reference/rl/hybrid_trainer.py`
- Line count: 57,250
- Size (bytes): 3,165,342
- SHA256: `b7dad66b63b57c0d5c29e0fbaf67466d9c2aab81baf7a4f67b6e681e38c5b102`

## Source of prior >250k statement
- The >250k statement appears in `CLAUDE.md` legacy guidance text.
- In this snapshot, that statement is stale/wrong if interpreted as the primary single trainer file size.

## Updated canonical statement
The trainer subsystem was initially believed to be >250k lines. The current snapshot’s primary hybrid trainer file is 57,250 lines, 3,165,342 bytes, sha256 `b7dad66b63b57c0d5c29e0fbaf67466d9c2aab81baf7a4f67b6e681e38c5b102`. The broader trainer subsystem may include additional files; exact subsystem size must be computed from manifest.

## Broader subsystem count
- See `claude_worklog/trainer_atlas/TRAINER_SUBSYSTEM_LINECOUNT.txt` for line counts across `*trainer*.py` and `rl/*` paths.
