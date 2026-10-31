"""DIM_MEMBER (SCD Type 2), built in a throwaway schema from hand-made MEMBER_STG rows."""

import uuid
from datetime import date

import pytest

from skypoints.gold.build import build_dim_member

pytestmark = pytest.mark.integration

B1, B2, B3 = date(2024, 1, 15), date(2024, 1, 16), date(2024, 1, 17)
OPEN_FROM, OPEN_TO = date(1900, 1, 1), date(9999, 12, 31)


def stg(batch, member_id, country_raw, iso, *, tier="GLD", flight="2024-01-01"):
    return (batch.isoformat(), member_id, f"Member {member_id}", "2010-10-12", flight, tier,
            country_raw, iso, "1985-05-03", True, 38, False, False,
            f"{member_id}|{country_raw}|{tier}|{flight}", "TEST.txt", 1, "test",
            "2024-01-15 06:00:00")  # fmt: skip


ROWS = [
    stg(B1, "A", "USA", "US"),
    stg(B2, "A", "PHIL", "PH"),  # country move: new version
    stg(B3, "A", "PHIL", "PH", flight="2024-01-16"),  # only flew: same version
    stg(B1, "B", "USA", "US", tier="SLV"),
    stg(B2, "B", "USA", "US", tier="GLD"),
    stg(B3, "B", "USA", "US", tier="SLV"),  # back to SLV: a third version, not a merge
    stg(B1, "D", "IND", "IN"),
    stg(B2, "D", "IND", "IN"),  # re-sent unchanged
    stg(B2, "E", "CAN", "CA"),  # first seen in batch 2
    stg(B1, "F", "AU", "AU"),
    stg(B2, "F", "AUS", "AU"),  # alias of the same country
]


@pytest.fixture(scope="module")
def schema(sf_conn, sf_settings):
    db = sf_settings.database
    name = f"{db}.TEST_DIM_{uuid.uuid4().hex[:8].upper()}"
    cur = sf_conn.cursor()
    cur.execute(f"CREATE TRANSIENT SCHEMA {name}")
    try:
        cur.execute(f"CREATE TABLE {name}.MEMBER_STG LIKE {db}.SILVER.MEMBER_STG")
        cur.execute(f"CREATE TABLE {name}.DIM_MEMBER LIKE {db}.GOLD.DIM_MEMBER")
        cur.executemany(
            f"INSERT INTO {name}.MEMBER_STG (BATCH_DATE, MEMBER_ID, MEMBER_NAME, ENROLLMENT_DATE, "
            "LAST_FLIGHT_DATE, TIER_CODE, COUNTRY_RAW, COUNTRY_ISO, DOB, IS_ACTIVE, AGE, "
            "STALE_MEMBER, NEVER_FLOWN, RECORD_HASH, SOURCE_FILE, SOURCE_FILE_ROW_NO, LOAD_ID, "
            "LOAD_TS) VALUES (" + ", ".join(["%s"] * 18) + ")",
            ROWS,
        )
        build_dim_member(sf_conn, silver=name, gold=name)
        yield name
    finally:
        cur.execute(f"DROP SCHEMA IF EXISTS {name}")


def versions(conn, schema, member_id=None):
    """(member, country, tier, version batch, valid from, valid to, current) in version order."""
    cur = conn.cursor()
    cur.execute(
        "SELECT MEMBER_ID, COUNTRY_ISO, TIER_CODE, VERSION_BATCH_DATE, VALID_FROM, VALID_TO, "
        f"IS_CURRENT FROM {schema}.DIM_MEMBER "
        "WHERE MEMBER_ID = COALESCE(%s, MEMBER_ID) ORDER BY MEMBER_ID, VERSION_NO",
        (member_id,),
    )
    return cur.fetchall()


def test_country_move_closes_old_version_and_opens_new(sf_conn, schema):
    assert versions(sf_conn, schema, "A") == [
        ("A", "US", "GLD", B1, OPEN_FROM, B1, False),
        ("A", "PH", "GLD", B2, B2, OPEN_TO, True),
    ]


def test_changing_back_creates_a_new_version(sf_conn, schema):
    assert [(v[2], v[4], v[5]) for v in versions(sf_conn, schema, "B")] == [
        ("SLV", OPEN_FROM, B1),
        ("GLD", B2, B2),
        ("SLV", B3, OPEN_TO),
    ]


def test_unchanged_resend_and_country_alias_keep_one_version(sf_conn, schema):
    assert len(versions(sf_conn, schema, "D")) == 1
    assert len(versions(sf_conn, schema, "F")) == 1


def test_first_version_is_open_from_the_start(sf_conn, schema):
    # E arrived in batch 2, but a redemption dated before that must still find a version.
    assert versions(sf_conn, schema, "E") == [("E", "CA", "GLD", B2, OPEN_FROM, OPEN_TO, True)]


def test_exactly_one_current_version_per_member(sf_conn, schema):
    current = [v[0] for v in versions(sf_conn, schema) if v[6]]
    assert sorted(current) == ["A", "B", "D", "E", "F"]


def test_versions_cover_time_without_gaps_or_overlaps(sf_conn, schema):
    rows = versions(sf_conn, schema)
    for prev, nxt in zip(rows, rows[1:], strict=False):
        if prev[0] == nxt[0]:
            assert (nxt[4] - prev[5]).days == 1, (prev, nxt)


def test_rebuild_is_idempotent(sf_conn, schema):
    cur = sf_conn.cursor()
    sql = f"SELECT MEMBER_SK, ATTRIBUTE_HASH, VALID_FROM, VALID_TO FROM {schema}.DIM_MEMBER"
    before = set(cur.execute(sql).fetchall())
    build_dim_member(sf_conn, silver=schema, gold=schema)
    assert set(cur.execute(sql).fetchall()) == before
