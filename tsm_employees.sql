-- ============================================================
-- TSM SCORECARD V2 - Ownership-Period Metrics
--
-- One row per TSM x Company OWNERSHIP PERIOD. A TSM who lost an account and
-- later regained it gets two rows; IS_CURRENT_CS marks the live one, and at
-- most one row per company can be TRUE.
--
-- Scope: owners with a TSM / Technical Success Manager / Solution Architect
-- title who currently own at least one active customer (so TSMs owning nothing
-- today are excluded, along with their history). Companies: Customer / Churn.
--
-- ASSIGNED_DATE is the latest of three floors; ASSIGNED_DATE_SOURCE says which
-- applied. Only 'crm_event' dates exist in HubSpot's CS Owner history - the
-- other two are derived corrections, so searching HubSpot for them finds
-- nothing. A company's first SCD record is its HubSpot creation timestamp, and
-- an owner set at creation is never logged as a "change".
--   crm_event           - the CRM run start
--   hire_date           - CRM claims ownership before the owner was hired
--   customer_conversion - CRM claims CS ownership before the company was a
--                         customer (that owner ran the sales cycle)
--
-- Metric shapes:
--   *_AT_ASSIGNMENT / *_AT_LEFT are all-time cumulative totals as of each date,
--   NOT period totals. AI_EVENTS and SELF_SERVICE_RUNS are additive, so period
--   activity = (_AT_LEFT - _AT_ASSIGNMENT). UNIQUE_LOGINS is COUNT(DISTINCT),
--   so its difference is net user growth and does not subtract cleanly.
--   GONG_CALLS is the exception: calls made DURING the period.
--   INTEGRATION_TYPES_AT_* is point-in-time, so it can legitimately DECREASE
--   when integrations are deleted.
--
-- Dates use elapsed days / 30.44, not DATEDIFF('month'/'quarter'), which counts
-- calendar-boundary crossings: a 33-day period inside one month returns 0.
--
-- Final filters: historical periods must exceed 14 days; current periods are
-- exempt. No licence requirement, so companies with no licence record still
-- appear. TSMs with no qualifying periods appear with NULL company rows.
-- ============================================================

