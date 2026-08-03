"""Paper-first trade management primitives for V2.

This package is intentionally exchange-free. It turns accepted paper fills into
net paper positions, close events, and trainer outcome labels.
"""

from .lifecycle import PaperLifecycleConfig, reconcile_paper_lifecycle

__all__ = [
    "PaperLifecycleConfig",
    "reconcile_paper_lifecycle",
]
