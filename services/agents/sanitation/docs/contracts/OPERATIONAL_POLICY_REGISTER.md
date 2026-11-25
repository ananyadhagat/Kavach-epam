# KAVACH Module 04 — Operational Policy & Rule Register

**Status**: `PROVISIONAL_PROTOTYPE_ASSUMPTIONS — AWAITING_FORMAL_MUNICIPAL_APPROVAL`  
**Policy Version**: `sanitation-operational-policy-v1-draft`

> [!WARNING]
> None of the productivity rates, setup durations, container capacities, or crew rules below represent legally approved municipal sanitation policies. All numerical values are provisional engineering assumptions derived from the KAVACH prototype specification. They must NOT be deployed in production without written validation from the Municipal Sanitation Authority.

---

## 1. Task Duration & Productivity Rules

| Rule Identifier | Task Code | Configured Value | Unit | Applicable Templates | Formula / Calculation Basis | Operational Status | Approval Owner / Evidence | Missing Approvals |
|---|---|---|---|---|---|---|---|---|
| `DUR-RULE-001` | `INSPECT_AREA` | 15.0 | Minutes (fixed) | `BIN_OVERFLOW_RESPONSE`, `GARBAGE_PILE_REMOVAL` | `STANDARD_INSPECTION_DURATION` | `PROVISIONAL_ASSUMPTION` | Master Plan §8 illustrative example | Formal time-and-motion study sign-off |
| `DUR-RULE-002` | `REMOVE_WASTE` | 10.0 setup + 150.0 rate | Minutes setup / kg per hour | `BIN_OVERFLOW_RESPONSE`, `GARBAGE_PILE_REMOVAL` | `setup + (kg / 150.0) * 60` | `PROVISIONAL_ASSUMPTION` | Master Plan §8 illustrative example | Municipal solid waste productivity rate approval |
| `DUR-RULE-003` | `CLEAN_AREA` | 15.0 setup + 50.0 rate | Minutes setup / m² per hour | `BIN_OVERFLOW_RESPONSE` | `setup + (m² / 50.0) * 60` | `PROVISIONAL_ASSUMPTION` | Master Plan §8 illustrative example | Street cleaning productivity benchmarks |
| `DUR-RULE-004` | `CHECK_PATH_CLEAR` | 10.0 | Minutes (fixed) | `BIN_OVERFLOW_RESPONSE` | `STANDARD_ACCESS_CHECK_DURATION` | `PROVISIONAL_ASSUMPTION` | Prototype estimate | Access corridor verification standard |
| `DUR-RULE-005` | `DISINFECT_AREA` | 10.0 setup + 80.0 rate | Minutes setup / m² per hour | `GARBAGE_PILE_REMOVAL` | `setup + (m² / 80.0) * 60` | `PROVISIONAL_ASSUMPTION` | Prototype estimate | Public health vector control protocol |
| `DUR-RULE-006` | `RESTRICT_ACCESS` | 10.0 | Minutes (fixed) | `PUBLIC_TOILET_CLEANING` | `STANDARD_BARRICADE_SETUP_DURATION` | `PROVISIONAL_ASSUMPTION` | Prototype estimate | Facility safety protocol sign-off |
| `DUR-RULE-007` | `CLEAN_FIXTURES` | 10.0 setup + 5.0 rate | Minutes setup / fixtures per hr | `PUBLIC_TOILET_CLEANING` | `setup + (fixtures / 5.0) * 60` | `PROVISIONAL_ASSUMPTION` | Prototype estimate | Restroom sanitation productivity rate |
| `DUR-RULE-008` | `RESTORE_ACCESS` | 10.0 | Minutes (fixed) | `PUBLIC_TOILET_CLEANING` | `STANDARD_ACCESS_REOPEN_DURATION` | `PROVISIONAL_ASSUMPTION` | Prototype estimate | Facility reopening inspection checklist |
| `DUR-RULE-009` | `CORDON_AREA` | 15.0 | Minutes (fixed) | `SPILL_RESPONSE` | `STANDARD_CORDON_SETUP_DURATION` | `PROVISIONAL_ASSUMPTION` | Prototype estimate | Hazardous spill cordon standard |
| `DUR-RULE-010` | `ABSORB_SPILL` | 15.0 setup + 30.0 rate | Minutes setup / m² per hour | `SPILL_RESPONSE` | `setup + (m² / 30.0) * 60` | `PROVISIONAL_ASSUMPTION` | Prototype estimate | Chemical/liquid spill containment protocol |
| `DUR-RULE-011` | `CLEAR_AREA` | 10.0 | Minutes (fixed) | `SPILL_RESPONSE` | `STANDARD_CLEARANCE_CHECK_DURATION` | `PROVISIONAL_ASSUMPTION` | Prototype estimate | Spill clearance traction verification |

---

## 2. Resource Capacity & Quantity Rules

