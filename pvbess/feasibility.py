# battery math starts clean pastaj branch checks 
from __future__ import annotations

from dataclasses import dataclass; from enum import Enum; from math import isfinite


DEFAULT_MISSION_FEASIBILITY_TOLERANCE = 1e-06 # solver slop


class IntervalPowerModel(str,Enum): PIECEWISE_CONSTANT='piecewise_constant'; PIECEWISE_LINEAR="piecewise_linear"


@dataclass(frozen=True)
class FeasibilityParameters:
    energy_min:float; energy_max:float
    charge_efficiency:float; discharge_efficiency:float
    timestep_hours: float

    def __post_init__(self)->None: #housekeeping
        if self.energy_min > self.energy_max: raise ValueError('energy_min cannot exceed energy_max')
        if not 0.0 < self.charge_efficiency <= 1.0: raise ValueError("charge_efficiency must be in (0, 1]")
        if not 0.0 < self.discharge_efficiency <= 1.0: raise ValueError("discharge_efficiency must be in (0, 1]")
        if self.timestep_hours <= 0.0: raise ValueError("timestep_hours must be positive")


@dataclass(frozen=True)
class FeasibilityLimits:
    max_pv_power:float; max_charge_power:float; max_discharge_power:float
    minimum_poi_power: float
    maximum_poi_power: float


@dataclass(frozen=True)
class ConverterOperatingPoint:
    converter_id: str
    active_power: float
    apparent_power_rating: float


@dataclass(frozen=True)
class FeasibilityPoint:
    energy: float
    pv_power_used: float
    charge_power: float
    discharge_power: float
    converters: tuple[ConverterOperatingPoint, ...] = ()


@dataclass(frozen=True)
class ConstraintCheck:
    constraint_id:str; satisfied:bool


@dataclass(frozen=True)
class BranchEnergyResult:
    branch_id: str
    current_energy: float
    next_energy: float
    energy_capacity: float
    active_power: float = 0.0
    charge_efficiency: float = 1.0
    discharge_efficiency: float = 1.0


@dataclass(frozen=True)
class FeasibilityResult:
    feasible: bool
    poi_active_power: float
    current_energy: float
    next_energy: float
    timestep_hours: float
    checks: tuple[ConstraintCheck, ...]
    branch_energy: tuple[BranchEnergyResult, ...] = ()
    charge_power: float = 0.0
    discharge_power: float = 0.0
    charge_efficiency: float = 1.0
    discharge_efficiency: float = 1.0


@dataclass(frozen=True)
class FeasibilityTrajectorySample:
    elapsed_minutes: float
    feasibility: FeasibilityResult


@dataclass(frozen=True)
class FeasibilityTrajectoryAssessment:
    all_steps_physically_feasible:bool; success:bool


