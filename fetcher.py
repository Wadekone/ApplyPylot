"""Ingestion: fetch raw listings from RapidAPI (JSearch) and store non-duplicates in SQLite."""
import requests

import config
from database import get_connection, insert_job


def fetch_jobs(query: str = config.DEFAULT_QUERY, location: str = config.DEFAULT_LOCATION,
               page: int = 1, num_pages: int = 1) -> list[dict]:
    """Call the JSearch search endpoint and return the raw job records."""
    if not config.RAPIDAPI_KEY:
        raise RuntimeError("RAPIDAPI_KEY is not set")
    response = requests.get(
        f"https://{config.RAPIDAPI_HOST}/search",
        headers={"x-rapidapi-key": config.RAPIDAPI_KEY, "x-rapidapi-host": config.RAPIDAPI_HOST},
        params={"query": f"{query} in {location}", "page": str(page), "num_pages": str(num_pages)},
        timeout=config.HTTP_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json().get("data", []) or []


def normalize(item: dict) -> dict | None:
    """Map a JSearch record to our jobs row. Returns None if required fields are missing."""
    if not item.get("job_id") or not item.get("job_title") or not item.get("employer_name"):
        return None
    if item.get("job_is_remote"):
        location = "Remote"
    else:
        location = ", ".join(p for p in (item.get("job_city"), item.get("job_state"), item.get("job_country")) if p) or None
    return {
        "external_id": item["job_id"],
        "title": item["job_title"],
        "company": item["employer_name"],
        "location": location,
        "source": "RapidAPI/JSearch",
        "url": item.get("job_apply_link"),
        "description": item.get("job_description"),
        "date_posted": item.get("job_posted_at_datetime_utc"),
    }


def store_jobs(items: list[dict]) -> int:
    """Normalize and insert records; returns how many were new (duplicates are skipped)."""
    new_count = 0
    with get_connection() as conn:
        for item in items:
            row = normalize(item)
            if row and insert_job(conn, row):
                new_count += 1
    return new_count


def fetch_and_store_jobs(query: str = config.DEFAULT_QUERY, location: str = config.DEFAULT_LOCATION,
                         num_pages: int = 1) -> tuple[int, int]:
    """Returns (fetched, inserted)."""
    items = fetch_jobs(query, location, num_pages=num_pages)
    return len(items), store_jobs(items)
