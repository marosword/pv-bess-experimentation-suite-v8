# Convert healthy states into mission inputs
from __future__ import annotations
from dataclasses import replace
from ....feasibility import FeasibilityParameters
from ...config import AvailabilityInput
from ..models import HealthyChronology


def build_chronological_availability(
    chronology: HealthyChronology,
    onset_index: int,
    elapsed_hours: float,
    timestep_hours: float,
    initial_soc: tuple[float, float],
) -> AvailabilityInput:
    if elapsed_hours < 0.0:
        raise ValueError("elapsed time cannot be negative")
    if timestep_hours <= 0.0:
        raise ValueError("timestep_hours must be positive")
    # source stays stuck at onset here
    p0 = chronology.points[onset_index]; cfg = chronology.configuration
    Emax = sum(
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
    return AvailabilityInput(
        capability=replace(
            cfg.capability,
            pv_availability=p0.pv_capacity_factor,
            bess_soc=initial_soc,
        ),
        feasibility=FeasibilityParameters(
            energy_min=0.0,
            energy_max=Emax,
            charge_efficiency=cfg.charge_efficiency,
            discharge_efficiency=cfg.discharge_efficiency,
            timestep_hours=timestep_hours,
        ),
        elapsed_hours_since_failure=elapsed_hours,
        station_dc_autonomy_hours=cfg.station_dc_autonomy_hours,
    )


def interval_hours(
    times: tuple[float, ...], index: int, units_per_hour: float
) -> float:
    if len(times) < 2:
        raise ValueError("an event needs at least two time points")
    if index < len(times) - 1:
        dt = times[index + 1] - times[index]
    else:
        dt = times[-1] - times[-2]
    if dt <= 0.0:
        raise ValueError("event times must be strictly increasing")
    return dt / units_per_hour
