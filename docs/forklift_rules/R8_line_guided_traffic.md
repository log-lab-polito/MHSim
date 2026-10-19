# R8: interaction between line-guided transporters

**Ledger:** B1f.

## Rule

With path-guided navigation and TransporterControl's `avoidCollisions = false`, nothing is
reserved: transporters interact only through vision, on the line-guided controller's updates.

Constants: body length and width Lb = W = 1 m (Forklift agent), minimum distance to obstacle
m = 1 m (fleet default), deceleration d, speed limit vmax, ε = 1e-4 m.

1. **Updates.** On every global 0.5 s tick, every moving transporter (in creation order) first
   updates its vision and motion; then every moving transporter resolves conflicts. A transporter
   also gets a single update when it crosses a route boundary, starts a movement, is re-dispatched,
   or arrives. Route boundaries are where a path starts or ends, ε past the point: at each node
   with a radius the route passes through, on leaving the origin node and on entering the
   destination node when those have a radius; a zero-radius node is a single boundary. Ticks lie
   on the 0.5 s grid; a time within 1e-9 s of a tick is that tick, and a transporter's own
   update within 1e-6 s of a tick is that tick's. A transporter that is loading or unloading
   at a node is not updated but is still an obstacle; an idle transporter standing at a node
   is not seen. A transporter in a rack transfer (R5) has left the network: the others do not
   see it, but it keeps its own tick updates (vision and right of way, without moving) from
   where it stands in the rack, `rack_approach_m` past its path exit into the rack.
2. **Vision.** With braking distance b = v²/(2d), the look-ahead is L = Lb/2 + 1.5·b + W/2, capped
   at the remaining planned route length minus ε. Circles of radius r = W/2 + m are placed along
   the transporter's own route from min(L, r) to L; there are 2 + max(⌈(L − 3r)/(2r)⌉, 0) of them,
   evenly spaced. Another transporter is seen when its Lb × W rectangle meets any circle.
3. **Speed.** For each seen transporter not being ignored, the gap g is the distance between the
   two rectangles minus m.
   - g < ε: hard stop; the speed becomes 0 at once until the next update.
   - otherwise, if g ≤ v²/d and the other's speed along the vision direction, v_par, is below
     v: brake at d towards max(v_par, 0)/2. v_par = v_other·cos θ, with θ the other's heading
     minus the direction from the first to the last vision circle, snapped to a multiple of 90°
     within 1e-4 rad.
   - otherwise the free line-guided profile applies.
4. **Right of way.** After the motion step, a transporter that touches another (g < ε) earns the
   right to ignore it if the other also touches it, or if it stands in front of the other's
   heading; when each sees only the other, only the earlier-created one earns it. The ignore lasts
   for 1 + 2·Lb m of its own travel on its odometer (earlier-created) or 1 + 4·Lb m
   (later-created), across movements, or until the other leaves its vision. While ignoring, it
   drives on.
5. **Hand-over.** When a transporter that is ignoring another starts loading or unloading while
   the other touches it, the other gets the ignore and the first one's is cancelled. A
   transporter released after a delivery and seized again at the same node starts with a fresh
   vision state.

## Evidence

Two-forklift Model 2 probes (72 s and 48 s arrivals, 18 000 s each) reproduce reference
iterations 12 and 10 exactly. Replaying all 138 interaction clusters of their first hour under
these rules gives every one of the 273 recorded stop and restart instants with no error and every
odometer within 2 mm. Leaving out any single element breaks the match (look-ahead factor 1.0 or
2.0: 6 episodes wrong; braking window 1× or 3×: 104 / 77; no hard stop: 158; no right of way:
230; no "in front" rule: 17; no hand-over: 5).

## MHSim reproduction

`LineGuidedTraffic` (mhsim/traffic.py) implements the rule; `Router.path_boundaries` places the
boundary updates from the NodeJunction geometry. Run against the same two probes, MHSim keeps every
stop, restart and arrival of both forklifts within 1 ms until 567 s (72 s arrivals) and 1106 s (48 s
arrivals). The drift that ends the match starts on a single forklift. In the model, path11 is drawn
1.3e-5 m off the node6 and rack boundaries, so each loaded leg into the rack is 1.7e-5 m shorter
than MHSim's grid and arrives 27 µs earlier. Braking at ticks amplifies that to milliseconds, and
eventually one decision lands on the other side of a tick.

From then on the runs are different realisations of the same rules:

- **72 s arrivals.** Utilisation 0.9861 against 0.9854 and cycle time 369.7 s against 369.0 s,
  the same in every perturbed MHSim run.
- **48 s arrivals.** The fleet is saturated (99.6% utilisation), and FIFO dispatch feeds back
  into itself. A fleet that falls behind serves more old store requests from the rack, which run
  head-on into loaded forklifts on the loop and add empty trips. Over 32 MHSim runs with the delay
  perturbed by up to 3.2 ms, completions range from 352 to 366 and cycle time from 423 s to 745 s.
  The probe gives 348 and 792 s, so a single deterministic run cannot validate this case.

Two- and three-forklift Model 5 probes (96 s arrivals), with the rack rules above, R5's
one-at-a-time bay and R9:

- **Two forklifts:** MHSim matches every arrival within 1 ms until 1,201 s and within 0.1 s
  until 2,313 s.
- **Three forklifts:** every first-hour arrival of units 0 and 1 matches, and unit 2's within
  0.1 s until 2,720 s.

Two moments show the rack rules at work:

- **279.17 s:** a forklift coming out of the rack drives off at once, head-on to one 0.9 m away.
  At the 279.0 s tick, standing at (33.5, 37.0) in the rack, it touched the other and earned the
  right of way by being in front of it, while the other could not see it.
- **1,431.17 s:** another forklift comes out with the other 1.7 m away. At the 1,431.0 s tick
  the gap from inside the rack was +0.02 m, so it earned nothing and waits.

## Open

More than two transporters, other speeds, sizes or obstacle distances, collision timeouts or
resume delays, and `avoidCollisions = true` were not exercised. The creation-order tie-break is
inferred from behaviour. MHSim does not reproduce path11's off-grid drawing. During the 0.15 s
moves into and out of the rack MHSim already places the transporter at its in-rack position.
