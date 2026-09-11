# Setpoint tracking, NESO (2026, BC2.5.1)
# small check but the window rules sit below
from __future__ import annotations
from ..base import Mission, MissionContext, MissionResult
from .models import (
    ActivePowerMissionContext,
    ActivePowerWindow,
)


class ActivePowerTrackingMission(Mission):
    @property
    def mission_id(self) -> str:
        return 'active_power_tracking'

    def evaluate(self, context: MissionContext) -> MissionResult:
        if not isinstance(context, ActivePowerMissionContext): raise TypeError(
                "ActivePowerTrackingMission requires ActivePowerMissionContext")
        mx, ok = self._assess_window(
            context.physical_window,
        )
        eps=context.numerical_tolerance
        return MissionResult(
            mission_id=self.mission_id,
            demanded=True,
            success=ok
            and mx <= eps,
            value=mx,
            threshold=eps,
        )

    @staticmethod
    def _assess_window(
        window: ActivePowerWindow,
    ) -> tuple[float, bool]:
        ss = window.samples
        n = len(ss)
        mx = max(
            abs(
                x.feasibility.poi_active_power
                - x.setpoint_power
            )
            for x in ss
        )
        if window.interval_average_samples:
            ok = all(
                c.satisfied
                for x in ss
                for c in x.feasibility.checks
            )
        else:
            skip = {
                "next_energy_minimum",
                "next_energy_maximum",
            }
            ok = all(
                c.satisfied
                for i, x in enumerate(ss)
                for c in x.feasibility.checks
                if i < n - 1
                or (
                    c.constraint_id not in skip
                    and not c.constraint_id.startswith(
                        "next_bess_energy_"
                    )
                )
            )
        return mx, ok
