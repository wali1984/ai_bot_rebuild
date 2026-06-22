"""V2 checkpoint metadata adapter.

Parses legacy RL checkpoint filenames (and sibling metadata JSON paths) into a
V2 :class:`CheckpointMetadata` record. This module deliberately does NOT load
any PyTorch / stable-baselines3 state. The V2 control plane is paper-only and
must never deserialize legacy policy weights into V2 processes.

Recognized legacy filename patterns:

- ``legacy_live_checkpoint_<unix_ts>.zip``
- ``legacy_live_checkpoint_<unix_ts>_<model_version>.zip``
- ``hybrid_trainer_ckpt_<unix_ts>.zip``
- ``ppo_masa_ckpt_<unix_ts>_<model_version>.zip``
- ``ppo_checkpoint_<unix_ts>.zip``
- ``masa_checkpoint_<unix_ts>.pkl``
- ``enterprise_modules_<unix_ts>.pt``

If the filename does not match a known pattern, :func:`parse_legacy_checkpoint_filename`
returns ``None``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_FILENAME_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"^(?P<prefix>legacy_live_checkpoint|hybrid_trainer_ckpt|ppo_masa_ckpt|"
        r"ppo_checkpoint|masa_checkpoint|enterprise_modules)"
        r"_(?P<ts>\d{10,13})"
        r"(?:_(?P<model_version>[A-Za-z0-9][A-Za-z0-9_-]*))?"
        r"(?P<ext>\.zip|\.pt|\.pth|\.pkl|_metadata\.json)?$"
    ),
)


@dataclass(frozen=True)
class CheckpointMetadata:
    """Parsed metadata for a legacy RL checkpoint.

    No PyTorch state is loaded; only filename/path/sha256 are captured.
    """

    checkpoint_id: str
    model_version: str
    created_utc: str
    source_legacy_path: str
    sha256_if_known: Optional[str]
    prefix: str

    def as_dict(self) -> dict[str, Optional[str]]:
        return {
            "checkpoint_id": self.checkpoint_id,
            "model_version": self.model_version,
            "created_utc": self.created_utc,
            "source_legacy_path": self.source_legacy_path,
            "sha256_if_known": self.sha256_if_known,
            "prefix": self.prefix,
        }


def _ts_to_utc(ts_value: str) -> str:
    """Convert a 10- or 13-digit unix timestamp string to ISO-8601 UTC."""
    raw = int(ts_value)
    if len(ts_value) == 13:
        # milliseconds
        seconds = raw / 1000.0
    else:
        seconds = float(raw)
    return (
        datetime.fromtimestamp(seconds, tz=timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


def parse_legacy_checkpoint_filename(
    name: str, *, sha256_if_known: Optional[str] = None
) -> Optional[CheckpointMetadata]:
    """Parse a legacy RL checkpoint filename or path.

    Args:
        name: filename or path string. Only the basename is parsed.
        sha256_if_known: optional precomputed SHA256 to attach.

    Returns:
        :class:`CheckpointMetadata` or ``None`` if the basename does not match
        a known legacy pattern.
    """
    if not name:
        return None
    basename = Path(str(name)).name
    for pattern in _FILENAME_PATTERNS:
        match = pattern.match(basename)
        if not match:
            continue
        prefix = match.group("prefix")
        ts_value = match.group("ts")
        model_version = match.group("model_version") or "unknown"
        try:
            created_utc = _ts_to_utc(ts_value)
        except (ValueError, OverflowError, OSError):
            return None
        checkpoint_id = f"{prefix}_{ts_value}"
        if match.group("model_version"):
            checkpoint_id = f"{checkpoint_id}_{match.group('model_version')}"
        return CheckpointMetadata(
            checkpoint_id=checkpoint_id,
            model_version=model_version,
            created_utc=created_utc,
            source_legacy_path=str(name),
            sha256_if_known=sha256_if_known,
            prefix=prefix,
        )
    return None
