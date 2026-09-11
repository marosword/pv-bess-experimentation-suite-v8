# ramp samples, window, then every tolerance
from __future__ import annotations
from dataclasses import dataclass; from math import isfinite
from ...feasibility import FeasibilityResult
from ..base import MissionContext
from .profile import RegisteredRampRates


@dataclass(frozen=True)
class RampRateSample:
    elapsed_minutes:float; target_power:float
    feasibility: FeasibilityResult

    def __post_init__(self) -> None:
        if not isfinite(self.elapsed_minutes):
            raise ValueError("elapsed_minutes must be finite")
        if not isfinite(self.target_power):
            raise ValueError("target_power must be finite")


@dataclass(frozen=True)
class RampRateWindow:
    samples: tuple[RampRateSample, ...]

    def __post_init__(self) -> None:
        if not self.samples:
            raise ValueError(
                "a ramp-rate window requires at least one sample"
            )
        tt = [x.elapsed_minutes for x in self.samples]
        if any(
            (
                b <= a
                for a, b in zip(tt, tt[1:])
            )
        ):
            raise ValueError(
                'ramp-rate sample times must be strictly increasing'
            )


@dataclass(frozen=True)
class RampRateMissionContext(MissionContext):
    window: RampRateWindow
    rates: RegisteredRampRates
    initial_profile_power: float
    power_tolerance: float
    step_power_tolerance: float
    energy_tolerance: float
    time_tolerance_minutes: float

    def __post_init__(self) -> None:
        if not isfinite(self.initial_profile_power):
            raise ValueError("initial_profile_power must be finite")
        if (
            not isfinite(self.power_tolerance)
            or self.power_tolerance < 0.0
        ):
            raise ValueError("power_tolerance cannot be negative")
        if (
            not isfinite(self.step_power_tolerance)
            or self.step_power_tolerance < 0.0
        ):
            raise ValueError("step_power_tolerance cannot be negative")
        if (
            not isfinite(self.energy_tolerance)
            or self.energy_tolerance < 0.0
        ):
            raise ValueError("energy_tolerance cannot be negative")
        if (
            not isfinite(self.time_tolerance_minutes)
            or self.time_tolerance_minutes < 0.0
        ):
            raise ValueError(
                "time_tolerance_minutes cannot be negative"
            )
