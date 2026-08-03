"""Freshness-based self-healing supervisor for non-ingestor V2 components.

Process-liveness alone is insufficient: a component can be alive-but-hung (its
process is up but it has stopped publishing fresh evidence). This package heals a
component when it is dead OR its heartbeat is stale, with hard safety pins:

  - only ENABLED units are healed (a disabled unit == operator wants it off);
  - a deliberately-stopped marker suppresses healing so the supervisor never
    fights an operator;
  - a denylist protects live/canary/legacy/ingestor/masked units;
  - remediation is `systemctl --user restart`, which preserves the unit env
    (LIVE_GATE=blocked_human_only) -- it never enables live, changes leverage/
    margin, or touches the exchange;
  - per-unit restart-rate limiting prevents restart storms.
"""

from .component_registry import (
    ComponentSpec,
    HealDecision,
    NON_INGESTOR_COMPONENTS,
    UNIT_DENYLIST_SUBSTRINGS,
    decide_heal_action,
)

__all__ = [
    "ComponentSpec",
    "HealDecision",
    "NON_INGESTOR_COMPONENTS",
    "UNIT_DENYLIST_SUBSTRINGS",
    "decide_heal_action",
]
