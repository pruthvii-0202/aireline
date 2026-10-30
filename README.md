# SkyPoints Loyalty Pipeline

Loads two daily feeds for the SkyPoints airline loyalty program into Snowflake:

1. **Member profile flat file** (pipe-delimited, `|H|` header, `|D|` detail rows)
2. **Redemption JSON feed** (one member object per line, nested `redemptions` array)

Members are validated, de-duplicated (latest record wins) and split into one table per country.
Redemptions are flattened to one row per transaction and joined back to members on `member_id`.

## Architecture

```
member file ─► MEMBER_RAW ─► MEMBER_STG (typed, AGE, STALE_MEMBER) ─► MEMBER_CURRENT ─► TABLE_<COUNTRY>
                                   └─► MEMBER_REJECT (row + reason)
JSON feed   ─► REDEMPTION_RAW (VARIANT) ─► REDEMPTION_TXN ─► join on member_id
```

## Deliverables map

| # | Brief asks for | Where |
|---|---|---|
| 1 | DDL: raw, staging, country tables | raw: [sql/ddl/V003__bronze_tables.sql](sql/ddl/V003__bronze_tables.sql); staging/country: _todo_ |
| 2 | Staging + Age + Stale_Member | _todo_ |
| 3 | Country split, latest record wins | _todo_ |
| 4 | Flatten JSON + join design | _todo_ |
| 5 | Validations | _todo_ |

## Setup

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
ruff check . ; pytest -q
```

## Sample data (simulated source system)

```powershell
python -m skypoints.datagen --out data/landing --days 3 --members 1000 --seed 42
```

Per day it writes `MEMBER_PROFILE_YYYYMMDD_06000000.txt`, `REDEMPTIONS_YYYYMMDD.json` and
`MANIFEST_YYYYMMDD.json`. Day 1 is a full extract; later days are deltas (~10% changed members
including country moves, ~2% new). About 5% of rows carry injected defects (missing fields,
invalid/future dates, short or too-long ids, unknown tier/country, dropped DOB leading zero,
duplicates, orphan and duplicate redemptions). The manifest lists every defect by line number:
it is the ground truth the pipeline's validations are tested against. Same seed, same files.

## Snowflake

Copy `.env.example` to `.env` and fill it in (never committed). Then:

```powershell
python -m skypoints.snowflake_conn            # read-only connectivity check
python -m skypoints.sql_runner                # apply sql/ddl/V*.sql in order (idempotent)
python -m skypoints.bronze --landing data/landing
```

The Bronze loader uploads each file to `BRONZE.LANDING_STG`, runs `COPY INTO`, records the
load in `META.FILE_LOAD_LOG`, and finally reconciles row counts per file against the local
files. Re-running loads nothing new: files already logged are skipped (a changed file with
the same name is refused), and Snowflake's COPY load history is a second safety net.
