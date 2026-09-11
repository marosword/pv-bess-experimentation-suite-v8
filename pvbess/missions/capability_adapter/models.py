# all the little adapter containers are in this file
from __future__ import annotations
from dataclasses import dataclass; from math import isfinite; from typing import TYPE_CHECKING
from ...feasibility import FeasibilityParameters
from ...graph.capabilities import CapabilitySnapshot

if TYPE_CHECKING:
    from ..active_power.models import ActivePowerWindow
    from ..frequency_response.models import (
        FrequencyResponseAssessmentInterval,
        FrequencyResponseCase,
    )
    from ..ramp_rate.models import RampRateWindow
from ..frequency_response.requirements import (
    FrequencyResponseService,
)


@dataclass(frozen=True)
class PlantBoundaryLimits:
    minimum_poi_power: float
    maximum_poi_power: float
    maximum_apparent_power: float | None = None

    def __post_init__(self) -> None:
        # reject invalid plant export limits early
        if not isfinite(self.minimum_poi_power) or not isfinite(
            self.maximum_poi_power
        ):
            raise ValueError("POI limits must be finite")
        if self.minimum_poi_power > self.maximum_poi_power:
            raise ValueError(
                "minimum POI power cannot exceed max POI power"
            )
        # some experiments leave poi MVA unconstrained
        if self.maximum_apparent_power is not None and (
            not isfinite(self.maximum_apparent_power)
            or self.maximum_apparent_power <= 0.0
        ):
            raise ValueError(
                "maximum apparent power must be finite and +"
            )


@dataclass(frozen=True)
class BranchDispatch:
    branch_id: str
    active_power: float

    def __post_init__(self) -> None:
        # positive is discharge, negative is charge
        if not self.branch_id:
            raise ValueError("branch_id cannot be empty")
        if not isfinite(self.active_power):
            raise ValueError("branch dispatch power must be finite")


@dataclass(frozen=True)
class BranchEnergyState:
    branch_id: str
    energy: float

    def __post_init__(self) -> None:
        # energy is tracked per surviving branch
        if not self.branch_id:
            raise ValueError("branch_id cannot be empty")
        if not isfinite(self.energy):
            raise ValueError("branch energy must be finite")


@dataclass(frozen=True)
class CapabilityDispatch:
    energy: float
    branches: tuple[BranchDispatch, ...]
    branch_energy: tuple[BranchEnergyState, ...] = ()

    def __post_init__(self) -> None:
        if not isfinite(self.energy):
            raise ValueError('dispatch energy must be finite')
        # duplicate ids would break branch totals
        ids = [x.branch_id for x in self.branches]
        if len(ids)!=len(set(ids)): raise ValueError('dispatch branch IDs must be unique')
        # energy rows need unique branches
        eids = [z.branch_id for z in self.branch_energy]
        if len(eids) != len(set(eids)):
            raise ValueError('branch energy IDs must be unique')
        # aggregate energy must equal branch sum
        if (
            self.branch_energy
            and abs(
                sum((z.energy for z in self.branch_energy))
                - self.energy
            )
            > 1e-09
        ):
            raise ValueError(
                "branch energies must sum to aggregate energy"
            )


# dispatch joined back to capability
@dataclass(frozen=True)
class CapabilityStatePoint:
    snapshot: CapabilitySnapshot
    feasibility_parameters: FeasibilityParameters
    dispatch: CapabilityDispatch


@dataclass(frozen=True)
class CapabilityAvailabilityPoint:
    snapshot: CapabilitySnapshot
    feasibility_parameters: FeasibilityParameters


# timed M1 input
@dataclass(frozen=True)
class ActivePowerSearchSample:
    elapsed_minutes: float
    setpoint_power: float
    availability: CapabilityAvailabilityPoint


# ramp points reuse the timed input shape
@dataclass(frozen=True)
class RampRateSearchSample:
    elapsed_minutes: float
    target_power: float
    availability: CapabilityAvailabilityPoint


