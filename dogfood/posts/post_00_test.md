# Flaky Tests in CI/CD

Flaky tests are one of the most frustrating problems in modern software engineering. When a test suite fails intermittently without any code changes, developers quickly lose trust in the automated test suite.

Instead of investigating real failures, engineers begin to re-run pipelines hoping for a green build. This wastes compute cycles and slows down shipping. To fix this, teams should immediately quarantine flaky tests into a separate suite and treat test reliability as a first-class operational metric.
