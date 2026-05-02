"""Feature status flag and per-source freshness envelope value objects."""

from __future__ import annotations

from dataclasses import dataclass

from .errors import TrainerParityLineageError


@dataclass(frozen=True, slots=True)
class FeatureStatusFlags:
    """Per-feature category flags. A feature appears in at most one category."""

    stale: tuple[str, ...]
    missing: tuple[str, ...]
    unused: tuple[str, ...]

    def __post_init__(self) -> None:
        for category, values in (
            ("stale", self.stale),
            ("missing", self.missing),
            ("unused", self.unused),
        ):
            if len(set(values)) != len(values):
                raise TrainerParityLineageError(
                    f"feature_status_flags.{category} contains duplicate feature names",
                    field=f"feature_status_flags.{category}",
                )

        seen: set[str] = set()
        for category, values in (
            ("stale", self.stale),
            ("missing", self.missing),
            ("unused", self.unused),
        ):
            for feature_name in values:
                if feature_name in seen:
                    raise TrainerParityLineageError(
                        (
                            f"feature {feature_name!r} appears in multiple "
                            "feature_status_flags categories"
                        ),
                        field="feature_status_flags",
                    )
                seen.add(feature_name)


@dataclass(frozen=True, slots=True)
class FeatureFreshnessEnvelope:
    """Per-source freshness view of the feature snapshot the trainer consumed."""

    per_source_freshness_ms: tuple[tuple[str, int], ...]
    oldest_source_age_ms: int
    oldest_source_name: str

    def __post_init__(self) -> None:
        if self.oldest_source_age_ms < 0:
            raise TrainerParityLineageError(
                "feature_freshness_envelope.oldest_source_age_ms must be >= 0",
                field="feature_freshness_envelope.oldest_source_age_ms",
            )
        if not self.oldest_source_name:
            raise TrainerParityLineageError(
                "feature_freshness_envelope.oldest_source_name must be non-empty",
                field="feature_freshness_envelope.oldest_source_name",
            )
        if not self.per_source_freshness_ms:
            raise TrainerParityLineageError(
                "feature_freshness_envelope.per_source_freshness_ms must contain at least one source",
                field="feature_freshness_envelope.per_source_freshness_ms",
            )

        seen_sources: set[str] = set()
        for source_name, freshness_ms in self.per_source_freshness_ms:
            if not source_name:
                raise TrainerParityLineageError(
                    "feature_freshness_envelope source name must be non-empty",
                    field="feature_freshness_envelope.per_source_freshness_ms",
                )
            if freshness_ms < 0:
                raise TrainerParityLineageError(
                    (
                        f"feature_freshness_envelope source {source_name!r} freshness_ms "
                        "must be >= 0"
                    ),
                    field="feature_freshness_envelope.per_source_freshness_ms",
                )
            if source_name in seen_sources:
                raise TrainerParityLineageError(
                    f"feature_freshness_envelope duplicate source name: {source_name!r}",
                    field="feature_freshness_envelope.per_source_freshness_ms",
                )
            seen_sources.add(source_name)

        actual_max_age = max(age for _, age in self.per_source_freshness_ms)
        if self.oldest_source_age_ms != actual_max_age:
            raise TrainerParityLineageError(
                "feature_freshness_envelope.oldest_source_age_ms does not match maximum entry",
                field="feature_freshness_envelope.oldest_source_age_ms",
            )
        matches = [
            (name, age)
            for name, age in self.per_source_freshness_ms
            if name == self.oldest_source_name and age == actual_max_age
        ]
        if not matches:
            raise TrainerParityLineageError(
                "feature_freshness_envelope.oldest_source_name does not match maximum entry",
                field="feature_freshness_envelope.oldest_source_name",
            )
