"""Status is derived from the score using the thresholds in config.py."""
import json

import pytest

import config
from evaluator import parse_and_validate


@pytest.mark.parametrize("score, expected", [
    (10.0, "PASS"), (7.5, "PASS"),
    (7.4, "BORDERLINE"), (5.0, "BORDERLINE"),
    (4.9, "FAIL"), (0.0, "FAIL"),
])
def test_status_for_score_thresholds(score, expected):
    assert config.status_for_score(score) == expected


def _answer(**overrides):
    base = {"match_score": 8.0, "role_fit_summary": "Good fit.", "key_requirements": ["SQL"],
            "missing_skills": [], "eval_status": "PASS"}
    return json.dumps({**base, **overrides})


def test_consistent_status_is_kept():
    evaluation, corrected = parse_and_validate(_answer())
    assert evaluation["eval_status"] == "PASS"
    assert not corrected


@pytest.mark.parametrize("score, claimed, expected", [
    (4.0, "PASS", "FAIL"),
    (9.0, "FAIL", "PASS"),
    (6.0, "PASS", "BORDERLINE"),
])
def test_contradictory_status_is_corrected(score, claimed, expected):
    evaluation, corrected = parse_and_validate(_answer(match_score=score, eval_status=claimed))
    assert evaluation["eval_status"] == expected
    assert corrected
