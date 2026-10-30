"""Redemption flattening and rules, run in a throwaway schema with hand-made JSON documents."""

import json
import uuid
from datetime import date

import pytest

from skypoints.silver import redemptions

pytestmark = pytest.mark.integration

B1, B2 = date(2024, 1, 15), date(2024, 1, 16)


def txn(txn_id="T1", *, txn_date="20240110", partner="AeroLink", miles=12000, status="COMPLETED"):
    t = {"txn_id": txn_id, "txn_date": txn_date, "partner": partner,
         "miles_redeemed": miles, "status": status}  # fmt: skip
    if txn_id is None:
        del t["txn_id"]
    return t


def doc(member_id, *txns):
    d = {"feed_date": "20240115", "redemptions": list(txns)}
    if member_id is not None:
        d["member_id"] = member_id
    return d


DOCS = [
    doc(
        "M1",
        txn("T1"),
        txn("T2", partner="SkyPoints", miles="5000", status="pending "),
        txn("T3", status="DONE"),
        txn("T4", miles=0),
        txn("T5", miles=-10),
        txn("T6", txn_date="20241345"),
        txn("T7", txn_date="20240120"),
        txn(None),
    ),
    doc("M2", txn("T1"), txn("T_OLD"), txn("T9")),  # T1 repeats this batch; T_OLD an earlier one
    doc("M9", txn("T10")),  # M9 is not a member yet: orphan
    doc("M1"),  # no transactions
    doc(None, txn("T11")),
    doc("M1", txn("T12", miles="abc"), txn("T13", miles=12.5), txn("T14", partner="")),
]


@pytest.fixture(scope="module")
def schema(sf_conn, sf_settings):
    db = sf_settings.database
    name = f"{db}.TEST_REDEMPTION_{uuid.uuid4().hex[:8].upper()}"
    cur = sf_conn.cursor()
    cur.execute(f"CREATE TRANSIENT SCHEMA {name}")
    try:
        for table in ("MEMBER_CURRENT", "REDEMPTION_TXN", "REDEMPTION_REJECT"):
            cur.execute(f"CREATE TABLE {name}.{table} LIKE {db}.SILVER.{table}")
        cur.execute(f"CREATE TABLE {name}.RAW LIKE {db}.BRONZE.REDEMPTION_RAW")
        for member_id in ("M1", "M2"):
            add_member(cur, name, member_id)
        cur.execute(
            f"INSERT INTO {name}.REDEMPTION_TXN (TXN_ID, MEMBER_ID, TXN_DATE, PARTNER, "
            "IS_INTERNAL_PARTNER, MILES_REDEEMED, STATUS, IS_COMPLETED, ORPHAN_MEMBER, BATCH_DATE, "
            "SOURCE_FILE, SOURCE_FILE_ROW_NO, TXN_INDEX, LOAD_ID) VALUES ('T_OLD', 'M2', "
            "'2024-01-10', 'AeroLink', FALSE, 100, 'COMPLETED', TRUE, FALSE, '2024-01-14', "
            "'OLD.json', 1, 0, 'old')"
        )
        for row_no, d in enumerate(DOCS, start=1):
            cur.execute(
                f"INSERT INTO {name}.RAW (PAYLOAD, SOURCE_FILE, SOURCE_FILE_ROW_NO, BATCH_DATE, "
                "LOAD_ID) SELECT PARSE_JSON(%s), 'TEST.json', %s, %s, 'test'",
                (json.dumps(d), row_no, B1.isoformat()),
            )
        redemptions.load_batch(sf_conn, db, B1, silver=name, source=f"{name}.RAW")
        yield name
    finally:
        cur.execute(f"DROP SCHEMA IF EXISTS {name}")


def add_member(cur, schema, member_id):
    cur.execute(
        f"INSERT INTO {schema}.MEMBER_CURRENT (MEMBER_ID, MEMBER_NAME, ENROLLMENT_DATE, "
        "TARGET_TABLE, STALE_MEMBER, NEVER_FLOWN, RECORD_HASH, FIRST_BATCH_DATE, LAST_BATCH_DATE, "
        "ROW_UPDATED_BATCH, SOURCE_FILE, SOURCE_FILE_ROW_NO) VALUES (%s, 'x', '2010-01-01', "
        "'MEMBER_US', FALSE, FALSE, 'h', '2024-01-01', '2024-01-01', '2024-01-01', 'x', 1)",
        (member_id,),
    )


