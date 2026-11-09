"""ApplyPilot evaluation harness.

10 mock job descriptions, each with an expected outcome band. Three layers of checks:

  1. Schema compliance   - output parses and validates against JobEvaluationSchema.
  2. Output validation   - score in 0-10, status consistent with score, non-empty lists/summary,
                           and the result round-trips through SQLite.
  3. Scoring accuracy    - status lands in the expected band (exact match, or one band off
                           counts as a near-miss, not a failure, in --live mode).

Plus guardrail tests that feed deliberately malformed LLM output to the parser.

Modes:
  python eval.py          offline: deterministic mock LLM, no API key needed (CI-safe)
  python eval.py --live   real Gemini calls (needs GEMINI_API_KEY)
"""
import argparse
import logging
import json
import os
import sys
import tempfile
from dataclasses import dataclass

from rich.console import Console
from rich.table import Table

import config

console = Console()


@dataclass
class Sample:
    key: str
    title: str
    company: str
    expected: str  # PASS / BORDERLINE / FAIL
    description: str
    mock_score: float  # what the offline mock LLM returns


SAMPLES: list[Sample] = [
    Sample("delivery_lead_ecom", "Senior Software Delivery Lead", "ShopStack", "PASS",
           "Remote (US). Lead delivery of our e-commerce platform across 6 agile squads. Own release "
           "governance, PMO cadence, and portfolio reporting. Hands-on SQL for delivery metrics, comfort "
           "reviewing system architecture, and experience automating workflows. Exposure to LLM integrations "
           "and evaluation a plus. 10+ years delivery management. $185k-$215k + equity.", 8.9),
    Sample("pmo_director", "Director, PMO & Delivery Operations", "Fintegrate", "PASS",
           "Fully remote. Build and run the enterprise PMO for a 300-person engineering org. Define agile "
           "governance, intake, capacity planning and OKR tracking. Partner with architects on ERP and "
           "payments system migrations. SQL/BI fluency required; process automation experience valued. "
           "Comp $200k-$240k base.", 8.4),
    Sample("ai_delivery_manager", "Technical Delivery Manager, AI Platform", "Northwind AI", "PASS",
           "Remote-first. Drive delivery of LLM-powered features: plan roadmaps, run sprint governance, "
           "coordinate eval pipelines with ML engineers, and own launch readiness. Must read SQL and "
           "understand service architecture. 8+ years technical program/delivery management. $190k+.", 8.1),
    Sample("program_manager_hybrid", "Program Manager", "MedCore Systems", "BORDERLINE",
           "Hybrid, 3 days/week in Columbus, OH. Manage EHR integration programs with vendors. Waterfall "
           "and some agile. Status reporting, RAID logs, stakeholder comms. 5+ years PM. $120k-$135k.", 6.2),
    Sample("scrum_master", "Scrum Master", "RetailWorks", "BORDERLINE",
           "Remote. Facilitate ceremonies for two e-commerce squads, remove impediments, coach on Scrum. "
           "No people management or portfolio scope. CSM required. $105k-$120k.", 5.6),
    Sample("ops_manager_ecom", "E-commerce Operations Manager", "Bloom & Co", "BORDERLINE",
           "Remote. Own order fulfillment ops, vendor SLAs and Shopify configuration. Some SQL reporting. "
           "Limited software delivery scope; works with an outsourced dev agency. $110k-$130k.", 6.8),
    Sample("junior_coordinator", "Project Coordinator (Entry Level)", "BuildRight", "FAIL",
           "On-site in Dallas, TX. Schedule meetings, take notes, update Smartsheet. 0-2 years experience. "
           "$48k-$55k.", 1.8),
    Sample("backend_ic", "Senior Backend Engineer (Go)", "StreamCo", "FAIL",
           "Remote. Write high-throughput Go microservices, own on-call, design Kafka pipelines. Pure IC "
           "role, no delivery or program management responsibilities. $170k-$200k.", 3.2),
    Sample("sales_ae", "Enterprise Account Executive", "CloudSell", "FAIL",
           "Remote. Carry a $1.2M quota selling SaaS to enterprise retail. Prospecting, demos, negotiation. "
           "OTE $260k.", 1.1),
    Sample("construction_pm", "Construction Project Manager", "Apex Builders", "FAIL",
           "On-site, travel to job sites. Manage subcontractors, budgets and permits for commercial builds. "
           "PMP preferred. OSHA 30 required. $95k-$115k.", 2.4),
]

