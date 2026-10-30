"""End-to-end checks on generated feeds: the manifest must describe the files exactly."""

import json
from datetime import date, datetime
from pathlib import Path

import pytest

from skypoints.datagen.defects import (
    MEMBER_DEFECTS,
    MEMBER_DUPLICATE_DEFECTS,
    REDEMPTION_FEED_DEFECTS,
    TXN_DEFECTS,
)
from skypoints.datagen.generator import generate
from skypoints.datagen.members import COUNTRY_ALIASES, COUNTRY_STATES, HEADER_FIELDS, TIERS
from skypoints.datagen.redemptions import STATUSES

START = date(2024, 1, 15)
DAYS = 3
KNOWN_COUNTRIES = {alias for c in COUNTRY_STATES for alias in COUNTRY_ALIASES.get(c, (c,))}


def _strict_date(value: str, fmt: str) -> date | None:
    """Python's strptime accepts 1-digit days/months, so insist on 8 digits first."""
    if len(value) != 8 or not value.isdigit():
        return None
    try:
        return datetime.strptime(value, fmt).date()
    except ValueError:
        return None


MEMBER_CHECKS = {
    "MISSING_MEMBER_NAME": lambda r, d: r["Member_Name"] == "",
    "MISSING_MEMBER_ID": lambda r, d: r["Member_Id"] == "",
    "MISSING_ENROLLMENT_DATE": lambda r, d: r["Enrollment_Date"] == "",
    "INVALID_ENROLLMENT_DATE": lambda r, d: _strict_date(r["Enrollment_Date"], "%Y%m%d") is None,
    "INVALID_LAST_FLIGHT_DATE": lambda r, d: _strict_date(r["Last_Flight_Date"], "%Y%m%d") is None,
    "INVALID_DOB": lambda r, d: _strict_date(r["DOB"], "%d%m%Y") is None,
    "FUTURE_DOB": lambda r, d: _strict_date(r["DOB"], "%d%m%Y") > d,
    "DOB_LEADING_ZERO_DROPPED": lambda r, d: len(r["DOB"]) == 7,
    "SHORT_MEMBER_ID": lambda r, d: 0 < len(r["Member_Id"]) < 6,
    "ID_TOO_LONG": lambda r, d: len(r["Member_Id"]) > 18,
    "FLIGHT_BEFORE_ENROLLMENT": lambda r, d: r["Last_Flight_Date"] < r["Enrollment_Date"],
    "UNKNOWN_TIER": lambda r, d: r["Tier_Code"] not in TIERS,
    "INVALID_ACTIVE_FLAG": lambda r, d: r["Is_Active"] not in ("A", "I"),
    "UNKNOWN_COUNTRY": lambda r, d: r["Country"] not in KNOWN_COUNTRIES,
    "NEEDS_NORMALISATION": lambda r, d: (
        r["Tier_Code"].strip().upper() in TIERS and r["Tier_Code"] != r["Tier_Code"].strip().upper()
    ),
}

TXN_CHECKS = {
    "MISSING_TXN_ID": lambda t, d: "txn_id" not in t,
    "NEGATIVE_OR_ZERO_MILES": lambda t, d: t["miles_redeemed"] <= 0,
    "INVALID_STATUS": lambda t, d: t["status"].upper() not in STATUSES,
    "STATUS_LOWERCASE": lambda t, d: t["status"].islower() and t["status"].upper() in STATUSES,
    "INVALID_TXN_DATE": lambda t, d: _strict_date(t["txn_date"], "%Y%m%d") is None,
    "FUTURE_TXN_DATE": lambda t, d: _strict_date(t["txn_date"], "%Y%m%d") > d,
    "MILES_AS_STRING": lambda t, d: isinstance(t["miles_redeemed"], str),
}


