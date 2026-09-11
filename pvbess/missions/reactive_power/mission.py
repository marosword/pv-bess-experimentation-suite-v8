# Reactive capability check, NESO (2026, ECC.6.3.2.4)
# q check, pak P-Q pak U-Q dhe worst wins
from __future__ import annotations

from math import inf

from ..base import Mission, MissionContext, MissionResult
from .models import (
    PowerReactiveCapabilityPoint,
    ReactiveAssessmentScope,
    ReactiveCapabilityRange,
    ReactivePowerMissionContext,
    VoltageReactiveCapabilityPoint,
)
from .requirements import (
    GRID_CODE_LOW_POWER_FRACTION,
    GRID_CODE_ZERO_TRANSFER_FRACTION,
    BelowTwentyMode,
    DeclaredReactiveRequirement,
    power_reactive_bounds,
)


_COORDINATE_TOLERANCE = 1e-09


class ReactivePowerCapabilityMission(Mission):
    @property
    def mission_id(self) -> str:
        return 'reactive_power_capability'

    def evaluate(self, context: MissionContext) -> MissionResult:
        if not isinstance(context, ReactivePowerMissionContext):
            raise TypeError(
                "ReactivePowerCapabilityMission requires ReactivePowerMissionContext"
            )
        # P-Q first, pastaj U-Q
        out = [self._power_reactive(context)]
        if (
            context.assessment_scope
            is ReactiveAssessmentScope.POWER_AND_VOLTAGE_ENVELOPES
        ):
            out.append(self._voltage_reactive(context))
        # merr worst one, nese nje curve nuk del krejt mission fail
        worst = min(m for m, _ in out)
        return MissionResult(
            mission_id=self.mission_id,
            demanded=True,
            success=all(ok for _, ok in out),
            value=worst / context.maximum_capacity,
            threshold=0.0,
        )

    def _power_reactive(
        self, context: ReactivePowerMissionContext
    ) -> tuple[float, bool]:
        out = []
        # one failed slice fails the envelope
        for pt in context.power_capability_points:
            L = (
                pt.active_power / context.maximum_capacity
            )
            # low power has plant specific rules
            if L < GRID_CODE_LOW_POWER_FRACTION:
                if (
                    context.below_twenty_mode
                    is BelowTwentyMode.ZERO_TRANSFER
                ):
                    # zero transfer is not the full range
                    out.append(
                        _zero_transfer(
                            pt.capability,
                            GRID_CODE_ZERO_TRANSFER_FRACTION
                            * context.maximum_capacity,
                            context.numerical_tolerance,
                        )
                    )
                else:
                    # declared limits replace the generic curve
                    req = _find_declared_requirement(
                        pt.active_power,
                        context.declared_below_twenty_requirements,
                    )
                    if req is None:
                        raise RuntimeError(
                            "validated declared requirement is missing"
                        )
                    out.append(
                        _containment(
                            pt.capability,
                            req.minimum_reactive_power,
                            req.maximum_reactive_power,
                            context.numerical_tolerance,
                        )
                    )
            else:
                # grid-code envelope above 20 percent
                Qreq = power_reactive_bounds(
                    context.maximum_capacity,
                    L,
                    context.full_absorbing_capability_to_20_percent,
                )
                out.append(
                    _containment(
                        pt.capability,
                        Qreq[0],
                        Qreq[1],
                        context.numerical_tolerance,
                    )
                )
        return _combine(out)

    def _voltage_reactive(
        self, context: ReactivePowerMissionContext
    ) -> tuple[float, bool]:
        out = []
        # voltage cases stay discrete
        for req in context.voltage_requirements:
            # match each request at the same voltage
            pt = _find_voltage_capability(
                req.voltage_per_unit,
                context.voltage_capability_points,
            )
            if pt is None:
                raise ValueError(
                    f"no capability point supplied for voltage {req.voltage_per_unit:g} p.u."
                )
            out.append(
                _containment(
                    pt.capability,
                    req.minimum_reactive_power,
                    req.maximum_reactive_power,
                    context.numerical_tolerance,
                )
            )
        return _combine(out)


def _containment(
    capability: ReactiveCapabilityRange,
    required_minimum: float,
    required_maximum: float,
    tolerance: float,
) -> tuple[float, bool]:
    # no operating point means failure
    if not capability.operating_point_feasible:
        return -inf, False
    Qmin = capability.minimum_reactive_power; Qmax = capability.maximum_reactive_power
    if Qmin is None or Qmax is None:
        raise RuntimeError("validated capability limits are missing")
    # margin from both Q boundaries
    m = min(
        required_minimum - Qmin,
        Qmax - required_maximum,
    )
    return m, m >= -tolerance


def _zero_transfer(
    capability: ReactiveCapabilityRange,
    tolerance: float,
    numerical_tolerance: float,
) -> tuple[float, bool]:
    if not capability.operating_point_feasible:
        return -inf, False
    Qmin = capability.minimum_reactive_power; Qmax = capability.maximum_reactive_power
    if Qmin is None or Qmax is None:
        raise RuntimeError("validated capability limits are missing")
    # how far capability sits from zero
    if Qmin <= 0.0 <= Qmax:
        d = 0.0
    elif Qmin > 0.0:
        d = Qmin
    else:
        d = abs(Qmax)
    m = tolerance - d
    return m, m >= -numerical_tolerance


def _combine(
    assessments: list[tuple[float, bool]]
) -> tuple[float, bool]:
    if not assessments:
        raise ValueError(
            "an envelope assessment requires at least one point"
        )
    # worst point sets the result
    return min(m for m, _ in assessments), all(
        ok for _, ok in assessments
    )


def _find_declared_requirement(
    active_power: float,
    requirements: tuple[DeclaredReactiveRequirement, ...],
) -> DeclaredReactiveRequirement | None:
    return next(
        (
            x
            for x in requirements
            if abs(x.active_power - active_power)
            <= _COORDINATE_TOLERANCE
        ),
        None,
    )


def _find_voltage_capability(
    voltage: float, points: tuple[VoltageReactiveCapabilityPoint, ...]
) -> VoltageReactiveCapabilityPoint | None:
    return next(
        (
            x
            for x in points
            if abs(x.voltage_per_unit - voltage)
            <= _COORDINATE_TOLERANCE
        ),
        None,
    )
