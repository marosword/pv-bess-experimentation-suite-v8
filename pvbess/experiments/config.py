# validation is beside the data, bit scattered
from __future__ import annotations
from dataclasses import dataclass
from math import isfinite
from typing import TypeAlias
from ..feasibility import FeasibilityParameters
from ..graph import PlantCapabilityParameters, ReactiveSupportMode
from ..missions import (
    BelowTwentyMode,
    DeclaredReactiveRequirement,
    FrequencyResponseAssessmentInterval,
    FrequencyResponseReference,
    FrequencyResponseService,
    PlantBoundaryLimits,
    PowerCapabilityRequest,
    ReactiveAssessmentScope,
    RegisteredRampRates,
    VoltageCapabilityRequest,
    VoltageReactiveRequirement,
)


@dataclass(frozen=True)
class AvailabilityInput:
    capability: PlantCapabilityParameters
    feasibility: FeasibilityParameters
    elapsed_hours_since_failure: float = 0.0
    station_dc_autonomy_hours: float | None = None

    def __post_init__(self) -> None:
        _require_nonnegative(
            self.elapsed_hours_since_failure,
            "elapsed_hours_since_failure",
        )
        # autonomy must stay positive
        if self.station_dc_autonomy_hours is not None:
            _require_positive(
                self.station_dc_autonomy_hours,
                "station_dc_autonomy_hours",
            )


@dataclass(frozen=True)
class ActivePowerScenarioPoint:
    elapsed_minutes: float
    setpoint_power: float
    availability: AvailabilityInput

    def __post_init__(self) -> None:
        _require_finite(self.elapsed_minutes, 'elapsed_minutes'); _require_finite(self.setpoint_power, "setpoint_power")


@dataclass(frozen=True)
class ActivePowerExperimentScenario:
    scenario_id: str
    points: tuple[ActivePowerScenarioPoint, ...]
    boundary: PlantBoundaryLimits
    reactive_support_mode: ReactiveSupportMode
    numerical_tolerance: float
    interval_average_samples: bool = False

    @property
    def mission_id(self) -> str:
        return "active_power_tracking"

    def __post_init__(self) -> None:
        _validate_scenario_id(self.scenario_id)
        # points stay in time order
        _validate_times(
            tuple((point.elapsed_minutes for point in self.points)),
            "active-power",
        )
        # initial storage stays fixed
        _validate_storage_trajectory_inputs(
            tuple((point.availability for point in self.points)),
            "active-power",
        )
        _require_nonnegative(
            self.numerical_tolerance, "numerical_tolerance"
        )


@dataclass(frozen=True)
class RampRateScenarioPoint:
    elapsed_minutes: float
    target_power: float
    availability: AvailabilityInput

    def __post_init__(self) -> None:
        _require_finite(self.elapsed_minutes, "elapsed_minutes")
        _require_finite(self.target_power, "target_power")


@dataclass(frozen=True)
class RampRateExperimentScenario:
    scenario_id: str
    points: tuple[RampRateScenarioPoint, ...]
    boundary: PlantBoundaryLimits
    reactive_support_mode: ReactiveSupportMode
    rates: RegisteredRampRates
    initial_profile_power: float
    power_tolerance: float
    step_power_tolerance: float
    energy_tolerance: float
    time_tolerance_minutes: float
    sample_interval_minutes: float

    @property
    def mission_id(self) -> str:
        return "ramp_profile_capability"

    @property
    def instruction_demanded(self) -> bool:
        # any target change starts M2
        return any(
            (
                abs(point.target_power - self.initial_profile_power)
                > self.power_tolerance
                for point in self.points
            )
        )

    def __post_init__(self) -> None:
        _validate_scenario_id(self.scenario_id)
        _validate_times(
            tuple((point.elapsed_minutes for point in self.points)),
            "ramp-rate",
            minimum_count=1,
        )
        _validate_storage_trajectory_inputs(
            tuple((point.availability for point in self.points)),
            "ramp-rate",
        )
        _require_finite(
            self.initial_profile_power, "initial_profile_power"
        )
        # all ramp tolerances stay nonnegative
        for value, label in (
            (self.power_tolerance, "power_tolerance"),
            (self.step_power_tolerance, "step_power_tolerance"),
            (self.energy_tolerance, "energy_tolerance"),
            (self.time_tolerance_minutes, "time_tolerance_minutes"),
        ):
            _require_nonnegative(value, label)
        _require_positive(
            self.sample_interval_minutes, "sample_interval_minutes"
        )
        times = tuple((point.elapsed_minutes for point in self.points))
        # gaps would skip part of the ramp
        if (
            len(times) > 1
            and max(
                (
                    later - earlier
                    for earlier, later in zip(times, times[1:])
                )
            )
            > self.sample_interval_minutes + 1e-12
        ):
            raise ValueError(
                "ramp sample spacing exceeds sample_interval_minutes"
            )
        # one point cannot form a ramp
        if len(self.points) == 1 and self.instruction_demanded:
            raise ValueError(
                "a demanded ramp requires at least two samples"
            )
        # targets stay inside POI limits
        powers = (
            self.initial_profile_power,
            *(point.target_power for point in self.points),
        )
        if any(
            (
                power < self.boundary.minimum_poi_power - 1e-12
                or power > self.boundary.maximum_poi_power + 1e-12
                for power in powers
            )
        ):
            raise ValueError(
                "ramp power lies outside the declared POI boundary"
            )


