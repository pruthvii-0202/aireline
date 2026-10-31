"""MEMBER_360, built in a throwaway schema from hand-made members and redemptions."""

import uuid
from datetime import date, timedelta

import pytest

from skypoints.gold.build import build_member_360
from skypoints.silver.current import apply_batch

pytestmark = pytest.mark.integration

AS_OF = date(2024, 1, 17)


def days_ago(n):
    return (AS_OF - timedelta(days=n)).isoformat()


def stg(member_id, flight, *, dob="1985-05-03"):
    return (AS_OF.isoformat(), member_id, f"Member {member_id}", "2010-10-12", flight, "GLD",
            "USA", "US", dob, True, 0, False, flight is None,
            f"{member_id}|{flight}", "TEST.txt", 1, "test", "2024-01-17 06:00:00")  # fmt: skip


MEMBERS = [
    stg("A", days_ago(30)),  # ACTIVE: 30 days is still active
    stg("B", days_ago(31)),  # AT_RISK
    stg("C", days_ago(90)),  # AT_RISK: 90 days is not stale yet
    stg("D", days_ago(91)),  # DORMANT, stale, redeemed 30 days ago
    stg("E", None, dob="2000-01-18"),  # never flown; turns 24 tomorrow
    stg("F", days_ago(5), dob="2000-01-17"),  # turns 24 today; no redemptions
    stg("G", days_ago(200)),  # DORMANT, stale, redeemed 31 days ago
]


def txn(txn_id, member_id, txn_date, partner, miles, status="COMPLETED"):
    return (txn_id, member_id, AS_OF.isoformat(), txn_date, partner, False, miles, status,
            status == "COMPLETED", member_id == "Z", AS_OF.isoformat(), "TEST.json", 1, 0,
            "test")  # fmt: skip


REDEMPTIONS = [
    txn("RX1", "A", "2024-01-10", "AeroLink", 1000),
    txn("RX2", "A", "2024-01-12", "SunAir", 2000),
    txn("RX3", "A", "2024-01-14", "SunAir", 500, "PENDING"),
    txn("RX4", "A", "2024-01-16", "AeroLink", 9000, "CANCELLED"),
    txn("RX5", "B", "2024-01-10", "EuroJet", 1000),  # tie on count and miles:
    txn("RX6", "B", "2024-01-10", "AeroLink", 1000),  # alphabetical wins
    txn("RX7", "C", "2024-01-10", "EuroJet", 500),  # tie on count:
    txn("RX8", "C", "2024-01-10", "SunAir", 4000),  # more miles wins
    txn("RX9", "D", days_ago(30), "SunAir", 700),
    txn("RX10", "G", days_ago(31), "SunAir", 800),
    txn("RX11", "Z", "2024-01-10", "SunAir", 5000),  # orphan: Z is not a member
]


@pytest.fixture(scope="module")
def schema(sf_conn, sf_settings):
    db = sf_settings.database
    name = f"{db}.TEST_360_{uuid.uuid4().hex[:8].upper()}"
    cur = sf_conn.cursor()
    cur.execute(f"CREATE TRANSIENT SCHEMA {name}")
    try:
        cur.execute(f"CREATE TABLE {name}.COUNTRY_MAP CLONE {db}.SILVER.COUNTRY_MAP")
        for table in ("MEMBER_STG", "MEMBER_CURRENT", "REDEMPTION_TXN"):
            cur.execute(f"CREATE TABLE {name}.{table} LIKE {db}.SILVER.{table}")
        cur.execute(f"CREATE TABLE {name}.MEMBER_360 LIKE {db}.GOLD.MEMBER_360")
        cur.executemany(
            f"INSERT INTO {name}.MEMBER_STG (BATCH_DATE, MEMBER_ID, MEMBER_NAME, ENROLLMENT_DATE, "
            "LAST_FLIGHT_DATE, TIER_CODE, COUNTRY_RAW, COUNTRY_ISO, DOB, IS_ACTIVE, AGE, "
            "STALE_MEMBER, NEVER_FLOWN, RECORD_HASH, SOURCE_FILE, SOURCE_FILE_ROW_NO, LOAD_ID, "
            "LOAD_TS) VALUES (" + ", ".join(["%s"] * 18) + ")",
            MEMBERS,
        )
        cur.executemany(
            f"INSERT INTO {name}.REDEMPTION_TXN (TXN_ID, MEMBER_ID, FEED_DATE, TXN_DATE, PARTNER, "
            "IS_INTERNAL_PARTNER, MILES_REDEEMED, STATUS, IS_COMPLETED, ORPHAN_MEMBER, "
            "BATCH_DATE, SOURCE_FILE, SOURCE_FILE_ROW_NO, TXN_INDEX, LOAD_ID) VALUES ("
            + ", ".join(["%s"] * 15) + ")",
            REDEMPTIONS,
        )
        apply_batch(sf_conn, db, AS_OF, silver=name)
        build_member_360(sf_conn, db, AS_OF, silver=name, gold=name)
        yield name
    finally:
        cur.execute(f"DROP SCHEMA IF EXISTS {name}")


