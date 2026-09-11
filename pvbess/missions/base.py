#parent
# common bits, deliberately bare
from __future__ import annotations
from abc import ABC, abstractmethod; from dataclasses import dataclass


@dataclass(frozen=True)
class MissionContext:
    pass


@dataclass(frozen=True)
class MissionResult:
    mission_id:str; demanded:bool
    success: bool|None
    value:float|None; threshold:float|None


class Mission(ABC):
    @property
    @abstractmethod
    def mission_id(self)->str:
        ...

    @abstractmethod
    def evaluate(self, context: MissionContext) -> MissionResult:
        ...
