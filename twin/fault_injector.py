"""Compatibility import for the relocated physical fault injector."""

from faults.physical import (
    SCENARIO_DEFAULTS,
    FaultInjector,
    FaultProfile,
    injector_from_scenario,
)

__all__ = ["SCENARIO_DEFAULTS", "FaultInjector", "FaultProfile", "injector_from_scenario"]
