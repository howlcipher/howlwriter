# API Rate Limiting Architecture

We implemented a token bucket rate limiter in our API gateway to protect backend microservices from burst traffic. Furthermore, it is worth noting that we selected Redis as the centralized state store. The algorithm allows bursts up to 200 requests while maintaining a sustained rate of 50 requests per second. This approach is pivotal for preventing service degradation during traffic spikes.
