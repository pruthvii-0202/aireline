-- Validate, normalise and derive one batch of member rows.
-- Returns every detail row with REJECT_REASONS (empty array = goes to MEMBER_STG).
--
-- Placeholders: source (Bronze-shaped table), batch_date (YYYY-MM-DD), database,
--               stale_days (90), min_id_length (6).
-- Note: REGEXP_LIKE is implicitly anchored in Snowflake (whole value must match).

WITH src AS (
    SELECT *
    FROM {{ source }}
    WHERE BATCH_DATE = '{{ batch_date }}'::DATE
      AND COALESCE(RECORD_TYPE, '') <> 'H'
),

-- 1. Normalise: trim everything, upper-case codes, NULL -> '' so rules stay simple.
--    DOB with 7 digits lost its leading zero (03051985 -> 3051985); put it back.
norm AS (
    SELECT
        s.*,
        '{{ batch_date }}'::DATE                AS as_of,
        COALESCE(TRIM(MEMBER_NAME), '')         AS n_name,
        COALESCE(TRIM(MEMBER_ID), '')           AS n_id,
        COALESCE(TRIM(ENROLLMENT_DATE), '')     AS n_enroll,
        COALESCE(TRIM(LAST_FLIGHT_DATE), '')    AS n_flight,
        COALESCE(UPPER(TRIM(TIER_CODE)), '')    AS n_tier,
        COALESCE(TRIM(AGENT_NAME), '')          AS n_agent,
        COALESCE(UPPER(TRIM(STATE)), '')        AS n_state,
        COALESCE(UPPER(TRIM(COUNTRY)), '')      AS n_country,
        COALESCE(TRIM(DOB), '')                 AS dob_as_sent,
        IFF(REGEXP_LIKE(dob_as_sent, '[0-9]{7}'), '0' || dob_as_sent, dob_as_sent) AS n_dob,
        COALESCE(UPPER(TRIM(IS_ACTIVE)), '')    AS n_active
    FROM src s
),

-- 2. Type: dates must be exactly 8 digits AND a real calendar date (no month 13, no 30 Feb).
typed AS (
    SELECT
        n.*,
        IFF(REGEXP_LIKE(n_enroll, '[0-9]{8}'), TRY_TO_DATE(n_enroll, 'YYYYMMDD'), NULL) AS enroll_dt,
        IFF(REGEXP_LIKE(n_flight, '[0-9]{8}'), TRY_TO_DATE(n_flight, 'YYYYMMDD'), NULL) AS flight_dt,
        IFF(REGEXP_LIKE(n_dob,    '[0-9]{8}'), TRY_TO_DATE(n_dob,    'DDMMYYYY'), NULL) AS dob_dt,
        m.COUNTRY_ISO AS country_iso
    FROM norm n
    LEFT JOIN {{ database }}.SILVER.COUNTRY_MAP m
        ON m.COUNTRY_CODE_RAW = n.n_country
),

-- 3. Rules. Reject = the row cannot be trusted. Flag = keep the row, note the issue.
checked AS (
    SELECT
        t.*,
        ARRAY_CONSTRUCT_COMPACT(
            IFF(COALESCE(RECORD_TYPE, '') <> 'D',            'INVALID_RECORD_TYPE', NULL),
            IFF(n_name = '',                                  'MISSING_MEMBER_NAME', NULL),
            IFF(LENGTH(n_name) > 255,                         'MEMBER_NAME_TOO_LONG', NULL),
            IFF(n_id = '',                                    'MISSING_MEMBER_ID', NULL),
            IFF(LENGTH(n_id) > 18,                            'ID_TOO_LONG', NULL),
            IFF(n_enroll = '',                                'MISSING_ENROLLMENT_DATE', NULL),
            IFF(n_enroll <> '' AND enroll_dt IS NULL,         'INVALID_ENROLLMENT_DATE', NULL),
            IFF(enroll_dt > as_of,                            'FUTURE_ENROLLMENT_DATE', NULL),
            IFF(n_flight <> '' AND flight_dt IS NULL,         'INVALID_LAST_FLIGHT_DATE', NULL),
            IFF(n_dob <> '' AND dob_dt IS NULL,               'INVALID_DOB', NULL),
            IFF(dob_dt > as_of,                               'FUTURE_DOB', NULL),
            IFF(LENGTH(n_tier) > 5,                           'TIER_CODE_TOO_LONG', NULL),
            IFF(LENGTH(n_agent) > 255,                        'AGENT_NAME_TOO_LONG', NULL),
            IFF(LENGTH(n_state) > 5,                          'STATE_TOO_LONG', NULL),
            IFF(LENGTH(n_country) > 5,                        'COUNTRY_TOO_LONG', NULL)
        ) AS rule_rejects,
        ARRAY_CONSTRUCT_COMPACT(
            IFF(n_id <> '' AND LENGTH(n_id) < {{ min_id_length }}, 'ID_LENGTH_SUSPECT', NULL),
            IFF(n_dob <> dob_as_sent,                         'DOB_REPAIRED', NULL),
            IFF(n_tier <> '' AND n_tier NOT IN ('SLV', 'GLD', 'PLT'), 'UNKNOWN_TIER', NULL),
            IFF(n_active <> '' AND n_active NOT IN ('A', 'I'), 'INVALID_ACTIVE_FLAG', NULL),
            IFF(flight_dt < enroll_dt,                        'FLIGHT_BEFORE_ENROLLMENT', NULL),
            IFF(flight_dt > as_of,                            'FUTURE_LAST_FLIGHT_DATE', NULL),
            IFF(country_iso IS NULL,                          'UNKNOWN_COUNTRY', NULL),
            IFF(COALESCE(MEMBER_NAME, '') <> n_name OR COALESCE(MEMBER_ID, '') <> n_id
                OR COALESCE(TIER_CODE, '') <> n_tier OR COALESCE(STATE, '') <> n_state
                OR COALESCE(COUNTRY, '') <> n_country OR COALESCE(IS_ACTIVE, '') <> n_active,
                                                              'VALUES_NORMALISED', NULL)
        ) AS dq_flags,
        SHA2(CONCAT_WS('|', n_id, n_name, n_enroll, n_flight, n_tier, n_agent,
                       n_state, n_country, n_dob, n_active), 256) AS record_hash
    FROM typed t
),

