# mission run loop
from __future__ import annotations
from dataclasses import replace
from ...critical_sets import MissionAssessment
from ..harness import (
    CriticalSetExperimentHarness,
    ExperimentDefinition,
    ExperimentRunResult,
)
from .exact_reuse import (
    EXACT_RESULT_REUSE_CAPACITY,
    ExactResultCache,
    exact_result_key,
)
from .models import (
    ChronologicalMissionRun,
    HealthyChronology,
)


class ChronologicalMissionFailureRunner:
    def __init__(
        self,
        harness: CriticalSetExperimentHarness,
        *,
        enable_exact_result_reuse: bool = True,
        exact_result_reuse_capacity: int = EXACT_RESULT_REUSE_CAPACITY,
    ) -> None:
        self._harness = harness
        self._exact_result_cache = (
            ExactResultCache(exact_result_reuse_capacity)
            if enable_exact_result_reuse
            else None
        )

    def run(
        self,
        chronology: HealthyChronology,
        builder,
        variant_id: str,
        universe_id: str,
        onset_indices: tuple[int, ...],
    ) -> tuple[ChronologicalMissionRun, ...]:
        if len(onset_indices) != len(set(onset_indices)):
            raise ValueError("onset indices must be unique")
        if any(
            (
                ii < 0 or ii >= len(chronology.points)
                for ii in onset_indices
            )
        ):
            raise ValueError("onset index is outside the chronology")
        return tuple(
            self._run_onset(
                chronology, builder, variant_id, universe_id, onset
            )
            for onset in onset_indices
        )

    def _run_onset(
        self,
        chronology: HealthyChronology,
        builder,
        variant_id: str,
        universe_id: str,
        onset: int,
    ) -> ChronologicalMissionRun:
        # build it first, labels after
        thing = builder.build(chronology, onset)
        if thing.mission_id != builder.mission_id:
            raise RuntimeError(
                "chronological builder changed mission_id"
            )
        thing = replace(
            thing,
            scenario_id=f"{thing.scenario_id}_{variant_id}_{universe_id}",
        )
        job = ExperimentDefinition(scenario=thing); job0 = job
        # healthy case has to pass first
        base, out = self._evaluate_definition(
            job0
        )
        p0 = chronology.points[onset]
        return ChronologicalMissionRun(
            onset_index=onset,
            onset_timestamp_utc=p0.timestamp_utc,
            healthy_mode=p0.mode,
            healthy_branch_soc=p0.branch_soc_before,
            scenario=thing,
            baseline_assessment=base,
            experiment=out,
        )

    def _evaluate_definition(
        self, definition: ExperimentDefinition
    ) -> tuple[MissionAssessment, ExperimentRunResult | None]:
        cc = self._exact_result_cache
        thing = definition.scenario
        if cc is None:
            return self._harness.run_if_baseline_successful(definition)
        kk = exact_result_key(self._harness.method_identity, thing)
        old = cc.get(kk)
        if old is not None:
            base, out = old
            return base, self._job_specific_result(
                definition, out
            )
        base, out = self._harness.run_if_baseline_successful(
            definition
        )
        cc.put(kk, (base, out))
        return (base, out)

    def _job_specific_result(
        self,
        definition: ExperimentDefinition,
        cached: ExperimentRunResult | None,
    ) -> ExperimentRunResult | None:
        if cached is None:
            return None
        return replace(cached, scenario=definition.scenario)
