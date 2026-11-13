"""Malformed LLM output is rejected with EvaluationError, never stored."""
import json

import pytest

from evaluator import EvaluationError, evaluate_job_description, parse_and_validate

GOOD = {"match_score": 8.0, "role_fit_summary": "Good fit.", "key_requirements": ["SQL"],
        "missing_skills": [], "eval_status": "PASS"}


@pytest.mark.parametrize("raw", [
    "{not json",
    "",
    json.dumps({**GOOD, "match_score": 11.5}),
    json.dumps({**GOOD, "match_score": -1}),
    json.dumps({**GOOD, "eval_status": "MAYBE"}),
    json.dumps({k: v for k, v in GOOD.items() if k != "missing_skills"}),
    json.dumps({**GOOD, "role_fit_summary": "   "}),
    json.dumps({**GOOD, "key_requirements": "SQL, Agile"}),
], ids=["invalid-json", "empty", "score>10", "score<0", "unknown-status",
        "missing-field", "blank-summary", "string-not-list"])
def test_malformed_output_is_rejected(raw):
    with pytest.raises(EvaluationError):
        parse_and_validate(raw)


def test_valid_output_passes_and_score_is_rounded():
    evaluation, _ = parse_and_validate(json.dumps({**GOOD, "match_score": 8.04}))
    assert evaluation["match_score"] == 8.0


def test_empty_description_is_rejected_before_calling_llm():
    def backend(system_prompt, content):
        raise AssertionError("LLM should not be called")
    with pytest.raises(EvaluationError):
        evaluate_job_description("   ", backend=backend)
