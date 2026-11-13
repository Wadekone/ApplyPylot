"""Bundled sample job postings and a deterministic mock LLM.

Used by `eval.py` (offline mode), `python cli.py demo` and the tests, so none of them
need an API key. The mock returns a pre-set score for each known sample; it does not
judge the text. Real scoring only happens through Gemini (`evaluator.gemini_backend`).
"""
import json
import os
from dataclasses import dataclass

import config

SAMPLES_PATH = os.path.join(config.BASE_DIR, "samples", "jobs.json")


@dataclass
class Sample:
    key: str
    title: str
    company: str
    expected: str  # PASS / BORDERLINE / FAIL
    description: str
    mock_score: float  # what the mock LLM returns for this sample


def load_samples(path: str = SAMPLES_PATH) -> list[Sample]:
    """Load the bundled sample postings from samples/jobs.json."""
    with open(path, encoding="utf-8") as f:
        return [Sample(**item) for item in json.load(f)]


def make_mock_backend(samples: list[Sample]):
    """Return an LLM backend that answers with well-formed JSON for the given samples."""
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