# healthy and failed inputs side by side
@dataclass(frozen=True)
class FrequencyResponseAvailabilitySample:
    elapsed_seconds: float
    frequency_hz: float
    failed_availability: CapabilityAvailabilityPoint
    healthy_reference_availability: CapabilityAvailabilityPoint


@dataclass(frozen=True)
class FrequencyResponseSearchCase:
    case_id: str
    service: FrequencyResponseService
    baseline_power: float
    samples: tuple[FrequencyResponseAvailabilitySample, ...]
    fixed_high_loading_requirement_fraction: float | None = None
    minimum_applicable_loading_fraction: float | None = None
    maximum_applicable_loading_fraction: float | None = None
    assessment_intervals: tuple[
        FrequencyResponseAssessmentInterval, ...
    ] = ()

    def __post_init__(self) -> None:
        if not self.case_id:
            raise ValueError("case_id cannot be empty")
        # a case needs actual samples
        if not self.samples:
            raise ValueError("freq-response search needs samples")
        if not isfinite(self.baseline_power):
            raise ValueError("baseline_power must be finite")


@dataclass(frozen=True)
class FrequencyResponseCaseSearchResult:
    healthy_dispatch: DispatchTrajectorySolution
    failed_dispatch: DispatchTrajectorySolution | None
    case: FrequencyResponseCase | None


@dataclass(frozen=True)
class PowerTrajectoryRequirement:
    minimum_poi_power: float
    maximum_poi_power: float
    preferred_poi_power: float

    def __post_init__(self) -> None:
        # finite target and allowed band
        z = (
            self.minimum_poi_power,
            self.maximum_poi_power,
            self.preferred_poi_power,
        )
        if any((not isfinite(x) for x in z)):
            raise ValueError(
                "trajectory power requirements must be finite"
            )
        if self.minimum_poi_power > self.maximum_poi_power:
            raise ValueError(
                "minimum required power cannot exceed maximum"
            )


@dataclass(frozen=True)
class DispatchTrajectorySolution:
    feasible: bool
    states: tuple[CapabilityStatePoint, ...]
    reason: str | None


@dataclass(frozen=True)
class ActivePowerSearchResult:
    dispatch: DispatchTrajectorySolution
    window: ActivePowerWindow | None


@dataclass(frozen=True)
class RampRateSearchResult:
    dispatch: DispatchTrajectorySolution
    window: RampRateWindow | None


@dataclass(frozen=True)
class ReactivePlantLimit:
    minimum_reactive_power: float
    maximum_reactive_power: float

    def __post_init__(self) -> None:
        # plant Q bounds
        if not isfinite(self.minimum_reactive_power) or not isfinite(
            self.maximum_reactive_power
        ):
            raise ValueError("reactive plant limits must be finite")
        if self.minimum_reactive_power > self.maximum_reactive_power:
            raise ValueError("minimum Q cannot exceed maximum Q")


@dataclass(frozen=True)
class PowerCapabilityRequest:
    active_power: float
    plant_limit: ReactivePlantLimit | None

    def __post_init__(self) -> None:
        if not isfinite(self.active_power) or self.active_power < 0.0:
            raise ValueError(
                "active_power must be finite and non-negative"
            )


@dataclass(frozen=True)
class VoltageCapabilityRequest:
    voltage_per_unit: float
    plant_limit: ReactivePlantLimit | None
    converter_rating_factor: float = 1.0

    def __post_init__(self) -> None:
        if (
            not isfinite(self.voltage_per_unit)
            or self.voltage_per_unit <= 0.0
        ):
            raise ValueError("voltage_per_unit must be positive")
        # voltage can derate converter capability
        if (
            not isfinite(self.converter_rating_factor)
            or not 0.0 <= self.converter_rating_factor <= 1.0
        ):
            raise ValueError(
                "converter_rating_factor must be in [0, 1]"
            )
