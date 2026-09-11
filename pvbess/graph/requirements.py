# only these start dc timer, rest dont
STATION_DC_AUTONOMY_TRIGGER_NODE_IDS=frozenset({'ac_aux',"dc_charger"});
STATION_DC_AUTONOMY_TRIGGER_CONNECTION_IDS=frozenset(
 {'ac_aux_dc_charger_link',
                    "dc_charger_distribution_link"})
