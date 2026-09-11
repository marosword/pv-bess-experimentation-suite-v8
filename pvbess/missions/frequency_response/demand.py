# Frequency demand, NESO (2026, ECC.6.3.7.3.3)
# mind the limits -> 1 dmeand
from __future__ import annotations
from dataclasses import dataclass
from .models import (
    FrequencyResponseCapabilityBounds,
    FrequencyResponseReference,
)
from .profiles import (
    high_capability_fraction,
    primary_secondary_capability_fraction,
)
from .requirements import (
    GRID_CODE_FSM_RESPONSE_RANGE_FRACTION,
    GRID_CODE_HIGH_START_SECONDS,
    GRID_CODE_NOMINAL_FREQUENCY_HZ,
    GRID_CODE_PRIMARY_END_SECONDS,
    GRID_CODE_PRIMARY_START_SECONDS,
    GRID_CODE_REFERENCE_FREQUENCY_DEVIATION_HZ,
    GRID_CODE_SECONDARY_END_SECONDS,
    GRID_CODE_SECONDARY_START_SECONDS,
    FrequencyResponseService,
)

_INTERNAL_TOLERANCE = 1e-12


@dataclass(frozen=True)
class FrequencyResponseDemand:
    assessed: bool
    requirement_defined: bool
    inapplicability_reason: str | None
    frequency_deviation_hz: float
    droop_request_power: float
    minimum_profile_demand_power: float
    reference_headroom_power: float
    required_response_power: float
    requested_poi_power: float


def assessment_interval(
    service: FrequencyResponseService, final_elapsed_seconds: float
) -> tuple[float, float]:
    # each service has its own response window
    if service is FrequencyResponseService.PRIMARY: return (GRID_CODE_PRIMARY_START_SECONDS, GRID_CODE_PRIMARY_END_SECONDS)
    if service is FrequencyResponseService.SECONDARY:
        return ( GRID_CODE_SECONDARY_START_SECONDS,
                        GRID_CODE_SECONDARY_END_SECONDS )
    return (GRID_CODE_HIGH_START_SECONDS, final_elapsed_seconds)


