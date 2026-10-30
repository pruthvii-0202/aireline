"""Silver must catch every defect the generator injected, and nothing else.

Needs data/landing generated, loaded to Bronze and processed to Silver:
    python -m skypoints.datagen ; python -m skypoints.bronze ; python -m skypoints.silver
"""

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

LANDING = Path("data/landing")

# Generator defect -> (where the row must end up, reason or flag)
EXPECTED = {
    "MISSING_MEMBER_NAME": ("reject", "MISSING_MEMBER_NAME"),
    "MISSING_MEMBER_ID": ("reject", "MISSING_MEMBER_ID"),
    "MISSING_ENROLLMENT_DATE": ("reject", "MISSING_ENROLLMENT_DATE"),
    "INVALID_ENROLLMENT_DATE": ("reject", "INVALID_ENROLLMENT_DATE"),
    "INVALID_LAST_FLIGHT_DATE": ("reject", "INVALID_LAST_FLIGHT_DATE"),
    "INVALID_DOB": ("reject", "INVALID_DOB"),
    "FUTURE_DOB": ("reject", "FUTURE_DOB"),
    "ID_TOO_LONG": ("reject", "ID_TOO_LONG"),
    "DOB_LEADING_ZERO_DROPPED": ("flag", "DOB_REPAIRED"),
    "SHORT_MEMBER_ID": ("flag", "ID_LENGTH_SUSPECT"),
    "FLIGHT_BEFORE_ENROLLMENT": ("flag", "FLIGHT_BEFORE_ENROLLMENT"),
    "UNKNOWN_TIER": ("flag", "UNKNOWN_TIER"),
    "INVALID_ACTIVE_FLAG": ("flag", "INVALID_ACTIVE_FLAG"),
    "UNKNOWN_COUNTRY": ("flag", "UNKNOWN_COUNTRY"),
    "NEEDS_NORMALISATION": ("flag", "VALUES_NORMALISED"),
}


def _manifests():
    paths = sorted(LANDING.glob("MANIFEST_*.json"))
    if not paths:
        pytest.skip("no generated data in data/landing")
    return [json.loads(p.read_text()) for p in paths]


@pytest.fixture(scope="module")
def silver(sf_conn):
    cur = sf_conn.cursor()
    staged = {
        (f, n): json.loads(flags)
        for f, n, flags in cur.execute(
            "SELECT SOURCE_FILE, SOURCE_FILE_ROW_NO, DQ_FLAGS FROM SILVER.MEMBER_STG"
        ).fetchall()
    }
    rejected = {
        (f, n): json.loads(reasons)
        for f, n, reasons in cur.execute(
            "SELECT SOURCE_FILE, SOURCE_FILE_ROW_NO, REJECT_REASONS FROM SILVER.MEMBER_REJECT"
        ).fetchall()
    }
    bronze = cur.execute(
        "SELECT COUNT(*) FROM BRONZE.MEMBER_PROFILE_RAW WHERE RECORD_TYPE = 'D'"
    ).fetchone()[0]
    return staged, rejected, bronze


def test_every_bronze_detail_row_is_staged_or_rejected(silver):
    staged, rejected, bronze = silver
    assert not staged.keys() & rejected.keys()
    assert len(staged) + len(rejected) == bronze


def test_every_injected_defect_is_caught(silver):
    staged, rejected, _ = silver
    for manifest in _manifests():
        f = manifest["member_file"]
        for d in manifest["member_defects"]:
            key = (f, d["line_no"])
            if d["defect"] == "EXACT_DUPLICATE":
                assert rejected[(f, d["duplicate_of_line_no"])] == ["EXACT_DUPLICATE"], d
            elif d["defect"] == "CONFLICTING_DUPLICATE":
                assert rejected[(f, d["duplicate_of_line_no"])] == ["DUPLICATE_KEY_SUPERSEDED"], d
                assert key in staged, d
            else:
                where, code = EXPECTED[d["defect"]]
                found = rejected.get(key) if where == "reject" else staged.get(key)
                assert found is not None and code in found, (d, found)


def test_no_false_positives(silver):
    """Rows the generator left clean must be staged with no flags."""
    staged, rejected, _ = silver
    expected_lines = set()
    for manifest in _manifests():
        f = manifest["member_file"]
        for d in manifest["member_defects"]:
            expected_lines.add((f, d["line_no"]))
            if "duplicate_of_line_no" in d:
                expected_lines.add((f, d["duplicate_of_line_no"]))
    assert set(rejected) <= expected_lines
    assert {k for k, flags in staged.items() if flags} <= expected_lines
