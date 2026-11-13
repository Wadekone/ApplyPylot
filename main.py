"""Pipeline orchestration: init DB -> fetch -> evaluate -> dashboard."""
import argparse
import logging
import time

from rich.console import Console
from rich.panel import Panel

import config
from database import get_unevaluated_jobs, init_db, save_evaluation
from evaluator import EvaluationError, evaluate_job_description
from fetcher import fetch_and_store_jobs

console = Console()


def run_fetch(query: str, location: str, num_pages: int = 1) -> int:
    """Fetch postings from JSearch and store the new ones; returns the number inserted."""
    fetched, inserted = fetch_and_store_jobs(query, location, num_pages)
    console.print(f"Fetched [bold]{fetched}[/] items. Inserted [bold green]{inserted}[/] new unique jobs.")
    return inserted


def run_evaluations(limit: int | None = None, delay: float = 0.5, backend=None) -> dict:
    """Evaluate every job that has no evaluation yet. One bad job never stops the batch."""
    jobs = get_unevaluated_jobs(limit)
    stats = {"evaluated": 0, "failed": 0, "status_corrected": 0}
    if not jobs:
        console.print("No unevaluated jobs.")
        return stats

    with console.status(f"Evaluating {len(jobs)} jobs...") as status:
        for i, job in enumerate(jobs, 1):
            status.update(f"[{i}/{len(jobs)}] {job['title']} @ {job['company']}")
            try:
                evaluation, raw, corrected = evaluate_job_description(job["description"], backend=backend)
                save_evaluation(job["id"], evaluation, raw)
                stats["evaluated"] += 1
                stats["status_corrected"] += int(corrected)
            except EvaluationError as e:
                stats["failed"] += 1
                console.print(f"[red]Job {job['id']} failed:[/] {e}")
            except Exception as e:  # network / API errors
                stats["failed"] += 1
                console.print(f"[red]Job {job['id']} error:[/] {type(e).__name__}: {e}")
            if delay and i < len(jobs):
                time.sleep(delay)

    console.print(f"Evaluated [green]{stats['evaluated']}[/], failed [red]{stats['failed']}[/], "
                  f"status auto-corrected [yellow]{stats['status_corrected']}[/].")
    return stats


def run_demo() -> None:
    """Run the full pipeline on the bundled sample postings with the mock LLM.

    Needs no API keys and uses a throwaway database, so it never touches data/applypylot.db.
    Ingestion, dedup, validation, storage and the dashboard are the real code paths;
    only the LLM call is replaced by a mock that returns preset scores.
    """
    import os
    import tempfile

    from cli import display_dashboard, show_job
    from fetcher import store_jobs
    from mock_llm import load_samples, make_mock_backend

    os.environ["APPLYPYLOT_DB_PATH"] = os.path.join(tempfile.mkdtemp(prefix="applypylot-demo-"), "demo.db")
    samples = load_samples()
    console.print(Panel(
        "Runs the real pipeline on bundled sample postings. No API keys needed.\n"
        "The LLM step uses a [bold]mock with preset scores[/]; use `python cli.py run` for real Gemini scoring.",
        title="ApplyPylot demo"))
    init_db()

    # JSearch-shaped records, so the real ingestion code (normalize + dedup) runs.
    records = [{
        "job_id": f"demo-{s.key}",
        "job_title": s.title,
        "employer_name": s.company,
        "job_is_remote": not any(w in s.description.lower() for w in ("on-site", "hybrid")),
        "job_description": s.description,
    } for s in samples]
    console.print(f"[bold]1. Ingest:[/] stored {store_jobs(records)} of {len(records)} sample postings")
    console.print(f"[bold]2. Dedup:[/] re-ingesting the same postings stored {store_jobs(records)} new rows")
    console.print("[bold]3. Evaluate:[/] mock LLM → schema validation → status derived from score → SQLite")
    run_evaluations(delay=0, backend=make_mock_backend(samples))
    console.print("[bold]4. Dashboard:[/] all evaluated roles, best first")
    display_dashboard(min_score=0)
    show_job(1)


def run_pipeline(query: str, location: str, num_pages: int, min_score: float) -> None:
    """Init the database, fetch, evaluate new jobs and show the dashboard."""
    from cli import display_dashboard

    init_db()
    run_fetch(query, location, num_pages)
    run_evaluations()
    display_dashboard(min_score)


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    p = argparse.ArgumentParser(description="Run the full ApplyPylot pipeline.")
    p.add_argument("--query", default=config.DEFAULT_QUERY)
    p.add_argument("--location", default=config.DEFAULT_LOCATION)
    p.add_argument("--pages", type=int, default=1)
    p.add_argument("--min-score", type=float, default=7.0)
    a = p.parse_args()
    run_pipeline(a.query, a.location, a.pages, a.min_score)
