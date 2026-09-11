# Monotone mission oracle, Marques-Silva et al. (2013)
from __future__ import annotations
from collections.abc import Callable; from dataclasses import replace
from ..critical_sets import (
    AssessmentStatus,
    FailureUniverse,
    MissionAssessment,
)
from ..graph import (
    CapabilityEvaluator,
    CapabilitySnapshot,
    FailureSelection,
    PlantCapabilityParameters,
    ReactiveSupportMode,
    STATION_DC_AUTONOMY_TRIGGER_CONNECTION_IDS,
    STATION_DC_AUTONOMY_TRIGGER_NODE_IDS,
)
from ..missions import (
    ActivePowerMissionContext,
    ActivePowerSearchSample,
    ActivePowerTrackingMission,
    CapabilityAvailabilityPoint,
    FrequencyResponseAvailabilitySample,
    FrequencyResponseCapabilityMission,
    FrequencyResponseCaseSearchResult,
    FrequencyResponseMissionContext,
    FrequencyResponseSearchCase,
    MissionCapabilityAdapter,
    RampProfileCapabilityMission,
    RampRateMissionContext,
    RampRateSearchSample,
    ReactiveAssessmentScope,
    ReactivePowerCapabilityMission,
    ReactivePowerMissionContext,
    frequency_response_applicability_reason,
)
from .config import (
    ActivePowerExperimentScenario,
    AvailabilityInput,
    FrequencyResponseCaseScenario,
    FrequencyResponseExperimentScenario,
    MissionExperimentScenario,
    RampRateExperimentScenario,
    ReactivePowerExperimentScenario,
)
from .mission_projection import (
    dispatch_availability_projection,
    reactive_snapshot_projection,
)

MissionOracle=Callable[[frozenset[str]],MissionAssessment]
SnapshotCacheKey = tuple[
    FailureSelection, PlantCapabilityParameters, ReactiveSupportMode
]
SnapshotCache=dict[SnapshotCacheKey,CapabilitySnapshot]; _TIME_COMPARISON_TOLERANCE_HOURS=1e-12


