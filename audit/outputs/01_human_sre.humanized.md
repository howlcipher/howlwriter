We rolled out the new alert routing last Tuesday, and by Thursday the on-call rotation was already less noisy. The old setup fired on every threshold twitch, so engineers started muting the channel. The issue came down to signal-to-noise rather than team culture.

I sat in on three incident reviews and counted the interruptions. P1 pages dropped from about nine a day to two. More importantly, the ones that still fired were real—disk pressure, failed circuit breakers, a certificate that actually expired. The rest got folded into a dashboard review queue instead of waking someone up.

The change wasn't fancy. We grouped related alerts, added a short delay before escalation, and made the runbook link mandatory. If a page doesn't have a runbook, it shouldn't exist. That rule alone killed a dozen legacy checks.

There's still work to do. The weekend rotation saw one false positive when a canary metric wobbled during a deployment. We probably need to tie that alert to the deployment window. But overall, the team is sleeping better, and that's the metric I care about.