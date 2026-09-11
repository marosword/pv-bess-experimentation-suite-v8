# Reactive cases, NESO (2026, ECC.6.3.2.4)
from __future__ import annotations

from dataclasses import replace

from ....feasibility import (
    DEFAULT_MISSION_FEASIBILITY_TOLERANCE,
    FeasibilityParameters,
)
from ....missions import (
    BelowTwentyMode,
    PowerCapabilityRequest,
    ReactiveAssessmentScope,
    VoltageCapabilityRequest,
    build_at_or_below_33_kv_voltage_requirements,
)
from ...config import AvailabilityInput, ReactivePowerExperimentScenario
from ..models import (
    ChronologicalBaselineConfiguration,
    HealthyChronology,
)
from .common import build_chronological_availability


# fixed grids for this experiment
_POWER_POINTS = tuple(index / 20.0 for index in range(21)); _VOLTAGES = (0.95, 1.0, 1.05)


class ChronologicalReactivePowerScenarioBuilder:
    mission_id = "reactive_power_capability"

    def __init__(
        self,
        specification_id: str,
        poi_apparent_power_ratio: float,
        declared: bool,
    ) -> None:
        self.specification_id = specification_id
        self.poi_apparent_power_ratio = poi_apparent_power_ratio
        self.declared = declared

    def build(
        self, chronology: HealthyChronology, onset_index: int
    ) -> ReactivePowerExperimentScenario:
        if self.declared:
            raise ValueError("declared envelopes use build_declared")
        p0 = chronology.points[onset_index]
        a0 = build_chronological_availability(
            chronology,
            onset_index,
            elapsed_hours=0.0,
            timestep_hours=1.0,
            initial_soc=p0.branch_soc_before,
        )
        return self._scenario(
            chronology.configuration,
            a0,
            (PowerCapabilityRequest(p0.poi_power, None),),
            None,
            ReactiveAssessmentScope.POWER_REACTIVE_POINTS,
            f"{chronology.site_id}_{p0.timestamp_utc:%Y%m%dT%H%M}_{self.specification_id}",
        )

    def build_declared(
        self, baseline: ChronologicalBaselineConfiguration
    ) -> ReactivePowerExperimentScenario:
        if not self.declared:
            raise ValueError(
                "build_declared requires a declared envelope"
            )
        cap = replace(
            baseline.capability,
            pv_availability=1.0,
            bess_soc=(0.5, 0.5),
        )
        Emax = sum(
            rating * soh * (maximum - minimum)
            for rating, soh, minimum, maximum in zip(
                cap.bess_energy_ratings,
                cap.bess_soh,
                cap.bess_min_soc,
                cap.bess_max_soc,
            )
        )
        a0 = AvailabilityInput(
            capability=cap,
            feasibility=FeasibilityParameters(
                energy_min=0.0,
                energy_max=Emax,
                charge_efficiency=baseline.charge_efficiency,
                discharge_efficiency=baseline.discharge_efficiency,
                timestep_hours=1.0,
            ),
            station_dc_autonomy_hours=baseline.station_dc_autonomy_hours,
        )
        return self._scenario(
            baseline,
            a0,
            tuple(
                PowerCapabilityRequest(power, None)
                for power in _POWER_POINTS
            ),
            1.0,
            ReactiveAssessmentScope.POWER_AND_VOLTAGE_ENVELOPES,
            self.specification_id,
        )

    def _scenario(
        self,
        baseline: ChronologicalBaselineConfiguration,
        availability: AvailabilityInput,
        power_requests: tuple[PowerCapabilityRequest, ...],
        voltage_active_power: float | None,
        assessment_scope: ReactiveAssessmentScope,
        scenario_id: str,
    ) -> ReactivePowerExperimentScenario:
        vv = _VOLTAGES if self.declared else ()
        return ReactivePowerExperimentScenario(
            scenario_id=scenario_id,
            availability=availability,
            boundary=replace(
                baseline.boundary,
                maximum_apparent_power=self.poi_apparent_power_ratio
                * baseline.maximum_capacity,
            ),
            reactive_support_mode=baseline.reactive_support_mode,
            maximum_capacity=baseline.maximum_capacity,
            assessment_scope=assessment_scope,
            power_requests=power_requests,
            voltage_active_power=voltage_active_power,
            voltage_requests=tuple(
                VoltageCapabilityRequest(voltage, None)
                for voltage in vv
            ),
            voltage_requirements=(
                build_at_or_below_33_kv_voltage_requirements(
                    1.0, vv
                )
                if vv
                else ()
            ),
            below_twenty_mode=BelowTwentyMode.ZERO_TRANSFER,
            numerical_tolerance=DEFAULT_MISSION_FEASIBILITY_TOLERANCE,
            full_absorbing_capability_to_20_percent=False,
            declared_below_twenty_requirements=(),
        )
