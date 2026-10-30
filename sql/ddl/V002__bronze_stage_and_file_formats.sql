-- Landing stage and file formats for the two source feeds.
-- File formats hold no data, so CREATE OR REPLACE keeps them in sync with this file.
-- The stage holds uploaded files, so it is only created if missing.

CREATE STAGE IF NOT EXISTS {{ database }}.BRONZE.LANDING_STG
    COMMENT = 'Internal stage for daily source files: member_profile/ and redemptions/';

-- Lines look like |H|...| or |D|...|: the leading pipe makes field 1 empty and field 2 the
-- record type. Header lines are loaded too (RECORD_TYPE = H) so Silver can check the layout.
-- Values are kept exactly as sent: no trimming, empty strings stay empty strings.
CREATE OR REPLACE FILE FORMAT {{ database }}.BRONZE.FF_MEMBER_PIPE
    TYPE = CSV
    FIELD_DELIMITER = '|'
    SKIP_HEADER = 0
    FIELD_OPTIONALLY_ENCLOSED_BY = NONE
    TRIM_SPACE = FALSE
    EMPTY_FIELD_AS_NULL = FALSE
    NULL_IF = ()
    ERROR_ON_COLUMN_COUNT_MISMATCH = FALSE
    ENCODING = 'UTF8'
    COMMENT = 'Pipe-delimited member profile file with |H| header and |D| detail lines';

-- Newline-delimited JSON: one member document per line.
CREATE OR REPLACE FILE FORMAT {{ database }}.BRONZE.FF_REDEMPTION_JSON
    TYPE = JSON
    STRIP_OUTER_ARRAY = FALSE
    COMMENT = 'Partner redemption feed, one JSON document per line';
