"""Synthetic SkyPoints member population, its daily changes, and the member flat-file rows.

`Member` holds the *true* state of a member. Defects are applied only to the outgoing
records, so the truth stays clean and every defect is traceable in the manifest.
"""

from __future__ import annotations

import random
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from typing import Any

from skypoints.datagen.defects import MEMBER_DEFECTS

# Column order of the brief's sample header (Post Code is in the layout but not the sample).
HEADER_FIELDS = (
    "Member_Name",
    "Member_Id",
    "Enrollment_Date",
    "Last_Flight_Date",
    "Tier_Code",
    "Agent_Name",
    "State",
    "Country",
    "DOB",
    "Is_Active",
)

COUNTRY_STATES: dict[str, tuple[str, ...]] = {
    "USA": ("CA", "NY", "TX", "FL"),
    "IND": ("TN", "MH", "KA", "DL"),
    "PHIL": ("NCR", "CEB"),
    "CAN": ("ONT", "BC", "QC"),
    "AU": ("VIC", "NSW", "QLD"),
}
# The source system is inconsistent about Australia's code (AU in the brief, AUS in extracts).
COUNTRY_ALIASES: dict[str, tuple[str, ...]] = {"AU": ("AU", "AUS")}
TIERS = ("SLV", "GLD", "PLT")
AGENTS = ("Sam", "Priya", "Liam", "Mei", "Omar")
FIRST_NAMES = (
    "Elena", "Ravi", "Mateo", "Nora", "Jacob", "Aisha", "Kenji", "Lucia", "Arjun", "Grace",
    "Diego", "Hana", "Ethan", "Maya", "Noah", "Zara", "Ivan", "Sofia", "Leo", "Amara",
)  # fmt: skip
LAST_NAMES = (
    "Cruz", "Iyer", "Santos", "Brown", "Wilson", "Khan", "Sato", "Rossi", "Mehta", "Lee",
    "Lopez", "Kim", "Clark", "Patel", "Smith", "Ali", "Petrov", "Garcia", "Jones", "Okafor",
)  # fmt: skip

FIRST_MEMBER_ID = 100_001
LAST_MEMBER_ID = 199_999
NEVER_FLOWN_RATE = 0.10


@dataclass(frozen=True)
class Member:
    member_id: str
    name: str
    enrollment_date: date
    last_flight_date: date | None
    tier: str
    agent: str
    country: str
    state: str
    dob: date
    is_active: bool


def _random_date(rng: random.Random, start: date, end: date) -> date:
    start = min(start, end)
    return start + timedelta(days=rng.randint(0, (end - start).days))


def new_member(rng: random.Random, member_id: int, as_of: date) -> Member:
    """A member aged 18-80 who enrolled as an adult; ~10% have never flown."""
    if not FIRST_MEMBER_ID <= member_id <= LAST_MEMBER_ID:
        raise ValueError(f"member_id {member_id} outside generator range")
    dob = _random_date(rng, as_of - timedelta(days=80 * 365), as_of - timedelta(days=18 * 365))
    enrolled = _random_date(rng, max(date(2005, 1, 1), dob + timedelta(days=18 * 365)), as_of)
    last_flight = None
    if rng.random() >= NEVER_FLOWN_RATE:
        # Up to ~400 days back so both stale (>90 days) and recent flyers exist.
        last_flight = _random_date(rng, max(enrolled, as_of - timedelta(days=400)), as_of)
    country = rng.choice(list(COUNTRY_STATES))
    return Member(
        member_id=str(member_id),
        name=f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}",
        enrollment_date=enrolled,
        last_flight_date=last_flight,
        tier=rng.choice(TIERS),
        agent=rng.choice(AGENTS),
        country=country,
        state=rng.choice(COUNTRY_STATES[country]),
        dob=dob,
        is_active=rng.random() < 0.9,
    )


