"""Pipeline orchestration: init DB -> fetch -> evaluate -> dashboard."""
import argparse
import logging
import time

from rich.console import Console

import config
from database import get_unevaluated_jobs, init_db, save_evaluation
from evaluator import EvaluationError, evaluate_job_description
from fetcher import fetch_and_store_jobs

console = Console()


def run_fetch(query: str, location: str, num_pages: int = 1) -> int:
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


def run_pipeline(query: str, location: str, num_pages: int, min_score: float) -> None:
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
