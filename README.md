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
                                                      │
Gold:  MEMBER_STG (every batch) ─► DIM_MEMBER (SCD2)  ▼
       MEMBER_CURRENT + REDEMPTION_TXN ─► MEMBER_360 (one row per member)
```

Design decisions and their alternatives: [docs/architecture.md](docs/architecture.md).

## Deliverables map

| # | Brief asks for | Where |
|---|---|---|
| 1 | DDL: raw, staging, country tables | raw: [V003](sql/ddl/V003__bronze_tables.sql); staging: [V004](sql/ddl/V004__silver_member_tables.sql); country: [V005](sql/ddl/V005__silver_member_current_and_country_tables.sql) |
| 2 | Staging + Age + Stale_Member | `SILVER.MEMBER_STG` via [member_validate.sql](sql/transform/silver/member_validate.sql) |
| 3 | Country split, latest record wins | [member_current_merge.sql](sql/transform/silver/member_current_merge.sql) + [country_table_sync.sql](sql/transform/silver/country_table_sync.sql) |
| 4 | Flatten JSON + join design | [redemption_validate.sql](sql/transform/silver/redemption_validate.sql) → `SILVER.REDEMPTION_TXN`; join: see below |
| 5 | Validations | members: rules in [member_validate.sql](sql/transform/silver/member_validate.sql), rejects in `SILVER.MEMBER_REJECT`; redemptions: [redemption_validate.sql](sql/transform/silver/redemption_validate.sql), rejects in `SILVER.REDEMPTION_REJECT` |

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

### Redemptions (Silver)

`LATERAL FLATTEN(..., OUTER => TRUE)` turns each JSON line into one row per transaction
(documents with an empty `redemptions` array are kept as one row so they can be logged).

| Outcome | Rule |
|---|---|
| Reject | missing txn_id / member_id / partner; status not COMPLETED/PENDING/CANCELLED; miles not a whole number or <= 0; invalid or future txn date; txn_id already accepted (first wins, in this batch or an earlier one); document with no transactions (`EMPTY_REDEMPTIONS`) |
| Keep + flag | status needed trimming/upper-casing; miles sent as a JSON string; invalid feed date |
| Keep + `ORPHAN_MEMBER` | member_id not in `MEMBER_CURRENT` yet. Re-checked every batch; resolved when the member arrives (`ORPHAN_RESOLVED_BATCH`). See `V_REDEMPTION_ORPHAN`. |

### Joining redemptions to members

```sql
SELECT r.TXN_ID, r.TXN_DATE, r.PARTNER, r.MILES_REDEEMED, r.STATUS,
       m.MEMBER_NAME, m.COUNTRY_ISO, m.TIER_CODE, m.STALE_MEMBER
FROM SILVER.REDEMPTION_TXN r
LEFT JOIN SILVER.MEMBER_CURRENT m ON m.MEMBER_ID = r.MEMBER_ID;
```

- Join on `MEMBER_ID`, the global business key, to **`MEMBER_CURRENT`**, not the country tables:
  it already carries the country, so there is no need to UNION five tables.
- `LEFT JOIN` keeps orphan redemptions (member not arrived yet) visible instead of dropping them.
- This gives the member's *current* country and tier. "Which country was the member in when
  they redeemed?" needs the Gold SCD2 `DIM_MEMBER`, joined on
  `TXN_DATE BETWEEN VALID_FROM AND VALID_TO`.
- At scale, cluster `REDEMPTION_TXN` on `TXN_DATE` (queries filter by date) and let Snowflake
  hash-join on `MEMBER_ID`.

## Gold

```powershell
python -m skypoints.gold                      # DIM_MEMBER + MEMBER_360, as of the latest batch
```

Both tables are rebuilt from Silver in one transaction (`INSERT OVERWRITE`), so re-running
gives the same rows.

**`GOLD.DIM_MEMBER`**: SCD Type 2 member history. A new version opens when name, enrollment,
tier, agent, state, country (ISO) or active flag changes, including a change back. Flights and
AU/AUS aliases do not open versions. Version 1 is valid from `1900-01-01`, later versions
from the batch that delivered them, until the day before the next one (`9999-12-31` while current).

```sql
-- Which country was the member in when they redeemed?
SELECT r.TXN_ID, r.TXN_DATE, d.COUNTRY_ISO AS COUNTRY_AT_REDEMPTION, d.TIER_CODE
FROM SILVER.REDEMPTION_TXN r
JOIN GOLD.DIM_MEMBER d
  ON d.MEMBER_ID = r.MEMBER_ID AND r.TXN_DATE BETWEEN d.VALID_FROM AND d.VALID_TO;
```

**`GOLD.MEMBER_360`**: one row per current member: profile, `AGE`, `STALE_MEMBER`, miles by
status, average miles, last redemption, favourite partner (most redemptions, then most miles,
then name), and:

| Column | Rule |
|---|---|
| `LIFECYCLE_STATUS` | `NEVER_FLOWN`; `ACTIVE` flew within 30 days; `AT_RISK` 31–90; `DORMANT` over 90 |
| `DORMANT_REDEEMER` | stale, but redeemed in the last 30 days: still engaged, worth a campaign |

Cancelled redemptions count in `TXN_COUNT` only. Orphan redemptions are left out until their
member arrives; completed miles reconcile with Silver (tested).

## Tests

```powershell
pytest -q                 # unit tests, no Snowflake needed
pytest -m integration     # Snowflake: rule edge cases in throwaway schemas + checks on generated data
```

Integration tests run the real SQL over hand-made rows in a throwaway schema (dropped
afterwards), and check the generated data against the manifest, its answer key.
