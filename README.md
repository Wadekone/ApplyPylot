# ApplyPilot

Local job-search pipeline: fetch postings from RapidAPI (JSearch) → dedupe in SQLite → score with Gemini structured output → review in a Rich terminal dashboard.

## Setup (macOS)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then add GEMINI_API_KEY and RAPIDAPI_KEY
python database.py     # creates data/applypilot.db
```

## Usage

```bash
python cli.py run                         # init → fetch → evaluate → dashboard
python cli.py fetch --query "PMO Director" --location "Remote" --pages 2
python cli.py evaluate --limit 20
python cli.py dashboard --min-score 6 --status PASS --search fintech
python cli.py show 42                     # full detail: requirements, gaps, URL
```

## Evals

```bash
python eval.py          # offline, mock LLM, no keys needed — schema, guardrails, dedup, SQLite round-trip
python eval.py --live   # real Gemini on the 10 samples; fails on any PASS↔FAIL miss or <70% exact band match
```

## Design notes

- `PASS`/`BORDERLINE`/`FAIL` thresholds live only in `config.py`. The evaluator re-derives `eval_status` from `match_score`, so a self-contradicting LLM answer is corrected (and counted) instead of stored.
- Malformed LLM output (bad JSON, score outside 0–10, unknown status, missing fields) raises `EvaluationError`; the batch logs it and moves on.
- Dedup happens through `INSERT OR IGNORE` on the UNIQUE `external_id`.
- `APPLYPILOT_DB_PATH` changes which database is used; `eval.py` uses it to run against a throwaway DB.
