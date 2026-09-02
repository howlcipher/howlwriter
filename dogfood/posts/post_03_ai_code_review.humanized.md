# AI in Code Reviews: Helpful for Unit Tests, Dangerous for Architecture

Over the last two years, engineering teams have rushed to add LLM bots to their GitHub pull request workflows. The results have been decidedly mixed.

AI assistants are good at generating mechanical test cases and listing edge cases. Give an LLM a 50-line state machine, and it can draft table-driven unit tests for boundary values, empty inputs, and null pointers in seconds. That saves developers real time on boilerplate.

High-level architectural judgment and distributed failure modes are where AI code review bots fail catastrophically. A bot may happily approve a pull request that puts an N+1 query inside a loop because the variable names look clean. It can miss distributed deadlock risks, cache stampede hazards, and subtle permission bypasses.

Treat AI review tools as deterministic linters with better pattern matching. Never rely on them to replace human engineering judgment about system architecture.