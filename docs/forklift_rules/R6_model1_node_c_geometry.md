# R6: Model 1 route geometry through node C

**Ledger:** H2 (confirmed), H5 (confirmed).

## Rule

In AnyLogic Model 1, point node C (600, 400) px has a 10 px radius. Paths `path` (from home) and
`AC` end on its boundary at (600, 390) and (590, 400); path `CB` starts at C's centre (600, 400).
The transporter follows the paths to their ends and crosses the node between them:

- Pickup (path → AC): a quarter circle of the node radius, 1.570796 m.
- Loaded (AC → CB): straight through, 1.0 m from (590, 400) to (600, 400).
- Return (CB → path): from the centre (600, 400), heading west, to (600, 390), heading north;
  measured length 1.106161 m, an S-shaped connector (below).

The return route is therefore 0.53536 m longer than a symmetric 1 m fillet at C. Measured return
route, Simulation geometry: B node 11 m, CB 9 m, node C 1.10616 m, path 5 m, home node 2 m.

## The node connector (general rule)

Inside a point node the transporter follows a connector from the incoming path's end point P
(heading t) to the outgoing path's start point Q (heading s). The fleet turn radius and the
node radius do not enter; only where the path geometries end does.

- t parallel to s and P, Q collinear: straight from P to Q.
- Both ends off the centre, so the heading lines meet ahead of P and before Q at X: with
  a = |PX|, b = |XQ|, m = min(a, b) and turn angle Δ, straight for a − m, a circular arc of
  radius m / tan(Δ/2), straight for b − m.
- One end at the node centre: with h = |PQ| / 5, corners A = P + h·t and B = Q − h·s, an arc
  at A with tangent length h, the straight from A towards B less 2h, and an arc at B with
  tangent length h.

MHSim implements this as `mhsim.routing.NodeJunction` (end offset per node, paths attached at
the centre listed per node). On the Model 1 probe the rule reproduces both measured
traversals of C (1.5707963 m and 1.1061615 m) within 7e-10 m, and every sample within 1e-8 px.
In Model 5 it gives 1 m arcs at the 10 px nodes and sharp turns at the zero-radius nodes, which
reproduces the measured store leg (22.0709 m) and home leg (27.5661 m) segment by segment.

## Evidence

MHSim's unchanged line-guided solver, run on these segment lengths from AnyLogic's 60 release
times (Model 1 probe), reproduces every return duration within 1.3e-4 s (one within 2.8e-3 s at the
sawtooth jump). Out of sample, the range-base release at t = 17.615 s gives 7.273479 s against
AnyLogic's utilisation-implied 7.2735 s; MHSim's own route gave 6.950 s.
