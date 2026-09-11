# Ramp capability check, NESO (2026, BC1.A.1.5)
# build the line then compare actual power against it
from __future__ import annotations
from math import inf
from ...feasibility import (
    FeasibilityTrajectoryModel,
    FeasibilityTrajectorySample,
    IntervalPowerModel,
)
from ..base import Mission, MissionContext, MissionResult
from .models import (
    RampRateMissionContext,
)
from .profile import (
    RampProfileModel,
    RampReferenceProfile,
    RampTargetPoint,
)


class RampProfileCapabilityMission(Mission):
    def __init__(self) -> None:
        self._profile_model = RampProfileModel(); self._trajectory_model = FeasibilityTrajectoryModel()

    @property
    def mission_id(self) -> str:
        return 'ramp_profile_capability'

    def evaluate(self, context: MissionContext) -> MissionResult:
        if not isinstance(context, RampRateMissionContext):
            raise TypeError(
                "RampProfileCapabilityMission requires RampRateMissionContext"
            )
        profile = self._profile_model.build(
            tuple(
                (
                    RampTargetPoint(
                        elapsed_minutes=sample.elapsed_minutes,
                        target_power=sample.target_power,
                    )
                    for sample in context.window.samples
                )
            ),
            context.rates,
            context.initial_profile_power,
        )
        traj = self._trajectory_model.assess(
            tuple(
                (
                    FeasibilityTrajectorySample(
                        elapsed_minutes=sample.elapsed_minutes,
                        feasibility=sample.feasibility,
                    )
                    for sample in context.window.samples
                )
            ),
            context.energy_tolerance,
            context.time_tolerance_minutes,
            IntervalPowerModel.PIECEWISE_LINEAR,
        )
        dP, rate_ok = self._assess_physical(
            context, profile
        )
        demanded = any(
            (
                abs(current.profile_power - previous.profile_power)
                > context.power_tolerance
                for previous, current in zip(
                    profile.points, profile.points[1:]
                )
            )
        )
        return MissionResult(
            mission_id=self.mission_id,
            demanded=demanded,
            success=(
                dP <= context.power_tolerance
                and rate_ok
                and traj.success
                if demanded
                else None
            ),
            value=dP,
            threshold=context.power_tolerance,
        )

    def _assess_physical(
        self,
        context: RampRateMissionContext,
        profile: RampReferenceProfile,
    ) -> tuple[float, bool]:
        P = tuple(
            (
                sample.feasibility.poi_active_power
                for sample in context.window.samples
            )
        )
        dP = max(
            abs(actual - reference.profile_power)
            for actual, reference in zip(P, profile.points)
        )
        ok = True
        for previous, sample in zip(
            context.window.samples, context.window.samples[1:]
        ):
            duration = sample.elapsed_minutes - previous.elapsed_minutes
            start_power = previous.feasibility.poi_active_power
            end_power = sample.feasibility.poi_active_power
            Pmin = self._profile_model.advance(
                start_power, -inf, duration, context.rates
            )
            Pmax = self._profile_model.advance(
                start_power, inf, duration, context.rates
            )
            ok = ok and (
                end_power - Pmax
                <= context.step_power_tolerance
                and Pmin - end_power
                <= context.step_power_tolerance
            )
        return dP, ok
