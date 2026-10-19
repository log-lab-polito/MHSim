# R1: planned overshoot and early arrival

**Ledger:** H3 (confirmed).

## Rule

Let ε = 1.0e-4 m and let D be the route length from the movement's origin to its target, both
taken at their nominal positions.

1. A movement starts from the nominal position of its origin, not from where the previous
   movement left the transporter.
2. Its speed profile is planned to come to rest at D + 2ε, i.e. 2ε beyond the target along the
   final approach.
3. The movement is complete (the destination is reached) when the transporter has travelled
   D + ε, so ε of the planned profile is still left. On a decelerating final approach the
   transporter still moves at √(2·d·ε), where d is the deceleration.

For a straight move from rest under a symmetric or trapezoidal profile the duration is therefore

    T = T_stop(D + 2ε) − √(2ε / d)

where `T_stop(L)` is the usual rest-to-rest time over L. A line-guided move (R7) brakes at the
first controller update where its stopping distance v²/(2d) has reached the distance left to
D + ε, and the move ends after D + ε of travel. Comparing against D + 2ε instead differs only
when an update falls within ε of the braking point. The two- and three-forklift Model 5 probes
have such a case: at 1053.0 s exactly 0.5 m was left to D + ε at 1 m/s, and AnyLogic braked.

## Source of ε

Measured, not fitted. On the Model 1 probe the loaded leg's profile fit gives a planned stop at
40.000200 m from the origin, and ARRIVE fires at 40.000100 m with v = 0.014142 m/s and 1.000e-4 m
left. Positions at ARRIVE are target + 0.001 px (= 1e-4 m) on every leg.

## Evidence

- Model 1 probe, loaded leg D = 40 m: 12.635000128 s on all 60 jobs; the rule gives 12.6350001 s.
- Model 1 reference benchmark, loaded leg D = 20 m: 8.930174496 s; the rule gives 8.9301745 s.
- Odometer from the nominal origin to ARRIVE is D + ε on the pickup (27.5709 m), loaded
  (40.0001 m) and return (28.10626 m) legs.

## Notes

The earlier reverted prototype fitted 9.9369e-5 m because it assumed a plan length of D. With the
start-side ε in the plan the constant is exactly the measured 1e-4 m.
