-- Silver member tables (brief deliverables 1, 2 and 5: staging DDL, derived columns, validations).

-- Reference data: every raw country code the source sends, mapped to ISO-2 and its target table.
CREATE TABLE IF NOT EXISTS {{ database }}.SILVER.COUNTRY_MAP (
    COUNTRY_CODE_RAW    VARCHAR(5)    NOT NULL COMMENT 'Code as sent by the source, upper-cased',
    COUNTRY_ISO         CHAR(2)       NOT NULL,
    COUNTRY_NAME        VARCHAR(100)  NOT NULL,
    TARGET_TABLE        VARCHAR(100)  NOT NULL COMMENT 'Per-country member table in SILVER',
    CONSTRAINT PK_COUNTRY_MAP PRIMARY KEY (COUNTRY_CODE_RAW)
)
COMMENT = 'Raw country code -> ISO-2. The source is inconsistent (AU/AUS, PHIL), so aliases map here';

MERGE INTO {{ database }}.SILVER.COUNTRY_MAP t
USING (
    SELECT column1 AS code, column2 AS iso, column3 AS name, column4 AS target
    FROM VALUES
        ('USA',  'US', 'United States', 'MEMBER_US'),
        ('US',   'US', 'United States', 'MEMBER_US'),
        ('IND',  'IN', 'India',         'MEMBER_IN'),
        ('IN',   'IN', 'India',         'MEMBER_IN'),
        ('PHIL', 'PH', 'Philippines',   'MEMBER_PH'),
        ('PHL',  'PH', 'Philippines',   'MEMBER_PH'),
        ('PH',   'PH', 'Philippines',   'MEMBER_PH'),
        ('CAN',  'CA', 'Canada',        'MEMBER_CA'),
        ('CA',   'CA', 'Canada',        'MEMBER_CA'),
        ('AUS',  'AU', 'Australia',     'MEMBER_AU'),
        ('AU',   'AU', 'Australia',     'MEMBER_AU')
) s
ON t.COUNTRY_CODE_RAW = s.code
WHEN MATCHED THEN UPDATE SET COUNTRY_ISO = s.iso, COUNTRY_NAME = s.name, TARGET_TABLE = s.target
WHEN NOT MATCHED THEN INSERT (COUNTRY_CODE_RAW, COUNTRY_ISO, COUNTRY_NAME, TARGET_TABLE)
    VALUES (s.code, s.iso, s.name, s.target);

-- The brief's "staging table": typed, validated, one row per member per batch.
CREATE TABLE IF NOT EXISTS {{ database }}.SILVER.MEMBER_STG (
    BATCH_DATE              DATE          NOT NULL,
    MEMBER_ID               VARCHAR(18)   NOT NULL COMMENT 'Business key (global across countries)',
    MEMBER_NAME             VARCHAR(255)  NOT NULL,
    ENROLLMENT_DATE         DATE          NOT NULL,
    LAST_FLIGHT_DATE        DATE,
    TIER_CODE               VARCHAR(5),
    AGENT_NAME              VARCHAR(255),
    STATE                   VARCHAR(5),
    COUNTRY_RAW             VARCHAR(5)    COMMENT 'Normalised code as sent (USA, AUS, PHIL...)',
    COUNTRY_ISO             CHAR(2)       COMMENT 'NULL when the code is not in COUNTRY_MAP',
    DOB                     DATE,
    IS_ACTIVE               BOOLEAN       COMMENT 'A = TRUE, I = FALSE, anything else NULL',
    AGE                     NUMBER(3,0)   COMMENT 'Whole years at BATCH_DATE',
    DAYS_SINCE_LAST_FLIGHT  NUMBER(6,0)   COMMENT 'Days from LAST_FLIGHT_DATE to BATCH_DATE',
    STALE_MEMBER            BOOLEAN       NOT NULL COMMENT 'No flight in more than 90 days, or never flown',
    NEVER_FLOWN             BOOLEAN       NOT NULL,
    DQ_FLAGS                ARRAY         COMMENT 'Repaired or suspicious values; row is kept',
    RECORD_HASH             VARCHAR(64)   NOT NULL COMMENT 'SHA2 of business columns, for change detection',
    SOURCE_FILE             VARCHAR       NOT NULL,
    SOURCE_FILE_ROW_NO      NUMBER(18,0)  NOT NULL,
    LOAD_ID                 VARCHAR       NOT NULL,
    LOAD_TS                 TIMESTAMP_LTZ NOT NULL COMMENT 'When the row landed in Bronze',
    PROCESSED_AT            TIMESTAMP_LTZ NOT NULL DEFAULT CURRENT_TIMESTAMP()
)
COMMENT = 'Typed and validated member profiles with derived AGE and STALE_MEMBER; latest row per member per batch';

CREATE TABLE IF NOT EXISTS {{ database }}.SILVER.MEMBER_REJECT (
    BATCH_DATE          DATE          NOT NULL,
    MEMBER_ID_RAW       VARCHAR,
    REJECT_REASONS      ARRAY         NOT NULL COMMENT 'Every rule the row failed',
    RAW_RECORD          OBJECT        NOT NULL COMMENT 'The Bronze values, unchanged',
    SOURCE_FILE         VARCHAR       NOT NULL,
    SOURCE_FILE_ROW_NO  NUMBER(18,0)  NOT NULL,
    LOAD_ID             VARCHAR       NOT NULL,
    REJECTED_AT         TIMESTAMP_LTZ NOT NULL DEFAULT CURRENT_TIMESTAMP()
)
COMMENT = 'Member rows that failed validation or lost to a later row for the same member in the batch';
