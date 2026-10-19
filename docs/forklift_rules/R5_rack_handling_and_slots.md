# R5: time at the rack and choice of cell

**Ledger:** B1d (confirmed).

## Rule

With shelf k at height h_k = k · 1 m, elevation speed v_e and lowering speed v_l (both
0.2 m/s, the Store/Retrieve defaults), and a handling time t_h:

- A store stays at the bay's path exit for t_h + |h_k − 1 m| / v_e, moving the pallet from 1 m to
  the cell.
- A retrieve stays at the path exit for t_h + h_k / v_l, moving the pallet from the cell to 0 m.
- Apart from the handling moves below, the transporter stays at the path exit.
- A bay takes one transfer at a time. A transporter that reaches the path exit while another
  is in the rack waits there until that one is out, first come, first served
  (`StorageSlotManager.bay_access`).
- The destination cell for a store is the lowest free shelf of bay 0. A cell whose pallet is
  being retrieved stays occupied until the pallet has been picked up.

## Evidence

Model 5 probe, 120 s and 96 s arrivals: the store wait at the path exit is exactly 5.5200 /
0.5200 / 5.5200 s for shelves 0 / 1 / 2 (50–63 each), and the retrieve wait is 0.52 / 5.52 /
10.52 s. The shelf sequence 0, 1, 2, 0, 1, 2, … matches lowest-free with occupancy held until
pickup at every store.

Two- and three-forklift Model 5 probes (96 s arrivals): predicting each stay at the path exit
as max(arrival, end of the previous stay) + the transfer time above reproduces all 372 stays of
each run exactly, 60 and 32 of which had to wait.

## The handling time

t_h is three straight moves at the transporter's 10 m/s: from the path exit 1.5 m into the
aisle to its centreline, 2.2 m across (half the aisle plus half the 2.4 m cell depth), and
1.5 m back out, so t_h = (2 · 1.5 + 2.2) / 10 = 0.52 s. The transporter turns to face the rack
on arrival and backs out without turning. For the rest of the transfer it stands 1.5 m into the
rack (at (335, 370) px in Model 5, `rack_approach_heading_deg` = 90°), which is where its own
vision looks from (R8). Every probe sample matches within 1e-7 px, and all six
store/retrieve × shelf durations within 3e-12 s. The 1 m start height of a store is the
transporter's cargo height (Forklift height 1 m).

## Open

- The order of the transfer and lift steps inside the wait, the source of the 10 m/s, and
  whether the 1 m reference is the cargo height or one shelf height (both are 1 m here) rest on
  timing alone.
- Only shelves 0–2 of bay 0 were exercised. Higher shelves and other bays follow by assumption.
