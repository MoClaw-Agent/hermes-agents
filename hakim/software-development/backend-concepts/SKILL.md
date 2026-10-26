---
name: backend-concepts
version: 1.0.0
description: Use when explaining or reviewing backend systems.
author: user
license: MIT
metadata:
  hermes:
    tags: [backend, distributed-systems, concurrency, caching, resilience]
    related_skills: []
---

# Backend Concepts

A compact reference of 50 backend and distributed-systems concepts. Use it to explain a topic, answer interview or study questions, review code or designs for these concerns, or connect related ideas.

## How to use this skill

- Find the relevant concept(s) below and answer from them. Expand with detail, examples, or code when the user needs more than the summary.
- When reviewing code or a design, check it against the relevant concepts and name specific risks (for example: retries without idempotency, dual writes without an outbox, cache entries with identical TTLs).
- When topics interact, say so. Common chains: idempotency + retries + backoff + jitter; outbox + message queues + dead letter queues; cache invalidation + cache stampedes; replication lag + read replicas + eventual consistency.
- Match depth to the user's level. Keep it short for quick questions, go deeper for design discussions.
- If a question goes beyond what is written here, answer from general knowledge and make clear which part is not from this reference.

## Index

1. Concurrency and data integrity (concepts 1-7, 13-14)
2. Database performance and operations (concepts 8-12, 15-20)
3. Caching (concepts 21-24)
4. Resilience and scaling (concepts 25-34)
5. Async and distributed architecture (concepts 35-50)

---

## 1. Concurrency and data integrity

