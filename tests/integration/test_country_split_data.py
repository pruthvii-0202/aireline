"""Country split on the generated data in SKYPOINTS_DEV (run the pipeline first)."""

import json
from pathlib import Path

import pytest

from skypoints.silver.current import target_tables

pytestmark = pytest.mark.integration

LANDING = Path("data/landing")


@pytest.fixture(scope="module")
def placement(sf_conn, sf_settings):
    """member_id -> list of country tables holding it."""
    silver = f"{sf_settings.database}.SILVER"
    cur = sf_conn.cursor()
    where: dict[str, list[str]] = {}
    for table in target_tables(cur, silver):
        for (member_id,) in cur.execute(f"SELECT MEMBER_ID FROM {silver}.{table}").fetchall():
            where.setdefault(member_id, []).append(table)
    current = dict(
        cur.execute(f"SELECT MEMBER_ID, TARGET_TABLE FROM {silver}.MEMBER_CURRENT").fetchall()
    )
    return where, current


def test_each_current_member_in_exactly_its_target_table(placement):
    where, current = placement
    assert where.keys() == current.keys()
    assert all(where[m] == [current[m]] for m in current)


def test_country_moves_land_in_new_country(placement):
    where, _ = placement
    manifests = [json.loads(p.read_text()) for p in sorted(LANDING.glob("MANIFEST_*.json"))]
    if not manifests:
        pytest.skip("no generated data in data/landing")
    iso_table = {"USA": "MEMBER_US", "IND": "MEMBER_IN", "PHIL": "MEMBER_PH",
                 "CAN": "MEMBER_CA", "AU": "MEMBER_AU"}  # fmt: skip
    final_move = {}
    for i, manifest in enumerate(manifests):
        for mv in manifest["country_moves"]:
            final_move[mv["member_id"]] = (i, mv["to_country"])
    checked = 0
    for member_id, (day, to_country) in final_move.items():
        # A later defective row for the same member would legitimately change the outcome.
        later = {d["member_id"] for m in manifests[day + 1 :] for d in m["member_defects"]}
        if member_id in later:
            continue
        assert where[member_id] == [iso_table[to_country]], member_id
        checked += 1
    assert checked > 0
