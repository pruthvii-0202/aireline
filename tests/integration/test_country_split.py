"""Latest-wins + country split, run in a throwaway schema with hand-made MEMBER_STG rows."""

import uuid
from datetime import date

import pytest

from skypoints.silver.current import apply_batch, target_tables

pytestmark = pytest.mark.integration

B1, B2 = date(2024, 1, 15), date(2024, 1, 16)


def stg(batch, member_id, country_raw, iso, *, tier="GLD", flight="2024-01-01", stale=False):
    return (batch.isoformat(), member_id, f"Member {member_id}", "2010-10-12", flight, tier,
            country_raw, iso, "1985-05-03", True, 38, stale, False,
            f"{member_id}|{country_raw}|{tier}", "TEST.txt", 1, "test",
            "2024-01-15 06:00:00")  # fmt: skip


BATCH_1 = [
    stg(B1, "A", "USA", "US"),
    stg(B1, "B", "IND", "IN"),
    stg(B1, "C", "AU", "AU", flight="2023-10-17"),  # 90 days before B1: not yet stale
    stg(B1, "D", "USA", "US"),
]
BATCH_2 = [
    stg(B2, "A", "PHIL", "PH"),  # moves US -> PH
    stg(B2, "B", "ZZ", None),  # moves to an unknown country -> UNMAPPED
    stg(B2, "D", "USA", "US"),  # re-sent unchanged
    stg(B2, "E", "CAN", "CA"),  # new member
    # C is not in batch 2; its last flight is now 91 days old, so it must turn stale.
]


@pytest.fixture(scope="module")
def schema(sf_conn, sf_settings):
    db = sf_settings.database
    name = f"{db}.TEST_SPLIT_{uuid.uuid4().hex[:8].upper()}"
    cur = sf_conn.cursor()
    cur.execute(f"CREATE TRANSIENT SCHEMA {name}")
    try:
        cur.execute(f"CREATE TABLE {name}.COUNTRY_MAP CLONE {db}.SILVER.COUNTRY_MAP")
        cur.execute(f"CREATE TABLE {name}.MEMBER_STG LIKE {db}.SILVER.MEMBER_STG")
        cur.execute(f"CREATE TABLE {name}.MEMBER_CURRENT LIKE {db}.SILVER.MEMBER_CURRENT")
        cur.executemany(
            f"INSERT INTO {name}.MEMBER_STG (BATCH_DATE, MEMBER_ID, MEMBER_NAME, ENROLLMENT_DATE, "
            "LAST_FLIGHT_DATE, TIER_CODE, COUNTRY_RAW, COUNTRY_ISO, DOB, IS_ACTIVE, AGE, "
            "STALE_MEMBER, NEVER_FLOWN, RECORD_HASH, SOURCE_FILE, SOURCE_FILE_ROW_NO, LOAD_ID, "
            "LOAD_TS) VALUES (" + ", ".join(["%s"] * 18) + ")",
            BATCH_1 + BATCH_2,
        )
        apply_batch(sf_conn, db, B1, silver=name)
        apply_batch(sf_conn, db, B2, silver=name)
        yield name
    finally:
        cur.execute(f"DROP SCHEMA IF EXISTS {name}")


def snapshot(conn, schema):
    """Every member in every country table, without the volatile UPDATED_AT."""
    cur = conn.cursor()
    rows = set()
    for table in target_tables(cur, schema):
        for r in cur.execute(
            f"SELECT MEMBER_ID, COUNTRY_ISO, PREVIOUS_COUNTRY_ISO, STALE_MEMBER, LAST_BATCH_DATE "
            f"FROM {schema}.{table}"
        ).fetchall():
            rows.add((table, *r))
    return rows


def tables_of(conn, schema, member_id):
    return sorted(t for t, m, *_ in snapshot(conn, schema) if m == member_id)


def current(conn, schema, member_id):
    cur = conn.cursor()
    cur.execute(f"SELECT * FROM {schema}.MEMBER_CURRENT WHERE MEMBER_ID = %s", (member_id,))
    return dict(zip([c[0] for c in cur.description], cur.fetchone(), strict=True))


def test_mover_is_only_in_new_country(sf_conn, schema):
    assert tables_of(sf_conn, schema, "A") == ["MEMBER_PH"]
    a = current(sf_conn, schema, "A")
    assert (a["COUNTRY_ISO"], a["PREVIOUS_COUNTRY_ISO"], a["COUNTRY_CHANGED_DATE"]) == (
        "PH",
        "US",
        B2,
    )


def test_unknown_country_goes_to_unmapped(sf_conn, schema):
    assert tables_of(sf_conn, schema, "B") == ["MEMBER_UNMAPPED"]


def test_member_not_in_batch_gets_stale_refreshed(sf_conn, schema):
    assert tables_of(sf_conn, schema, "C") == ["MEMBER_AU"]
    assert current(sf_conn, schema, "C")["STALE_MEMBER"] is True
    [(_, _, _, _, stale, _)] = [r for r in snapshot(sf_conn, schema) if r[1] == "C"]
    assert stale is True  # country table got the refresh too


def test_unchanged_resend_keeps_original_record(sf_conn, schema):
    assert tables_of(sf_conn, schema, "D") == ["MEMBER_US"]
    assert current(sf_conn, schema, "D")["LAST_BATCH_DATE"] == B1


def test_new_member_inserted(sf_conn, schema):
    assert tables_of(sf_conn, schema, "E") == ["MEMBER_CA"]


def test_every_member_in_exactly_one_table(sf_conn, schema):
    members = [m for _, m, *_ in snapshot(sf_conn, schema)]
    assert sorted(members) == ["A", "B", "C", "D", "E"]


def test_rerun_is_idempotent_and_old_batch_cannot_win(sf_conn, sf_settings, schema):
    before = snapshot(sf_conn, schema)
    apply_batch(sf_conn, sf_settings.database, B2, silver=schema)
    assert snapshot(sf_conn, schema) == before
    apply_batch(sf_conn, sf_settings.database, B1, silver=schema)  # replay an older batch
    assert snapshot(sf_conn, schema) == before
