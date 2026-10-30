"""Silver must catch every redemption defect the generator injected, and nothing else."""

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

LANDING = Path("data/landing")

# Generator defect -> (where the transaction must end up, reason or flag)
EXPECTED = {
    "MISSING_TXN_ID": ("reject", "MISSING_TXN_ID"),
    "NEGATIVE_OR_ZERO_MILES": ("reject", "NEGATIVE_OR_ZERO_MILES"),
    "INVALID_STATUS": ("reject", "INVALID_STATUS"),
    "INVALID_TXN_DATE": ("reject", "INVALID_TXN_DATE"),
    "FUTURE_TXN_DATE": ("reject", "FUTURE_TXN_DATE"),
    "DUPLICATE_TXN_ID": ("reject", "DUPLICATE_TXN_ID"),
    "STATUS_LOWERCASE": ("flag", "STATUS_NORMALISED"),
    "MILES_AS_STRING": ("flag", "MILES_CAST_FROM_STRING"),
}


def _manifests():
    paths = sorted(LANDING.glob("MANIFEST_*.json"))
    if not paths:
        pytest.skip("no generated data in data/landing")
    return [json.loads(p.read_text()) for p in paths]


@pytest.fixture(scope="module")
def silver(sf_conn):
    cur = sf_conn.cursor()
    accepted = {
        (f, n, i): (json.loads(flags), orphan)
        for f, n, i, flags, orphan in cur.execute(
            "SELECT SOURCE_FILE, SOURCE_FILE_ROW_NO, TXN_INDEX, DQ_FLAGS, ORPHAN_MEMBER "
            "FROM SILVER.REDEMPTION_TXN"
        ).fetchall()
    }
    rejected = {
        (f, n, i): json.loads(reasons)
        for f, n, i, reasons in cur.execute(
            "SELECT SOURCE_FILE, SOURCE_FILE_ROW_NO, TXN_INDEX, REJECT_REASONS "
            "FROM SILVER.REDEMPTION_REJECT"
        ).fetchall()
    }
    bronze_units = cur.execute(
        "SELECT SUM(GREATEST(COALESCE(ARRAY_SIZE(PAYLOAD:redemptions), 0), 1)) "
        "FROM BRONZE.REDEMPTION_RAW"
    ).fetchone()[0]
    return accepted, rejected, bronze_units


def _expected_positions():
    """Every (file, line, txn_index) the manifests say is defective."""
    positions = {}
    for manifest in _manifests():
        f = manifest["redemption_file"]
        for d in manifest["redemption_defects"]:
            positions[(f, d["line_no"], d.get("txn_index"))] = d["defect"]
    return positions


def test_every_bronze_transaction_is_accepted_or_rejected(silver):
    accepted, rejected, bronze_units = silver
    assert not accepted.keys() & rejected.keys()
    assert len(accepted) + len(rejected) == bronze_units


def test_every_injected_defect_is_caught(silver):
    accepted, rejected, _ = silver
    for (f, line, idx), defect in _expected_positions().items():
        if defect == "EMPTY_REDEMPTIONS":
            assert rejected[(f, line, None)] == ["EMPTY_REDEMPTIONS"]
        elif defect == "ORPHAN_MEMBER":
            assert accepted[(f, line, 0)][1] is True
        else:
            where, code = EXPECTED[defect]
            found = (
                rejected.get((f, line, idx))
                if where == "reject"
                else accepted.get((f, line, idx), ([],))[0]
            )
            assert found is not None and code in found, (f, line, idx, defect, found)


def test_no_false_positives(silver):
    accepted, rejected, _ = silver
    positions = _expected_positions()
    orphan_lines = {(f, line) for (f, line, _), d in positions.items() if d == "ORPHAN_MEMBER"}
    assert set(rejected) <= set(positions)
    assert {k for k, (flags, _) in accepted.items() if flags} <= set(positions)
    assert {(f, line) for (f, line, _), (_, orphan) in accepted.items() if orphan} <= orphan_lines