class FeasibilityTrajectoryModel:
    def assess(self,samples:tuple[FeasibilityTrajectorySample,...],
        energy_tolerance: float,
        time_tolerance_minutes: float,
        interval_power_model: IntervalPowerModel = IntervalPowerModel.PIECEWISE_CONSTANT,
    )->FeasibilityTrajectoryAssessment:
        if not samples: raise ValueError("a feasibility trajectory requires at least one sample")
        if energy_tolerance < 0.0 or time_tolerance_minutes < 0.0: raise ValueError("trajectory tolerances cannot be negative")
        if not isinstance(interval_power_model, IntervalPowerModel):
            raise TypeError(
                "interval_power_model must be an IntervalPowerModel"
            )
        ts=tuple(s.elapsed_minutes for s in samples)
        if any(not isfinite(t) for t in ts): raise ValueError("trajectory sample times must be finite")
        if any(
            b <= a for a, b in zip(ts, ts[1:])
        ):
            raise ValueError(
                "trajectory sample times must be strictly increasing"
            )
        if any(
            not isfinite(x)
            for s in samples
            for x in (
                s.feasibility.current_energy,
                s.feasibility.next_energy,
                s.feasibility.timestep_hours,
            )
        ):
            raise ValueError(
                "trajectory energy and timesteps must be finite"
            )
        # timestep edhe sample gap duhet me dale same se ndryshe energy shkon off
        timeok = all(
            abs(
                s.feasibility.timestep_hours * 60.0
                - (nxt.elapsed_minutes - s.elapsed_minutes)
            )
            <= time_tolerance_minutes
            for s, nxt in zip(samples, samples[1:])
        )
        # linear apo flat, ketu ndahet math se rampi nuk llogaritet si block
        if interval_power_model is IntervalPowerModel.PIECEWISE_LINEAR:
            (
                ee,
                be,
            ) = self._piecewise_linear_errors(samples)
        else:
            ee = tuple(
                s.feasibility.next_energy
                - nxt.feasibility.current_energy
                for s, nxt in zip(samples, samples[1:])
            )
            be = self._piecewise_constant_branch_errors(
                samples
            )
        # energy ska jump
        eok=all(
            abs(e) <= energy_tolerance for e in ee
        ); bok=all(
            abs(e) <= energy_tolerance for _, e in be
        ); n=len(samples)
        # linear continuity replaces solver next-energy checks
        endchecks = {"next_energy_minimum", "next_energy_maximum"}
        # check cdo limit
        ok = all(
            c.satisfied
            for i, s in enumerate(samples)
            for c in s.feasibility.checks
            if not self._excluded_next_energy_check(
                c.constraint_id,
                i,
                n,
                interval_power_model,
                endchecks,
            )
        )
        # point checks first, continuity after
        ans=FeasibilityTrajectoryAssessment(
            ok,
            ok
            and timeok
            and eok
            and bok,
        )
        return ans

    @staticmethod
    def _excluded_next_energy_check(
        constraint_id: str,
        index: int,
        sample_count: int,
        model: IntervalPowerModel,
        aggregate_ids: set[str],
    ) -> bool:
        yes = (
            constraint_id in aggregate_ids
            or constraint_id.startswith("next_bess_energy_")
        )
        return yes and (
            model is IntervalPowerModel.PIECEWISE_LINEAR
            or index == sample_count - 1
        )

    @staticmethod
    def _branch_maps(
        sample: FeasibilityTrajectorySample,
        following: FeasibilityTrajectorySample,
    ) -> tuple[
        dict[str, BranchEnergyResult], dict[str, BranchEnergyResult]
    ]:
        # match bess me id
        cur = {
            x.branch_id: x
            for x in sample.feasibility.branch_energy
        }
        nxt = {
            x.branch_id: x
            for x in following.feasibility.branch_energy
        }
        if not cur and not nxt:
            return {}, {}
        if set(cur) != set(nxt):
            raise ValueError('branch energy identities must remain fixed across a trajectory')
        return cur, nxt

    @classmethod
    def _piecewise_constant_branch_errors(
        cls, samples: tuple[FeasibilityTrajectorySample, ...]
    ) -> tuple[tuple[str, float], ...]:
        # flat mes dy pikave
        out = []
        for s, nxt in zip(samples, samples[1:]):
            cur, after = cls._branch_maps(s, nxt)
            out.extend(
                (
                    bid,
                    cur[bid].next_energy
                    - after[bid].current_energy,
                )
                for bid in sorted(cur)
            )
        return tuple(out)

    @classmethod
    def _piecewise_linear_errors(
        cls, samples: tuple[FeasibilityTrajectorySample, ...]
    ) -> tuple[tuple[float, ...], tuple[tuple[str, float], ...]]:
        # trapez per ramp
        ae = []
        be = []
        for s, nxt in zip(samples, samples[1:]):
            cur, after = cls._branch_maps(s, nxt)
            if cur:
                # rebuild branch endpoints
                guess = []
                for bid in sorted(cur):
                    x = cur[bid]
                    y = after[bid]
                    e2 = (
                        x.current_energy
                        + cls._linear_energy_change(
                            x.active_power,
                            y.active_power,
                            s.feasibility.timestep_hours,
                            x.charge_efficiency,
                            x.discharge_efficiency,
                        )
                    )
                    guess.append(e2)
                    be.append(
                        (
                            bid,
                            e2 - y.current_energy,
                        )
                    )
                ae.append(
                    sum(guess)
                    - nxt.feasibility.current_energy
                )
            else:
                # pa branch detail, use plant totals
                a0 = s.feasibility
                a1 = nxt.feasibility
                guess = (
                    a0.current_energy
                    + cls._linear_energy_change(
                        a0.discharge_power
                        - a0.charge_power,
                        a1.discharge_power
                        - a1.charge_power,
                        a0.timestep_hours,
                        a0.charge_efficiency,
                        a0.discharge_efficiency,
                    )
                )
                ae.append(
                    guess - a1.current_energy
                )
        return tuple(ae), tuple(be)

    @staticmethod
    def _linear_energy_change(
        start_power: float,
        end_power: float,
        duration_hours: float,
        charge_efficiency: float,
        discharge_efficiency: float,
    ) -> float:
        # plus = discharge
        if start_power >= 0.0 and end_power >= 0.0:
            return (
                -0.5
                * (start_power + end_power)
                * duration_hours
                / discharge_efficiency
            )
        if start_power <= 0.0 and end_power <= 0.0:
            return (
                -0.5
                * (start_power + end_power)
                * duration_hours
                * charge_efficiency
            )
        # split ketu per efficiency
        z = -start_power / (end_power - start_power)
        r0 = (
            -start_power / discharge_efficiency
            if start_power > 0.0
            else -start_power * charge_efficiency
        )
        r1 = (
            -end_power / discharge_efficiency
            if end_power > 0.0
            else -end_power * charge_efficiency
        )
        return (
            0.5
            * duration_hours
            * (
                r0 * z
                + r1 * (1.0 - z)
            )
        )


