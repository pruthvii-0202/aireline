-- One business-facing row per current member: profile plus redemption metrics.

CREATE TABLE IF NOT EXISTS {{ database }}.GOLD.MEMBER_360 (
    MEMBER_ID                   VARCHAR(18)   NOT NULL,
    MEMBER_NAME                 VARCHAR(255)  NOT NULL,
    COUNTRY_ISO                 CHAR(2)       COMMENT 'NULL = country code not in COUNTRY_MAP',
    TIER_CODE                   VARCHAR(5),
    IS_ACTIVE                   BOOLEAN,
    AGE                         NUMBER(3,0)   COMMENT 'Whole years at AS_OF_DATE',
    STALE_MEMBER                BOOLEAN       NOT NULL COMMENT 'No flight in more than 90 days, or never flown',
    NEVER_FLOWN                 BOOLEAN       NOT NULL,
    LAST_FLIGHT_DATE            DATE,
    DAYS_SINCE_LAST_FLIGHT      NUMBER(6,0),
    LIFECYCLE_STATUS            VARCHAR(12)   NOT NULL COMMENT 'NEVER_FLOWN, ACTIVE (<= 30 days), AT_RISK (31-90), DORMANT (> 90)',
    TXN_COUNT                   NUMBER(12,0)  NOT NULL COMMENT 'Accepted redemptions, any status',
    COMPLETED_TXN_COUNT         NUMBER(12,0)  NOT NULL,
    COMPLETED_MILES             NUMBER(18,0)  NOT NULL,
    PENDING_MILES               NUMBER(18,0)  NOT NULL,
    AVG_MILES_PER_COMPLETED_TXN NUMBER(12,2)  COMMENT 'NULL when there is no completed redemption',
    LAST_REDEMPTION_DATE        DATE          COMMENT 'Latest completed or pending redemption',
    DAYS_SINCE_LAST_REDEMPTION  NUMBER(6,0),
    FAVOURITE_PARTNER           VARCHAR(100)  COMMENT 'Most completed or pending redemptions; ties: more miles, then name',
    DORMANT_REDEEMER            BOOLEAN       NOT NULL COMMENT 'Stale but redeemed in the last 30 days: still engaged',
    AS_OF_DATE                  DATE          NOT NULL COMMENT 'Latest batch date; every day count is measured to it',
    BUILT_AT                    TIMESTAMP_LTZ NOT NULL DEFAULT CURRENT_TIMESTAMP(),
    CONSTRAINT PK_MEMBER_360 PRIMARY KEY (MEMBER_ID)
)
COMMENT = 'One row per current member with profile, lifecycle and redemption metrics';
