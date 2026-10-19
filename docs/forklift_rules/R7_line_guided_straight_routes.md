# R7: which routes follow the line-guided controller

**Ledger:** H4 (confirmed).

## Rule

AnyLogic's line-guided controller takes its braking decision on its global 0.5 s cadence and at
route-boundary events, so a transporter may reach its destination still moving. This governs:

- every cornered route, and
- every straight route whose profile over its nominal distance reaches the speed limit and
  cruises.

A straight route that never reaches the speed limit follows the closed-form rest-to-rest
profile (with R1's arrival tolerance).

## Evidence

- Model 2 probe, retrieve loaded leg: storage_rack → node6 → outbound is straight, 14.0001 m at
  1 m/s. It takes 14.5001–14.9086 s, depending on the tick phase. MHSim's line-guided solver on
  AnyLogic's segment lengths reproduces all 126 legs to within 1e-6 s; the closed form is off by
  +0.08 to +0.49 s.
- Model 1 probe, loaded leg: straight, 40 m, peak 6.3 m/s against a 10 m/s limit. It takes
  12.635000128 s at every phase, the closed form with R1. The line-guided solver would give
  10.04–11.72 s.
- Model 1 and Model 2 cornered legs follow the line-guided solver to within 1e-6 s (Model 1)
  and on average to within 0.015 s (Model 2 iteration 1).

## Consequences in MHSim

Model 2's per-leg overrides, an analytical store drop-off and an outbound target fitted to
x = 42.611 m, are no longer needed and have been removed. With R7 and the AnyLogic route
geometry the fleet default matches every probed leg.

## Open

The rule is empirical: it fits all four probed leg types, but the mechanism that makes a
never-cruising straight route exact is not identified.