BAND_ORDER = ["FAIL", "BORDERLINE", "PASS"]


def make_mock_backend(samples: list[Sample]):
    """Deterministic stand-in for Gemini: returns well-formed JSON keyed off the description."""
    by_desc = {s.description: s for s in samples}

    def backend(system_prompt: str, content: str) -> str:
        desc = content.split("Job Description:\n", 1)[-1]
        s = by_desc[desc]
        return json.dumps({
            "match_score": s.mock_score,
            "role_fit_summary": f"Mock evaluation of '{s.title}' at {s.company}.",
            "key_requirements": ["delivery management", "stakeholder communication"],
            "missing_skills": [] if s.expected == "PASS" else ["scope or seniority below target"],
            "eval_status": config.status_for_score(s.mock_score),
        })
    return backend


def check_sample(sample: Sample, backend, job_id: int) -> dict:
    from database import get_job_with_evaluation, save_evaluation
    from evaluator import EvaluationError, evaluate_job_description

    result = {"sample": sample, "errors": [], "score": None, "status": None, "corrected": False, "band": "-"}
    try:
        ev, raw, corrected = evaluate_job_description(sample.description, backend=backend)
    except EvaluationError as e:
        result["errors"].append(f"schema: {e}")
        return result
    except Exception as e:
        result["errors"].append(f"backend: {type(e).__name__}: {e}")
        return result

    result.update(score=ev["match_score"], status=ev["eval_status"], corrected=corrected)

    # Output validation
    if not 0 <= ev["match_score"] <= 10:
        result["errors"].append("score out of range")
    if ev["eval_status"] != config.status_for_score(ev["match_score"]):
        result["errors"].append("status inconsistent with score")
    if not ev["key_requirements"]:
        result["errors"].append("key_requirements empty")
    if not ev["role_fit_summary"]:
        result["errors"].append("role_fit_summary empty")

    # Persistence round-trip
    save_evaluation(job_id, ev, raw)
    row = get_job_with_evaluation(job_id)
    if row is None or row["eval_status"] != ev["eval_status"] or abs(row["match_score"] - ev["match_score"]) > 1e-9 \
            or json.loads(row["key_requirements"]) != ev["key_requirements"]:
        result["errors"].append("SQLite round-trip mismatch")

    # Scoring accuracy
    distance = abs(BAND_ORDER.index(ev["eval_status"]) - BAND_ORDER.index(sample.expected))
    result["band"] = {0: "exact", 1: "near"}.get(distance, "miss")
    return result