@dataclass(frozen=True)
class ReactivePowerExperimentScenario:
    scenario_id: str
    availability: AvailabilityInput
    boundary: PlantBoundaryLimits
    reactive_support_mode: ReactiveSupportMode
    maximum_capacity: float
    assessment_scope: ReactiveAssessmentScope
    power_requests: tuple[PowerCapabilityRequest, ...]
    voltage_active_power: float | None
    voltage_requests: tuple[VoltageCapabilityRequest, ...]
    voltage_requirements: tuple[VoltageReactiveRequirement, ...]
    below_twenty_mode: BelowTwentyMode
    numerical_tolerance: float
    full_absorbing_capability_to_20_percent: bool
    declared_below_twenty_requirements: tuple[
        DeclaredReactiveRequirement, ...
    ]

    @property
    def mission_id(self) -> str:
        return "reactive_power_capability"

    def __post_init__(self) -> None:
        _validate_scenario_id(self.scenario_id)
        _require_positive(self.maximum_capacity, "maximum_capacity")
        _require_nonnegative(
            self.numerical_tolerance, "numerical_tolerance"
        )
        # M3 needs at least one P-Q request
        if not self.power_requests:
            raise ValueError("power_requests cannot be empty")
        if not isinstance(
            self.assessment_scope, ReactiveAssessmentScope
        ):
            raise TypeError(
                "assessment_scope must be a ReactiveAssessmentScope"
            )
        # U-Q inputs travel together
        has_voltage_inputs = bool(
            self.voltage_requests or self.voltage_requirements
        )
        if (
            self.assessment_scope
            is ReactiveAssessmentScope.POWER_AND_VOLTAGE_ENVELOPES
        ):
            if self.voltage_active_power is None:
                raise ValueError(
                    "voltage-envelope active power is required"
                )
            _require_nonnegative(
                self.voltage_active_power, "voltage_active_power"
            )
            # the U-Q envelope uses maximum output
            if (
                abs(self.voltage_active_power - self.maximum_capacity)
                > self.numerical_tolerance
            ):
                raise ValueError(
                    "voltage envelope must be evaluated at Maximum Capacity"
                )
            if (
                not self.voltage_requests
                or not self.voltage_requirements
            ):
                raise ValueError(
                    "voltage-envelope slices cannot be empty"
                )
            if len(self.voltage_requests) != len(
                self.voltage_requirements
            ):
                raise ValueError(
                    "voltage requests and requirements must have equal length"
                )
            # capability and requirement voltages must align
            for request, requirement in zip(
                self.voltage_requests, self.voltage_requirements
            ):
                if (
                    abs(
                        request.voltage_per_unit
                        - requirement.voltage_per_unit
                    )
                    > self.numerical_tolerance
                ):
                    raise ValueError(
                        "voltage requests and requirements must use matching slices"
                    )
        # point-only mode carries no voltage data
        elif (
            self.voltage_active_power is not None or has_voltage_inputs
        ):
            raise ValueError(
                "power-only assessment cannot include voltage-envelope inputs"
            )


@dataclass(frozen=True)
class FrequencyResponseScenarioPoint:
    elapsed_seconds: float
    frequency_hz: float
    availability: AvailabilityInput

    def __post_init__(self) -> None:
        _require_nonnegative(self.elapsed_seconds, "elapsed_seconds")
        _require_positive(self.frequency_hz, "frequency_hz")


