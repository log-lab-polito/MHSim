# R2: release before the trip home

**Ledger:** B1b (confirmed).

## Rule

1. A block that seized a transporter (Store, Retrieve, MoveByTransporter, ReleaseTransporter)
   releases it as soon as its last handling step ends (unloading, or putting the pallet into the
   cell). The material item leaves the block at that same instant.
2. If the release policy sends transporters home and no request is waiting, the transporter then
   starts a wrap-up trip to its home location. If a request is waiting, it is served at once and
   there is no trip home.
3. The wrap-up counts as busy for utilisation, from the release until the transporter reaches
   home or is seized again (R3).

## Evidence

Model 5 probe, 120 s and 96 s arrivals: STORE_RELEASE = STORE_EXIT = DELAY_ENTER on all 150 and
187 stores, and RETRIEVE_RELEASE = RETRIEVE_EXIT on all 148 and 185 retrieves. At release the
state goes IDLE → GOING_HOME when nothing waits, or IDLE → GOING_TO_AGENT when a request waits.

## MHSim before this rule

StoreBlock and RetrieveBlock ran the trip home before releasing the forklift and forwarding the
pallet, so pallet cycle time and both release windows included the trip.
