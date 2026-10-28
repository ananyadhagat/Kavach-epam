# KAVACH Module 04 — In-Memory Storage & Deployment Limitations

**Architecture Constraint**: In-memory Python data structures only; zero external databases, queues, or distributed caches.

---

## 1. Operational Realities & In-Memory Guarantees

The Module 04 sanitation planning service relies on in-process repository implementations:
- [`InMemoryPlanRepository`](file:///c:/Users/namra/OneDrive/Desktop/sanitation_agent/app/repositories/plan_repository.py)
- [`InMemoryIdempotencyRepository`](file:///c:/Users/namra/OneDrive/Desktop/sanitation_agent/app/repositories/idempotency_repository.py)
- [`InMemoryAuditRepository`](file:///c:/Users/namra/OneDrive/Desktop/sanitation_agent/app/repositories/audit_repository.py)
- [`InMemoryTemplateRepository`](file:///c:/Users/namra/OneDrive/Desktop/sanitation_agent/app/repositories/template_repository.py)

Each repository uses Python dictionaries/lists synchronized with `threading.Lock` to guarantee safety across concurrent threads within a single operating process.

---

## 2. Documented Production Limitations

### 2.1 Process Restart Data Loss
- **Limitation**: All generated plans, task records, idempotency hashes, and audit log entries are stored strictly in Python process RAM.
- **Impact**: Any container restart, server reboot, process crash, or blue/green deployment terminates the process memory, completely clearing historical plans and audit records.
- **Guarantee**: Application restart starts with completely clean repositories. There is zero disk-backed spillover.

### 2.2 Single-Process Scope
- **Limitation**: Repository state is isolated to the Python process in which it was instantiated.
- **Impact**: If Uvicorn or Gunicorn is configured with multiple worker processes (e.g. `--workers 4`), each worker process maintains an isolated, independent dictionary in its own address space.

### 2.3 Cross-Worker Idempotency Limitations
- **Limitation**: SHA-256 idempotency checks are evaluated against the local worker's in-memory dictionary.
- **Impact**: If a client sends two concurrent or successive requests that are routed by a load balancer to different worker processes, the second worker process will not see the first worker's idempotency record, resulting in dual plan creation.

### 2.4 Audit Trail History Scope
- **Limitation**: The audit repository maintains events in a Python list.
- **Impact**: Long-running single processes will accumulate memory proportional to the number of planning events. In-memory audit trails cannot serve as legal compliance evidence across system recycles.

---

## 3. Future Architecture Decision for Durable Multi-Worker Deployment

When the KAVACH platform graduates from the in-memory prototype phase to durable enterprise deployment, the following architecture decisions must be addressed:

1. **Distributed Idempotency & Locking Tier**:
   - Implementation of atomic, distributed key-value checks (e.g. Redis `SET key val NX EX 86400` or PostgreSQL unique constraint `(event_id, incident_id)`) to enforce cross-worker idempotency.

2. **Durable Plan & Task Storage**:
   - Relational persistence (e.g. PostgreSQL) mapping `SanitationPlanResult` and `SanitationTask` schemas to relational tables with transactional commit guarantees.

3. **Append-Only Immutable Audit Log**:
   - Storage of `PlanAuditRecord` in an immutable, append-only event store or log aggregation pipeline (e.g. OpenTelemetry / Kafka / TimescaleDB) to preserve audit trails across application lifecycles.

4. **Zero-Change Domain Invariants**:
   - The planning engine (`SanitationPlanningService`), template rules, critical-path calculations, and dispatch boundaries are completely decoupled from storage and will remain unchanged when repository interfaces (`Protocol`) are backed by external storage.
