"""Jobs are deduplicated by external_id."""
from database import get_connection, insert_job
from fetcher import normalize, store_jobs


def _job(external_id="abc", title="Delivery Lead"):
    return {"external_id": external_id, "title": title, "company": "Acme", "location": "Remote",
            "source": "test", "url": None, "description": "desc", "date_posted": None}


def test_same_external_id_is_inserted_once(temp_db):
    with get_connection() as conn:
        assert insert_job(conn, _job()) is True
        assert insert_job(conn, _job(title="Changed title")) is False
        rows = conn.execute("SELECT title FROM jobs").fetchall()
    assert [r["title"] for r in rows] == ["Delivery Lead"]


def test_refetching_the_same_records_adds_nothing(temp_db):
    records = [{"job_id": f"j{i}", "job_title": "PM", "employer_name": "Acme",
                "job_description": "d"} for i in range(3)]
    assert store_jobs(records) == 3
    assert store_jobs(records) == 0


def test_records_missing_required_fields_are_skipped():
    assert normalize({"job_title": "PM", "employer_name": "Acme"}) is None  # no job_id
    assert normalize({"job_id": "1", "employer_name": "Acme"}) is None      # no title
