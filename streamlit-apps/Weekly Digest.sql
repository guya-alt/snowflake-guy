WITH weeks AS (
  SELECT
    DATE_TRUNC('WEEK', DATEADD(WEEK, -(ROW_NUMBER() OVER (ORDER BY NULL) - 1), DATE_TRUNC('WEEK', CURRENT_DATE))) AS week_start,
    DATEADD(DAY, 6, DATE_TRUNC('WEEK', DATEADD(WEEK, -(ROW_NUMBER() OVER (ORDER BY NULL) - 1), DATE_TRUNC('WEEK', CURRENT_DATE)))) AS week_end
  FROM TABLE(GENERATOR(ROWCOUNT => 16))
),

deal_metrics AS (
  SELECT
    w.week_start,
    w.week_end,
    -- Net New ARR
    SUM(CASE WHEN deal_stage IN ('Closed Won', 'Churn') AND deal_closed_date BETWEEN w.week_start AND w.week_end THEN deal_net_new_arr ELSE 0 END) AS net_new_arr,
    -- OPP ARR
    SUM(CASE WHEN qualified_date IS NOT NULL AND deal_total_arr > 0 AND qualified_date BETWEEN w.week_start AND w.week_end THEN deal_total_arr ELSE 0 END) AS opp_arr,
    -- Meetings
    COUNT(CASE WHEN sk_sales_owner IS NOT NULL AND deal_created_date BETWEEN w.week_start AND w.week_end THEN 1 END) AS meetings_count,
    -- Won ARR
    SUM(CASE WHEN deal_stage = 'Closed Won' AND deal_closed_date BETWEEN w.week_start AND w.week_end THEN deal_net_new_arr ELSE 0 END) AS won_arr
  FROM weeks w
  LEFT JOIN PORT_ANALYTICS_PROD.DWH.FACT_DEALS d
    ON (d.deal_closed_date BETWEEN w.week_start AND w.week_end
     OR d.deal_created_date BETWEEN w.week_start AND w.week_end
     OR d.qualified_date BETWEEN w.week_start AND w.week_end)
  LEFT JOIN PORT_ANALYTICS_PROD.DWH.DIM_COMPANY c ON d.sk_company = c.sk_company
  WHERE COALESCE(c.company_name, '') NOT ILIKE '%test%'
    AND COALESCE(c.company_name, '') != 'Port'
  GROUP BY w.week_start, w.week_end
),

new_signup AS (
  SELECT
    w.week_start,
    w.week_end,
    COUNT(DISTINCT o.org_id) AS new_signup_count
  FROM weeks w
  LEFT JOIN PORT_ANALYTICS_PROD.DWH.DIM_ORG o
    ON o.created_at::DATE BETWEEN w.week_start AND w.week_end
   AND o._is_deleted = FALSE
   AND COALESCE(o.org_name, '') NOT ILIKE '%test%'
   AND COALESCE(o.org_name, '') NOT ILIKE '%port.io%'
   AND COALESCE(o.org_name, '') NOT ILIKE 'port%'
  LEFT JOIN PORT_ANALYTICS_PROD.DWH.DIM_USER u
    ON o.owner_sk_user = u.sk_user
   AND NOT u.is_internal
  LEFT JOIN PORT_ANALYTICS_PROD.DWH.DIM_ORG co
    ON o.sk_account = co.sk_account
   AND co.created_at < o.created_at
  WHERE u.sk_user IS NOT NULL
    AND co.org_id IS NULL
  GROUP BY w.week_start, w.week_end
)

SELECT
  d.week_start,
  d.week_end,
  TO_CHAR(d.week_start, 'YYYY-MM-DD') || ' - ' || TO_CHAR(d.week_end, 'YYYY-MM-DD') AS week_label,
  d.net_new_arr,
  d.opp_arr,
  d.meetings_count,
  d.won_arr,
  COALESCE(s.new_signup_count, 0) AS new_signup_count
FROM deal_metrics d
LEFT JOIN new_signup s ON d.week_start = s.week_start
ORDER BY d.week_start DESC;
