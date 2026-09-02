
-- ============================================================
-- TSM SCORECARD V2 — Company-Level Assignment Metrics
-- ============================================================
--
-- PURPOSE:
--   One row per TSM × Company assignment showing key success metrics
--   for the period the TSM owned the company.
--
-- SCOPE (who is included):
--   - TSMs: DIM_EMPLOYEE where TITLE contains TSM, Technical Success Manager,
--           or Solution Architect; hired on or before relevant_date.
--   - Only TSMs who are CURRENTLY assigned to at least one active customer
--     (current_cs_owners via DIM_COMPANY where LIFECYCLE_STAGE = 'Customer').
--   - Companies: LIFECYCLE_STAGE IN ('Customer', 'Churn').
--
-- ASSIGNMENT DETECTION (how we find the assigned date):
--   1. Explicit change: SK_CSM_OWNER changed in DIM_COMPANY_SCD (LAG detection).
--   2. Inherited: TSM was already the owner before their hire date; use
--      the first SCD record on or after hire date as the assigned date.
--   - Pre-2024 SCD records are excluded (unreliable historical data).
--   - SCD versions lasting < 1 day are excluded (sub-day blips/pipeline noise).
--   - Today's pipeline SCD refreshes are excluded from inherited assignments.
--
-- LEFT_DATE (end of ownership):
--   - If the company was reassigned to a different owner: date of that change.
--   - If still assigned: CURRENT_TIMESTAMP (today).
--   - In all cases capped at relevant_date (CURRENT_TIMESTAMP).
--
-- FILTERS APPLIED TO FINAL OUTPUT:
--   - Ownership period must be > 14 days (removes brief handoffs).
--   - A license must have overlapped the ownership window. This drops
--     pre-contract ownership: cases where the TSM held the account through
--     the sales cycle and handed it off within days of the first license
--     starting (e.g. abu dhabi, StoneX, bhp, ses engineering, Wisconsin),
--     as well as companies with no license record at all.
--   - TSMs with no qualifying assignments still appear (with NULL company rows).
--
-- ARR:
--   - ARR_AT_ASSIGNMENT: from DIM_COMPANY_SCD, looked up 1 day after
--     assignment date to avoid intra-day blips.
--   - ARR_AT_END_DATE: from DIM_COMPANY_SCD at LEFT_DATE.
--     For churned companies (LIFECYCLE_STAGE = 'Churn'): forced to 0.
--
-- GONG CALLS:
--   - Completed calls > 10 minutes where TSM is listed as owner.
--   - Targets (annualized, prorated by ownership days):
--     Strategic 48/yr, Core+ 36/yr, Core 9/yr, Digital N/A.
--
-- SELF-SERVICE ACTIONS:
--   - Only TRIGGER_TYPE = 'self-service' from FACT_ACTION_RUNS.
--   - Monthly rate = total / (days_owned / 30).
--
-- LICENSED USERS:
--   - First non-zero license from FACT_PURCHASED_SEATS active at any
--     point during the ownership window (ASSIGNED_DATE to LEFT_DATE).
--   - Duration filter: license must last > 1 day.
--
-- LOGINS:
--   - Distinct user emails who logged in between ASSIGNED_DATE and LEFT_DATE.
--
-- AI EVENTS:
--   - SUM of NUMBER_OF_EVENTS from FACT_AI_USAGE between ASSIGNED_DATE and LEFT_DATE.
--   - FIRST_AI_USAGE_DATE: All-time earliest AI usage date per company (no window).
--
-- SEAT UTILIZATION:
--   - LICENSES_AT_ASSIGNMENT / LICENSES_AT_LEFT: seats in force on each date
--     (point-in-time; NULL when no license was active on that date).
--   - UNIQUE_LOGINS_AT_ASSIGNMENT / UNIQUE_LOGINS_AT_LEFT: all-time cumulative
--     distinct users as of each date. The difference is net new users.
--   - SEAT_UTILIZATION_AT_ASSIGNMENT / SEAT_UTILIZATION_AT_LEFT: each pair
--     divided at its own point in time, so numerator and denominator always
--     match. NULL when no license was in force on that date.
--
--   NO PASS/FAIL SCORE. A tier/age threshold column was built and removed:
--   utilization can't be scored fairly when the license changes mid-ownership.
--     - Seats at LEFT_DATE penalizes upselling: 540 users on 600 seats = 90%
--       (pass); upsell to 800 and the same users score 68% (fail).
--     - Seats at ASSIGNED_DATE avoids that but goes stale, ignoring seats added
--       later. Affects 35/124 rows, license grew in all - always flattering.
--   Both endpoints are exposed instead, so the license change stays visible:
--   comparing the two shows whether an upsell occurred during ownership, and
--   utilization can be read as a trajectory rather than a single verdict.
-- ============================================================

