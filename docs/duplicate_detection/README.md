# Duplicate Detection Agent — Phase 1 Documentation

KAVACH group project · component owned by the Duplicate Detection Agent (DDA).

This directory contains the **Phase 1 specification only**. No Python implementation,
no FastAPI application, and no database are defined or created in this phase.

| Document | Purpose |
| --- | --- |
| [`architecture.md`](./architecture.md) | Standalone architecture, component responsibilities, data flow, integration options A/B. |
| [`api_contract.md`](./api_contract.md) | Versioned request/response contract for `POST /api/v1/duplicate-detection/check`, sample JSON, error behaviour. |
| [`matching_policy.md`](./matching_policy.md) | Comparators, scoring normalisation, thresholds, evidence rules, contradiction rules, decision behaviour. |
| [`integration.md`](./integration.md) | KAVACH Inter-Agent Integration Contract, upstream/downstream roles, decisions required from the team. |
| [`implementation_plan.md`](./implementation_plan.md) | Ordered milestones for Phase 2+, and the exact first coding task. |

## How to read this specification

- **Assumption** — a placeholder decision made so the component can be built before
  the group agrees. Every assumption is labelled `ASSUMPTION`.
- **Open decision** — something that must be agreed by the 10-member team before
  final integration. Every open item is labelled `TEAM-DECISION`.
- **Phase 1** is design only. Any file path such as `src/duplicate_detection/...`
  is a *proposed* future location, not something created now.

## Canonical synthetic examples

All documents use the same small synthetic dataset so examples stay consistent:

| Complaint ID | Category | Location | Reported at | Role in examples |
| --- | --- | --- | --- | --- |
| `CMP-2026-0001` | `ROAD_DAMAGE` | Central Market, north gate | `2026-10-14T09:15:00+05:30` | The **incoming** complaint in every example. |
| `CMP-2026-0000` | `ROAD_DAMAGE` | Central Market, north gate | `2026-10-14T08:40:00+05:30` | Near-identical **existing** record → `DUPLICATE`. |
| `CMP-2026-0042` | `STREETLIGHT_OUTAGE` | Central Market, north gate | `2026-10-13T20:00:00+05:30` | Same location, incompatible category → contradiction. |
| `CMP-2026-0055` | `ROAD_DAMAGE` | 8 km away, different ward | `2026-10-14T09:00:00+05:30` | Similar text, clearly different location → contradiction. |
| `CMP-2026-0060` | `ROAD_DAMAGE` | Central Market, ~30 m away | `2026-09-14T09:00:00+05:30` | Same category/location, 30 days earlier → boundary/time test. |

These IDs, category names, and location identifiers are **synthetic** and exist only
to make the specification concrete.
