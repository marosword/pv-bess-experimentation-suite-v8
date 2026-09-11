# Ramp profile, NESO (2026, BC1.A.1.5)
# elbows make this lovely
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from math import isfinite

_COMPARISON_TOLERANCE = 1e-12


class RampDirection(Enum):
    RUN_UP = "run_up"
    RUN_DOWN = "run_down"

    @property
    def sign(self) -> float:
        if self is RampDirection.RUN_UP:
            return 1.0
        return -1.0


@dataclass(frozen=True)
class RampRateCurve:
    direction: RampDirection
    rates_per_minute: tuple[float, ...]
    elbows: tuple[float, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.direction, RampDirection):
            raise TypeError("direction must be a RampDirection")
        # one rate per segment
        if not 1 <= len(self.rates_per_minute) <= 3:
            raise ValueError(
                "a ramp-rate curve requires one to three rates"
            )
        # rate changes need elbows
        if len(self.elbows) != len(self.rates_per_minute) - 1:
            raise ValueError("each rate change requires one elbow")
        if any(
            (
                not isfinite(rate) or rate <= 0.0
                for rate in self.rates_per_minute
            )
        ):
            raise ValueError("ramp rates must be positive")
        if any((not isfinite(elbow) for elbow in self.elbows)):
            raise ValueError("ramp elbows must be finite")
        # elbows must follow the ramp direction
        pairs = zip(self.elbows, self.elbows[1:])
        if self.direction is RampDirection.RUN_UP:
            if any((later <= earlier for earlier, later in pairs)):
                raise ValueError(
                    "run-up elbows must be strictly increasing"
                )
        elif any((later >= earlier for earlier, later in pairs)):
            raise ValueError(
                "run-down elbows must be strictly decreasing"
            )

    def segment_index(self, power: float) -> int:
        # find the active rate band
        if self.direction is RampDirection.RUN_UP:
            return sum(
                (
                    power >= elbow - _COMPARISON_TOLERANCE
                    for elbow in self.elbows
                )
            )
        return sum(
            (
                power <= elbow + _COMPARISON_TOLERANCE
                for elbow in self.elbows
            )
        )

    def rate_at(self, power: float) -> float:
        return self.rates_per_minute[self.segment_index(power)]

    def next_elbow(self, power: float) -> float | None:
        i = self.segment_index(power)
        if i >= len(self.elbows):
            return None
        return self.elbows[i]


@dataclass(frozen=True)
class RegisteredRampRates:
    run_up: RampRateCurve
    run_down: RampRateCurve

    def __post_init__(self) -> None:
        if self.run_up.direction is not RampDirection.RUN_UP:
            raise ValueError("run_up must use a run-up curve")
        if self.run_down.direction is not RampDirection.RUN_DOWN:
            raise ValueError("run_down must use a run-down curve")

    def curve_for(self, direction: RampDirection) -> RampRateCurve:
        if direction is RampDirection.RUN_UP:
            return self.run_up
        return self.run_down


@dataclass(frozen=True)
class RampTargetPoint:
    elapsed_minutes: float
    target_power: float


@dataclass(frozen=True)
class RampReferencePoint:
    elapsed_minutes: float
    target_power: float
    profile_power: float


@dataclass(frozen=True)
class RampReferenceSegment:
    direction: RampDirection
    start_power: float
    end_power: float
    declared_rate_per_minute: float
    expected_start_minutes: float
    expected_arrival_minutes: float
    ends_at_elbow: bool


@dataclass(frozen=True)
class RampReferenceProfile:
    points: tuple[RampReferencePoint, ...]


class RampProfileModel:
    def build(
        self,
        targets: tuple[RampTargetPoint, ...],
        rates: RegisteredRampRates,
        initial_power: float,
    ) -> RampReferenceProfile:
        if not targets:
            raise ValueError(
                "a ramp profile requires at least one target"
            )
        x0 = targets[0]
        # seed from initial power
        out = [
            RampReferencePoint(
                elapsed_minutes=x0.elapsed_minutes,
                target_power=x0.target_power,
                profile_power=initial_power,
            )
        ]
        P = initial_power
        # move through the timestamped targets
        for previous, target in zip(targets, targets[1:]):
            dt = target.elapsed_minutes - previous.elapsed_minutes
            if dt <= 0.0:
                raise ValueError(
                    'ramp target times must be increasing'
                )
            P = self.advance(
                P, target.target_power, dt, rates
            )
            out.append(
                RampReferencePoint(
                    elapsed_minutes=target.elapsed_minutes,
                    target_power=target.target_power,
                    profile_power=P,
                )
            )
        return RampReferenceProfile(points=tuple(out))

    def advance(
        self,
        start_power: float,
        target_power: float,
        duration_minutes: float,
        rates: RegisteredRampRates,
    ) -> float:
        if duration_minutes < 0.0:
            raise ValueError("duration_minutes cannot be negative")
        if duration_minutes == 0.0 or start_power == target_power:
            return start_power
        # up or down
        direction = self._direction(start_power, target_power)
        curve = rates.curve_for(direction)
        left = duration_minutes
        P = start_power
        # shkon segment pas segmenti se rate mundet me ndrru te elbow
        while left > _COMPARISON_TOLERANCE:
            rate = curve.rate_at(P)
            boundary = self._next_boundary(P, target_power, curve)
            distance = abs(boundary - P)
            if distance <= _COMPARISON_TOLERANCE:
                if boundary == target_power:
                    return target_power
                P = boundary
                continue
            t_edge = distance / rate
            if left + _COMPARISON_TOLERANCE >= t_edge:
                P = boundary
                left -= t_edge
                if boundary == target_power:
                    return target_power
            else:
                return P + direction.sign * rate * left
        return P

    def plan_segments(
        self,
        start_power: float,
        target_power: float,
        start_minutes: float,
        rates: RegisteredRampRates,
    ) -> tuple[RampReferenceSegment, ...]:
        if start_power == target_power:
            return ()
        direction = self._direction(start_power, target_power)
        curve = rates.curve_for(direction)
        out = []
        P = start_power
        t0 = start_minutes
        # keep each constant-rate segment separate
        while P != target_power:
            rate = curve.rate_at(P)
            boundary = self._next_boundary(P, target_power, curve)
            t1 = (
                t0 + abs(boundary - P) / rate
            )
            out.append(
                RampReferenceSegment(
                    direction=direction,
                    start_power=P,
                    end_power=boundary,
                    declared_rate_per_minute=rate,
                    expected_start_minutes=t0,
                    expected_arrival_minutes=t1,
                    ends_at_elbow=boundary != target_power,
                )
            )
            P = boundary
            t0 = t1
        return tuple(out)

    @staticmethod
    def _direction(
        start_power: float, target_power: float
    ) -> RampDirection:
        if target_power > start_power:
            return RampDirection.RUN_UP
        return RampDirection.RUN_DOWN

    @staticmethod
    def _next_boundary(
        power: float, target_power: float, curve: RampRateCurve
    ) -> float:
        # mos kalo elbow ose target
        elbow = curve.next_elbow(power)
        if elbow is None:
            return target_power
        if curve.direction is RampDirection.RUN_UP:
            if elbow < target_power - _COMPARISON_TOLERANCE:
                return elbow
        elif elbow > target_power + _COMPARISON_TOLERANCE:
            return elbow
        return target_power