-- Find company-level CS owner assignments for each TSM
-- Shows when each TSM was first assigned to each company (customers only)
-- Uses SCD table with LAG to detect when SK_CSM_OWNER changed
WITH params AS (
    SELECT CURRENT_TIMESTAMP() AS relevant_date
),
current_cs_owners AS (
    -- CS owners currently assigned to at least one active customer
    SELECT DISTINCT SK_CSM_OWNER
    FROM PORT_ANALYTICS_PROD.DWH.DIM_COMPANY
    WHERE LIFECYCLE_STAGE = 'Customer'
      AND SK_CSM_OWNER IS NOT NULL
),
cs_owners_for_customers AS (
    -- Get all CS owners who ever owned a customer company (current or historical)
    SELECT DISTINCT scd.SK_CSM_OWNER
    FROM PORT_ANALYTICS_PROD.DWH.DIM_COMPANY_SCD scd
    INNER JOIN PORT_ANALYTICS_PROD.DWH.DIM_COMPANY comp ON comp.SK_COMPANY = scd.SK_COMPANY
    WHERE comp.LIFECYCLE_STAGE = 'Customer'
      AND scd.SK_CSM_OWNER IS NOT NULL
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
    JOIN current_cs_owners cs ON cs.SK_CSM_OWNER = e.SK_EMPLOYEE
    WHERE (e.TITLE ILIKE '%TSM%'
       OR e.TITLE ILIKE '%Technical Success Manager%'
       OR e.TITLE ILIKE '%Solution Architect%')
      AND e.ORIGINAL_START_DATE <= (SELECT relevant_date FROM params)
),
company_csm_changes AS (
    SELECT 
        scd.SK_COMPANY,
        scd.COMPANY_CRM_ID,
        scd.COMPANY_NAME,
        scd.SK_CSM_OWNER,
        scd.EFFECTIVE_START_DATE,
        scd.EFFECTIVE_END_DATE,
        scd.IS_LATEST_VERSION,
        -- LAG over ALL SCD records (not just current owners) to detect real transitions
        LAG(scd.SK_CSM_OWNER) OVER (
            PARTITION BY scd.SK_COMPANY 
            ORDER BY scd.EFFECTIVE_START_DATE
        ) AS PREV_CSM_OWNER
    FROM PORT_ANALYTICS_PROD.DWH.DIM_COMPANY_SCD scd
    INNER JOIN PORT_ANALYTICS_PROD.DWH.DIM_COMPANY comp 
        ON comp.SK_COMPANY = scd.SK_COMPANY
        AND comp.LIFECYCLE_STAGE IN ('Customer', 'Churn')
    WHERE scd.SK_CSM_OWNER IS NOT NULL
),
first_assignment AS (
    SELECT 
        c.SK_CSM_OWNER,
        c.SK_COMPANY,
        c.COMPANY_CRM_ID,
        c.COMPANY_NAME,
        c.EFFECTIVE_START_DATE AS ASSIGNED_DATE,
        t.HIRE_DATE,
        ROW_NUMBER() OVER (
            PARTITION BY c.SK_CSM_OWNER, c.SK_COMPANY 
            ORDER BY c.EFFECTIVE_START_DATE
        ) AS assignment_rank
    FROM company_csm_changes c
    INNER JOIN tsm_employees t ON c.SK_CSM_OWNER = t.SK_EMPLOYEE
    WHERE c.EFFECTIVE_START_DATE >= '2024-01-01'  -- Exclude pre-2024 assignments (unreliable historical data)
      AND DATEDIFF('day', c.EFFECTIVE_START_DATE, COALESCE(c.EFFECTIVE_END_DATE, CURRENT_TIMESTAMP)) >= 1  -- Min 1 day duration
      AND (
        (
            -- Historical assignments: explicit LAG-detected owner change
            (c.SK_CSM_OWNER != COALESCE(c.PREV_CSM_OWNER, '') OR c.PREV_CSM_OWNER IS NULL)
            AND c.EFFECTIVE_START_DATE >= t.HIRE_DATE
            AND c.EFFECTIVE_START_DATE <= (SELECT relevant_date FROM params)
        ) OR (
            -- Inherited assignments: TSM owned this company before their hire date
            -- No LAG change exists after hire; pick first post-hire SCD record (ROW_NUMBER takes earliest)
            c.PREV_CSM_OWNER = c.SK_CSM_OWNER  -- Owner didn't change in this SCD version
            AND c.EFFECTIVE_START_DATE >= t.HIRE_DATE
            AND c.EFFECTIVE_START_DATE::DATE < CURRENT_DATE()  -- Exclude today's pipeline refreshes
        )
      )
),
assignment_end_dates AS (
    SELECT 
        f.SK_CSM_OWNER,
        f.SK_COMPANY,
        MIN(c2.EFFECTIVE_START_DATE) AS LEFT_DATE
    FROM first_assignment f
    INNER JOIN company_csm_changes c2 
        ON f.SK_COMPANY = c2.SK_COMPANY 
        AND c2.EFFECTIVE_START_DATE > f.ASSIGNED_DATE
        AND c2.SK_CSM_OWNER != f.SK_CSM_OWNER
    WHERE f.assignment_rank = 1
    GROUP BY f.SK_CSM_OWNER, f.SK_COMPANY
),
arr_metrics AS (
    SELECT 
        f.SK_CSM_OWNER,
        f.SK_COMPANY,
        LEAST(
            COALESCE(e.LEFT_DATE, (SELECT relevant_date FROM params)),
            (SELECT relevant_date FROM params)
        ) AS LEFT_DATE,
        COALESCE(arr_start.ARR, 0) AS ARR_AT_ASSIGNMENT,
        -- If company has churned, ARR at end is 0 regardless of SCD value
        CASE 
            WHEN comp.LIFECYCLE_STAGE = 'Churn' THEN 0
            ELSE COALESCE(arr_end.ARR, 0)
        END AS ARR_AT_END_DATE,
        arr_start.CUSTOMER_INTERNAL_TIER AS TIER_AT_ASSIGNMENT
    FROM first_assignment f
    INNER JOIN PORT_ANALYTICS_PROD.DWH.DIM_COMPANY comp ON comp.SK_COMPANY = f.SK_COMPANY
    LEFT JOIN assignment_end_dates e
        ON f.SK_CSM_OWNER = e.SK_CSM_OWNER
        AND f.SK_COMPANY = e.SK_COMPANY
    LEFT JOIN PORT_ANALYTICS_PROD.DWH.DIM_COMPANY_SCD arr_start
        ON f.SK_COMPANY = arr_start.SK_COMPANY
        AND DATEADD(day, 1, f.ASSIGNED_DATE::DATE)::TIMESTAMP >= arr_start.EFFECTIVE_START_DATE
        AND DATEADD(day, 1, f.ASSIGNED_DATE::DATE)::TIMESTAMP < COALESCE(arr_start.EFFECTIVE_END_DATE, '9999-12-31')
    LEFT JOIN PORT_ANALYTICS_PROD.DWH.DIM_COMPANY_SCD arr_end
        ON f.SK_COMPANY = arr_end.SK_COMPANY
        AND LEAST(COALESCE(e.LEFT_DATE, (SELECT relevant_date FROM params)), (SELECT relevant_date FROM params)) >= arr_end.EFFECTIVE_START_DATE
        AND LEAST(COALESCE(e.LEFT_DATE, (SELECT relevant_date FROM params)), (SELECT relevant_date FROM params)) < COALESCE(arr_end.EFFECTIVE_END_DATE, '9999-12-31')
    WHERE f.assignment_rank = 1
),
company_logins AS (
    SELECT
        f.SK_CSM_OWNER,
        f.SK_COMPANY,
        COUNT(DISTINCT ful.USER_EMAIL_ADDRESS) AS UNIQUE_LOGINS
    FROM first_assignment f
    INNER JOIN arr_metrics arr
        ON f.SK_CSM_OWNER = arr.SK_CSM_OWNER
        AND f.SK_COMPANY = arr.SK_COMPANY
    INNER JOIN PORT_ANALYTICS_PROD.DWH.DIM_ACCOUNT da
        ON da.SK_COMPANY = f.SK_COMPANY
        AND da.IS_COMMERCIAL_ACCOUNT = TRUE
    INNER JOIN PORT_ANALYTICS_PROD.DWH.DIM_ORG do
        ON do.SK_ACCOUNT = da.SK_ACCOUNT
    LEFT JOIN PORT_ANALYTICS_PROD.DWH.FACT_USER_LOGIN ful
        ON ful.SK_ORG = do.SK_ORG
        AND ful.LOGIN_DATE >= f.ASSIGNED_DATE::DATE
        AND ful.LOGIN_DATE <= arr.LEFT_DATE::DATE
    WHERE f.assignment_rank = 1
    GROUP BY f.SK_CSM_OWNER, f.SK_COMPANY
),
company_self_service_runs AS (
    SELECT
        f.SK_CSM_OWNER,
        f.SK_COMPANY,
        SUM(ar.COUNT_SUCCEEDED + ar.COUNT_FAILED) AS TOTAL_SELF_SERVICE_RUNS
    FROM first_assignment f
    INNER JOIN arr_metrics arr
        ON f.SK_CSM_OWNER = arr.SK_CSM_OWNER
        AND f.SK_COMPANY = arr.SK_COMPANY
    INNER JOIN PORT_ANALYTICS_PROD.DWH.DIM_ACCOUNT da
        ON da.SK_COMPANY = f.SK_COMPANY
        AND da.IS_COMMERCIAL_ACCOUNT = TRUE
    INNER JOIN PORT_ANALYTICS_PROD.DWH.DIM_ORG do
        ON do.SK_ACCOUNT = da.SK_ACCOUNT
    LEFT JOIN PORT_ANALYTICS_PROD.DWH.FACT_ACTION_RUNS ar
        ON ar.SK_ORG = do.SK_ORG
        AND ar._FACT_DATE >= f.ASSIGNED_DATE
        AND ar._FACT_DATE <= arr.LEFT_DATE
        AND ar.SK_ACTION IN (SELECT SK_ACTION FROM PORT_ANALYTICS_PROD.DWH.DIM_ACTION WHERE TRIGGER_TYPE = 'self-service')
    WHERE f.assignment_rank = 1
    GROUP BY f.SK_CSM_OWNER, f.SK_COMPANY
),
company_gong_calls AS (
    SELECT
        f.SK_CSM_OWNER,
        f.SK_COMPANY,
        COUNT(DISTINCT fc.SK_CONVERSATION) AS GONG_CALLS
    FROM first_assignment f
    INNER JOIN arr_metrics arr
        ON f.SK_CSM_OWNER = arr.SK_CSM_OWNER
        AND f.SK_COMPANY = arr.SK_COMPANY
    INNER JOIN PORT_ANALYTICS_PROD.DWH.MV_CALL_ASSOCIATED_COMPANY_FLAT caf
        ON caf.ASSOCIATED_SK = f.SK_COMPANY
    INNER JOIN PORT_ANALYTICS_PROD.DWH.FACT_CALL fc
        ON fc.SK_CONVERSATION = caf.SK_CONVERSATION
        AND fc.EFFECTIVE_START_DATETIME >= f.ASSIGNED_DATE
        AND fc.EFFECTIVE_START_DATETIME <= arr.LEFT_DATE
        AND ARRAY_CONTAINS(f.SK_CSM_OWNER::VARIANT, fc.ASSOCIATED_OWNER)
        AND fc.DURATION_SECONDS > 600  -- Over 10 minutes
    WHERE f.assignment_rank = 1
    GROUP BY f.SK_CSM_OWNER, f.SK_COMPANY
),
purchased_seats AS (
    SELECT SK_COMPANY, SK_LICENSE, START_DATE, END_DATE, TOTAL_LICENSED_USERS, IS_UNLIMITED, TYPE
    FROM PORT_ANALYTICS_PROD.DWH.FACT_PURCHASED_SEATS
    WHERE DATEDIFF(day, START_DATE, END_DATE) > 1
),
company_first_license AS (
    SELECT SK_COMPANY, MIN(START_DATE) AS FIRST_LICENSE_DATE
    FROM PORT_ANALYTICS_PROD.DWH.FACT_PURCHASED_SEATS
    WHERE DATEDIFF(day, START_DATE, END_DATE) > 1
      AND TOTAL_LICENSED_USERS > 0
    GROUP BY SK_COMPANY
),
company_ai_features AS (
    SELECT
        f.SK_CSM_OWNER,
        f.SK_COMPANY,
        SUM(ai.NUMBER_OF_EVENTS) AS AI_EVENTS
    FROM first_assignment f
    INNER JOIN arr_metrics arr
        ON f.SK_CSM_OWNER = arr.SK_CSM_OWNER
        AND f.SK_COMPANY = arr.SK_COMPANY
    INNER JOIN PORT_ANALYTICS_PROD.DWH.DIM_ACCOUNT da
        ON da.SK_COMPANY = f.SK_COMPANY
        AND da.IS_COMMERCIAL_ACCOUNT = TRUE
    INNER JOIN PORT_ANALYTICS_PROD.DWH.DIM_ORG do
        ON do.SK_ACCOUNT = da.SK_ACCOUNT
    LEFT JOIN PORT_ANALYTICS_PROD.DWH.FACT_AI_USAGE ai
        ON ai.SK_ORG = do.SK_ORG
        AND ai._FACT_DATE >= f.ASSIGNED_DATE
        AND ai._FACT_DATE <= arr.LEFT_DATE
    WHERE f.assignment_rank = 1
    GROUP BY f.SK_CSM_OWNER, f.SK_COMPANY
),
company_first_ai_date AS (
    -- All-time first AI usage date per company (no ownership window restriction)
    SELECT
        da.SK_COMPANY,
        MIN(ai._FACT_DATE) AS FIRST_AI_USAGE_DATE
    FROM PORT_ANALYTICS_PROD.DWH.DIM_ACCOUNT da
    INNER JOIN PORT_ANALYTICS_PROD.DWH.DIM_ORG do
        ON do.SK_ACCOUNT = da.SK_ACCOUNT
    INNER JOIN PORT_ANALYTICS_PROD.DWH.FACT_AI_USAGE ai
        ON ai.SK_ORG = do.SK_ORG
    WHERE da.IS_COMMERCIAL_ACCOUNT = TRUE
      AND ai.NUMBER_OF_EVENTS > 0
    GROUP BY da.SK_COMPANY
),
license_at_dates AS (
    -- Seats in force at the assignment date and at the left date (point-in-time,
    -- not "first overlapping"). NULL when no license was active on that date.
    SELECT
        f.SK_CSM_OWNER,
        f.SK_COMPANY,
        MAX(CASE WHEN ps.START_DATE <= f.ASSIGNED_DATE::DATE
                  AND ps.END_DATE   >= f.ASSIGNED_DATE::DATE
                 THEN ps.TOTAL_LICENSED_USERS END) AS LICENSES_AT_ASSIGNMENT,
        MAX(CASE WHEN ps.START_DATE <= arr.LEFT_DATE::DATE
                  AND ps.END_DATE   >= arr.LEFT_DATE::DATE
                 THEN ps.TOTAL_LICENSED_USERS END) AS LICENSES_AT_LEFT
    FROM first_assignment f
    INNER JOIN arr_metrics arr
        ON f.SK_CSM_OWNER = arr.SK_CSM_OWNER
        AND f.SK_COMPANY = arr.SK_COMPANY
    LEFT JOIN purchased_seats ps
        ON ps.SK_COMPANY = f.SK_COMPANY
    WHERE f.assignment_rank = 1
    GROUP BY f.SK_CSM_OWNER, f.SK_COMPANY
),
logins_at_dates AS (
    -- All-time cumulative distinct users as of the assignment date and as of the
    -- left date. The difference between the two is net new users during ownership.
    SELECT
        f.SK_CSM_OWNER,
        f.SK_COMPANY,
        COUNT(DISTINCT CASE WHEN ful.LOGIN_DATE <= f.ASSIGNED_DATE::DATE
                            THEN ful.USER_EMAIL_ADDRESS END) AS UNIQUE_LOGINS_AT_ASSIGNMENT,
        COUNT(DISTINCT CASE WHEN ful.LOGIN_DATE <= arr.LEFT_DATE::DATE
                            THEN ful.USER_EMAIL_ADDRESS END) AS UNIQUE_LOGINS_AT_LEFT
    FROM first_assignment f
    INNER JOIN arr_metrics arr
        ON f.SK_CSM_OWNER = arr.SK_CSM_OWNER
        AND f.SK_COMPANY = arr.SK_COMPANY
    INNER JOIN PORT_ANALYTICS_PROD.DWH.DIM_ACCOUNT da
        ON da.SK_COMPANY = f.SK_COMPANY
        AND da.IS_COMMERCIAL_ACCOUNT = TRUE
    INNER JOIN PORT_ANALYTICS_PROD.DWH.DIM_ORG do
        ON do.SK_ACCOUNT = da.SK_ACCOUNT
    LEFT JOIN PORT_ANALYTICS_PROD.DWH.FACT_USER_LOGIN ful
        ON ful.SK_ORG = do.SK_ORG
    WHERE f.assignment_rank = 1
    GROUP BY f.SK_CSM_OWNER, f.SK_COMPANY
),
company_licensed_users AS (
    SELECT
        f.SK_CSM_OWNER,
        f.SK_COMPANY,
        ps.TOTAL_LICENSED_USERS AS LICENSED_USERS_AT_ASSIGNMENT,
        ps.IS_UNLIMITED
    FROM first_assignment f
    INNER JOIN arr_metrics arr
        ON f.SK_CSM_OWNER = arr.SK_CSM_OWNER
        AND f.SK_COMPANY = arr.SK_COMPANY
    INNER JOIN purchased_seats ps
        ON ps.SK_COMPANY = f.SK_COMPANY
        AND ps.START_DATE <= arr.LEFT_DATE::DATE  -- License starts before or on left date
        AND ps.END_DATE >= f.ASSIGNED_DATE::DATE - 1  -- License ends after or near assignment
    WHERE f.assignment_rank = 1
      AND ps.TOTAL_LICENSED_USERS != 0
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY f.SK_CSM_OWNER, f.SK_COMPANY
        ORDER BY ps.START_DATE
    ) = 1
)
SELECT 
    t.DISPLAY_NAME,
    t.EMAIL,
    t.TITLE,
    t.HIRE_DATE,
    f.SK_COMPANY,
    dc.COMPANY_CRM_ID,
    dc.COMPANY_NAME,
    fl.FIRST_LICENSE_DATE,
    DATEDIFF('month', fl.FIRST_LICENSE_DATE, arr.LEFT_DATE) AS CUSTOMER_AGE_MONTHS,
    f.ASSIGNED_DATE,
    arr.LEFT_DATE,
    DATEDIFF('quarter', f.ASSIGNED_DATE, arr.LEFT_DATE) AS QUARTERS_OWNED,
    arr.ARR_AT_ASSIGNMENT,
    arr.ARR_AT_END_DATE,
    arr.TIER_AT_ASSIGNMENT,
    CASE
        WHEN arr.ARR_AT_END_DATE = 0 AND arr.ARR_AT_ASSIGNMENT > 0 THEN 'churn'
        WHEN arr.ARR_AT_ASSIGNMENT > arr.ARR_AT_END_DATE            THEN 'downgrade'
        WHEN arr.ARR_AT_ASSIGNMENT < arr.ARR_AT_END_DATE            THEN 'upgrade'
        ELSE 'no_change'
    END AS ARR_TYPE,
    COALESCE(gc.GONG_CALLS, 0) AS GONG_CALLS,
    -- Gong call targets per tier (annualized, prorated to ownership period):
    --   Strategic : 48 calls/year
    --   Core+     : 36 calls/year
    --   Core      : 9 calls/year
    --   Digital   : no target defined
    ROUND(
        DATEDIFF('day', f.ASSIGNED_DATE, arr.LEFT_DATE) / 365.0 *
        CASE arr.TIER_AT_ASSIGNMENT
            WHEN 'Strategic' THEN 48
            WHEN 'Core+'     THEN 36
            WHEN 'Core'      THEN 9
            ELSE 0
        END
    ) AS EXPECTED_GONG_CALLS,
    COALESCE(cl.UNIQUE_LOGINS, 0) AS UNIQUE_LOGINS,
    COALESCE(ar.TOTAL_SELF_SERVICE_RUNS, 0) AS TOTAL_SELF_SERVICE_RUNS,
    DIV0(COALESCE(ar.TOTAL_SELF_SERVICE_RUNS, 0), NULLIF(DATEDIFF('day', f.ASSIGNED_DATE, arr.LEFT_DATE), 0) / 30.0) AS MONTHLY_SELF_SERVICE_RUNS,
    cfa.FIRST_AI_USAGE_DATE,
    COALESCE(ai.AI_EVENTS, 0) AS AI_EVENTS,
    lad.LICENSES_AT_ASSIGNMENT,
    lad.LICENSES_AT_LEFT,
    lod.UNIQUE_LOGINS_AT_ASSIGNMENT,
    lod.UNIQUE_LOGINS_AT_LEFT,
    DIV0(lod.UNIQUE_LOGINS_AT_ASSIGNMENT, lad.LICENSES_AT_ASSIGNMENT) AS SEAT_UTILIZATION_AT_ASSIGNMENT,
    DIV0(lod.UNIQUE_LOGINS_AT_LEFT, lad.LICENSES_AT_LEFT) AS SEAT_UTILIZATION_AT_LEFT,
    CASE WHEN cco.SK_CSM_OWNER IS NOT NULL THEN TRUE ELSE FALSE END AS IS_CURRENT_CS
