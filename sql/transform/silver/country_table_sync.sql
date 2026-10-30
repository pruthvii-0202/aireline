-- Step 3 (run once per country table): apply this batch's MEMBER_CURRENT changes.
-- A member who moved is deleted from every table except their new one, so each member
-- is in exactly one country table. Runs inside the batch transaction.

DELETE FROM {{ silver }}.{{ table }}
WHERE MEMBER_ID IN (
    SELECT MEMBER_ID FROM {{ silver }}.MEMBER_CURRENT
    WHERE ROW_UPDATED_BATCH = '{{ batch_date }}'::DATE
      AND TARGET_TABLE <> '{{ table }}');

MERGE INTO {{ silver }}.{{ table }} t
USING (
    SELECT * FROM {{ silver }}.MEMBER_CURRENT
    WHERE ROW_UPDATED_BATCH = '{{ batch_date }}'::DATE
      AND TARGET_TABLE = '{{ table }}'
) s
ON t.MEMBER_ID = s.MEMBER_ID
WHEN MATCHED THEN UPDATE SET {{ update_set }}
WHEN NOT MATCHED THEN INSERT ({{ columns }}) VALUES ({{ source_columns }});
