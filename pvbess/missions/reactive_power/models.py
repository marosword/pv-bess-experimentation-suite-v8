# Reactive capability data, NESO (2026, ECC.6.3.2.4)
# q data and validation here
from __future__ import annotations
from dataclasses import dataclass; from enum import Enum; from math import isfinite
from ..base import MissionContext
from .requirements import (
    GRID_CODE_LOW_POWER_FRACTION,
    BelowTwentyMode,
    DeclaredReactiveRequirement,
    VoltageReactiveRequirement,
)

_COORDINATE_TOLERANCE = 1e-09


# P-Q only or full envelope
class ReactiveAssessmentScope(Enum):
    POWER_REACTIVE_POINTS = "power_reactive_points"
    POWER_AND_VOLTAGE_ENVELOPES = "power_and_voltage_envelopes"


@dataclass(frozen=True)
class ReactiveCapabilityRange:
    minimum_reactive_power: float | None
    maximum_reactive_power: float | None
    operating_point_feasible: bool = True

    def __post_init__(self) -> None:
        # feasible point needs both Q limits
        if self.operating_point_feasible:
            if (
                self.minimum_reactive_power is None
                or self.maximum_reactive_power is None
            ):
                raise ValueError(
                    "a feasible operating point requires both Q limits"
                )
            if not isfinite(
                self.minimum_reactive_power
            ) or not isfinite(self.maximum_reactive_power):
                raise ValueError(
                    "reactive capability limits must be finite"
                )
            if (
                self.minimum_reactive_power
                > self.maximum_reactive_power
            ):
                raise ValueError("minimum Q cannot exceed maximum Q")


@dataclass(frozen=True)
class PowerReactiveCapabilityPoint:
    active_power: float
    capability: ReactiveCapabilityRange

    def __post_init__(self) -> None:
        # active-power slice
        if not isfinite(self.active_power):
            raise ValueError("active_power must be finite")


@dataclass(frozen=True)
class VoltageReactiveCapabilityPoint:
    active_power: float
    voltage_per_unit: float
    capability: ReactiveCapabilityRange

    def __post_init__(self) -> None:
        # U-Q coordinates
        if not isfinite(self.active_power) or not isfinite(
            self.voltage_per_unit
        ):
            raise ValueError(
                "voltage capability coordinates must be finite"
            )


@dataclass(frozen=True)
class ReactivePowerMissionContext(MissionContext):
    maximum_capacity: float
    assessment_scope: ReactiveAssessmentScope
    power_capability_points: tuple[PowerReactiveCapabilityPoint, ...]
    voltage_capability_points: tuple[
        VoltageReactiveCapabilityPoint, ...
    ]
    voltage_requirements: tuple[VoltageReactiveRequirement, ...]
    below_twenty_mode: BelowTwentyMode
    numerical_tolerance: float
    full_absorbing_capability_to_20_percent: bool = False
    declared_below_twenty_requirements: tuple[
        DeclaredReactiveRequirement, ...
    ] = ()

    def __post_init__(self) -> None:
        # normalise against plant capacity
        if (
            not isfinite(self.maximum_capacity)
            or self.maximum_capacity <= 0.0
        ):
            raise ValueError("maximum_capacity must be positive")
        # at least one P-Q test
        if not self.power_capability_points:
            raise ValueError("power_capability_points cannot be empty")
        if not isinstance(
            self.assessment_scope, ReactiveAssessmentScope
        ):
            raise TypeError(
                "assessment_scope must be a ReactiveAssessmentScope"
            )
        # U-Q data comes as one block
        has_uq = bool(
            self.voltage_capability_points or self.voltage_requirements
        )
        if (
            self.assessment_scope
            is ReactiveAssessmentScope.POWER_AND_VOLTAGE_ENVELOPES
        ):
            if not self.voltage_capability_points:
                raise ValueError(
                    "voltage_capability_points cannot be empty"
                )
            if not self.voltage_requirements:
                raise ValueError("voltage_requirements cannot be empty")
            # full envelope uses maximum output
            if any(
                (
                    abs(x.active_power - self.maximum_capacity)
                    > self.numerical_tolerance
                    for x in self.voltage_capability_points
                )
            ):
                raise ValueError(
                    "voltage capability must be calculated at Maximum Capacity"
                )
            u_cap = tuple(
                (
                    x.voltage_per_unit
                    for x in self.voltage_capability_points
                )
            )
            u_req = tuple(
                (
                    x.voltage_per_unit
                    for x in self.voltage_requirements
                )
            )
            # duplicate voltages make matching ambiguous
            if _has_near_duplicates(
                u_cap, self.numerical_tolerance
            ):
                raise ValueError(
                    "voltage capability points must be unique"
                )
            if _has_near_duplicates(
                u_req, self.numerical_tolerance
            ):
                raise ValueError("voltage requirements must be unique")
            # both voltage grids must line up
            if len(u_cap) != len(
                u_req
            ) or any(
                (
                    not any(
                        (
                            abs(
                                u0 - u1
                            )
                            <= self.numerical_tolerance
                            for u0 in u_cap
                        )
                    )
                    for u1 in u_req
                )
            ):
                raise ValueError(
                    "voltage capability and requirement slices must match"
                )
        elif has_uq:
            raise ValueError(
                "power-only assessment cannot include voltage-envelope inputs"
            )
        if (
            not isfinite(self.numerical_tolerance)
            or self.numerical_tolerance < 0.0
        ):
            raise ValueError("numerical_tolerance cannot be negative")
        # export range checks
        for pt in self.power_capability_points:
            if pt.active_power < -_COORDINATE_TOLERANCE:
                raise ValueError("Mission 3 is export-only")
            if (
                pt.active_power
                > self.maximum_capacity + _COORDINATE_TOLERANCE
            ):
                raise ValueError(
                    "active power cannot exceed Maximum Capacity"
                )
        # low power needs plant specific q limits
        if self.below_twenty_mode is BelowTwentyMode.CONTINUED_CONTROL:
            P20 = (
                GRID_CODE_LOW_POWER_FRACTION * self.maximum_capacity
            )
            for pt in self.power_capability_points:
                if (
                    pt.active_power
                    < P20 - _COORDINATE_TOLERANCE
                    and find_declared_requirement(
                        pt.active_power,
                        self.declared_below_twenty_requirements,
                    )
                    is None
                ):
                    raise ValueError(
                        f"continued control requires a declared Q range for P={pt.active_power:g}"
                    )


def find_declared_requirement(
    active_power: float,
    requirements: tuple[DeclaredReactiveRequirement, ...],
) -> DeclaredReactiveRequirement | None:
    return next(
        (
            x
            for x in requirements
            if abs(x.active_power - active_power)
            <= _COORDINATE_TOLERANCE
        ),
        None,
    )


def _has_near_duplicates(
    values: tuple[float, ...], tolerance: float
) -> bool:
    # compare within tolerance
    z = sorted(values)
    return any(
        (
            b - a <= tolerance
            for a, b in zip(z, z[1:])
        )
    )
