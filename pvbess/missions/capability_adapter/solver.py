# BESS dispatch MILP, Alpizar-Castillo et al. (2023)
# bounds then rows then highs - untidy
from __future__ import annotations
from collections.abc import Iterable; from dataclasses import dataclass; from math import inf
import warnings
import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_matrix, csr_matrix, vstack
from ...feasibility import IntervalPowerModel
from .models import (
    BranchDispatch,
    BranchEnergyState,
    CapabilityAvailabilityPoint,
    CapabilityDispatch,
    CapabilityStatePoint,
    DispatchTrajectorySolution,
    PlantBoundaryLimits,
    PowerTrajectoryRequirement,
)

_LEXICOGRAPHIC_OBJECTIVE_TOLERANCE = 1e-09


@dataclass(frozen=True)
class _BranchLimit:
    branch_id: str
    maximum_power: float
    energy_capacity: float = 0.0
    initial_energy: float = 0.0


@dataclass(frozen=True)
class _StepLimits:
    pv: tuple[_BranchLimit, ...]
    charge: tuple[_BranchLimit, ...]
    discharge: tuple[_BranchLimit, ...]


@dataclass(frozen=True)
class _SparseConstraints:
    matrix: csr_matrix
    lower: np.ndarray
    upper: np.ndarray

    def append(
        self,
        coefficients: tuple[tuple[int, float], ...],
        lower: float,
        upper: float,
    ) -> _SparseConstraints:
        # append without rebuilding dense matrices
        cc = [
            c for c, x in coefficients if x != 0.0
        ]
        vv = [x for _, x in coefficients if x != 0.0]
        rr = csr_matrix(
            (vv, ([0] * len(cc), cc)),
            shape=(1, self.matrix.shape[1]),
        )
        return _SparseConstraints(
            matrix=vstack((self.matrix, rr), format="csr"),
            lower=np.append(self.lower, lower),
            upper=np.append(self.upper, upper),
        )


class _ConstraintBuilder:
    def __init__(self, variable_count: int) -> None:
        self._variable_count = variable_count; self._rows: list[int] = []; self._columns: list[int] = []
        self._values: list[float] = []; self._lower: list[float] = []; self._upper: list[float] = []

    def add(
        self,
        coefficients: Iterable[tuple[int, float]],
        lower: float,
        upper: float,
    ) -> None:
        # zeros do not need storing
        rr = len(self._lower)
        for c, x in coefficients:
            if x == 0.0:
                continue
            self._rows.append(rr); self._columns.append(c); self._values.append(x)
        self._lower.append(lower)
        self._upper.append(upper)

    def build(self) -> _SparseConstraints:
        # csr is faster
        mm = coo_matrix(
            (self._values, (self._rows, self._columns)),
            shape=(len(self._lower), self._variable_count),
        ).tocsr()
        mm.sum_duplicates()
        return _SparseConstraints(
            matrix=mm,
            lower=np.asarray(self._lower),
            upper=np.asarray(self._upper),
        )


@dataclass(frozen=True)
class _VariableIndex:
    sample_count: int
    pv_count: int
    bess_count: int
    terminal_interval: bool = False

    @property
    def energy_state_count(self) -> int:
        # duhet edhe nje energy state ne fund se last interval harxhon energy
        return self.sample_count + int(self.terminal_interval)

    @property
    def pv_offset(self) -> int:
        return 0

    @property
    def charge_offset(self) -> int:
        return self.sample_count * self.pv_count

    @property
    def discharge_offset(self) -> int:
        return self.charge_offset + self.sample_count * self.bess_count

    @property
    def energy_offset(self) -> int:
        return (
            self.discharge_offset + self.sample_count * self.bess_count
        )

    @property
    def mode_offset(self) -> int:
        return (
            self.energy_offset
            + self.energy_state_count * self.bess_count
        )

    @property
    def deviation_offset(self) -> int:
        return self.mode_offset + self.sample_count

    @property
    def size(self) -> int:
        return self.maximum_deviation_offset + 1

    @property
    def maximum_deviation_offset(self) -> int:
        return self.deviation_offset + self.sample_count

    def pv(self, sample: int, branch: int) -> int:
        return self.pv_offset + sample * self.pv_count + branch

    def charge(self, sample: int, branch: int) -> int:
        return self.charge_offset + sample * self.bess_count + branch

    def discharge(self, sample: int, branch: int) -> int:
        return self.discharge_offset + sample * self.bess_count + branch

    def energy(self, sample: int, branch: int) -> int:
        return self.energy_offset + sample * self.bess_count + branch

    def mode(self, sample: int) -> int:
        return self.mode_offset + sample

    def deviation(self, sample: int) -> int:
        return self.deviation_offset + sample

    def maximum_deviation(self) -> int:
        return self.maximum_deviation_offset


