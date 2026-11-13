# ApplyPylot

A local CLI that pulls job postings from RapidAPI (JSearch), dedupes them in SQLite, scores each one against a target profile (Senior Delivery Lead / PMO / Operations) with Gemini structured output, and shows the ranked results in a terminal dashboard.

**Why:** I was searching for senior delivery roles and spending most of my time reading postings that were junior, on-site, or not delivery roles at all. ApplyPylot does the first-pass triage, so I only read the roles worth reading.

## Setup

Requires **Python 3.11+**. The `python3` that ships with macOS is 3.9, so install a newer one first (`brew install python@3.12`).

```bash
git clone https://github.com/Wadekone/ApplyPylot.git && cd ApplyPylot
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python eval.py            # offline check, no keys needed
cp .env.example .env      # add GEMINI_API_KEY and RAPIDAPI_KEY for real runs
```

## Usage

```bash
python cli.py run                                   # fetch → evaluate → dashboard
python cli.py fetch --query "PMO Director" --pages 2
python cli.py evaluate --limit 20
python cli.py dashboard --min-score 6 --status PASS --search fintech
python cli.py show 42                               # requirements, gaps, apply link
```

## Evals

`python eval.py` runs 10 hand-written job descriptions with expected outcomes (3 PASS, 3 BORDERLINE, 4 FAIL) through the full parse → validate → store path. It checks:

- **Schema compliance:** every output parses and matches `JobEvaluationSchema`.
- **Output validation:** score is 0–10, status agrees with score, summary and requirements are non-empty, and the result round-trips through SQLite unchanged.
- **Guardrails:** bad JSON, out-of-range scores, unknown statuses, missing fields and wrong types are rejected. A contradictory status is corrected. Threshold edges (7.5 / 7.4 / 5.0 / 4.9) fall in the right band. Duplicate `external_id`s are skipped.

By default a deterministic mock stands in for the LLM, so the run needs no keys and works in CI. `python eval.py --live` calls Gemini instead and fails on any PASS↔FAIL miss or on fewer than 70% exact band matches.

## Design decisions

- **Status is derived from score.** The model returns both, but code re-derives `PASS` / `BORDERLINE` / `FAIL` from `match_score` using thresholds in `config.py`. A self-contradicting answer (e.g. `PASS` at 4.0) is corrected and counted, never stored as-is.
- **Malformed output is rejected.** Anything that fails JSON parsing or Pydantic validation raises `EvaluationError`. That job is skipped and the batch keeps going.
- **Dedup by `external_id`.** The `jobs.external_id` column is `UNIQUE`, and inserts use `INSERT OR IGNORE`, so re-fetching never creates duplicates.
- **Low temperature (0.2) plus a response schema** to keep output stable and parseable.

## Known limitations

- `--live` evals have not yet been run against Gemini, so the real model's accuracy is unmeasured.
- Dedup relies on JSearch's job ID. The same role posted under different IDs (e.g. on two boards) can still appear twice.
- The target profile is hard-coded in the prompt (`evaluator.py`). It isn't matched against a CV.
- One source (JSearch). There is no retry or backoff on API errors, only a fixed delay between LLM calls.
- 10 eval samples is a smoke test, not a benchmark.

## How it was built

I defined the problem, the scoring logic, the quality rules and the evals. The code was written with [Claude Code](https://claude.com/claude-code).
