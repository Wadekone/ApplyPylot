# Decision log

Short records of the main design choices: the context, what we decided, and why.

## 1. Job data from an API, not RSS or scraping

- **Context:** The first version collected postings from RSS feeds and HTML parsing. Sources broke whenever a site changed its layout, and too few of the postings were relevant.
- **Decision:** Ingest from RapidAPI's JSearch, which aggregates many job boards and ATS platforms into structured JSON.
- **Why:** Stable, structured input with more volume. We pay the cost of one external dependency and an API key.

## 2. Dedup by `external_id` in SQLite

- **Context:** The same posting comes back on every fetch, and re-runs filled the database with duplicates.
- **Decision:** Store the source's job ID as `external_id` with a `UNIQUE` constraint, and insert with `INSERT OR IGNORE`.
- **Why:** The database enforces uniqueness, so no code path can create a duplicate, and re-fetching is safe. SQLite keeps it a single local file with no server.
- **Trade-off:** The same role posted under two different source IDs is not caught (see README limitations).

## 3. Structured output with a Pydantic schema

- **Context:** Free-text LLM answers were hard to parse reliably, and the model sometimes listed skills the posting never mentioned.
- **Decision:** Ask Gemini for JSON constrained by `JobEvaluationSchema` (`response_schema`), at temperature 0.2, and validate the result with the same Pydantic model.
- **Why:** One schema serves as the contract sent to the model and as the check applied to its answer. Low temperature keeps scores stable between runs.

## 4. Status is derived from the score in code

- **Context:** The model returns both `match_score` and `eval_status`, and the two can disagree (e.g. PASS with a score of 4.0).
- **Decision:** Thresholds live once, in `config.py`. After validation, code recomputes the status from the score, overwrites the model's status, and counts every correction.
- **Why:** A ranking needs one source of truth. The score is the finer-grained signal, and a rule in code is testable and can't drift. The correction count shows how often the model contradicts itself.

## 5. Reject malformed output and keep the batch going

- **Context:** Some answers can be unusable: invalid JSON, a score outside 0–10, an unknown status, missing fields.
- **Decision:** Any parse or validation failure raises `EvaluationError`. That job is logged and skipped, it is not stored, and the rest of the batch continues.
- **Why:** A wrong score in the database is worse than a missing one, because it silently ranks a job up or down. A skipped job is visible and can be retried.

## 6. Offline evals with a mock LLM

- **Context:** Quality checks that need an API key don't run in CI or on a reviewer's machine.
- **Decision:** `eval.py` uses a deterministic mock by default to check schema compliance, validation, guardrails, dedup and storage. `--live` runs the same 10 samples against Gemini to measure real accuracy.
- **Why:** Pipeline correctness is checked on every change at no cost. Model accuracy is measured separately, when it matters.
