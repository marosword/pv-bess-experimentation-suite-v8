# Build M1-M4 experiment cases
from __future__ import annotations
from math import sqrt

from ...feasibility import DEFAULT_MISSION_FEASIBILITY_TOLERANCE
from ...missions import (
    FrequencyResponseAssessmentInterval,
    FrequencyResponseReference,
    FrequencyResponseService,
    GRID_CODE_MAXIMUM_MRL_FRACTION,
    GRID_CODE_MAXIMUM_MSOL_FRACTION,
    GRID_CODE_FIGURE_REACTIVE_FRACTION,
    GRID_CODE_RESPONSE_RESTORATION_MINUTES,
    RampDirection,
    RampRateCurve,
    RegisteredRampRates,
)
from .baseline import (
    RAMP_RATE_SWEEP_PER_UNIT_PER_MINUTE,
    REFERENCE_RAMP_RATE_PER_UNIT_PER_MINUTE,
)
from .coverage import complete_hourly_intervals
from .mission_adapters import (
    ChronologicalFrequencyResponseScenarioBuilder,
    ChronologicalRampRateScenarioBuilder,
    ChronologicalReactivePowerScenarioBuilder,
    FrequencyCaseTemplate,
)
from .models import HealthyChronology
from .sweeps import ControlledSweepVariant, SweepFamily

# tolerances 
TOLERANCE = DEFAULT_MISSION_FEASIBILITY_TOLERANCE; COORDINATE_TOLERANCE = 1e-09
STATIC_REACTIVE_CASE = "mission_3_declared_envelope_grid"
REACTIVE_POI_APPARENT_POWER_REFERENCE_RATIO = sqrt(
    1.0 + GRID_CODE_FIGURE_REACTIVE_FRACTION**2
)
# keto tre are the declared cases for now
REACTIVE_POI_APPARENT_POWER_RATIO_CASES = (
    REACTIVE_POI_APPARENT_POWER_REFERENCE_RATIO,
    1.1,
    1.2,
)
# avoid plant specific freq rules
FREQUENCY_MINIMUM_INVARIANT_LOADING = 0.7
FREQUENCY_MAXIMUM_DEFINED_LOADING = 0.95
FREQUENCY_HIGH_STUDY_SECONDS = 30.0 * 60.0


def _ramp_rates(rate_per_minute: float) -> RegisteredRampRates:
    # same rate up and down
    return RegisteredRampRates(
        run_up=RampRateCurve(RampDirection.RUN_UP, (rate_per_minute,)),
        run_down=RampRateCurve(
            RampDirection.RUN_DOWN, (rate_per_minute,)
        ),
    )


def _ramp_builder(
    specification_id: str,
    target_power: float,
    rate_per_minute: float,
) -> ChronologicalRampRateScenarioBuilder:
    # one builder for each target-rate pair
    return ChronologicalRampRateScenarioBuilder(
        specification_id,
        target_power,
        _ramp_rates(rate_per_minute),
        TOLERANCE,
    )


def _reactive_builder(
    declared: bool,
    poi_apparent_power_ratio: float = REACTIVE_POI_APPARENT_POWER_REFERENCE_RATIO,
) -> ChronologicalReactivePowerScenarioBuilder:
    # choose current point or declared envelope
    return ChronologicalReactivePowerScenarioBuilder(
        (
            "reactive_envelope_grid_"
            if declared
            else "reactive_current_point_"
        )
        + _reactive_ratio_case_id(poi_apparent_power_ratio),
        poi_apparent_power_ratio,
        declared,
    )


def _reactive_ratio_case_id(ratio: float) -> str:
    # keep case names stable
    if ratio == REACTIVE_POI_APPARENT_POWER_REFERENCE_RATIO:
        return "requirement_boundary"
    return f"design_margin_{ratio:.2f}".replace(".", "p")


