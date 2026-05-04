# SQLite Concurrency Policy

Study AI uses SQLite with `aiosqlite` by default. SQLite is reliable for local
single-node use, but writes are still serialized by the database file. Increasing
`DB_POOL_SIZE` or `DB_MAX_OVERFLOW` does not create PostgreSQL-style parallel
write throughput; it only allows more async requests to wait on the same SQLite
write lock.

## Pool Settings

- `DB_POOL_SIZE` controls how many async SQLAlchemy connections are kept ready.
- `DB_MAX_OVERFLOW` controls temporary connections above the pool size.
- `DB_BUSY_TIMEOUT_S` is the important SQLite knob for lock contention; it sets
  how long a connection waits before SQLite reports the database as busy.
- `DB_POOL_TIMEOUT_S` controls how long SQLAlchemy waits for a pool connection.

For local SQLite deployments, prefer modest pool sizes and reduce write lock
duration with batching. Larger pools can increase contention without improving
throughput.

## Batch-Commit Contract

High-volume paths must avoid one transaction per event or draft item.

- Long-task event persistence uses `TaskRuntime` pending event buffers and
  `append_task_events(...)`, so SSE events are flushed in batches by count or
  interval.
- Task aggregate rebuilds reuse one session and flush rows before a single
  outer commit.
- Question-library generation snapshots are materialized in memory and persisted
  as session/preview snapshots instead of committing each candidate.
- Study-material flows should emit progress through the shared task runtime and
  avoid direct per-fragment database commits.

New high-volume database writers must either:

1. accept an existing `AsyncSession` so the caller can batch a transaction, or
2. expose a plural write API that performs a single commit for many rows.

If concurrent writes or multi-user throughput becomes a product requirement,
the canonical migration path is PostgreSQL behind the existing SQLAlchemy
repository boundary, not larger SQLite pool values.
