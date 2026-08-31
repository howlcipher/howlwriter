# Python Concurrency Patterns

When writing asynchronous Python services, prefer `asyncio.gather` for concurrent I/O operations over raw threading:

```python
async def fetch_all(urls: list[str]) -> list[dict]:
    tasks = [fetch(u) for u in urls]
    return await asyncio.gather(*tasks)
```

> "Simplicity is prerequisite for reliability." -- Edsger W. Dijkstra
