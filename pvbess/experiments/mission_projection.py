# reuse key inputs
from __future__ import annotations
from ..missions import CapabilityAvailabilityPoint
from ..graph import CapabilitySnapshot


def dispatch_availability_projection(
    point: CapabilityAvailabilityPoint,
) -> tuple[object, ...]:
    # tuples end up as cache keys
    ss = point.snapshot
    tmp = (
        tuple(
            (
                branch.branch_id,
                branch.active_power_dispatchable,
                branch.converter_rating,
            )
            for branch in ss.pv_branches
        ),
        tuple(
            (
                branch.branch_id,
                branch.charge_power_dispatchable,
                branch.discharge_power_dispatchable,
                branch.usable_energy,
                branch.energy_capacity,
                branch.converter_rating,
            )
            for branch in ss.bess_branches
        ),
        point.feasibility_parameters,
    )
    return tmp


def reactive_snapshot_projection(
    snapshot: CapabilitySnapshot,
) -> tuple[object, ...]:
    thing = snapshot
    return tuple(
        (
            branch.branch_id,
            branch.converter_rating,
            branch.reactive_converter_available,
            branch.active_power_dispatchable,
            branch.discharge_power_dispatchable,
            branch.usable_energy,
        )
        for branch in (*thing.pv_branches, *thing.bess_branches)
    )
