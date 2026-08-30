WITH open_deals AS (
    SELECT SK_DEAL, DEAL_CRM_ID, DEAL_NAME, SK_COMPANY, SK_SALES_OWNER,
           DEAL_TOTAL_ARR, DEAL_TYPE, QUALIFIED_DATE, DEAL_STAGE, DEAL_TEAM_NAME,
           EVALUATED_COMPETITORS
    FROM PORT_ANALYTICS_PROD.DWH.FACT_DEALS
    WHERE IS_CLOSED = FALSE
      AND DEAL_TYPE = 'newbusiness'
      AND PIPELINE = 'Classic'
      AND QUALIFIED_DATE IS NOT NULL
      AND DEAL_STAGE IN ('SDR / Omitted  Opp', 'SDR Discovery', 'Demo / Presentation ', 'Business Validation', 'Business Case Confirmation', 'Formal Pilot')
),
call_deal AS (
    SELECT
        d.VALUE::STRING AS sk_deal,
        COUNT(DISTINCT fc.SK_CONVERSATION) AS num_calls,
        MAX(fc.EFFECTIVE_START_DATETIME)::DATE AS last_call_date
    FROM PORT_ANALYTICS_PROD.DWH.FACT_CALL fc,
    LATERAL FLATTEN(input => fc.ASSOCIATED_DEAL) d
    WHERE fc.DURATION_SECONDS >= 600
      AND d.VALUE::STRING IN (SELECT SK_DEAL FROM open_deals)
    GROUP BY 1
),
call_deal_conversations AS (
    SELECT
        fc.SK_CONVERSATION,
        d.VALUE::STRING AS sk_deal
    FROM PORT_ANALYTICS_PROD.DWH.FACT_CALL fc,
    LATERAL FLATTEN(input => fc.ASSOCIATED_DEAL) d
    WHERE fc.DURATION_SECONDS >= 600
      AND d.VALUE::STRING IN (SELECT SK_DEAL FROM open_deals)
),
transcript_competitor_mentions AS (
    SELECT
        cd.sk_deal,
        ftc.TRANSCRIPT_CHAPTER_WINDOW AS chapter_text,
        CASE
            WHEN ftc.TRANSCRIPT_CHAPTER_WINDOW ILIKE '%backstage%' OR ftc.TRANSCRIPT_CHAPTER_WINDOW ILIKE '%spotify%' THEN 'Backstage'
            WHEN ftc.TRANSCRIPT_CHAPTER_WINDOW ILIKE ANY ('%opslevel%','%ops level%') THEN 'OpsLevel'
            WHEN ftc.TRANSCRIPT_CHAPTER_WINDOW ILIKE '%cortex%' THEN 'Cortex'
        END AS candidate_competitor
    FROM call_deal_conversations cd
    INNER JOIN PORT_ANALYTICS_PROD.DWH.FACT_TRANSCRIPT_CHAPTER ftc ON cd.SK_CONVERSATION = ftc.SK_CONVERSATION
    WHERE ftc.TRANSCRIPT_CHAPTER_WINDOW ILIKE '%backstage%'
       OR ftc.TRANSCRIPT_CHAPTER_WINDOW ILIKE '%spotify%'
       OR ftc.TRANSCRIPT_CHAPTER_WINDOW ILIKE ANY ('%opslevel%','%ops level%')
       OR ftc.TRANSCRIPT_CHAPTER_WINDOW ILIKE '%cortex%'
),
ai_classified AS (
    SELECT
        sk_deal,
        candidate_competitor,
        AI_CLASSIFY(
            chapter_text,
            [
                candidate_competitor || ' is discussed as a competing product or alternative solution',
                candidate_competitor || ' is mentioned casually, not as a competitor'
            ]
        ):label::STRING AS classification
    FROM transcript_competitor_mentions
),
gong_competitors AS (
    SELECT
        sk_deal,
        ARRAY_AGG(DISTINCT candidate_competitor) AS competitors_arr
    FROM ai_classified
    WHERE classification ILIKE '%competing product%'
    GROUP BY 1
),
hubspot_competitors AS (
    SELECT
        od.SK_DEAL AS sk_deal,
        ARRAY_AGG(
            CASE UPPER(comp.VALUE::STRING)
                WHEN 'BACKSTAGE' THEN 'Backstage'
                WHEN 'OPSLEVEL' THEN 'OpsLevel'
                WHEN 'CORTEX' THEN 'Cortex'
                ELSE NULL
            END
        ) AS competitors_arr
    FROM open_deals od,
    LATERAL FLATTEN(input => od.EVALUATED_COMPETITORS, OUTER => TRUE) comp
    WHERE comp.VALUE IS NOT NULL
    GROUP BY 1
),
deal_competitors AS (
    SELECT
        od.SK_DEAL AS sk_deal,
        ARRAY_TO_STRING(
            ARRAY_DISTINCT(ARRAY_CAT(
                COALESCE(gc.competitors_arr, ARRAY_CONSTRUCT()),
                COALESCE(hc.competitors_arr, ARRAY_CONSTRUCT())
            )), ', '
        ) AS competitors
    FROM open_deals od
    LEFT JOIN gong_competitors gc ON od.SK_DEAL = gc.sk_deal
    LEFT JOIN hubspot_competitors hc ON od.SK_DEAL = hc.sk_deal
)
SELECT
    od.DEAL_TEAM_NAME AS hubspot_team,
    od.DEAL_NAME,
    c.COMPANY_NAME,
    od.DEAL_TOTAL_ARR AS arr,
    e.DISPLAY_NAME AS deal_owner,
    od.QUALIFIED_DATE AS qualify_date,
    od.DEAL_STAGE AS current_stage,
    cd_filter.num_calls,
    cd_filter.last_call_date,
    dc.competitors
FROM open_deals od
LEFT JOIN PORT_ANALYTICS_PROD.DWH.DIM_EMPLOYEE e ON od.SK_SALES_OWNER = e.SK_EMPLOYEE
LEFT JOIN PORT_ANALYTICS_PROD.DWH.DIM_COMPANY c
    ON od.SK_COMPANY = c.SK_COMPANY
   AND COALESCE(c.COMPANY_NAME, '') NOT ILIKE '%test%'
   AND COALESCE(c.COMPANY_NAME, '') != 'Port'
   AND c._IS_DELETED = FALSE
   AND c.ARCHIVED = FALSE
INNER JOIN call_deal cd_filter ON od.SK_DEAL = cd_filter.sk_deal
LEFT JOIN deal_competitors dc ON od.SK_DEAL = dc.sk_deal
WHERE dc.competitors IS NOT NULL AND dc.competitors != ''
ORDER BY od.QUALIFIED_DATE DESC
