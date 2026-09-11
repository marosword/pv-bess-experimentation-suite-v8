# Reactive limits, NESO (2026, ECC.6.3.2.4)
# constants first then the low power curve mess
from __future__ import annotations
from dataclasses import dataclass; from enum import Enum; from math import acos, isfinite, tan

GRID_CODE_FIGURE_REACTIVE_FRACTION = 0.33; GRID_CODE_LEADING_AT_20_FRACTION = 0.12
GRID_CODE_ZERO_TRANSFER_FRACTION = 0.05
GRID_CODE_LOW_POWER_FRACTION = 0.2
GRID_CODE_FULL_LEADING_FRACTION = 0.5
GRID_CODE_POWER_FACTOR = 0.95
GRID_CODE_POWER_FACTOR_REACTIVE_FRACTION = tan(
    acos(GRID_CODE_POWER_FACTOR)
)


class BelowTwentyMode(Enum):
    ZERO_TRANSFER = "zero_transfer"
    CONTINUED_CONTROL = "continued_control"


@dataclass(frozen=True)
class VoltageReactiveRequirement:
    voltage_per_unit: float
    minimum_reactive_power: float
    maximum_reactive_power: float

    def __post_init__(self) -> None:
        z = (
            self.voltage_per_unit,
            self.minimum_reactive_power,
            self.maximum_reactive_power,
        )
        if any((not isfinite(x) for x in z)):
            raise ValueError(
                "voltage requirement values must be finite"
            )
        if self.minimum_reactive_power > self.maximum_reactive_power:
            raise ValueError(
                "minimum required Q cannot exceed maximum required Q"
            )


@dataclass(frozen=True)
class DeclaredReactiveRequirement:
    active_power: float
    minimum_reactive_power: float
    maximum_reactive_power: float

    def __post_init__(self) -> None:
        z = (
            self.active_power,
            self.minimum_reactive_power,
            self.maximum_reactive_power,
        )
        if any((not isfinite(x) for x in z)):
            raise ValueError(
                "declared requirement values must be finite"
            )
        if self.minimum_reactive_power > self.maximum_reactive_power:
            raise ValueError(
                "minimum required Q cannot exceed maximum required Q"
            )


def build_at_or_below_33_kv_voltage_requirements(
    maximum_capacity: float, voltages_per_unit: tuple[float, ...]
) -> tuple[VoltageReactiveRequirement, ...]:
    if not isfinite(maximum_capacity) or maximum_capacity <= 0.0:
        raise ValueError("maximum_capacity must be positive")
    if not voltages_per_unit:
        raise ValueError("voltages_per_unit cannot be empty")
    Q = (
        GRID_CODE_POWER_FACTOR_REACTIVE_FRACTION * maximum_capacity
    )
    out = []
    for U in voltages_per_unit:
        if not 0.95 <= U <= 1.05:
            raise ValueError(
                'Figure (b) voltage must be in [0.95, 1.05]'
            )
        if U <= 1.0:
            Qmin = -Q * (U - 0.95) / 0.05
            Qmax = Q
        else:
            Qmin = -Q
            Qmax = Q * (1.05 - U) / 0.05
        out.append(
            VoltageReactiveRequirement(
                voltage_per_unit=U,
                minimum_reactive_power=Qmin,
                maximum_reactive_power=Qmax,
            )
        )
    return tuple(out)


def power_reactive_bounds(
    maximum_capacity: float,
    active_fraction: float,
    full_absorbing_to_20_percent: bool,
) -> tuple[float, float]:
    Q = GRID_CODE_FIGURE_REACTIVE_FRACTION * maximum_capacity
    if (
        full_absorbing_to_20_percent
        or active_fraction >= GRID_CODE_FULL_LEADING_FRACTION
    ):
        Qmin = -Q
    else:
        # middle bit is linear
        span = (
            GRID_CODE_FULL_LEADING_FRACTION
            - GRID_CODE_LOW_POWER_FRACTION
        )
        progress = (
            active_fraction - GRID_CODE_LOW_POWER_FRACTION
        ) / span
        qfrac = (
            GRID_CODE_LEADING_AT_20_FRACTION
            + progress
            * (
                GRID_CODE_FIGURE_REACTIVE_FRACTION
                - GRID_CODE_LEADING_AT_20_FRACTION
            )
        )
        Qmin = -qfrac * maximum_capacity
    return (Qmin, Q)
