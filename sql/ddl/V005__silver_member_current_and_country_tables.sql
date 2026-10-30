-- Latest-wins member table and per-country targets (brief deliverables 1 and 3).

-- Shared business rules, used by staging and by the daily refresh so they can never drift.
CREATE OR REPLACE FUNCTION {{ database }}.SILVER.AGE_IN_YEARS(DOB DATE, AS_OF DATE)
RETURNS NUMBER(3,0)
COMMENT = 'Whole years from DOB to AS_OF; one less if this year''s birthday is still ahead'
AS $$
    DATEDIFF('year', DOB, AS_OF)
        - IFF(DATEADD('year', DATEDIFF('year', DOB, AS_OF), DOB) > AS_OF, 1, 0)
$$;

CREATE OR REPLACE FUNCTION {{ database }}.SILVER.IS_STALE(LAST_FLIGHT DATE, AS_OF DATE, STALE_DAYS NUMBER)
RETURNS BOOLEAN
COMMENT = 'TRUE when the last flight is more than STALE_DAYS before AS_OF, or there is none'
AS $$
    COALESCE(DATEDIFF('day', LAST_FLIGHT, AS_OF) > STALE_DAYS, TRUE)
$$;

-- One row per member: the latest valid record across all batches.
CREATE TABLE IF NOT EXISTS {{ database }}.SILVER.MEMBER_CURRENT (
    MEMBER_ID               VARCHAR(18)   NOT NULL,
    MEMBER_NAME             VARCHAR(255)  NOT NULL,
    ENROLLMENT_DATE         DATE          NOT NULL,
    LAST_FLIGHT_DATE        DATE,
    TIER_CODE               VARCHAR(5),
    AGENT_NAME              VARCHAR(255),
    STATE                   VARCHAR(5),
    COUNTRY_RAW             VARCHAR(5),
    COUNTRY_ISO             CHAR(2)       COMMENT 'NULL = unknown country, member is in MEMBER_UNMAPPED',
    TARGET_TABLE            VARCHAR(100)  NOT NULL COMMENT 'Country table this member belongs to',
    PREVIOUS_COUNTRY_ISO    CHAR(2)       COMMENT 'Country before the most recent move',
    COUNTRY_CHANGED_DATE    DATE          COMMENT 'Batch in which the most recent move arrived',
    DOB                     DATE,
    IS_ACTIVE               BOOLEAN,
    AGE                     NUMBER(3,0)   COMMENT 'Refreshed every batch',
    STALE_MEMBER            BOOLEAN       NOT NULL COMMENT 'Refreshed every batch',
    NEVER_FLOWN             BOOLEAN       NOT NULL,
    DQ_FLAGS                ARRAY,
    RECORD_HASH             VARCHAR(64)   NOT NULL,
    FIRST_BATCH_DATE        DATE          NOT NULL COMMENT 'First batch this member appeared in',
    LAST_BATCH_DATE         DATE          NOT NULL COMMENT 'Batch of the record currently held',
    ROW_UPDATED_BATCH       DATE          NOT NULL COMMENT 'Last batch that changed this row (data or refresh); drives country sync',
    SOURCE_FILE             VARCHAR       NOT NULL,
    SOURCE_FILE_ROW_NO      NUMBER(18,0)  NOT NULL,
    UPDATED_AT              TIMESTAMP_LTZ NOT NULL DEFAULT CURRENT_TIMESTAMP(),
    CONSTRAINT PK_MEMBER_CURRENT PRIMARY KEY (MEMBER_ID)
)
COMMENT = 'Latest valid record per member across all batches (latest record wins)';

-- Per-country targets share MEMBER_CURRENT's columns. A new country only needs a COUNTRY_MAP
-- row: the sync step creates its table the same way if it does not exist yet.
CREATE TABLE IF NOT EXISTS {{ database }}.SILVER.MEMBER_US       LIKE {{ database }}.SILVER.MEMBER_CURRENT;
CREATE TABLE IF NOT EXISTS {{ database }}.SILVER.MEMBER_IN       LIKE {{ database }}.SILVER.MEMBER_CURRENT;
CREATE TABLE IF NOT EXISTS {{ database }}.SILVER.MEMBER_PH       LIKE {{ database }}.SILVER.MEMBER_CURRENT;
CREATE TABLE IF NOT EXISTS {{ database }}.SILVER.MEMBER_CA       LIKE {{ database }}.SILVER.MEMBER_CURRENT;
CREATE TABLE IF NOT EXISTS {{ database }}.SILVER.MEMBER_AU       LIKE {{ database }}.SILVER.MEMBER_CURRENT;
CREATE TABLE IF NOT EXISTS {{ database }}.SILVER.MEMBER_UNMAPPED LIKE {{ database }}.SILVER.MEMBER_CURRENT;

COMMENT ON TABLE {{ database }}.SILVER.MEMBER_US       IS 'Current members in the United States';
COMMENT ON TABLE {{ database }}.SILVER.MEMBER_IN       IS 'Current members in India';
COMMENT ON TABLE {{ database }}.SILVER.MEMBER_PH       IS 'Current members in the Philippines';
COMMENT ON TABLE {{ database }}.SILVER.MEMBER_CA       IS 'Current members in Canada';
COMMENT ON TABLE {{ database }}.SILVER.MEMBER_AU       IS 'Current members in Australia';
COMMENT ON TABLE {{ database }}.SILVER.MEMBER_UNMAPPED IS 'Current members whose country code is not in COUNTRY_MAP';
