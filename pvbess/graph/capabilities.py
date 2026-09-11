# capability graph :'|
from __future__ import annotations

from dataclasses import dataclass; from math import isfinite

from .variants import ReactiveSupportMode


REPRESENTATIVES = frozenset(
    {
        'ac_aux', "batt_dc_isolation_a",
        'batt_dc_isolation_b',
        "batt_sensing_a",
        "batt_sensing_b",
        "bess_ctrl",
        "bess_feeder_collection_link_a", 'bess_feeder_collection_link_b',
        "bms_master",
        "collection_main_transformer_link",
        "control_power_ppc_primary_link",
        "control_power_ppc_standby_link",
        "information__pv_field_comms__pv_inv_a",
        "information__pv_field_comms__pv_inv_b",
        "information__pv_field_comms__pv_subctrl",
        'pcs_a', "pcs_b",
        "pv_dc_link_a",
        "pv_dc_link_b",
        'station_battery',
    }
)


@dataclass(frozen=True, slots=True)
class FailureSelection:
    node_ids:frozenset[str]=frozenset(); connection_ids:frozenset[str]=frozenset()


@dataclass(frozen=True, slots=True)
class PlantCapabilityParameters:
    pv_availability: float
    pv_branch_ratings: tuple[float, float]
    bess_charge_ratings: tuple[float, float]
    bess_discharge_ratings: tuple[float, float]
    bess_energy_ratings: tuple[float, float]
    bess_soc: tuple[float, float]
    bess_min_soc: tuple[float, float]
    bess_max_soc: tuple[float, float]
    bess_soh: tuple[float, float]
    bms_charge_limit_factors: tuple[float, float]
    bms_discharge_limit_factors: tuple[float, float]
    pv_converter_ratings: tuple[float, float]
    bess_converter_ratings: tuple[float, float]
    station_battery_energy_available: bool

    @classmethod
    def normalized_reference(cls) -> PlantCapabilityParameters:
        # even branch split
        half=(0.5,0.5); one=(1.0,1.0); zero=(0.0,0.0)
        return cls(
            1.0,
            half,
            half,
            half,
            half,
            one,
            zero,
            one,
            one,
            one,
            one,
            half,
            half,
            True,
        )

    def __post_init__(self) -> None:
        # all numeric inputs must be finite
        vals = (
            self.pv_availability,
            *self.pv_branch_ratings,
            *self.bess_charge_ratings,
            *self.bess_discharge_ratings,
            *self.bess_energy_ratings,
            *self.bess_soc,
            *self.bess_min_soc,
            *self.bess_max_soc,
            *self.bess_soh,
            *self.bms_charge_limit_factors,
            *self.bms_discharge_limit_factors,
            *self.pv_converter_ratings,
            *self.bess_converter_ratings,
        )
        if any(not isfinite(x) for x in vals): raise ValueError('capability parameters must be finite')
        # no negative ratings
        rr = (
            *self.pv_branch_ratings,
            *self.bess_charge_ratings,
            *self.bess_discharge_ratings,
            *self.bess_energy_ratings,
            *self.pv_converter_ratings,
            *self.bess_converter_ratings,
        )
        if any(x < 0.0 for x in rr): raise ValueError("ratings cannot be negative")
        # fractions stay inside zero and one
        frac = (
            self.pv_availability,
            *self.bess_soc,
            *self.bess_min_soc,
            *self.bess_max_soc,
            *self.bess_soh,
            *self.bms_charge_limit_factors,
            *self.bms_discharge_limit_factors,
        )
        if any(not 0.0 <= x <= 1.0 for x in frac):
            raise ValueError(
                "availability, state and limit factors must be in [0, 1]"
            )
        # soc duhet brenda min max, perndryshe energy del nonsense ma vone
        if any(
            lo > x
            for lo, x in zip(self.bess_min_soc, self.bess_soc)
        ):
            raise ValueError("minimum SoC cannot exceed branch SoC")
        if any(
            x > hi
            for x, hi in zip(self.bess_soc, self.bess_max_soc)
        ):
            raise ValueError("branch SoC cannot exceed maximum SoC")
        if any(
            lo >= hi
            for lo, hi in zip(self.bess_min_soc, self.bess_max_soc)
        ):
            raise ValueError("minimum SoC must be below maximum SoC")


@dataclass(frozen=True, slots=True)
class BranchCapability:
    branch_id:str; active_power_dispatchable:float
    charge_power_dispatchable: float
    discharge_power_dispatchable: float
    usable_energy:float; energy_capacity:float
    reactive_converter_available: bool
    converter_rating: float


@dataclass(frozen=True, slots=True)
class CapabilitySnapshot:
    pv_dispatchable_power: float
    bess_dispatchable_charge_power: float
    bess_dispatchable_discharge_power: float
    bess_usable_energy: float
    bess_accessible_energy_capacity: float
    pv_branches: tuple[BranchCapability, BranchCapability]
    bess_branches: tuple[BranchCapability, BranchCapability]