WITH params AS (
    -- Snapshot date. Replace with a literal to pin a point in time.
    SELECT DATEADD('second', -1, DATE_TRUNC('month', CURRENT_DATE()))::TIMESTAMP AS relevant_date
),
cs_owner_pool AS (
    -- Owners currently holding at least one active customer. Gates the roster.
    SELECT DISTINCT SK_CSM_OWNER
    FROM PORT_ANALYTICS_PROD.DWH.DIM_COMPANY
    WHERE LIFECYCLE_STAGE = 'Customer'
      AND SK_CSM_OWNER IS NOT NULL
),
customer_pool AS (
    SELECT
        SK_COMPANY,
        COMPANY_CRM_ID,
        COMPANY_NAME,
        LIFECYCLE_STAGE,
        CUSTOMER_INTERNAL_TIER,
        SK_CSM_OWNER AS CURRENT_OWNER
    FROM PORT_ANALYTICS_PROD.DWH.DIM_COMPANY
    WHERE LIFECYCLE_STAGE IN ('Customer', 'Churn')
),
company_contract_dates AS (
    -- Contract facts per company, shared by the conversion floor and
    -- CUSTOMER_AGE_MONTHS so the underlying tables are scanned once.
    SELECT
        c.SK_COMPANY,
        w.first_won,
        l.first_lic
    FROM (SELECT SK_COMPANY FROM PORT_ANALYTICS_PROD.DWH.DIM_COMPANY
          WHERE LIFECYCLE_STAGE IN ('Customer', 'Churn')) c
    LEFT JOIN (
        SELECT SK_COMPANY, MIN(DEAL_CLOSED_DATE) AS first_won
        FROM PORT_ANALYTICS_PROD.DWH.FACT_DEALS
        WHERE IS_WON = TRUE AND DEAL_CLOSED_DATE IS NOT NULL
        GROUP BY SK_COMPANY
    ) w ON w.SK_COMPANY = c.SK_COMPANY
    LEFT JOIN (
        SELECT SK_COMPANY, MIN(START_DATE) AS first_lic
        FROM PORT_ANALYTICS_PROD.DWH.FACT_PURCHASED_SEATS
        WHERE TOTAL_LICENSED_USERS > 0
          AND DATEDIFF(day, START_DATE, END_DATE) > 1
        GROUP BY SK_COMPANY
    ) l ON l.SK_COMPANY = c.SK_COMPANY
),
company_became_customer AS (
    -- Transactional conversion date, used to floor ASSIGNED_DATE. Deliberately
    -- NOT from LIFECYCLE_STAGE, which is manually maintained and unreliable both
    -- ways: a rep can assign a CS owner days before flipping the stage, and the
    -- pre-2024 SCD carries junk stage history (oligosecurity.io reads 'Customer'
    -- from 2022-12-07 against a first won deal of 2025-09-29).
    -- Falls back to first licence start, which trails the won deal by ~13 days.
    -- One owned company has neither and so gets no floor.
    SELECT
        SK_COMPANY,
        COALESCE(first_won, first_lic)::TIMESTAMP AS BECAME_CUSTOMER_AT
    FROM company_contract_dates
),
tsm_employees AS (
    SELECT
        e.SK_EMPLOYEE,
        e.EMPLOYEE_ID,
        e.EMAIL,
        e.DISPLAY_NAME,
        e.TITLE,
        e.ORIGINAL_START_DATE AS HIRE_DATE
    FROM PORT_ANALYTICS_PROD.DWH.DIM_EMPLOYEE e
    JOIN cs_owner_pool cs ON cs.SK_CSM_OWNER = e.SK_EMPLOYEE
    WHERE (e.TITLE ILIKE '%TSM%'
       OR e.TITLE ILIKE '%Technical Success Manager%'
       OR e.TITLE ILIKE '%Solution Architect%')
      AND e.ORIGINAL_START_DATE <= (SELECT relevant_date FROM params)
),
company_org_map AS (
    -- Shared company -> account -> org mapping. Grain is one row per
    -- (SK_COMPANY, SK_ACCOUNT, SK_ORG), which the metric SUMs depend on.
    -- IS_ACTIVE_LIFECYCLE is a flag, not a filter: the login/self-service/AI
    -- CTEs require it, integrations do not.
    -- Prefers commercial accounts, but falls back to ALL accounts for companies
    -- that have none flagged commercial. 34 customers (16 of them owned) are in
    -- that state despite having real activity - Wisconsin and Banner Health
    -- carry thousands of logins - and filtering on the flag alone dropped them
    -- from every org-based metric.
    SELECT
        da.SK_COMPANY,
        da.SK_ACCOUNT,
        do.SK_ORG,
        (dc_lc.LIFECYCLE_STAGE IN ('Customer', 'Churn')) AS IS_ACTIVE_LIFECYCLE
    FROM PORT_ANALYTICS_PROD.DWH.DIM_ACCOUNT da
    INNER JOIN PORT_ANALYTICS_PROD.DWH.DIM_ORG do
        ON do.SK_ACCOUNT = da.SK_ACCOUNT
    LEFT JOIN PORT_ANALYTICS_PROD.DWH.DIM_COMPANY dc_lc
        ON dc_lc.SK_COMPANY = da.SK_COMPANY
    WHERE da.IS_COMMERCIAL_ACCOUNT = TRUE
       OR NOT EXISTS (SELECT 1 FROM PORT_ANALYTICS_PROD.DWH.DIM_ACCOUNT da2
                      WHERE da2.SK_COMPANY = da.SK_COMPANY
                        AND da2.IS_COMMERCIAL_ACCOUNT = TRUE)
),
-- ---------- ownership periods (gaps-and-islands over the SCD) ----------
-- The SCD is heavily fragmented (one company can carry hundreds of versions),
-- so a version is NOT an assignment. Collapse consecutive same-owner versions
-- into runs, drop sub-24h runs as pipeline noise, then re-collapse so runs
-- separated only by a suppressed blip merge back together.
scd_owners AS (
    SELECT
        scd.SK_COMPANY,
        scd.SK_CSM_OWNER,
        scd.EFFECTIVE_START_DATE,
        COALESCE(scd.EFFECTIVE_END_DATE, '9999-12-31'::TIMESTAMP) AS EFFECTIVE_END_DATE
    FROM PORT_ANALYTICS_PROD.DWH.DIM_COMPANY_SCD scd
    INNER JOIN customer_pool cp
        ON cp.SK_COMPANY = scd.SK_COMPANY
    WHERE scd.SK_CSM_OWNER IS NOT NULL
      AND scd.EFFECTIVE_START_DATE >= '2024-01-01'  -- Pre-2024 history is unreliable
),
run_pass1_flag AS (
    SELECT s.*,
        CASE WHEN s.SK_CSM_OWNER = LAG(s.SK_CSM_OWNER) OVER (
                 PARTITION BY s.SK_COMPANY ORDER BY s.EFFECTIVE_START_DATE)
             THEN 0 ELSE 1 END AS is_new_run
    FROM scd_owners s
),
run_pass1_grp AS (
    SELECT f.*,
        SUM(f.is_new_run) OVER (
            PARTITION BY f.SK_COMPANY ORDER BY f.EFFECTIVE_START_DATE
            ROWS UNBOUNDED PRECEDING) AS run_grp
    FROM run_pass1_flag f
),
runs_pass1 AS (
    SELECT
        SK_COMPANY,
        SK_CSM_OWNER,
        MIN(EFFECTIVE_START_DATE) AS run_start,
        MAX(EFFECTIVE_END_DATE)   AS run_end
    FROM run_pass1_grp
    GROUP BY SK_COMPANY, SK_CSM_OWNER, run_grp
),
runs_kept AS (
    -- Drop blip runs. Hours, not DATEDIFF('day'): a ~12h run crossing midnight
    -- returns day-diff 1 and would survive. Open/current runs always kept.
    SELECT *
    FROM runs_pass1
    WHERE run_end > (SELECT relevant_date FROM params)
       OR DATEDIFF('hour', run_start, run_end) >= 24
),
run_pass2_flag AS (
    SELECT k.*,
        CASE WHEN k.SK_CSM_OWNER = LAG(k.SK_CSM_OWNER) OVER (
                 PARTITION BY k.SK_COMPANY ORDER BY k.run_start)
             THEN 0 ELSE 1 END AS is_new_run2
    FROM runs_kept k
),
run_pass2_grp AS (
    SELECT f.*,
        SUM(f.is_new_run2) OVER (
            PARTITION BY f.SK_COMPANY ORDER BY f.run_start
            ROWS UNBOUNDED PRECEDING) AS run_grp2
    FROM run_pass2_flag f
),
ownership_runs AS (
    SELECT
        SK_COMPANY,
        SK_CSM_OWNER,
        MIN(run_start) AS run_start,
        MAX(run_end)   AS run_end
    FROM run_pass2_grp
    GROUP BY SK_COMPANY, SK_CSM_OWNER, run_grp2
),
ownership_periods AS (
    -- PERIOD_ID is the single join key for every metric CTE, so multiple periods
    -- per TSM x company cannot fan out the metric joins.
    SELECT
        HASH(r.SK_CSM_OWNER, r.SK_COMPANY, r.run_start) AS PERIOD_ID,
        r.SK_CSM_OWNER,
        r.SK_COMPANY,
        cp.COMPANY_CRM_ID,
        cp.COMPANY_NAME,
        cp.LIFECYCLE_STAGE,
        cp.CUSTOMER_INTERNAL_TIER,
        t.HIRE_DATE,
        -- Latest of: CRM run start, hire date, customer conversion. The latter
        -- two correct impossible CRM states.
        GREATEST(r.run_start,
                 t.HIRE_DATE::TIMESTAMP,
                 COALESCE(bc.BECAME_CUSTOMER_AT, r.run_start)) AS ASSIGNED_DATE,
        CASE
            WHEN bc.BECAME_CUSTOMER_AT >= GREATEST(r.run_start, t.HIRE_DATE::TIMESTAMP)
                 AND bc.BECAME_CUSTOMER_AT > r.run_start          THEN 'customer_conversion'
            WHEN t.HIRE_DATE::TIMESTAMP > r.run_start             THEN 'hire_date'
            ELSE 'crm_event'
        END AS ASSIGNED_DATE_SOURCE,
        LEAST(r.run_end, (SELECT relevant_date FROM params)) AS LEFT_DATE,
        -- At most one period per company can be live.
        (r.run_end > (SELECT relevant_date FROM params)
         AND cp.CURRENT_OWNER = r.SK_CSM_OWNER) AS IS_CURRENT_CS
    FROM ownership_runs r
    INNER JOIN tsm_employees t
        ON t.SK_EMPLOYEE = r.SK_CSM_OWNER
    INNER JOIN customer_pool cp
        ON cp.SK_COMPANY = r.SK_COMPANY
    LEFT JOIN company_became_customer bc
        ON bc.SK_COMPANY = r.SK_COMPANY
    -- Period must overlap the window, and extend past both the hire date and
    -- the conversion date. Companies with no conversion date get no such floor.
    WHERE GREATEST(r.run_start, t.HIRE_DATE::TIMESTAMP, COALESCE(bc.BECAME_CUSTOMER_AT, r.run_start)) <= (SELECT relevant_date FROM params)
      AND r.run_end > t.HIRE_DATE::TIMESTAMP
      AND r.run_end > COALESCE(bc.BECAME_CUSTOMER_AT, r.run_start)
),
-- ---------- metrics, all keyed on PERIOD_ID ----------
arr_and_tier_at_dates AS (
    -- ARR at both dates from point-in-time SCD lookups.
    SELECT
        f.PERIOD_ID,
        COALESCE(arr_start.ARR, 0) AS ARR_AT_ASSIGNMENT,
        -- Churned companies report 0 regardless of the SCD value
        CASE
            WHEN f.LIFECYCLE_STAGE = 'Churn' THEN 0
            ELSE COALESCE(arr_end.ARR, 0)
        END AS ARR_AT_END_DATE
    FROM ownership_periods f
    LEFT JOIN PORT_ANALYTICS_PROD.DWH.DIM_COMPANY_SCD arr_start
        ON f.SK_COMPANY = arr_start.SK_COMPANY
        AND DATEADD(day, 1, f.ASSIGNED_DATE::DATE)::TIMESTAMP >= arr_start.EFFECTIVE_START_DATE
        AND DATEADD(day, 1, f.ASSIGNED_DATE::DATE)::TIMESTAMP < COALESCE(arr_start.EFFECTIVE_END_DATE, '9999-12-31')
    LEFT JOIN PORT_ANALYTICS_PROD.DWH.DIM_COMPANY_SCD arr_end
        ON f.SK_COMPANY = arr_end.SK_COMPANY
        AND f.LEFT_DATE >= arr_end.EFFECTIVE_START_DATE
        AND f.LEFT_DATE < COALESCE(arr_end.EFFECTIVE_END_DATE, '9999-12-31')
),
tier_at_assignment AS (
    -- Most recent stable, non-NULL tier at or before the assignment lookup
    -- point. A plain point-in-time read is unsafe: tier churns during pipeline
    -- writes. Grupo Credito S.A. shows Core for hours, flips to Digital for 3
    -- SECONDS, goes NULL for 13 hours, then returns to Core - so a naive read
    -- returns either NULL or the 3-second Digital blip instead of Core.
    -- Versions under 60s are excluded for the same reason blip runs are.
    SELECT
        f.PERIOD_ID,
        s.CUSTOMER_INTERNAL_TIER AS TIER_AT_ASSIGNMENT
    FROM ownership_periods f
    INNER JOIN PORT_ANALYTICS_PROD.DWH.DIM_COMPANY_SCD s
        ON s.SK_COMPANY = f.SK_COMPANY
        AND s.EFFECTIVE_START_DATE <= DATEADD(day, 1, f.ASSIGNED_DATE::DATE)::TIMESTAMP
        AND s.CUSTOMER_INTERNAL_TIER IS NOT NULL
        AND DATEDIFF('second', s.EFFECTIVE_START_DATE,
                     COALESCE(s.EFFECTIVE_END_DATE, (SELECT relevant_date FROM params))) >= 60
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY f.PERIOD_ID ORDER BY s.EFFECTIVE_START_DATE DESC) = 1
),
logins_at_dates AS (
    -- Cumulative, so COUNT(DISTINCT) does not subtract cleanly: the difference
    -- between the two is NET user growth, not new users.
    SELECT
        f.PERIOD_ID,
        COUNT(DISTINCT CASE WHEN ful.LOGIN_DATE <= f.ASSIGNED_DATE::DATE
                            THEN ful.USER_EMAIL_ADDRESS END) AS UNIQUE_LOGINS_AT_ASSIGNMENT,
        COUNT(DISTINCT CASE WHEN ful.LOGIN_DATE <= f.LEFT_DATE::DATE
                            THEN ful.USER_EMAIL_ADDRESS END) AS UNIQUE_LOGINS_AT_LEFT
    FROM ownership_periods f
    INNER JOIN company_org_map com
        ON com.SK_COMPANY = f.SK_COMPANY
        AND com.IS_ACTIVE_LIFECYCLE
    LEFT JOIN PORT_ANALYTICS_PROD.DWH.FACT_USER_LOGIN ful
        ON ful.SK_ORG = com.SK_ORG
    GROUP BY f.PERIOD_ID
),
ai_at_dates AS (
    SELECT
        f.PERIOD_ID,
        SUM(CASE WHEN ai._FACT_DATE <= f.ASSIGNED_DATE
                 THEN ai.NUMBER_OF_EVENTS END) AS AI_EVENTS_AT_ASSIGNMENT,
        SUM(CASE WHEN ai._FACT_DATE <= f.LEFT_DATE
                 THEN ai.NUMBER_OF_EVENTS END) AS AI_EVENTS_AT_LEFT
    FROM ownership_periods f
    INNER JOIN company_org_map com
        ON com.SK_COMPANY = f.SK_COMPANY
        AND com.IS_ACTIVE_LIFECYCLE
    LEFT JOIN PORT_ANALYTICS_PROD.DWH.FACT_AI_USAGE ai
        ON ai.SK_ORG = com.SK_ORG
    GROUP BY f.PERIOD_ID
),
company_first_ai_date AS (
    -- All-time per company, deliberately not period-scoped.
    SELECT
        com.SK_COMPANY,
        MIN(ai._FACT_DATE) AS FIRST_AI_USAGE_DATE
    FROM company_org_map com
    INNER JOIN PORT_ANALYTICS_PROD.DWH.FACT_AI_USAGE ai
        ON ai.SK_ORG = com.SK_ORG
    WHERE ai.NUMBER_OF_EVENTS > 0
    GROUP BY com.SK_COMPANY
),
gong_calls AS (
    -- In-window, not a cumulative pair.
    SELECT
        f.PERIOD_ID,
        COUNT(DISTINCT fc.SK_CONVERSATION) AS GONG_CALLS
    FROM ownership_periods f
    INNER JOIN PORT_ANALYTICS_PROD.DWH.MV_CALL_ASSOCIATED_COMPANY_FLAT caf
        ON caf.ASSOCIATED_SK = f.SK_COMPANY
    INNER JOIN PORT_ANALYTICS_PROD.DWH.FACT_CALL fc
        ON fc.SK_CONVERSATION = caf.SK_CONVERSATION
        AND fc.EFFECTIVE_START_DATETIME >= f.ASSIGNED_DATE
        AND fc.EFFECTIVE_START_DATETIME <= f.LEFT_DATE
        AND ARRAY_CONTAINS(f.SK_CSM_OWNER::VARIANT, fc.ASSOCIATED_OWNER)
        AND fc.DURATION_SECONDS > 600  -- Over 10 minutes
    GROUP BY f.PERIOD_ID
),
self_service_at_dates AS (
    SELECT
        f.PERIOD_ID,
        SUM(CASE WHEN ar._FACT_DATE <= f.ASSIGNED_DATE
                 THEN ar.COUNT_SUCCEEDED + ar.COUNT_FAILED END) AS SELF_SERVICE_RUNS_AT_ASSIGNMENT,
        SUM(CASE WHEN ar._FACT_DATE <= f.LEFT_DATE
                 THEN ar.COUNT_SUCCEEDED + ar.COUNT_FAILED END) AS SELF_SERVICE_RUNS_AT_LEFT
    FROM ownership_periods f
    INNER JOIN company_org_map com
        ON com.SK_COMPANY = f.SK_COMPANY
        AND com.IS_ACTIVE_LIFECYCLE
    LEFT JOIN PORT_ANALYTICS_PROD.DWH.FACT_ACTION_RUNS ar
        ON ar.SK_ORG = com.SK_ORG
        AND ar.SK_ACTION IN (SELECT SK_ACTION FROM PORT_ANALYTICS_PROD.DWH.DIM_ACTION WHERE TRIGGER_TYPE = 'self-service')
    GROUP BY f.PERIOD_ID
),
integration_types_at_dates AS (
    -- Types, not instances: one type can hold many connections, which is one
    -- capability rather than many. Uses _DELETED_TIMESTAMP_UTC for
    -- point-in-time state, not the current _IS_DELETED flag.
    SELECT
        f.PERIOD_ID,
        COUNT(DISTINCT CASE WHEN di.CREATED_AT <= f.ASSIGNED_DATE
                             AND (di._DELETED_TIMESTAMP_UTC IS NULL
                                  OR di._DELETED_TIMESTAMP_UTC > f.ASSIGNED_DATE)
                            THEN di.INTEGRATION_TYPE END) AS INTEGRATION_TYPES_AT_ASSIGNMENT,
        COUNT(DISTINCT CASE WHEN di.CREATED_AT <= f.LEFT_DATE
                             AND (di._DELETED_TIMESTAMP_UTC IS NULL
                                  OR di._DELETED_TIMESTAMP_UTC > f.LEFT_DATE)
                            THEN di.INTEGRATION_TYPE END) AS INTEGRATION_TYPES_AT_LEFT
    FROM ownership_periods f
    INNER JOIN company_org_map com
        ON com.SK_COMPANY = f.SK_COMPANY
    LEFT JOIN PORT_ANALYTICS_PROD.DWH.DIM_INTEGRATION di
        ON di.SK_ORG = com.SK_ORG
    GROUP BY f.PERIOD_ID
),
company_first_license AS (
    -- Used for CUSTOMER_AGE_MONTHS. Falls back to the first won deal when there
    -- is no licence record, so age is still measurable from the contract date.
    SELECT
        SK_COMPANY,
        COALESCE(first_lic, first_won) AS FIRST_LICENSE_DATE
    FROM company_contract_dates
)
SELECT
    t.DISPLAY_NAME,
    t.EMAIL,
    t.TITLE,
    t.HIRE_DATE,
    f.SK_COMPANY,
    f.COMPANY_CRM_ID,
    f.COMPANY_NAME,
    fl.FIRST_LICENSE_DATE,
    -- Negative marks pre-contract ownership: the licence starts after LEFT_DATE.
    ROUND(DATEDIFF('day', fl.FIRST_LICENSE_DATE, f.LEFT_DATE) / 30.44, 1) AS CUSTOMER_AGE_MONTHS,
    f.ASSIGNED_DATE,
    f.ASSIGNED_DATE_SOURCE,
    f.LEFT_DATE,
    ROUND(DATEDIFF('day', f.ASSIGNED_DATE, f.LEFT_DATE) / 30.44, 1) AS MONTHS_OWNED,
    ta.TIER_AT_ASSIGNMENT,
    at.ARR_AT_ASSIGNMENT,
    at.ARR_AT_END_DATE,
    CASE
        WHEN at.ARR_AT_END_DATE = 0 AND at.ARR_AT_ASSIGNMENT > 0 THEN 'churn'
        WHEN at.ARR_AT_ASSIGNMENT > at.ARR_AT_END_DATE            THEN 'downgrade'
        WHEN at.ARR_AT_ASSIGNMENT < at.ARR_AT_END_DATE            THEN 'upgrade'
        ELSE 'no_change'
    END AS ARR_TYPE,
    lod.UNIQUE_LOGINS_AT_ASSIGNMENT,
    lod.UNIQUE_LOGINS_AT_LEFT,
    COALESCE(ai.AI_EVENTS_AT_ASSIGNMENT, 0) AS AI_EVENTS_AT_ASSIGNMENT,
    COALESCE(ai.AI_EVENTS_AT_LEFT, 0)       AS AI_EVENTS_AT_LEFT,
    cfa.FIRST_AI_USAGE_DATE,
    COALESCE(gc.GONG_CALLS, 0) AS GONG_CALLS,
    -- Tier targets per year: Strategic 48, Core+ 36, Core 9, Digital none.
    ROUND(
        DATEDIFF('day', f.ASSIGNED_DATE, f.LEFT_DATE) / 365.0 *
        CASE ta.TIER_AT_ASSIGNMENT
            WHEN 'Strategic' THEN 48
            WHEN 'Core+'     THEN 36
            WHEN 'Core'      THEN 9
            ELSE 0
        END
    ) AS EXPECTED_GONG_CALLS,
    COALESCE(ss.SELF_SERVICE_RUNS_AT_ASSIGNMENT, 0) AS SELF_SERVICE_RUNS_AT_ASSIGNMENT,
    COALESCE(ss.SELF_SERVICE_RUNS_AT_LEFT, 0)       AS SELF_SERVICE_RUNS_AT_LEFT,
    iad.INTEGRATION_TYPES_AT_ASSIGNMENT,
    iad.INTEGRATION_TYPES_AT_LEFT,
    f.IS_CURRENT_CS
