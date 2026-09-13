from __future__ import annotations

from .connections import build_connections, identify_connections
from .schema import (
    DependencyGroup,
    DependencyLogic,
    EdgeLayer,
    EdgeSubtype,
    GraphEdge,
    GraphNode,
    NodeRole,
    PlantGraph,
    PowerKind,
)


def _node_group(role, names, failable=True, virtual=False, capacity=None):
    return tuple(GraphNode(name, name, NodeRole(role), failable, "", virtual, capacity)
                 for name in names.split())


_POWER = {
    "": frozenset(),
    "P": frozenset({PowerKind.ACTIVE}),
    "Q": frozenset({PowerKind.REACTIVE}),
    "PQ": frozenset({PowerKind.ACTIVE, PowerKind.REACTIVE}),
}


def _edge(edge_id, source, target, kind, link=None, power=""):
    layer = (EdgeLayer.PHYSICAL if kind.endswith("_power") or kind == "actuation"
             else EdgeLayer.FUNCTIONAL if kind in ("hosts", "realises", "requires")
             else EdgeLayer.INFORMATION)
    return GraphEdge(edge_id, source, target, layer, EdgeSubtype(kind), "",
                     connection_id=link, power_kinds=_POWER[power])


def _group(group_id, target, sources, logic):
    return DependencyGroup(group_id, target, sources, DependencyLogic(logic), "")


def _nodes() -> tuple[GraphNode, ...]:
    return (
        *_node_group('boundary', 'tso_setpoint', failable=False, virtual=True),
        *_node_group('control_asset', 'telecontrol_gw poi_meas_ied ppc_primary ppc_standby'),
        *_node_group('function', 'ppc_failover', failable=False, virtual=True),
        *_node_group('logic', 'ppc_standby_path', failable=False, virtual=True),
        *_node_group('function', ' '.join(_PPC_FUNCTIONS), failable=False, virtual=True),
        *_node_group('control_asset', 'scada_hmi'),
        *_node_group('control_asset', 'eng_ws', failable=False),
        *_node_group('information_service', 'station_network'),
        *_node_group('control_asset', 'met_sensing', failable=False),
        *_node_group('information_service', 'time_sync', failable=False),
        *_node_group('physical_asset', 'ac_aux dc_charger station_battery dc_distribution'),
        *_node_group('physical_asset', 'pv_source_a pv_source_b pv_inv_a pv_inv_b', capacity=0.5),
        *_node_group('control_asset', 'pv_subctrl'),
        *_node_group('information_service', 'pv_field_comms'),
        *_node_group('physical_asset', 'pv_unit_xfmr_a pv_unit_xfmr_b pv_feeder_isolation_a pv_feeder_isolation_b', capacity=0.5),
        *_node_group('physical_asset', 'mv_collection'),
        *_node_group(
            'physical_asset',
            'batt_rack_a batt_rack_b batt_dc_isolation_a batt_dc_isolation_b pcs_a pcs_b '
            'bess_unit_xfmr_a bess_unit_xfmr_b bess_feeder_isolation_a bess_feeder_isolation_b',
            capacity=0.5,
        ),
        *_node_group('control_asset', 'bess_ctrl'),
        *_node_group('information_service', 'bess_field_comms'),
        *_node_group('control_asset', 'bms_master'),
        *_node_group('control_asset', 'batt_sensing_a batt_sensing_b rack_bms_a rack_bms_b', capacity=0.5),
        *_node_group('function', 'bms_aggregation bms_charge_limit bms_discharge_limit', failable=False, virtual=True),
        *_node_group('physical_asset', 'main_xfmr poi_breaker'),
        *_node_group('protection_asset', 'poi_protection_sensing poi_protection poi_trip_circuit'),
        *_node_group('logic', 'protective_trip_path', failable=False, virtual=True),
        *_node_group('output', 'safe_state', failable=False, virtual=True),
        *_node_group('logic', 'export_path', failable=False, virtual=True),
        *_node_group('output', 'poi_export', failable=False, virtual=True),
    )


_PPC_FUNCTIONS = (
    "ppc_setpoint_interp",
    "ppc_mode_sm",
    "ppc_state_est",
    "ppc_soc_est",
    "ppc_pwr_alloc",
    "ppc_var_alloc",
    "ppc_ramp_mgr",
    "ppc_cmd_arb",
)

