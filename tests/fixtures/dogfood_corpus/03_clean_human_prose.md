# Why We Dropped MongoDB

We replaced MongoDB with PostgreSQL last year. Our data was relational from the start, and schema validation in application code became a maintenance burden. We needed foreign key constraints, ACID transactions across multiple tables, and predictable query performance. After the migration, our p99 query latency dropped from 120ms to 18ms.