class DispatchFeasibilitySolver:
    def __init__(self) -> None:
        self._tolerance = 1e-09

    def solve(
        self,
        availability: tuple[CapabilityAvailabilityPoint, ...],
        requirements: tuple[PowerTrajectoryRequirement, ...],
        boundary: PlantBoundaryLimits,
        initial_energy: float,
        interval_power_model: IntervalPowerModel = IntervalPowerModel.PIECEWISE_CONSTANT,
        *,
        terminal_interval: bool = False,
        minimize_maximum_deviation: bool = False,
        lexicographic_tiebreak: bool = True,
        feasibility_only: bool = False,
        export_only_fixed_direction: bool = False,
    ) -> DispatchTrajectorySolution:
        if not availability: raise ValueError("a dispatch search needs at least one point")
        if len(availability) != len(requirements):
            raise ValueError(
                "availability and requirements must have equal length"
            )
        if not isinstance(interval_power_model, IntervalPowerModel):
            raise TypeError(
                "interval_power_model must be an IntervalPowerModel"
            )
        # a held endpoint needs no next sample
        if (
            terminal_interval
            and interval_power_model
            is not IntervalPowerModel.PIECEWISE_CONSTANT
        ):
            raise ValueError(
                "terminal_interval is only defined for interval-average power"
            )
        if feasibility_only and minimize_maximum_deviation:
            raise ValueError(
                "feasibility_only cannot quantify maximum deviation"
            )
        if feasibility_only and lexicographic_tiebreak:
            raise ValueError(
                "feasibility_only cannot request a dispatch tie-break"
            )
        # fixed export keeps the oracle monotone
        if export_only_fixed_direction and (not feasibility_only):
            raise ValueError(
                "fixed export direction is only valid for classification"
            )
        if (
            export_only_fixed_direction
            and boundary.minimum_poi_power < -self._tolerance
        ):
            raise ValueError(
                "fixed export direction requires a nonnegative POI boundary"
            )
        # one milp layout needs stable branch order
        step_limits = tuple(
            (self._step_limits(point) for point in availability)
        )
        self._validate_branch_structure(step_limits)
        first_parameters = availability[0].feasibility_parameters
        if (
            not first_parameters.energy_min - self._tolerance
            <= initial_energy
            <= first_parameters.energy_max + self._tolerance
        ):
            return self._failure("initial_energy_outside_bounds")
        # avoid conflicting initial energy states
        E0 = sum(
            (
                branch.initial_energy
                for branch in step_limits[0].discharge
            )
        )
        if abs(initial_energy - E0) > self._tolerance:
            raise ValueError(
                "initial_energy must equal the sum of graph-conditioned branch energies"
            )
        # save milp calls for coupled cases
        effective_requirements = []; fixed_export_power: list[float] = []
        for index, (requirement, limits) in enumerate(
            zip(requirements, step_limits)
        ):
            parameters = availability[index].feasibility_parameters
            branch_capacity = sum(
                (item.energy_capacity for item in limits.charge)
            )
            if (
                parameters.energy_min
                > branch_capacity + self._tolerance
                or parameters.energy_max < -self._tolerance
            ):
                return self._failure(
                    "energy_bounds_incompatible_with_surviving_branches"
                )
            # demand and poi limits must overlap
            minimum = max(requirement.minimum_poi_power, boundary.minimum_poi_power); maximum = min(
                    requirement.maximum_poi_power,
                                        boundary.maximum_poi_power)
            if minimum > maximum + self._tolerance:
                return self._failure("requirement_outside_poi_boundary")
            if export_only_fixed_direction:
                fixed_export_power.append(minimum); maximum = minimum
            # this screen does not test stored energy
            maximum_export = sum(
                (item.maximum_power for item in limits.pv)
            ) + sum((item.maximum_power for item in limits.discharge))
            minimum_export = -sum(
                (item.maximum_power for item in limits.charge)
            )
            if (
                maximum < minimum_export - self._tolerance
                or minimum > maximum_export + self._tolerance
            ):
                return self._failure("insufficient_instantaneous_power")
            effective_requirements.append((minimum, maximum))
        # offsets keep every variable index stable
        index = _VariableIndex(
            sample_count=len(availability),
            pv_count=len(step_limits[0].pv),
            bess_count=len(step_limits[0].charge),
            terminal_interval=terminal_interval,
        )
        # scale kete se highs nuk i pelqen kur energy numbers dalin shume larg
        Eunit = self._energy_unit_hours(availability, index)
        lower_bounds, upper_bounds, integrality = self._variable_bounds(
            step_limits,
            index,
            Eunit,
            tuple(fixed_export_power)
            if export_only_fixed_direction
            else None,
        )
        constraints = self._constraints(
            availability,
            requirements,
            tuple(effective_requirements),
            step_limits,
            index,
            interval_power_model,
            Eunit,
        )
        # mission error stays the main objective
        obj = np.zeros(index.size)
        if not feasibility_only:
            if minimize_maximum_deviation: obj[index.maximum_deviation()] = 1.0
            else:
                for sample in range(index.sample_count):
                    obj[index.deviation(sample)] = 1.0
        # find the best tracking result first
        first = self._run_milp(
            obj,
            integrality,
            lower_bounds,
            upper_bounds,
            constraints,
        )
        # instant power can pass while energy fails
        if first is None:
            return self._failure(
                "insufficient_branch_energy_over_horizon"
            )
        solution = (first)
        if lexicographic_tiebreak:
            if minimize_maximum_deviation: best_deviation = first[index.maximum_deviation()]
            else:
                best_deviation = sum(
                    (
                        first[index.deviation(sample)]
                        for sample in range(index.sample_count)
                    )
                )
            if minimize_maximum_deviation:
                deviation_coefficients = (
                    (index.maximum_deviation(), 1.0),
                )
            else:
                deviation_coefficients = tuple(
                    (
                        (index.deviation(sample), 1.0)
                        for sample in range(index.sample_count)
                    )
                )
            # dont trade tracking for the tie break
            constrained_optimum = constraints.append(
                deviation_coefficients, -inf, best_deviation
            )
            # prefer less cycling between equal solutions
            cycling_objective = np.zeros(index.size)
            for sample in range(index.sample_count):
                weight = self._cycling_weight(
                    availability,
                    sample,
                    interval_power_model,
                    index.terminal_interval,
                )
                for branch in range(index.bess_count):
                    cycling_objective[
                        index.charge(sample, branch)
                    ] = weight
                    cycling_objective[
                        index.discharge(sample, branch)
                    ] = weight
            second = self._run_milp(
                cycling_objective,
                integrality,
                lower_bounds,
                upper_bounds,
                constrained_optimum,
            )
            if second is not None:
                if minimize_maximum_deviation:
                    second_deviation = second[index.maximum_deviation()]
                else:
                    second_deviation = sum(
                        (
                            second[index.deviation(sample)]
                            for sample in range(index.sample_count)
                        )
                    )
                # mos e prish tracking for the tie break
                if (
                    second_deviation
                    <= best_deviation
                    + _LEXICOGRAPHIC_OBJECTIVE_TOLERANCE
                ):
                    solution = second
        states = tuple(
            (
                self._build_state(
                    availability[sample],
                    step_limits[sample],
                    index,
                    solution,
                    sample,
                    Eunit,
                )
                for sample in range(index.sample_count)
            )
        )
        return DispatchTrajectorySolution(
            True,
            states,
            None,
        )

    def _step_limits(
        self, point: CapabilityAvailabilityPoint
    ) -> _StepLimits:
        # availability cannot exceed hardware rating
        return _StepLimits(
            pv=tuple(
                (
                    _BranchLimit(
                        branch.branch_id,
                        min(
                            branch.active_power_dispatchable,
                            branch.converter_rating,
                        ),
                    )
                    for branch in point.snapshot.pv_branches
                )
            ),
            charge=tuple(
                (
                    _BranchLimit(
                        branch.branch_id,
                        min(
                            branch.charge_power_dispatchable,
                            branch.converter_rating,
                        ),
                        branch.energy_capacity,
                        branch.usable_energy,
                    )
                    for branch in point.snapshot.bess_branches
                )
            ),
            discharge=tuple(
                (
                    _BranchLimit(
                        branch.branch_id,
                        min(
                            branch.discharge_power_dispatchable,
                            branch.converter_rating,
                        ),
                        branch.energy_capacity,
                        branch.usable_energy,
                    )
                    for branch in point.snapshot.bess_branches
                )
            ),
        )

    def _validate_branch_structure(
        self, limits: tuple[_StepLimits, ...]
    ) -> None:
        # branch order duhet same cdo step se variables lidhen me index
        p0 = tuple((x.branch_id for x in limits[0].pv))
        b0 = tuple(
            (x.branch_id for x in limits[0].charge)
        )
        e0 = tuple(
            (x.energy_capacity for x in limits[0].charge)
        )
        for z in limits:
            if (
                tuple((x.branch_id for x in z.pv))
                != p0
            ):
                raise ValueError(
                    "PV branch identities cannot change within a search"
                )
            if (
                tuple((x.branch_id for x in z.charge))
                != b0
            ):
                raise ValueError(
                    "BESS branch identities cannot change within a search"
                )
            if (
                tuple((x.branch_id for x in z.discharge))
                != b0
            ):
                raise ValueError(
                    "charge and discharge branch identities must match"
                )
            # one run cannot change installed storage
            cap = tuple(
                (x.energy_capacity for x in z.charge)
            )
            if any(
                (
                    abs(a - b) > self._tolerance
                    for a, b in zip(
                        cap, e0
                    )
                )
            ):
                raise ValueError(
                    "one dispatch experiment must use one fixed BESS failure configuration"
                )

    def _variable_bounds(
        self,
        limits: tuple[_StepLimits, ...],
        index: _VariableIndex,
        energy_unit_hours: float,
        fixed_poi_power: tuple[float, ...] | None = None,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        if (
            fixed_poi_power is not None
            and len(fixed_poi_power) != index.sample_count
        ):
            raise ValueError("fixed POI power must cover every sample")
        lo = np.zeros(index.size)
        hi = np.full(index.size, inf)
        ii = np.zeros(index.size, dtype=int)
        # physical limits become solver bounds
        for k, z in enumerate(limits):
            for j, x in enumerate(z.pv):
                hi[index.pv(k, j)] = x.maximum_power
            for j, x in enumerate(z.charge):
                hi[index.charge(k, j)] = x.maximum_power
                hi[index.discharge(k, j)] = z.discharge[
                    j
                ].maximum_power
                hi[index.energy(k, j)] = (
                    x.energy_capacity / energy_unit_hours
                )
            m = index.mode(k)
            # one mode blocks simultaneous charge and discharge
            if fixed_poi_power is None:
                hi[m] = 1.0
                ii[m] = 1
            else:
                pmax = sum(
                    (x.maximum_power for x in z.pv)
                )
                cm = float(
                    fixed_poi_power[k]
                    <= pmax + self._tolerance
                )
                lo[m] = cm
                hi[m] = cm
        # final interval still needs an energy limit
        if index.terminal_interval:
            for j, x in enumerate(limits[-1].charge):
                hi[index.energy(index.sample_count, j)] = (
                    x.energy_capacity / energy_unit_hours
                )
        # starting energy stays fixed
        for j, x in enumerate(limits[0].charge):
            v = index.energy(0, j)
            e = x.initial_energy / energy_unit_hours
            lo[v] = e
            hi[v] = e
        return (lo, hi, ii)

    def _constraints(
        self,
        availability: tuple[CapabilityAvailabilityPoint, ...],
        requirements: tuple[PowerTrajectoryRequirement, ...],
        effective_requirements: tuple[tuple[float, float], ...],
        limits: tuple[_StepLimits, ...],
        index: _VariableIndex,
        interval_power_model: IntervalPowerModel,
        energy_unit_hours: float,
    ) -> _SparseConstraints:
        constraints = _ConstraintBuilder(index.size)
        for sample, (point, requirement, effective, step) in enumerate(
            zip(
                availability,
                requirements,
                effective_requirements,
                limits,
            )
        ):
            # charging reduces exported power
            poi = self._poi_coefficients(index, sample)
            constraints.add(poi, effective[0], effective[1])
            constraints.add(
                (*poi, (index.deviation(sample), -1.0)),
                -inf,
                requirement.preferred_poi_power,
            )
            constraints.add(
                (*poi, (index.deviation(sample), 1.0)),
                requirement.preferred_poi_power,
                inf,
            )
            constraints.add(
                (
                    (index.deviation(sample), 1.0),
                    (index.maximum_deviation(), -1.0),
                ),
                -inf,
                0.0,
            )
            # block cycling between bess branches
            for branch, item in enumerate(step.charge):
                constraints.add(
                    (
                        (index.charge(sample, branch), 1.0),
                        (index.mode(sample), -item.maximum_power),
                    ),
                    -inf,
                    0.0,
                )
                discharge_item = step.discharge[branch]
                constraints.add(
                    (
                        (index.discharge(sample, branch), 1.0),
                        (
                            index.mode(sample),
                            discharge_item.maximum_power,
                        ),
                    ),
                    -inf,
                    discharge_item.maximum_power,
                )
            # plant energy limits cover all branches
            parameters = point.feasibility_parameters
            constraints.add(
                tuple(
                    (
                        (index.energy(sample, branch), 1.0)
                        for branch in range(index.bess_count)
                    )
                ),
                parameters.energy_min / energy_unit_hours,
                parameters.energy_max / energy_unit_hours,
            )
            if sample == index.sample_count - 1 and (
                not index.terminal_interval
            ):
                continue
            for branch in range(index.bess_count):
                interval_fraction = (
                    0.5
                    if interval_power_model
                    is IntervalPowerModel.PIECEWISE_LINEAR
                    else 1.0
                )
                integration_weight = (
                    parameters.timestep_hours * interval_fraction
                )
                energy_coefficient = (
                    energy_unit_hours / integration_weight
                )
                charge_coefficient = -parameters.charge_efficiency; discharge_coefficient = (
                        1.0 / parameters.discharge_efficiency)
                # each interval starts where the last ended
                energy_balance = [
                    (
                        index.energy(sample + 1, branch),
                        energy_coefficient,
                    ),
                    (index.energy(sample, branch), -energy_coefficient),
                    (index.charge(sample, branch), charge_coefficient),
                    (
                        index.discharge(sample, branch),
                        discharge_coefficient,
                    ),
                ]
                if (
                    interval_power_model
                    is IntervalPowerModel.PIECEWISE_LINEAR
                ):
                    # linear ramps need trapezoidal energy
                    energy_balance.extend(
                        (
                            (
                                index.charge(sample + 1, branch),
                                charge_coefficient,
                            ),
                            (
                                index.discharge(sample + 1, branch),
                                discharge_coefficient,
                            ),
                        )
                    )
                constraints.add(energy_balance, 0.0, 0.0)
                if (
                    interval_power_model
                    is IntervalPowerModel.PIECEWISE_LINEAR
                ):
                    constraints.add(
                        (
                            (index.charge(sample, branch), 1.0),
                            (
                                index.mode(sample + 1),
                                -step.charge[branch].maximum_power,
                            ),
                        ),
                        -inf,
                        0.0,
                    )
                    constraints.add(
                        (
                            (index.discharge(sample, branch), 1.0),
                            (
                                index.mode(sample + 1),
                                step.discharge[branch].maximum_power,
                            ),
                        ),
                        -inf,
                        step.discharge[branch].maximum_power,
                    )
        if index.terminal_interval:
            terminal_parameters = availability[
                            -1
                                ].feasibility_parameters
            constraints.add(
                tuple(
                    (
                        (index.energy(index.sample_count, branch), 1.0)
                        for branch in range(index.bess_count)
                    )
                ),
                terminal_parameters.energy_min / energy_unit_hours,
                terminal_parameters.energy_max / energy_unit_hours,
            )
        return constraints.build()

    @staticmethod
    def _energy_unit_hours(
        availability: tuple[CapabilityAvailabilityPoint, ...],
        index: _VariableIndex,
    ) -> float:
        n = (
            index.sample_count
            if index.terminal_interval
            else index.sample_count - 1
        )
        if n <= 0:
            return 1.0
        # convert the solver energy scale back
        return sum(
            (
                x.feasibility_parameters.timestep_hours
                for x in availability[:n]
            )
        )

    @staticmethod
    def _cycling_weight(
        availability: tuple[CapabilityAvailabilityPoint, ...],
        sample: int,
        interval_power_model: IntervalPowerModel,
        terminal_interval: bool,
    ) -> float:
        # weight cycling by interval duration
        if (
            interval_power_model
            is IntervalPowerModel.PIECEWISE_CONSTANT
        ):
            if sample == len(availability) - 1 and (
                not terminal_interval
            ):
                return 0.0
            return availability[
                sample
            ].feasibility_parameters.timestep_hours
        if len(availability) == 1:
            return 0.0
        if sample == 0:
            return (
                0.5
                * availability[0].feasibility_parameters.timestep_hours
            )
        p0 = availability[
            sample - 1
        ].feasibility_parameters.timestep_hours
        if sample == len(availability) - 1:
            return 0.5 * p0
        p1 = availability[
            sample
        ].feasibility_parameters.timestep_hours
        return 0.5 * (p0 + p1)

    def _poi_coefficients(
        self, index: _VariableIndex, sample: int
    ) -> tuple[tuple[int, float], ...]:
        return tuple(
            (
                (index.pv(sample, j), 1.0)
                for j in range(index.pv_count)
            )
        ) + tuple(
            (
                z
                for j in range(index.bess_count)
                for z in (
                    (index.charge(sample, j), -1.0),
                    (index.discharge(sample, j), 1.0),
                )
            )
        )

    def _run_milp(
        self,
        objective: np.ndarray,
        integrality: np.ndarray,
        lower_bounds: np.ndarray,
        upper_bounds: np.ndarray,
        constraints: _SparseConstraints,
    ) -> np.ndarray | None:
        # same case should return the same witness
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message="Unrecognized options detected: (?=\\{[^}]*'mip_feasibility_tolerance')(?=\\{[^}]*'primal_feasibility_tolerance')(?=\\{[^}]*'random_seed')(?=\\{[^}]*'parallel')(?=\\{[^}]*'threads')\\{(?:'(?:mip_feasibility_tolerance|primal_feasibility_tolerance|random_seed|parallel|threads)'(?:, )?)+\\}\\. These will be passed to HiGHS verbatim\\.", #do not change package level, logs will explode
                category=RuntimeWarning,
            )
            res = milp(
                c=objective,
                integrality=integrality,
                bounds=Bounds(lower_bounds, upper_bounds),
                constraints=LinearConstraint(
                    constraints.matrix,
                    constraints.lower,
                    constraints.upper,
                ),
                options={
                    "presolve": True,
                    "mip_rel_gap": 0.0,
                    "primal_feasibility_tolerance": self._tolerance,
                    "mip_feasibility_tolerance": self._tolerance,
                    "random_seed": 0,
                    "threads": 1,
                    "parallel": False,
                },
            )
        # infeasible is a normal mission outcome
        if res.status == 2:
            return None
        if not res.success or res.x is None:
            raise RuntimeError(
                f"branch dispatch solver failed: {res.message}"
            )
        # kontrollo solution against our tolerance
        maximum_violation = (
            DispatchFeasibilitySolver._maximum_violation(
                res.x,
                integrality,
                lower_bounds,
                upper_bounds,
                constraints,
            )
        )
        if maximum_violation > self._tolerance:
            raise RuntimeError(
                f"branch dispatch witness exceeds the declared feasibility tolerance: {maximum_violation:g} > {self._tolerance:g}"
            )
        return res.x

    @staticmethod
    def _maximum_violation(
        values: np.ndarray,
        integrality: np.ndarray,
        lower_bounds: np.ndarray,
        upper_bounds: np.ndarray,
        constraints: _SparseConstraints,
    ) -> float:
        vv = [0.0]; fl = np.isfinite(lower_bounds); fu = np.isfinite(upper_bounds)
        if fl.any():
            vv.append(
                float(
                    np.max(
                        lower_bounds[fl]
                        - values[fl]
                    )
                )
            )
        if fu.any():
            vv.append(
                float(
                    np.max(
                        values[fu]
                        - upper_bounds[fu]
                    )
                )
            )
        # solver success still gets checked here
        mv = constraints.matrix @ values; rl = constraints.lower
        ru = constraints.upper; frl = np.isfinite(rl); fru = np.isfinite(ru)
        if frl.any():
            vv.append(
                float(
                    np.max(
                        rl[frl]
                        - mv[frl]
                    )
                )
            )
        if fru.any():
            vv.append(
                float(
                    np.max(
                        mv[fru]
                        - ru[fru]
                    )
                )
            )
        # binary error belongs in the final check
        iz = integrality != 0
        if iz.any():
            vv.append(
                float(
                    np.max(
                        np.abs(
                            values[iz] - np.rint(values[iz])
                        )
                    )
                )
            )
        return max(vv)

    def _build_state(
        self,
        point: CapabilityAvailabilityPoint,
        limits: _StepLimits,
        index: _VariableIndex,
        solution: np.ndarray,
        sample: int,
        energy_unit_hours: float,
    ) -> CapabilityStatePoint:
        # rebuild plant states from solver values
        bb = tuple(
            (
                BranchDispatch(
                    x.branch_id,
                    self._clean(solution[index.pv(sample, j)]),
                )
                for j, x in enumerate(limits.pv)
            )
        ) + tuple(
            (
                BranchDispatch(
                    x.branch_id,
                    self._clean(
                        solution[index.discharge(sample, j)]
                        - solution[index.charge(sample, j)]
                    ),
                )
                for j, x in enumerate(limits.charge)
            )
        )
        # restore physical energy units
        ee = tuple(
            (
                BranchEnergyState(
                    x.branch_id,
                    self._clean(solution[index.energy(sample, j)])
                    * energy_unit_hours,
                )
                for j, x in enumerate(limits.charge)
            )
        )
        z = CapabilityDispatch(
            energy=sum((x.energy for x in ee)),
            branches=bb,
            branch_energy=ee,
        )
        return CapabilityStatePoint(
            snapshot=point.snapshot,
            feasibility_parameters=point.feasibility_parameters,
            dispatch=z,
        )

    def _clean(self, value: float) -> float:
        return 0.0 if abs(value) <= self._tolerance else float(value)

    @staticmethod
    def _failure(reason: str) -> DispatchTrajectorySolution:
        return DispatchTrajectorySolution(False, (), reason)