@pytest.fixture(scope="module")
def out_dir(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("landing")
    generate(out, days=DAYS, members=2000, seed=7, start=START)
    return out


def _days(out_dir: Path):
    for manifest_path in sorted(out_dir.glob("MANIFEST_*.json")):
        manifest = json.loads(manifest_path.read_text())
        lines = (out_dir / manifest["member_file"]).read_text().splitlines()
        docs = [
            json.loads(x) for x in (out_dir / manifest["redemption_file"]).read_text().splitlines()
        ]
        yield manifest, lines, docs


def _record(line: str) -> dict[str, str]:
    parts = line.split("|")
    assert parts[:2] == ["", "D"], line
    return dict(zip(HEADER_FIELDS, parts[2:], strict=True))


def test_writes_three_files_per_day(out_dir):
    names = sorted(p.name for p in out_dir.iterdir())
    assert len(names) == 3 * DAYS
    assert "MEMBER_PROFILE_20240115_06000000.txt" in names
    assert "REDEMPTIONS_20240115.json" in names


def test_member_file_layout_matches_brief(out_dir):
    for manifest, lines, _ in _days(out_dir):
        assert lines[0] == "|H|" + "|".join(HEADER_FIELDS)
        assert len(lines) - 1 == manifest["member_rows"]
        for line in lines[1:]:
            _record(line)


def test_day_one_is_full_extract_later_days_are_deltas(out_dir):
    rows = [m["member_rows"] for m, _, _ in _days(out_dir)]
    assert rows[0] >= 2000
    assert all(r < rows[0] / 4 for r in rows[1:])


def test_same_seed_gives_identical_files(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    generate(a, days=2, members=200, seed=1, start=START)
    generate(b, days=2, members=200, seed=1, start=START)
    for f in a.iterdir():
        assert f.read_bytes() == (b / f.name).read_bytes()


def test_every_manifest_member_defect_is_visible_on_its_line(out_dir):
    for manifest, lines, _ in _days(out_dir):
        feed_date = _strict_date(manifest["feed_date"], "%Y%m%d")
        for d in manifest["member_defects"]:
            rec = _record(lines[d["line_no"] - 1])
            if d["defect"] in MEMBER_DUPLICATE_DEFECTS:
                original = _record(lines[d["duplicate_of_line_no"] - 1])
                assert rec["Member_Id"] == original["Member_Id"] == d["member_id"]
                assert (rec == original) == (d["defect"] == "EXACT_DUPLICATE")
            else:
                assert MEMBER_CHECKS[d["defect"]](rec, feed_date), d


def test_all_member_defect_types_are_exercised(out_dir):
    assert set(MEMBER_CHECKS) == set(MEMBER_DEFECTS)
    seen = {d["defect"] for m, _, _ in _days(out_dir) for d in m["member_defects"]}
    assert seen == set(MEMBER_DEFECTS) | set(MEMBER_DUPLICATE_DEFECTS)


def test_country_moves_appear_with_new_country(out_dir):
    moves = 0
    for manifest, lines, _ in _days(out_dir):
        by_id = {}
        for line in lines[1:]:
            rec = _record(line)
            by_id.setdefault(rec["Member_Id"], []).append(rec)
        for mv in manifest["country_moves"]:
            [rec] = by_id[mv["member_id"]]  # exactly one, undefected row
            assert rec["Country"] in COUNTRY_ALIASES.get(mv["to_country"], (mv["to_country"],))
            moves += 1
    assert moves > 0


def test_every_manifest_redemption_defect_is_visible(out_dir):
    for manifest, _, docs in _days(out_dir):
        feed_date = _strict_date(manifest["feed_date"], "%Y%m%d")
        for d in manifest["redemption_defects"]:
            doc = docs[d["line_no"] - 1]
            if d["defect"] == "EMPTY_REDEMPTIONS":
                assert doc["redemptions"] == []
            elif d["defect"] == "ORPHAN_MEMBER":
                assert doc["member_id"].startswith("9")
            elif d["defect"] == "DUPLICATE_TXN_ID":
                assert doc["redemptions"][d["txn_index"]]["txn_id"] == d["txn_id"]
            else:
                assert TXN_CHECKS[d["defect"]](doc["redemptions"][d["txn_index"]], feed_date), d


def test_all_redemption_defect_types_are_exercised(out_dir):
    assert set(TXN_CHECKS) == set(TXN_DEFECTS)
    seen = {d["defect"] for m, _, _ in _days(out_dir) for d in m["redemption_defects"]}
    assert seen == set(TXN_DEFECTS) | set(REDEMPTION_FEED_DEFECTS)


def test_txn_ids_unique_except_injected_duplicates(out_dir):
    ids = [
        t["txn_id"]
        for _, _, docs in _days(out_dir)
        for doc in docs
        for t in doc["redemptions"]
        if "txn_id" in t
    ]
    injected = sum(
        d["defect"] == "DUPLICATE_TXN_ID"
        for m, _, _ in _days(out_dir)
        for d in m["redemption_defects"]
    )
    assert len(ids) - len(set(ids)) == injected


def test_redemptions_only_reference_known_members_or_flagged_orphans(out_dir):
    clean_ids = set()
    for manifest, lines, docs in _days(out_dir):
        defected = {d["line_no"] for d in manifest["member_defects"]}
        clean_ids |= {
            _record(line)["Member_Id"] for n, line in enumerate(lines[1:], 2) if n not in defected
        }
        orphan_lines = {
            d["line_no"] for d in manifest["redemption_defects"] if d["defect"] == "ORPHAN_MEMBER"
        }
        for n, doc in enumerate(docs, 1):
            assert (doc["member_id"] in clean_ids) != (n in orphan_lines)