def _ppc_host_edges() -> tuple[GraphEdge, ...]:
    function_hosts = tuple(
        _edge(f'{host}_hosts_{function}', host, function, 'hosts')
        for function in _PPC_FUNCTIONS
        for host in ("ppc_primary", "ppc_standby_path")
    )
    failover_hosts = tuple(
        _edge(f'{host}_hosts_ppc_failover', host, 'ppc_failover', 'hosts')
        for host in ("ppc_primary", "ppc_standby")
    )
    return function_hosts + failover_hosts


def _control_power_edges() -> tuple[GraphEdge, ...]:
    loads = (
        "telecontrol_gw",
        "poi_meas_ied",
        "ppc_primary",
        "ppc_standby",
        "scada_hmi",
        "station_network",
        "time_sync",
    )
    return (
        _edge('ac_aux_to_dc_charger', 'ac_aux', 'dc_charger', 'auxiliary_power', 'ac_aux_dc_charger_link', 'P'),
        _edge('dc_charger_to_station_battery', 'dc_charger', 'station_battery', 'dc_power', 'dc_charger_battery_link', 'P'),
        _edge('dc_charger_to_distribution', 'dc_charger', 'dc_distribution', 'dc_power', 'dc_charger_distribution_link', 'P'),
        _edge('station_battery_to_distribution', 'station_battery', 'dc_distribution', 'dc_power', 'station_battery_distribution_link', 'P'),
        *(
            _edge(f'control_power_to_{target}', 'dc_distribution', target, 'auxiliary_power', f'control_power_{target}_link', 'P')
            for target in loads
        ),
    )


