import random
from datetime import date

import pytest

from skypoints.datagen.defects import MEMBER_DEFECTS
from skypoints.datagen.members import (
    TIERS,
    Member,
    build_member_feed,
    evolve,
    new_member,
    to_record,
)

AS_OF = date(2024, 1, 15)


def _member(**overrides) -> Member:
    base = dict(
        member_id="123457",
        name="Elena Cruz",
        enrollment_date=date(2010, 10, 12),
        last_flight_date=date(2012, 10, 13),
        tier="GLD",
        agent="Sam",
        country="USA",
        state="CA",
        dob=date(1985, 5, 3),
        is_active=True,
    )
    return Member(**{**base, **overrides})


def test_to_record_uses_source_formats():
    rec = to_record(random.Random(0), _member())
    assert rec["Enrollment_Date"] == "20101012"
    assert rec["DOB"] == "03051985"  # DDMMYYYY keeps the leading zero
    assert rec["Is_Active"] == "A"


def test_to_record_blank_flight_date_when_never_flown():
    assert to_record(random.Random(0), _member(last_flight_date=None))["Last_Flight_Date"] == ""


def test_new_member_is_internally_consistent():
    rng = random.Random(1)
    for i in range(500):
        m = new_member(rng, 100_001 + i, AS_OF)
        assert m.dob < m.enrollment_date <= AS_OF
        assert m.last_flight_date is None or m.enrollment_date <= m.last_flight_date <= AS_OF


def test_new_member_rejects_id_outside_range():
    with pytest.raises(ValueError):
        new_member(random.Random(0), 99, AS_OF)


def test_evolve_country_move_changes_country_and_state():
    rng = random.Random(3)
    for _ in range(200):
        after, change = evolve(rng, _member(), AS_OF)
        if change == "COUNTRY_MOVE":
            assert after.country != "USA"
            assert after.member_id == "123457"
            return
    pytest.fail("no COUNTRY_MOVE in 200 draws")


def test_short_member_id_is_shorter_and_unique():
    ids = set()
    for mid in ("100001", "123457", "199999"):
        rec = {"Member_Id": mid}
        MEMBER_DEFECTS["SHORT_MEMBER_ID"](rec, random.Random(0), AS_OF)
        assert len(rec["Member_Id"]) < 6
        ids.add(rec["Member_Id"])
    assert len(ids) == 3


def test_dob_leading_zero_dropped_gives_seven_digits():
    rec = {"DOB": "03051985"}
    MEMBER_DEFECTS["DOB_LEADING_ZERO_DROPPED"](rec, random.Random(0), AS_OF)
    assert len(rec["DOB"]) == 7


def test_protected_members_are_never_defected():
    rng = random.Random(5)
    members = [new_member(rng, 100_001 + i, AS_OF) for i in range(200)]
    protected = {m.member_id for m in members}
    _, defects, clean = build_member_feed(rng, members, protected, AS_OF, defect_rate=1.0)
    assert defects == []
    assert clean == protected


def test_conflicting_duplicate_later_row_holds_true_state():
    rng = random.Random(9)
    members = [new_member(rng, 100_001 + i, AS_OF) for i in range(300)]
    truth = {m.member_id: m for m in members}
    records, defects, _ = build_member_feed(rng, members, set(), AS_OF, defect_rate=0.0)
    conflicts = [d for d in defects if d["defect"] == "CONFLICTING_DUPLICATE"]
    assert conflicts
    for d in conflicts:
        later, earlier = records[d["line_no"] - 2], records[d["duplicate_of_line_no"] - 2]
        assert d["duplicate_of_line_no"] < d["line_no"]
        assert later["Tier_Code"] == truth[d["member_id"]].tier
        assert earlier["Tier_Code"] != later["Tier_Code"]
        assert earlier["Tier_Code"] in TIERS