def guardrail_tests() -> list[tuple[str, bool, str]]:
    """Malformed outputs must be rejected; inconsistent status must be corrected."""
    from evaluator import EvaluationError, parse_and_validate

    good = {"match_score": 8.0, "role_fit_summary": "ok", "key_requirements": ["x"],
            "missing_skills": [], "eval_status": "PASS"}
    must_reject = {
        "invalid JSON": "{not json",
        "score > 10": json.dumps({**good, "match_score": 11.5}),
        "negative score": json.dumps({**good, "match_score": -1}),
        "unknown status": json.dumps({**good, "eval_status": "MAYBE"}),
        "missing field": json.dumps({k: v for k, v in good.items() if k != "missing_skills"}),
        "empty summary": json.dumps({**good, "role_fit_summary": "   "}),
        "wrong list type": json.dumps({**good, "key_requirements": "SQL, Agile"}),
    }
    out = []
    for name, raw in must_reject.items():
        try:
            parse_and_validate(raw)
            out.append((f"rejects {name}", False, "accepted bad output"))
        except EvaluationError:
            out.append((f"rejects {name}", True, ""))

    ev, corrected = parse_and_validate(json.dumps({**good, "match_score": 4.0, "eval_status": "PASS"}))
    ok = corrected and ev["eval_status"] == "FAIL"
    out.append(("corrects PASS@4.0 -> FAIL", ok, "" if ok else f"got {ev['eval_status']}"))

    for score, expected in [(7.5, "PASS"), (7.4, "BORDERLINE"), (5.0, "BORDERLINE"), (4.9, "FAIL")]:
        got = config.status_for_score(score)
        out.append((f"threshold {score} -> {expected}", got == expected, "" if got == expected else f"got {got}"))
    return out


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--live", action="store_true", help="call the real Gemini API instead of the mock")
    p.add_argument("--min-exact", type=float, default=0.7,
                   help="live mode: minimum fraction of exact band matches to pass (default 0.7)")
    args = p.parse_args()
    logging.basicConfig(level=logging.ERROR)  # the guardrail test triggers an expected warning

    # Isolated scratch DB so evals never touch data/applypilot.db
    tmpdir = tempfile.mkdtemp(prefix="applypilot-eval-")
    os.environ["APPLYPILOT_DB_PATH"] = os.path.join(tmpdir, "eval.db")
    from database import get_connection, init_db, insert_job
    from evaluator import gemini_backend

    init_db()
    job_ids = {}
    with get_connection() as conn:
        for s in SAMPLES:
            insert_job(conn, {"external_id": f"eval-{s.key}", "title": s.title, "company": s.company,
                              "location": None, "source": "eval", "url": None,
                              "description": s.description, "date_posted": None})
        # dedup check: re-inserting must be a no-op
        dup_inserted = insert_job(conn, {"external_id": f"eval-{SAMPLES[0].key}", "title": "x", "company": "x",
                                         "location": None, "source": "eval", "url": None,
                                         "description": "x", "date_posted": None})
        for r in conn.execute("SELECT id, external_id FROM jobs"):
            job_ids[r["external_id"]] = r["id"]

    backend = gemini_backend if args.live else make_mock_backend(SAMPLES)
    mode = f"LIVE ({config.GEMINI_MODEL})" if args.live else "OFFLINE (mock LLM)"
    console.rule(f"ApplyPilot eval — {mode}")

    results = [check_sample(s, backend, job_ids[f"eval-{s.key}"]) for s in SAMPLES]

    table = Table(title="Sample results")
    for col in ("Sample", "Expected", "Got", "Score", "Band", "Schema/Validation"):
        table.add_column(col)
    for r in results:
        s = r["sample"]
        band_style = {"exact": "green", "near": "yellow", "miss": "red"}.get(r["band"], "dim")
        checks = "[green]ok[/]" if not r["errors"] else "[red]" + "; ".join(r["errors"]) + "[/]"
        if r["corrected"]:
            checks += " [yellow](status corrected)[/]"
        table.add_row(s.key, s.expected, r["status"] or "-",
                      f"{r['score']:.1f}" if r["score"] is not None else "-",
                      f"[{band_style}]{r['band']}[/]", checks)
    console.print(table)

    g_results = guardrail_tests()
    g_results.append(("dedup on external_id", not dup_inserted, "duplicate was inserted" if dup_inserted else ""))
    gt = Table(title="Guardrail & storage tests")
    gt.add_column("Test")
    gt.add_column("Result")
    for name, ok, note in g_results:
        gt.add_row(name, "[green]PASS[/]" if ok else f"[red]FAIL[/] {note}")
    console.print(gt)

    n = len(results)
    schema_ok = sum(1 for r in results if not r["errors"])
    exact = sum(1 for r in results if r["band"] == "exact")
    misses = sum(1 for r in results if r["band"] == "miss")
    guard_ok = sum(1 for _, ok, _ in g_results if ok)
    console.print(f"Schema/validation compliance: [bold]{schema_ok}/{n}[/]  |  "
                  f"Band accuracy: [bold]{exact}/{n}[/] exact, {misses} misses  |  "
                  f"Guardrails: [bold]{guard_ok}/{len(g_results)}[/]")

    failures = []
    if schema_ok < n:
        failures.append("schema/validation failures")
    if guard_ok < len(g_results):
        failures.append("guardrail failures")
    if args.live:
        if misses:
            failures.append(f"{misses} two-band misses (PASS<->FAIL)")
        if exact / n < args.min_exact:
            failures.append(f"exact band accuracy {exact/n:.0%} < {args.min_exact:.0%}")
    elif exact < n:
        failures.append("mock scoring mismatch")

    if failures:
        console.print(f"[bold red]EVAL FAILED:[/] {', '.join(failures)}")
        return 1
    console.print("[bold green]EVAL PASSED[/]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
