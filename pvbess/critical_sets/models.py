# MCS objects
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from ..graph import FailureSelection
from ..missions import MissionResult


class CandidateKind(str,Enum): NODE='node'; CONNECTION="connection"


class AssessmentStatus(str,Enum): SUCCESS="success"; FAILURE='failure'; INVALID="invalid"


@dataclass(frozen=True)
class FailureCandidate:
    candidate_id:str; kind:CandidateKind


@dataclass(frozen=True)
class FailureUniverse:
    candidates:tuple[FailureCandidate,...]
    _candidate_by_id: dict[str, FailureCandidate] = field(
        init=False, repr=False, compare=False, hash=False
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "_candidate_by_id",
            {
                candidate.candidate_id: candidate
                for candidate in self.candidates
            },
        )

    def selection(self,candidate_ids:frozenset[str])->FailureSelection:
        # same ids, split node and wire differently on purpose
        return FailureSelection(
            node_ids=frozenset(
                candidate_id for candidate_id in candidate_ids
                if self._candidate_by_id[candidate_id].kind is CandidateKind.NODE
            ),
            connection_ids=frozenset(
                (
                    candidate_id
                    for candidate_id in candidate_ids
                    if self._candidate_by_id[candidate_id].kind
                    is CandidateKind.CONNECTION
                )
            ),
        )


@dataclass(frozen=True)
class MissionAssessment:
    mission_id:str; status:AssessmentStatus
    value:float|None=None
    threshold: float | None = None; reason:str|None=None

    @classmethod
    def from_mission_result(
        cls, result: MissionResult
    ) -> MissionAssessment:
        if (not result.demanded):
            return cls(
                mission_id=result.mission_id,
                status=AssessmentStatus.INVALID,
                value=result.value,
                threshold=result.threshold,
                reason="mission_not_demanded",
            )
        if result.success is None:
            return cls(
                mission_id=result.mission_id,
                status=AssessmentStatus.INVALID,
                value=result.value,
                threshold=result.threshold,
                reason="mission_result_not_attributable",
            )
        st=(AssessmentStatus.SUCCESS
            if result.success else AssessmentStatus.FAILURE)
        return cls(
            mission_id=result.mission_id,
            status=st,
            value=result.value,
            threshold=result.threshold,
        )


@dataclass(frozen=True)
class MinimalCriticalSet:
    candidate_ids: tuple[str, ...]

    @property
    def order(self) -> int:
        return (len(self.candidate_ids))


@dataclass(frozen=True)
class InvalidSelection:
    candidate_ids:tuple[str,...]; assessment:MissionAssessment


@dataclass(frozen=True)
class CriticalSetEnumerationResult:
    mission_id:str; algorithm:str
    baseline: MissionAssessment
    critical_sets:tuple[MinimalCriticalSet,...]; invalid_selections:tuple[InvalidSelection,...]
    complete:bool; completeness_scope:str
    failure_effect_quotient_certificate_id: str | None = None
    failure_effect_quotient_certificate_digest: str | None = None
    quotient_representative_candidate_ids: tuple[str, ...] = ()
    quotient_class_members: tuple[tuple[str, ...], ...] = ()


class MonotonicityError(RuntimeError): pass
