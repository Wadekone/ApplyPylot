"""LLM evaluation pipeline: structured JSON output, schema validation, and scoring guardrails."""
import json
import logging
from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

import config

log = logging.getLogger(__name__)

EvalStatus = Literal["PASS", "BORDERLINE", "FAIL"]


class JobEvaluationSchema(BaseModel):
    match_score: float = Field(description="Relevance score from 0.0 to 10.0 based on Delivery Lead / Operations profile fit")
    role_fit_summary: str = Field(description="2-3 sentence overview of why this role matches or fails the target profile")
    key_requirements: list[str] = Field(description="List of primary technical and delivery requirements extracted from the post")
    missing_skills: list[str] = Field(description="Any missing requirements, red flags, or gaps relative to senior delivery roles")
    eval_status: EvalStatus = Field(description="Classification: MUST be 'PASS' (score >= 7.5), 'BORDERLINE' (5.0-7.4), or 'FAIL' (< 5.0)")

    # Validators (not Field(ge/le)) so the JSON schema sent to Gemini stays simple.
    @field_validator("match_score")
    @classmethod
    def _score_in_range(cls, v: float) -> float:
        if not 0.0 <= v <= 10.0:
            raise ValueError(f"match_score {v} outside 0.0-10.0")
        return round(v, 1)

    @field_validator("role_fit_summary")
    @classmethod
    def _summary_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("role_fit_summary is empty")
        return v.strip()


SYSTEM_PROMPT = f"""
You are an executive talent evaluation engine. Analyze the provided job posting for a Senior Software Delivery Lead / PMO / Operations Leader role.

Target Profile Criteria:
- Technical Software Delivery Management, Agile Governance, PMO Leadership, e-Commerce / Enterprise Systems.
- High value on hands-on technical literacy (SQL, system architecture, LLM integrations/evaluations, process automation).
- Competitive remote compensation structure.

Scoring rules:
- match_score is 0.0-10.0.
- eval_status MUST follow the score: PASS if score >= {config.PASS_THRESHOLD}, BORDERLINE if {config.BORDERLINE_THRESHOLD}-{config.PASS_THRESHOLD - 0.1}, FAIL if < {config.BORDERLINE_THRESHOLD}.
- Junior roles, non-delivery roles (e.g. pure sales, pure IC engineering), or on-site-only roles should score low.

Evaluate the job description and respond ONLY in valid JSON matching the requested schema.
""".strip()


class EvaluationError(Exception):
    """Raised when the LLM output cannot be parsed or fails schema validation."""


# An LLM backend takes (system_prompt, user_content) and returns raw JSON text.
LLMBackend = Callable[[str, str], str]


def gemini_backend(system_prompt: str, content: str) -> str:
    """Call Gemini with the response schema and return the raw JSON text."""
    from google import genai  # imported lazily so offline evals don't need credentials
    from google.genai import types

    if not config.GEMINI_API_KEY:
        raise EvaluationError("GEMINI_API_KEY is not set")
    client = genai.Client(api_key=config.GEMINI_API_KEY)
    response = client.models.generate_content(
        model=config.GEMINI_MODEL,
        contents=content,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            response_mime_type="application/json",
            response_schema=JobEvaluationSchema,
            temperature=config.LLM_TEMPERATURE,
        ),
    )
    return response.text


def parse_and_validate(raw: str) -> tuple[dict, bool]:
    """Parse raw LLM text into a validated evaluation dict.

    Guardrail: eval_status is always re-derived from match_score. Returns
    (evaluation, status_corrected) so callers can track LLM inconsistency.
    """
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as e:
        raise EvaluationError(f"LLM returned invalid JSON: {e}") from e
    try:
        parsed = JobEvaluationSchema.model_validate(data)
    except ValidationError as e:
        raise EvaluationError(f"LLM output failed schema validation: {e}") from e

    expected = config.status_for_score(parsed.match_score)
    corrected = parsed.eval_status != expected
    if corrected:
        log.warning("eval_status %s inconsistent with score %.1f; corrected to %s",
                    parsed.eval_status, parsed.match_score, expected)
        parsed.eval_status = expected
    return parsed.model_dump(), corrected


def evaluate_job_description(description: str, backend: LLMBackend | None = None) -> tuple[dict, str, bool]:
    """Evaluate one job description. Returns (evaluation, raw_json, status_corrected)."""
    if not description or not description.strip():
        raise EvaluationError("Empty job description")
    backend = backend or gemini_backend
    raw = backend(SYSTEM_PROMPT, f"Job Description:\n{description}")
    evaluation, corrected = parse_and_validate(raw)
    return evaluation, raw, corrected
