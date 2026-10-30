-- Bronze raw tables (brief deliverable 1: raw/landing DDL).
-- Every business column is VARCHAR so nothing is lost or rejected at load time.
-- Typing and validation happen in Silver.

CREATE TABLE IF NOT EXISTS {{ database }}.BRONZE.MEMBER_PROFILE_RAW (
    RECORD_TYPE         VARCHAR       COMMENT 'H = header line, D = detail line',
    MEMBER_NAME         VARCHAR,
    MEMBER_ID           VARCHAR,
    ENROLLMENT_DATE     VARCHAR       COMMENT 'YYYYMMDD as sent',
    LAST_FLIGHT_DATE    VARCHAR       COMMENT 'YYYYMMDD as sent, may be empty',
    TIER_CODE           VARCHAR,
    AGENT_NAME          VARCHAR,
    STATE               VARCHAR,
    COUNTRY             VARCHAR       COMMENT 'Raw country code, not standardised (USA, AU, AUS, PHIL...)',
    DOB                 VARCHAR       COMMENT 'DDMMYYYY as sent, may have lost its leading zero',
    IS_ACTIVE           VARCHAR,
    SOURCE_FILE         VARCHAR       NOT NULL COMMENT 'Original landing file name',
    SOURCE_FILE_ROW_NO  NUMBER(18,0)  NOT NULL COMMENT 'Line number in the file, header = 1',
    BATCH_DATE          DATE          NOT NULL COMMENT 'Feed date from the file name',
    LOAD_ID             VARCHAR       NOT NULL COMMENT 'Joins to META.FILE_LOAD_LOG',
    LOAD_TS             TIMESTAMP_LTZ NOT NULL DEFAULT CURRENT_TIMESTAMP()
)
COMMENT = 'Member profile flat file, one row per file line, exactly as received';

CREATE TABLE IF NOT EXISTS {{ database }}.BRONZE.REDEMPTION_RAW (
    PAYLOAD             VARIANT       COMMENT 'Whole JSON document: member_id, feed_date, redemptions[]',
    SOURCE_FILE         VARCHAR       NOT NULL,
    SOURCE_FILE_ROW_NO  NUMBER(18,0)  NOT NULL,
    BATCH_DATE          DATE          NOT NULL,
    LOAD_ID             VARCHAR       NOT NULL,
    LOAD_TS             TIMESTAMP_LTZ NOT NULL DEFAULT CURRENT_TIMESTAMP()
)
COMMENT = 'Partner redemption feed, one row per JSON line, exactly as received';

CREATE TABLE IF NOT EXISTS {{ database }}.META.FILE_LOAD_LOG (
    LOAD_ID             VARCHAR       NOT NULL,
    FEED                VARCHAR       NOT NULL COMMENT 'MEMBER_PROFILE or REDEMPTIONS',
    FILE_NAME           VARCHAR       NOT NULL,
    FILE_MD5            VARCHAR       NOT NULL COMMENT 'Detects a re-sent file with changed content',
    BATCH_DATE          DATE          NOT NULL,
    ROWS_PARSED         NUMBER(18,0),
    ROWS_LOADED         NUMBER(18,0),
    ERRORS_SEEN         NUMBER(18,0),
    FIRST_ERROR         VARCHAR,
    STATUS              VARCHAR       NOT NULL COMMENT 'LOADED, LOADED_WITH_ERRORS, SKIPPED_BY_COPY',
    LOADED_AT           TIMESTAMP_LTZ NOT NULL DEFAULT CURRENT_TIMESTAMP()
)
COMMENT = 'One row per landing file load attempt; the loader skips files already LOADED';