def _edges() -> tuple[GraphEdge, ...]:
    return _control_power_edges() + _ppc_host_edges() + (
        _edge('external_instruction_to_telecontrol_gateway', 'tso_setpoint', 'telecontrol_gw', 'command'),
        _edge('telecontrol_command_to_station_network', 'telecontrol_gw', 'station_network', 'command'),
        _edge('local_hmi_command_to_station_network', 'scada_hmi', 'station_network', 'command'),
        _edge('station_network_command_to_setpoint_interpretation', 'station_network', 'ppc_setpoint_interp', 'command'),
        _edge('ac_aux_to_engineering_workstation', 'ac_aux', 'eng_ws', 'auxiliary_power', 'ac_aux_engineering_workstation_link', 'P'),
        _edge('engineering_workstation_to_station_network', 'eng_ws', 'station_network', 'configuration'),
        _edge('station_network_configuration_to_primary_ppc', 'station_network', 'ppc_primary', 'configuration'),
        _edge('station_network_configuration_to_standby_ppc', 'station_network', 'ppc_standby', 'configuration'),
        _edge('station_network_runtime_command_to_primary_ppc', 'station_network', 'ppc_primary', 'command'),
        _edge('primary_ppc_runtime_command_to_station_network', 'ppc_primary', 'station_network', 'command'),
        _edge('station_network_runtime_measurement_to_primary_ppc', 'station_network', 'ppc_primary', 'measurement'),
        _edge('station_network_runtime_command_to_standby_ppc', 'station_network', 'ppc_standby', 'command'),
        _edge('standby_ppc_runtime_command_to_station_network', 'ppc_standby', 'station_network', 'command'),
        _edge('station_network_runtime_measurement_to_standby_ppc', 'station_network', 'ppc_standby', 'measurement'),
        _edge('station_network_status_to_engineering_workstation', 'station_network', 'eng_ws', 'status'),
        _edge('meteorological_measurement_to_station_network', 'met_sensing', 'station_network', 'measurement'),
        _edge('station_network_met_data_to_active_power_allocation', 'station_network', 'ppc_pwr_alloc', 'measurement'),
        _edge('station_network_met_data_to_ramp_management', 'station_network', 'ppc_ramp_mgr', 'measurement'),
        _edge('poi_power_exchange_to_measurement_ied', 'poi_export', 'poi_meas_ied', 'measurement'),
        _edge('poi_measurement_ied_to_station_network', 'poi_meas_ied', 'station_network', 'measurement'),
        _edge('station_network_measurement_to_state_estimation', 'station_network', 'ppc_state_est', 'measurement'),
        _edge('station_network_measurement_to_hmi', 'station_network', 'scada_hmi', 'measurement'),
        _edge('station_network_status_to_telecontrol_gateway', 'station_network', 'telecontrol_gw', 'status'),
        _edge('time_sync_to_poi_measurement_ied', 'time_sync', 'poi_meas_ied', 'timing'),
        _edge('primary_ppc_peer_status_to_standby', 'ppc_primary', 'ppc_standby', 'status', 'ppc_peer_redundancy_link'),
        _edge('standby_ppc_peer_status_to_primary', 'ppc_standby', 'ppc_primary', 'status', 'ppc_peer_redundancy_link'),
        _edge('standby_ppc_required_by_standby_path', 'ppc_standby', 'ppc_standby_path', 'requires'),
        _edge('failover_required_by_standby_path', 'ppc_failover', 'ppc_standby_path', 'requires'),
        _edge('setpoint_interpretation_to_mode_selection', 'ppc_setpoint_interp', 'ppc_mode_sm', 'command'),
        _edge('mode_selection_to_active_power_allocation', 'ppc_mode_sm', 'ppc_pwr_alloc', 'command'),
        _edge('mode_selection_to_reactive_power_allocation', 'ppc_mode_sm', 'ppc_var_alloc', 'command'),
        _edge('mode_selection_to_ramp_management', 'ppc_mode_sm', 'ppc_ramp_mgr', 'command'),
        _edge('state_estimation_to_active_power_allocation', 'ppc_state_est', 'ppc_pwr_alloc', 'measurement'),
        _edge('state_estimation_to_reactive_power_allocation', 'ppc_state_est', 'ppc_var_alloc', 'measurement'),
        _edge('state_estimation_to_ramp_management', 'ppc_state_est', 'ppc_ramp_mgr', 'measurement'),
        _edge('bms_master_measurement_to_station_network', 'bms_master', 'station_network', 'measurement'),
        _edge('station_network_measurement_to_soc_estimation', 'station_network', 'ppc_soc_est', 'measurement'),
        _edge('soc_estimation_to_active_power_allocation', 'ppc_soc_est', 'ppc_pwr_alloc', 'measurement'),
        _edge('soc_estimation_to_ramp_management', 'ppc_soc_est', 'ppc_ramp_mgr', 'measurement'),
        _edge('active_power_allocation_to_command_arbitration', 'ppc_pwr_alloc', 'ppc_cmd_arb', 'command'),
        _edge('reactive_power_allocation_to_command_arbitration', 'ppc_var_alloc', 'ppc_cmd_arb', 'command'),
        _edge('ramp_management_to_command_arbitration', 'ppc_ramp_mgr', 'ppc_cmd_arb', 'command'),
        _edge('command_arbitration_to_station_network', 'ppc_cmd_arb', 'station_network', 'command'),
        _edge('station_network_command_to_pv_controller', 'station_network', 'pv_subctrl', 'command'),
        _edge('station_network_command_to_bess_controller', 'station_network', 'bess_ctrl', 'command'),
        _edge('pv_dc_route_a', 'pv_source_a', 'pv_inv_a', 'dc_power', 'pv_dc_link_a', 'P'),
        _edge('pv_dc_route_b', 'pv_source_b', 'pv_inv_b', 'dc_power', 'pv_dc_link_b', 'P'),
        _edge('pv_inverter_output_a', 'pv_inv_a', 'pv_unit_xfmr_a', 'ac_power', 'pv_inverter_transformer_link_a', 'PQ'),
        _edge('pv_reactive_transformer_to_inverter_a', 'pv_unit_xfmr_a', 'pv_inv_a', 'ac_power', 'pv_inverter_transformer_link_a', 'Q'),
        _edge('pv_inverter_output_b', 'pv_inv_b', 'pv_unit_xfmr_b', 'ac_power', 'pv_inverter_transformer_link_b', 'PQ'),
        _edge('pv_reactive_transformer_to_inverter_b', 'pv_unit_xfmr_b', 'pv_inv_b', 'ac_power', 'pv_inverter_transformer_link_b', 'Q'),
        _edge('pv_mv_route_a', 'pv_unit_xfmr_a', 'pv_feeder_isolation_a', 'mv_power', 'pv_transformer_feeder_link_a', 'PQ'),
        _edge('pv_reactive_feeder_to_transformer_a', 'pv_feeder_isolation_a', 'pv_unit_xfmr_a', 'mv_power', 'pv_transformer_feeder_link_a', 'Q'),
        _edge('pv_mv_route_b', 'pv_unit_xfmr_b', 'pv_feeder_isolation_b', 'mv_power', 'pv_transformer_feeder_link_b', 'PQ'),
        _edge('pv_reactive_feeder_to_transformer_b', 'pv_feeder_isolation_b', 'pv_unit_xfmr_b', 'mv_power', 'pv_transformer_feeder_link_b', 'Q'),
        _edge('pv_feeder_to_collection_a', 'pv_feeder_isolation_a', 'mv_collection', 'mv_power', 'pv_feeder_collection_link_a', 'PQ'),
        _edge('pv_reactive_collection_to_feeder_a', 'mv_collection', 'pv_feeder_isolation_a', 'mv_power', 'pv_feeder_collection_link_a', 'Q'),
        _edge('pv_feeder_to_collection_b', 'pv_feeder_isolation_b', 'mv_collection', 'mv_power', 'pv_feeder_collection_link_b', 'PQ'),
        _edge('pv_reactive_collection_to_feeder_b', 'mv_collection', 'pv_feeder_isolation_b', 'mv_power', 'pv_feeder_collection_link_b', 'Q'),
        _edge('pv_controller_command_to_field_comms', 'pv_subctrl', 'pv_field_comms', 'command'),
        _edge('pv_field_command_to_inverter_a', 'pv_field_comms', 'pv_inv_a', 'command'),
        _edge('pv_field_command_to_inverter_b', 'pv_field_comms', 'pv_inv_b', 'command'),
        _edge('pv_inverter_status_a_to_field_comms', 'pv_inv_a', 'pv_field_comms', 'status'),
        _edge('pv_inverter_status_b_to_field_comms', 'pv_inv_b', 'pv_field_comms', 'status'),
        _edge('pv_field_status_to_controller', 'pv_field_comms', 'pv_subctrl', 'status'),
        _edge('bess_discharge_rack_to_dc_isolation_a', 'batt_rack_a', 'batt_dc_isolation_a', 'dc_power', 'bess_rack_dc_link_a', 'P'),
        _edge('bess_charge_dc_isolation_to_rack_a', 'batt_dc_isolation_a', 'batt_rack_a', 'dc_power', 'bess_rack_dc_link_a', 'P'),
        _edge('bess_discharge_dc_isolation_to_pcs_a', 'batt_dc_isolation_a', 'pcs_a', 'dc_power', 'bess_dc_pcs_link_a', 'P'),
        _edge('bess_charge_pcs_to_dc_isolation_a', 'pcs_a', 'batt_dc_isolation_a', 'dc_power', 'bess_dc_pcs_link_a', 'P'),
        _edge('bess_discharge_pcs_to_unit_transformer_a', 'pcs_a', 'bess_unit_xfmr_a', 'ac_power', 'bess_pcs_transformer_link_a', 'PQ'),
        _edge('bess_charge_unit_transformer_to_pcs_a', 'bess_unit_xfmr_a', 'pcs_a', 'ac_power', 'bess_pcs_transformer_link_a', 'PQ'),
        _edge(
            'bess_discharge_transformer_to_feeder_a', 'bess_unit_xfmr_a', 'bess_feeder_isolation_a', 'mv_power', 'bess_transformer_feeder_link_a',
            'PQ',
        ),
        _edge(
            'bess_charge_feeder_to_transformer_a', 'bess_feeder_isolation_a', 'bess_unit_xfmr_a', 'mv_power', 'bess_transformer_feeder_link_a', 'PQ',
        ),
        _edge('bess_discharge_feeder_to_collection_a', 'bess_feeder_isolation_a', 'mv_collection', 'mv_power', 'bess_feeder_collection_link_a', 'PQ'),
        _edge('bess_charge_collection_to_feeder_a', 'mv_collection', 'bess_feeder_isolation_a', 'mv_power', 'bess_feeder_collection_link_a', 'PQ'),
        _edge('bess_discharge_rack_to_dc_isolation_b', 'batt_rack_b', 'batt_dc_isolation_b', 'dc_power', 'bess_rack_dc_link_b', 'P'),
        _edge('bess_charge_dc_isolation_to_rack_b', 'batt_dc_isolation_b', 'batt_rack_b', 'dc_power', 'bess_rack_dc_link_b', 'P'),
        _edge('bess_discharge_dc_isolation_to_pcs_b', 'batt_dc_isolation_b', 'pcs_b', 'dc_power', 'bess_dc_pcs_link_b', 'P'),
        _edge('bess_charge_pcs_to_dc_isolation_b', 'pcs_b', 'batt_dc_isolation_b', 'dc_power', 'bess_dc_pcs_link_b', 'P'),
        _edge('bess_discharge_pcs_to_unit_transformer_b', 'pcs_b', 'bess_unit_xfmr_b', 'ac_power', 'bess_pcs_transformer_link_b', 'PQ'),
        _edge('bess_charge_unit_transformer_to_pcs_b', 'bess_unit_xfmr_b', 'pcs_b', 'ac_power', 'bess_pcs_transformer_link_b', 'PQ'),
        _edge(
            'bess_discharge_transformer_to_feeder_b', 'bess_unit_xfmr_b', 'bess_feeder_isolation_b', 'mv_power', 'bess_transformer_feeder_link_b',
            'PQ',
        ),
        _edge(
            'bess_charge_feeder_to_transformer_b', 'bess_feeder_isolation_b', 'bess_unit_xfmr_b', 'mv_power', 'bess_transformer_feeder_link_b', 'PQ',
        ),
        _edge('bess_discharge_feeder_to_collection_b', 'bess_feeder_isolation_b', 'mv_collection', 'mv_power', 'bess_feeder_collection_link_b', 'PQ'),
        _edge('bess_charge_collection_to_feeder_b', 'mv_collection', 'bess_feeder_isolation_b', 'mv_power', 'bess_feeder_collection_link_b', 'PQ'),
        _edge('bess_controller_command_to_field_comms', 'bess_ctrl', 'bess_field_comms', 'command'),
        _edge('bess_field_command_to_pcs_a', 'bess_field_comms', 'pcs_a', 'command'),
        _edge('bess_field_command_to_pcs_b', 'bess_field_comms', 'pcs_b', 'command'),
        _edge('pcs_status_a_to_bess_field_comms', 'pcs_a', 'bess_field_comms', 'status'),
        _edge('pcs_status_b_to_bess_field_comms', 'pcs_b', 'bess_field_comms', 'status'),
        _edge('bess_field_status_to_controller', 'bess_field_comms', 'bess_ctrl', 'status'),
        _edge('battery_state_a_to_sensing', 'batt_rack_a', 'batt_sensing_a', 'measurement'),
        _edge('battery_sensing_a_to_rack_bms', 'batt_sensing_a', 'rack_bms_a', 'measurement'),
        _edge('battery_state_b_to_sensing', 'batt_rack_b', 'batt_sensing_b', 'measurement'),
        _edge('battery_sensing_b_to_rack_bms', 'batt_sensing_b', 'rack_bms_b', 'measurement'),
        _edge('rack_bms_a_measurement_to_field_comms', 'rack_bms_a', 'bess_field_comms', 'measurement'),
        _edge('rack_bms_b_measurement_to_field_comms', 'rack_bms_b', 'bess_field_comms', 'measurement'),
        _edge('bess_field_measurement_to_bms_master', 'bess_field_comms', 'bms_master', 'measurement'),
        _edge('bms_master_status_to_field_comms', 'bms_master', 'bess_field_comms', 'status'),
        _edge('rack_bms_a_actuates_dc_isolation', 'rack_bms_a', 'batt_dc_isolation_a', 'actuation'),
        _edge('rack_bms_b_actuates_dc_isolation', 'rack_bms_b', 'batt_dc_isolation_b', 'actuation'),
        _edge('bms_master_hosts_aggregation', 'bms_master', 'bms_aggregation', 'hosts'),
        _edge('rack_bms_a_hosts_aggregation', 'rack_bms_a', 'bms_aggregation', 'hosts'),
        _edge('rack_bms_b_hosts_aggregation', 'rack_bms_b', 'bms_aggregation', 'hosts'),
        _edge('aggregation_realises_charge_limit', 'bms_aggregation', 'bms_charge_limit', 'realises'),
        _edge('aggregation_realises_discharge_limit', 'bms_aggregation', 'bms_discharge_limit', 'realises'),
        _edge('charge_limit_required_by_bess_controller', 'bms_charge_limit', 'bess_ctrl', 'requires'),
        _edge('discharge_limit_required_by_bess_controller', 'bms_discharge_limit', 'bess_ctrl', 'requires'),
        _edge('charge_limit_required_by_pcs_a', 'bms_charge_limit', 'pcs_a', 'requires'),
        _edge('charge_limit_required_by_pcs_b', 'bms_charge_limit', 'pcs_b', 'requires'),
        _edge('discharge_limit_required_by_pcs_a', 'bms_discharge_limit', 'pcs_a', 'requires'),
        _edge('discharge_limit_required_by_pcs_b', 'bms_discharge_limit', 'pcs_b', 'requires'),
        _edge('collection_to_main_transformer', 'mv_collection', 'main_xfmr', 'mv_power', 'collection_main_transformer_link', 'PQ'),
        _edge('main_transformer_to_collection', 'main_xfmr', 'mv_collection', 'mv_power', 'collection_main_transformer_link', 'PQ'),
        _edge('main_transformer_to_poi_breaker', 'main_xfmr', 'poi_breaker', 'hv_power', 'main_transformer_poi_breaker_link', 'PQ'),
        _edge('poi_breaker_to_main_transformer', 'poi_breaker', 'main_xfmr', 'hv_power', 'main_transformer_poi_breaker_link', 'PQ'),
        _edge('poi_quantity_to_protection_sensing', 'poi_export', 'poi_protection_sensing', 'measurement'),
        _edge('poi_breaker_status_to_protection_sensing', 'poi_breaker', 'poi_protection_sensing', 'status'),
        _edge('protection_sensing_to_poi_protection', 'poi_protection_sensing', 'poi_protection', 'measurement'),
        _edge('control_power_to_poi_protection', 'dc_distribution', 'poi_protection', 'auxiliary_power', 'control_power_poi_protection_link', 'P'),
        _edge(
            'control_power_to_poi_trip_circuit', 'dc_distribution', 'poi_trip_circuit', 'auxiliary_power', 'control_power_poi_trip_circuit_link', 'P',
        ),
        _edge('poi_protection_trip_to_trip_circuit', 'poi_protection', 'poi_trip_circuit', 'trip'),
        _edge('poi_trip_circuit_actuates_breaker', 'poi_trip_circuit', 'poi_breaker', 'actuation'),
        _edge('poi_protection_status_to_station_network', 'poi_protection', 'station_network', 'status'),
        _edge('station_network_configuration_to_poi_protection', 'station_network', 'poi_protection', 'configuration'),
        _edge('time_sync_to_poi_protection', 'time_sync', 'poi_protection', 'timing'),
        _edge('protection_sensing_required_by_trip_path', 'poi_protection_sensing', 'protective_trip_path', 'requires'),
        _edge('poi_protection_required_by_trip_path', 'poi_protection', 'protective_trip_path', 'requires'),
        _edge('poi_trip_circuit_required_by_trip_path', 'poi_trip_circuit', 'protective_trip_path', 'requires'),
        _edge('poi_breaker_required_by_trip_path', 'poi_breaker', 'protective_trip_path', 'requires'),
        _edge('dc_distribution_required_by_trip_path', 'dc_distribution', 'protective_trip_path', 'requires'),
        _edge('protective_trip_path_to_safe_state', 'protective_trip_path', 'safe_state', 'realises'),
        _edge('poi_breaker_to_export_path', 'poi_breaker', 'export_path', 'hv_power', 'poi_breaker_grid_link', 'PQ'),
        _edge('power_transfer_path_to_poi_breaker', 'export_path', 'poi_breaker', 'hv_power', 'poi_breaker_grid_link', 'PQ'),
        _edge('export_path_to_poi_output', 'export_path', 'poi_export', 'realises'),
    )


