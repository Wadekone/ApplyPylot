"""Interactive CLI dashboard & search interface."""
import argparse
import json
import logging

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

import config
from database import get_connection, get_job_with_evaluation, init_db

console = Console()
STATUS_STYLE = {"PASS": "bold green", "BORDERLINE": "bold yellow", "FAIL": "bold red"}


def display_dashboard(min_score: float = 7.0, search: str | None = None, status: str | None = None) -> None:
    """Print evaluated roles at or above min_score, best first, with optional text/status filters."""
    sql = """
        SELECT j.id, j.title, j.company, j.location, e.match_score, e.eval_status, e.role_fit_summary
        FROM jobs j JOIN evaluations e ON j.id = e.job_id
        WHERE e.match_score >= ?
    """
    params: list = [min_score]
    if search:
        sql += " AND (j.title LIKE ? OR j.company LIKE ? OR j.description LIKE ?)"
        params += [f"%{search}%"] * 3
    if status:
        sql += " AND e.eval_status = ?"
        params.append(status.upper())
    sql += " ORDER BY e.match_score DESC"

    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()

    title = f"ApplyPylot — Evaluated Roles (Min Score: {min_score})"
    if search:
        title += f" · search: '{search}'"
    table = Table(title=title)
    table.add_column("ID", justify="right", style="cyan", no_wrap=True)
    table.add_column("Title", style="bold white")
    table.add_column("Company", style="magenta")
    table.add_column("Location")
    table.add_column("Score", justify="right", style="green")
    table.add_column("Status")
    table.add_column("Fit Summary", style="dim")

    for row in rows:
        style = STATUS_STYLE.get(row["eval_status"], "white")
        summary = row["role_fit_summary"] or ""
        table.add_row(
            str(row["id"]), row["title"], row["company"], row["location"] or "",
            f"{row['match_score']:.1f}",
            f"[{style}]{row['eval_status']}[/{style}]",
            summary[:60] + ("..." if len(summary) > 60 else ""),
        )

    if rows:
        console.print(table)
    else:
        console.print(f"[dim]No evaluated roles match (min score {min_score}).[/]")


def show_job(job_id: int) -> None:
    """Print full detail for one job: metadata, score, requirements and gaps."""
    row = get_job_with_evaluation(job_id)
    if not row:
        console.print(f"[red]No job with id {job_id}[/]")
        return
    lines = [f"[bold]{row['title']}[/] @ [magenta]{row['company']}[/]",
             f"Location: {row['location'] or '-'}   Posted: {row['date_posted'] or '-'}",
             f"URL: {row['url'] or '-'}"]
    if row["match_score"] is not None:
        style = STATUS_STYLE.get(row["eval_status"], "white")
        lines += ["", f"Score: [bold]{row['match_score']:.1f}[/]  [{style}]{row['eval_status']}[/{style}]",
                  "", row["role_fit_summary"] or "",
                  "", "[bold]Key requirements[/]"] + [f"  • {r}" for r in json.loads(row["key_requirements"] or "[]")]
        lines += ["", "[bold]Gaps / red flags[/]"] + [f"  • {r}" for r in json.loads(row["missing_skills"] or "[]")]
    else:
        lines += ["", "[dim]Not evaluated yet.[/]"]
    console.print(Panel("\n".join(lines), title=f"Job {job_id}"))


def main() -> None:
    """Parse the command line and dispatch to the matching subcommand."""
    logging.basicConfig(level=logging.WARNING)
    p = argparse.ArgumentParser(prog="applypylot", description="ApplyPylot job search CLI")
    sub = p.add_subparsers(dest="cmd")

    sub.add_parser("init", help="Initialize the SQLite database")

    f = sub.add_parser("fetch", help="Fetch jobs from RapidAPI/JSearch")
    f.add_argument("--query", default=config.DEFAULT_QUERY)
    f.add_argument("--location", default=config.DEFAULT_LOCATION)
    f.add_argument("--pages", type=int, default=1)

    e = sub.add_parser("evaluate", help="Score unevaluated jobs with the LLM")
    e.add_argument("--limit", type=int)

    d = sub.add_parser("dashboard", help="Show evaluated roles")
    d.add_argument("--min-score", type=float, default=7.0)
    d.add_argument("--search", help="Filter by text in title/company/description")
    d.add_argument("--status", choices=["PASS", "BORDERLINE", "FAIL"])

    s = sub.add_parser("show", help="Show full detail for one job")
    s.add_argument("job_id", type=int)

    sub.add_parser("demo", help="Full pipeline on bundled samples with a mock LLM (no API keys)")

    r = sub.add_parser("run", help="Full pipeline: init, fetch, evaluate, dashboard")
    r.add_argument("--query", default=config.DEFAULT_QUERY)
    r.add_argument("--location", default=config.DEFAULT_LOCATION)
    r.add_argument("--pages", type=int, default=1)
    r.add_argument("--min-score", type=float, default=7.0)

    a = p.parse_args()
    if a.cmd is None:
        a = p.parse_args(["dashboard"])

    if a.cmd == "demo":
        from main import run_demo
        run_demo()
        return

    init_db()  # idempotent
    if a.cmd == "fetch":
        from main import run_fetch
        run_fetch(a.query, a.location, a.pages)
    elif a.cmd == "evaluate":
        from main import run_evaluations
        run_evaluations(a.limit)
    elif a.cmd == "dashboard":
        display_dashboard(a.min_score, a.search, a.status)
    elif a.cmd == "show":
        show_job(a.job_id)
    elif a.cmd == "run":
        from main import run_pipeline
        run_pipeline(a.query, a.location, a.pages, a.min_score)
    elif a.cmd == "init":
        console.print(f"Database ready at {config.db_path()}")


if __name__ == "__main__":
    main()
