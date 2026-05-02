"""Per-feature freshness metadata value object.

`FreshnessMetadata` is the per-feature freshness view aligned with the freshness
policy in `claude_worklog/v2_requirements/02_FEATURE_SNAPSHOT_SCHEMA.md`. It is
distinct from `FeatureFreshnessEnvelope` (per-source) and the two coexist on
every Stage A record per the contract bullet list.
"""

from __future__ import annotations

from dataclasses import dataclass

from .errors import TrainerParityLineageError

_ALLOWED_FRESHNESS_STATUSES: frozenset[str] = frozenset(
    {"fresh", "warning", "stale", "missing"}
)


@dataclass(frozen=True, slots=True)
class FreshnessMetadata:
    """Per-feature last-update, age, and freshness-status payload.

    Each tuple is ordered by the producing pipeline. The three tuples must cover
    the same set of feature names (membership identical, ordering independent).
    """

    per_feature_last_update_ms: tuple[tuple[str, int], ...]
    per_feature_age_ms: tuple[tuple[str, int], ...]
    per_feature_status: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        if (
            not self.per_feature_last_update_ms
            and not self.per_feature_age_ms
            and not self.per_feature_status
        ):
            raise TrainerParityLineageError(
                (
                    "freshness_metadata cannot be empty; the active model consumes at least "
                    "one feature"
                ),
                field="freshness_metadata",
            )

        last_update_names = self._unique_names(
            self.per_feature_last_update_ms, "per_feature_last_update_ms"
        )
        age_names = self._unique_names(
            self.per_feature_age_ms, "per_feature_age_ms"
        )
        status_names = self._unique_names(
            self.per_feature_status, "per_feature_status"
        )

        if last_update_names != age_names or last_update_names != status_names:
            raise TrainerParityLineageError(
                (
                    "freshness_metadata feature-name set must be identical across "
                    "per_feature_last_update_ms, per_feature_age_ms, and per_feature_status"
                ),
                field="freshness_metadata",
            )

        for name, last_update_ts_ms in self.per_feature_last_update_ms:
            if last_update_ts_ms < 0:
                raise TrainerParityLineageError(
                    (
                        f"freshness_metadata feature {name!r} last_update_ts_ms "
                        "must be >= 0"
                    ),
                    field="freshness_metadata.per_feature_last_update_ms",
                )

        for name, age_ms in self.per_feature_age_ms:
            if age_ms < 0:
                raise TrainerParityLineageError(
                    f"freshness_metadata feature {name!r} age_ms must be >= 0",
                    field="freshness_metadata.per_feature_age_ms",
                )

        for name, status in self.per_feature_status:
            if status not in _ALLOWED_FRESHNESS_STATUSES:
                raise TrainerParityLineageError(
                    (
                        f"freshness_metadata feature {name!r} status {status!r} not in "
                        "allowed set"
                    ),
                    field="freshness_metadata.per_feature_status",
                )

    @staticmethod
    def _unique_names(
        entries: tuple[tuple[str, object], ...], field_name: str
    ) -> frozenset[str]:
        names: list[str] = []
        for raw_name, _ in entries:
            if not raw_name:
                raise TrainerParityLineageError(
                    f"freshness_metadata.{field_name} contains empty feature name",
                    field=f"freshness_metadata.{field_name}",
                )
            names.append(raw_name)
        if len(set(names)) != len(names):
            raise TrainerParityLineageError(
                f"freshness_metadata.{field_name} contains duplicate feature names",
                field=f"freshness_metadata.{field_name}",
            )
        return frozenset(names)