def _frequency_case(
    case_id: str,
    service: FrequencyResponseService,
    event_frequency: float,
    start_seconds: float,
    end_seconds: float,
    *,
    assessment_intervals: tuple[
        FrequencyResponseAssessmentInterval, ...
    ] = (),
) -> FrequencyCaseTemplate:
    # healthy start, then hold the frequency event
    return FrequencyCaseTemplate(
        case_id=case_id,
        service=service,
        points=(
            (0.0, 50.0),
            (start_seconds, event_frequency),
            (end_seconds, event_frequency),
        ),
        assessment_intervals=assessment_intervals,
    )


def _frequency_repeatability_case() -> FrequencyCaseTemplate:
    # provo primary prap after recovery
    deadline_seconds = GRID_CODE_RESPONSE_RESTORATION_MINUTES * 60.0
    activation_seconds = 10.0
    # second event waits for recovery
    repeated_response_start = deadline_seconds + activation_seconds
    return FrequencyCaseTemplate(
        case_id="primary_repeatability_20min",
        service=FrequencyResponseService.PRIMARY,
        points=(
            (0.0, 50.0),
            (10.0, 49.5),
            (30.0, 49.5),
            (40.0, 50.0),
            (deadline_seconds, 50.0),
            (repeated_response_start, 49.5),
            (repeated_response_start + 20.0, 49.5),
            (repeated_response_start + 30.0, 50.0),
        ),
        assessment_intervals=(
            FrequencyResponseAssessmentInterval(10.0, 30.0),
            FrequencyResponseAssessmentInterval(
                repeated_response_start, repeated_response_start + 20.0
            ),
        ),
    )


def _frequency_builder() -> (
    ChronologicalFrequencyResponseScenarioBuilder
):
    # all four frequency cases
    return ChronologicalFrequencyResponseScenarioBuilder(
        cases=(
            _frequency_case(
                "primary",
                FrequencyResponseService.PRIMARY,
                49.5,
                10.0,
                30.0,
            ),
            _frequency_case(
                "secondary",
                FrequencyResponseService.SECONDARY,
                49.5,
                30.0,
                1800.0,
            ),
            _frequency_case(
                "high",
                FrequencyResponseService.HIGH,
                50.5,
                10.0,
                FREQUENCY_HIGH_STUDY_SECONDS,
            ),
            _frequency_repeatability_case(),
        ),
        healthy_reference=FrequencyResponseReference(
            maximum_capacity=1.0,
            maximum_export_level=1.0,
            minimum_regulating_level=GRID_CODE_MAXIMUM_MRL_FRACTION,
            minimum_stable_operating_level=GRID_CODE_MAXIMUM_MSOL_FRACTION,
        ),
        droop=0.04,
        target_frequency_hz=50.0,
        numerical_tolerance=TOLERANCE,
        energy_tolerance=TOLERANCE,
        time_tolerance_seconds=COORDINATE_TOLERANCE,
        minimum_loading_fraction=FREQUENCY_MINIMUM_INVARIANT_LOADING,
        maximum_loading_fraction=FREQUENCY_MAXIMUM_DEFINED_LOADING,
    )


def _temporal_mission_builders():
    out = {"mission_4_frequency": _frequency_builder()}
    out["mission_3_chronological_p_slice"] = _reactive_builder(
        False,
        REACTIVE_POI_APPARENT_POWER_REFERENCE_RATIO,
    )
    # both directions at every tested rate
    for d0, pp in (("up", 1.0), ("down", 0.0)):
        for rr in RAMP_RATE_SWEEP_PER_UNIT_PER_MINUTE:
            tag = f"{rr:.2f}".replace(".", "p")
            key = f"ramp_{d0}_rate_{tag}"
            out[f"mission_2_{key}"] = _ramp_builder(
                key, pp, rr
            )
    return out