@dataclass(frozen=True)
class FrequencyResponseCaseScenario:
    case_id: str
    service: FrequencyResponseService
    baseline_power: float
    points: tuple[FrequencyResponseScenarioPoint, ...]
    fixed_high_loading_requirement_fraction: float | None
    assessment_intervals: tuple[
        FrequencyResponseAssessmentInterval, ...
    ] = ()
    minimum_applicable_loading_fraction: float | None = None
    maximum_applicable_loading_fraction: float | None = None

    def __post_init__(self) -> None:
        _validate_scenario_id(self.case_id)
        _require_finite(self.baseline_power, "baseline_power")
        _validate_times(
            tuple((point.elapsed_seconds for point in self.points)),
            f"frequency-response case {self.case_id}",
            minimum_count=2,
        )
        _validate_storage_trajectory_inputs(
            tuple((point.availability for point in self.points)),
            f"frequency-response case {self.case_id}",
        )
        # event timeline starts at zero
        if abs(self.points[0].elapsed_seconds) > 1e-12:
            raise ValueError(
                "a frequency-response case must start at zero"
            )
        declared = self.fixed_high_loading_requirement_fraction
        # declared response is a fraction
        if declared is not None and (not 0.0 <= declared <= 1.0):
            raise ValueError(
                "fixed_high_loading_requirement_fraction must be in [0, 1]"
            )
        loading_limits = (
            self.minimum_applicable_loading_fraction,
            self.maximum_applicable_loading_fraction,
        )
        # dy loading limits ose asnje
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
class FrequencyResponseExperimentScenario:
    scenario_id: str
    cases: tuple[FrequencyResponseCaseScenario, ...]
    boundary: PlantBoundaryLimits
    reactive_support_mode: ReactiveSupportMode
    healthy_reference: FrequencyResponseReference
    droop: float
    target_frequency_hz: float
    numerical_tolerance: float
    energy_tolerance: float
    time_tolerance_seconds: float
    allow_grid_import: bool

    @property
    def mission_id(self) -> str:
        return "frequency_response_resource_capability"

    def __post_init__(self) -> None:
        _validate_scenario_id(self.scenario_id)
        if not self.cases:
            raise ValueError("frequency-response cases cannot be empty")
        case_ids = [case.case_id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError(
                "frequency-response case IDs must be unique"
            )
        # every frequency service is required
        missing = set(FrequencyResponseService) - {
            case.service for case in self.cases
        }
        if missing:
            labels = ", ".join(
                sorted((service.value for service in missing))
            )
            raise ValueError(
                f"frequency-response services missing: {labels}"
            )
        _require_positive(self.droop, "droop")
        _require_positive(
            self.target_frequency_hz, "target_frequency_hz"
        )
        for value, label in (
            (self.numerical_tolerance, "numerical_tolerance"),
            (self.energy_tolerance, "energy_tolerance"),
            (self.time_tolerance_seconds, "time_tolerance_seconds"),
        ):
            _require_nonnegative(value, label)


MissionExperimentScenario: TypeAlias = (
    ActivePowerExperimentScenario
    | RampRateExperimentScenario
    | ReactivePowerExperimentScenario
    | FrequencyResponseExperimentScenario
)


def _validate_scenario_id(value: str) -> None:
    if not value:
        raise ValueError("scenario_id cannot be empty")


def _validate_times(
    values: tuple[float, ...], label: str, minimum_count: int = 1
) -> None:
    if len(values) < minimum_count:
        raise ValueError(
            f"{label} needs at least {minimum_count} sample(s)"
        )
    if any((not isfinite(value) for value in values)):
        raise ValueError(f"{label} times must be finite")
    if any(
        (later <= earlier for earlier, later in zip(values, values[1:]))
    ):
        raise ValueError(f"{label} times must be strictly increasing")


def _require_finite(value: float, label: str) -> None:
    if not isfinite(value):
        raise ValueError(f"{label} must be finite")


def _require_positive(value: float, label: str) -> None:
    _require_finite(value, label)
    if value <= 0.0:
        raise ValueError(f"{label} must be positive")


def _require_nonnegative(value: float, label: str) -> None:
    _require_finite(value, label)
    if value < 0.0:
        raise ValueError(f"{label} cannot be negative")


def _validate_storage_trajectory_inputs(
    points: tuple[AvailabilityInput, ...], label: str
) -> None:
    p0 = points[0].capability
    want = (
        p0.bess_energy_ratings,
        p0.bess_soc,
        p0.bess_min_soc,
        p0.bess_max_soc,
        p0.bess_soh,
    )
    # later energy comes from the solver
    for p in points[1:]:
        got = (
            p.capability.bess_energy_ratings,
            p.capability.bess_soc,
            p.capability.bess_min_soc,
            p.capability.bess_max_soc,
            p.capability.bess_soh,
        )
        if got != want:
            raise ValueError(
                f"{label} storage ratings and initial state must remain fixed; the solver calculates later branch energy"
            )