FROM tsm_employees t
LEFT JOIN first_assignment f 
    ON t.SK_EMPLOYEE = f.SK_CSM_OWNER 
    AND f.assignment_rank = 1
LEFT JOIN arr_metrics arr
    ON f.SK_CSM_OWNER = arr.SK_CSM_OWNER
    AND f.SK_COMPANY = arr.SK_COMPANY
LEFT JOIN company_gong_calls gc
    ON f.SK_CSM_OWNER = gc.SK_CSM_OWNER
    AND f.SK_COMPANY = gc.SK_COMPANY
LEFT JOIN company_logins cl
    ON f.SK_CSM_OWNER = cl.SK_CSM_OWNER
    AND f.SK_COMPANY = cl.SK_COMPANY
LEFT JOIN company_self_service_runs ar
    ON f.SK_CSM_OWNER = ar.SK_CSM_OWNER
    AND f.SK_COMPANY = ar.SK_COMPANY
LEFT JOIN company_ai_features ai
    ON f.SK_CSM_OWNER = ai.SK_CSM_OWNER
    AND f.SK_COMPANY = ai.SK_COMPANY
LEFT JOIN company_licensed_users lu
    ON f.SK_CSM_OWNER = lu.SK_CSM_OWNER
    AND f.SK_COMPANY = lu.SK_COMPANY
