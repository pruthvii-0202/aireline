-- Rebuild MEMBER_360: one row per member in MEMBER_CURRENT with redemption metrics.
-- Every day count is measured to the as-of date (the latest batch), never the wall clock,
-- so rebuilding for the same batch always gives the same answer.
--
-- Driven from MEMBER_CURRENT with a LEFT JOIN: members with no redemptions get zeros,
-- and orphan redemptions (member not arrived yet) are left out until the member arrives.
-- Placeholders: database (holds the SILVER UDFs), silver, gold, as_of, stale_days,
--               active_days, recent_redemption_days.

INSERT OVERWRITE INTO {{ gold }}.MEMBER_360 (
    MEMBER_ID, MEMBER_NAME, COUNTRY_ISO, TIER_CODE, IS_ACTIVE, AGE, STALE_MEMBER, NEVER_FLOWN,
    LAST_FLIGHT_DATE, DAYS_SINCE_LAST_FLIGHT, LIFECYCLE_STATUS, TXN_COUNT, COMPLETED_TXN_COUNT,
    COMPLETED_MILES, PENDING_MILES, AVG_MILES_PER_COMPLETED_TXN, LAST_REDEMPTION_DATE,
    DAYS_SINCE_LAST_REDEMPTION, FAVOURITE_PARTNER, DORMANT_REDEEMER, AS_OF_DATE)
WITH txn AS (
    SELECT *
    FROM {{ silver }}.REDEMPTION_TXN
    WHERE BATCH_DATE <= '{{ as_of }}'::DATE
),

-- 1. Totals per member. Cancelled redemptions count as transactions but not as engagement.
totals AS (
    SELECT
        MEMBER_ID,
        COUNT(*)                                                AS txn_count,
        COUNT_IF(STATUS = 'COMPLETED')                          AS completed_txn_count,
        SUM(IFF(STATUS = 'COMPLETED', MILES_REDEEMED, 0))       AS completed_miles,
        SUM(IFF(STATUS = 'PENDING', MILES_REDEEMED, 0))         AS pending_miles,
        MAX(IFF(STATUS <> 'CANCELLED', TXN_DATE, NULL))         AS last_redemption_date
    FROM txn
    GROUP BY MEMBER_ID
),

-- 2. Favourite partner: most completed or pending redemptions; ties go to more miles,
--    then to the partner name so the result is deterministic.
favourite AS (
    SELECT MEMBER_ID, PARTNER
    FROM txn
    WHERE STATUS <> 'CANCELLED'
    GROUP BY MEMBER_ID, PARTNER
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY MEMBER_ID
        ORDER BY COUNT(*) DESC, SUM(MILES_REDEEMED) DESC, PARTNER) = 1
),

members AS (
    SELECT
        m.*,
        '{{ as_of }}'::DATE                                        AS as_of,
        DATEDIFF('day', m.LAST_FLIGHT_DATE, '{{ as_of }}'::DATE)   AS days_since_flight,
        {{ database }}.SILVER.IS_STALE(m.LAST_FLIGHT_DATE, '{{ as_of }}'::DATE, {{ stale_days }}) AS stale
    FROM {{ silver }}.MEMBER_CURRENT m
)

SELECT
    m.MEMBER_ID,
    m.MEMBER_NAME,
    m.COUNTRY_ISO,
    m.TIER_CODE,
    m.IS_ACTIVE,
    {{ database }}.SILVER.AGE_IN_YEARS(m.DOB, m.as_of)            AS AGE,
    m.stale                                                       AS STALE_MEMBER,
    m.LAST_FLIGHT_DATE IS NULL                                    AS NEVER_FLOWN,
    m.LAST_FLIGHT_DATE,
    m.days_since_flight                                           AS DAYS_SINCE_LAST_FLIGHT,
    CASE
        WHEN m.LAST_FLIGHT_DATE IS NULL                 THEN 'NEVER_FLOWN'
        WHEN m.days_since_flight <= {{ active_days }}   THEN 'ACTIVE'
        WHEN m.days_since_flight <= {{ stale_days }}    THEN 'AT_RISK'
        ELSE 'DORMANT'
    END                                                           AS LIFECYCLE_STATUS,
    COALESCE(t.txn_count, 0)                                      AS TXN_COUNT,
    COALESCE(t.completed_txn_count, 0)                            AS COMPLETED_TXN_COUNT,
    COALESCE(t.completed_miles, 0)                                AS COMPLETED_MILES,
    COALESCE(t.pending_miles, 0)                                  AS PENDING_MILES,
    t.completed_miles / NULLIF(t.completed_txn_count, 0)          AS AVG_MILES_PER_COMPLETED_TXN,
    t.last_redemption_date                                        AS LAST_REDEMPTION_DATE,
    DATEDIFF('day', t.last_redemption_date, m.as_of)              AS DAYS_SINCE_LAST_REDEMPTION,
    f.PARTNER                                                     AS FAVOURITE_PARTNER,
    m.stale AND COALESCE(DATEDIFF('day', t.last_redemption_date, m.as_of)
                         <= {{ recent_redemption_days }}, FALSE)  AS DORMANT_REDEEMER,
    m.as_of                                                       AS AS_OF_DATE
FROM members m
LEFT JOIN totals t    ON t.MEMBER_ID = m.MEMBER_ID
LEFT JOIN favourite f ON f.MEMBER_ID = m.MEMBER_ID;
