# Root Cause Hypothesis

The sudden latency spike may indicate network packet loss between the primary cluster and the read replica. Initial metrics suggest that memory pressure on the caching layer could possibly have triggered garbage collection pauses, although disk I/O bottlenecks remain a likely contributing factor.
