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
| 1 | DDL: raw, staging, country tables | raw: [V003](sql/ddl/V003__bronze_tables.sql); staging: [V004](sql/ddl/V004__silver_member_tables.sql); country: [V005](sql/ddl/V005__silver_member_current_and_country_tables.sql) |
| 2 | Staging + Age + Stale_Member | `SILVER.MEMBER_STG` via [member_validate.sql](sql/transform/silver/member_validate.sql) |
| 3 | Country split, latest record wins | [member_current_merge.sql](sql/transform/silver/member_current_merge.sql) + [country_table_sync.sql](sql/transform/silver/country_table_sync.sql) |
| 4 | Flatten JSON + join design | _todo_ |
| 5 | Validations | members: rules in [member_validate.sql](sql/transform/silver/member_validate.sql), rejects in `SILVER.MEMBER_REJECT`; redemptions: _todo_ |

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

```powershell
python -m skypoints.silver                    # MEMBER_STG/REJECT, MEMBER_CURRENT, country tables
pytest -m integration                         # Snowflake tests (edge cases + manifest coverage)
```

### Member validation rules (Silver)

| Outcome | Rule |
|---|---|
| Reject | missing name / id / enrollment date; invalid date (must be 8 digits and a real date); DOB or enrollment in the future; id > 18 chars; field longer than the layout allows; earlier row for the same member in the batch (`EXACT_DUPLICATE` / `DUPLICATE_KEY_SUPERSEDED`) |
| Keep + flag | id shorter than 6 (`ID_LENGTH_SUSPECT`); 7-digit DOB repaired (`DOB_REPAIRED`); unknown tier; active flag not A/I; flight before enrollment; flight in the future; country not in `COUNTRY_MAP`; values trimmed or upper-cased |

`AGE` is whole years at the batch date. `STALE_MEMBER` is TRUE when the last flight is more than
90 days before the batch date, or the member has never flown (`NEVER_FLOWN`).

### Latest record wins + country split (Silver)

Per batch, in one transaction:
1. `MERGE` the batch's staged rows into `MEMBER_CURRENT` (one row per member). An older batch
   replayed later can never overwrite a newer record; unchanged rows are not rewritten.
   A country change records `PREVIOUS_COUNTRY_ISO` and `COUNTRY_CHANGED_DATE`.
2. Refresh `AGE` / `STALE_MEMBER` for members not in the batch, writing only rows that change.
3. For each country table (`MEMBER_US/IN/PH/CA/AU`, `MEMBER_UNMAPPED`): delete members who now
   belong elsewhere, then merge the members that belong here. Each member is in exactly one table.
