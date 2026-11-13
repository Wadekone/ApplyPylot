# ApplyPylot eval report

- **Mode:** OFFLINE (mock LLM)
- **Run at:** 2026-11-13 15:54 UTC
- **Result:** PASSED

> Offline run: the mock LLM returns preset scores, so accuracy here only shows the pipeline,
> validation and storage work end to end. Model accuracy comes from a `--live` run.

| Metric | Value |
|---|---|
| Status accuracy (exact band) | 10/10 (100%) |
| One band off / two bands off | 0 / 0 |
| Schema + validation compliance | 10/10 |
| LLM answers with status corrected from score | 0 |
| Guardrail & storage tests | 13/13 |

| Sample | Expected | Got | Score | Result |
|---|---|---|---|---|
| delivery_lead_ecom | PASS | PASS | 8.9 | ✅ pass |
| pmo_director | PASS | PASS | 8.4 | ✅ pass |
| ai_delivery_manager | PASS | PASS | 8.1 | ✅ pass |
| program_manager_hybrid | BORDERLINE | BORDERLINE | 6.2 | ✅ pass |
| scrum_master | BORDERLINE | BORDERLINE | 5.6 | ✅ pass |
| ops_manager_ecom | BORDERLINE | BORDERLINE | 6.8 | ✅ pass |
| junior_coordinator | FAIL | FAIL | 1.8 | ✅ pass |
| backend_ic | FAIL | FAIL | 3.2 | ✅ pass |
| sales_ae | FAIL | FAIL | 1.1 | ✅ pass |
| construction_pm | FAIL | FAIL | 2.4 | ✅ pass |
