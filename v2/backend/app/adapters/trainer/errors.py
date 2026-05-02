"""Trainer subprocess adapter error types."""

from __future__ import annotations


class TrainerSubprocessSafetyError(RuntimeError):
    """Raised when a subprocess invocation violates the non-live safety envelope."""


class TrainerSubprocessTimeoutError(RuntimeError):
    """Raised when the bounded subprocess runner reports a timeout."""


class TrainerSubprocessConfigError(RuntimeError):
    """Raised when adapter configuration is invalid."""