def rows(conn, schema, table):
    cur = conn.cursor()
    cur.execute(f"SELECT * FROM {schema}.{table} WHERE SOURCE_FILE = 'TEST.json'")
    columns = [c[0] for c in cur.description]
    out = []
    for values in cur.fetchall():
        r = dict(zip(columns, values, strict=True))
        for key in ("DQ_FLAGS", "REJECT_REASONS"):
            if key in r and r[key] is not None:
                r[key] = json.loads(r[key])
        out.append(r)
    return out


def accepted(conn, schema):
    return {r["TXN_ID"]: r for r in rows(conn, schema, "REDEMPTION_TXN")}


def rejected(conn, schema):
    return {
        (r["SOURCE_FILE_ROW_NO"], r["TXN_INDEX"]): r
        for r in rows(conn, schema, "REDEMPTION_REJECT")
    }


def test_clean_txn_flattened_and_derived(sf_conn, schema):
    t1 = accepted(sf_conn, schema)["T1"]
    assert (t1["MEMBER_ID"], t1["SOURCE_FILE_ROW_NO"], t1["TXN_INDEX"]) == ("M1", 1, 0)
    assert (t1["TXN_DATE"], t1["FEED_DATE"], t1["FEED_LAG_DAYS"]) == (date(2024, 1, 10), B1, 5)
    assert (t1["MILES_REDEEMED"], t1["STATUS"], t1["IS_COMPLETED"]) == (12000, "COMPLETED", True)
    assert (t1["IS_INTERNAL_PARTNER"], t1["ORPHAN_MEMBER"], t1["DQ_FLAGS"]) == (False, False, [])


def test_repairable_values_are_kept_and_flagged(sf_conn, schema):
    t2 = accepted(sf_conn, schema)["T2"]
    assert (t2["STATUS"], t2["MILES_REDEEMED"], t2["IS_INTERNAL_PARTNER"]) == (
        "PENDING",
        5000,
        True,
    )
    assert t2["DQ_FLAGS"] == ["STATUS_NORMALISED", "MILES_CAST_FROM_STRING"]


@pytest.mark.parametrize(
    ("position", "reasons"),
    [
        ((1, 2), ["INVALID_STATUS"]),
        ((1, 3), ["NEGATIVE_OR_ZERO_MILES"]),
        ((1, 4), ["NEGATIVE_OR_ZERO_MILES"]),
        ((1, 5), ["INVALID_TXN_DATE"]),
        ((1, 6), ["FUTURE_TXN_DATE"]),
        ((1, 7), ["MISSING_TXN_ID"]),
        ((2, 0), ["DUPLICATE_TXN_ID"]),  # T1 already seen earlier in the file
        ((2, 1), ["DUPLICATE_TXN_ID"]),  # T_OLD accepted in an earlier batch
        ((4, None), ["EMPTY_REDEMPTIONS"]),
        ((5, 0), ["MISSING_MEMBER_ID"]),
        ((6, 0), ["INVALID_MILES"]),
        ((6, 1), ["INVALID_MILES"]),
        ((6, 2), ["MISSING_PARTNER"]),
    ],
)
def test_rejected(sf_conn, schema, position, reasons):
    assert rejected(sf_conn, schema)[position]["REJECT_REASONS"] == reasons


def test_every_txn_accounted_for(sf_conn, schema):
    total = sum(max(len(d["redemptions"]), 1) for d in DOCS)
    assert len(accepted(sf_conn, schema)) + len(rejected(sf_conn, schema)) == total
    assert set(accepted(sf_conn, schema)) == {"T1", "T2", "T9", "T10"}


def test_orphan_kept_then_resolved_when_member_arrives(sf_conn, sf_settings, schema):
    assert accepted(sf_conn, schema)["T10"]["ORPHAN_MEMBER"] is True
    before = {
        k: (v["ORPHAN_MEMBER"], v["MILES_REDEEMED"]) for k, v in accepted(sf_conn, schema).items()
    }

    # Re-running the batch changes nothing.
    db = sf_settings.database
    redemptions.load_batch(sf_conn, db, B1, silver=schema, source=f"{schema}.RAW")
    after = {
        k: (v["ORPHAN_MEMBER"], v["MILES_REDEEMED"]) for k, v in accepted(sf_conn, schema).items()
    }
    assert after == before

    # M9 arrives; the next batch (no redemptions of its own) resolves the orphan.
    add_member(sf_conn.cursor(), schema, "M9")
    redemptions.load_batch(sf_conn, db, B2, silver=schema, source=f"{schema}.RAW")
    t10 = accepted(sf_conn, schema)["T10"]
    assert (t10["ORPHAN_MEMBER"], t10["ORPHAN_RESOLVED_BATCH"]) == (False, B2)
