-- ============================================================
-- TSM SCORECARD V2 - Ownership-Period Metrics
-- ============================================================
--
-- PURPOSE:
--   One row per TSM x Company OWNERSHIP PERIOD, showing success metrics for
--   exactly the span the TSM held that company. A TSM who lost an account and
--   later regained it gets TWO rows, one per period; IS_CURRENT_CS marks the
--   live one. At most one row per company can be IS_CURRENT_CS.
--
-- PIPELINE (in order):
--   1.  params                     - snapshot date
--   2.  cs_owner_pool              - every CS owner in DIM_COMPANY
--   3.  customer_pool              - Customer/Churn companies + tier + owner
--   4.  tsm_employees              - the owner roster (hire dates)
--   5.  scd_owners -> ownership_periods
--                                  - SCD collapsed into ownership periods
--   6.  arr_and_tier_at_dates      - TIER_AT_ASSIGNMENT + ARR at both dates
--   7.  logins_at_dates            - cumulative unique logins at both dates
--   8.  ai_at_dates                - cumulative AI events at both dates
--   9.  company_first_ai_date      - all-time FIRST_AI_USAGE_DATE
--   10. gong_calls                 - calls made DURING the period
--   11. self_service_at_dates      - cumulative self-service runs at both dates
--   12. integration_types_at_dates - live integration types at both dates
--   13. final SELECT               - derived columns + 14-day filter
--
-- OWNERSHIP PERIOD DETECTION (gaps-and-islands over DIM_COMPANY_SCD):
--   The SCD is heavily fragmented - one company can carry hundreds of versions
--   (cyberark alone has ~293 since Aug 2025), so an SCD version is NOT an
--   assignment. Versions are collapsed into contiguous same-owner runs:
--     Pass 1  : collapse consecutive same-owner versions into runs.
--     Suppress: drop runs under 24h of ELAPSED time - a different owner
--               appearing briefly is pipeline noise, not a handoff. Hours, not
--               DATEDIFF('day'): a ~12h run crossing midnight returns day-diff
--               of 1 and would survive (this is how honeybook slipped through).
--     Pass 2  : re-collapse, so two runs of the same owner separated only by a
--               suppressed blip MERGE into one period. This handles
--               cyberark/honeybook without special-casing, while genuine
--               multi-day handoffs still split the timeline.
--   Pre-2024 SCD records are excluded (unreliable historical data - the SCD
--   reaches back to 2022-05-08, ~35k rows, predating the company).
--   ASSIGNED_DATE is floored at the owner's hire date: a CS owner cannot own a
--   customer before being hired, but the CRM asserts pre-hire ownership on a
--   meaningful number of rows. ASSIGNED_DATE_FLOORED_AT_HIRE flags those, since
--   their ASSIGNED_DATE is the hire date and will NOT appear in HubSpot's change
--   history (HubSpot logs changes, and "was already the owner" is not a change).
--
-- DATE ARITHMETIC:
--   MONTHS_OWNED and CUSTOMER_AGE_MONTHS use elapsed days / 30.44, NOT
--   DATEDIFF('month'). DATEDIFF counts calendar-boundary crossings, not elapsed
--   time: a 33-day period inside one month returns 0, while a 2-day period
--   spanning month end returns 1. The same trap applies to DATEDIFF('day') and
--   is why the blip guard above is expressed in hours.
--   CUSTOMER_AGE_MONTHS can be NEGATIVE - that marks pre-contract ownership,
--   where the TSM held the account before it had a licence.
--
-- LEFT_DATE:
--   End of the ownership run, capped at relevant_date. For a still-open run
--   this is relevant_date.
--
-- SCOPE:
--   - Owners: DIM_EMPLOYEE where TITLE contains TSM, Technical Success Manager,
--     or Solution Architect, hired on or before relevant_date, AND currently
--     assigned to at least one active customer (cs_owner_pool). Note this
--     excludes TSMs who currently own nothing (e.g. Magali Philippe, Chris
--     Hodson, Tal Shladovsky) along with their historical periods.
--   - Companies: LIFECYCLE_STAGE IN ('Customer', 'Churn').
--
-- METRIC SHAPES - read this before interpreting the columns:
--   Cumulative pairs (*_AT_ASSIGNMENT / *_AT_LEFT) are all-time totals as of
--   each date, with NO lower bound. They are not period totals.
--     - AI_EVENTS and SELF_SERVICE_RUNS are additive, so activity DURING the
--       period is recoverable as (_AT_LEFT - _AT_ASSIGNMENT).
--     - UNIQUE_LOGINS is COUNT(DISTINCT ...), so its difference is NET user
--       growth, not the number of new users. It does not subtract cleanly.
--   GONG_CALLS is the exception: an in-window count of calls made between
--   ASSIGNED_DATE and LEFT_DATE, not a cumulative pair.
--
-- ARR:
--   - ARR_AT_ASSIGNMENT: from DIM_COMPANY_SCD, looked up 1 day after the
--     assignment date to avoid intra-day blips.
--   - ARR_AT_END_DATE: from DIM_COMPANY_SCD at LEFT_DATE. For churned companies
--     (LIFECYCLE_STAGE = 'Churn') this is forced to 0, so a churned account
--     reports 0 rather than its last contract value.
--
-- GONG CALLS:
--   Completed calls over 10 minutes where the TSM is listed as owner.
--   Targets (annualized, prorated by period length):
--     Strategic 48/yr, Core+ 36/yr, Core 9/yr, Digital N/A.
--
-- INTEGRATIONS:
--   INTEGRATION_TYPES_AT_ASSIGNMENT / _AT_LEFT: distinct integration types
--   (data inputs) live on each date - the adoption BREADTH measure. "Live on a
--   date" uses _DELETED_TIMESTAMP_UTC rather than the current _IS_DELETED flag,
--   so integrations removed later still count at the historical date.
--   Raw instance counts are deliberately not exposed: one type can have many
--   connections (Bell Canada: 7 types across 41 instances, 15 of them
--   gitlab-v2), so instances overstate breadth.
--
-- FILTERS APPLIED TO FINAL OUTPUT:
--   - Historical periods must exceed 14 days (removes brief handoffs).
--     CURRENT periods are exempt, so a live assignment always appears
--     regardless of tenure.
--   - No license requirement. The old "a license must have overlapped the
--     ownership window" filter was removed, so companies with no license
--     record still appear (e.g. MSD, whose only FACT_PURCHASED_SEATS row has
--     NULL start/end dates). This also means pre-contract periods are no
--     longer suppressed; under the period model they surface as separate
--     historical rows rather than corrupting the current one.
--   - TSMs with no qualifying periods still appear (with NULL company rows).
--
-- NO PASS/FAIL SCORE, AND NO SEAT UTILIZATION. Licence and seat-utilization
--   columns were removed. Utilization could not be scored fairly when the
--   licence changed mid-ownership: seats at LEFT_DATE penalizes upselling
--   (540 users on 600 seats = 90% pass; upsell to 800 and the same users score
--   68% fail), while seats at ASSIGNED_DATE goes stale and ignores seats added
--   later. UNIQUE_LOGINS_AT_* is retained as the raw adoption signal.
-- ============================================================