| Rule Identifier | Resource Code | Configured Capacity / Quantity | Unit | Applicable Task | Calculation Basis | Operational Status | Approval Owner / Evidence | Missing Approvals |
|---|---|---|---|---|---|---|---|---|
| `RES-RULE-001` | `WASTE_CONTAINERS` | 25.0 kg per container | Bag / Container | `REMOVE_WASTE` | `ceil(estimated_waste_kg / 25.0)` | `PROVISIONAL_ASSUMPTION` | Master Plan §7 illustrative example | Bag capacity specifications & municipal ergonomics limit |
| `RES-RULE-002` | `DISINFECTANT_SUPPLIES`| 0.20 kg per m² | kg | `DISINFECT_AREA` | `round(affected_area_sqm * 0.2, 2)` | `PROVISIONAL_ASSUMPTION` | Chemical manufacturer guidance draft | Department of Health dosage standards |
| `RES-RULE-003` | `ABSORBENT_MATERIAL` | 0.20 kg per m² | kg | `ABSORB_SPILL` | `round(affected_area_sqm * 0.2, 2)` | `PROVISIONAL_ASSUMPTION` | Prototype assumption | HAZMAT absorbent usage standard |
| `RES-RULE-004` | `PPE_GENERAL` | 1.0 (fixed minimum) | Set | All manual tasks | `TEMPLATE_MINIMUM` (1 per worker) | `PROVISIONAL_ASSUMPTION` | Occupational safety guideline draft | Municipal worker safety gear standard |
| `RES-RULE-005` | `INSPECTION_TOOLS` | 1.0 (fixed) | Set | `INSPECT_AREA` | `TEMPLATE_MINIMUM` | `PROVISIONAL_ASSUMPTION` | Tool checklist draft | Sanitation supervisor tool inventory standard |
| `RES-RULE-006` | `CLEANING_TOOLS` | 1.0 (fixed) | Set | `CLEAN_AREA`, `CLEAN_FIXTURES` | `TEMPLATE_MINIMUM` | `PROVISIONAL_ASSUMPTION` | Tool checklist draft | Mop/broom/scraper equipment register |
| `RES-RULE-007` | `CAUTION_SIGNS` | 1.0 (fixed) | Set | `RESTRICT_ACCESS`, `CORDON_AREA` | `TEMPLATE_MINIMUM` | `PROVISIONAL_ASSUMPTION` | Traffic & facility safety draft | Signage standard approval |

---

## 3. Crew Sizing & Worker Demand Rules

| Rule Identifier | Incident Priority | Estimated Worker Demand | Role Allocation | Calculation Basis | Operational Status | Approval Owner / Evidence | Missing Approvals |
|---|---|---|---|---|---|---|---|
| `CREW-RULE-001`| `CRITICAL` | 2 workers | 1x `LEAD_SANITATION_WORKER`, 1x `SANITATION_OPERATIVE` | `PRIORITY_CRITICAL_CREW_RULE` | `PROVISIONAL_ASSUMPTION` | Prototype crew rule | Sanitation labor agreement & safety regulation |
| `CREW-RULE-002`| `HIGH` | 2 workers | 1x `LEAD_SANITATION_WORKER`, 1x `SANITATION_OPERATIVE` | `PRIORITY_HIGH_CREW_RULE` | `PROVISIONAL_ASSUMPTION` | Prototype crew rule | Sanitation labor agreement & safety regulation |
| `CREW-RULE-003`| `MEDIUM` | 1 worker | 1x `SANITATION_OPERATIVE` | `PRIORITY_MEDIUM_CREW_RULE` | `PROVISIONAL_ASSUMPTION` | Prototype crew rule | Standard operative dispatch policy |
| `CREW-RULE-004`| `LOW` | 1 worker | 1x `SANITATION_OPERATIVE` | `PRIORITY_LOW_CREW_RULE` | `PROVISIONAL_ASSUMPTION` | Prototype crew rule | Standard operative dispatch policy |

---

## 4. Work Templates

| Template Identifier | Version | Title | Allowed Category | Allowed Incident Type | Allowed Department | Allowed Priorities | Operational Status |
|---|---|---|---|---|---|---|---|
| `BIN_OVERFLOW_RESPONSE` | `1` | Bin Overflow Cleaning and Area Clearance | `WASTE_OVERFLOW` | `BIN_OVERFLOW` | `SANITATION` | `LOW`, `MEDIUM`, `HIGH`, `CRITICAL` | `PROVISIONAL_ASSUMPTION` |
| `GARBAGE_PILE_REMOVAL` | `1` | Open Garbage Pile Clearance | `WASTE_OVERFLOW` | `GARBAGE_PILE` | `SANITATION` | `LOW`, `MEDIUM`, `HIGH`, `CRITICAL` | `PROVISIONAL_ASSUMPTION` |
| `PUBLIC_TOILET_CLEANING` | `1` | Public Toilet Sanitation and Disinfection | `FACILITY_CLEANING` | `DIRTY_PUBLIC_TOILET`, `TOILET_CLEANING` | `SANITATION` | `LOW`, `MEDIUM`, `HIGH`, `CRITICAL` | `PROVISIONAL_ASSUMPTION` |
| `SPILL_RESPONSE` | `1` | Waste Spill Containment and Response | `HAZARD_OR_SPILL`, `WASTE_OVERFLOW` | `WASTE_SPILL` | `SANITATION` | `LOW`, `MEDIUM`, `HIGH`, `CRITICAL` | `PROVISIONAL_ASSUMPTION` |
