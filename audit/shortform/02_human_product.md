Our product manager asked why feature flags were slowing down releases. I told her they were not the bottleneck; the bottleneck was the lack of a kill switch policy. Everyone could create a flag, nobody retired them, and after eighteen months we had 340 active flags for a product with maybe forty meaningful user segments.

We ran a two-week cleanup. We deleted 90 flags that had been fully rolled out for more than a quarter, archived 40 behind experiments that ended last year, and marked 30 as needing an owner review. The rest got grouped by team and labeled with an expiration date.

The result was not dramatic, but it was measurable. CI time for the mobile app dropped by about 12 percent because the flag evaluation table was smaller. More importantly, incident rollback time improved. During the outage on March 3, we flipped one flag and the error rate dropped in under two minutes.

The real win was cultural. Teams now ask whether a flag is worth its operational cost before adding it. That question did not come from a tool; it came from cleaning up the mess first.
