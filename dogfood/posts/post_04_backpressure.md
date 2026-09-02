# Backpressure in Distributed Queue Architectures

In distributed systems, the most dangerous operational failure mode is silent unbounded buffering. When upstream producers publish messages at 50,000 requests per second while downstream worker pools can only consume 20,000 requests per second, a message queue will experience runaway memory growth.

Without explicit backpressure mechanisms, one of three disasters occurs:
1. The message broker runs out of RAM and crashes (OOM kill).
2. Processing latency stretches from 10 milliseconds to hours, rendering real-time events useless.
3. Network buffers fill up and TCP connections drop unpredictably across the cluster.

Proper systems design requires end-to-end backpressure. When downstream worker queues exceed a safe high-water mark, workers must stop pulling or throttle intake. Upstream gateways must push back on clients using HTTP 429 Too Many Requests or TCP flow control. It is always better to fail fast at the boundary than to allow an unbounded internal backlog to destroy the entire cluster.
