-- AM Scorecard: Quarterly NRR per Account Manager (company-level)
-- NRR = Won ARR / Total Base ARR at risk (won + lost), aggregated per company first
WITH company_quarter AS (
    SELECT
        e.DISPLAY_NAME AS account_manager,
        c.COMPANY_NAME,
        f.SK_COMPANY,
        DATE_TRUNC('quarter', f.DEAL_CLOSED_DATE) AS closed_quarter,
        SUM(f.BASE_ARR) AS base_arr_at_risk,
        SUM(CASE WHEN f.IS_WON THEN f.DEAL_TOTAL_ARR ELSE 0 END) AS retained_expanded_arr,
        SUM(CASE WHEN f.IS_WON THEN f.DEAL_NET_NEW_ARR ELSE 0 END) AS net_expansion_arr,
        SUM(CASE WHEN NOT f.IS_WON THEN f.BASE_ARR ELSE 0 END) AS churned_arr
    FROM PORT_ANALYTICS_PROD.DWH.FACT_DEALS f
    JOIN PORT_ANALYTICS_PROD.DWH.DIM_EMPLOYEE e
        ON f.SK_SALES_OWNER = e.SK_EMPLOYEE
    LEFT JOIN PORT_ANALYTICS_PROD.DWH.DIM_COMPANY c
        ON f.SK_COMPANY = c.SK_COMPANY
       AND COALESCE(c.COMPANY_NAME, '') NOT ILIKE '%test%'
       AND COALESCE(c.COMPANY_NAME, '') != 'Port'
       AND c._DELETED_TIMESTAMP_UTC IS NULL
    WHERE f.ARCHIVED = FALSE
      AND f._DELETED_TIMESTAMP IS NULL
      AND f.DEAL_TEAM_NAME = 'AM'
      AND f.IS_CLOSED = TRUE
      AND f.DEAL_CLOSED_DATE >= '2025-01-01'
      AND f.BASE_ARR > 0
    GROUP BY 1, 2, 3, 4
)

SELECT
    account_manager,
    COMPANY_NAME,
    closed_quarter,
    base_arr_at_risk,
    retained_expanded_arr,
    net_expansion_arr,
    churned_arr,
    CASE
        WHEN base_arr_at_risk > 0
        THEN ROUND(retained_expanded_arr / base_arr_at_risk * 100, 1)
    END AS nrr_pct
FROM company_quarter
ORDER BY closed_quarter DESC, account_manager, base_arr_at_risk DESC;
