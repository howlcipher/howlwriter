# Database Connection Pooling and Silent Leaks

In high-throughput microservices, database connection pool exhaustion is one of the most common causes of cascading outages. A service under peak load suddenly spikes to 100% pool utilization, queries begin queueing, latency degrades from 15ms to 8000ms, and upstream callers timeout.

The root cause is rarely an undersized connection pool. In most incidents, the true culprit is a connection leak: a code path that acquires a connection from the pool, encounters an unhandled exception or unclosed transaction, and fails to return the socket back to the pool.

To prevent this:
1. Always acquire connections inside scoped context managers or deterministic defer/finally blocks.
2. Set aggressive connection acquisition timeouts (e.g., 2000ms) rather than blocking indefinitely.
3. Configure pool eviction policies like max connection lifetime (e.g., 30 minutes) and idle timeouts.
4. Export active vs idle connection pool metrics to Prometheus to catch slow leaks before traffic spikes trigger a full outage.
