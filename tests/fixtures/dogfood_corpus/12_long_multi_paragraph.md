# Distributed Consensus in Practice

Building distributed systems requires choosing the right consensus algorithm for your consistency requirements. While Paxos provides the mathematical foundation for fault-tolerant state machine replication, its practical implementation is notoriously complex.

In recent years, Raft has gained widespread adoption due to its understandable leader-based architecture. Raft separates leader election, log replication, and safety into distinct subproblems, making formal verification and debugging substantially easier for engineering teams.

However, consensus protocols introduce non-trivial latency overhead. Network round-trips for leader heartbeats and quorum acknowledgments mean write operations cannot complete faster than your cluster's round-trip time. Engineers must carefully evaluate whether strong consistency is strictly required for every data path.
