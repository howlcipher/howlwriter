We rolled out the new alert routing last Tuesday, and by Thursday the on-call rotation was already less noisy. The old setup fired on every threshold twitch, so engineers started muting the channel. That is not a culture problem; it is a signal-to-noise problem.

I sat in on three incident reviews and counted the interruptions. P1 pages dropped from about nine a day to two. More importantly, the ones that still fired were real—disk pressure, failed circuit breakers, a certificate that actually expired. The rest got folded into a dashboard review queue instead of waking someone up.

The change was not fancy. We grouped related alerts, added a short delay before escalation, and made the runbook link mandatory. If a page does not have a runbook, it should not exist. That rule alone killed a dozen legacy checks.

There is still work to do. The weekend rotation saw one false positive when a canary metric wobbled during a deployment. We probably need to tie that alert to the deployment window. But overall, the team is sleeping better, and that is the metric I care about.
