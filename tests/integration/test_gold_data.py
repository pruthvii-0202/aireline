"""Gold on the generated data (run the Bronze and Silver pipeline first)."""

import json
from pathlib import Path

import pytest

from skypoints.gold.__main__ import main
from skypoints.gold.build import latest_batch_date

pytestmark = pytest.mark.integration

LANDING = Path("data/landing")
ISO = {"USA": "US", "IND": "IN", "PHIL": "PH", "CAN": "CA", "AU": "AU"}


@pytest.fixture(scope="module")
def db(sf_conn, sf_settings):
    """Build Gold through the CLI, then hand back a cursor and the schema names."""
    main([])
    database = sf_settings.database
    return sf_conn.cursor(), f"{database}.SILVER", f"{database}.GOLD"


def test_member_360_is_as_of_the_latest_batch(db):
    cur, silver, gold = db
    as_of = latest_batch_date(cur, silver)
    assert as_of is not None
    assert cur.execute(f"SELECT DISTINCT AS_OF_DATE FROM {gold}.MEMBER_360").fetchall() == [
        (as_of,)
    ]


def test_current_versions_match_member_current(db):
    cur, silver, gold = db
    cols = (
        "MEMBER_ID, MEMBER_NAME, ENROLLMENT_DATE, TIER_CODE, AGENT_NAME, STATE, COUNTRY_ISO, "
        "DOB, IS_ACTIVE"
    )
    dim = cur.execute(f"SELECT {cols} FROM {gold}.DIM_MEMBER WHERE IS_CURRENT").fetchall()
    current = cur.execute(f"SELECT {cols} FROM {silver}.MEMBER_CURRENT").fetchall()
    assert len(dim) == len({r[0] for r in dim})  # one current version per member
    assert set(dim) == set(current)


def test_every_known_member_redemption_finds_exactly_one_version(db):
    cur, silver, gold = db
    unmatched, multiple = cur.execute(
        f"""
        SELECT COUNT_IF(n = 0), COUNT_IF(n > 1) FROM (
            SELECT t.TXN_ID, COUNT(d.MEMBER_SK) AS n
            FROM {silver}.REDEMPTION_TXN t
            JOIN {silver}.MEMBER_CURRENT m ON m.MEMBER_ID = t.MEMBER_ID
            LEFT JOIN {gold}.DIM_MEMBER d
                ON d.MEMBER_ID = t.MEMBER_ID AND t.TXN_DATE BETWEEN d.VALID_FROM AND d.VALID_TO
            GROUP BY t.TXN_ID)
        """
    ).fetchone()
    assert (unmatched, multiple) == (0, 0)


def test_completed_miles_reconcile_with_silver(db):
    cur, silver, gold = db
    gold_miles = cur.execute(f"SELECT SUM(COMPLETED_MILES) FROM {gold}.MEMBER_360").fetchone()[0]
    silver_miles = cur.execute(
        f"SELECT SUM(t.MILES_REDEEMED) FROM {silver}.REDEMPTION_TXN t "
        f"JOIN {silver}.MEMBER_CURRENT m ON m.MEMBER_ID = t.MEMBER_ID WHERE t.IS_COMPLETED"
    ).fetchone()[0]
    assert gold_miles == silver_miles > 0


def test_country_moves_from_the_manifest_open_a_new_version(db):
    cur, _, gold = db
    manifests = [json.loads(p.read_text()) for p in sorted(LANDING.glob("MANIFEST_*.json"))]
    if not manifests:
        pytest.skip("no generated data in data/landing")
    defective = {d["member_id"] for m in manifests for d in m["member_defects"]}
    moves = {}
    for m in manifests:
        for mv in m["country_moves"]:
            moves[mv["member_id"]] = (mv["from_country"], ISO[mv["to_country"]])
    checked = 0
    for member_id, (_, to_iso) in moves.items():
        if member_id in defective:  # a defective row changes what is expected
            continue
        rows = cur.execute(
            f"SELECT COUNTRY_ISO, IS_CURRENT FROM {gold}.DIM_MEMBER "
            "WHERE MEMBER_ID = %s ORDER BY VERSION_NO",
            (member_id,),
        ).fetchall()
        assert len(rows) >= 2, member_id
        assert rows[-1] == (to_iso, True), member_id
        checked += 1
    assert checked > 0
