# Frequency cases, NESO (2026, ECC.A.3)
from __future__ import annotations

from dataclasses import dataclass

from ....missions import (
    FrequencyResponseAssessmentInterval,
    FrequencyResponseReference,
    FrequencyResponseService,
)
from ...config import (
    FrequencyResponseCaseScenario,
    FrequencyResponseExperimentScenario,
    FrequencyResponseScenarioPoint,
)
from ..models import HealthyChronology
from .common import build_chronological_availability, interval_hours


@dataclass(frozen=True)
class FrequencyCaseTemplate:
    case_id: str
    service: FrequencyResponseService
    points: tuple[tuple[float, float], ...]
    assessment_intervals: tuple[
        FrequencyResponseAssessmentInterval, ...
    ] = ()


class ChronologicalFrequencyResponseScenarioBuilder:
    mission_id = "frequency_response_resource_capability"

    def __init__(
        self,
        cases: tuple[FrequencyCaseTemplate, ...],
        healthy_reference: FrequencyResponseReference,
        droop: float,
        target_frequency_hz: float,
        numerical_tolerance: float,
        energy_tolerance: float,
        time_tolerance_seconds: float,
        minimum_loading_fraction: float,
        maximum_loading_fraction: float,
    ) -> None:
        # plain fields dont change - easy to invetsigate
        self.cases = cases; self.healthy_reference = healthy_reference
        self.droop = droop
        self.target_frequency_hz = target_frequency_hz
        self.numerical_tolerance = numerical_tolerance
        self.energy_tolerance = energy_tolerance
        self.time_tolerance_seconds = time_tolerance_seconds
        self.minimum_loading_fraction = minimum_loading_fraction
        self.maximum_loading_fraction = maximum_loading_fraction

    def build(
        self, chronology: HealthyChronology, onset_index: int
    ) -> FrequencyResponseExperimentScenario:
        p0 = chronology.points[onset_index]
        cfg = chronology.configuration
        return FrequencyResponseExperimentScenario(
            scenario_id=f"{chronology.site_id}_{p0.timestamp_utc:%Y%m%dT%H%M}_frequency_operating_point",
            cases=tuple(
                self._build_case(chronology, onset_index, case)
                for case in self.cases
            ),
            boundary=cfg.boundary,
            reactive_support_mode=cfg.reactive_support_mode,
            healthy_reference=self.healthy_reference,
            droop=self.droop,
            target_frequency_hz=self.target_frequency_hz,
            numerical_tolerance=self.numerical_tolerance,
            energy_tolerance=self.energy_tolerance,
            time_tolerance_seconds=self.time_tolerance_seconds,
            allow_grid_import=False,
        )

    def _build_case(
        self,
        chronology: HealthyChronology,
        onset_index: int,
        case: FrequencyCaseTemplate,
    ) -> FrequencyResponseCaseScenario:
        p0 = chronology.points[onset_index]
        tt = tuple(t for t, _ in case.points)
        out = tuple(
            FrequencyResponseScenarioPoint(
                elapsed_seconds=t,
                frequency_hz=f,
                availability=build_chronological_availability(
                    chronology,
                    onset_index,
                    t / 3600.0,
                    interval_hours(tt, ii, 3600.0),
                    p0.branch_soc_before,
                ),
            )
            for ii, (t, f) in enumerate(case.points)
        )
        built_case_points = out
        return FrequencyResponseCaseScenario(
            case_id=case.case_id,
            service=case.service,
            baseline_power=p0.poi_power,
            points=built_case_points,
            fixed_high_loading_requirement_fraction=None,
            assessment_intervals=case.assessment_intervals,
            minimum_applicable_loading_fraction=self.minimum_loading_fraction,
            maximum_applicable_loading_fraction=self.maximum_loading_fraction,
        )
