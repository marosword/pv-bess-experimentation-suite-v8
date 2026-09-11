# P-Q capability, Ivas et al. (2020)
# graph state hyn ketu, pastaj ndahet per secilen mission
from __future__ import annotations
from dataclasses import replace; from math import sqrt
from ...feasibility import (
    DEFAULT_MISSION_FEASIBILITY_TOLERANCE,
    BranchEnergyResult,
    ConstraintCheck,
    ConverterOperatingPoint,
    FeasibilityLimits,
    FeasibilityPoint,
    FeasibilityResult,
    IntervalPowerModel,
    PlantFeasibilityModel,
)
from ...graph.capabilities import BranchCapability, CapabilitySnapshot
from ..active_power.models import ActivePowerSample, ActivePowerWindow
from ..frequency_response.models import (
    FrequencyResponseCapabilityBounds,
    FrequencyResponseCase,
    FrequencyResponseReference,
    FrequencyResponseReferenceState,
    FrequencyResponseSample,
    FrequencyResponseWindow,
)
from ..frequency_response.demand import (
    calculate_frequency_response_demand,
)
from ..frequency_response.requirements import FrequencyResponseService
from ..ramp_rate.models import RampRateSample, RampRateWindow
from ..ramp_rate.profile import (
    RampProfileModel,
    RampReferenceProfile,
    RampTargetPoint,
    RegisteredRampRates,
)
from ..reactive_power.models import (
    PowerReactiveCapabilityPoint,
    ReactiveCapabilityRange,
    VoltageReactiveCapabilityPoint,
)
from .models import (
    ActivePowerSearchResult,
    ActivePowerSearchSample,
    BranchDispatch,
    CapabilityDispatch,
    CapabilityStatePoint,
    DispatchTrajectorySolution,
    FrequencyResponseCaseSearchResult,
    FrequencyResponseSearchCase,
    PlantBoundaryLimits,
    PowerCapabilityRequest,
    PowerTrajectoryRequirement,
    RampRateSearchResult,
    RampRateSearchSample,
    ReactivePlantLimit,
    VoltageCapabilityRequest,
)
from .solver import DispatchFeasibilitySolver


