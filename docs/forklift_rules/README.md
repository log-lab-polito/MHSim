# Forklift rule specs

Each file states one AnyLogic transporter behaviour that MHSim implements, in words and maths,
with the probe measurements that confirm it. MHSim code is written against these specs. Evidence
ids refer to the project's parity ledger; probe runs are produced with
`scripts/anylogic_probe.py`.

| Spec | Ledger | Behaviour |
|---|---|---|
| [R1](R1_arrival_tolerance.md) | H3 | Movements are planned past the target and arrive slightly early |
| [R2](R2_release_and_wrap_up.md) | B1b | Release happens before the trip home, which is a separate wrap-up |
| [R3](R3_redispatch_while_going_home.md) | B1c | A forklift on its way home can be seized and keeps moving |
| [R4](R4_model5_rack_access.md) | B1a | Model 5 rack cells are served from the bay's path exit |
| [R5](R5_rack_handling_and_slots.md) | B1d | Time at the rack and the choice of cell |
| [R6](R6_model1_node_c_geometry.md) | H2 | Model 1's return route passes through node C's centre |
| [R7](R7_line_guided_straight_routes.md) | H4 | Which routes follow the line-guided controller |

Constants carry their source. None is fitted to make a comparison pass.
