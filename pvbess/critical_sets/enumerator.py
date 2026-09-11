# MARCO search, Liffiton et al. (2016, Sec. 5)
from __future__ import annotations
from collections.abc import Callable
from .antichain import BitsetAntichainIndex
from .models import (
    AssessmentStatus,
    CriticalSetEnumerationResult,
    FailureUniverse,
    InvalidSelection,
    MinimalCriticalSet,
    MissionAssessment,
    MonotonicityError,
)
from .sat_map import IncrementalSatSubsetMap

MissionOracle=Callable[[frozenset[str]],MissionAssessment];

# candidate failures -> SAT map -> unexplored combinations
# healthy combination -> block subsets
# failed combination -> shrink to MCS -> block supersets
class MinimalCriticalSetEnumerator:
    def __init__(self,verify_monotonicity:bool=True)->None: self._verify_monotonicity=verify_monotonicity

    def enumerate(
        self,
        universe: FailureUniverse,
        oracle: MissionOracle,
    ) -> CriticalSetEnumerationResult:
        self._oracle = oracle
        self._candidate_ids = tuple(candidate.candidate_id
                        for candidate in universe.candidates)
        self._candidate_index = {
            candidate_id: index
            for index, candidate_id in enumerate(self._candidate_ids)
        }
        self._cache:dict[frozenset[str],MissionAssessment]={}; self._cuts:dict[frozenset[str],MinimalCriticalSet]={}
        self._invalid:dict[frozenset[str],InvalidSelection]={}
        width=len(self._candidate_ids)
        self._minimal_failure_masks=BitsetAntichainIndex(width); self._maximal_success_masks=BitsetAntichainIndex(width)
        baseline_ids=frozenset(); baseline=self._assess(baseline_ids)
        if baseline.status is not AssessmentStatus.SUCCESS:
            raise ValueError(
                "critical-set enumeration needs a valid successful baseline"
            )
        if self._candidate_ids:
            with IncrementalSatSubsetMap(
                self._candidate_ids
            ) as subset_map:
                self._enumerate_map(subset_map)
        mids = {
            assessment.mission_id for assessment in self._cache.values()
        }
        if len(mids) != 1:
            raise ValueError(
                "the mission oracle changed mission_id during enumeration"
            )
        cuts = tuple(sorted(self._cuts.values(),
                key=lambda item:(item.order,item.candidate_ids)))
        invalid = tuple(
            self._invalid[key]
            for key in sorted(self._invalid,key=self._sort_key)
        )
        done=CriticalSetEnumerationResult(
            mission_id=baseline.mission_id,
            algorithm='MARCO_incremental_SAT_maximal_seed_mission_oracle_adaptation',
            baseline=baseline,
            critical_sets=cuts,
            invalid_selections=invalid,
            complete=not invalid,
            completeness_scope="Complete for chosen specs.",
        )
        return done

    def _enumerate_map(
        self, subset_map: IncrementalSatSubsetMap
    ) -> None:
        while True:
            seed=subset_map.maximal_unexplored_seed()
            if seed is None: return
            assessment=self._assess(seed)
            # stop here, partial list is useless
            if assessment.status is AssessmentStatus.INVALID:
                self._record_invalid(seed,assessment)
                return
            if assessment.status is AssessmentStatus.SUCCESS:
                subset_map.block_subsets(seed); continue
            cut_ids = self._shrink(seed)
            if cut_ids is None: return
            if not self._verify_minimality(cut_ids): return
            self._cuts[cut_ids] = MinimalCriticalSet(
                tuple(sorted(cut_ids))
            )
            subset_map.block_supersets(cut_ids)

    def _shrink(self, seed: frozenset[str]) -> frozenset[str] | None:
        # hiq failures nje nga nje deri sa nuk hiqet ma asnje
        current = set(seed)
        for candidate_id in sorted(seed):
            if candidate_id not in current: continue
            trial=frozenset(current-{candidate_id})
            assessment = self._assess(trial)
            if assessment.status is AssessmentStatus.FAILURE:
                current.remove(candidate_id)
            elif assessment.status is AssessmentStatus.INVALID:
                self._record_invalid(trial, assessment)
                return None
        return frozenset(current)

    #remove nga full cut qe causes failure, if still failure post removal set != minimal
    def _verify_minimality(self,cut_ids:frozenset[str])->bool: 
        for candidate_id in sorted(cut_ids):
            remaining = cut_ids - {candidate_id}
            assessment = self._assess(remaining)
            if assessment.status is AssessmentStatus.INVALID:
                self._record_invalid(remaining,assessment); return False
            if assessment.status is not AssessmentStatus.SUCCESS:
                raise RuntimeError(
                    "MARCO shrink produced a non-minimal set"
                )
        return (True)

    def _assess(
        self, candidate_ids: frozenset[str]
    ) -> MissionAssessment:
        # oracle expensive, same failures mos i llogarit prap
        cached=self._cache.get(candidate_ids)
        if cached is not None: return cached
        assessment=self._oracle(candidate_ids)
        if not isinstance(assessment, MissionAssessment):
            raise TypeError(
                "mission oracle must return MissionAssessment"
            )
        if self._verify_monotonicity:
            self._check_monotonicity(candidate_ids, assessment)
        self._cache[candidate_ids] = assessment
        return assessment

    def _check_monotonicity(
        self,
        candidate_ids: frozenset[str],
        assessment: MissionAssessment,
    ) -> None:
        if assessment.status is AssessmentStatus.INVALID:
            return
        mask = self._candidate_mask(candidate_ids)
        if assessment.status is AssessmentStatus.SUCCESS:
            if self._minimal_failure_masks.contains_subset(mask):
                raise MonotonicityError(
                    "adding failures changed into success"
                )
            if not self._maximal_success_masks.contains_superset(mask):
                self._maximal_success_masks.remove_subsets(mask)
                self._maximal_success_masks.add(mask)
            return
        if assessment.status is AssessmentStatus.FAILURE:
            if self._maximal_success_masks.contains_superset(mask):
                raise MonotonicityError(
                    "removing failures changed mission success into failure"
                )
            if not self._minimal_failure_masks.contains_subset(mask):
                self._minimal_failure_masks.remove_supersets(mask)
                self._minimal_failure_masks.add(mask)

    def _candidate_mask(self,candidate_ids:frozenset[str])->int:
        mask=0;
        for candidate_id in candidate_ids: mask |= 1 << self._candidate_index[candidate_id]
        return (mask)

    def _record_invalid(
        self,
        candidate_ids: frozenset[str],
        assessment: MissionAssessment,
    ) -> None:
        self._invalid[candidate_ids] = InvalidSelection(
            candidate_ids=tuple(sorted(candidate_ids)),
            assessment=assessment,
        )

    @staticmethod
    def _sort_key(
        candidate_ids: frozenset[str],
    ) -> tuple[int, tuple[str, ...]]:
        return (len(candidate_ids), tuple(sorted(candidate_ids)))
