# active power inputs
# time samples and some validation stuff
from __future__ import annotations
from dataclasses import dataclass; from ...feasibility import FeasibilityResult; from ..base import MissionContext


@dataclass(frozen=True)
class ActivePowerSample:
    elapsed_minutes:float; setpoint_power:float
    feasibility: FeasibilityResult


@dataclass(frozen=True)
class ActivePowerWindow:
    samples: tuple[ActivePowerSample, ...]
    interval_average_samples: bool = False

    def __post_init__(self) -> None:
        if not self.samples:
            raise ValueError(
                'an active-power window requires at least one sample'
            )
        tt = [
            x.elapsed_minutes for x in self.samples
        ]
        if any((b <= a for a, b in zip(
                    tt, tt[1:]))):
            raise ValueError(
                "active-power sample times must be increasing"
            )


@dataclass(frozen=True)
class ActivePowerMissionContext(MissionContext):
    physical_window: ActivePowerWindow
    numerical_tolerance: float

    def __post_init__(self) -> None:
        if self.numerical_tolerance < 0.0:
            raise ValueError("numerical_tolerance cannot be negative")