1. **Race Conditions:** A bug where the outcome depends on the timing of concurrent operations, like two requests both reading a balance, then both writing back an update. Fix with locks, atomic operations, or transactions.
2. **Deadlocks:** Two or more processes each hold a resource the other needs, so none can proceed. Avoid by acquiring locks in a consistent order, using timeouts, or letting the database detect and abort one victim.
3. **Database Transactions:** A group of operations that succeed or fail as one unit. If anything fails midway, everything rolls back.
4. **ACID Properties:** Atomicity (all or nothing), Consistency (constraints always hold), Isolation (concurrent transactions don't interfere), Durability (committed data survives crashes).
5. **Isolation Levels:** Settings that trade correctness for concurrency: Read Uncommitted, Read Committed, Repeatable Read, Serializable. Higher levels prevent more anomalies (dirty reads, non-repeatable reads, phantoms) but cost throughput.
6. **Optimistic Locking:** Assume conflicts are rare. Read a version number with the row, and on update check that it hasn't changed. If it has, retry. Good for low-contention workloads.
7. **Pessimistic Locking:** Lock the row up front (`SELECT ... FOR UPDATE`) so nobody else can modify it until you finish. Safer under high contention, but it reduces concurrency and risks deadlocks.
13. **Foreign Key Constraints:** Enforce that a reference points to an existing row in another table. They prevent orphaned data and can cascade deletes or updates.
14. **Unique Constraints:** Guarantee no two rows share the same value (or combination) in the given columns. They are the reliable defense against duplicates, since app-level checks are racy.

## 2. Database performance and operations

8. **Connection Pooling:** Reuse a fixed set of open database connections instead of opening one per request. Connections are expensive to create, and databases cap how many they accept.
9. **N+1 Queries:** Fetching a list (1 query) and then querying related data once per item (N queries). Fix with joins, eager loading, or batched `IN` queries.
10. **Database Indexes:** Auxiliary data structures (usually B-trees) that let the database find rows without scanning the whole table. They speed up reads but slow writes and use storage.
11. **Query Optimization:** Making queries cheaper by selecting only needed columns, indexing filter and join columns, avoiding functions on indexed columns, and paginating sensibly.
12. **EXPLAIN ANALYZE:** Shows the query plan the database chose and, with `ANALYZE`, actually runs it and reports real timings and row counts. Use it to spot sequential scans and bad estimates.
15. **Database Migrations:** Versioned, ordered scripts that evolve the schema over time so every environment reaches the same state, and changes are reviewable and repeatable.
16. **Zero-Downtime Migrations:** Changing the schema without taking the app offline. Use the expand/contract pattern: add new structures, deploy code that works with both, backfill, then remove the old ones. Avoid long table locks.
17. **Read Replicas:** Copies of the primary database that serve read queries, offloading load from the primary. Writes still go to the primary.
18. **Replication Lag:** The delay before a write on the primary shows up on a replica. It can cause stale reads, such as a user not seeing what they just saved. Mitigate by reading from the primary after writes.
19. **Database Sharding:** Splitting data across multiple database servers by a shard key (like user ID) to scale writes and storage. It complicates cross-shard queries, joins, and rebalancing.
20. **Partitioning:** Splitting one large table into smaller pieces (by date range, hash, or list) within the same database. Queries touching one partition run faster, and old data is easy to drop.

## 3. Caching

21. **Cache Invalidation:** Deciding when cached data is stale and must be removed or refreshed. Strategies include TTLs, write-through updates, and explicit deletion on change. It is famously hard to get right.
22. **Redis Eviction:** The policy Redis uses to free memory when it hits `maxmemory`, such as `allkeys-lru`, `volatile-ttl`, or `noeviction`. Pick one that matches whether Redis is a cache or a primary store.
23. **Cache Stampedes:** When a popular key expires and many requests simultaneously miss and hammer the database to rebuild it. Prevent with request coalescing or locks, early refresh, and TTL jitter.
24. **Distributed Caching:** A cache shared across servers (Redis, Memcached) so all instances see the same data. Often uses consistent hashing to spread keys, and adds network latency and failure modes.

## 4. Resilience and scaling

25. **Idempotency:** An operation that has the same effect whether run once or many times. Typically implemented with idempotency keys so retried requests (like payments) don't duplicate work.
26. **Retry Mechanisms:** Automatically re-attempting failed operations that are likely transient. Retry only safe or idempotent operations, cap attempts, and don't retry permanent errors.
27. **Exponential Backoff:** Increasing the wait between retries (1s, 2s, 4s, 8s...) so a struggling service gets room to recover instead of being flooded.
28. **Jitter:** Adding randomness to retry delays so many clients don't retry in sync and create waves of load (the thundering herd).
29. **Circuit Breakers:** Stop calling a failing dependency after too many errors ("open" state), then periodically test it ("half-open") before resuming. This fails fast and prevents cascading failures.
30. **Rate Limiting:** Capping how many requests a client can make in a time window (token bucket, sliding window). It protects services from abuse and overload, typically returning HTTP 429.
31. **Load Balancing:** Distributing incoming traffic across multiple servers using strategies like round robin, least connections, or hashing. It improves capacity and availability.
32. **Horizontal Scaling:** Adding more machines to handle load. It scales further and tolerates failures but requires stateless services or shared state.
33. **Vertical Scaling:** Adding more CPU, RAM, or disk to a single machine. It is simple but has hardware limits and a single point of failure.
34. **Reverse Proxies:** Servers (Nginx, HAProxy, Envoy) that sit in front of your apps to handle TLS termination, routing, caching, compression, and load balancing.

## 5. Async and distributed architecture

35. **Message Queues:** Buffers that let producers send messages that consumers process later (RabbitMQ, SQS, Kafka). They decouple services and smooth out traffic spikes.
36. **Dead Letter Queues:** A holding queue for messages that repeatedly fail processing, so they don't block the main queue and can be inspected or replayed.
37. **Background Workers:** Processes that run slow or non-urgent tasks (emails, image processing, reports) outside the request cycle, usually pulling from a queue.
38. **Job Scheduling:** Running tasks at set times or intervals (cron-style). In distributed setups, make sure a job runs once rather than once per instance, using locks or leader election.
39. **Event-Driven Architecture:** Services communicate by publishing and reacting to events ("OrderPlaced") rather than calling each other directly. This gives loose coupling but makes flow harder to trace.
40. **Webhook Verification:** Confirming an incoming webhook really came from the sender, typically by checking an HMAC signature of the payload with a shared secret, and rejecting old timestamps to block replays.
41. **Webhook Retries:** Senders retry failed deliveries with backoff, so receivers must respond quickly with 2xx, process asynchronously, and handle duplicates idempotently.
42. **Eventual Consistency:** Replicas or services may briefly disagree but converge to the same state if updates stop. It is the trade-off made for availability and scale.
43. **Distributed Transactions:** Keeping operations consistent across multiple services or databases. Two-phase commit is strict but slow and fragile. Sagas use a sequence of local transactions with compensating actions instead.
44. **Outbox Pattern:** Write the event to an "outbox" table in the same transaction as your data change, then a separate process publishes it. This avoids the dual-write problem where the DB commits but the message is lost.
45. **CQRS:** Command Query Responsibility Segregation. Use separate models for writes (commands) and reads (queries), so each can be optimized and scaled independently.
46. **Event Sourcing:** Store the full sequence of events as the source of truth, and derive current state by replaying them. It gives a complete audit trail and time travel, at the cost of complexity.
47. **Backpressure:** A mechanism for a slow consumer to signal producers to slow down, or for the system to shed load, rather than letting queues and memory grow unbounded.
48. **Graceful Shutdown:** On a stop signal (SIGTERM), stop accepting new work, finish in-flight requests and jobs, close connections, then exit. It prevents dropped requests during deploys.
49. **Health Checks:** Endpoints that report whether a service is alive (liveness) and ready to take traffic (readiness). Orchestrators and load balancers use them to restart or route around unhealthy instances.
50. **Distributed Tracing:** Following a single request across many services using a trace ID propagated through each hop (OpenTelemetry, Jaeger). It shows where time is spent and where failures originate.

---

## Common combinations

- **Safe retries:** Retry Mechanisms (26) + Exponential Backoff (27) + Jitter (28) + Idempotency (25). Retries are only safe when the operation is idempotent, and backoff with jitter keeps retries from overloading a recovering service.
- **Reliable event publishing:** Outbox Pattern (44) + Message Queues (35) + Dead Letter Queues (36) + Idempotency (25). The outbox prevents lost events, and consumers must tolerate duplicates.
- **Read scaling:** Read Replicas (17) + Replication Lag (18) + Eventual Consistency (42) + Distributed Caching (24). Scaling reads means accepting some staleness.
- **Cache safety:** Cache Invalidation (21) + Cache Stampedes (23) + Redis Eviction (22). Plan for staleness, expiry storms, and memory pressure together.
- **Overload protection:** Rate Limiting (30) + Backpressure (47) + Circuit Breakers (29) + Load Balancing (31).
- **Safe deploys:** Zero-Downtime Migrations (16) + Graceful Shutdown (48) + Health Checks (49).
- **Write correctness:** Transactions (3) + Isolation Levels (5) + Optimistic or Pessimistic Locking (6, 7) + Unique Constraints (14).