-- Closed-lost deals since H2 2025, latest 100 with a filled CLOSED_LOST_REASON,
-- excluding deals closed in the last 2 days (settlement buffer).

WITH lost_deals AS (
    SELECT
        d.SK_DEAL,
        d.DEAL_CRM_ID,
        d.DEAL_NAME,
        dc.COMPANY_NAME,
        d.PIPELINE,
        d.DEAL_TYPE,
        d.DEAL_TEAM_NAME,
        d.DEAL_STAGE,
        d.DEAL_CLOSED_DATE,
        d.DEAL_CREATED_DATE,
        d.SALES_CYCLE_DAYS,
        d.DEAL_TOTAL_ARR,
        d.DEAL_NET_NEW_ARR,
        d.CLOSED_LOST_REASON,
        sales_e.DISPLAY_NAME AS SALES_OWNER
    FROM PORT_ANALYTICS_PROD.DWH.FACT_DEALS d
    LEFT JOIN PORT_ANALYTICS_PROD.DWH.DIM_COMPANY dc
           ON d.SK_COMPANY = dc.SK_COMPANY
          AND COALESCE(dc.COMPANY_NAME, '') NOT ILIKE '%test%'
          AND COALESCE(dc.COMPANY_NAME, '') != 'Port'
          AND dc._IS_DELETED = FALSE
          AND dc.ARCHIVED    = FALSE
    LEFT JOIN PORT_ANALYTICS_PROD.DWH.DIM_EMPLOYEE sales_e ON d.SK_SALES_OWNER = sales_e.SK_EMPLOYEE
    WHERE d.IS_CLOSED = TRUE
      AND d.DEAL_TEAM_NAME IS NOT NULL AND d.DEAL_TEAM_NAME NOT ILIKE 'sdr%'
      AND d.DEAL_TOTAL_ARR IS NOT NULL
      AND d.DEAL_TYPE = 'newbusiness'
      AND d.CLOSED_LOST_REASON NOT IN ('no_show', 'Unable to connect', 'Other')
      AND d.IS_WON    = FALSE
      AND d.CLOSED_LOST_REASON IS NOT NULL AND d.CLOSED_LOST_REASON != ''
      AND d.DEAL_CLOSED_DATE >= DATE '2025-07-01'
      AND d.DEAL_CLOSED_DATE <  DATEADD('day', -2, CURRENT_DATE)
    QUALIFY ROW_NUMBER() OVER (ORDER BY d.DEAL_CLOSED_DATE DESC) <= 100
),
lost_deals_cat AS (
    SELECT *,
        ARRAY_DISTINCT(ARRAY_COMPACT(ARRAY_CONSTRUCT(
            IFF(CLOSED_LOST_REASON ILIKE '%no_show%'
                OR CLOSED_LOST_REASON ILIKE '%unable to connect%'
                OR CLOSED_LOST_REASON ILIKE '%UNQ%',                'No Engagement', NULL),
            IFF(CLOSED_LOST_REASON ILIKE '%bad timing%'
                OR CLOSED_LOST_REASON ILIKE '%early stage%',         'Timing',        NULL),
            IFF(CLOSED_LOST_REASON ILIKE '%not right%'
                OR CLOSED_LOST_REASON ILIKE '%persona%'
                OR CLOSED_LOST_REASON ILIKE '%consultant%'
                OR CLOSED_LOST_REASON ILIKE '%partnership%',         'Fit',           NULL),
            IFF(CLOSED_LOST_REASON ILIKE '%no value%'
                OR CLOSED_LOST_REASON ILIKE '%product%'
                OR CLOSED_LOST_REASON ILIKE '%freemium%'
                OR CLOSED_LOST_REASON ILIKE '%on-prem%',             'Value/Product', NULL),
            IFF(CLOSED_LOST_REASON ILIKE '%competition%'
                OR CLOSED_LOST_REASON ILIKE '%internal build%',      'Competitive',   NULL),
            IFF(CLOSED_LOST_REASON ILIKE '%budget%'
                OR CLOSED_LOST_REASON ILIKE '%price%',               'Commercial',    NULL),
            IFF(CLOSED_LOST_REASON ILIKE '%champion%'
                OR CLOSED_LOST_REASON ILIKE '%churn%',               'Sponsorship',   NULL),
            IFF(CLOSED_LOST_REASON ILIKE '%security%',               'Security',      NULL)
        ))) AS HS_LOST_CATEGORIES
    FROM lost_deals
),
recent_calls AS (
    SELECT
        SK_DEAL,
        COUNT(*)              AS CALLS_ANALYZED,
        MAX(CALL_DATE)        AS LATEST_CALL_DATE,
        MIN(CALL_DATE)        AS EARLIEST_ANALYZED_CALL_DATE,
        LEFT(
            LISTAGG(SPOTLIGHT_TEXT, '\n--- next call ---\n')
                WITHIN GROUP (ORDER BY rn ASC),
            4000
        )                                                           AS SPOTLIGHT_TEXT,
        ARRAY_AGG(SK_CONVERSATION) WITHIN GROUP (ORDER BY rn ASC)   AS ANALYZED_SK_CONVERSATIONS
    FROM (
        SELECT
            df.ASSOCIATED_SK AS SK_DEAL,
            f.SK_CONVERSATION,
            f.EFFECTIVE_START_DATETIME::DATE AS CALL_DATE,
            CONCAT_WS('\n',
                NULLIF(COALESCE(f.CALL_SPOTLIGHT_BRIEF, ''), ''),
                NULLIF(COALESCE(ARRAY_TO_STRING(f.CALL_SPOTLIGHT_KEY_POINTS, '\n'), ''), ''),
                NULLIF(COALESCE(f.CALL_SPOTLIGHT_NEXT_STEPS, ''), '')
            ) AS SPOTLIGHT_TEXT,
            ROW_NUMBER() OVER (PARTITION BY df.ASSOCIATED_SK
                               ORDER BY f.EFFECTIVE_START_DATETIME DESC) AS rn
        FROM PORT_ANALYTICS_PROD.DWH.MV_CALL_ASSOCIATED_DEAL_FLAT df
        JOIN PORT_ANALYTICS_PROD.DWH.FACT_CALL     f  ON df.SK_CONVERSATION = f.SK_CONVERSATION
        JOIN lost_deals_cat                        ld ON ld.SK_DEAL         = df.ASSOCIATED_SK
        WHERE f.EFFECTIVE_START_DATETIME <= ld.DEAL_CLOSED_DATE
    )
    WHERE rn <= 3
      AND LENGTH(TRIM(SPOTLIGHT_TEXT)) > 0
    GROUP BY SK_DEAL
),
gong_classified AS (
    SELECT
        SK_DEAL,
        CALLS_ANALYZED,
        LATEST_CALL_DATE,
        EARLIEST_ANALYZED_CALL_DATE,
        ANALYZED_SK_CONVERSATIONS,
        SPOTLIGHT_TEXT,
        AI_CLASSIFY(
            SPOTLIGHT_TEXT,
            ['No Engagement','Timing','Fit','Value/Product','Competitive',
             'Commercial','Sponsorship','Security','Other'],
            {'output_mode': 'multi'}
        ):labels::ARRAY AS GONG_LOST_CATEGORY
    FROM recent_calls
),
ai_reason_judgment AS (
    SELECT
        ld.SK_DEAL,
        LOWER(TRIM(AI_COMPLETE(
            'claude-4-sonnet',
            'You are comparing the stated HubSpot closed-lost reason for a sales deal to the actual loss reason as it appears in the recent Gong call transcripts/summaries.' ||
            ' Ignore any predefined categories or taxonomy — judge on the raw text only.' ||
            ' Does the transcript-derived loss reason match / support the stated HubSpot lost reason?' ||
            ' Respond with exactly one word: yes, no, or unclear.' ||
            ' Stated HubSpot CLOSED_LOST_REASON: "' || ld.CLOSED_LOST_REASON || '".' ||
            ' Concatenated Gong Spotlight summary of the last calls:\n' || gc.SPOTLIGHT_TEXT
        ))) AS AI_REASON_SUPPORTED
    FROM lost_deals_cat ld
    JOIN gong_classified gc ON gc.SK_DEAL = ld.SK_DEAL
    WHERE gc.SPOTLIGHT_TEXT IS NOT NULL
)
SELECT
    ld.SK_DEAL,
    ld.DEAL_CRM_ID,
    ld.DEAL_NAME,
    ld.COMPANY_NAME,
    ld.PIPELINE,
    ld.DEAL_TYPE,
    ld.DEAL_TEAM_NAME,
    ld.DEAL_STAGE,
    ld.DEAL_CLOSED_DATE,
    ld.DEAL_CREATED_DATE,
    ld.SALES_CYCLE_DAYS,
    ld.DEAL_TOTAL_ARR,
    ld.DEAL_NET_NEW_ARR,
    ld.SALES_OWNER,
    ld.CLOSED_LOST_REASON,
    ld.HS_LOST_CATEGORIES,
    gc.CALLS_ANALYZED,
    gc.LATEST_CALL_DATE,
    gc.EARLIEST_ANALYZED_CALL_DATE,
    gc.ANALYZED_SK_CONVERSATIONS,
    gc.GONG_LOST_CATEGORY,
    IFF(gc.GONG_LOST_CATEGORY IS NULL, NULL,
        ARRAYS_OVERLAP(
            gc.GONG_LOST_CATEGORY,
            IFF(ARRAY_SIZE(ld.HS_LOST_CATEGORIES) = 0,
                ARRAY_CONSTRUCT('Other'),
                ld.HS_LOST_CATEGORIES)
        )) AS CATEGORY_MATCH,
    j.AI_REASON_SUPPORTED
FROM lost_deals_cat ld
LEFT JOIN gong_classified gc ON gc.SK_DEAL = ld.SK_DEAL
LEFT JOIN ai_reason_judgment j ON j.SK_DEAL = ld.SK_DEAL
WHERE COALESCE(gc.CALLS_ANALYZED, 0) > 0
ORDER BY ld.DEAL_CLOSED_DATE DESC;