class CapabilityEvaluator:
    def __init__(self,*,enable_topology_cache:bool=True)->None: pass

    def evaluate(
        self,
        failures: FailureSelection,
        parameters: PlantCapabilityParameters,
        reactive_support_mode: ReactiveSupportMode,
    ) -> CapabilitySnapshot:
        # nodes edges krejt nje set ketu, poshte na duhet vec a eshte healthy
        bad=failures.node_ids | failures.connection_ids; extra=bad-REPRESENTATIVES
        if extra:
            raise ValueError(
                f"unknown failure class representatives: {sorted(extra)}"
            )
        alive=REPRESENTATIVES-bad; has=alive.__contains__
        # shared backbone check
        main_ok = all(
            (
                has("collection_main_transformer_link"),
                has("ac_aux")
                or (
                    parameters.station_battery_energy_available
                    and has("station_battery")
                ),
                has("control_power_ppc_primary_link")
                or has("control_power_ppc_standby_link"),
            )
        )
        # PV also needs its shared controller
        pv_ok=(main_ok and has(
            "information__pv_field_comms__pv_subctrl"
        ))
        # build both pv sides
        pvs = tuple(
            self._pv_branch(
                side,
                i,
                pv_ok
                and has(f"information__pv_field_comms__pv_inv_{side}"),
                has(f"pv_dc_link_{side}"),
                parameters,
                reactive_support_mode,
            )
            for i, side in enumerate(("a", "b"))
        )
        # dy BESS paths i bojme vec se nje side mundet me ra and not the other
        bat = tuple(
            self._bess_branch(
                side,
                i,
                main_ok,
                has("bess_ctrl"),
                has(f"batt_dc_isolation_{side}"),
                has(f"batt_sensing_{side}"),
                has(f"bess_feeder_collection_link_{side}"),
                has("bms_master"),
                has(f"pcs_{side}"),
                parameters,
                reactive_support_mode,
            )
            for i, side in enumerate(("a", "b"))
        )
        # totals get shoved back in here
        snap=CapabilitySnapshot(
            sum(x.active_power_dispatchable for x in pvs),
            sum(
                x.charge_power_dispatchable
                for x in bat
            ),
            sum(x.discharge_power_dispatchable for x in bat),
            sum(x.usable_energy for x in bat),
            sum(x.energy_capacity for x in bat), pvs,
            bat
        )
        return snap

    @staticmethod
    def _pv_branch(
        branch: str,
        index: int,
        controlled_ac_path: bool,
        source_path: bool,
        parameters: PlantCapabilityParameters,
        reactive_support_mode: ReactiveSupportMode,
    ) -> BranchCapability:
        # support mode changes the reactive path
        sourceq = (
            getattr(
                reactive_support_mode, "value", reactive_support_mode
            )
            == "source_coupled"
        )
        go=controlled_ac_path and source_path
        p = (
            parameters.pv_availability
            * parameters.pv_branch_ratings[index]
            if go
            else 0.0
        )
        q = controlled_ac_path and (
            source_path and parameters.pv_availability > 0.0
            if sourceq
            else True
        )
        return BranchCapability(
            f"pv_{branch}",
            p,
            0.0,
            0.0,
            0.0,
            0.0,
            q,
            parameters.pv_converter_ratings[index],
        )

    @staticmethod
    def _bess_branch(
        branch: str,
        index: int,
        common: bool,
        controller: bool,
        dc_path: bool,
        sensing: bool,
        ac_path: bool,
        aggregation: bool,
        pcs: bool,
        parameters: PlantCapabilityParameters,
        reactive_support_mode: ReactiveSupportMode,
    ) -> BranchCapability:
        # active power don full chain, nje missing edhe ky branch del zero
        go = all(
            (
                common,
                controller,
                dc_path,
                sensing,
                ac_path,
                aggregation,
                pcs,
            )
        )
        # BMS factors derate each branch
        ch = (
            parameters.bess_charge_ratings[index]
            * parameters.bms_charge_limit_factors[index]
            if go
            else 0.0
        )
        dis = (
            parameters.bess_discharge_ratings[index]
            * parameters.bms_discharge_limit_factors[index]
            if go
            else 0.0
        )
        # energy path ma i shkurter se control path
        ep=dc_path and pcs
        # SoC sets usable energy, bounds set capacity
        Euse = (
            parameters.bess_energy_ratings[index]
            * parameters.bess_soh[index]
            * (
                parameters.bess_soc[index]
                - parameters.bess_min_soc[index]
            )
            if ep
            else 0.0
        )
        Emax = (
            parameters.bess_energy_ratings[index]
            * parameters.bess_soh[index]
            * (
                parameters.bess_max_soc[index]
                - parameters.bess_min_soc[index]
            )
            if ep
            else 0.0
        )
        # same reactive split si PV, arch choice assumptions
        sourceq = (
            getattr(
                reactive_support_mode, "value", reactive_support_mode
            )
            == "source_coupled"
        )
        q = (
            go
            if sourceq
            else all((common, controller, ac_path, pcs))
        )
        return BranchCapability(
            f"bess_{branch}",
            dis,
            ch,
            dis,
            Euse,
            Emax,
            q,
            parameters.bess_converter_ratings[index],
        )
