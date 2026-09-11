# equivalent classes se raw failures dalin same, mos i numero vec e vec
from __future__ import annotations

from hashlib import sha256
import json

from pvbess.critical_sets import (
    AssessmentStatus,
    CandidateKind,
    FailureCandidate,
    FailureUniverse,
    MinimalCriticalSetEnumerator,
)
from pvbess.experiments.harness import (
    ExperimentDefinition,
    ExperimentRunResult,
)
from pvbess.experiments.oracles import MissionOracleFactory

#class members as per the computational reductions 90->20
CLASS_MEMBERS = (
    (
        'ac_aux', "ac_aux_dc_charger_link",
        "dc_charger",
        'dc_charger_distribution_link',
    ),
    # each rack keeps its own dc path
    (
        "batt_dc_isolation_a",
        "batt_rack_a",
        "bess_dc_pcs_link_a",
        "bess_rack_dc_link_a",
    ),
    (
        "batt_dc_isolation_b",
        "batt_rack_b",
        "bess_dc_pcs_link_b",
        "bess_rack_dc_link_b",
    ),
    # one sensing-chain failure loses the rack
    (
        "batt_sensing_a",
        "information__batt_rack_a__batt_sensing_a",
        "information__batt_sensing_a__rack_bms_a",
        "information__bess_field_comms__rack_bms_a",
        "rack_bms_a",
    ),
    (
        "batt_sensing_b",
        "information__batt_rack_b__batt_sensing_b",
        "information__batt_sensing_b__rack_bms_b",
        "information__bess_field_comms__rack_bms_b",
        "rack_bms_b",
    ),
    # one control loss removes both racks
    (
        "bess_ctrl",
        "bess_field_comms",
        "information__bess_ctrl__bess_field_comms",
        "information__bess_ctrl__station_network",
    ),
    # export branches stay independent
    (
        "bess_feeder_collection_link_a",
        "bess_feeder_isolation_a",
        "bess_pcs_transformer_link_a",
        "bess_transformer_feeder_link_a",
        "bess_unit_xfmr_a",
        "information__bess_field_comms__pcs_a",
    ),
    (
        "bess_feeder_collection_link_b",
        "bess_feeder_isolation_b",
        "bess_pcs_transformer_link_b",
        "bess_transformer_feeder_link_b",
        "bess_unit_xfmr_b",
        "information__bess_field_comms__pcs_b",
    ),
    ('bms_master', "information__bess_field_comms__bms_master"),
    #backbone i perbashket, one fail is enough, seriale
    (
        "collection_main_transformer_link",
        "control_power_poi_meas_ied_link",
        "control_power_station_network_link",
        "control_power_telecontrol_gw_link",
        "dc_distribution",
        "information__poi_export__poi_meas_ied",
        "information__poi_meas_ied__station_network",
        "information__station_network__telecontrol_gw",
        "information__telecontrol_gw__tso_setpoint",
        "main_transformer_poi_breaker_link",
        "main_xfmr",
        "mv_collection",
        "poi_breaker",
        "poi_breaker_grid_link",
        "poi_meas_ied",
        "station_network",
        "telecontrol_gw",
    ),
    # primary edhe standby rrine vec se njeri mundet me majt plantin gjalle
    (
        "control_power_ppc_primary_link",
        "information__ppc_primary__station_network",
        "ppc_primary",
    ),
    (
        "control_power_ppc_standby_link",
        "information__ppc_standby__station_network",
        "ppc_peer_redundancy_link",
        "ppc_standby",
    ),
    # each pv side fails independently
    (
        "information__pv_field_comms__pv_inv_a",
        "pv_feeder_collection_link_a",
        "pv_feeder_isolation_a",
        "pv_inv_a",
        "pv_inverter_transformer_link_a",
        "pv_transformer_feeder_link_a",
        "pv_unit_xfmr_a",
    ),
    (
        "information__pv_field_comms__pv_inv_b",
        "pv_feeder_collection_link_b",
        "pv_feeder_isolation_b",
        "pv_inv_b",
        "pv_inverter_transformer_link_b",
        "pv_transformer_feeder_link_b",
        "pv_unit_xfmr_b",
    ),
    # shared control loss removes both pv sides
    (
        "information__pv_field_comms__pv_subctrl",
        "information__pv_subctrl__station_network",
        "pv_field_comms",
        "pv_subctrl",
    ),
    # each pcs can survive the other
    ('pcs_a',), ("pcs_b",),
    # source and dc link have one outcome
    ("pv_dc_link_a", "pv_source_a"),
    ("pv_dc_link_b", "pv_source_b"),
    # either route loss removes station dc backup
    ("station_battery", "station_battery_distribution_link"),
)

# search uses one id per equivalent class
REPRESENTATIVES=tuple(x[0] for x in CLASS_MEMBERS);
# edge representatives stay as connections
CONNECTION_REPRESENTATIVES = frozenset(
    {
        "bess_feeder_collection_link_a",
        "bess_feeder_collection_link_b",
        "collection_main_transformer_link",
        "control_power_ppc_primary_link",
        "control_power_ppc_standby_link",
        "information__pv_field_comms__pv_inv_a",
        "information__pv_field_comms__pv_inv_b",
        "information__pv_field_comms__pv_subctrl",
        "pv_dc_link_a",
        "pv_dc_link_b",
    }
)
# keep the raw members for expansion
MEMBERS_BY_REPRESENTATIVE=dict(zip(REPRESENTATIVES, CLASS_MEMBERS))
# results stay tied to this grouping - verify post red
CLASS_MODEL_DIGEST = sha256(
    json.dumps(CLASS_MEMBERS, separators=(",", ":")).encode("utf-8")
).hexdigest()


# MARCO merr nje id per klase, raw members i hapim me vone
REPRESENTATIVE_UNIVERSE = FailureUniverse(
    tuple(
        FailureCandidate(
            cid,
            CandidateKind.CONNECTION
            if cid in CONNECTION_REPRESENTATIVES
            else CandidateKind.NODE,
        )
        for cid in REPRESENTATIVES
    )
)


class ClassCriticalSetHarness:
    def __init__(self)->None:
        self._universe=REPRESENTATIVE_UNIVERSE; self._oracles=MissionOracleFactory()

    @property
    def method_identity(self)->str: return "direct_20_class_mcs_v1"

    def run(self,definition:ExperimentDefinition)->ExperimentRunResult:
        z=self._classification_oracle(definition)
        # z is the class oracle for this one run snusor :P
        return self._enumerate(definition,z)

    def run_if_baseline_successful(
        self, definition: ExperimentDefinition
    ):
        fn=self._classification_oracle(definition);
        # no failure search if baseline already fails
        base=fn(frozenset())
        if (base.status is not AssessmentStatus.SUCCESS):
            return (base,None)
        out=self._enumerate(definition,fn)
        return out.enumeration.baseline,out

    def _classification_oracle(self, definition: ExperimentDefinition):
        return self._oracles.build(
            definition.scenario,
            self._universe,
        )

    def _enumerate(
        self, definition: ExperimentDefinition, oracle
    ) -> ExperimentRunResult:
        en = MinimalCriticalSetEnumerator().enumerate(
            self._universe, oracle
        )
        return ExperimentRunResult(
            scenario=definition.scenario,
            enumeration=en,
        )


def expanded_count(patterns:tuple[tuple[str,...],...])->int:
    # hap classes back out
    n=0;
    for pat in patterns:
        v = 1
        for rep in pat:
            v *= (len(MEMBERS_BY_REPRESENTATIVE[rep]));
        n+=v
    return (n)
