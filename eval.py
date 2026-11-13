"""ApplyPylot evaluation harness.

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

Each run writes a markdown summary: docs/eval-report.md (live) or
docs/eval-report-offline.md (offline). Override with --report PATH.
"""
import argparse
import json
import logging
import os
import sys
import tempfile
from datetime import UTC, datetime

from rich.console import Console
from rich.table import Table

import config
from mock_llm import Sample, load_samples, make_mock_backend

console = Console()


SAMPLES: list[Sample] = load_samples()

BAND_ORDER = ["FAIL", "BORDERLINE", "PASS"]


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


def write_report(path: str, mode: str, results: list[dict], g_results: list[tuple[str, bool, str]],
                 failures: list[str]) -> None:
    """Write a short markdown summary of one eval run."""
    n = len(results)
    exact = sum(1 for r in results if r["band"] == "exact")
    near = sum(1 for r in results if r["band"] == "near")
    misses = sum(1 for r in results if r["band"] == "miss")
    schema_ok = sum(1 for r in results if not r["errors"])
    corrected = sum(1 for r in results if r["corrected"])
    guard_ok = sum(1 for _, ok, _ in g_results if ok)
    icon = {"exact": "✅ pass", "near": "⚠️ near", "miss": "❌ miss"}

    lines = [
        "# ApplyPylot eval report",
        "",
        f"- **Mode:** {mode}",
        f"- **Run at:** {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}",
        f"- **Result:** {'PASSED' if not failures else 'FAILED (' + ', '.join(failures) + ')'}",
        "",
        *([] if mode.startswith("LIVE") else [
            "> Offline run: the mock LLM returns preset scores, so accuracy here only shows the pipeline,",
            "> validation and storage work end to end. Model accuracy comes from a `--live` run.",
            ""]),
        "| Metric | Value |",
        "|---|---|",
        f"| Status accuracy (exact band) | {exact}/{n} ({exact / n:.0%}) |",
        f"| One band off / two bands off | {near} / {misses} |",
        f"| Schema + validation compliance | {schema_ok}/{n} |",
        f"| LLM answers with status corrected from score | {corrected} |",
        f"| Guardrail & storage tests | {guard_ok}/{len(g_results)} |",
        "",
        "| Sample | Expected | Got | Score | Result |",
        "|---|---|---|---|---|",
    ]
    for r in results:
        s = r["sample"]
        result = "❌ error: " + "; ".join(r["errors"]) if r["errors"] else icon[r["band"]]
        if r["corrected"]:
            result += " (status corrected)"
        score = f"{r['score']:.1f}" if r["score"] is not None else "-"
        lines.append(f"| {s.key} | {s.expected} | {r['status'] or '-'} | {score} | {result} |")
    failed_guards = [f"- {name}: {note}" for name, ok, note in g_results if not ok]
    if failed_guards:
        lines += ["", "**Failed guardrails:**", *failed_guards]

    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--live", action="store_true", help="call the real Gemini API instead of the mock")
    p.add_argument("--min-exact", type=float, default=0.7,
                   help="live mode: minimum fraction of exact band matches to pass (default 0.7)")
    p.add_argument("--report", help="markdown report path (default: docs/eval-report.md for --live, "
                                    "docs/eval-report-offline.md otherwise)")
    args = p.parse_args()
    report_path = args.report or os.path.join(
        config.BASE_DIR, "docs", "eval-report.md" if args.live else "eval-report-offline.md")
    logging.basicConfig(level=logging.ERROR)  # the guardrail test triggers an expected warning

    # Isolated scratch DB so evals never touch data/applypylot.db
    tmpdir = tempfile.mkdtemp(prefix="applypylot-eval-")
    os.environ["APPLYPYLOT_DB_PATH"] = os.path.join(tmpdir, "eval.db")
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
    console.rule(f"ApplyPylot eval — {mode}")

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

    write_report(report_path, mode, results, g_results, failures)
    console.print(f"Report written to {os.path.relpath(report_path)}")

    if failures:
        console.print(f"[bold red]EVAL FAILED:[/] {', '.join(failures)}")
        return 1
    console.print("[bold green]EVAL PASSED[/]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
