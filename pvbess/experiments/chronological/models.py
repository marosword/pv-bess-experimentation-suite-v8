# chronology objects
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING
from ...graph import PlantCapabilityParameters, ReactiveSupportMode
from ...missions import PlantBoundaryLimits

if TYPE_CHECKING:
    from ...critical_sets import MissionAssessment
    from ..config import MissionExperimentScenario
    from ..harness import ExperimentRunResult


@dataclass(frozen=True)
class PvTimeSeriesPoint:
    timestamp_utc: datetime
    capacity_factor: float
    source_missing: bool = False


@dataclass(frozen=True)
class PvTimeSeries:
    site_id: str
    points: tuple[PvTimeSeriesPoint, ...]


@dataclass(frozen=True)
class ChronologicalBaselineConfiguration:
    capability: PlantCapabilityParameters
    boundary: PlantBoundaryLimits
    reactive_support_mode: ReactiveSupportMode
    maximum_capacity: float
    charge_efficiency: float
    discharge_efficiency: float
    smoothing_window_hours: int
    station_dc_autonomy_hours: float
    warmup_cycles: int
    numerical_tolerance: float
    maximum_warmup_cycles: int = 50
    cyclic_energy_tolerance: float = 1e-09


class BessOperatingMode(str, Enum):
    CHARGING = 'charging'; DISCHARGING = "discharging"; IDLE = 'idle'


@dataclass(frozen=True)
class HealthyOperatingPoint:
    timestamp_utc: datetime
    pv_capacity_factor: float
    poi_power: float
    branch_soc_before: tuple[float, float]
    mode: BessOperatingMode


@dataclass(frozen=True)
class HealthyChronology:
    site_id: str
    configuration: ChronologicalBaselineConfiguration
    points: tuple[HealthyOperatingPoint, ...]


@dataclass(frozen=True)
class TemporalFailureRun:
    onset_index: int
    onset_timestamp_utc: datetime
    healthy_mode: BessOperatingMode
    healthy_branch_soc: tuple[float, float]
    experiment: ExperimentRunResult


@dataclass(frozen=True)
class ChronologicalMissionRun:
    onset_index: int
    onset_timestamp_utc: datetime
    healthy_mode: BessOperatingMode
    healthy_branch_soc: tuple[float, float]
    scenario: MissionExperimentScenario
    baseline_assessment: MissionAssessment
    experiment: ExperimentRunResult | None
