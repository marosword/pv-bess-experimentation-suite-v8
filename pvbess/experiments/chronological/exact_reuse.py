# Reuse identical mission results
from __future__ import annotations

from collections import OrderedDict
from dataclasses import replace

from ...critical_sets import MissionAssessment
from ..config import MissionExperimentScenario
from ..harness import ExperimentMethodIdentity, ExperimentRunResult


# small cache, no present need for bigger
EXACT_RESULT_REUSE_CAPACITY = 32; _NORMALIZED_SCENARIO_ID = "exact_cross_job_numerical_scenario"

ExactResultKey = tuple[
    ExperimentMethodIdentity,
    MissionExperimentScenario,
]
ExactResult = tuple[MissionAssessment, ExperimentRunResult | None]


def exact_result_key(
    method: ExperimentMethodIdentity,
    scenario: MissionExperimentScenario,
) -> ExactResultKey:
    # ignore labels in cache key
    return (
        method,
        replace(scenario, scenario_id=_NORMALIZED_SCENARIO_ID),
    )


class ExactResultCache:
    def __init__(
        self, capacity: int = EXACT_RESULT_REUSE_CAPACITY
    ) -> None:
        if capacity < 1:
            raise ValueError(
                "exact result-reuse capacity must be positive"
            )
        self._capacity = capacity
        self._entries: OrderedDict[
            ExactResultKey, ExactResult
        ] = OrderedDict()

    def get(self, key: ExactResultKey) -> ExactResult | None:
        tmp = self._entries.get(key)
        if tmp is None: return None
        self._entries.move_to_end(key)
        return tmp

    def put(self, key: ExactResultKey, result: ExactResult) -> None:
        self._entries[key] = result
        self._entries.move_to_end(key)
        if len(self._entries) > self._capacity:
            self._entries.popitem(last=False)
