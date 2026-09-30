-- Org Activation Funnel Query
-- Standalone SQL to explore the activation funnel stages
-- Based on org_activation.py dashboard logic

-- =============================================================================
-- MAIN FUNNEL: Aggregated stage counts and conversion rates
-- =============================================================================

WITH funnel_data AS (
    SELECT 
        stage_order,
        stage_name,
        COUNT(DISTINCT org_id) AS orgs_tested,
        COUNT(DISTINCT CASE WHEN pass THEN org_id END) AS orgs_passed
    FROM PORT_ANALYTICS_PROD.PRODUCT.OA6_FUNNEL_RAW
    WHERE 1=1
        -- Optional filters (uncomment to use):
        -- AND org_created_timestamp >= '2024-01-01'
        -- AND org_created_timestamp < '2024-02-01'
        -- AND lifecyclestage IN ('lead', 'opportunity')
        -- AND meeting_booked = TRUE
    GROUP BY stage_order, stage_name
)
SELECT 
    stage_order,
    stage_name,
    SUM(orgs_passed) AS orgs,
    CASE 
        WHEN SUM(orgs_tested) > 0 
        THEN ROUND(SUM(orgs_passed) * 100.0 / SUM(orgs_tested), 2) 
    END AS conversion_rate_pct
FROM funnel_data
GROUP BY stage_order, stage_name
ORDER BY stage_order;

-- =============================================================================
-- STAGE-TO-STAGE CONVERSION: How orgs flow between stages
-- =============================================================================

-- Note: Run the main funnel query above first to get counts
-- Then calculate:
-- Signup -> Onboarding: (onboarding / signup) * 100
-- Onboarding -> Setup: (setup / onboarding) * 100
-- Setup -> Aha: (aha / setup) * 100
-- Aha -> Habit: (habit / aha) * 100

-- =============================================================================
-- DETAILED FUNNEL: See individual org progression
-- =============================================================================

SELECT 
    org_id,
    org_name,
    lifecyclestage,
    meeting_booked,
    user_prompt_text,
    org_created_timestamp,
    creator_email,
    MAX(CASE WHEN stage_name = 'signup' AND pass THEN 1 ELSE 0 END) AS signup,
    MAX(CASE WHEN stage_name = 'onboarding finished' AND pass THEN 1 ELSE 0 END) AS onboarding_finished,
    MAX(CASE WHEN stage_name = 'setup' AND pass THEN 1 ELSE 0 END) AS setup,
    MAX(CASE WHEN stage_name = 'aha' AND pass THEN 1 ELSE 0 END) AS aha,
    MAX(CASE WHEN stage_name = 'habit' AND pass THEN 1 ELSE 0 END) AS habit
FROM PORT_ANALYTICS_PROD.PRODUCT.OA6_FUNNEL_RAW
WHERE 1=1
    -- Optional filters:
    -- AND org_created_timestamp >= DATEADD(month, -1, CURRENT_DATE())
GROUP BY 
    org_id,
    org_name,
    lifecyclestage,
    meeting_booked,
    user_prompt_text,
    org_created_timestamp,
    creator_email
ORDER BY org_created_timestamp DESC
LIMIT 100;

-- =============================================================================
-- SETUP BREAKDOWN: Integration, SSA, and Workflow details
-- =============================================================================

SELECT 
    'Setup Stage Breakdown' AS metric,
    COUNT(DISTINCT org_id) AS total_orgs,
    COUNT(DISTINCT CASE WHEN healthy_integrations >= 1 THEN org_id END) AS with_healthy_integration,
    COUNT(DISTINCT CASE WHEN ssa_pass THEN org_id END) AS with_ssa,
    COUNT(DISTINCT CASE WHEN workflow_pass THEN org_id END) AS with_workflow,
    COUNT(DISTINCT CASE 
        WHEN healthy_integrations >= 1 
            AND (ssa_pass OR workflow_pass) 
        THEN org_id 
    END) AS passed_setup
FROM PORT_ANALYTICS_PROD.PRODUCT.OA3_SETUP2_TOTAL
WHERE 1=1;
    -- Optional filters:
    -- AND org_created_timestamp >= '2024-01-01';

-- =============================================================================
-- AHA MOMENT BREAKDOWN: Successful execution analysis
-- =============================================================================

SELECT 
    ARRAY_TO_STRING(
        ARRAY_COMPACT(
            ARRAY_CONSTRUCT(
                CASE WHEN aha_ssa_pass = TRUE THEN 'ssa' END,
                CASE WHEN aha_workflow_pass = TRUE THEN 'workflow' END
            )
        ), 
        ' & '
    ) AS aha_type,
    COUNT(DISTINCT org_id) AS orgs
FROM PORT_ANALYTICS_PROD.PRODUCT.OA4_AHA2_TOTAL
WHERE pass = TRUE
    -- Optional filters:
    -- AND org_created_timestamp >= '2024-01-01'
GROUP BY 1
ORDER BY orgs DESC;

-- =============================================================================
-- WEEKLY FUNNEL TRENDS
-- =============================================================================

SELECT 
    week_date,
    SUM(signup) AS signup,
    SUM(onboarding) AS onboarding,
    SUM(setup) AS setup,
    SUM(aha) AS aha,
    SUM(habit) AS habit,
    SUM(meeting_booked_count) AS meeting_booked,
    -- Stage-to-stage conversion rates
    CASE WHEN SUM(signup) > 0 THEN ROUND(100.0 * SUM(onboarding) / SUM(signup), 2) END AS onboarding_rate,
    CASE WHEN SUM(onboarding) > 0 THEN ROUND(100.0 * SUM(setup) / SUM(onboarding), 2) END AS setup_rate,
    CASE WHEN SUM(setup) > 0 THEN ROUND(100.0 * SUM(aha) / SUM(setup), 2) END AS aha_rate,
    CASE WHEN SUM(aha) > 0 THEN ROUND(100.0 * SUM(habit) / SUM(aha), 2) END AS habit_rate,
    -- Signup-based conversion rates
    CASE WHEN SUM(signup) > 0 THEN ROUND(100.0 * SUM(habit) / SUM(signup), 2) END AS activation_rate
FROM PORT_ANALYTICS_PROD.PRODUCT.OA6_FUNNEL_WEEKLY
WHERE 1=1
    -- Optional date filter:
    -- AND week_date >= DATEADD(month, -3, CURRENT_DATE())
GROUP BY week_date
ORDER BY week_date DESC
LIMIT 12;

-- =============================================================================
-- ACTIVATION RATE KPI
-- =============================================================================

WITH stage_counts AS (
    SELECT 
        stage_name,
        SUM(CASE WHEN pass THEN 1 ELSE 0 END) AS orgs
    FROM PORT_ANALYTICS_PROD.PRODUCT.OA6_FUNNEL_RAW
    WHERE 1=1
        -- Optional filters:
        -- AND org_created_timestamp >= '2024-01-01'
        -- AND org_created_timestamp < '2024-02-01'
    GROUP BY stage_name
)
SELECT 
    MAX(CASE WHEN stage_name = 'signup' THEN orgs END) AS signup_count,
    MAX(CASE WHEN stage_name = 'habit' THEN orgs END) AS habit_count,
    CASE 
        WHEN MAX(CASE WHEN stage_name = 'signup' THEN orgs END) > 0 
        THEN ROUND(
            MAX(CASE WHEN stage_name = 'habit' THEN orgs END) * 100.0 / 
            MAX(CASE WHEN stage_name = 'signup' THEN orgs END), 
            2
        )
    END AS activation_rate_pct
FROM stage_counts;
