"""Bronze loader: upload landing files to the stage and COPY them into the raw tables.

Each file is loaded exactly once:
1. META.FILE_LOAD_LOG: a file already LOADED is skipped. If the same file name comes back
   with different content (MD5), the load stops: the source must send a new file name.
2. Snowflake's own COPY load history: even if the log row is missing, COPY will not load
   the same staged file twice.
"""

from __future__ import annotations

import hashlib
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Feed:
    name: str
    pattern: re.Pattern[str]
    stage_dir: str
    table: str
    copy_sql: str


MEMBER_PROFILE = Feed(
    name="MEMBER_PROFILE",
    pattern=re.compile(r"^MEMBER_PROFILE_(\d{8})_\d{8}\.txt$"),
    stage_dir="member_profile",
    table="BRONZE.MEMBER_PROFILE_RAW",
    copy_sql="""
COPY INTO BRONZE.MEMBER_PROFILE_RAW (
    RECORD_TYPE, MEMBER_NAME, MEMBER_ID, ENROLLMENT_DATE, LAST_FLIGHT_DATE, TIER_CODE,
    AGENT_NAME, STATE, COUNTRY, DOB, IS_ACTIVE,
    SOURCE_FILE, SOURCE_FILE_ROW_NO, BATCH_DATE, LOAD_ID)
FROM (
    SELECT $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12,
           %(source_file)s, METADATA$FILE_ROW_NUMBER, %(batch_date)s::DATE, %(load_id)s
    FROM @BRONZE.LANDING_STG/member_profile/)
FILES = (%(staged_file)s)
FILE_FORMAT = (FORMAT_NAME = 'BRONZE.FF_MEMBER_PIPE')
ON_ERROR = 'CONTINUE'
""",
)

REDEMPTIONS = Feed(
    name="REDEMPTIONS",
    pattern=re.compile(r"^REDEMPTIONS_(\d{8})\.json$"),
    stage_dir="redemptions",
    table="BRONZE.REDEMPTION_RAW",
    copy_sql="""
COPY INTO BRONZE.REDEMPTION_RAW (PAYLOAD, SOURCE_FILE, SOURCE_FILE_ROW_NO, BATCH_DATE, LOAD_ID)
FROM (
    SELECT $1, %(source_file)s, METADATA$FILE_ROW_NUMBER, %(batch_date)s::DATE, %(load_id)s
    FROM @BRONZE.LANDING_STG/redemptions/)
FILES = (%(staged_file)s)
FILE_FORMAT = (FORMAT_NAME = 'BRONZE.FF_REDEMPTION_JSON')
ON_ERROR = 'CONTINUE'
""",
)

FEEDS = (MEMBER_PROFILE, REDEMPTIONS)


@dataclass(frozen=True)
class LandingFile:
    path: Path
    feed: Feed
    batch_date: date


def classify(path: Path) -> LandingFile | None:
    """Match a file name to its feed; the batch date comes from the name."""
    for feed in FEEDS:
        match = feed.pattern.match(path.name)
        if match:
            return LandingFile(path, feed, datetime.strptime(match.group(1), "%Y%m%d").date())
    return None


def discover(landing_dir: Path) -> list[LandingFile]:
    """Loadable files in batch-date order (members before redemptions on the same day)."""
    found = [lf for p in landing_dir.iterdir() if p.is_file() and (lf := classify(p))]
    return sorted(found, key=lambda lf: (lf.batch_date, FEEDS.index(lf.feed), lf.path.name))