def evolve(rng: random.Random, member: Member, as_of: date) -> tuple[Member, str]:
    """Apply one realistic day-over-day change and return (new state, change type)."""
    change = rng.choices(
        ("FLIGHT", "TIER_CHANGE", "COUNTRY_MOVE", "STATUS_CHANGE"), weights=(60, 15, 15, 10)
    )[0]
    if change == "FLIGHT":
        flown = max(member.enrollment_date, as_of - timedelta(days=rng.randint(0, 3)))
        return replace(member, last_flight_date=flown), change
    if change == "TIER_CHANGE":
        return replace(member, tier=rng.choice([t for t in TIERS if t != member.tier])), change
    if change == "COUNTRY_MOVE":
        country = rng.choice([c for c in COUNTRY_STATES if c != member.country])
        return replace(member, country=country, state=rng.choice(COUNTRY_STATES[country])), change
    return replace(member, is_active=not member.is_active), change


def to_record(rng: random.Random, member: Member) -> dict[str, str]:
    """Format a member as the source system writes it: dates YYYYMMDD, DOB DDMMYYYY."""
    return {
        "Member_Name": member.name,
        "Member_Id": member.member_id,
        "Enrollment_Date": member.enrollment_date.strftime("%Y%m%d"),
        "Last_Flight_Date": (
            member.last_flight_date.strftime("%Y%m%d") if member.last_flight_date else ""
        ),
        "Tier_Code": member.tier,
        "Agent_Name": member.agent,
        "State": member.state,
        "Country": rng.choice(COUNTRY_ALIASES.get(member.country, (member.country,))),
        "DOB": member.dob.strftime("%d%m%Y"),
        "Is_Active": "A" if member.is_active else "I",
    }


@dataclass
class _Line:
    record: dict[str, str]
    member_id: str
    defect: str | None = None
    duplicate_of: _Line | None = field(default=None, repr=False)


def build_member_feed(
    rng: random.Random,
    members: Iterable[Member],
    protected_ids: set[str],
    as_of: date,
    defect_rate: float,
) -> tuple[list[dict[str, str]], list[dict[str, Any]], set[str]]:
    """Build one day's member rows with injected defects.

    Rows for ``protected_ids`` (e.g. country moves) are never defected, so expected
    outcomes such as "member now lives in exactly one country table" stay unambiguous.
    Duplicates are inserted after their original; for a conflicting duplicate the earlier
    row carries a stale tier, so the later row (latest wins) holds the true state.

    Returns (records in file order, manifest defect entries, ids emitted with a clean row).
    """
    lines: list[_Line] = []
    for member in members:
        line = _Line(to_record(rng, member), member.member_id)
        if member.member_id not in protected_ids and rng.random() < defect_rate:
            line.defect = rng.choice(sorted(MEMBER_DEFECTS))
            MEMBER_DEFECTS[line.defect](line.record, rng, as_of)
        lines.append(line)

    clean = [ln for ln in lines if ln.defect is None and ln.member_id not in protected_ids]
    n_each = max(1, len(clean) // 100) if len(clean) >= 2 else 0
    picks = rng.sample(clean, k=min(len(clean), 2 * n_each))
    for i, original in enumerate(picks):
        defect = "EXACT_DUPLICATE" if i < n_each else "CONFLICTING_DUPLICATE"
        dup = _Line(dict(original.record), original.member_id, defect, duplicate_of=original)
        if defect == "CONFLICTING_DUPLICATE":
            stale_tier = rng.choice([t for t in TIERS if t != original.record["Tier_Code"]])
            original.record["Tier_Code"] = stale_tier
        lines.insert(rng.randint(lines.index(original) + 1, len(lines)), dup)

    line_no = {id(ln): i for i, ln in enumerate(lines, start=2)}  # line 1 is the header
    defects: list[dict[str, Any]] = []
    for ln in lines:
        if ln.defect is None:
            continue
        entry: dict[str, Any] = {
            "defect": ln.defect,
            "line_no": line_no[id(ln)],
            "member_id": ln.member_id,
        }
        if ln.duplicate_of is not None:
            entry["duplicate_of_line_no"] = line_no[id(ln.duplicate_of)]
        defects.append(entry)

    clean_ids = {ln.member_id for ln in lines if ln.defect is None}
    return [ln.record for ln in lines], defects, clean_ids
