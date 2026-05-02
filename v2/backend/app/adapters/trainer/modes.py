"""Allowed subprocess modes for the V2 trainer parity adapter."""

from __future__ import annotations

from enum import Enum


class TrainerSubprocessMode(str, Enum):
    READ_ONLY = "read_only"
    STATUS = "status"
    EXPORT = "export"


ALLOWED_MODES = frozenset(mode.value for mode in TrainerSubprocessMode)
