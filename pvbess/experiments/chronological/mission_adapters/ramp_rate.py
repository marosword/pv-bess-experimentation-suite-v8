# Ramp cases, NESO (2026, BC1.A.1.5)
from __future__ import annotations

from math import isfinite

from ....missions import (
    RampProfileModel,
    RampTargetPoint,
    RegisteredRampRates,
)
from ...config import RampRateExperimentScenario, RampRateScenarioPoint
from ..models import HealthyChronology
from .common import build_chronological_availability, interval_hours


# minute grid plus comparison slop
_SAMPLE_INTERVAL_MINUTES = 1.0; _TIME_TOLERANCE_MINUTES = 1e-9


class ChronologicalRampRateScenarioBuilder:
    mission_id = "ramp_profile_capability"

    def __init__(
        self,
        specification_id: str,
        target_power: float,
        rates: RegisteredRampRates,
        tolerance: float,
    ) -> None:
        if not specification_id:
            raise ValueError("specification_id cannot be empty")
        if not isfinite(target_power):
            raise ValueError("target_power must be finite")
        self.specification_id = specification_id
        self.target_power = target_power
        self.rates = rates
        self.tolerance = tolerance

    def build(
        self, chronology: HealthyChronology, onset_index: int
    ) -> RampRateExperimentScenario:
        p0 = chronology.points[onset_index]
        P0 = p0.poi_power
        rr = self._sampled_targets(P0)
        tt = tuple(
            x.elapsed_minutes for x in rr
        )
        out = tuple(
            RampRateScenarioPoint(
                elapsed_minutes=x.elapsed_minutes,
                target_power=x.target_power,
                availability=build_chronological_availability(
                    chronology,
                    onset_index,
                    x.elapsed_minutes / 60.0,
                    interval_hours(tt, ii, 60.0)
                    if len(tt) > 1
                    else _SAMPLE_INTERVAL_MINUTES / 60.0,
                    p0.branch_soc_before,
                ),
            )
            for ii, x in enumerate(rr)
        )
        cfg = chronology.configuration
        return RampRateExperimentScenario(
            scenario_id=f"{chronology.site_id}_{p0.timestamp_utc:%Y%m%dT%H%M}_{self.specification_id}",
            points=out,
            boundary=cfg.boundary,
            reactive_support_mode=cfg.reactive_support_mode,
            rates=self.rates,
            initial_profile_power=P0,
            power_tolerance=self.tolerance,
            step_power_tolerance=self.tolerance,
            energy_tolerance=self.tolerance,
            time_tolerance_minutes=_TIME_TOLERANCE_MINUTES,
            sample_interval_minutes=_SAMPLE_INTERVAL_MINUTES,
        )

    def _sampled_targets(
        self, initial_power: float
    ) -> tuple[RampTargetPoint, ...]:
        if abs(self.target_power - initial_power) <= self.tolerance:
            return (RampTargetPoint(0.0, self.target_power),)
        tmp = RampProfileModel()
        ss = tmp.plan_segments(
            initial_power, self.target_power, 0.0, self.rates
        )
        if not ss:
            raise RuntimeError(
                "a demanded ramp has no reference-profile segments"
            )
        end = ss[-1].expected_arrival_minutes
        tt = []
        t0 = _SAMPLE_INTERVAL_MINUTES
        while t0 < end - 1e-12:
            tt.append(t0)
            t0 += _SAMPLE_INTERVAL_MINUTES
        for seg in ss:
            if (
                1e-12
                < seg.expected_arrival_minutes
                < end - 1e-12
            ):
                tt.append(seg.expected_arrival_minutes)
        out = []
        for t0 in sorted(tt):
            if not out or abs(t0 - out[-1]) > 1e-12:
                out.append(t0)
        return (
            RampTargetPoint(0.0, self.target_power),
            *(
                RampTargetPoint(t0, self.target_power)
                for t0 in out
            ),
            RampTargetPoint(end, self.target_power),
        )
