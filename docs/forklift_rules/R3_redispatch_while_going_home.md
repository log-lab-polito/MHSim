# R3: re-dispatch while going home

**Ledger:** B1c (confirmed).

## Rule

1. A seize request may take a transporter that is on its wrap-up trip home (R2).
2. The transporter is not stopped and does not reverse in the middle of a path. It keeps its
   current speed, continues along its current path to that path's end node in the direction of
   travel, turns there, and then follows the route from that node to the new destination.
3. Inside a node (for example while crossing the home area from the home point to the edge
   where a path starts) the transporter instead turns at once and heads for the exit it needs,
   keeping its speed. Inside a point node with a radius it drives straight from where it is to
   the point where the route's first path leaves the node.
4. When the route from that end node leaves along the same path, the transporter turns round
   where the path meets the node's edge and does not enter the node.
5. Busy time continues without a gap: the wrap-up and the new task are one busy period.

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

Two-forklift Model 5 probe (96 s arrivals): seized at t = 318 s on node4's arc at (293.187,
352.320) px, the forklift reached path5's start (280, 355) px after 1.3458 m, the straight-line
distance, at 1 m/s. Seized at t = 459.17 s on the aisle path at x = 315.57 px heading for
node4, it ran on to node4's edge (300, 355) px and entered and left the node at the same instant
(460.7275 s), back along the same path to the rack.

## Not yet observed

Re-dispatch at a speed below the maximum, and a turn onto a different path at a node with a
radius after running on to the path end.
