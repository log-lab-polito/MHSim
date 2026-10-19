# R9: which transporter a request gets

**Ledger:** B1g.

## Rule

1. A seize request goes to the free transporter (idle, or on its wrap-up trip home) nearest to
   the requesting agent in a straight line, measured from where the transporter actually is:
   its current position if moving, otherwise where its last movement left it, ε = 1e-4 m past
   the target along the final heading (R1).
2. Exact ties go to the earliest-created transporter.
3. The reference experiments run simultaneous events last-scheduled first. A transporter
   released at the instant a request is raised is therefore free for that request. MHSim
   defers the dispatch decision past the events already due at that instant.
4. In an area home node (Model 5) each transporter has its own home spot, 25 px apart along the
   area's centre line from (245, 280) px. It starts there and returns there, crossing the area
   in a straight line to the path that leaves it.

## Evidence

- Two- and three-forklift Model 5 probes and the three-forklift Model 2 probe: rule 1 picks the
  chosen transporter in every seize with a unique nearest one (213, 373 and 315 seizes).
- Model 5 META rows place units at (245, 280), (270, 280) and (295, 280) px, and every return
  home ends at the unit's own spot (135, 20 and 153 times).
- Unit 1 leaves (270, 280) px for path4's start (290, 300) px after 2.8285 m, the straight-line
  distance plus ε.
- At 271.86 s in the Model 2 probe, a release at the rack and a retrieve request coincide. All
  186 such retrieves went to the transporter just released there.
- The experiments set `SelectionModeForSimultaneousEvents` to LIFO.

## Open

- Rule 2 explains 200 of the 222 exact ties among transporters parked at the same point. The
  rest probably come from floating-point differences below the probe's print precision, which
  MHSim cannot reproduce.
- **Phase-locked runs.** With deterministic 60 s arrivals, a delay that is a multiple of 60 s
  and three or four transporters, every retrieve falls due at the instant a store's
  transporter is released at the rack. Whether the two are exactly simultaneous then depends
  on how two different sums of times round. That happens in AnyLogic (186 of 296 retrieves
  coincide at d = 180 s) and in MHSim alike, and it decides between a regime where retrieves
  start at the rack and one where they start from home. MHSim cannot reproduce AnyLogic's
  rounding, so these six range combinations are not a test of the transporter rules.
- Model 5's fourth home spot (320, 280) px is extrapolated.
- A retrieve's agent position (in the rack cell, at the bay exit, or at the outbound area)
  orders the free transporters the same way in every probe seize, so MHSim keeps the outbound
  area.