def md5_of(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def summarise_copy(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Collapse COPY INTO result rows into one log entry.

    COPY returns one row per file, or a single 'Copy executed with 0 files processed.' row
    when the file is already in Snowflake's load history.
    """
    per_file = [r for r in results if "rows_loaded" in r]
    if not per_file:
        return {"status": "SKIPPED_BY_COPY", "rows_parsed": 0, "rows_loaded": 0,
                "errors_seen": 0, "first_error": None}  # fmt: skip
    errors = sum(r["errors_seen"] or 0 for r in per_file)
    return {
        "status": "LOADED_WITH_ERRORS" if errors else "LOADED",
        "rows_parsed": sum(r["rows_parsed"] or 0 for r in per_file),
        "rows_loaded": sum(r["rows_loaded"] or 0 for r in per_file),
        "errors_seen": errors,
        "first_error": next((r["first_error"] for r in per_file if r.get("first_error")), None),
    }


def already_loaded(cur: Any) -> dict[str, str]:
    """File name -> MD5 for every file successfully loaded before."""
    cur.execute(
        "SELECT FILE_NAME, FILE_MD5 FROM META.FILE_LOAD_LOG "
        "WHERE STATUS IN ('LOADED', 'LOADED_WITH_ERRORS')"
    )
    return dict(cur.fetchall())


def load_file(cur: Any, lf: LandingFile, loaded: dict[str, str]) -> dict[str, Any] | None:
    """Stage and COPY one file. Returns the log entry, or None if it was skipped."""
    name = lf.path.name
    checksum = md5_of(lf.path)
    if name in loaded:
        if loaded[name] != checksum:
            raise RuntimeError(f"{name} was already loaded with different content")
        log.info("skip %s: already loaded", name)
        return None

    cur.execute(
        f"PUT 'file://{lf.path.resolve().as_posix()}' @BRONZE.LANDING_STG/{lf.feed.stage_dir}/ "
        "AUTO_COMPRESS = TRUE OVERWRITE = FALSE"
    )
    load_id = str(uuid.uuid4())
    cur.execute(
        lf.feed.copy_sql,
        {
            "source_file": name,
            "batch_date": lf.batch_date.isoformat(),
            "load_id": load_id,
            "staged_file": f"{name}.gz",
        },
    )
    columns = [c[0].lower() for c in cur.description]
    entry = summarise_copy([dict(zip(columns, row, strict=True)) for row in cur.fetchall()])
    entry.update(load_id=load_id, feed=lf.feed.name, file_name=name, file_md5=checksum,
                 batch_date=lf.batch_date.isoformat())  # fmt: skip
    cur.execute(
        "INSERT INTO META.FILE_LOAD_LOG (LOAD_ID, FEED, FILE_NAME, FILE_MD5, BATCH_DATE, "
        "ROWS_PARSED, ROWS_LOADED, ERRORS_SEEN, FIRST_ERROR, STATUS) VALUES "
        "(%(load_id)s, %(feed)s, %(file_name)s, %(file_md5)s, %(batch_date)s, "
        "%(rows_parsed)s, %(rows_loaded)s, %(errors_seen)s, %(first_error)s, %(status)s)",
        entry,
    )
    log.info("%s %s: %d rows loaded, %d errors", entry["status"], name,
             entry["rows_loaded"], entry["errors_seen"])  # fmt: skip
    return entry


def load_landing(cur: Any, landing_dir: Path) -> list[dict[str, Any]]:
    loaded = already_loaded(cur)
    entries = []
    for lf in discover(landing_dir):
        entry = load_file(cur, lf, loaded)
        if entry is not None:
            entries.append(entry)
    return entries


def expected_rows(path: Path) -> int:
    """Rows a file should produce in Bronze: every non-empty line (member header included)."""
    with path.open(encoding="utf-8") as fh:
        return sum(1 for line in fh if line.strip())


def reconcile(cur: Any, landing_dir: Path) -> list[tuple[str, int, int]]:
    """(file, lines in file, rows in Bronze) for every landing file."""
    counts: dict[str, int] = {}
    for feed in FEEDS:
        cur.execute(f"SELECT SOURCE_FILE, COUNT(*) FROM {feed.table} GROUP BY SOURCE_FILE")
        counts.update(dict(cur.fetchall()))
    return [(lf.path.name, expected_rows(lf.path), counts.get(lf.path.name, 0))
            for lf in discover(landing_dir)]  # fmt: skip
