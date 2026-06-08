"""Factory utilities for SimPy Model 6."""

from __future__ import annotations

from dataclasses import dataclass

import simpy

from mhsim.conveyor import (
    ConveyorNetwork,
    ConveyorPath,
    ConveyorSimpleStation,
    ConveyorSpur,
    PositionOnConveyor,
)

from .params import Model6Params


@dataclass(frozen=True)
class Model6Markup:
    network: ConveyorNetwork
    conveyor: ConveyorPath
    storage_conveyor: ConveyorPath
    unbatch_transfer_point: PositionOnConveyor
    batch_transfer_point: PositionOnConveyor
    unbatch_station: ConveyorSimpleStation
    batch_station: ConveyorSimpleStation
    storage_spur: ConveyorSpur


def create_model6_markup(
    env: simpy.Environment,
    params: Model6Params,
    *,
    on_unbatch_started=None,
) -> Model6Markup:
    """Create the AnyLogic Model 6 conveyor network and markup."""
    network = ConveyorNetwork(id="conveyorNetwork")

    conveyor = network.add_conveyor(
        ConveyorPath(
            id="conveyor",
            env=env,
            length_m=params.main_conveyor_length_m,
            speed_mps=params.conveyor_speed_mps,
            max_items=params.conveyor_capacity,
            item_length_m=params.conveyor_item_length_m,
            min_gap_m=params.conveyor_gap_m,
        )
    )
    storage_conveyor = network.add_conveyor(
        ConveyorPath(
            id="storageConveyor",
            env=env,
            length_m=params.storage_conveyor_length_m,
            speed_mps=params.conveyor_speed_mps,
            max_items=params.conveyor_capacity,
            item_length_m=params.conveyor_item_length_m,
            min_gap_m=params.conveyor_gap_m,
        )
    )

    unbatch_transfer_point = network.add_position(
        PositionOnConveyor(
            id="unbatchTransferPoint",
            conveyor=conveyor,
            offset_m=params.unbatch_transfer_offset_m,
        )
    )
    batch_transfer_point = network.add_position(
        PositionOnConveyor(
            id="batchTransferPoint",
            conveyor=conveyor,
            offset_m=params.batch_transfer_offset_m,
        )
    )

    batch_station = network.add_station(
        ConveyorSimpleStation(
            id="batchStation",
            env=env,
            conveyor=conveyor,
            offset_m=params.batch_transfer_offset_m,
            length_m=params.batch_station_length_m,
            capacity=params.station_capacity,
        )
    )
    unbatch_station = network.add_station(
        ConveyorSimpleStation(
            id="unbatchStation",
            env=env,
            conveyor=conveyor,
            offset_m=params.unbatch_transfer_offset_m,
            length_m=params.unbatch_station_length_m,
            capacity=params.station_capacity,
            on_process_started=on_unbatch_started,
        )
    )

    storage_spur = network.add_spur(
        ConveyorSpur(
            id="conveyorSpur",
            env=env,
            source_conveyor=conveyor,
            target_conveyor=storage_conveyor,
            target_offset_m=0.0,
            offset_m=params.storage_spur_offset_m,
            on_right_side=True,
        )
    )

    return Model6Markup(
        network=network,
        conveyor=conveyor,
        storage_conveyor=storage_conveyor,
        unbatch_transfer_point=unbatch_transfer_point,
        batch_transfer_point=batch_transfer_point,
        unbatch_station=unbatch_station,
        batch_station=batch_station,
        storage_spur=storage_spur,
    )

