Our product manager asked why feature flags were slowing down releases. I told her they were not the bottleneck. The problem was that we had no kill switch policy. Everyone could create a flag, nobody retired them, and after eighteen months we had 340 active flags for a product with maybe forty meaningful user segments.

We ran a two-week cleanup. We deleted 90 flags that had been fully rolled out for more than a quarter, archived 40 tied to experiments that ended last year, and marked 30 for owner review. The rest were grouped by team and given expiration dates.

The results were measurable, even if they were not dramatic. CI time for the mobile app dropped by about 12 percent because the flag evaluation table was smaller. Incident rollback time improved too. During the outage on March 3, we flipped one flag, and the error rate dropped in under two minutes.

The biggest change was cultural. Teams now ask whether a flag is worth its operational cost before adding it. That question did not come from a tool. It came from cleaning up the mess first.