def _dependency_groups() -> tuple[DependencyGroup, ...]:
    return (
        _group('ppc_standby_path_requires_platform_and_failover', 'ppc_standby_path', ('ppc_standby', 'ppc_failover'), 'all'),
        _group(
            'protective_trip_path_requires_complete_chain', 'protective_trip_path',
            ('poi_protection_sensing', 'poi_protection', 'poi_trip_circuit', 'poi_breaker', 'dc_distribution'), 'all',
        ),
        _group('ppc_failover_has_available_controller_host', 'ppc_failover', ('ppc_primary', 'ppc_standby'), 'any'),
        _group('bms_aggregation_has_dedicated_host', 'bms_aggregation', ('bms_master',), 'all'),
        _group('charge_limit_requires_aggregation', 'bms_charge_limit', ('bms_aggregation',), 'all'),
        _group('discharge_limit_requires_aggregation', 'bms_discharge_limit', ('bms_aggregation',), 'all'),
        _group('safe_state_requires_trip_path', 'safe_state', ('protective_trip_path',), 'all'),
        *(
            _group(f'{function}_has_available_ppc_host', function, ('ppc_primary', 'ppc_standby_path'), 'any')
            for function in _PPC_FUNCTIONS
        ),
    )


def build_reference_graph() -> PlantGraph:
    nodes = _nodes()
    edges = identify_connections(_edges())
    return PlantGraph(
        model_id="ac_coupled_pv_bess_reference",
        label="",
        scope="",
        nodes=nodes,
        edges=edges,
        connections=build_connections(nodes, edges),
        dependency_groups=_dependency_groups(),
    )