class PlantFeasibilityModel:
    def __init__(
        self,
        numerical_tolerance: float = DEFAULT_MISSION_FEASIBILITY_TOLERANCE,
    ) -> None:
        if numerical_tolerance < 0.0: raise ValueError("numerical_tolerance cannot be negative")
        self._tolerance=numerical_tolerance

    def evaluate(
        self,
        parameters: FeasibilityParameters,
        limits: FeasibilityLimits,
        point: FeasibilityPoint,
    ) -> FeasibilityResult:
        tol=self._tolerance
        # net power ne POI
        Ppoi=( point.pv_power_used
            + point.discharge_power
            - point.charge_power )
        # charge adds energy, discharge removes it
        E1=(point.energy
            + parameters.charge_efficiency
            * point.charge_power
            * parameters.timestep_hours
            - point.discharge_power
            / parameters.discharge_efficiency
            * parameters.timestep_hours)
        # limits one by one
        cc = [ #housekeeping
            ConstraintCheck(
                'pv_power_minimum', point.pv_power_used >= -tol
            ),
            ConstraintCheck("pv_power_maximum",
                point.pv_power_used <= limits.max_pv_power + tol),
            ConstraintCheck(
                "current_energy_minimum",
                point.energy >= parameters.energy_min - tol,
            ),
            ConstraintCheck(
                "current_energy_maximum",
                point.energy <= parameters.energy_max + tol,
            ),
            ConstraintCheck(
                "next_energy_minimum",
                E1 >= parameters.energy_min - tol,
            ),
            ConstraintCheck(
                "next_energy_maximum",
                E1 <= parameters.energy_max + tol,
            ),
            ConstraintCheck('charge_power_minimum',
                            point.charge_power >= -tol),
            ConstraintCheck(
                "charge_power_maximum",
                point.charge_power
                <= limits.max_charge_power + tol,
            ),
            ConstraintCheck("discharge_power_minimum",point.discharge_power >= -tol),
            ConstraintCheck(
                "discharge_power_maximum",
                point.discharge_power
                <= limits.max_discharge_power + tol,
            ),
            ConstraintCheck(
                "exclusive_charge_or_discharge",
                not (
                    point.charge_power > tol
                    and point.discharge_power > tol
                ),
            ),
            ConstraintCheck(
                "poi_power_minimum",
                Ppoi >= limits.minimum_poi_power - tol,
            ),
            ConstraintCheck(
                "poi_power_maximum",
                Ppoi <= limits.maximum_poi_power + tol,
            ),
        ]
        # converter circle checks
        cc.extend(
            ConstraintCheck(
                f"converter_rating:{x.converter_id}",
                x.active_power**2
                <= x.apparent_power_rating**2 + tol,
            )
            for x in point.converters
        )
        checks0=tuple(cc)
        result=FeasibilityResult(
            all(x.satisfied for x in checks0),
            Ppoi,
            point.energy,
            E1,
            parameters.timestep_hours,
            checks0,
            charge_power=point.charge_power,
            discharge_power=point.discharge_power,
            charge_efficiency=parameters.charge_efficiency,
            discharge_efficiency=parameters.discharge_efficiency,
        )
        return result
