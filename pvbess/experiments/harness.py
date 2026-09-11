# scenario into MCS search
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..critical_sets import (
    CriticalSetEnumerationResult,
    MissionAssessment,
)
from .config import MissionExperimentScenario


@dataclass(frozen=True)
class ExperimentDefinition:
    scenario: MissionExperimentScenario


@dataclass(frozen=True)
class ExperimentRunResult:
    scenario: MissionExperimentScenario
    enumeration: CriticalSetEnumerationResult


ExperimentMethodIdentity = str


class CriticalSetExperimentHarness(Protocol):
    # only the two calls the runners actually need
    method_identity: ExperimentMethodIdentity

    def run(
        self, definition: ExperimentDefinition
    ) -> ExperimentRunResult: ...

    def run_if_baseline_successful(
        self, definition: ExperimentDefinition
    ) -> tuple[MissionAssessment, ExperimentRunResult | None]:
        ...
