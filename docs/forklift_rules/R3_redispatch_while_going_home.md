# R3: re-dispatch while going home

**Ledger:** B1c (confirmed).

## Rule

1. A seize request may take a transporter that is on its wrap-up trip home (R2).
2. The transporter is not stopped and does not reverse in the middle of a path. It keeps its
   current speed, continues along its current path to that path's end node in the direction of
   travel, turns there, and then follows the route from that node to the new destination.
3. Inside a node (for example while crossing the home area from the home point to the edge
   where a path starts) the transporter instead turns at once and heads for the exit it needs,
   keeping its speed.
4. Busy time continues without a gap: the wrap-up and the new task are one busy period.

## Evidence

Model 5 probe at 96 s arrivals: 183 of 187 completed stores seized a GOING_HOME forklift on the
home connector (x = 290 px, y = 314–336 px). The state switched straight to GOING_TO_AGENT, the
sampled speed stayed at 1.0 m/s from the seize onwards, the first node entered was the home node
1.45–3.64 m ahead, and the route then ran node4 → node1 → node5 → receiving. Seize → load start
took 18.0595–27.1966 s for these and 28.0685 s for the four idle starts. The weighted mean
(24.668 s) equals the reference iteration-1 value (24.6686 s).

Inside the home node (seizes at t = 606 s and 894 s at (288.654, 299.402) and (275.259,
293.448) px), the forklift reached the home-node exit (290, 300) after 0.1474 m and 1.6132 m,
i.e. straight back along its crossing at 1 m/s.

## Not yet observed

Re-dispatch at a speed below the maximum, and inside a point-node connector.
