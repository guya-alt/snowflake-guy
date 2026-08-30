WITH deals_with_calls AS (
    SELECT 
        d.SK_DEAL,
        d.DEAL_NAME,
        d.DEAL_TEAM_NAME,
        d.DEAL_GEO,
        d.IS_WON,
        d.DEAL_TOTAL_ARR,
        d.DEAL_CLOSED_DATE,
        d.CLOSED_LOST_REASON,
        d.PIPELINE,
        d.DEAL_STAGE,
        d.SALES_CYCLE_DAYS,
        COUNT(c.SK_CONVERSATION) AS call_count
    FROM PORT_ANALYTICS_PROD.DWH.FACT_DEALS d
    JOIN PORT_ANALYTICS_PROD.DWH.FACT_CALL c
        ON ARRAY_CONTAINS(d.SK_DEAL::VARIANT, c.ASSOCIATED_DEAL)
    WHERE d.IS_CLOSED = TRUE
      AND d.IS_WON = FALSE
      AND d.DEAL_TYPE = 'newbusiness'
      AND d.PIPELINE='Classic'
      AND d._DELETED_TIMESTAMP IS NULL
      AND d.ARCHIVED = FALSE
      AND d.DEAL_CREATED_DATE >= '2025-06-01'
      AND d.DEAL_GEO IN ('America', 'EMEA')
      AND d.DEAL_TEAM_NAME IN ('US Ent', 'US MM', 'EMEA Ent', 'EMEA MM')
      AND d.DEAL_TOTAL_ARR > 0
    GROUP BY 1,2,3,4,5,6,7,8,9,10,11
    HAVING call_count < 10
),
ranked AS (
    SELECT *,
        CASE 
            WHEN DEAL_TEAM_NAME IN ('US Ent', 'EMEA Ent') AND DEAL_TOTAL_ARR >= 150000 THEN 'High ARR'
            WHEN DEAL_TEAM_NAME IN ('US Ent', 'EMEA Ent') AND DEAL_TOTAL_ARR < 150000 THEN 'Low ARR'
            WHEN DEAL_TEAM_NAME IN ('US MM', 'EMEA MM') AND DEAL_TOTAL_ARR >= 75000 THEN 'High ARR'
            ELSE 'Low ARR'
        END AS arr_bucket,
        ROW_NUMBER() OVER (
            PARTITION BY DEAL_TEAM_NAME, 
                CASE 
                    WHEN DEAL_TEAM_NAME IN ('US Ent', 'EMEA Ent') AND DEAL_TOTAL_ARR >= 150000 THEN 'High'
                    WHEN DEAL_TEAM_NAME IN ('US MM', 'EMEA MM') AND DEAL_TOTAL_ARR >= 75000 THEN 'High'
                    ELSE 'Low' 
                END
            ORDER BY call_count DESC, DEAL_CLOSED_DATE DESC
        ) AS rn
    FROM deals_with_calls
)
SELECT 
    SK_DEAL,
    DEAL_NAME,
    DEAL_TEAM_NAME,
    DEAL_GEO,
    'Lost' AS outcome,
    DEAL_TOTAL_ARR,
    arr_bucket,
    DEAL_CLOSED_DATE,
    CLOSED_LOST_REASON,
    SALES_CYCLE_DAYS,
    call_count
FROM ranked
WHERE rn <= 5
ORDER BY DEAL_TEAM_NAME, arr_bucket DESC, DEAL_TOTAL_ARR DESC
LIMIT 40;

-- Open deals classified as IDP or SDLC via Gong call titles, diverse across teams/stages/ARR
WITH open_deals_with_use_case AS (
    SELECT 
        d.SK_DEAL,
        d.DEAL_NAME,
        d.DEAL_TEAM_NAME,
        d.DEAL_GEO,
        d.DEAL_TOTAL_ARR,
        d.DEAL_STAGE,
        d.DEAL_CREATED_DATE,
        COUNT(c.SK_CONVERSATION) AS call_count,
        COUNT(CASE WHEN c.TITLE ILIKE '%IDP%' OR c.TITLE ILIKE '%internal developer%' 
                        OR c.TITLE ILIKE '%developer portal%' OR c.TITLE ILIKE '%portal%'
                        OR c.TITLE ILIKE '%service catalog%' OR c.TITLE ILIKE '%scorecard%' 
                        OR c.TITLE ILIKE '%self-service%' THEN 1 END) AS idp_calls,
        COUNT(CASE WHEN c.TITLE ILIKE '%SDLC%' OR c.TITLE ILIKE '%software delivery%' 
                        OR c.TITLE ILIKE '%CI/CD%' OR c.TITLE ILIKE '%agentic%' 
                        OR c.TITLE ILIKE '%AEP%' OR c.TITLE ILIKE '%golden path%' THEN 1 END) AS sdlc_calls
    FROM PORT_ANALYTICS_PROD.DWH.FACT_DEALS d
    JOIN PORT_ANALYTICS_PROD.DWH.FACT_CALL c
        ON ARRAY_CONTAINS(d.SK_DEAL::VARIANT, c.ASSOCIATED_DEAL)
    WHERE d.IS_CLOSED = FALSE
      AND d.DEAL_TYPE = 'newbusiness'
      AND d.PIPELINE = 'Classic'
      AND d._DELETED_TIMESTAMP IS NULL
      AND d.ARCHIVED = FALSE
      AND d.DEAL_TOTAL_ARR > 0
    --   AND d.DEAL_GEO IN ('America', 'EMEA')
    --   AND d.DEAL_TEAM_NAME IN ('US Ent', 'US MM', 'EMEA Ent', 'EMEA MM')
      AND d.DEAL_STAGE IN ('Business Validation', 'Business Case Confirmation', 'Formal Pilot')
      AND d.DEAL_NAME NOT ILIKE '%Nationwide%'
      AND d.DEAL_NAME NOT ILIKE '%Deutsche Bank%'
      AND d.DEAL_NAME NOT ILIKE '%IKEA%'
    GROUP BY 1,2,3,4,5,6,7
    HAVING call_count <= 15 AND (idp_calls > 0 OR sdlc_calls > 0)
),
classified AS (
    SELECT *,
        CASE WHEN idp_calls > 0 AND sdlc_calls > 0 THEN 'Both'
             WHEN idp_calls > 0 THEN 'IDP'
             ELSE 'SDLC' END AS use_case
    FROM open_deals_with_use_case
),
ranked AS (
    SELECT *,
        ROW_NUMBER() OVER (
            PARTITION BY use_case
            ORDER BY call_count DESC
        ) AS rn
    FROM classified
)
SELECT 
    SK_DEAL,
    DEAL_NAME,
    DEAL_TEAM_NAME,
    DEAL_GEO,
    DEAL_STAGE,
    DEAL_TOTAL_ARR,
    DEAL_CREATED_DATE,
    call_count,
    use_case,
    idp_calls,
    sdlc_calls
FROM ranked
WHERE rn <= 4
ORDER BY use_case, call_count DESC
LIMIT 10;