-- 4. Key uniqueness within the batch: among valid rows, the latest one per member wins
--    (load time, then file, then line number). Losers are rejected with a reason.
gated AS (
    SELECT c.*, ARRAY_SIZE(rule_rejects) = 0 AS passed_rules
    FROM checked c
),

ranked AS (
    SELECT
        g.*,
        ROW_NUMBER() OVER (
            PARTITION BY n_id, passed_rules
            ORDER BY LOAD_TS DESC, SOURCE_FILE DESC, SOURCE_FILE_ROW_NO DESC) AS key_rank,
        FIRST_VALUE(record_hash) OVER (
            PARTITION BY n_id, passed_rules
            ORDER BY LOAD_TS DESC, SOURCE_FILE DESC, SOURCE_FILE_ROW_NO DESC) AS winner_hash
    FROM gated g
)

SELECT
    as_of                                               AS BATCH_DATE,
    n_id                                                AS MEMBER_ID,
    n_name                                              AS MEMBER_NAME,
    enroll_dt                                           AS ENROLLMENT_DATE,
    flight_dt                                           AS LAST_FLIGHT_DATE,
    NULLIF(n_tier, '')                                  AS TIER_CODE,
    NULLIF(n_agent, '')                                 AS AGENT_NAME,
    NULLIF(n_state, '')                                 AS STATE,
    NULLIF(n_country, '')                               AS COUNTRY_RAW,
    country_iso                                         AS COUNTRY_ISO,
    dob_dt                                              AS DOB,
    CASE n_active WHEN 'A' THEN TRUE WHEN 'I' THEN FALSE END AS IS_ACTIVE,
    -- Whole years: subtract one if this year's birthday is still ahead of as_of.
    DATEDIFF('year', dob_dt, as_of)
        - IFF(DATEADD('year', DATEDIFF('year', dob_dt, as_of), dob_dt) > as_of, 1, 0) AS AGE,
    DATEDIFF('day', flight_dt, as_of)                   AS DAYS_SINCE_LAST_FLIGHT,
    COALESCE(DATEDIFF('day', flight_dt, as_of) > {{ stale_days }}, TRUE) AS STALE_MEMBER,
    flight_dt IS NULL                                   AS NEVER_FLOWN,
    dq_flags                                            AS DQ_FLAGS,
    record_hash                                         AS RECORD_HASH,
    CASE
        WHEN NOT passed_rules THEN rule_rejects
        WHEN key_rank > 1 AND record_hash = winner_hash THEN ARRAY_CONSTRUCT('EXACT_DUPLICATE')
        WHEN key_rank > 1 THEN ARRAY_CONSTRUCT('DUPLICATE_KEY_SUPERSEDED')
        ELSE ARRAY_CONSTRUCT()
    END                                                 AS REJECT_REASONS,
    OBJECT_CONSTRUCT_KEEP_NULL(
        'RECORD_TYPE', RECORD_TYPE, 'MEMBER_NAME', MEMBER_NAME, 'MEMBER_ID', MEMBER_ID,
        'ENROLLMENT_DATE', ENROLLMENT_DATE, 'LAST_FLIGHT_DATE', LAST_FLIGHT_DATE,
        'TIER_CODE', TIER_CODE, 'AGENT_NAME', AGENT_NAME, 'STATE', STATE,
        'COUNTRY', COUNTRY, 'DOB', DOB, 'IS_ACTIVE', IS_ACTIVE) AS RAW_RECORD,
    MEMBER_ID                                           AS MEMBER_ID_RAW,
    SOURCE_FILE,
    SOURCE_FILE_ROW_NO,
    LOAD_ID,
    LOAD_TS
FROM ranked
