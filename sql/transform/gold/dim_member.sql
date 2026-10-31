-- Rebuild DIM_MEMBER (SCD Type 2) from every batch in MEMBER_STG.
-- INSERT OVERWRITE replaces the table in one atomic statement, so a reader never sees it
-- half built, and a rebuild from the same Silver data always gives the same rows.
--
-- Tracked columns open a new version when they change. LAST_FLIGHT_DATE is left out (it
-- changes with every flight; MEMBER_360 carries it) and so is COUNTRY_RAW (AU and AUS are
-- the same country). AGE and STALE_MEMBER change daily without the member changing.

INSERT OVERWRITE INTO {{ gold }}.DIM_MEMBER (
    MEMBER_SK, MEMBER_ID, VERSION_NO, MEMBER_NAME, ENROLLMENT_DATE, TIER_CODE, AGENT_NAME,
    STATE, COUNTRY_ISO, DOB, IS_ACTIVE, ATTRIBUTE_HASH, VERSION_BATCH_DATE, VALID_FROM,
    VALID_TO, IS_CURRENT, SOURCE_FILE, SOURCE_FILE_ROW_NO)
WITH tracked AS (
    SELECT
        s.*,
        SHA2(CONCAT_WS('|', MEMBER_NAME, TO_VARCHAR(ENROLLMENT_DATE), COALESCE(TIER_CODE, ''),
                       COALESCE(AGENT_NAME, ''), COALESCE(STATE, ''), COALESCE(COUNTRY_ISO, ''),
                       COALESCE(TO_VARCHAR(DOB), ''), COALESCE(TO_VARCHAR(IS_ACTIVE), '')),
             256) AS attribute_hash
    FROM {{ silver }}.MEMBER_STG s
),

-- 1. A version starts at a member's first batch and whenever the tracked columns differ
--    from the previous batch the member appeared in. A change back (SLV -> GLD -> SLV)
--    is a new version, not a return to the old one.
changes AS (
    SELECT *
    FROM tracked
    QUALIFY NOT EQUAL_NULL(
        LAG(attribute_hash) OVER (PARTITION BY MEMBER_ID ORDER BY BATCH_DATE), attribute_hash)
),

-- 2. Each version lasts until the day before the next one starts.
versions AS (
    SELECT
        c.*,
        ROW_NUMBER() OVER (PARTITION BY MEMBER_ID ORDER BY BATCH_DATE) AS version_no,
        LEAD(BATCH_DATE) OVER (PARTITION BY MEMBER_ID ORDER BY BATCH_DATE) AS next_version_date
    FROM changes c
)

SELECT
    MD5(MEMBER_ID || '|' || TO_VARCHAR(BATCH_DATE))                AS MEMBER_SK,
    MEMBER_ID,
    version_no                                                    AS VERSION_NO,
    MEMBER_NAME,
    ENROLLMENT_DATE,
    TIER_CODE,
    AGENT_NAME,
    STATE,
    COUNTRY_ISO,
    DOB,
    IS_ACTIVE,
    attribute_hash                                                AS ATTRIBUTE_HASH,
    BATCH_DATE                                                    AS VERSION_BATCH_DATE,
    -- Nothing before the first record is known, so version 1 covers all earlier dates and a
    -- redemption dated before the member's first feed still finds a version.
    IFF(version_no = 1, '1900-01-01'::DATE, BATCH_DATE)          AS VALID_FROM,
    COALESCE(DATEADD('day', -1, next_version_date), '9999-12-31'::DATE) AS VALID_TO,
    next_version_date IS NULL                                     AS IS_CURRENT,
    SOURCE_FILE,
    SOURCE_FILE_ROW_NO
FROM versions;
