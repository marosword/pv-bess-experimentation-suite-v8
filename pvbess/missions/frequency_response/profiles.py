# Loading response curve, NESO (2026, Fig. ECC.A.3.1)
# three bits of the loading curve, kept "ndarazi"
from __future__ import annotations
from math import isfinite
from .requirements import (
    GRID_CODE_FSM_RESPONSE_RANGE_FRACTION,
    GRID_CODE_MAXIMUM_MRL_FRACTION,
)

_HIGH_RESPONSE_FULL_LOAD_FRACTION = 0.7
_PRIMARY_SECONDARY_FLAT_END_FRACTION = 0.8
_DECLARED_HIGH_LOADING_START_FRACTION = 0.95


def primary_secondary_capability_fraction(
    load_fraction: float,
    declared_above_95_fraction: float | None = None,
) -> float | None:
    _validate_load_fraction(load_fraction)
    if load_fraction > _DECLARED_HIGH_LOADING_START_FRACTION:
        return _declared_high_loading_fraction(
            declared_above_95_fraction
        )
    if load_fraction <= _PRIMARY_SECONDARY_FLAT_END_FRACTION:
        return GRID_CODE_FSM_RESPONSE_RANGE_FRACTION
    return 0.5 * (1.0 - load_fraction)


def high_capability_fraction(
    load_fraction: float,
    minimum_regulating_fraction: float,
    declared_above_95_fraction: float | None = None,
) -> float | None:
    _validate_load_fraction(load_fraction)
    if (
        not isfinite(minimum_regulating_fraction)
        or not 0.0
        <= minimum_regulating_fraction
        <= GRID_CODE_MAXIMUM_MRL_FRACTION
    ):
        raise ValueError('MRL fraction must be in the Grid Code range')
    if load_fraction < minimum_regulating_fraction:
        raise ValueError("load fraction cannot be below MRL")
    if load_fraction > _DECLARED_HIGH_LOADING_START_FRACTION:
        return _declared_high_loading_fraction(
            declared_above_95_fraction
        )
    if load_fraction >= _HIGH_RESPONSE_FULL_LOAD_FRACTION:
        return GRID_CODE_FSM_RESPONSE_RANGE_FRACTION
    dx = (
        _HIGH_RESPONSE_FULL_LOAD_FRACTION - minimum_regulating_fraction
    )
    u = (load_fraction - minimum_regulating_fraction) / dx
    return GRID_CODE_FSM_RESPONSE_RANGE_FRACTION * u


def _validate_load_fraction(load_fraction: float) -> None:
    if not isfinite(load_fraction) or not 0.0 <= load_fraction <= 1.0: raise ValueError(
            "load fraction must be in [0, 1]")


def _declared_high_loading_fraction(
    value: float | None,
) -> float | None:
    if value is None:
        return None
    if not isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError(
            "declared high-loading capability must be in [0, 1]"
        )
    return value
