# R4: Model 5 rack access point

**Ledger:** B1a (confirmed).

## Rule

Every cell of a rack bay is served from that bay's path exit: the point on the path network next
to the bay. In AnyLogic Model 5, bay 0 of the rack is served from (335, 355) px = (33.5, 35.5) m,
on the top path between node4/node1 and node (350, 355) px. The transporter does not leave the
path to reach the cell.

## Evidence

Model 5 probe, 120 s and 96 s arrivals: after STORE_LOAD_END the forklift always arrives at
(335.0, 355.0) px after 22.0709 m via node5 → node1 → node4; retrieves load at the same point and
drive 14.0709 m to outbound (430, 405) px. The cells report positions (335, 392) px.

## MHSim before this rule

Model 5 placed the shelf at (29.0–29.9, 40.5) m with a 0.9 m spur from node6, so every store and
retrieve drove a different, longer route (receiving → slot 32.84 m against 22.07 m).
