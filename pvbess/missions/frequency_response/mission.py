# Frequency response check, NESO (2026, ECC.A.3)
# failed and healthy get checked side by side
from __future__ import annotations

from dataclasses import dataclass

from ...feasibility import (
    FeasibilityTrajectoryModel,
    FeasibilityTrajectorySample,
)
from ..base import Mission, MissionContext, MissionResult
from .demand import (
    assessment_interval,
    calculate_frequency_response_demand,
)
from .models import (
    FrequencyResponseAssessmentInterval,
    FrequencyResponseCase,
    FrequencyResponseMissionContext,
    FrequencyResponseReference,
    FrequencyResponseSample,
)
from .requirements import FrequencyResponseService


@dataclass(frozen=True, slots=True)
class _Point:
    assessed: bool
    margin: float
    reference_feasible: bool
    success: bool | None


class FrequencyResponseCapabilityMission(Mission):
    def __init__(self) -> None:
        self._trajectory_model = (FeasibilityTrajectoryModel())

    @property
    def mission_id(self) -> str:
        return "frequency_response_resource_capability"

    def evaluate(self, context: MissionContext) -> MissionResult:
        if not isinstance(context, FrequencyResponseMissionContext):
            raise TypeError(
                "FrequencyResponseCapabilityMission requires FrequencyResponseMissionContext"
            )
        # assess every service
        mm, ok = self._assess(
            context, context.healthy_reference
        )
        # scale the worst margin by plant capacity
        value = (
            None
            if ok is None
            else mm
            / context.healthy_reference.maximum_capacity
        )
        ans = MissionResult(self.mission_id, True, ok, value, 0.0)
        return ans

    def _assess(
        self,
        context: FrequencyResponseMissionContext,
        reference: FrequencyResponseReference,
    ) -> tuple[float, bool | None]:
        # one score per case
        cases = tuple(
            self._assess_case(context, case, reference)
            for case in context.cases
        )
        services = []
        # all services need to pass
        for service in FrequencyResponseService:
            service_cases = tuple(
                (case for case in cases if case[0] is service)
            )
            if not service_cases:
                raise RuntimeError(
                    'validated Mission 4 service is missing'
                )
            margins = tuple(case[1] for case in service_cases)
            outcomes = tuple(case[2] for case in service_cases)
            outcome = (
                None
                if any(value is None for value in outcomes)
                else all(outcomes)
            )
            services.append((min(margins), outcome))
        # unknown propagates
        outcomes = tuple(outcome for _, outcome in services)
        return min(margin for margin, _ in services), (
            None
            if any(value is None for value in outcomes)
            else all(outcomes)
        )

    def _assess_case(
        self,
        context: FrequencyResponseMissionContext,
        case: FrequencyResponseCase,
        reference: FrequencyResponseReference,
    ) -> tuple[FrequencyResponseService, float, bool | None]:
        intervals = self._assessment_intervals(case)
        # assessment edges need samples
        for interval in intervals:
            self._require_boundary(
                case,
                interval.start_seconds,
                context.time_tolerance_seconds,
            )
            self._require_boundary(
                case,
                interval.end_seconds,
                context.time_tolerance_seconds,
            )
        # failed trajectory first
        trajectory = self._trajectory_model.assess(
            tuple(
                FeasibilityTrajectorySample(
                    sample.elapsed_seconds / 60.0, sample.feasibility
                )
                for sample in case.window.samples
            ),
            context.energy_tolerance,
            context.time_tolerance_seconds / 60.0,
        )
        # check healthy energy separately
        rt = self._trajectory_model.assess(
            tuple(
                FeasibilityTrajectorySample(
                    sample.elapsed_seconds / 60.0,
                    sample.healthy_reference_state.feasibility,
                )
                for sample in case.window.samples
            ),
            context.energy_tolerance,
            context.time_tolerance_seconds / 60.0,
        )
        points = tuple(
            self._assess_point(context, case, sample, reference)
            for sample in case.window.samples
        )
        # only the active window counts
        assessed = tuple(point for point in points if point.assessed)
        if not assessed:
            return case.service, 0.0, None
        # healthy feasibility gates the result
        reference_feasible = (
            all(point.reference_feasible for point in points)
            and rt.success
        )
        mm = min(point.margin for point in assessed)
        if not reference_feasible:
            ok = None
        else:
            ok = (
                trajectory.success
                and trajectory.all_steps_physically_feasible
                and all(point.success for point in assessed)
            )
        return case.service, mm, ok

    @staticmethod
    def _assess_point(
        context: FrequencyResponseMissionContext,
        case: FrequencyResponseCase,
        sample: FrequencyResponseSample,
        reference: FrequencyResponseReference,
    ) -> _Point:
        reference_state = sample.healthy_reference_state
        bounds = reference_state.capability_bounds
        # rebuild demand for this sample
        demand = calculate_frequency_response_demand(
            service=case.service,
            elapsed_seconds=sample.elapsed_seconds,
            final_elapsed_seconds=case.window.samples[
                -1
            ].elapsed_seconds,
            frequency_hz=sample.frequency_hz,
            baseline_power=case.baseline_power,
            reference=reference,
            bounds=bounds,
            droop=context.droop,
            target_frequency_hz=context.target_frequency_hz,
            declared_above_95_fraction=case.fixed_high_loading_requirement_fraction,
            time_tolerance_seconds=context.time_tolerance_seconds,
            assessment_intervals=tuple(
                (interval.start_seconds, interval.end_seconds)
                for interval in FrequencyResponseCapabilityMission._assessment_intervals(
                    case
                )
            ),
            minimum_applicable_loading_fraction=case.minimum_applicable_loading_fraction,
            maximum_applicable_loading_fraction=case.maximum_applicable_loading_fraction,
        )
        # response sign follows the service
        if case.service in (
            FrequencyResponseService.PRIMARY,
            FrequencyResponseService.SECONDARY,
        ):
            delivered = (
                sample.feasibility.poi_active_power
                - case.baseline_power
            )
            reference_delivered = (
                reference_state.feasibility.poi_active_power
                - case.baseline_power
            )
        else:
            delivered = (
                case.baseline_power
                - sample.feasibility.poi_active_power
            )
            reference_delivered = (
                case.baseline_power
                - reference_state.feasibility.poi_active_power
            )
        terminal = sample is case.window.samples[-1]
        # healthy point must meet the same demand
        reference_feasible = (
            demand.requirement_defined
            and bounds.minimum_poi_power
            <= case.baseline_power + context.numerical_tolerance
            and bounds.maximum_poi_power
            >= case.baseline_power - context.numerical_tolerance
            and FrequencyResponseCapabilityMission._point_feasible(
                reference_state.feasibility, terminal
            )
            and (
                not demand.assessed
                or (
                    demand.reference_headroom_power
                    >= demand.minimum_profile_demand_power
                    - context.numerical_tolerance
                    and reference_delivered
                    >= demand.required_response_power
                    - context.numerical_tolerance
                )
            )
        )
        # positive margin meets the request
        margin = delivered - demand.required_response_power
        assessed = demand.assessed and demand.requirement_defined
        success = None
        if assessed and reference_feasible:
            success = (
                FrequencyResponseCapabilityMission._point_feasible(
                    sample.feasibility, terminal
                )
                and margin >= -context.numerical_tolerance
            )
        return _Point(
            assessed,
            margin,
            reference_feasible,
            success,
        )

    @staticmethod
    def _point_feasible(feasibility, terminal: bool) -> bool:
        if not terminal:
            return feasibility.feasible
        # the final sample has no next interval
        ignored = {"next_energy_minimum", "next_energy_maximum"}
        return all(
            check.satisfied
            for check in feasibility.checks
            if check.constraint_id not in ignored
            and not check.constraint_id.startswith("next_bess_energy_")
        )

    @staticmethod
    def _assessment_intervals(
        case: FrequencyResponseCase,
    ) -> tuple[FrequencyResponseAssessmentInterval, ...]:
        if case.assessment_intervals:
            return case.assessment_intervals
        start, end = assessment_interval(
            case.service, case.window.samples[-1].elapsed_seconds
        )
        return (FrequencyResponseAssessmentInterval(start, end),)

    @staticmethod
    def _require_boundary(
        case: FrequencyResponseCase, boundary: float, tolerance: float
    ) -> None:
        if not any(
            abs(sample.elapsed_seconds - boundary) <= tolerance
            for sample in case.window.samples
        ):
            raise ValueError(
                f"{case.case_id} needs a sample at t={boundary:g} seconds"
            )
