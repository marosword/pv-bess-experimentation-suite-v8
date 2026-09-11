# PV smoothing, Martins et al. (2019, Sec. 2.1)
from __future__ import annotations
from collections import deque; from dataclasses import replace
from ...feasibility import FeasibilityParameters
from ...graph import CapabilityEvaluator, FailureSelection
from ...missions import (
    BranchDispatch,
    BranchEnergyState,
    CapabilityDispatch,
    CapabilityStatePoint,
    MissionCapabilityAdapter,
)
from .models import (
    BessOperatingMode,
    ChronologicalBaselineConfiguration,
    HealthyChronology,
    HealthyOperatingPoint,
    PvTimeSeries,
)


class ChronologicalSmoothingController:
    def __init__(self) -> None:
        self._capability = CapabilityEvaluator()

    def simulate(
        self,
        series: PvTimeSeries,
        configuration: ChronologicalBaselineConfiguration,
    ) -> HealthyChronology:
        tol = configuration.numerical_tolerance; aa = MissionCapabilityAdapter(tol)
        ee = self._initial_energy(configuration.capability); w = configuration.smoothing_window_hours
        pvr = sum(configuration.capability.pv_branch_ratings)
        # avoid a year start smoothing artefact
        n0 = w - 1
        old = (series.points[-n0:]
                if n0
                              else ())
        hh = deque(
            (p.capacity_factor * pvr for p in old),
            maxlen=w,
        )
        out: tuple[HealthyOperatingPoint, ...] = ()
        # history has to carry round
        # remove dependence on starting soc
        for x in range(configuration.maximum_warmup_cycles + 1):
            # start versus finish
            e0 = ee
            tmp = []
            for pp in series.points:
                hh.append(pp.capacity_factor * pvr)
                # dont use future pv information
                rr = ( sum(hh) / len(hh) )
                op, ee = self._step(
                    pp.timestamp_utc,
                    pp.capacity_factor,
                    rr,
                    ee,
                    configuration,
                    aa,
                )
                tmp.append(op)
            d0 = max(
                (
                    abs(b - a)
                    for a, b in zip(e0, ee)
                )
            )
            # stop annual energy drift
            if (x >= configuration.warmup_cycles
                    and d0 <= configuration.cyclic_energy_tolerance):
                out = tuple(tmp); break
        else:
            raise RuntimeError(
                f"healthy chronology did not reach a cyclic annual energy state within {configuration.maximum_warmup_cycles} warm-up cycles"
            )
        return HealthyChronology(
            site_id=series.site_id,
            configuration=configuration,
            points=out,
        )

    def _step(
        self,
        timestamp,
        capacity_factor: float,
        raw_reference: float,
        energy: tuple[float, float],
        configuration: ChronologicalBaselineConfiguration,
        adapter: MissionCapabilityAdapter,
    ) -> tuple[HealthyOperatingPoint, tuple[float, float]]:
        # current energy changes available headroom
        pars = self._parameters_for_energy(
            configuration.capability, energy, capacity_factor
        )
        snap = self._capability.evaluate(
            FailureSelection(),
            pars,
            configuration.reactive_support_mode,
        )
        # apply the poi limit before allocation
        rr = min(
            max(
                raw_reference, configuration.boundary.minimum_poi_power
            ),
            configuration.boundary.maximum_poi_power,
        )
        pva = snap.pv_dispatchable_power
        ee = tuple(
            (b.usable_energy for b in snap.bess_branches)
        )
        caps = tuple(
            (
                b.energy_capacity
                for b in snap.bess_branches
            )
        )
        # both power and free space matter
        clim = tuple(
            (
                min(
                    b.charge_power_dispatchable,
                    max(c - e, 0.0)
                    / configuration.charge_efficiency,
                )
                for b, e, c in zip(
                    snap.bess_branches,
                    ee,
                    caps,
                )
            )
        )
        # both power and stored energy matter
        dlim = tuple(
            (
                min(
                    b.discharge_power_dispatchable,
                    e * configuration.discharge_efficiency,
                )
                for b, e in zip(
                    snap.bess_branches, ee
                )
            )
        )
        # bess follows the moving average residual
        want_c = max(pva - rr, 0.0); want_d = max(rr - pva, 0.0)
        cc = self._allocate(want_c, clim) ; dd = self._allocate(want_d, dlim)
        ct = sum(cc); dt = sum(dd)
        # curtail what BESS cannot absorb
        if want_c > 0.0: puse = min(rr + ct, pva)
        else: puse = pva
        # charging subtracts at the POI
        junk = puse + dt - ct
        pa = self._allocate(
            puse,
            tuple(
                (
                    b.active_power_dispatchable
                    for b in snap.pv_branches
                )
            ),
        )
        # BESS discharge stays positive
        bb = tuple(
            (
                BranchDispatch(b.branch_id, x)
                for b, x in zip(
                    snap.pv_branches, pa
                )
            )
        ) + tuple(
            (
                BranchDispatch(b.branch_id, dis - ch)
                for b, ch, dis in zip(
                    snap.bess_branches, cc, dd
                )
            )
        )
        # one-hour energy update
        limits = FeasibilityParameters(
            energy_min=0.0,
            energy_max=snap.bess_accessible_energy_capacity,
            charge_efficiency=configuration.charge_efficiency,
            discharge_efficiency=configuration.discharge_efficiency,
            timestep_hours=1.0,
        )
        # baseline and missions share physical limits
        got = adapter.evaluate_state(
            CapabilityStatePoint(
                snapshot=snap,
                feasibility_parameters=limits,
                dispatch=CapabilityDispatch(
                    energy=sum(ee),
                    branches=bb,
                    branch_energy=tuple(
                        (
                            BranchEnergyState(b.branch_id, e)
                            for b, e in zip(
                                snap.bess_branches, ee
                            )
                        )
                    ),
                ),
            ),
            configuration.boundary,
        )
        if not got.feasible:
            bad = ", ".join(
                (
                    x.constraint_id
                    for x in got.checks
                    if not x.satisfied
                )
            )
            raise RuntimeError(
                f"healthy chronological dispatch is infeasible: {bad}"
            )
        # energy del nga kjo ore edhe hyn ne tjetren, mos e llogarit prap
        d0 = {
            x.branch_id: x.next_energy
            for x in got.branch_energy
        }
        enext = tuple(
            (
                d0[b.branch_id]
                for b in snap.bess_branches
            )
        )
        SoC0 = self._soc_from_energy(pars, ee)
        # record the battery mode that occurred
        m = BessOperatingMode.IDLE
        if ct > configuration.numerical_tolerance:
            m = BessOperatingMode.CHARGING
        elif dt > configuration.numerical_tolerance:
            m = BessOperatingMode.DISCHARGING
        return (
            HealthyOperatingPoint(
                timestamp_utc=timestamp,
                pv_capacity_factor=capacity_factor,
                poi_power=got.poi_active_power,
                branch_soc_before=SoC0,
                mode=m,
            ),
            enext,
        )

    @staticmethod
    def _allocate(
        requested: float, limits: tuple[float, ...]
    ) -> tuple[float, ...]:
        # split demand using available headroom
        n = sum(limits); x = min(max(requested, 0.0), n)
        if n <= 0.0: return tuple((0.0 for _ in limits))
        return tuple((x * thing / n for thing in limits))

    @staticmethod
    def _initial_energy(parameters) -> tuple[float, float]:
        # energy above minimum SoC
        return tuple(
            (
                rating * soh * (soc - minimum)
                for rating, soh, soc, minimum in zip(
                    parameters.bess_energy_ratings,
                    parameters.bess_soh,
                    parameters.bess_soc,
                    parameters.bess_min_soc,
                )
            )
        )

    @staticmethod
    def _parameters_for_energy(
        base, energy: tuple[float, float], capacity_factor: float
    ):
        tmp = tuple(
            (
                ChronologicalSmoothingController._one_soc(
                    current, rating, soh, minimum, maximum
                )
                for current, rating, soh, minimum, maximum in zip(
                    energy,
                    base.bess_energy_ratings,
                    base.bess_soh,
                    base.bess_min_soc,
                    base.bess_max_soc,
                )
            )
        )
        # updated SoC prap into graph
        return replace(
            base, pv_availability=capacity_factor, bess_soc=tmp
        )

    @staticmethod
    def _soc_from_energy(
        parameters, energy: tuple[float, ...]
    ) -> tuple[float, float]:
        return tuple(
            (
                ChronologicalSmoothingController._one_soc(
                    current, rating, soh, minimum, maximum
                )
                for current, rating, soh, minimum, maximum in zip(
                    energy,
                    parameters.bess_energy_ratings,
                    parameters.bess_soh,
                    parameters.bess_min_soc,
                    parameters.bess_max_soc,
                )
            )
        )

    @staticmethod
    def _one_soc(
        energy: float,
        rating: float,
        soh: float,
        minimum: float,
        maximum: float,
    ) -> float:
        d0 = rating * soh
        if d0 <= 0.0: return minimum
        # clamp to usable SoC range
        return min( max(minimum + energy / d0, minimum),
                                 maximum )
