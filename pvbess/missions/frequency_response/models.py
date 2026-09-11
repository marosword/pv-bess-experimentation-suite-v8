# Frequency service data, NESO (2026, ECC.A.3)
# data objects plus all their guard checks
from __future__ import annotations
from dataclasses import dataclass; from math import isfinite
from ...feasibility import FeasibilityResult
from ..base import MissionContext
from .requirements import (
    GRID_CODE_FSM_DROOP_MAXIMUM,
    GRID_CODE_FSM_DROOP_MINIMUM,
    GRID_CODE_MAXIMUM_MRL_FRACTION,
    GRID_CODE_MAXIMUM_MSOL_FRACTION,
    GRID_CODE_TARGET_FREQUENCY_MAXIMUM_HZ,
    GRID_CODE_TARGET_FREQUENCY_MINIMUM_HZ,
    FrequencyResponseService,
)

_COORDINATE_TOLERANCE = 1e-09


@dataclass(frozen=True)
class FrequencyResponseReference:
    maximum_capacity: float
    maximum_export_level: float
    minimum_regulating_level: float
    minimum_stable_operating_level: float

    def __post_init__(self) -> None:
        # validate the four plant reference levels
        vv = (
            self.maximum_capacity,
            self.maximum_export_level,
            self.minimum_regulating_level,
            self.minimum_stable_operating_level,
        )
        if any((not isfinite(x) for x in vv)):
            raise ValueError(
                'frequency-response reference values must be finite'
            )
        if self.maximum_capacity <= 0.0:
            raise ValueError("maximum_capacity must be positive")
        if (
            not 0.0
            <= self.maximum_export_level
            <= self.maximum_capacity
        ):
            raise ValueError("MEL must be in [0, Maximum Capacity]")
        if not 0.0 <= self.minimum_regulating_level:
            raise ValueError("MRL cannot be negative")
        # MRL stays under its grid-code cap
        if (
            self.minimum_regulating_level
            > GRID_CODE_MAXIMUM_MRL_FRACTION * self.maximum_capacity
            + _COORDINATE_TOLERANCE
        ):
            raise ValueError("MRL exceeds the ECC.A.3 maximum")
        if (
            self.minimum_stable_operating_level
            > GRID_CODE_MAXIMUM_MSOL_FRACTION * self.maximum_capacity
            + _COORDINATE_TOLERANCE
        ):
            raise ValueError("MSOL exceeds the ECC.A.3 maximum")
        # keep MRL below MSOL and MEL
        if (
            self.minimum_stable_operating_level
            < self.minimum_regulating_level
        ):
            raise ValueError("MSOL cannot be below MRL")
        if self.minimum_regulating_level > self.maximum_export_level:
            raise ValueError("MRL cannot exceed MEL")


@dataclass(frozen=True)
class FrequencyResponseCapabilityBounds:
    minimum_poi_power: float
    maximum_poi_power: float

    def __post_init__(self) -> None:
        # finite POI range
        if not isfinite(self.minimum_poi_power) or not isfinite(
            self.maximum_poi_power
        ):
            raise ValueError("frequency-response bounds must be finite")
        if self.minimum_poi_power > self.maximum_poi_power:
            raise ValueError(
                "minimum POI power cannot exceed maximum POI power"
            )


@dataclass(frozen=True)
class FrequencyResponseReferenceState:
    capability_bounds: FrequencyResponseCapabilityBounds
    feasibility: FeasibilityResult


@dataclass(frozen=True)
class FrequencyResponseSample:
    elapsed_seconds: float
    frequency_hz: float
    feasibility: FeasibilityResult
    healthy_reference_state: FrequencyResponseReferenceState

    def __post_init__(self) -> None:
        # real time and frequency values only
        if not isfinite(self.elapsed_seconds):
            raise ValueError("elapsed_seconds must be finite")
        if not isfinite(self.frequency_hz):
            raise ValueError("frequency_hz must be finite")


@dataclass(frozen=True)
class FrequencyResponseWindow:
    samples: tuple[FrequencyResponseSample, ...]

    def __post_init__(self) -> None:
        # need a window, not a point
        if len(self.samples) < 2:
            raise ValueError(
                "a frequency-response window needs at least two samples"
            )
        times = [sample.elapsed_seconds for sample in self.samples]
        if abs(times[0]) > _COORDINATE_TOLERANCE:
            raise ValueError(
                "a frequency-response window must start at zero"
            )
        # ordered samples prevent negative intervals
        if any(
            (
                later <= earlier
                for earlier, later in zip(times, times[1:])
            )
        ):
            raise ValueError(
                "frequency-response times must be strictly increasing"
            )