@pytest.fixture(scope="module")
def rows(sf_conn, schema):
    """member_id -> MEMBER_360 row as a dict."""
    cur = sf_conn.cursor()
    cur.execute(f"SELECT * FROM {schema}.MEMBER_360")
    cols = [c[0] for c in cur.description]
    return {r[0]: dict(zip(cols, r, strict=True)) for r in cur.fetchall()}


def pick(row, *cols):
    return tuple(row[c] for c in cols)


def test_one_row_per_member_and_orphans_left_out(rows):
    assert sorted(rows) == ["A", "B", "C", "D", "E", "F", "G"]


def test_miles_split_by_status(rows):
    a = rows["A"]
    assert pick(a, "TXN_COUNT", "COMPLETED_TXN_COUNT", "COMPLETED_MILES", "PENDING_MILES") == (
        4, 2, 3000, 500,
    )  # fmt: skip
    assert a["AVG_MILES_PER_COMPLETED_TXN"] == 1500


def test_last_redemption_ignores_cancelled(rows):
    assert pick(rows["A"], "LAST_REDEMPTION_DATE", "DAYS_SINCE_LAST_REDEMPTION") == (
        date(2024, 1, 14),
        3,
    )


def test_favourite_partner_by_count_then_miles_then_name(rows):
    assert rows["A"]["FAVOURITE_PARTNER"] == "SunAir"  # 2 txns beat 1 (cancelled not counted)
    assert rows["C"]["FAVOURITE_PARTNER"] == "SunAir"  # same count, more miles
    assert rows["B"]["FAVOURITE_PARTNER"] == "AeroLink"  # full tie: alphabetical


def test_member_without_redemptions_has_zero_metrics(rows):
    assert pick(rows["F"], "TXN_COUNT", "COMPLETED_MILES", "PENDING_MILES") == (0, 0, 0)
    assert pick(
        rows["F"], "AVG_MILES_PER_COMPLETED_TXN", "LAST_REDEMPTION_DATE", "FAVOURITE_PARTNER"
    ) == (None, None, None)


def test_lifecycle_status_boundaries(rows):
    assert {m: r["LIFECYCLE_STATUS"] for m, r in rows.items()} == {
        "A": "ACTIVE",
        "B": "AT_RISK",
        "C": "AT_RISK",
        "D": "DORMANT",
        "E": "NEVER_FLOWN",
        "F": "ACTIVE",
        "G": "DORMANT",
    }
    assert (rows["C"]["STALE_MEMBER"], rows["D"]["STALE_MEMBER"]) == (False, True)


def test_dormant_redeemer_is_stale_but_redeemed_in_last_30_days(rows):
    assert {m for m, r in rows.items() if r["DORMANT_REDEEMER"]} == {"D"}


def test_age_is_computed_at_the_as_of_date(rows):
    assert (rows["E"]["AGE"], rows["F"]["AGE"]) == (23, 24)
    assert {r["AS_OF_DATE"] for r in rows.values()} == {AS_OF}


def test_completed_miles_reconcile_with_non_orphan_transactions(sf_conn, schema, rows):
    cur = sf_conn.cursor()
    cur.execute(
        f"SELECT SUM(MILES_REDEEMED) FROM {schema}.REDEMPTION_TXN t "
        f"JOIN {schema}.MEMBER_CURRENT m ON m.MEMBER_ID = t.MEMBER_ID WHERE t.IS_COMPLETED"
    )
    assert sum(r["COMPLETED_MILES"] for r in rows.values()) == cur.fetchone()[0] == 11000


def test_rebuild_is_idempotent(sf_conn, sf_settings, schema):
    cur = sf_conn.cursor()
    sql = f"SELECT * EXCLUDE BUILT_AT FROM {schema}.MEMBER_360"
    before = set(cur.execute(sql).fetchall())
    build_member_360(sf_conn, sf_settings.database, AS_OF, silver=schema, gold=schema)
    assert set(cur.execute(sql).fetchall()) == before
