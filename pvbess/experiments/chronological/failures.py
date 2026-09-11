# Apply failures at each chosen onset
from __future__ import annotations
from dataclasses import replace
from ...feasibility import FeasibilityParameters
from ..config import (
    ActivePowerExperimentScenario,
    ActivePowerScenarioPoint,
    AvailabilityInput,
)
from ..harness import CriticalSetExperimentHarness, ExperimentDefinition
from .models import (
    HealthyChronology,
    TemporalFailureRun,
)


class HourlyFailureInsertionRunner:
    def __init__(self, harness: CriticalSetExperimentHarness) -> None:
        self._harness = harness

    def run(
        self,
        chronology: HealthyChronology,
        failure_duration_hours: int,
        variant_id: str,
        universe_id: str,
        onset_indices: tuple[int, ...],
    ) -> tuple[TemporalFailureRun, ...]:
        if failure_duration_hours < 1:
            raise ValueError("failure_duration_hours must be positive")
        if len(onset_indices) != len(set(onset_indices)):
            raise ValueError("onset indices must be unique")
        n0 = (
            len(chronology.points) - failure_duration_hours + 1
        )
        if any(
            (
                ii < 0 or ii >= n0
                for ii in onset_indices
            )
        ):
            raise ValueError(
                "onset index cannot complete its failure window"
            )
        return tuple(
            self._run_onset(
                chronology,
                failure_duration_hours,
                variant_id,
                universe_id,
                onset,
            )
            for onset in onset_indices
        )

    def _run_onset(
        self,
        chronology: HealthyChronology,
        failure_duration_hours: int,
        variant_id: str,
        universe_id: str,
        onset: int,
    ) -> TemporalFailureRun:
        cfg = chronology.configuration
        hh = chronology.points[
            onset : onset + failure_duration_hours
        ]
        # failures start from healthy pre-fault soc
        SoC0 = hh[0].branch_soc_before
        emax = sum(
            (
                rating * soh * (maximum - minimum)
                for rating, soh, minimum, maximum in zip(
                    cfg.capability.bess_energy_ratings,
                    cfg.capability.bess_soh,
                    cfg.capability.bess_min_soc,
                    cfg.capability.bess_max_soc,
                )
            )
        )
        # make the points now, scenario stuff later
        # build full failure window
        points = tuple(
            (
                ActivePowerScenarioPoint(
                    elapsed_minutes=float(ii * 60),
                    setpoint_power=pp.poi_power,
                    availability=AvailabilityInput(
                        capability=replace(
                            cfg.capability,
                            pv_availability=pp.pv_capacity_factor,
                            bess_soc=SoC0,
                        ),
                        feasibility=FeasibilityParameters(
                            energy_min=0.0,
                            energy_max=emax,
                            charge_efficiency=cfg.charge_efficiency,
                            discharge_efficiency=cfg.discharge_efficiency,
                            timestep_hours=1.0,
                        ),
                        elapsed_hours_since_failure=float(ii),
                        station_dc_autonomy_hours=cfg.station_dc_autonomy_hours,
                    ),
                )
                for ii, pp in enumerate(hh)
            )
        )
        stamp = hh[0].timestamp_utc
        thing = ActivePowerExperimentScenario(
            scenario_id=f"{chronology.site_id}_{stamp:%Y%m%dT%H%M}_{failure_duration_hours}h_{variant_id}_{universe_id}",
            points=points,
            boundary=cfg.boundary,
            reactive_support_mode=cfg.reactive_support_mode,
            numerical_tolerance=cfg.numerical_tolerance,
            interval_average_samples=True,
        )
        tmp = self._harness.run(
            ExperimentDefinition(scenario=thing)
        )
        return TemporalFailureRun(
            onset_index=onset,
            onset_timestamp_utc=stamp,
            healthy_mode=hh[0].mode,
            healthy_branch_soc=SoC0,
            experiment=tmp,
        )
