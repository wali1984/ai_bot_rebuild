"""Read-only allocator simulation adapters (paper/analytics only)."""

from . import hedge_plan_simulator as _hedge_mod
from . import simulation as _sim_mod

# Two implementations landed during the parallel build; export whichever
# names each module provides and alias the other so all call-sites work.
simulate_allocator_decision = getattr(
    _sim_mod, "simulate_allocator_decision", None
) or getattr(_sim_mod, "build_allocator_simulation")
build_allocator_simulation = getattr(
    _sim_mod, "build_allocator_simulation", None
) or simulate_allocator_decision

simulate_hedge_plan = getattr(
    _hedge_mod, "simulate_hedge_plan", None
) or getattr(_hedge_mod, "build_hedge_plan")
build_hedge_plan = getattr(_hedge_mod, "build_hedge_plan", None) or simulate_hedge_plan

__all__ = [
    "simulate_allocator_decision",
    "build_allocator_simulation",
    "simulate_hedge_plan",
    "build_hedge_plan",
]