class MissionCapabilityAdapter:
    def __init__( self,
        numerical_tolerance:float=DEFAULT_MISSION_FEASIBILITY_TOLERANCE,
        *,
        enable_equivalence_cache: bool = True,
        classification_only: bool = False,
    )->None:
        if numerical_tolerance < 0.0: raise ValueError("numerical_tolerance cannot be negative")
        if not isinstance(classification_only, bool): raise TypeError("classification_only must be a boolean")
        self._tolerance=numerical_tolerance; self._feasibility=PlantFeasibilityModel(numerical_tolerance)
        self._dispatch_solver=DispatchFeasibilitySolver(); self._enable_equivalence_cache=enable_equivalence_cache
        self._classification_only=classification_only
        self._frequency_healthy_dispatch_cache: dict[
            tuple[object, ...], DispatchTrajectorySolution
        ] = {}

    def feasibility_limits(self,snapshot:CapabilitySnapshot,
                 boundary: PlantBoundaryLimits)->FeasibilityLimits:
        return FeasibilityLimits(
            max_pv_power=snapshot.pv_dispatchable_power,
            max_charge_power=snapshot.bess_dispatchable_charge_power,
            max_discharge_power=snapshot.bess_dispatchable_discharge_power,
            minimum_poi_power=boundary.minimum_poi_power,
            maximum_poi_power=boundary.maximum_poi_power,
        )

    def evaluate_state(self,
        state:CapabilityStatePoint,
        boundary: PlantBoundaryLimits,
        *,
        terminal_energy_state: bool = False,
    )->FeasibilityResult:
        # validate each branch first
        bc=self._branch_capabilities(state.snapshot)
        bd = self._validated_dispatch(
            state.dispatch, frozenset(bc)
        ); be = self._validated_branch_energy(
            state.dispatch, state.snapshot
        )
        # branch stuff osht vecmas po checks poshte duan totals per krejt plantin
        pp = sum(
            (
                x.active_power
                for k, x in bd.items()
                if k.startswith("pv_")
            )
        )
        ch = sum(
            (
                max(-x.active_power, 0.0)
                for k, x in bd.items()
                if k.startswith("bess_")
            )
        )
        dis = sum(
            (
                max(x.active_power, 0.0)
                for k, x in bd.items()
                if k.startswith("bess_")
            )
        )
        pts = tuple(
            (
                ConverterOperatingPoint(
                    converter_id=k,
                    active_power=x.active_power,
                    apparent_power_rating=bc[
                        k
                    ].converter_rating,
                )
                for k, x in bd.items()
            )
        )
        p0 = FeasibilityPoint(
            energy=state.dispatch.energy,
            pv_power_used=pp,
            charge_power=ch,
            discharge_power=dis,
            converters=pts,
        )
        z = self._feasibility.evaluate(
            state.feasibility_parameters,
            self.feasibility_limits(state.snapshot, boundary),
            p0,
        )
        # terminal points spend no further energy
        if terminal_energy_state:
            z = replace(
                z,
                next_energy=z.current_energy,
                timestep_hours=0.0,
                checks=tuple(
                    (
                        c
                        for c in z.checks
                        if c.constraint_id
                        not in {
                            "next_energy_minimum",
                            "next_energy_maximum",
                        }
                    )
                ),
            )
        # local branch-limit checks
        aa = tuple(
            (
                c
                for k in sorted(bc)
                for c in self._branch_checks(
                    bd[k],
                    bc[k],
                )
            )
        )
        # update energy per BESS branch
        er = tuple(
            (
                self._branch_energy_result(
                    k,
                    e,
                    bd[k],
                    bc[k],
                    state,
                    terminal_energy_state,
                )
                for k, e in be.items()
            )
        )
        ee = tuple(
            c
            for r in er
            for c in self._branch_energy_checks(
                r, terminal_energy_state
            )
        )
        allc = (*z.checks,
                     *aa,
          *ee,)
        return replace(
            z,
            feasible=all((c.satisfied for c in allc)),
            checks=allc,
            branch_energy=er,
        )

    def _active_power_window(
        self,
        samples: tuple[ActivePowerSearchSample, ...],
        states: tuple[CapabilityStatePoint, ...],
        boundary: PlantBoundaryLimits,
        *,
        interval_average_samples: bool = False,
    ) -> ActivePowerWindow:
        # turn dispatch into M1 samples
        return ActivePowerWindow(
            tuple(
                (
                    ActivePowerSample(
                        elapsed_minutes=sample.elapsed_minutes,
                        setpoint_power=sample.setpoint_power,
                        feasibility=self.evaluate_state(
                            state, boundary
                        ),
                    )
                    for sample, state in zip(samples, states)
                )
            ),
            interval_average_samples=interval_average_samples,
        )

    def _ramp_rate_window(
        self,
        samples: tuple[RampRateSearchSample, ...],
        states: tuple[CapabilityStatePoint, ...],
        boundary: PlantBoundaryLimits,
    ) -> RampRateWindow:
        # last ramp point has no next interval
        return RampRateWindow(
            tuple(
                (
                    RampRateSample(
                        elapsed_minutes=sample.elapsed_minutes,
                        target_power=sample.target_power,
                        feasibility=self.evaluate_state(
                            state,
                            boundary,
                            terminal_energy_state=index
                            == len(samples) - 1,
                        ),
                    )
                    for index, (sample, state) in enumerate(
                        zip(samples, states)
                    )
                )
            )
        )

    def solve_static_active_power_point(
        self,
        availability: CapabilityAvailabilityPoint,
        boundary: PlantBoundaryLimits,
        initial_energy: float,
        poi_power: float,
    ) -> DispatchTrajectorySolution:
        # one point, fixed POI target
        return self._dispatch_solver.solve(
            (availability,),
            (
                PowerTrajectoryRequirement(
                    poi_power, poi_power, poi_power
                ),
            ),
            boundary,
            initial_energy,
            lexicographic_tiebreak=not self._classification_only,
            feasibility_only=self._classification_only,
            export_only_fixed_direction=self._classification_only,
        )

    def solve_active_power_window(
        self,
        samples: tuple[ActivePowerSearchSample, ...],
        boundary: PlantBoundaryLimits,
        initial_energy: float,
        *,
        interval_average_samples: bool = False,
    ) -> ActivePowerSearchResult:
        self._validate_time_axis(
            tuple((x.elapsed_minutes for x in samples)),
            tuple((x.availability for x in samples)),
            hours_per_time_unit=1.0 / 60.0,
        )
        # hold the exact setpoint
        z = self._dispatch_solver.solve(
            tuple((x.availability for x in samples)),
            tuple(
                (
                    PowerTrajectoryRequirement(
                        x.setpoint_power,
                        x.setpoint_power,
                        x.setpoint_power,
                    )
                    for x in samples
                )
            ),
            boundary,
            initial_energy,
            terminal_interval=interval_average_samples,
            lexicographic_tiebreak=not self._classification_only,
            feasibility_only=self._classification_only,
            export_only_fixed_direction=self._classification_only,
        )
        w = None
        if z.feasible:
            w = self._active_power_window(
                samples,
                z.states,
                boundary,
                interval_average_samples=interval_average_samples,
            )
        return ActivePowerSearchResult(z, w)

    def solve_active_power_best_effort_window(
        self,
        samples: tuple[ActivePowerSearchSample, ...],
        boundary: PlantBoundaryLimits,
        initial_energy: float,
        *,
        interval_average_samples: bool = False,
    ) -> ActivePowerSearchResult:
        self._validate_time_axis(
            tuple((x.elapsed_minutes for x in samples)),
            tuple((x.availability for x in samples)),
            hours_per_time_unit=1.0 / 60.0,
        )
        # minimise worst tracking error
        z = self._dispatch_solver.solve(
            tuple((x.availability for x in samples)),
            tuple(
                (
                    PowerTrajectoryRequirement(
                        boundary.minimum_poi_power,
                        boundary.maximum_poi_power,
                        x.setpoint_power,
                    )
                    for x in samples
                )
            ),
            boundary,
            initial_energy,
            terminal_interval=interval_average_samples,
            minimize_maximum_deviation=True,
        )
        w = None
        if z.feasible:
            w = self._active_power_window(
                samples,
                z.states,
                boundary,
                interval_average_samples=interval_average_samples,
            )
        return ActivePowerSearchResult(z, w)

    def solve_ramp_rate_window(
        self,
        samples: tuple[RampRateSearchSample, ...],
        boundary: PlantBoundaryLimits,
        initial_energy: float,
        rates: RegisteredRampRates,
        initial_profile_power: float,
    ) -> RampRateSearchResult:
        pm = RampProfileModel()
        self._validate_time_axis(
            tuple((x.elapsed_minutes for x in samples)),
            tuple((x.availability for x in samples)),
            hours_per_time_unit=1.0 / 60.0,
        )
        # capability cannot change mid-ramp
        self._validate_constant_ramp_availability(samples)
        # first-pass ramp
        rr = pm.build(
            tuple(
                (
                    RampTargetPoint(
                        x.elapsed_minutes, x.target_power
                    )
                    for x in samples
                )
            ),
            rates,
            initial_profile_power,
        )
        samples = self._insert_ramp_dispatch_breakpoints(
            samples, rr
        )
        rr = pm.build(
            tuple(
                (
                    RampTargetPoint(
                        x.elapsed_minutes, x.target_power
                    )
                    for x in samples
                )
            ),
            rates,
            initial_profile_power,
        )
        z = self._dispatch_solver.solve(
            tuple((x.availability for x in samples)),
            tuple(
                (
                    PowerTrajectoryRequirement(
                        p.profile_power,
                        p.profile_power,
                        p.profile_power,
                    )
                    for p in rr.points
                )
            ),
            boundary,
            initial_energy,
            interval_power_model=IntervalPowerModel.PIECEWISE_LINEAR,
            lexicographic_tiebreak=not self._classification_only,
            feasibility_only=self._classification_only,
            export_only_fixed_direction=False,
        )
        w = None
        if z.feasible:
            w = self._ramp_rate_window(
                samples,
                z.states,
                boundary,
            )
        return RampRateSearchResult(z, w)

    def _validate_constant_ramp_availability(
        self, samples: tuple[RampRateSearchSample, ...]
    ) -> None:
        x0 = samples[0].availability
        r0 = x0.feasibility_parameters
        for x in samples[1:]:
            av = x.availability
            pp = av.feasibility_parameters
            if av.snapshot != x0.snapshot:
                raise ValueError(
                    "piecewise-linear ramp search requires constant capability"
                )
            if any(
                (
                    abs(a - b) > self._tolerance
                    for a, b in (
                        (pp.energy_min, r0.energy_min),
                        (pp.energy_max, r0.energy_max),
                        (
                            pp.charge_efficiency,
                            r0.charge_efficiency,
                        ),
                        (
                            pp.discharge_efficiency,
                            r0.discharge_efficiency,
                        ),
                    )
                )
            ):
                raise ValueError(
                    "piecewise-linear ramp search requires constant parameters"
                )

    def _insert_ramp_dispatch_breakpoints(
        self,
        samples: tuple[RampRateSearchSample, ...],
        profile: RampReferenceProfile,
    ) -> tuple[RampRateSearchSample, ...]:
        if len(samples) == 1:
            return samples
        refined = [samples[0]]
        for index, (sample, next_sample) in enumerate(
            zip(samples, samples[1:])
        ):
            start = profile.points[index]
            end = profile.points[index + 1]
            snapshot = sample.availability.snapshot
            pv_limit = snapshot.pv_dispatchable_power
            charge_limit = snapshot.bess_dispatchable_charge_power
            # add dispatch mode crossings
            breakpoints = {pv_limit, pv_limit - charge_limit}
            lower = min(start.profile_power, end.profile_power)
            upper = max(start.profile_power, end.profile_power)
            crossings = []
            if upper - lower > self._tolerance:
                for breakpoint in breakpoints:
                    if (
                        not lower + self._tolerance
                        < breakpoint
                        < upper - self._tolerance
                    ):
                        continue
                    fraction = (breakpoint - start.profile_power) / (
                        end.profile_power - start.profile_power
                    )
                    t = (
                        sample.elapsed_minutes
                        + fraction
                        * (
                            next_sample.elapsed_minutes
                            - sample.elapsed_minutes
                        )
                    )
                    crossings.append(t)
            for t in sorted(crossings):
                refined.append(
                    RampRateSearchSample(
                        elapsed_minutes=t,
                        target_power=next_sample.target_power,
                        availability=sample.availability,
                    )
                )
            refined.append(next_sample)
        out = []
        for index, sample in enumerate(refined):
            if index < len(refined) - 1:
                dt = (
                    refined[index + 1].elapsed_minutes
                    - sample.elapsed_minutes
                )
            else:
                dt = (
                    sample.elapsed_minutes
                    - refined[index - 1].elapsed_minutes
                )
            av = replace(
                sample.availability,
                feasibility_parameters=replace(
                    sample.availability.feasibility_parameters,
                    timestep_hours=dt / 60.0,
                ),
            )
            out.append(replace(sample, availability=av))
        ans = tuple(out)
        return ans

    def build_power_reactive_capability_points(
        self,
        snapshot: CapabilitySnapshot,
        requests: tuple[PowerCapabilityRequest, ...],
        boundary: PlantBoundaryLimits,
    ) -> tuple[PowerReactiveCapabilityPoint, ...]:
        # one Q range for each P request
        return tuple(
            (
                PowerReactiveCapabilityPoint(
                    active_power=request.active_power,
                    capability=self._apply_reactive_plant_limit(
                        self._reactive_capability(
                            snapshot,
                            request.active_power,
                            boundary,
                            converter_rating_factor=1.0,
                        ),
                        request.plant_limit,
                    ),
                )
                for request in requests
            )
        )

    def build_voltage_reactive_capability_points(
        self,
        snapshot: CapabilitySnapshot,
        active_power: float,
        requests: tuple[VoltageCapabilityRequest, ...],
        boundary: PlantBoundaryLimits,
    ) -> tuple[VoltageReactiveCapabilityPoint, ...]:
        # voltage derating happens slice by slice
        return tuple(
            (
                VoltageReactiveCapabilityPoint(
                    active_power=active_power,
                    voltage_per_unit=request.voltage_per_unit,
                    capability=self._apply_reactive_plant_limit(
                        self._reactive_capability(
                            snapshot,
                            active_power,
                            boundary,
                            request.converter_rating_factor,
                        ),
                        request.plant_limit,
                    ),
                )
                for request in requests
            )
        )

    def frequency_response_bounds(
        self,
        snapshot: CapabilitySnapshot,
        boundary: PlantBoundaryLimits,
        allow_grid_import: bool = False,
    ) -> FrequencyResponseCapabilityBounds:
        # charging sets the lower physical bound
        physical_minimum = -snapshot.bess_dispatchable_charge_power
        if not allow_grid_import:
            physical_minimum = max(physical_minimum, 0.0)
        minimum = max(boundary.minimum_poi_power, physical_minimum)
        maximum = min(
            boundary.maximum_poi_power,
            snapshot.pv_dispatchable_power
            + snapshot.bess_dispatchable_discharge_power,
        )
        if minimum > maximum + self._tolerance:
            raise ValueError(
                "the snapshot has no feasible POI operating range"
            )
        return FrequencyResponseCapabilityBounds(minimum, maximum)

    def _frequency_response_window(
        self,
        samples: tuple[FrequencyResponseAvailabilitySample, ...],
        failed_states: tuple[CapabilityStatePoint, ...],
        healthy_states: tuple[CapabilityStatePoint, ...],
        healthy_bounds: tuple[FrequencyResponseCapabilityBounds, ...],
        boundary: PlantBoundaryLimits,
    ) -> FrequencyResponseWindow:
        adapted = []
        for sample, failed_state, healthy_state, bounds in zip(
            samples, failed_states, healthy_states, healthy_bounds
        ):
            adapted.append(
                FrequencyResponseSample(
                    elapsed_seconds=sample.elapsed_seconds,
                    frequency_hz=sample.frequency_hz,
                    feasibility=self.evaluate_state(
                        failed_state, boundary
                    ),
                    healthy_reference_state=FrequencyResponseReferenceState(
                        capability_bounds=bounds,
                        feasibility=self.evaluate_state(
                            healthy_state, boundary
                        ),
                    ),
                )
            )
        return FrequencyResponseWindow(tuple(adapted))

    def solve_frequency_response_case(
        self,
        search_case: FrequencyResponseSearchCase,
        boundary: PlantBoundaryLimits,
        healthy_reference: FrequencyResponseReference,
        droop: float,
        target_frequency_hz: float,
        time_tolerance_seconds: float,
        failed_initial_energy: float,
        healthy_initial_energy: float,
        allow_grid_import: bool = False,
    ) -> FrequencyResponseCaseSearchResult:
        samples=search_case.samples; final_time=samples[-1].elapsed_seconds
        self._validate_time_axis(
            tuple((sample.elapsed_seconds for sample in samples)),
            tuple((sample.failed_availability for sample in samples)),
            hours_per_time_unit=1.0 / 3600.0,
        )
        self._validate_time_axis(
            tuple((sample.elapsed_seconds for sample in samples)),
            tuple(
                (
                    sample.healthy_reference_availability
                    for sample in samples
                )
            ),
            hours_per_time_unit=1.0 / 3600.0,
        )
        # import mos e lejo kot, vec kur case e ka explicitly
        effective_boundary = PlantBoundaryLimits(
            minimum_poi_power=boundary.minimum_poi_power
            if allow_grid_import
            else max(0.0, boundary.minimum_poi_power),
            maximum_poi_power=boundary.maximum_poi_power,
        )
        healthy_bounds = tuple(
            (
                self.frequency_response_bounds(
                    sample.healthy_reference_availability.snapshot,
                    effective_boundary,
                    allow_grid_import,
                )
                for sample in samples
            )
        )
        # healthy baseline must fit every sample
        invalid_baseline = any(
            not bounds.minimum_poi_power - self._tolerance
            <= search_case.baseline_power
            <= bounds.maximum_poi_power + self._tolerance
            for bounds in healthy_bounds
        )
        if (invalid_baseline):
            unavailable_reference=self._failed_solution(
                "healthy_baseline_unavailable"
            );
            return FrequencyResponseCaseSearchResult(
                unavailable_reference, None, None
            )
        # frequency demand into POI bands
        healthy_requirements = tuple(
            (
                self._frequency_response_requirement(
                    search_case,
                    sample.elapsed_seconds,
                    sample.frequency_hz,
                    final_time,
                    healthy_reference,
                    bounds,
                    droop,
                    target_frequency_hz,
                    time_tolerance_seconds,
                    effective_boundary,
                    search_case.fixed_high_loading_requirement_fraction,
                )
                for sample, bounds in zip(samples, healthy_bounds)
            )
        )
        healthy_key = (
            tuple(
                (
                    sample.healthy_reference_availability
                    for sample in samples
                )
            ),
            healthy_requirements,
            effective_boundary,
            healthy_initial_energy,
        )
        # healthy solve osht same shpesh, mos thirr highs prap pa nevoje
        healthy_dispatch = (
            self._frequency_healthy_dispatch_cache.get(healthy_key)
            if self._enable_equivalence_cache
            else None
        )
        if healthy_dispatch is None:
            healthy_dispatch = self._dispatch_solver.solve(
                tuple(
                    (
                        sample.healthy_reference_availability
                        for sample in samples
                    )
                ),
                healthy_requirements,
                effective_boundary,
                healthy_initial_energy,
                lexicographic_tiebreak=not self._classification_only,
                feasibility_only=self._classification_only,
                export_only_fixed_direction=self._classification_only,
            )
            if self._enable_equivalence_cache:
                self._frequency_healthy_dispatch_cache[
                    healthy_key
                ] = healthy_dispatch
        # pa healthy reference ska comparison
        if not healthy_dispatch.feasible:
            return FrequencyResponseCaseSearchResult(
                healthy_dispatch, None, None
            )
        # apply failed availability next
        failed_dispatch = self._dispatch_solver.solve(
            tuple((sample.failed_availability for sample in samples)),
            healthy_requirements,
            effective_boundary,
            failed_initial_energy,
            lexicographic_tiebreak=not self._classification_only,
            feasibility_only=self._classification_only,
            export_only_fixed_direction=self._classification_only,
        )
        case=None
        if (failed_dispatch.feasible):
            case = FrequencyResponseCase(
                case_id=search_case.case_id,
                service=search_case.service,
                baseline_power=search_case.baseline_power,
                window=self._frequency_response_window(
                    samples,
                    failed_dispatch.states,
                    healthy_dispatch.states,
                    healthy_bounds,
                    effective_boundary,
                ),
                fixed_high_loading_requirement_fraction=search_case.fixed_high_loading_requirement_fraction,
                assessment_intervals=search_case.assessment_intervals,
                minimum_applicable_loading_fraction=search_case.minimum_applicable_loading_fraction,
                maximum_applicable_loading_fraction=search_case.maximum_applicable_loading_fraction,
            )
        return FrequencyResponseCaseSearchResult(
            healthy_dispatch, failed_dispatch, case
        )

    @staticmethod
    def _frequency_response_requirement(
        search_case: FrequencyResponseSearchCase,
        elapsed_seconds: float,
        frequency_hz: float,
        final_elapsed_seconds: float,
        reference: FrequencyResponseReference,
        bounds: FrequencyResponseCapabilityBounds,
        droop: float,
        target_frequency_hz: float,
        time_tolerance_seconds: float,
        boundary: PlantBoundaryLimits,
        declared_above_95_fraction: float | None,
    ) -> PowerTrajectoryRequirement:
        demand = calculate_frequency_response_demand(
            service=search_case.service,
            elapsed_seconds=elapsed_seconds,
            final_elapsed_seconds=final_elapsed_seconds,
            frequency_hz=frequency_hz,
            baseline_power=search_case.baseline_power,
            reference=reference,
            bounds=bounds,
            droop=droop,
            target_frequency_hz=target_frequency_hz,
            declared_above_95_fraction=declared_above_95_fraction,
            time_tolerance_seconds=time_tolerance_seconds,
            assessment_intervals=tuple(
                (
                    (interval.start_seconds, interval.end_seconds)
                    for interval in search_case.assessment_intervals
                )
            ),
            minimum_applicable_loading_fraction=search_case.minimum_applicable_loading_fraction,
            maximum_applicable_loading_fraction=search_case.maximum_applicable_loading_fraction,
        )
        # outside assessment, hold baseline
        if not demand.assessed or not demand.requirement_defined:
            return PowerTrajectoryRequirement(
                search_case.baseline_power,
                search_case.baseline_power,
                search_case.baseline_power,
            )
        # underfrequency asks for upward power
        if search_case.service in (
            FrequencyResponseService.PRIMARY,
            FrequencyResponseService.SECONDARY,
        ):
            return PowerTrajectoryRequirement(
                demand.requested_poi_power,
                boundary.maximum_poi_power,
                demand.requested_poi_power,
            )
        return PowerTrajectoryRequirement(
            boundary.minimum_poi_power,
            demand.requested_poi_power,
            demand.requested_poi_power,
        )

    @staticmethod
    def _failed_solution(reason: str) -> DispatchTrajectorySolution:
        return DispatchTrajectorySolution(False, (), reason)

    def _validate_time_axis(self,times:tuple[float,...],
        availability: tuple,
        hours_per_time_unit: float,
    )->None:
        if not times: raise ValueError("a dispatch search needs at least one sample")
        if len(times) != len(availability):
            raise ValueError(
                "times and availability must have equal length"
            )
        if any(
            (
                later <= earlier
                for earlier, later in zip(times, times[1:])
            )
        ):
            raise ValueError(
                "dispatch search times must be strictly increasing"
            )
        # sample gaps must match energy steps
        for index, (earlier, later) in enumerate(zip(times, times[1:])):
            expected_hours = (later - earlier) * hours_per_time_unit
            actual_hours = availability[
                index
            ].feasibility_parameters.timestep_hours
            if abs(actual_hours - expected_hours) > self._tolerance:
                raise ValueError(
                    f"dispatch timestep does not match the sample-time interval at index {index}"
                )

    @staticmethod
    def _validated_dispatch(
        dispatch: CapabilityDispatch,
        expected_branch_ids: frozenset[str],
    ) -> dict[str, BranchDispatch]:
        tmp = {
            x.branch_id: x for x in dispatch.branches
        }
        got = set(tmp)
        if got != expected_branch_ids:
            miss = expected_branch_ids - got
            xx = got - expected_branch_ids
            bits = []
            if miss:
                bits.append(f"missing: {', '.join(sorted(miss))}")
            if xx:
                bits.append(f"unknown: {', '.join(sorted(xx))}")
            raise ValueError(
                "invalid dispatch branches (" + "; ".join(bits) + ")"
            )
        if any(
            (
                x.active_power < 0.0
                for k, x in tmp.items()
                if k.startswith("pv_")
            )
        ):
            raise ValueError(
                "PV branch active power cannot be negative"
            )
        return tmp

    @staticmethod
    def _validated_branch_energy(
        dispatch: CapabilityDispatch, snapshot: CapabilitySnapshot
    ) -> dict[str, float]:
        if not dispatch.branch_energy:
            return {}
        tmp = {
            x.branch_id: x.energy
            for x in dispatch.branch_energy
        }
        want = {
            x.branch_id for x in snapshot.bess_branches
        }
        got = set(tmp)
        if got != want:
            miss = want - got
            xx = got - want
            bits = []
            if miss:
                bits.append(f"missing: {', '.join(sorted(miss))}")
            if xx:
                bits.append(f"unknown: {', '.join(sorted(xx))}")
            raise ValueError(
                "invalid branch energy states ("
                + "; ".join(bits)
                + ")"
            )
        return tmp

    @staticmethod
    def _branch_capabilities(
        snapshot: CapabilitySnapshot,
    ) -> dict[str, BranchCapability]:
        tmp = {
            x.branch_id: x
            for x in (
                *snapshot.pv_branches,
                *snapshot.bess_branches,
            )
        }
        n = len(snapshot.pv_branches) + len(
            snapshot.bess_branches
        )
        if len(tmp) != n:
            raise ValueError(
                "capability snapshot branch IDs must be unique"
            )
        if any(
            (
                not x.branch_id.startswith("pv_")
                for x in snapshot.pv_branches
            )
        ) or any(
            (
                not x.branch_id.startswith("bess_")
                for x in snapshot.bess_branches
            )
        ):
            raise ValueError(
                "capability branch IDs must identify PV or BESS"
            )
        return tmp

    def _branch_checks(
        self, dispatch: BranchDispatch, capability: BranchCapability
    ) -> tuple[ConstraintCheck, ...]:
        if dispatch.branch_id.startswith("pv_"):
            lim = capability.active_power_dispatchable
            x = dispatch.active_power
            tag = "pv_active_power"
        elif dispatch.active_power >= 0.0:
            lim = capability.discharge_power_dispatchable
            x = dispatch.active_power
            tag = "bess_discharge_power"
        else:
            lim = capability.charge_power_dispatchable
            x = -dispatch.active_power
            tag = "bess_charge_power"
        return (
            ConstraintCheck(
                f"{tag}:{dispatch.branch_id}",
                x <= lim + self._tolerance,
            ),
        )

    def _branch_energy_checks(
        self,
        result: BranchEnergyResult,
        terminal_energy_state: bool = False,
    ) -> tuple[ConstraintCheck, ...]:
        bid = result.branch_id
        e0 = result.current_energy
        zz = (
            ConstraintCheck(
                f"current_bess_energy_minimum:{bid}",
                e0 >= -self._tolerance,
            ),
            ConstraintCheck(
                f"current_bess_energy_maximum:{bid}",
                e0 <= result.energy_capacity + self._tolerance,
            ),
            ConstraintCheck(
                f"next_bess_energy_minimum:{bid}",
                result.next_energy >= -self._tolerance,
            ),
            ConstraintCheck(
                f"next_bess_energy_maximum:{bid}",
                result.next_energy
                <= result.energy_capacity + self._tolerance,
            ),
        )
        if terminal_energy_state:
            return zz[:2]
        return zz

    @staticmethod
    def _branch_energy_result(
        branch_id: str,
        energy: float,
        dispatch: BranchDispatch,
        capability: BranchCapability,
        state: CapabilityStatePoint,
        terminal_energy_state: bool = False,
    ) -> BranchEnergyResult:
        p = state.feasibility_parameters
        # charge futet me eta, discharge del pjesetim se losses shkojne opposite
        if terminal_energy_state:
            e1 = energy
        elif dispatch.active_power >= 0.0:
            e1 = (
                energy
                - dispatch.active_power
                / p.discharge_efficiency
                * p.timestep_hours
            )
        else:
            e1 = (
                energy
                - dispatch.active_power
                * p.charge_efficiency
                * p.timestep_hours
            )
        return BranchEnergyResult(
            branch_id=branch_id,
            current_energy=energy,
            next_energy=e1,
            energy_capacity=capability.energy_capacity,
            active_power=dispatch.active_power,
            charge_efficiency=p.charge_efficiency,
            discharge_efficiency=p.discharge_efficiency,
        )

    def _reactive_capability(
        self,
        snapshot: CapabilitySnapshot,
        active_power: float,
        boundary: PlantBoundaryLimits,
        converter_rating_factor: float,
    ) -> ReactiveCapabilityRange:
        if active_power < -self._tolerance:
            raise ValueError(
                "reactive capability adapter is export-only"
            )
        bb = (*snapshot.pv_branches, *snapshot.bess_branches)
        rr = tuple(
            (
                x.converter_rating * converter_rating_factor
                if x.reactive_converter_available
                else 0.0
                for x in bb
            )
        )
        if sum(rr) <= self._tolerance:
            return ReactiveCapabilityRange(
                minimum_reactive_power=None,
                maximum_reactive_power=None,
                operating_point_feasible=False,
            )
        if (
            boundary.maximum_apparent_power is not None
            and active_power
            > boundary.maximum_apparent_power + self._tolerance
        ):
            return ReactiveCapabilityRange(
                minimum_reactive_power=None,
                maximum_reactive_power=None,
                operating_point_feasible=False,
            )
        ll = tuple(
            (
                min(
                    x.active_power_dispatchable
                    if x.branch_id.startswith("pv_")
                    else x.discharge_power_dispatchable
                    if x.usable_energy > self._tolerance
                    else 0.0,
                    x.converter_rating * converter_rating_factor,
                )
                for x in bb
            )
        )
        mx = min(
            boundary.maximum_poi_power, sum(ll)
        )
        if active_power > mx + self._tolerance:
            return ReactiveCapabilityRange(
                minimum_reactive_power=None,
                maximum_reactive_power=None,
                operating_point_feasible=False,
            )
        # leave maximum room for Q
        aa = self._allocate_active_for_maximum_reactive(
            active_power, ll, rr
        )
        q = sum(
            (
                sqrt(max(r**2 - p**2, 0.0))
                for p, r in zip(aa, rr)
            )
        )
        if boundary.maximum_apparent_power is not None:
            qpoi = sqrt(
                max(
                    boundary.maximum_apparent_power**2
                    - active_power**2,
                    0.0,
                )
            )
            q = min(q, qpoi)
        return ReactiveCapabilityRange(
            minimum_reactive_power=-q,
            maximum_reactive_power=q,
        )

    @staticmethod
    def _apply_reactive_plant_limit(
        capability: ReactiveCapabilityRange,
        plant_limit: ReactivePlantLimit | None,
    ) -> ReactiveCapabilityRange:
        if (
            plant_limit is None
            or not capability.operating_point_feasible
        ):
            return capability
        if (
            capability.minimum_reactive_power is None
            or capability.maximum_reactive_power is None
        ):
            raise RuntimeError("validated reactive limits are missing")
        # intersect converter and plant Q limits
        lo = max(
            capability.minimum_reactive_power,
            plant_limit.minimum_reactive_power,
        )
        hi = min(
            capability.maximum_reactive_power,
            plant_limit.maximum_reactive_power,
        )
        if lo > hi:
            return ReactiveCapabilityRange(
                minimum_reactive_power=None,
                maximum_reactive_power=None,
                operating_point_feasible=False,
            )
        return ReactiveCapabilityRange(
            minimum_reactive_power=lo,
            maximum_reactive_power=hi,
        )

    def _allocate_active_for_maximum_reactive(
        self,
        active_power: float,
        active_limits: tuple[float, ...],
        ratings: tuple[float, ...],
    ) -> tuple[float, ...]:
        # P ndahet keshtu qe mos me marre krejt Q room ne nje converter
        out = [0.0] * len(active_limits)
        left = active_power
        for i, (lim, rr) in enumerate(
            zip(active_limits, ratings)
        ):
            if rr > self._tolerance:
                continue
            x = min(lim, left)
            out[i] = x
            left -= x
        todo = {
            i
            for i, (lim, rr) in enumerate(
                zip(active_limits, ratings)
            )
            if rr > self._tolerance and lim > self._tolerance
        }
        while todo and left > self._tolerance:
            tot = sum((ratings[i] for i in todo))
            if tot <= self._tolerance:
                break
            z = left / tot
            done = {
                i
                for i in todo
                if z * ratings[i]
                > active_limits[i] + self._tolerance
            }
            if not done:
                for i in todo:
                    out[i] = z * ratings[i]
                left = 0.0
                break
            for i in done:
                out[i] = active_limits[i]
                left -= active_limits[i]
            todo -= done
        if left > self._tolerance:
            raise RuntimeError(
                "validated active power could not be allocated"
            )
        return tuple(out)