def _temporal_builders_for_variant(
    variant: ControlledSweepVariant,
    builders: dict[str, object],
) -> dict[str, object]:
    if not variant.runs_dynamic_missions:
        return {}
    # isolate ramp rate from other sweeps
    if variant.family is SweepFamily.BASELINE:
        return builders
    rr = (
        f"{REFERENCE_RAMP_RATE_PER_UNIT_PER_MINUTE:.2f}".replace(
            ".", "p"
        )
    )
    return {
        key: thing
        for key, thing in builders.items()
        if not key.startswith("mission_2_")
        or key.endswith(f"_rate_{rr}")
    }


def _declared_reactive_envelope_builders():
    out = {}
    # three POI rating cases
    for x in REACTIVE_POI_APPARENT_POWER_RATIO_CASES:
        tag = _reactive_ratio_case_id(x)
        key = (
            STATIC_REACTIVE_CASE
            if x == REACTIVE_POI_APPARENT_POWER_REFERENCE_RATIO
            else f"{STATIC_REACTIVE_CASE}_{tag}"
        )
        out[key] = _reactive_builder(True, x)
    return out


def _smoke_onset(chronology: HealthyChronology) -> int:
    # fixed noon smoke case
    return next(
        (
            ii
            for ii, p in enumerate(chronology.points)
            if p.timestamp_utc.month == 6
            and p.timestamp_utc.day == 15
            and (p.timestamp_utc.hour == 12)
        )
    )


def _onset_plan(
    chronology: HealthyChronology,
    active_terminal_hours: int,
    builders: dict[str, object],
    smoke: bool,
    *,
    active_comparison_terminal_hours: int | None = None,
    selected_onset_indices: tuple[int, ...] | None = None,
) -> dict[str, tuple[int, ...]]:
    if smoke and selected_onset_indices is not None:
        raise ValueError(
            "smoke and declared onset sampling cannot be combined"
        )
    # sampled onsets stay ordered and unique
    if selected_onset_indices is not None:
        if not selected_onset_indices:
            raise ValueError("declared onset sampling cannot be empty")
        if (
            tuple(sorted(selected_onset_indices))
            != selected_onset_indices
        ):
            raise ValueError("declared onset indices must be ordered")
        if len(selected_onset_indices) != len(
            set(selected_onset_indices)
        ):
            raise ValueError("declared onset indices must be unique")
    smoke0 = _smoke_onset(chronology) if smoke else None
    stop0 = (
        active_terminal_hours
        if active_comparison_terminal_hours is None
        else active_comparison_terminal_hours
    )
    if stop0 < active_terminal_hours:
        raise ValueError(
            "active comparison window cannot be shorter than the failure window"
        )
    # m1 needs the full comparison window
    aa = complete_hourly_intervals(
        len(chronology.points), stop0
    )
    if smoke:
        if smoke0 not in aa:
            raise RuntimeError("smoke onset cannot complete Mission 1")
        aa = (smoke0,)
    elif selected_onset_indices is not None:
        _require_onset_support(
            selected_onset_indices, aa, "Mission 1"
        )
        aa = selected_onset_indices
    out = {"mission_1_active_power": aa}
    # M2-M4 start from the full hourly index
    mm = tuple(range(len(chronology.points)))
    for key in builders:
        if smoke:
            if smoke0 not in mm:
                raise RuntimeError(
                    f"smoke onset cannot complete {key}"
                )
            mm = (smoke0,)
        elif selected_onset_indices is not None:
            _require_onset_support(
                selected_onset_indices, mm, key
            )
            mm = selected_onset_indices
        out[key] = mm
    return out


def _require_onset_support(
    selected: tuple[int, ...], eligible: tuple[int, ...], label: str
) -> None:
    ok = frozenset(eligible)
    # every case keeps the same onsets
    bad = tuple(
        (x for x in selected if x not in ok)
    )
    if bad:
        raise ValueError(
            f"{label} cannot support {len(bad)} declared sampled onsets"
        )