class MissionOracleFactory:
    # lots of paths KEEP LOCAL
    def __init__(self)->None: self._capability=CapabilityEvaluator()

    def build(self,scenario:MissionExperimentScenario,
              universe:FailureUniverse)->MissionOracle:
        # route mission type to the right oracle
        if isinstance(scenario, ActivePowerExperimentScenario):
            return self._active_power(
                scenario,
                universe,
            )
        if isinstance(scenario,RampRateExperimentScenario): return self._ramp_rate(scenario,universe)
        if isinstance(scenario, ReactivePowerExperimentScenario):
            return self._reactive_power(scenario, universe)
        if isinstance(scenario,FrequencyResponseExperimentScenario): return self._frequency_response(scenario,universe)
        raise TypeError(
            f"unsupported experiment scenario: {type(scenario)!r}"
        )

    def _active_power(
        self,
        scenario: ActivePowerExperimentScenario,
        universe: FailureUniverse,
    ) -> MissionOracle:
        adapter = MissionCapabilityAdapter(
            scenario.numerical_tolerance,
            classification_only=True,
        )
        mission=ActivePowerTrackingMission(); assessment_cache:dict[object,MissionAssessment]={}

        def assess(candidate_ids: frozenset[str]) -> MissionAssessment:
            # map IDs to graph failures
            failures=universe.selection(candidate_ids); snapshot_cache:SnapshotCache={}
            # failure effects change with plant state
            samples = tuple(
                (
                    ActivePowerSearchSample(
                        elapsed_minutes=point.elapsed_minutes,
                        setpoint_power=point.setpoint_power,
                        availability=self._availability(
                            failures,
                            point.availability,
                            scenario.reactive_support_mode,
                            snapshot_cache,
                        ),
                    )
                    for point in scenario.points
                )
            )
            # equal capability needs one solver call
            cache_key = (
                "projection",
                tuple(
                    (
                        (
                            sample.elapsed_minutes,
                            sample.setpoint_power,
                            dispatch_availability_projection(
                                sample.availability
                            ),
                        )
                        for sample in samples
                    )
                ),
            )
            cached=assessment_cache.get(cache_key)
            if cached is not None: return cached

            def finish(
                assessment: MissionAssessment,
            ) -> MissionAssessment:
                assessment_cache[cache_key]=assessment; return assessment

            # energy links the full m1 horizon
            search = adapter.solve_active_power_window(
                samples,
                scenario.boundary,
                initial_energy=samples[
                    0
                ].availability.snapshot.bess_usable_energy,
                interval_average_samples=scenario.interval_average_samples,
            )
            if not search.dispatch.feasible:
                return finish(
                    MissionAssessment(
                        scenario.mission_id,
                        AssessmentStatus.FAILURE,
                        threshold=scenario.numerical_tolerance,
                        reason=search.dispatch.reason,
                    )
                )
            if search.window is None:
                raise RuntimeError(
                    "feasible active-power search has no window"
                )
            result = mission.evaluate(
                ActivePowerMissionContext(
                    physical_window=search.window,
                    numerical_tolerance=scenario.numerical_tolerance,
                )
            )
            return finish(MissionAssessment.from_mission_result(result))

        return assess

    def _ramp_rate(
        self,
        scenario: RampRateExperimentScenario,
        universe: FailureUniverse,
    ) -> MissionOracle:
        adapter = MissionCapabilityAdapter(
            scenario.power_tolerance,
            classification_only=True,
        )
        mission=RampProfileCapabilityMission(); assessment_cache:dict[object,MissionAssessment]={}

        def assess(candidate_ids: frozenset[str]) -> MissionAssessment:
            # no requested movement means no mission
            if not scenario.instruction_demanded:
                return MissionAssessment(
                    scenario.mission_id,
                    AssessmentStatus.INVALID,
                    value=0.0,
                    threshold=scenario.power_tolerance,
                    reason="mission_not_demanded",
                )
            failures=universe.selection(candidate_ids); snapshot_cache:SnapshotCache={}
            # hold pv while bess energy moves
            samples = tuple(
                (
                    RampRateSearchSample(
                        elapsed_minutes=point.elapsed_minutes,
                        target_power=point.target_power,
                        availability=self._availability(
                            failures,
                            point.availability,
                            scenario.reactive_support_mode,
                            snapshot_cache,
                        ),
                    )
                    for point in scenario.points
                )
            )
            cache_key = (
                "projection",
                tuple(
                    (
                        (
                            sample.elapsed_minutes,
                            sample.target_power,
                            dispatch_availability_projection(
                                sample.availability
                            ),
                        )
                        for sample in samples
                    )
                ),
            )
            cached=assessment_cache.get(cache_key)
            if cached is not None: return cached

            def finish(
                assessment: MissionAssessment,
            ) -> MissionAssessment:
                assessment_cache[cache_key]=assessment; return assessment

            initial_energy = samples[
                0
            ].availability.snapshot.bess_usable_energy
            search = adapter.solve_ramp_rate_window(
                samples,
                scenario.boundary,
                initial_energy=initial_energy,
                rates=scenario.rates,
                initial_profile_power=scenario.initial_profile_power,
            )
            if not search.dispatch.feasible:
                # separate bad start from bad ramp
                precondition = adapter.solve_static_active_power_point(
                    samples[0].availability,
                    scenario.boundary,
                    initial_energy,
                    scenario.initial_profile_power,
                )
                if not precondition.feasible:
                    return finish(
                        MissionAssessment(
                            scenario.mission_id,
                            AssessmentStatus.FAILURE,
                            reason=f"pre_ramp_operating_point_unavailable:{precondition.reason}",
                        )
                    )
                return finish(
                    MissionAssessment(
                        scenario.mission_id,
                        AssessmentStatus.FAILURE,
                        reason=f"ramp_trajectory_unavailable:{search.dispatch.reason}",
                    )
                )
            if search.window is None:
                raise RuntimeError(
                    "feasible ramp-rate search has no window"
                )
            result = mission.evaluate(
                RampRateMissionContext(
                    window=search.window,
                    rates=scenario.rates,
                    initial_profile_power=scenario.initial_profile_power,
                    power_tolerance=scenario.power_tolerance,
                    step_power_tolerance=scenario.step_power_tolerance,
                    energy_tolerance=scenario.energy_tolerance,
                    time_tolerance_minutes=scenario.time_tolerance_minutes,
                )
            )
            return finish(MissionAssessment.from_mission_result(result))

        return assess

    def _reactive_power(
        self,
        scenario: ReactivePowerExperimentScenario,
        universe: FailureUniverse,
    ) -> MissionOracle:
        adapter = MissionCapabilityAdapter(
            scenario.numerical_tolerance,
            classification_only=True,
        )
        mission=ReactivePowerCapabilityMission(); assessment_cache:dict[object,MissionAssessment]={}

        def assess(candidate_ids: frozenset[str]) -> MissionAssessment:
            failures=universe.selection(candidate_ids); snapshot_cache:SnapshotCache={}
            snapshot=self._snapshot(
                failures,
                scenario.availability,
                scenario.reactive_support_mode,
                snapshot_cache,
            )
            # reactive checks use a static energy state
            cache_key = (
                "projection",
                reactive_snapshot_projection(snapshot),
            )
            cached=assessment_cache.get(cache_key)
            if cached is not None: return cached
            # add U-Q only when requested
            voltage_capability_points = ()
            if (
                scenario.assessment_scope
                is ReactiveAssessmentScope.POWER_AND_VOLTAGE_ENVELOPES
            ):
                if scenario.voltage_active_power is None:
                    raise RuntimeError(
                        "validated voltage-envelope active power is missing"
                    )
                voltage_capability_points = (
                    adapter.build_voltage_reactive_capability_points(
                        snapshot,
                        scenario.voltage_active_power,
                        scenario.voltage_requests,
                        scenario.boundary,
                    )
                )
            result = mission.evaluate(
                ReactivePowerMissionContext(
                    maximum_capacity=scenario.maximum_capacity,
                    assessment_scope=scenario.assessment_scope,
                    power_capability_points=adapter.build_power_reactive_capability_points(
                        snapshot,
                        scenario.power_requests,
                        scenario.boundary,
                    ),
                    voltage_capability_points=voltage_capability_points,
                    voltage_requirements=scenario.voltage_requirements,
                    below_twenty_mode=scenario.below_twenty_mode,
                    numerical_tolerance=scenario.numerical_tolerance,
                    full_absorbing_capability_to_20_percent=scenario.full_absorbing_capability_to_20_percent,
                    declared_below_twenty_requirements=scenario.declared_below_twenty_requirements,
                )
            )
            assessment=MissionAssessment.from_mission_result(result)
            assessment_cache[cache_key]=assessment; return assessment

        return assess

    def _frequency_response(
        self,
        scenario: FrequencyResponseExperimentScenario,
        universe: FailureUniverse,
    ) -> MissionOracle:
        adapter = MissionCapabilityAdapter(
            scenario.numerical_tolerance,
            classification_only=True,
        )
        mission=FrequencyResponseCapabilityMission(); healthy_failures=FailureSelection()
        assessment_cache:dict[object,MissionAssessment]={}; healthy_snapshot_cache:SnapshotCache={}
        healthy_reference_validated=False

        def assess(candidate_ids: frozenset[str]) -> MissionAssessment:
            nonlocal healthy_reference_validated
            for case in scenario.cases:
                # undefined loading rules mean inapplicable
                reason = frequency_response_applicability_reason(
                    baseline_power=case.baseline_power,
                    reference=scenario.healthy_reference,
                    declared_above_95_fraction=case.fixed_high_loading_requirement_fraction,
                    minimum_applicable_loading_fraction=case.minimum_applicable_loading_fraction,
                    maximum_applicable_loading_fraction=case.maximum_applicable_loading_fraction,
                )
                if reason is not None:
                    return MissionAssessment(
                        scenario.mission_id,
                        AssessmentStatus.INVALID,
                        reason=f"not_applicable:{case.case_id}:{reason}",
                    )
            failures=universe.selection(candidate_ids); failed_snapshot_cache:SnapshotCache={}
            # pair failed and healthy states
            sample_groups = tuple(
                (
                    self._frequency_case_samples(
                        case,
                        scenario,
                        failures,
                        healthy_failures,
                        failed_snapshot_cache,
                        healthy_snapshot_cache,
                    )
                    for case in scenario.cases
                )
            )
            cache_key = (
                "projection",
                tuple(
                    (
                        tuple(
                            (
                                (
                                    sample.elapsed_seconds,
                                    sample.frequency_hz,
                                    dispatch_availability_projection(
                                        sample.failed_availability
                                    ),
                                    dispatch_availability_projection(
                                        sample.healthy_reference_availability
                                    ),
                                )
                                for sample in samples
                            )
                        )
                        for samples in sample_groups
                    )
                ),
            )
            cached = assessment_cache.get(cache_key)
            if cached is not None:
                return cached

            def finish(
                assessment: MissionAssessment,
            ) -> MissionAssessment:
                assessment_cache[cache_key] = assessment
                return assessment

            # later calls stop at first failure
            searches = []
            for case, samples in zip(scenario.cases, sample_groups):
                search = self._frequency_case_search(
                    case, scenario, samples, adapter
                )
                searches.append(search)
                if healthy_reference_validated and (
                    search.failed_dispatch is None
                    or not search.failed_dispatch.feasible
                ):
                    break
            searches = tuple(searches)
            # healthy reference must pass first
            invalid = next(
                (
                    (case, search)
                    for case, search in zip(scenario.cases, searches)
                    if not search.healthy_dispatch.feasible
                ),
                None,
            )
            if invalid is not None:
                case, search = invalid
                return finish(
                    MissionAssessment(
                        scenario.mission_id,
                        AssessmentStatus.INVALID,
                        reason=f"healthy_reference:{case.case_id}:{search.healthy_dispatch.reason}",
                    )
                )
            healthy_reference_validated = True
            # healthy success leaves the failed side
            failed = next(
                (
                    (case, search)
                    for case, search in zip(scenario.cases, searches)
                    if search.failed_dispatch is None
                    or not search.failed_dispatch.feasible
                ),
                None,
            )
            if failed is not None:
                case, search = failed
                reason = (
                    "failed_dispatch_not_evaluated"
                    if search.failed_dispatch is None
                    else search.failed_dispatch.reason
                )
                return finish(
                    MissionAssessment(
                        scenario.mission_id,
                        AssessmentStatus.FAILURE,
                        reason=f"{case.case_id}:{reason}",
                    )
                )
            cases = tuple((search.case for search in searches))
            if any((case is None for case in cases)):
                raise RuntimeError(
                    "feasible frequency search has no mission case"
                )
            result = mission.evaluate(
                FrequencyResponseMissionContext(
                    healthy_reference=scenario.healthy_reference,
                    cases=tuple(
                        (case for case in cases if case is not None)
                    ),
                    droop=scenario.droop,
                    target_frequency_hz=scenario.target_frequency_hz,
                    numerical_tolerance=scenario.numerical_tolerance,
                    energy_tolerance=scenario.energy_tolerance,
                    time_tolerance_seconds=scenario.time_tolerance_seconds,
                )
            )
            return finish(MissionAssessment.from_mission_result(result))

        return assess

    def _frequency_case_samples(
        self,
        case: FrequencyResponseCaseScenario,
        scenario: FrequencyResponseExperimentScenario,
        failures: FailureSelection,
        healthy_failures: FailureSelection,
        failed_snapshot_cache: SnapshotCache,
        healthy_snapshot_cache: SnapshotCache,
    ) -> tuple[FrequencyResponseAvailabilitySample, ...]:
        return tuple(
            (
                FrequencyResponseAvailabilitySample(
                    elapsed_seconds=pp.elapsed_seconds,
                    frequency_hz=pp.frequency_hz,
                    failed_availability=self._availability(
                        failures,
                        pp.availability,
                        scenario.reactive_support_mode,
                        failed_snapshot_cache,
                    ),
                    healthy_reference_availability=self._availability(
                        healthy_failures,
                        pp.availability,
                        scenario.reactive_support_mode,
                        healthy_snapshot_cache,
                    ),
                )
                for pp in case.points
            )
        )

    def _frequency_case_search(
        self,
        case: FrequencyResponseCaseScenario,
        scenario: FrequencyResponseExperimentScenario,
        samples: tuple[FrequencyResponseAvailabilitySample, ...],
        adapter: MissionCapabilityAdapter,
    ) -> FrequencyResponseCaseSearchResult:
        # failed hardware changes accessible energy
        e_bad = samples[
            0
        ].failed_availability.snapshot.bess_usable_energy
        e_ok = samples[
            0
        ].healthy_reference_availability.snapshot.bess_usable_energy
        thing = FrequencyResponseSearchCase(
            case_id=case.case_id,
            service=case.service,
            baseline_power=case.baseline_power,
            samples=samples,
            fixed_high_loading_requirement_fraction=case.fixed_high_loading_requirement_fraction,
            assessment_intervals=case.assessment_intervals,
            minimum_applicable_loading_fraction=case.minimum_applicable_loading_fraction,
            maximum_applicable_loading_fraction=case.maximum_applicable_loading_fraction,
        )
        return adapter.solve_frequency_response_case(
            thing,
            scenario.boundary,
            scenario.healthy_reference,
            scenario.droop,
            scenario.target_frequency_hz,
            scenario.time_tolerance_seconds,
            e_bad,
            e_ok,
            allow_grid_import=scenario.allow_grid_import,
        )

    def _availability(
        self,
        failures: FailureSelection,
        inputs: AvailabilityInput,
        reactive_support_mode: ReactiveSupportMode,
        snapshot_cache: SnapshotCache,
    ) -> CapabilityAvailabilityPoint:
        ss = self._snapshot(
            failures, inputs, reactive_support_mode, snapshot_cache
        )
        out = CapabilityAvailabilityPoint(
            snapshot=ss,
            feasibility_parameters=inputs.feasibility,
        )
        return out

    @staticmethod
    def _effective_capability(
        failures: FailureSelection, inputs: AvailabilityInput
    ) -> PlantCapabilityParameters:
        cap=inputs.capability; limit=inputs.station_dc_autonomy_hours
        # unrelated failures dont drain station dc
        dead = bool(
            failures.node_ids & STATION_DC_AUTONOMY_TRIGGER_NODE_IDS
            or failures.connection_ids
            & STATION_DC_AUTONOMY_TRIGGER_CONNECTION_IDS
        )
        # >= ketu intentional se tamam ne timeout battery nuk llogaritet ma
        if (
            limit is not None
            and dead
            and (
                inputs.elapsed_hours_since_failure
                + _TIME_COMPARISON_TOLERANCE_HOURS
                >= limit
            )
        ):
            return replace(
                cap, station_battery_energy_available=False
            )
        return cap

    def _snapshot(
        self,
        failures: FailureSelection,
        inputs: AvailabilityInput,
        reactive_support_mode: ReactiveSupportMode,
        snapshot_cache: SnapshotCache,
    ) -> CapabilitySnapshot:
        if not isinstance(reactive_support_mode, ReactiveSupportMode):
            reactive_support_mode = ReactiveSupportMode(
                reactive_support_mode.value
            )
        cap=self._effective_capability(failures,inputs)
        # same graph state, same snapshot
        kk=(failures,cap,reactive_support_mode); old=snapshot_cache.get(kk)
        if old is not None: return old
        ss = self._capability.evaluate(
            failures, cap, reactive_support_mode
        )
        snapshot_cache[kk]=ss; return ss
