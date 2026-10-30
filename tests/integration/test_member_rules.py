"""Runs member_validate.sql in Snowflake over hand-made edge cases (temporary table only)."""

import json
from datetime import date

import pytest

from skypoints.silver.members import validate_sql

pytestmark = pytest.mark.integration

BATCH = date(2024, 1, 15)


def row(row_no, member_id="100001", *, record_type="D", name="Elena Cruz", enroll="20101012",
        flight="20240101", tier="GLD", agent="Sam", state="CA", country="USA",
        dob="03051985", active="A"):  # fmt: skip
    return (record_type, name, member_id, enroll, flight, tier, agent, state, country, dob,
            active, "TEST_FILE.txt", row_no, BATCH.isoformat(), "test-load")  # fmt: skip


CASES = [
    row(1, "Member_Id", record_type="H"),  # header line: excluded
    row(2, "100001"),  # clean; flew 14 days before the batch
    row(3, "100002", flight="20231017"),  # exactly 90 days: not stale
    row(4, "100003", flight="20231016"),  # 91 days: stale
    row(5, "100004", flight=""),  # never flown: stale
    row(6, "100005", dob="29022000"),  # leap-day birthday
    row(7, "100006", dob="15011990"),  # birthday on the batch date
    row(8, "100007", dob="16011990"),  # birthday the day after
    row(9, "100008", dob="3051985"),  # DOB lost its leading zero
    row(10, "100009", name=""),
    row(11, "1" * 19),
    row(12, "100011", enroll="20211313"),
    row(13, "100012", flight="20230230"),
    row(14, "100013", dob="01012030"),
    row(15, "2256"),  # short id, as in the brief
    row(16, " 100015 ", tier=" gld ", country="aus "),
    row(17, "100016", country="ZZ"),
    row(18, "200001", tier="SLV"),  # conflicting duplicate: earlier line loses
    row(19, "200001", tier="GLD"),
    row(20, "200002"),  # exact duplicate: earlier line loses
    row(21, "200002"),
    row(22, "100021", name="", enroll=""),  # every failed rule is reported
    row(23, "200003", enroll="20211313"),  # invalid row does not count as a duplicate
    row(24, "200003"),
    row(25, "100025", tier="BRZ", active="Y", flight="20090101"),
]


@pytest.fixture(scope="module")
def results(sf_conn, sf_settings):
    db = sf_settings.database
    table = f"{db}.SILVER.TEST_MEMBER_RAW"
    cur = sf_conn.cursor()
    cur.execute(f"CREATE OR REPLACE TEMPORARY TABLE {table} LIKE {db}.BRONZE.MEMBER_PROFILE_RAW")
    cur.executemany(
        f"INSERT INTO {table} (RECORD_TYPE, MEMBER_NAME, MEMBER_ID, ENROLLMENT_DATE, "
        "LAST_FLIGHT_DATE, TIER_CODE, AGENT_NAME, STATE, COUNTRY, DOB, IS_ACTIVE, SOURCE_FILE, "
        "SOURCE_FILE_ROW_NO, BATCH_DATE, LOAD_ID) VALUES "
        "(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        CASES,
    )
    cur.execute(validate_sql(db, BATCH, source=table))
    columns = [c[0] for c in cur.description]
    out = {}
    for values in cur.fetchall():
        rec = dict(zip(columns, values, strict=True))
        rec["REJECT_REASONS"] = json.loads(rec["REJECT_REASONS"])
        rec["DQ_FLAGS"] = json.loads(rec["DQ_FLAGS"])
        out[rec["SOURCE_FILE_ROW_NO"]] = rec
    return out


def test_header_line_excluded(results):
    assert 1 not in results
    assert len(results) == len(CASES) - 1


def test_clean_row_is_typed_and_derived(results):
    r = results[2]
    assert r["REJECT_REASONS"] == [] and r["DQ_FLAGS"] == []
    assert r["ENROLLMENT_DATE"] == date(2010, 10, 12)
    assert r["DOB"] == date(1985, 5, 3)  # DDMMYYYY
    assert (r["AGE"], r["DAYS_SINCE_LAST_FLIGHT"], r["STALE_MEMBER"]) == (38, 14, False)
    assert (r["COUNTRY_ISO"], r["IS_ACTIVE"], r["NEVER_FLOWN"]) == ("US", True, False)


@pytest.mark.parametrize(
    ("row_no", "days", "stale"),
    [(3, 90, False), (4, 91, True), (5, None, True)],
)
def test_stale_member_boundary(results, row_no, days, stale):
    assert results[row_no]["DAYS_SINCE_LAST_FLIGHT"] == days
    assert results[row_no]["STALE_MEMBER"] is stale


def test_never_flown(results):
    assert results[5]["NEVER_FLOWN"] is True


@pytest.mark.parametrize(("row_no", "age"), [(6, 23), (7, 34), (8, 33)])
def test_age_whole_years_at_batch_date(results, row_no, age):
    assert results[row_no]["AGE"] == age


def test_dob_leading_zero_repaired(results):
    assert results[9]["DOB"] == date(1985, 5, 3)
    assert results[9]["DQ_FLAGS"] == ["DOB_REPAIRED"]


@pytest.mark.parametrize(
    ("row_no", "reasons"),
    [
        (10, ["MISSING_MEMBER_NAME"]),
        (11, ["ID_TOO_LONG"]),
        (12, ["INVALID_ENROLLMENT_DATE"]),
        (13, ["INVALID_LAST_FLIGHT_DATE"]),
        (14, ["FUTURE_DOB"]),
        (18, ["DUPLICATE_KEY_SUPERSEDED"]),
        (20, ["EXACT_DUPLICATE"]),
        (22, ["MISSING_MEMBER_NAME", "MISSING_ENROLLMENT_DATE"]),
        (23, ["INVALID_ENROLLMENT_DATE"]),
    ],
)
def test_rejected(results, row_no, reasons):
    assert results[row_no]["REJECT_REASONS"] == reasons


@pytest.mark.parametrize(
    ("row_no", "flags"),
    [
        (15, ["ID_LENGTH_SUSPECT"]),
        (16, ["VALUES_NORMALISED"]),
        (17, ["UNKNOWN_COUNTRY"]),
        (19, []),
        (21, []),
        (24, []),
        (25, ["UNKNOWN_TIER", "INVALID_ACTIVE_FLAG", "FLIGHT_BEFORE_ENROLLMENT"]),
    ],
)
def test_kept_with_flags(results, row_no, flags):
    assert results[row_no]["REJECT_REASONS"] == []
    assert results[row_no]["DQ_FLAGS"] == flags


def test_normalisation(results):
    r = results[16]
    assert (r["MEMBER_ID"], r["TIER_CODE"], r["COUNTRY_RAW"], r["COUNTRY_ISO"]) == (
        "100015",
        "GLD",
        "AUS",
        "AU",
    )


def test_unknown_country_has_no_iso(results):
    assert results[17]["COUNTRY_ISO"] is None


def test_latest_duplicate_wins(results):
    assert results[19]["TIER_CODE"] == "GLD"
