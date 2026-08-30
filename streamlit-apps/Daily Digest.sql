WITH params AS (
  SELECT
    CURRENT_DATE - 1                                            AS yesterday,
    DATE_TRUNC('QUARTER', CURRENT_DATE - 1)                     AS qtd_start,
    DATEADD(YEAR, -1, DATE_TRUNC('QUARTER', CURRENT_DATE - 1))  AS qtd_ly_start,
    DATEADD(YEAR, -1, CURRENT_DATE - 1)                         AS qtd_ly_end,
    DATEADD(MONTH, -15, CURRENT_DATE)                           AS scan_boundary
),

arr AS (
  SELECT
    SUM(arr) AS total_arr,
    COUNT(DISTINCT sk_company) AS total_customers
  FROM PORT_ANALYTICS_PROD.DWH.DIM_COMPANY
  WHERE is_customer = TRUE AND _is_deleted = FALSE AND archived = FALSE AND arr > 0
),

deal_metrics AS (
  SELECT
    -- Net New ARR
    SUM(CASE WHEN deal_stage IN ('Closed Won', 'Churn') AND deal_closed_date = p.yesterday THEN deal_net_new_arr ELSE 0 END) AS net_new_arr_daily,
    SUM(CASE WHEN deal_stage IN ('Closed Won', 'Churn') AND deal_closed_date BETWEEN p.qtd_start AND p.yesterday THEN deal_net_new_arr ELSE 0 END) AS net_new_arr_qtd,
    SUM(CASE WHEN deal_stage IN ('Closed Won', 'Churn') AND deal_closed_date BETWEEN p.qtd_ly_start AND p.qtd_ly_end THEN deal_net_new_arr ELSE 0 END) AS net_new_arr_qtd_ly,

    -- OPP ARR (qualified_date IS NOT NULL & amount > 0)
    SUM(CASE WHEN qualified_date IS NOT NULL AND deal_total_arr > 0 AND qualified_date = p.yesterday THEN deal_total_arr ELSE 0 END) AS opp_daily_arr,
    SUM(CASE WHEN qualified_date IS NOT NULL AND deal_total_arr > 0 AND qualified_date BETWEEN p.qtd_start AND p.yesterday THEN deal_total_arr ELSE 0 END) AS opp_qtd_arr,
    SUM(CASE WHEN qualified_date IS NOT NULL AND deal_total_arr > 0 AND qualified_date BETWEEN p.qtd_ly_start AND p.qtd_ly_end THEN deal_total_arr ELSE 0 END) AS opp_qtd_ly_arr,

    -- Meetings (deals created with sales owner)
    COUNT(CASE WHEN sk_sales_owner IS NOT NULL AND deal_created_date = p.yesterday THEN 1 END) AS meetings_daily_count,
    COUNT(CASE WHEN sk_sales_owner IS NOT NULL AND deal_created_date BETWEEN p.qtd_start AND p.yesterday THEN 1 END) AS meetings_qtd_count,
    COUNT(CASE WHEN sk_sales_owner IS NOT NULL AND deal_created_date BETWEEN p.qtd_ly_start AND p.qtd_ly_end THEN 1 END) AS meetings_qtd_ly_count,

    -- Won ARR (any Closed Won)
    SUM(CASE WHEN deal_stage = 'Closed Won' AND deal_closed_date = p.yesterday THEN deal_net_new_arr ELSE 0 END) AS won_daily_arr,
    SUM(CASE WHEN deal_stage = 'Closed Won' AND deal_closed_date BETWEEN p.qtd_start AND p.yesterday THEN deal_net_new_arr ELSE 0 END) AS won_qtd_arr,
    SUM(CASE WHEN deal_stage = 'Closed Won' AND deal_closed_date BETWEEN p.qtd_ly_start AND p.qtd_ly_end THEN deal_net_new_arr ELSE 0 END) AS won_qtd_ly_arr

  FROM PORT_ANALYTICS_PROD.DWH.FACT_DEALS d
  LEFT JOIN PORT_ANALYTICS_PROD.DWH.DIM_COMPANY c ON d.sk_company = c.sk_company
  CROSS JOIN params p
  WHERE (d.deal_closed_date >= p.scan_boundary
     OR d.deal_created_date >= p.scan_boundary
     OR d.qualified_date >= p.scan_boundary)
    AND COALESCE(c.company_name, '') NOT ILIKE '%test%'
    AND COALESCE(c.company_name, '') != 'Port'
),

new_signup AS (
  SELECT
    COUNT(DISTINCT CASE WHEN o.created_at::DATE = p.yesterday THEN o.org_id END) AS new_signup_daily,
    COUNT(DISTINCT CASE WHEN o.created_at::DATE BETWEEN p.qtd_start AND p.yesterday THEN o.org_id END) AS new_signup_qtd,
    COUNT(DISTINCT CASE WHEN o.created_at::DATE BETWEEN p.qtd_ly_start AND p.qtd_ly_end THEN o.org_id END) AS new_signup_qtd_ly
  FROM PORT_ANALYTICS_PROD.DWH.DIM_ORG o
  JOIN PORT_ANALYTICS_PROD.DWH.DIM_USER u ON o.owner_sk_user = u.sk_user
  LEFT JOIN PORT_ANALYTICS_PROD.DWH.DIM_ORG co ON o.sk_account = co.sk_account AND co.created_at < o.created_at
  CROSS JOIN params p
  WHERE o._is_deleted = FALSE
    AND o.created_at::DATE >= p.scan_boundary
    AND COALESCE(o.org_name, '') NOT ILIKE '%test%'
    AND COALESCE(o.org_name, '') NOT ILIKE '%port.io%'
    AND COALESCE(o.org_name, '') NOT ILIKE 'port%'
    AND NOT u.is_internal
    AND co.org_id IS NULL
)

SELECT
  'Daily Digest ' || TO_CHAR(p.yesterday, 'YYYY-MM-DD') || ' (' || DAYNAME(p.yesterday) || ')' AS header,
  total_arr,
  total_customers,
  net_new_arr_daily,
  net_new_arr_qtd,
  net_new_arr_qtd_ly,
  opp_daily_arr,
  opp_qtd_arr,
  opp_qtd_ly_arr,
  meetings_daily_count,
  meetings_qtd_count,
  meetings_qtd_ly_count,
  won_daily_arr,
  won_qtd_arr,
  won_qtd_ly_arr,
  new_signup_daily,
  new_signup_qtd,
  new_signup_qtd_ly
FROM deal_metrics, arr, new_signup, params p;


