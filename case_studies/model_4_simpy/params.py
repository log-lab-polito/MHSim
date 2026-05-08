from dataclasses import dataclass

from mhsim.params import SimulationParams


@dataclass
class Model4Params(SimulationParams):
    """Parameters for the conveyor spur merge test model."""

    # Sources
    main_arrival_time_s: float = 15.0
    branch_arrival_time_s: float = 15.0

    # Process
    main_service_time_s: float = 6.0
    branch_service_time_s: float = 4.0
    downstream_service_time_s: float = 5.0

    # Shared conveyor settings from AnyLogic Model 4
    conveyor_speed_mps: float = 0.8
    conveyor_gap_m: float = 0.3
    conveyor_item_length_m: float = 1.2

    # Main conveyor
    main_conveyor_length_m: float = 30.0
    # Model 4 uses AnyLogic Convey blocks, which include waiting capacity ahead
    # of the moving conveyor path. The effective cap here mirrors that block
    # backlog so saturated spur cases keep the same merge order as AnyLogic.
    main_conveyor_max_items: int = 20

    # Branch conveyor
    branch_conveyor_length_m: float = 9.0
    branch_conveyor_max_items: int = 13

    # Spur
    spur_merge_offset_m: float = 18.0
