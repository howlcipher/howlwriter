# Deterministic CI/CD Artifact Caching Without Cache Poisoning

Fast CI/CD pipelines rely on aggressive dependency caching. Downloading hundreds of megabytes of npm packages or Rust crates on every single commit slows developer feedback cycles to a crawl.

However, naive cache keys like `npm-cache-{{ branch }}` frequently lead to cache poisoning: a broken intermediate build pollutes the cache, causing subsequent pull requests to fail with incomprehensible linking or dependency mismatch errors.

To achieve fast and fully deterministic CI caching:
- Key your caches strictly on cryptographic lockfile hashes: `deps-{{ hashFiles('package-lock.json') }}` or `cargo-{{ hashFiles('Cargo.lock') }}`.
- Make cache restoration read-only during pull request builds, only updating cache snapshots on post-merge main branch builds.
- Set a bounded TTL (e.g., 7 days) on cache entries to prevent accumulating obsolete compiler artifacts and stale build outputs.
- Track cache hit rate metrics in CI dashboards to identify cache thrashing early.