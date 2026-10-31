-- Member history as SCD Type 2: one row per version of a member.
-- Rebuilt from SILVER.MEMBER_STG, which keeps every valid record of every batch.

CREATE TABLE IF NOT EXISTS {{ database }}.GOLD.DIM_MEMBER (
    MEMBER_SK               VARCHAR(32)   NOT NULL COMMENT 'Surrogate key: MD5 of MEMBER_ID and VERSION_BATCH_DATE, stable across rebuilds',
    MEMBER_ID               VARCHAR(18)   NOT NULL COMMENT 'Business key',
    VERSION_NO              NUMBER(6,0)   NOT NULL COMMENT '1 = first version seen',
    MEMBER_NAME             VARCHAR(255)  NOT NULL,
    ENROLLMENT_DATE         DATE          NOT NULL,
    TIER_CODE               VARCHAR(5),
    AGENT_NAME              VARCHAR(255),
    STATE                   VARCHAR(5),
    COUNTRY_ISO             CHAR(2)       COMMENT 'NULL = country code not in COUNTRY_MAP',
    DOB                     DATE,
    IS_ACTIVE               BOOLEAN,
    ATTRIBUTE_HASH          VARCHAR(64)   NOT NULL COMMENT 'SHA2 of the tracked columns above; a change opens a new version',
    VERSION_BATCH_DATE      DATE          NOT NULL COMMENT 'Batch that delivered this version',
    VALID_FROM              DATE          NOT NULL COMMENT 'Version 1 starts 1900-01-01: nothing earlier is known',
    VALID_TO                DATE          NOT NULL COMMENT 'Day before the next version; 9999-12-31 while current',
    IS_CURRENT              BOOLEAN       NOT NULL,
    SOURCE_FILE             VARCHAR       NOT NULL,
    SOURCE_FILE_ROW_NO      NUMBER(18,0)  NOT NULL,
    BUILT_AT                TIMESTAMP_LTZ NOT NULL DEFAULT CURRENT_TIMESTAMP(),
    CONSTRAINT PK_DIM_MEMBER PRIMARY KEY (MEMBER_SK)
)
COMMENT = 'Member history (SCD Type 2). Join facts on MEMBER_ID and date BETWEEN VALID_FROM AND VALID_TO';