def calculate_frequency_response_demand(
    *,
    service: FrequencyResponseService,
    elapsed_seconds: float,
    final_elapsed_seconds: float,
    frequency_hz: float,
    baseline_power: float,
    reference: FrequencyResponseReference,
    bounds: FrequencyResponseCapabilityBounds,
    droop: float,
    target_frequency_hz: float,
    declared_above_95_fraction: float | None,
    time_tolerance_seconds: float,
    assessment_intervals: tuple[tuple[float, float], ...] = (),
    minimum_applicable_loading_fraction: float | None = None,
    maximum_applicable_loading_fraction: float | None = None,
) -> FrequencyResponseDemand:
    # custom windows override the default
    ii = assessment_intervals or (
        assessment_interval(service, final_elapsed_seconds),
    )
    # only points inside them count
    use = any(
        (
            a - time_tolerance_seconds
            <= elapsed_seconds
            <= b + time_tolerance_seconds
            for a, b in ii
        )
    )
    # signed frequency error
    df = frequency_hz - target_frequency_hz
    # signal direction must match the service
    if use:
        if (
            service
            in (
                FrequencyResponseService.PRIMARY,
                FrequencyResponseService.SECONDARY,
            )
            and df >= -_INTERNAL_TOLERANCE
        ):
            raise ValueError(
                "underfrequency service needs an underfrequency signal"
            )
        if (
            service is FrequencyResponseService.HIGH
            and df <= _INTERNAL_TOLERANCE
        ):
            raise ValueError(
                "high service needs an overfrequency signal"
            )
    # keep undefined cases out of success counts
    why = frequency_response_applicability_reason(
        baseline_power=baseline_power,
        reference=reference,
        declared_above_95_fraction=declared_above_95_fraction,
        minimum_applicable_loading_fraction=minimum_applicable_loading_fraction,
        maximum_applicable_loading_fraction=maximum_applicable_loading_fraction,
    )
    if why is not None:
        return _undefined_demand(
            use, df, baseline_power, why
        )
    # loading is based on plant capacity
    ll = baseline_power / reference.maximum_capacity; mrl = (
            reference.minimum_regulating_level / reference.maximum_capacity)
    # low f means power up
    if service in (
        FrequencyResponseService.PRIMARY,
        FrequencyResponseService.SECONDARY,
    ):
        mf = primary_secondary_capability_fraction(
            ll, declared_above_95_fraction
        )
        room = bounds.maximum_poi_power - baseline_power; sgn = 1.0
    else:
        # high f means power down
        mf = high_capability_fraction(
            ll,
            mrl,
            declared_above_95_fraction,
        )
        room = baseline_power - bounds.minimum_poi_power; sgn = -1.0
    # dont guess response above 0.95
    if mf is None:
        return _undefined_demand(
            use,
            df,
            baseline_power,
            'plant_specific_response_above_95_percent_not_declared',
        )
    # droop del first pastaj e presim me limits, ketu mos i perziej
    dr = (
        -reference.maximum_capacity
        / (droop * GRID_CODE_NOMINAL_FREQUENCY_HZ)
        * df
    )
    # cap scaling at the reference event
    scale = min(
        abs(df) / GRID_CODE_REFERENCE_FREQUENCY_DEVIATION_HZ, 1.0
    )
    # scale the profile floor with event size
    floor = (
        mf * reference.maximum_capacity * scale
    )
    # wrong direction earns no response
    dd = (max(dr, 0.0)
     if sgn > 0.0
                             else max(-dr, 0.0))
    # cap at the FSM range
    dd = min(
        dd,
        GRID_CODE_FSM_RESPONSE_RANGE_FRACTION
        * reference.maximum_capacity,
    )
    # enforce the stricter response floor
    P_req = max(
        floor, min(dd, max(room, 0.0))
    )
    ans = FrequencyResponseDemand(
        assessed=use,
        requirement_defined=True,
        inapplicability_reason=None,
        frequency_deviation_hz=df,
        droop_request_power=dr,
        minimum_profile_demand_power=floor,
        reference_headroom_power=room,
        required_response_power=P_req,
        requested_poi_power=baseline_power + sgn * P_req,
    )
    return ans


def frequency_response_applicability_reason(
    *,
    baseline_power: float,
    reference: FrequencyResponseReference,
    declared_above_95_fraction: float | None,
    minimum_applicable_loading_fraction: float | None = None,
    maximum_applicable_loading_fraction: float | None = None,
) -> str | None:
    # jashte loading rules stays undefined
    ll = baseline_power / reference.maximum_capacity
    if (
        ll > 0.95 + _INTERNAL_TOLERANCE
        and declared_above_95_fraction is None
    ):
        return "plant_specific_response_above_95_percent_not_declared"
    if (
        minimum_applicable_loading_fraction is not None
        and maximum_applicable_loading_fraction is not None
        and (
            not minimum_applicable_loading_fraction
            - _INTERNAL_TOLERANCE
            <= ll
            <= maximum_applicable_loading_fraction + _INTERNAL_TOLERANCE
        )
    ):
        return "baseline_outside_declared_loading_applicability"
    if (
        baseline_power
        < reference.minimum_stable_operating_level - _INTERNAL_TOLERANCE
    ):
        return "baseline_below_declared_msol"
    return None


def _undefined_demand(
    assessed: bool, deviation: float, baseline_power: float, reason: str
) -> FrequencyResponseDemand:
    # keep the reason, zero unused fields
    return FrequencyResponseDemand(
        assessed=assessed,
        requirement_defined=False,
        inapplicability_reason=reason,
        frequency_deviation_hz=deviation,
        droop_request_power=0.0,
        minimum_profile_demand_power=0.0,
        reference_headroom_power=0.0,
        required_response_power=0.0,
        requested_poi_power=baseline_power,
    )