@dataclass(frozen=True)
class FrequencyResponseAssessmentInterval:
    start_seconds: float
    end_seconds: float

    def __post_init__(self) -> None:
        # valid start and end only
        if not isfinite(self.start_seconds) or not isfinite(
            self.end_seconds
        ):
            raise ValueError("response interval limits must be finite")
        if (
            self.start_seconds < 0.0
            or self.end_seconds <= self.start_seconds
        ):
            raise ValueError(
                "a response interval needs 0 <= start < end"
            )


@dataclass(frozen=True)
class FrequencyResponseCase:
    case_id: str
    service: FrequencyResponseService
    baseline_power: float
    window: FrequencyResponseWindow
    fixed_high_loading_requirement_fraction: float | None = None
    minimum_applicable_loading_fraction: float | None = None
    maximum_applicable_loading_fraction: float | None = None
    assessment_intervals: tuple[
        FrequencyResponseAssessmentInterval, ...
    ] = ()

    def __post_init__(self) -> None:
        if not self.case_id:
            raise ValueError("case_id cannot be empty")
        if not isinstance(self.service, FrequencyResponseService):
            raise TypeError(
                "service must be a FrequencyResponseService"
            )
        if not isfinite(self.baseline_power):
            raise ValueError("baseline_power must be finite")
        # sort rules for custom intervals
        if self.assessment_intervals:
            z = tuple(
                sorted(
                    self.assessment_intervals,
                    key=lambda x: x.start_seconds,
                )
            )
            if z != self.assessment_intervals:
                raise ValueError("response intervals must be ordered")
            if any(
                (
                    later.start_seconds < earlier.end_seconds
                    for earlier, later in zip(z, z[1:])
                )
            ):
                raise ValueError("response intervals cannot overlap")
            # intervals must fit inside the case
            t1 = self.window.samples[-1].elapsed_seconds
            if any(
                (
                    interval.end_seconds
                    > t1 + _COORDINATE_TOLERANCE
                    for interval in z
                )
            ):
                raise ValueError(
                    "response interval exceeds the case window"
                )
        # loading limits come as a pair
        loading_limits = (
            self.minimum_applicable_loading_fraction,
            self.maximum_applicable_loading_fraction,
        )
        if (loading_limits[0] is None) != (loading_limits[1] is None):
            raise ValueError(
                "both loading applicability limits are required"
            )
        if (
            loading_limits[0] is not None
            and loading_limits[1] is not None
        ):
            if not 0.0 <= loading_limits[0] <= loading_limits[1] <= 1.0:
                raise ValueError(
                    "loading applicability must lie within [0, 1]"
                )


@dataclass(frozen=True)
class FrequencyResponseMissionContext(MissionContext):
    healthy_reference: FrequencyResponseReference
    cases: tuple[FrequencyResponseCase, ...]
    droop: float
    target_frequency_hz: float
    numerical_tolerance: float
    energy_tolerance: float
    time_tolerance_seconds: float

    def __post_init__(self) -> None:
        if not self.cases:
            raise ValueError(
                "Mission 4 requires frequency-response cases"
            )
        case_ids = [case.case_id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError(
                "frequency-response case IDs must be unique"
            )
        # duhen krejt services for m4
        services = {case.service for case in self.cases}
        missing = set(FrequencyResponseService) - services
        if missing:
            labels = ", ".join(
                sorted((service.value for service in missing))
            )
            raise ValueError(
                f"Mission 4 is missing service cases: {labels}"
            )
        # validate droop and target frequency
        if (
            not GRID_CODE_FSM_DROOP_MINIMUM
            <= self.droop
            <= GRID_CODE_FSM_DROOP_MAXIMUM
        ):
            raise ValueError("FSM droop must be in [0.03, 0.05]")
        if (
            not GRID_CODE_TARGET_FREQUENCY_MINIMUM_HZ
            <= self.target_frequency_hz
            <= GRID_CODE_TARGET_FREQUENCY_MAXIMUM_HZ
        ):
            raise ValueError(
                "target frequency must be in [49.90, 50.10] Hz"
            )
        # tolerances cannot be negative
        tolerances = (
            self.numerical_tolerance,
            self.energy_tolerance,
            self.time_tolerance_seconds,
        )
        if any(
            (not isfinite(value) or value < 0.0 for value in tolerances)
        ):
            raise ValueError(
                "Mission 4 tolerances must be non-negative"
            )
        for case in self.cases:
            if (
                case.baseline_power
                > self.healthy_reference.maximum_export_level
                + self.numerical_tolerance
            ):
                raise ValueError("case baseline cannot exceed MEL")