LEFT JOIN current_cs_owners cco
    ON t.SK_EMPLOYEE = cco.SK_CSM_OWNER
LEFT JOIN PORT_ANALYTICS_PROD.DWH.DIM_COMPANY dc
    ON f.SK_COMPANY = dc.SK_COMPANY
LEFT JOIN company_first_license fl
    ON f.SK_COMPANY = fl.SK_COMPANY
LEFT JOIN company_first_ai_date cfa
    ON f.SK_COMPANY = cfa.SK_COMPANY
LEFT JOIN license_at_dates lad
    ON f.SK_CSM_OWNER = lad.SK_CSM_OWNER
    AND f.SK_COMPANY = lad.SK_COMPANY
LEFT JOIN logins_at_dates lod
    ON f.SK_CSM_OWNER = lod.SK_CSM_OWNER
    AND f.SK_COMPANY = lod.SK_COMPANY
WHERE f.SK_COMPANY IS NULL  -- TSMs with no assignments still show
   OR (
        DATEDIFF('day', f.ASSIGNED_DATE, arr.LEFT_DATE) > 14  -- Only assignments > 14 days
        AND lu.LICENSED_USERS_AT_ASSIGNMENT IS NOT NULL       -- Must have had a license during ownership
      )
ORDER BY t.DISPLAY_NAME, f.ASSIGNED_DATE;
