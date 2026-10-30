-- Step 1: upsert one batch of MEMBER_STG into MEMBER_CURRENT. Latest record wins.
-- Runs inside the batch transaction (see members_current.py).
-- A member whose row was rejected this batch is not in MEMBER_STG, so their previous
-- valid record stays. An unknown country still wins and routes them to MEMBER_UNMAPPED.

MERGE INTO {{ silver }}.MEMBER_CURRENT t
USING (
    SELECT s.*, COALESCE(m.TARGET_TABLE, 'MEMBER_UNMAPPED') AS TARGET_TABLE
    FROM {{ silver }}.MEMBER_STG s
    LEFT JOIN (SELECT DISTINCT COUNTRY_ISO, TARGET_TABLE FROM {{ silver }}.COUNTRY_MAP) m
        ON m.COUNTRY_ISO = s.COUNTRY_ISO
    WHERE s.BATCH_DATE = '{{ batch_date }}'::DATE
) s
ON t.MEMBER_ID = s.MEMBER_ID
-- Never let a replayed older batch overwrite a newer record; skip rows that did not change.
WHEN MATCHED AND s.BATCH_DATE >= t.LAST_BATCH_DATE AND s.RECORD_HASH <> t.RECORD_HASH THEN UPDATE SET
    PREVIOUS_COUNTRY_ISO = IFF(EQUAL_NULL(t.COUNTRY_ISO, s.COUNTRY_ISO), t.PREVIOUS_COUNTRY_ISO, t.COUNTRY_ISO),
    COUNTRY_CHANGED_DATE = IFF(EQUAL_NULL(t.COUNTRY_ISO, s.COUNTRY_ISO), t.COUNTRY_CHANGED_DATE, s.BATCH_DATE),
    MEMBER_NAME = s.MEMBER_NAME,
    ENROLLMENT_DATE = s.ENROLLMENT_DATE,
    LAST_FLIGHT_DATE = s.LAST_FLIGHT_DATE,
    TIER_CODE = s.TIER_CODE,
    AGENT_NAME = s.AGENT_NAME,
    STATE = s.STATE,
    COUNTRY_RAW = s.COUNTRY_RAW,
    COUNTRY_ISO = s.COUNTRY_ISO,
    TARGET_TABLE = s.TARGET_TABLE,
    DOB = s.DOB,
    IS_ACTIVE = s.IS_ACTIVE,
    AGE = s.AGE,
    STALE_MEMBER = s.STALE_MEMBER,
    NEVER_FLOWN = s.NEVER_FLOWN,
    DQ_FLAGS = s.DQ_FLAGS,
    RECORD_HASH = s.RECORD_HASH,
    LAST_BATCH_DATE = s.BATCH_DATE,
    ROW_UPDATED_BATCH = s.BATCH_DATE,
    SOURCE_FILE = s.SOURCE_FILE,
    SOURCE_FILE_ROW_NO = s.SOURCE_FILE_ROW_NO,
    UPDATED_AT = CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN INSERT (
    MEMBER_ID, MEMBER_NAME, ENROLLMENT_DATE, LAST_FLIGHT_DATE, TIER_CODE, AGENT_NAME, STATE,
    COUNTRY_RAW, COUNTRY_ISO, TARGET_TABLE, DOB, IS_ACTIVE, AGE, STALE_MEMBER, NEVER_FLOWN,
    DQ_FLAGS, RECORD_HASH, FIRST_BATCH_DATE, LAST_BATCH_DATE, ROW_UPDATED_BATCH, SOURCE_FILE,
    SOURCE_FILE_ROW_NO)
VALUES (
    s.MEMBER_ID, s.MEMBER_NAME, s.ENROLLMENT_DATE, s.LAST_FLIGHT_DATE, s.TIER_CODE, s.AGENT_NAME,
    s.STATE, s.COUNTRY_RAW, s.COUNTRY_ISO, s.TARGET_TABLE, s.DOB, s.IS_ACTIVE, s.AGE,
    s.STALE_MEMBER, s.NEVER_FLOWN, s.DQ_FLAGS, s.RECORD_HASH, s.BATCH_DATE, s.BATCH_DATE,
    s.BATCH_DATE, s.SOURCE_FILE, s.SOURCE_FILE_ROW_NO);

-- Step 2: refresh time-dependent columns for members NOT in this batch.
-- Only rows whose AGE or STALE_MEMBER actually changes are written (birthdays and members
-- crossing the stale threshold), so the daily write volume stays small at any table size.
-- Skipped when replaying a batch older than the newest one already applied.
UPDATE {{ silver }}.MEMBER_CURRENT t
SET AGE = r.AGE,
    STALE_MEMBER = r.STALE_MEMBER,
    ROW_UPDATED_BATCH = '{{ batch_date }}'::DATE,
    UPDATED_AT = CURRENT_TIMESTAMP()
FROM (
    SELECT
        MEMBER_ID,
        {{ database }}.SILVER.AGE_IN_YEARS(DOB, '{{ batch_date }}'::DATE) AS AGE,
        {{ database }}.SILVER.IS_STALE(LAST_FLIGHT_DATE, '{{ batch_date }}'::DATE, {{ stale_days }}) AS STALE_MEMBER
    FROM {{ silver }}.MEMBER_CURRENT
    WHERE '{{ batch_date }}'::DATE >= (SELECT MAX(LAST_BATCH_DATE) FROM {{ silver }}.MEMBER_CURRENT)
) r
WHERE t.MEMBER_ID = r.MEMBER_ID
  AND (NOT EQUAL_NULL(t.AGE, r.AGE) OR t.STALE_MEMBER <> r.STALE_MEMBER);