FROM tsm_employees t
LEFT JOIN ownership_periods f
    ON t.SK_EMPLOYEE = f.SK_CSM_OWNER
LEFT JOIN arr_and_tier_at_dates at
    ON f.PERIOD_ID = at.PERIOD_ID
LEFT JOIN tier_at_assignment ta
    ON f.PERIOD_ID = ta.PERIOD_ID
LEFT JOIN logins_at_dates lod
    ON f.PERIOD_ID = lod.PERIOD_ID
LEFT JOIN ai_at_dates ai
    ON f.PERIOD_ID = ai.PERIOD_ID
LEFT JOIN gong_calls gc
    ON f.PERIOD_ID = gc.PERIOD_ID
LEFT JOIN self_service_at_dates ss
    ON f.PERIOD_ID = ss.PERIOD_ID
LEFT JOIN integration_types_at_dates iad
    ON f.PERIOD_ID = iad.PERIOD_ID
LEFT JOIN company_first_ai_date cfa
    ON f.SK_COMPANY = cfa.SK_COMPANY
LEFT JOIN company_first_license fl
    ON f.SK_COMPANY = fl.SK_COMPANY
WHERE f.SK_COMPANY IS NULL  -- TSMs with no periods still show
   OR f.IS_CURRENT_CS       -- Live ownership always shows, regardless of tenure
   OR DATEDIFF('day', f.ASSIGNED_DATE, f.LEFT_DATE) > 14  -- Historical: over 14 days only
ORDER BY t.DISPLAY_NAME, f.ASSIGNED_DATE;
