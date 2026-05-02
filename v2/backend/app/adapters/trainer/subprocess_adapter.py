"""Trainer subprocess adapter placeholder.

Subprocess boundary only. Will invoke `LEGACY_TRAINER_PYTHON` via
`subprocess.run(...)` with `--mode read_only|status|export`. No legacy
trainer modules are ever imported into the FastAPI process.
"""