WITH params AS (
    -- Snapshot date: last second of the previous calendar month (dynamic).
    -- To pin to a specific point in time, replace with a literal, e.g.:
    --   End of last full quarter : '2026-06-30 23:59:59'::TIMESTAMP
    SELECT DATEADD('second', -1, DATE_TRUNC('month', CURRENT_DATE()))::TIMESTAMP AS relevant_date
),
cs_owner_pool AS (
    -- The full CS owner pool: everyone currently assigned to at least one
    -- active customer. Gates the roster below.
    SELECT DISTINCT SK_CSM_OWNER
    FROM PORT_ANALYTICS_PROD.DWH.DIM_COMPANY
    WHERE LIFECYCLE_STAGE = 'Customer'
      AND SK_CSM_OWNER IS NOT NULL
),
customer_pool AS (
    -- The customer pool: one row per company, carrying tier, lifecycle and the
    -- CURRENT owner. Single source for the tier lookup and churn ARR override.
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
tsm_employees AS (
    -- Owner roster with hire dates.
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
    -- Shared company -> account -> org mapping, built once instead of repeated
    -- in every metric CTE. Grain is one row per (SK_COMPANY, SK_ACCOUNT,
    -- SK_ORG), so SUM/COUNT fan-out matches the original inline joins.
    -- IS_ACTIVE_LIFECYCLE carries the lifecycle filter as a flag: the
    -- login/self-service/AI CTEs require it, integrations do not.
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
),
-- ---------- ownership period detection (gaps-and-islands) ----------
scd_owners AS (
    -- Raw SCD ownership versions in scope. Individual versions are NOT
    -- assignments; they are collapsed into runs below.
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
    -- Pass 1: mark where the owner actually changes.
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
    -- Consecutive same-owner versions collapsed into one contiguous run.
    SELECT
        SK_COMPANY,
        SK_CSM_OWNER,
        MIN(EFFECTIVE_START_DATE) AS run_start,
        MAX(EFFECTIVE_END_DATE)   AS run_end
    FROM run_pass1_grp
    GROUP BY SK_COMPANY, SK_CSM_OWNER, run_grp
),
runs_kept AS (
    -- Suppress blip runs (under 24h elapsed). Open/current runs always kept.
    SELECT *
    FROM runs_pass1
    WHERE run_end > (SELECT relevant_date FROM params)
       OR DATEDIFF('hour', run_start, run_end) >= 24
),
run_pass2_flag AS (
    -- Pass 2: re-collapse after blip removal so same-owner runs separated only
    -- by a suppressed blip merge into one continuous period.
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
    -- One row per real ownership period. PERIOD_ID is the single join key for
    -- every metric CTE below, so multiple periods per TSM x company cannot
    -- fan out the metric joins.
    SELECT
        HASH(r.SK_CSM_OWNER, r.SK_COMPANY, r.run_start) AS PERIOD_ID,
        r.SK_CSM_OWNER,
        r.SK_COMPANY,
        cp.COMPANY_CRM_ID,
        cp.COMPANY_NAME,
        cp.LIFECYCLE_STAGE,
        cp.CUSTOMER_INTERNAL_TIER,
        t.HIRE_DATE,
        GREATEST(r.run_start, t.HIRE_DATE::TIMESTAMP) AS ASSIGNED_DATE,
        -- TRUE when the CRM claims ownership starting before the owner's hire
        -- date, so ASSIGNED_DATE above is the hire date rather than a real CRM
        -- event. Such a date will NOT be findable in HubSpot's change history.
        -- A CS owner cannot own a customer before being hired, so the floor is
        -- correct - this flag just makes the correction auditable.
        (r.run_start < t.HIRE_DATE::TIMESTAMP) AS ASSIGNED_DATE_FLOORED_AT_HIRE,
        LEAST(r.run_end, (SELECT relevant_date FROM params)) AS LEFT_DATE,
        -- At most one period per company can be live: the run is still open
        -- AND this owner is the current owner in DIM_COMPANY.
        (r.run_end > (SELECT relevant_date FROM params)
         AND cp.CURRENT_OWNER = r.SK_CSM_OWNER) AS IS_CURRENT_CS
    FROM ownership_runs r
    INNER JOIN tsm_employees t
        ON t.SK_EMPLOYEE = r.SK_CSM_OWNER
    INNER JOIN customer_pool cp
        ON cp.SK_COMPANY = r.SK_COMPANY
    -- Period must overlap the reporting window and not start after it
    WHERE GREATEST(r.run_start, t.HIRE_DATE::TIMESTAMP) <= (SELECT relevant_date FROM params)
      AND r.run_end > t.HIRE_DATE::TIMESTAMP
),
-- ---------- metrics, all keyed on PERIOD_ID ----------
arr_and_tier_at_dates AS (
    -- TIER_AT_ASSIGNMENT and ARR at both dates share the same point-in-time
    -- SCD lookups, so they are resolved together rather than scanning
    -- DIM_COMPANY_SCD twice more.
    SELECT
        f.PERIOD_ID,
        COALESCE(arr_start.ARR, 0) AS ARR_AT_ASSIGNMENT,
        -- Churned companies report 0 at end regardless of the SCD value
        CASE
            WHEN f.LIFECYCLE_STAGE = 'Churn' THEN 0
            ELSE COALESCE(arr_end.ARR, 0)
        END AS ARR_AT_END_DATE,
        arr_start.CUSTOMER_INTERNAL_TIER AS TIER_AT_ASSIGNMENT
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
logins_at_dates AS (
    -- Cumulative distinct users as of each date. No lower bound: these are
    -- all-time totals, not period totals. COUNT(DISTINCT ...) does not
    -- subtract cleanly - the difference is NET user growth.
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
    -- Cumulative AI events as of each date. Additive, so events DURING the
    -- period = AI_EVENTS_AT_LEFT - AI_EVENTS_AT_ASSIGNMENT.
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
    -- All-time first AI usage date per company (no period restriction)
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
    -- IN-WINDOW count (not a cumulative pair): calls made between
    -- ASSIGNED_DATE and LEFT_DATE where this TSM is the owner.
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
    -- Cumulative self-service runs as of each date. Additive, so runs DURING
    -- the period = SELF_SERVICE_RUNS_AT_LEFT - SELF_SERVICE_RUNS_AT_ASSIGNMENT.
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
    -- Distinct integration TYPES live on each date: created on/before the date
    -- and not deleted by then. Types, not instances - one type can hold many
    -- connections (Bell Canada has 15 gitlab-v2), which is one capability, not
    -- fifteen. Uses _DELETED_TIMESTAMP_UTC for point-in-time state rather than
    -- the current _IS_DELETED flag.
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
    -- Only used for CUSTOMER_AGE_MONTHS. Licence and seat-utilization columns
    -- are no longer exposed.
    SELECT SK_COMPANY, MIN(START_DATE) AS FIRST_LICENSE_DATE
    FROM PORT_ANALYTICS_PROD.DWH.FACT_PURCHASED_SEATS
    WHERE DATEDIFF(day, START_DATE, END_DATE) > 1
      AND TOTAL_LICENSED_USERS > 0
    GROUP BY SK_COMPANY
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
    -- Elapsed months, not DATEDIFF('month'), for the same boundary-crossing
    -- reason as MONTHS_OWNED below. Negative values are meaningful: they mark
    -- pre-contract ownership, where the TSM held the account before it had a
    -- licence, so FIRST_LICENSE_DATE falls after LEFT_DATE.
    ROUND(DATEDIFF('day', fl.FIRST_LICENSE_DATE, f.LEFT_DATE) / 30.44, 1) AS CUSTOMER_AGE_MONTHS,
    f.ASSIGNED_DATE,
    f.ASSIGNED_DATE_FLOORED_AT_HIRE,
    f.LEFT_DATE,
    -- Elapsed months, not DATEDIFF('month'): DATEDIFF counts calendar-boundary
    -- crossings, so a 33-day period inside one month would report 0 while a
    -- 2-day period spanning month end would report 1. Divided by the mean month
    -- length and kept to one decimal so short periods stay visible.
    ROUND(DATEDIFF('day', f.ASSIGNED_DATE, f.LEFT_DATE) / 30.44, 1) AS MONTHS_OWNED,
    at.TIER_AT_ASSIGNMENT,
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
    -- Gong call targets per tier (annualized, prorated to the period):
    --   Strategic : 48 calls/year
    --   Core+     : 36 calls/year
    --   Core      : 9 calls/year
    --   Digital   : no target defined
    ROUND(
        DATEDIFF('day', f.ASSIGNED_DATE, f.LEFT_DATE) / 365.0 *
        CASE at.TIER_AT_ASSIGNMENT
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
    -- TRUE only on the company's live ownership period. At most one row per
    -- company can be TRUE. Computed in ownership_periods so the WHERE clause
    -- below can filter on it.
    f.IS_CURRENT_CS
FROM tsm_employees t
LEFT JOIN ownership_periods f
    ON t.SK_EMPLOYEE = f.SK_CSM_OWNER
LEFT JOIN arr_and_tier_at_dates at
    ON f.PERIOD_ID = at.PERIOD_ID
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
