-- Flatten, validate and derive one batch of redemption documents.
-- Returns one row per transaction (plus one row per document with no transactions),
-- with REJECT_REASONS (empty array = goes to REDEMPTION_TXN).
--
-- Placeholders: source (Bronze-shaped table), silver (schema holding MEMBER_CURRENT and
--               REDEMPTION_TXN), batch_date (YYYY-MM-DD).

WITH docs AS (
    SELECT r.*, '{{ batch_date }}'::DATE AS as_of
    FROM {{ source }} r
    WHERE BATCH_DATE = '{{ batch_date }}'::DATE
),

-- 1. Flatten: one row per element of redemptions[]. OUTER keeps documents with an empty or
--    missing array (they become one row with TXN_INDEX NULL). A non-array value is treated
--    as empty rather than flattening an object's keys.
flat AS (
    SELECT
        d.SOURCE_FILE, d.SOURCE_FILE_ROW_NO, d.LOAD_ID, d.LOAD_TS, d.as_of, d.PAYLOAD,
        COALESCE(TRIM(d.PAYLOAD:member_id::STRING), '') AS member_id,
        COALESCE(TRIM(d.PAYLOAD:feed_date::STRING), '') AS feed_date_raw,
        f.INDEX AS txn_index,
        f.VALUE AS txn
    FROM docs d,
         LATERAL FLATTEN(
             INPUT => IFF(IS_ARRAY(d.PAYLOAD:redemptions), d.PAYLOAD:redemptions, ARRAY_CONSTRUCT()),
             OUTER => TRUE) f
),

-- 2. Type and normalise. Miles may arrive as a JSON string ("12000"): cast and flag it.
typed AS (
    SELECT
        f.*,
        COALESCE(TRIM(txn:txn_id::STRING), '')          AS txn_id,
        COALESCE(TRIM(txn:partner::STRING), '')         AS partner,
        COALESCE(txn:status::STRING, '')                AS status_raw,
        UPPER(TRIM(status_raw))                         AS status,
        TYPEOF(txn:miles_redeemed)                      AS miles_type,
        TRY_TO_NUMBER(txn:miles_redeemed::STRING, 38, 2) AS miles,
        COALESCE(TRIM(txn:txn_date::STRING), '')        AS txn_date_raw,
        IFF(REGEXP_LIKE(txn_date_raw, '[0-9]{8}'), TRY_TO_DATE(txn_date_raw, 'YYYYMMDD'), NULL) AS txn_dt,
        IFF(REGEXP_LIKE(feed_date_raw, '[0-9]{8}'), TRY_TO_DATE(feed_date_raw, 'YYYYMMDD'), NULL) AS feed_dt
    FROM flat f
),

-- 3. Rules.
checked AS (
    SELECT
        t.*,
        IFF(txn_index IS NULL,
            ARRAY_CONSTRUCT_COMPACT(
                IFF(member_id = '', 'MISSING_MEMBER_ID', NULL),
                'EMPTY_REDEMPTIONS'),
            ARRAY_CONSTRUCT_COMPACT(
                IFF(member_id = '',                                   'MISSING_MEMBER_ID', NULL),
                IFF(LENGTH(member_id) > 18,                           'MEMBER_ID_TOO_LONG', NULL),
                IFF(txn_id = '',                                      'MISSING_TXN_ID', NULL),
                IFF(partner = '',                                     'MISSING_PARTNER', NULL),
                IFF(status NOT IN ('COMPLETED', 'PENDING', 'CANCELLED'), 'INVALID_STATUS', NULL),
                IFF(miles IS NULL OR miles <> FLOOR(miles),           'INVALID_MILES', NULL),
                IFF(miles <= 0,                                       'NEGATIVE_OR_ZERO_MILES', NULL),
                IFF(txn_dt IS NULL,                                   'INVALID_TXN_DATE', NULL),
                IFF(txn_dt > as_of,                                   'FUTURE_TXN_DATE', NULL))
        ) AS rule_rejects,
        ARRAY_CONSTRUCT_COMPACT(
            IFF(status_raw <> status AND status IN ('COMPLETED', 'PENDING', 'CANCELLED'),
                'STATUS_NORMALISED', NULL),
            IFF(miles_type = 'VARCHAR' AND miles > 0 AND miles = FLOOR(miles),
                'MILES_CAST_FROM_STRING', NULL),
            IFF(feed_dt IS NULL, 'INVALID_FEED_DATE', NULL)
        ) AS dq_flags
    FROM typed t
),

gated AS (
    SELECT c.*, ARRAY_SIZE(rule_rejects) = 0 AS passed_rules
    FROM checked c
),

-- 4. txn_id uniqueness: the first valid occurrence wins, within this batch (file order) and
--    against transactions already accepted from earlier batches.
ranked AS (
    SELECT
        g.*,
        ROW_NUMBER() OVER (
            PARTITION BY txn_id, passed_rules
            ORDER BY SOURCE_FILE, SOURCE_FILE_ROW_NO, txn_index) AS key_rank,
        e.earlier_txn_id IS NOT NULL AS seen_in_earlier_batch,
        m.known_member_id IS NULL AS orphan
    FROM gated g
    -- Columns renamed: Snowflake names are case-insensitive, so TXN_ID would clash with txn_id.
    LEFT JOIN (
        SELECT TXN_ID AS earlier_txn_id FROM {{ silver }}.REDEMPTION_TXN
        WHERE BATCH_DATE < '{{ batch_date }}'::DATE
    ) e ON e.earlier_txn_id = g.txn_id
    LEFT JOIN (
        SELECT MEMBER_ID AS known_member_id FROM {{ silver }}.MEMBER_CURRENT
    ) m ON m.known_member_id = g.member_id
)

SELECT
    txn_id                                      AS TXN_ID,
    member_id                                   AS MEMBER_ID,
    feed_dt                                     AS FEED_DATE,
    txn_dt                                      AS TXN_DATE,
    partner                                     AS PARTNER,
    UPPER(partner) = 'SKYPOINTS'                AS IS_INTERNAL_PARTNER,
    miles::NUMBER(12,0)                         AS MILES_REDEEMED,
    status                                      AS STATUS,
    status = 'COMPLETED'                        AS IS_COMPLETED,
    DATEDIFF('day', txn_dt, feed_dt)            AS FEED_LAG_DAYS,
    orphan                                      AS ORPHAN_MEMBER,
    dq_flags                                    AS DQ_FLAGS,
    as_of                                       AS BATCH_DATE,
    CASE
        WHEN NOT passed_rules THEN rule_rejects
        WHEN key_rank > 1 OR seen_in_earlier_batch THEN ARRAY_CONSTRUCT('DUPLICATE_TXN_ID')
        ELSE ARRAY_CONSTRUCT()
    END                                         AS REJECT_REASONS,
    IFF(txn_index IS NULL, PAYLOAD, txn)        AS RAW_VALUE,
    NULLIF(member_id, '')                       AS MEMBER_ID_RAW,
    NULLIF(txn_id, '')                          AS TXN_ID_RAW,
    SOURCE_FILE,
    SOURCE_FILE_ROW_NO,
    txn_index                                   AS TXN_INDEX,
    LOAD_ID
FROM ranked
