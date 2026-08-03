"""V2 native ingestors verification + classification (P0.5)."""
from .registry import (
    INGESTOR_REGISTRY,
    IngestorClassification,
    IngestorRecord,
    classify_all_ingestors,
    ingestors_invariants_snapshot,
)

__all__ = [
    "INGESTOR_REGISTRY",
    "IngestorClassification",
    "IngestorRecord",
    "classify_all_ingestors",
    "ingestors_invariants_snapshot",
]
