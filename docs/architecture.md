# Architecture: SkyPoints medallion pipeline

## Flow

```
source system (datagen) ─► landing files ─► Snowflake stage
                                               │ COPY INTO (skip already-loaded files)
                                               ▼
BRONZE   MEMBER_PROFILE_RAW (all VARCHAR)      REDEMPTION_RAW (VARIANT)      META.FILE_LOAD_LOG
                                               │ SQL transforms, run in order by a Python runner
                                               ▼
SILVER   MEMBER_STG ─► MEMBER_REJECT            REDEMPTION_TXN ─► REDEMPTION_REJECT
            │
            ▼ MERGE, latest record wins
         MEMBER_CURRENT ─► MEMBER_US / _IN / _PH / _CA / _AU / MEMBER_UNMAPPED
                                               │
                                               ▼
GOLD     DIM_MEMBER (SCD Type 2)               MEMBER_360 (one row per member)
```

## Layers

| Layer | Purpose | Tables |
|---|---|---|
| BRONZE | Exact copy of what arrived. Never updated or deleted. | `MEMBER_PROFILE_RAW`, `REDEMPTION_RAW` |
| SILVER | Typed, validated, standardised, current. Holds the brief's staging and country tables. | `MEMBER_STG`, `MEMBER_REJECT`, `MEMBER_CURRENT`, `MEMBER_<ISO2>`, `MEMBER_UNMAPPED`, `REDEMPTION_TXN`, `REDEMPTION_REJECT` |
| GOLD | Business-ready, history-aware. | `DIM_MEMBER`, `MEMBER_360` |
| META | Operational logs. | `FILE_LOAD_LOG`, `PIPELINE_RUN_LOG` |

Every table carries audit columns: source file, source row number, batch date, load timestamp.

## Brief deliverables → where they live

| # | Deliverable | Implementation |
|---|---|---|
| 1 | Raw, staging, country DDL | Bronze raw tables, `MEMBER_STG`, `MEMBER_<ISO2>` |
| 2 | Age, Stale_Member | Derived in `MEMBER_STG` from the batch date |
| 3 | Country split, latest wins | `MEMBER_CURRENT` MERGE, then country table sync |
| 4 | Flatten JSON + join | `LATERAL FLATTEN` into `REDEMPTION_TXN`; joined on `member_id` in `MEMBER_360` |
| 5 | Validations | Reject tables with reason codes; DQ flags for repairable issues |

## Decisions

| # | Decision | Why | Alternative considered |
|---|---|---|---|
| D1 | Transforms are plain Snowflake SQL files run in order by a small Python runner | Readable by any reviewer, easy to demo step by step, no extra tooling | Snowpark DataFrames (harder to read for SQL reviewers); dbt (extra tool to set up) |
| D2 | Country tables are real tables in Silver, kept in sync by MERGE; a member who moves is deleted from the old table | The brief asks to *load* members into country tables | Views over `MEMBER_CURRENT` (simpler, but not what the brief asks for) |
| D3 | `DIM_MEMBER` is SCD Type 2 (`valid_from`, `valid_to`, `is_current`) | Silver keeps only the latest record; Gold keeps the history, e.g. which country a member was in when they redeemed | SCD Type 1 (history lost) |
| D4 | Gold output is `MEMBER_360`: one row per member with profile, age, stale flag and redemption metrics | Single business-facing table that shows the member + redemption join working | Full star schema / extra marts: out of scope for now |
| D5 | `Member_Id` is the business key | The layout marks Member Name as the key, but names are not unique; moves between countries are only detectable by id | Member Name (spec as written) |
| D6 | Latest wins ordering: batch date, then load time, then file row number | Deterministic even when the same member appears twice in one file | Load time only (ties within a file) |
| D7 | Derived dates (Age, Stale) use the batch date, not `CURRENT_DATE` | Re-running a past batch gives the same result | `CURRENT_DATE` (results drift on reruns) |
| D8 | Bad rows go to reject tables with a reason code; fixable issues are repaired and flagged | Nothing is silently dropped; data owners can act on rejects | Failing the whole file |
| D9 | A member whose latest row has an unknown country moves to `MEMBER_UNMAPPED` (removed from the old country) | Latest record wins consistently; the unmapped table is the alert for fixing `COUNTRY_MAP` | Keep them in the old country until the code is fixed |
| D10 | A member whose latest row is rejected keeps their previous valid record in `MEMBER_CURRENT` | A bad row should not erase good data; the reject is visible in `MEMBER_REJECT` | Remove the member |
| D11 | AGE and STALE_MEMBER are refreshed every batch, writing only rows whose value changes | Daily files are deltas, so members not in today's file would otherwise keep yesterday's values; writing only changes keeps cost flat at billions of rows | Rewrite every row daily; or compute at query time in a view |
| D12 | Merge, refresh and every country-table sync for a batch run in one transaction | A reader never sees a member in two country tables, or in none, mid-move | Separate statements |
| D13 | Age and staleness rules are SQL UDFs (`AGE_IN_YEARS`, `IS_STALE`) used by staging and the refresh | One definition, so the two can never disagree | Copy the expression in both places |
| D14 | A new country needs only a `COUNTRY_MAP` row; its table is created automatically | Global program: adding a market should not need a code change | One hand-written DDL per country |

## Scale (billions of rows/day)

- Files split to 100–250 MB compressed; `COPY INTO` / Snowpipe loads them in parallel.
- Streams on Bronze tables so Silver processes only new rows; Tasks chain the steps.
- `QUALIFY ROW_NUMBER()` dedupe and `MERGE` instead of full rebuilds.
- Cluster large tables on `MEMBER_ID` (Silver) and date (Gold facts); size the warehouse up only for heavy steps.
