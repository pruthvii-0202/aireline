-- Flattened redemption transactions (brief deliverables 4 and 5).

CREATE TABLE IF NOT EXISTS {{ database }}.SILVER.REDEMPTION_TXN (
    TXN_ID                  VARCHAR       NOT NULL COMMENT 'Business key; first occurrence wins',
    MEMBER_ID               VARCHAR(18)   NOT NULL COMMENT 'Joins to MEMBER_CURRENT.MEMBER_ID',
    FEED_DATE               DATE          COMMENT 'feed_date of the JSON document',
    TXN_DATE                DATE          NOT NULL,
    PARTNER                 VARCHAR(100)  NOT NULL,
    IS_INTERNAL_PARTNER     BOOLEAN       NOT NULL COMMENT 'Partner is SkyPoints itself',
    MILES_REDEEMED          NUMBER(12,0)  NOT NULL,
    STATUS                  VARCHAR(10)   NOT NULL COMMENT 'COMPLETED, PENDING or CANCELLED',
    IS_COMPLETED            BOOLEAN       NOT NULL,
    FEED_LAG_DAYS           NUMBER(6,0)   COMMENT 'Days between the transaction and the feed that sent it',
    ORPHAN_MEMBER           BOOLEAN       NOT NULL COMMENT 'Member not (yet) in MEMBER_CURRENT; re-checked every batch',
    ORPHAN_RESOLVED_BATCH   DATE          COMMENT 'Batch in which a late-arriving member resolved the orphan',
    DQ_FLAGS                ARRAY         COMMENT 'Repaired values; row is kept',
    BATCH_DATE              DATE          NOT NULL,
    SOURCE_FILE             VARCHAR       NOT NULL,
    SOURCE_FILE_ROW_NO      NUMBER(18,0)  NOT NULL COMMENT 'JSON line in the file',
    TXN_INDEX               NUMBER(6,0)   NOT NULL COMMENT 'Position in the redemptions array',
    LOAD_ID                 VARCHAR       NOT NULL,
    PROCESSED_AT            TIMESTAMP_LTZ NOT NULL DEFAULT CURRENT_TIMESTAMP(),
    CONSTRAINT PK_REDEMPTION_TXN PRIMARY KEY (TXN_ID)
)
COMMENT = 'One row per valid redemption transaction, flattened from the partner JSON feed';

CREATE TABLE IF NOT EXISTS {{ database }}.SILVER.REDEMPTION_REJECT (
    BATCH_DATE          DATE          NOT NULL,
    MEMBER_ID_RAW       VARCHAR,
    TXN_ID_RAW          VARCHAR,
    REJECT_REASONS      ARRAY         NOT NULL,
    RAW_VALUE           VARIANT       NOT NULL COMMENT 'The transaction object, or the whole document for document-level issues',
    SOURCE_FILE         VARCHAR       NOT NULL,
    SOURCE_FILE_ROW_NO  NUMBER(18,0)  NOT NULL,
    TXN_INDEX           NUMBER(6,0)   COMMENT 'NULL for document-level issues such as EMPTY_REDEMPTIONS',
    LOAD_ID             VARCHAR       NOT NULL,
    REJECTED_AT         TIMESTAMP_LTZ NOT NULL DEFAULT CURRENT_TIMESTAMP()
)
COMMENT = 'Redemptions that failed validation, duplicated an earlier txn_id, or documents with no transactions';

CREATE OR REPLACE VIEW {{ database }}.SILVER.V_REDEMPTION_ORPHAN
COMMENT = 'Redemptions whose member has not arrived yet (late-arriving members are re-checked every batch)'
AS
SELECT * FROM {{ database }}.SILVER.REDEMPTION_TXN WHERE ORPHAN_MEMBER;
