# Baseline experiment settings
from __future__ import annotations
from dataclasses import replace
from ...feasibility import DEFAULT_MISSION_FEASIBILITY_TOLERANCE
from ...graph import PlantCapabilityParameters, ReactiveSupportMode
from ...missions import PlantBoundaryLimits
from .models import ChronologicalBaselineConfiguration

# do NOT MOVE
BESS_DURATION_SWEEP_HOURS = (2.0, 4.0); SMOOTHING_WINDOW_SWEEP_HOURS = (1, 3, 6, 12, 24)
FAILURE_DURATION_SWEEP_HOURS = tuple(range(1, 25))
RAMP_RATE_SWEEP_PER_UNIT_PER_MINUTE = (0.01, 0.02, 0.05, 0.1, 0.2)
REFERENCE_RAMP_RATE_PER_UNIT_PER_MINUTE = 0.05
STATION_DC_AUTONOMY_SWEEP_HOURS = (4.0, 8.0, 12.0, 24.0)
BASELINE_BESS_DURATION_HOURS = 2.0; BASELINE_SMOOTHING_WINDOW_HOURS = 3
BASELINE_FAILURE_DURATION_HOURS = 1
BASELINE_STATION_DC_AUTONOMY_HOURS = 8.0
STATION_DC_AUTONOMY_STUDY_DURATION_HOURS = 24


def build_declared_baseline_configuration(
    *,
    bess_duration_hours: float = BASELINE_BESS_DURATION_HOURS,
    smoothing_window_hours: int = BASELINE_SMOOTHING_WINDOW_HOURS,
    station_dc_autonomy_hours: float = BASELINE_STATION_DC_AUTONOMY_HOURS,
) -> ChronologicalBaselineConfiguration:
    e0 = bess_duration_hours / 2.0
    thing = PlantCapabilityParameters.normalized_reference()
    declared_capability = replace(
        thing,
        bess_energy_ratings=(e0, e0),
        bess_soc=(0.5, 0.5),
        bess_min_soc=(0.0, 0.0),
        bess_max_soc=(1.0, 1.0),
    )
    return ChronologicalBaselineConfiguration(
        capability=declared_capability,
        boundary=PlantBoundaryLimits(0.0, 1.0),
        reactive_support_mode=ReactiveSupportMode.SOURCE_COUPLED,
        maximum_capacity=1.0,
        charge_efficiency=0.95,
        discharge_efficiency=0.95,
        smoothing_window_hours=smoothing_window_hours,
        station_dc_autonomy_hours=station_dc_autonomy_hours,
        warmup_cycles=1,
        numerical_tolerance=DEFAULT_MISSION_FEASIBILITY_TOLERANCE,
        maximum_warmup_cycles=50,
        cyclic_energy_tolerance=1e-09,
    )
