# Change one parameter per sweep
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from .baseline import (
    BASELINE_BESS_DURATION_HOURS,
    BASELINE_FAILURE_DURATION_HOURS,
    BASELINE_SMOOTHING_WINDOW_HOURS,
    BASELINE_STATION_DC_AUTONOMY_HOURS,
    BESS_DURATION_SWEEP_HOURS,
    FAILURE_DURATION_SWEEP_HOURS,
    SMOOTHING_WINDOW_SWEEP_HOURS,
    STATION_DC_AUTONOMY_STUDY_DURATION_HOURS,
    STATION_DC_AUTONOMY_SWEEP_HOURS,
    build_declared_baseline_configuration,
)
from .models import ChronologicalBaselineConfiguration


class SweepFamily(str, Enum):
    BASELINE = 'baseline'
    BESS_DURATION = "bess_duration"
    SMOOTHING_WINDOW = "smoothing_window"
    FAILURE_DURATION = 'failure_duration'
    STATION_DC_AUTONOMY = "station_dc_autonomy"


@dataclass(frozen=True)
class ControlledSweepVariant:
    variant_id: str
    family: SweepFamily
    bess_duration_hours: float
    smoothing_window_hours: int
    failure_duration_hours: int
    station_dc_autonomy_hours: float

    @property
    def runs_dynamic_missions(self) -> bool:
        return self.family not in {
            SweepFamily.FAILURE_DURATION,
            SweepFamily.STATION_DC_AUTONOMY,
        }

    @property
    def runs_declared_reactive_envelope(self) -> bool:
        return self.family is SweepFamily.BASELINE

    def baseline_configuration(
        self,
    ) -> ChronologicalBaselineConfiguration:
        return build_declared_baseline_configuration(
            bess_duration_hours=self.bess_duration_hours,
            smoothing_window_hours=self.smoothing_window_hours,
            station_dc_autonomy_hours=self.station_dc_autonomy_hours,
        )


def build_controlled_sweep(
    family: SweepFamily,
) -> tuple[ControlledSweepVariant, ...]:
    # baseline value gets left out of the side sweeps
    # each family changes one parameter
    if family is SweepFamily.BASELINE:
        vv = (
            _variant(
                "baseline",
                family,
                BASELINE_BESS_DURATION_HOURS,
                BASELINE_SMOOTHING_WINDOW_HOURS,
                BASELINE_FAILURE_DURATION_HOURS,
                BASELINE_STATION_DC_AUTONOMY_HOURS,
            ),
        )
    elif family is SweepFamily.BESS_DURATION:
        vv = tuple(
            (
                _variant(
                    f"bess_duration_{_number_id(x)}h",
                    family,
                    x,
                    BASELINE_SMOOTHING_WINDOW_HOURS,
                    BASELINE_FAILURE_DURATION_HOURS,
                    BASELINE_STATION_DC_AUTONOMY_HOURS,
                )
                for x in BESS_DURATION_SWEEP_HOURS
                if x != BASELINE_BESS_DURATION_HOURS
            )
        )
    elif family is SweepFamily.SMOOTHING_WINDOW:
        vv = tuple(
            (
                _variant(
                    f"smoothing_window_{x}h",
                    family,
                    BASELINE_BESS_DURATION_HOURS,
                    x,
                    BASELINE_FAILURE_DURATION_HOURS,
                    BASELINE_STATION_DC_AUTONOMY_HOURS,
                )
                for x in SMOOTHING_WINDOW_SWEEP_HOURS
                if x != BASELINE_SMOOTHING_WINDOW_HOURS
            )
        )
    elif family is SweepFamily.FAILURE_DURATION:
        vv = tuple(
            (
                _variant(
                    f"failure_duration_{x}h",
                    family,
                    BASELINE_BESS_DURATION_HOURS,
                    BASELINE_SMOOTHING_WINDOW_HOURS,
                    x,
                    BASELINE_STATION_DC_AUTONOMY_HOURS,
                )
                for x in FAILURE_DURATION_SWEEP_HOURS
                if x != BASELINE_FAILURE_DURATION_HOURS
            )
        )
    else:
        vv = tuple(
            (
                _variant(
                    f"station_dc_autonomy_{_number_id(x)}h",
                    family,
                    BASELINE_BESS_DURATION_HOURS,
                    BASELINE_SMOOTHING_WINDOW_HOURS,
                    STATION_DC_AUTONOMY_STUDY_DURATION_HOURS,
                    x,
                )
                for x in STATION_DC_AUTONOMY_SWEEP_HOURS
            )
        )
    return vv


def build_controlled_design() -> tuple[ControlledSweepVariant, ...]:
    return tuple(
        x
        for ff in (
            SweepFamily.BASELINE,
            SweepFamily.BESS_DURATION,
            SweepFamily.SMOOTHING_WINDOW,
            SweepFamily.FAILURE_DURATION,
        )
        for x in build_controlled_sweep(ff)
    )


def build_station_dc_autonomy_design() -> (
    tuple[ControlledSweepVariant, ...]
):
    return build_controlled_sweep(SweepFamily.STATION_DC_AUTONOMY)


def _variant(
    variant_id: str,
    family: SweepFamily,
    bess_duration_hours: float,
    smoothing_window_hours: int,
    failure_duration_hours: int,
    station_dc_autonomy_hours: float,
) -> ControlledSweepVariant:
    return ControlledSweepVariant(
        variant_id=variant_id,
        family=family,
        bess_duration_hours=bess_duration_hours,
        smoothing_window_hours=smoothing_window_hours,
        failure_duration_hours=failure_duration_hours,
        station_dc_autonomy_hours=station_dc_autonomy_hours,
    )


def _number_id(value: float) -> str:
    return f"{value:g}".replace(".", "p")
