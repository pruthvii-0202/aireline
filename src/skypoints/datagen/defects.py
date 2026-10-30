"""Defect injectors for the synthetic feeds.

Each injector mutates one outgoing record in place. Defect names are the reason codes the
pipeline's validations are expected to emit, so the manifest written next to each feed is
the ground truth for validation coverage.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any

Record = dict[str, Any]
Injector = Callable[[Record, random.Random, date], None]


def _blank(field: str) -> Injector:
    def inject(rec: Record, rng: random.Random, as_of: date) -> None:
        rec[field] = ""

    return inject


def _invalid_enrollment_date(rec: Record, rng: random.Random, as_of: date) -> None:
    """Month 13, like the 2021-13-13 seen in the AUS sample extract."""
    rec["Enrollment_Date"] = f"{rng.randint(2010, 2023)}13{rng.randint(1, 28):02d}"


def _invalid_last_flight_date(rec: Record, rng: random.Random, as_of: date) -> None:
    rec["Last_Flight_Date"] = f"{rng.randint(2015, 2023)}0230"


def _invalid_dob(rec: Record, rng: random.Random, as_of: date) -> None:
    rec["DOB"] = f"32{rng.randint(1, 12):02d}{rng.randint(1950, 2000)}"


def _future_dob(rec: Record, rng: random.Random, as_of: date) -> None:
    rec["DOB"] = (as_of + timedelta(days=rng.randint(30, 3650))).strftime("%d%m%Y")


def _dob_leading_zero_dropped(rec: Record, rng: random.Random, as_of: date) -> None:
    """Mirrors the brief's staging sample, where 03051985 became 3051985 (integer cast)."""
    rec["DOB"] = f"{rng.randint(1, 9)}{rec['DOB'][2:]}"


def _short_member_id(rec: Record, rng: random.Random, as_of: date) -> None:
    """Like 22345 / 2256 in the brief. Ids are 100001-199999, so the modulo stays unique."""
    rec["Member_Id"] = str(int(rec["Member_Id"]) % 100_000)


def _id_too_long(rec: Record, rng: random.Random, as_of: date) -> None:
    """Exceeds the 18-character Member ID length in the layout."""
    rec["Member_Id"] = rec["Member_Id"].rjust(19, "9")


def _flight_before_enrollment(rec: Record, rng: random.Random, as_of: date) -> None:
    enrolled = datetime.strptime(rec["Enrollment_Date"], "%Y%m%d").date()
    rec["Last_Flight_Date"] = (enrolled - timedelta(days=rng.randint(1, 365))).strftime("%Y%m%d")


def _unknown_tier(rec: Record, rng: random.Random, as_of: date) -> None:
    rec["Tier_Code"] = "BRZ"


def _invalid_active_flag(rec: Record, rng: random.Random, as_of: date) -> None:
    rec["Is_Active"] = rng.choice(("Y", "N", "1"))


def _unknown_country(rec: Record, rng: random.Random, as_of: date) -> None:
    rec["Country"] = rng.choice(("ZZ", "XX", "UNK"))


def _needs_normalisation(rec: Record, rng: random.Random, as_of: date) -> None:
    """Valid values with stray whitespace and wrong case; should be fixed, not rejected."""
    rec["Tier_Code"] = f" {rec['Tier_Code'].lower()} "
    rec["Country"] = f"{rec['Country'].lower()} "


MEMBER_DEFECTS: dict[str, Injector] = {
    "MISSING_MEMBER_NAME": _blank("Member_Name"),
    "MISSING_MEMBER_ID": _blank("Member_Id"),
    "MISSING_ENROLLMENT_DATE": _blank("Enrollment_Date"),
    "INVALID_ENROLLMENT_DATE": _invalid_enrollment_date,
    "INVALID_LAST_FLIGHT_DATE": _invalid_last_flight_date,
    "INVALID_DOB": _invalid_dob,
    "FUTURE_DOB": _future_dob,
    "DOB_LEADING_ZERO_DROPPED": _dob_leading_zero_dropped,
    "SHORT_MEMBER_ID": _short_member_id,
    "ID_TOO_LONG": _id_too_long,
    "FLIGHT_BEFORE_ENROLLMENT": _flight_before_enrollment,
    "UNKNOWN_TIER": _unknown_tier,
    "INVALID_ACTIVE_FLAG": _invalid_active_flag,
    "UNKNOWN_COUNTRY": _unknown_country,
    "NEEDS_NORMALISATION": _needs_normalisation,
}

# Added by the feed builder rather than by mutating a single record.
MEMBER_DUPLICATE_DEFECTS = ("EXACT_DUPLICATE", "CONFLICTING_DUPLICATE")


def _missing_txn_id(txn: Record, rng: random.Random, as_of: date) -> None:
    del txn["txn_id"]


def _non_positive_miles(txn: Record, rng: random.Random, as_of: date) -> None:
    txn["miles_redeemed"] = rng.choice((0, -txn["miles_redeemed"]))


def _invalid_status(txn: Record, rng: random.Random, as_of: date) -> None:
    txn["status"] = rng.choice(("DONE", "UNKNOWN"))


def _status_lowercase(txn: Record, rng: random.Random, as_of: date) -> None:
    txn["status"] = txn["status"].lower()


def _invalid_txn_date(txn: Record, rng: random.Random, as_of: date) -> None:
    txn["txn_date"] = f"{as_of.year}1345"


def _future_txn_date(txn: Record, rng: random.Random, as_of: date) -> None:
    txn["txn_date"] = (as_of + timedelta(days=rng.randint(1, 30))).strftime("%Y%m%d")


def _miles_as_string(txn: Record, rng: random.Random, as_of: date) -> None:
    """Type drift: a numeric field arrives as a JSON string."""
    txn["miles_redeemed"] = str(txn["miles_redeemed"])


TXN_DEFECTS: dict[str, Injector] = {
    "MISSING_TXN_ID": _missing_txn_id,
    "NEGATIVE_OR_ZERO_MILES": _non_positive_miles,
    "INVALID_STATUS": _invalid_status,
    "STATUS_LOWERCASE": _status_lowercase,
    "INVALID_TXN_DATE": _invalid_txn_date,
    "FUTURE_TXN_DATE": _future_txn_date,
    "MILES_AS_STRING": _miles_as_string,
}

# Added by the feed builder: whole-document or cross-record defects.
REDEMPTION_FEED_DEFECTS = ("DUPLICATE_TXN_ID", "ORPHAN_MEMBER", "EMPTY_REDEMPTIONS")
