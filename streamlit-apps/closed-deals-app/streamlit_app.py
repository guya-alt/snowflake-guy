import os
import streamlit as st

st.set_page_config(page_title="NewBiz Closed Lost Analysis", layout="wide")
st.title("NewBiz Closed Lost Analysis")

conn = st.connection("snowflake", ttl=os.getenv("SNOWFLAKE_CONNECTION_TTL"))

if st.button("Load Data"):
    with st.spinner("Querying..."):
        df = conn.query("""
            SELECT
                close_date_quarter,
                Deal_Stage_Before_Closed,
                COUNT(DISTINCT deal_name) AS deal_count,
                ROUND(
                    COUNT(DISTINCT deal_name) * 100.0
                    / SUM(COUNT(DISTINCT deal_name)) OVER (PARTITION BY close_date_quarter),
                    2
                ) AS pct_of_closed_deals
            FROM "PORT_ANALYTICS_DEV"."SALES_ANALYTICS"."CLOSED_DEALS_JUN26"
            WHERE deal_stage = 'Closed Lost'
              AND (date_entered_closed_won_classic IS NOT NULL OR date_entered_closed_lost_classic IS NOT NULL)
              AND qualified_date IS NOT NULL
              AND deal_type = 'New Business'
            GROUP BY ALL
            ORDER BY 1, 2
        """)
        st.session_state["deals_data"] = df

        df_winrate = conn.query("""
            SELECT
                close_date_quarter,
                COUNT(DISTINCT CASE WHEN deal_stage = 'Closed Won' THEN deal_name END) AS closed_won_count,
                COUNT(DISTINCT CASE WHEN deal_stage = 'Closed Lost' THEN deal_name END) AS closed_lost_count,
                COUNT(DISTINCT deal_name) AS total_closed,
                ROUND(
                    COUNT(DISTINCT CASE WHEN deal_stage = 'Closed Won' THEN deal_name END) * 100.0
                    / NULLIF(COUNT(DISTINCT deal_name), 0),
                    2
                ) AS win_rate_pct,
                SUM(CASE WHEN deal_stage = 'Closed Won' THEN amount ELSE 0 END) AS won_net_arr,
                SUM(CASE WHEN deal_stage = 'Closed Lost' THEN amount ELSE 0 END) AS lost_net_arr
            FROM "PORT_ANALYTICS_DEV"."SALES_ANALYTICS"."CLOSED_DEALS_JUN26"
            WHERE (date_entered_closed_won_classic IS NOT NULL OR date_entered_closed_lost_classic IS NOT NULL)
              AND qualified_date IS NOT NULL
              AND deal_type = 'New Business'
            GROUP BY close_date_quarter
            ORDER BY close_date_quarter
        """)
        st.session_state["winrate_data"] = df_winrate

        df_pilot = conn.query("""
            SELECT
                close_date_quarter,
                poc_indication,
                COUNT(DISTINCT CASE WHEN deal_stage = 'Closed Lost' THEN deal_name END) AS lost_count,
                COUNT(DISTINCT CASE WHEN deal_stage = 'Closed Won' THEN deal_name END) AS won_count,
                COUNT(DISTINCT deal_name) AS total_deals,
                ROUND(
                    COUNT(DISTINCT CASE WHEN deal_stage = 'Closed Lost' THEN deal_name END) * 100.0
                    / NULLIF(COUNT(DISTINCT deal_name), 0),
                    2
                ) AS lost_rate_pct
            FROM "PORT_ANALYTICS_DEV"."SALES_ANALYTICS"."CLOSED_DEALS_JUN26"
            WHERE poc_indication IN ('With POC', 'No POC')
              AND (date_entered_closed_won_classic IS NOT NULL OR date_entered_closed_lost_classic IS NOT NULL)
              AND qualified_date IS NOT NULL
              AND deal_type = 'New Business'
            GROUP BY close_date_quarter, poc_indication
            ORDER BY close_date_quarter, poc_indication
        """)
        st.session_state["pilot_data"] = df_pilot

        df_sweetspot = conn.query("""
            WITH parsed AS (
                SELECT
                    deal_name,
                    deal_stage,
                    SPLIT_PART(formal_pilot_duration_hhmmss, ':', 1)::INT / 24 AS pilot_days
                FROM "PORT_ANALYTICS_DEV"."SALES_ANALYTICS"."CLOSED_DEALS_JUN26"
                WHERE formal_pilot_duration_hhmmss IS NOT NULL
                  AND formal_pilot_duration_hhmmss != '0:00:00'
                  AND SPLIT_PART(formal_pilot_duration_hhmmss, ':', 1)::INT > 0
                  AND (date_entered_closed_won_classic IS NOT NULL OR date_entered_closed_lost_classic IS NOT NULL)
                  AND qualified_date IS NOT NULL
                  AND deal_type = 'New Business'
            )
            SELECT
                CASE
                    WHEN pilot_days <= 14 THEN '0–14d'
                    WHEN pilot_days <= 30 THEN '15–30d'
                    WHEN pilot_days <= 45 THEN '31–45d'
                    WHEN pilot_days <= 60 THEN '46–60d'
                    WHEN pilot_days <= 90 THEN '61–90d'
                    ELSE '90d+'
                END AS pilot_bucket,
                CASE
                    WHEN pilot_days <= 14 THEN 1
                    WHEN pilot_days <= 30 THEN 2
                    WHEN pilot_days <= 45 THEN 3
                    WHEN pilot_days <= 60 THEN 4
                    WHEN pilot_days <= 90 THEN 5
                    ELSE 6
                END AS bucket_order,
                COUNT(DISTINCT deal_name) AS deal_count,
                COUNT(DISTINCT CASE WHEN deal_stage = 'Closed Lost' THEN deal_name END) AS lost_count,
                ROUND(
                    COUNT(DISTINCT CASE WHEN deal_stage = 'Closed Lost' THEN deal_name END) * 100.0
                    / NULLIF(COUNT(DISTINCT deal_name), 0),
                    2
                ) AS lost_rate_pct
            FROM parsed
            GROUP BY pilot_bucket, bucket_order
            ORDER BY bucket_order
        """)
        st.session_state["sweetspot_data"] = df_sweetspot

        df_poc_loss = conn.query("""
            SELECT
                close_date_quarter,
                COALESCE(poc_indication, 'Unknown') AS poc_indication,
                COUNT(DISTINCT CASE WHEN deal_stage = 'Closed Lost' THEN deal_name END) AS lost_count,
                COUNT(DISTINCT CASE WHEN deal_stage IN ('Closed Won', 'Closed Lost') THEN deal_name END) AS total_count,
                ROUND(
                    COUNT(DISTINCT CASE WHEN deal_stage = 'Closed Lost' THEN deal_name END) * 100.0
                    / NULLIF(
                        COUNT(DISTINCT CASE WHEN deal_stage IN ('Closed Won', 'Closed Lost') THEN deal_name END),
                        0
                    ),
                    2
                ) AS loss_rate_pct
            FROM "PORT_ANALYTICS_DEV"."SALES_ANALYTICS"."CLOSED_DEALS_JUN26"
            WHERE poc_indication IN ('With POC', 'No POC')
              AND (date_entered_closed_won_classic IS NOT NULL OR date_entered_closed_lost_classic IS NOT NULL)
              AND qualified_date IS NOT NULL
              AND deal_type = 'New Business'
            GROUP BY close_date_quarter, poc_indication
            ORDER BY close_date_quarter, poc_indication
        """)
        st.session_state["poc_loss_data"] = df_poc_loss

        df_bucket_quarter = conn.query("""
            WITH parsed AS (
                SELECT
                    close_date_quarter,
                    deal_name,
                    deal_stage,
                    SPLIT_PART(formal_pilot_duration_hhmmss, ':', 1)::INT / 24 AS pilot_days
                FROM "PORT_ANALYTICS_DEV"."SALES_ANALYTICS"."CLOSED_DEALS_JUN26"
                WHERE formal_pilot_duration_hhmmss IS NOT NULL
                  AND formal_pilot_duration_hhmmss != '0:00:00'
                  AND SPLIT_PART(formal_pilot_duration_hhmmss, ':', 1)::INT > 0
                  AND deal_stage IN ('Closed Won', 'Closed Lost')
                  AND (date_entered_closed_won_classic IS NOT NULL OR date_entered_closed_lost_classic IS NOT NULL)
                  AND qualified_date IS NOT NULL
                  AND deal_type = 'New Business'
            )
            SELECT
                close_date_quarter,
                CASE
                    WHEN pilot_days <= 14  THEN '0-14d'
                    WHEN pilot_days <= 30  THEN '15-30d'
                    WHEN pilot_days <= 45  THEN '31-45d'
                    WHEN pilot_days <= 60  THEN '46-60d'
                    WHEN pilot_days <= 90  THEN '61-90d'
                    ELSE '90d+'
                END AS pilot_bucket,
                CASE
                    WHEN pilot_days <= 14  THEN 1
                    WHEN pilot_days <= 30  THEN 2
                    WHEN pilot_days <= 45  THEN 3
                    WHEN pilot_days <= 60  THEN 4
                    WHEN pilot_days <= 90  THEN 5
                    ELSE 6
                END AS bucket_order,
                ROUND(
                    COUNT(DISTINCT CASE WHEN deal_stage = 'Closed Lost' THEN deal_name END) * 100.0
                    / NULLIF(COUNT(DISTINCT deal_name), 0),
                    2
                ) AS loss_rate_pct,
                COUNT(DISTINCT deal_name) AS deal_count
            FROM parsed
            GROUP BY close_date_quarter, pilot_bucket, bucket_order
            ORDER BY close_date_quarter, bucket_order
        """)
        st.session_state["bucket_quarter_data"] = df_bucket_quarter

        df_poc_to_close = conn.query("""
            SELECT
                close_date_quarter,
                CASE
                    WHEN segment = 'Mid-Market' THEN 'Mid-Market'
                    WHEN segment = 'Enterprise' AND deal_stage = 'Closed Won' THEN 'Enterprise Won'
                    WHEN segment = 'Enterprise' AND deal_stage = 'Closed Lost' THEN 'Enterprise Lost'
                END AS series,
                MEDIAN(DATEDIFF('day', date_entered_formal_pilot_classic, close_date)) AS median_poc_to_close_days,
                COUNT(DISTINCT deal_name) AS deal_count
            FROM "PORT_ANALYTICS_DEV"."SALES_ANALYTICS"."CLOSED_DEALS_JUN26"
            WHERE deal_stage IN ('Closed Won', 'Closed Lost')
              AND date_entered_formal_pilot_classic IS NOT NULL
              AND close_date IS NOT NULL
              AND qualified_date IS NOT NULL
              AND deal_type = 'New Business'
              AND (
    SUBSTR(formal_pilot_duration_hhmmss, 1, POSITION(':', formal_pilot_duration_hhmmss) - 1)::INT * 3600 +
    SUBSTR(formal_pilot_duration_hhmmss, POSITION(':', formal_pilot_duration_hhmmss) + 1, 2)::INT * 60 +
    SUBSTR(formal_pilot_duration_hhmmss, REGEXP_INSTR(formal_pilot_duration_hhmmss, ':', 1, 2) + 1, 2)::INT
  ) > 86400
            GROUP BY close_date_quarter, series
            HAVING series IS NOT NULL and count(distinct deal_name)>2
            ORDER BY close_date_quarter, series
        """)
        st.session_state["poc_to_close_data"] = df_poc_to_close

        df_velocity = conn.query("""
            SELECT
                close_date_quarter,
                deal_stage_before_closed,
                MEDIAN(DATEDIFF('day', qualified_date, close_date)) AS median_days,
                COUNT(DISTINCT deal_name) AS deal_count
            FROM "PORT_ANALYTICS_DEV"."SALES_ANALYTICS"."CLOSED_DEALS_JUN26"
            WHERE deal_stage = 'Closed Lost'
              AND qualified_date IS NOT NULL
              AND close_date IS NOT NULL
              AND (date_entered_closed_won_classic IS NOT NULL OR date_entered_closed_lost_classic IS NOT NULL)
              AND deal_type = 'New Business'
            GROUP BY close_date_quarter, deal_stage_before_closed
            ORDER BY close_date_quarter, deal_stage_before_closed
        """)
        st.session_state["velocity_data"] = df_velocity

        df_staleness = conn.query("""
            SELECT
                close_date_quarter,
                AVG(COALESCE(SPLIT_PART(cumulative_time_in_demo_presentation_classic_hhmmss, ':', 1)::INT, 0) / 24.0) AS demo_presentation_days,
                AVG(COALESCE(SPLIT_PART(cumulative_time_in_business_validation_classic_hhmmss, ':', 1)::INT, 0) / 24.0) AS business_validation_days,
                AVG(COALESCE(SPLIT_PART(cumulative_time_in_formal_pilot_classic_hhmmss, ':', 1)::INT, 0) / 24.0) AS formal_pilot_days,
                AVG(COALESCE(SPLIT_PART(cumulative_time_in_negotiation_legal_classic_hhmmss, ':', 1)::INT, 0) / 24.0) AS negotiation_legal_days
            FROM "PORT_ANALYTICS_DEV"."SALES_ANALYTICS"."CLOSED_DEALS_JUN26"
            WHERE deal_stage = 'Closed Lost'
              AND (date_entered_closed_won_classic IS NOT NULL OR date_entered_closed_lost_classic IS NOT NULL)
              AND qualified_date IS NOT NULL
              AND deal_type = 'New Business'
            GROUP BY close_date_quarter
            ORDER BY close_date_quarter
        """)
        st.session_state["staleness_data"] = df_staleness

        df_team_loss = conn.query("""
            SELECT
                close_date_quarter,
                hubspot_team,
                COUNT(DISTINCT CASE WHEN deal_stage = 'Closed Lost' THEN deal_name END) AS lost_count,
                COUNT(DISTINCT CASE WHEN deal_stage IN ('Closed Won', 'Closed Lost') THEN deal_name END) AS total_count,
                ROUND(
                    COUNT(DISTINCT CASE WHEN deal_stage = 'Closed Lost' THEN deal_name END) * 100.0
                    / NULLIF(
                        COUNT(DISTINCT CASE WHEN deal_stage IN ('Closed Won', 'Closed Lost') THEN deal_name END),
                        0
                    ),
                    2
                ) AS loss_rate_pct
            FROM "PORT_ANALYTICS_DEV"."SALES_ANALYTICS"."CLOSED_DEALS_JUN26"
            WHERE hubspot_team IS NOT NULL
              AND (date_entered_closed_won_classic IS NOT NULL OR date_entered_closed_lost_classic IS NOT NULL)
              AND qualified_date IS NOT NULL
              AND deal_type = 'New Business'
            GROUP BY close_date_quarter, hubspot_team
            ORDER BY close_date_quarter, hubspot_team
        """)
        st.session_state["team_loss_data"] = df_team_loss


        df_forecast = conn.query("""
            SELECT
                close_date_quarter,
                COALESCE(forecast_category_before_closed, 'Not forecasted') AS forecast_category,
                COUNT(DISTINCT deal_name) AS lost_deals,
                SUM(amount) AS lost_amount
            FROM "PORT_ANALYTICS_DEV"."SALES_ANALYTICS"."CLOSED_DEALS_JUN26"
            WHERE date_entered_closed_lost_classic IS NOT NULL
              AND (date_entered_closed_won_classic IS NOT NULL OR date_entered_closed_lost_classic IS NOT NULL)
              AND qualified_date IS NOT NULL
              AND deal_type = 'New Business'
            GROUP BY close_date_quarter, forecast_category
            ORDER BY close_date_quarter, forecast_category
        """)
        st.session_state["forecast_data"] = df_forecast

        df_rep_age = conn.query("""
            WITH deal_emp AS (
                SELECT
                    d.deal_name,
                    d.deal_stage,
                    d.close_date,
                    TO_VARCHAR(d.close_date, 'YYYY') || '-Q' || TO_VARCHAR(QUARTER(d.close_date)) AS close_quarter,
                    e.original_start_date,
                    e.display_name,
                    d.deal_owner,
                    CASE WHEN e.display_name IS NULL THEN NULL ELSE DATEDIFF('month', e.original_start_date, d.close_date) END AS rep_tenure_months
                FROM "PORT_ANALYTICS_DEV"."SALES_ANALYTICS"."CLOSED_DEALS_JUN26" d
                LEFT JOIN "PORT_ANALYTICS_DEV"."DWH"."DIM_EMPLOYEE" e
                    ON e.display_name ILIKE REGEXP_REPLACE(TRIM(d.deal_owner), '\\s*\\([^)]*\\)', '')
                WHERE d.deal_stage IN ('Closed Won', 'Closed Lost')
                  AND (d.date_entered_closed_won_classic IS NOT NULL OR d.date_entered_closed_lost_classic IS NOT NULL)
                  AND d.qualified_date IS NOT NULL
                  AND d.deal_type = 'New Business'
            )
            SELECT
                close_quarter,
                CASE
                    WHEN rep_tenure_months IS NULL OR rep_tenure_months < 7 THEN 'Under 7 Months'
                    WHEN rep_tenure_months >= 7 THEN '7+ Months'
                END AS rep_age_group,
                COUNT(DISTINCT CASE WHEN deal_stage = 'Closed Lost' THEN deal_name END) AS lost_count,
                COUNT(DISTINCT CASE WHEN deal_stage IN ('Closed Won', 'Closed Lost') THEN deal_name END) AS total_count,
                ROUND(
                    COUNT(DISTINCT CASE WHEN deal_stage = 'Closed Lost' THEN deal_name END) * 100.0
                    / NULLIF(COUNT(DISTINCT CASE WHEN deal_stage IN ('Closed Won', 'Closed Lost') THEN deal_name END), 0),
                    2
                ) AS loss_rate_pct
            FROM deal_emp
            GROUP BY close_quarter, rep_age_group
            ORDER BY close_quarter, rep_age_group
        """)
        st.session_state["rep_age_data"] = df_rep_age

        df_source_loss = conn.query("""
            SELECT
                close_date_quarter,
                COALESCE(mega_source, 'Unknown') AS lead_source,
                COUNT(DISTINCT CASE WHEN deal_stage = 'Closed Lost' THEN deal_name END) AS lost_count,
                COUNT(DISTINCT CASE WHEN deal_stage IN ('Closed Won', 'Closed Lost') THEN deal_name END) AS total_count,
                ROUND(
                    COUNT(DISTINCT CASE WHEN deal_stage = 'Closed Lost' THEN deal_name END) * 100.0
                    / NULLIF(
                        COUNT(DISTINCT CASE WHEN deal_stage IN ('Closed Won', 'Closed Lost') THEN deal_name END),
                        0
                    ),
                    2
                ) AS loss_rate_pct
            FROM "PORT_ANALYTICS_DEV"."SALES_ANALYTICS"."CLOSED_DEALS_JUN26"
            WHERE (date_entered_closed_won_classic IS NOT NULL OR date_entered_closed_lost_classic IS NOT NULL)
              AND qualified_date IS NOT NULL
              AND deal_type = 'New Business'
            GROUP BY close_date_quarter, lead_source
            HAVING COUNT(DISTINCT CASE WHEN deal_stage IN ('Closed Won', 'Closed Lost') THEN deal_name END) >= 5
            ORDER BY close_date_quarter, lead_source
        """)
        st.session_state["source_loss_data"] = df_source_loss

        df_cohort = conn.query("""
            SELECT
                TO_VARCHAR(DATE_TRUNC('month', qualified_date), 'YYYY-MM') AS creation_cohort,
                COUNT(DISTINCT CASE WHEN deal_stage = 'Closed Lost' THEN deal_name END) AS lost_count,
                COUNT(DISTINCT CASE WHEN deal_stage IN ('Closed Won', 'Closed Lost') THEN deal_name END) AS total_count,
                ROUND(
                    COUNT(DISTINCT CASE WHEN deal_stage = 'Closed Lost' THEN deal_name END) * 100.0
                    / NULLIF(COUNT(DISTINCT CASE WHEN deal_stage IN ('Closed Won', 'Closed Lost') THEN deal_name END), 0),
                    2
                ) AS loss_rate_pct
            FROM "PORT_ANALYTICS_DEV"."SALES_ANALYTICS"."CLOSED_DEALS_JUN26"
            WHERE deal_stage IN ('Closed Won', 'Closed Lost')
              AND (date_entered_closed_won_classic IS NOT NULL OR date_entered_closed_lost_classic IS NOT NULL)
              AND qualified_date IS NOT NULL
              AND deal_type = 'New Business'
            GROUP BY creation_cohort
            HAVING COUNT(DISTINCT CASE WHEN deal_stage IN ('Closed Won', 'Closed Lost') THEN deal_name END) >= 3
            ORDER BY creation_cohort
        """)
        st.session_state["cohort_data"] = df_cohort

        df_cohort_create = conn.query("""
            SELECT
                TO_VARCHAR(DATE_TRUNC('month', create_date), 'YYYY-MM') AS create_cohort,
                COUNT(DISTINCT CASE WHEN deal_stage = 'Closed Lost' THEN deal_name END) AS lost_count,
                COUNT(DISTINCT CASE WHEN deal_stage IN ('Closed Won', 'Closed Lost') THEN deal_name END) AS total_count,
                ROUND(
                    COUNT(DISTINCT CASE WHEN deal_stage = 'Closed Lost' THEN deal_name END) * 100.0
                    / NULLIF(COUNT(DISTINCT CASE WHEN deal_stage IN ('Closed Won', 'Closed Lost') THEN deal_name END), 0),
                    2
                ) AS loss_rate_pct
            FROM "PORT_ANALYTICS_DEV"."SALES_ANALYTICS"."CLOSED_DEALS_JUN26"
            WHERE deal_stage IN ('Closed Won', 'Closed Lost')
              AND (date_entered_closed_won_classic IS NOT NULL OR date_entered_closed_lost_classic IS NOT NULL)
              AND qualified_date IS NOT NULL
              AND deal_type = 'New Business'
              AND create_date IS NOT NULL
            GROUP BY create_cohort
            HAVING COUNT(DISTINCT CASE WHEN deal_stage IN ('Closed Won', 'Closed Lost') THEN deal_name END) >2
            ORDER BY create_cohort
        """)
        st.session_state["cohort_create_data"] = df_cohort_create

        df_segment_mix = conn.query("""
            SELECT
                close_date_quarter,
                COALESCE(segment, 'Unknown') AS segment,
                COUNT(DISTINCT deal_name) AS deal_count,
                ROUND(
                    COUNT(DISTINCT deal_name) * 100.0
                    / NULLIF(SUM(COUNT(DISTINCT deal_name)) OVER (PARTITION BY close_date_quarter), 0),
                    2
                ) AS pct_of_deals
            FROM "PORT_ANALYTICS_DEV"."SALES_ANALYTICS"."CLOSED_DEALS_JUN26"
            WHERE deal_stage IN ('Closed Won', 'Closed Lost')
              AND (date_entered_closed_won_classic IS NOT NULL OR date_entered_closed_lost_classic IS NOT NULL)
              AND qualified_date IS NOT NULL
              AND deal_type = 'New Business'
            GROUP BY close_date_quarter, segment
            ORDER BY close_date_quarter, segment
        """)
        st.session_state["segment_mix_data"] = df_segment_mix

        df_qualify_segment = conn.query("""
            SELECT
                TO_VARCHAR(DATE_TRUNC('month', qualified_date), 'YYYY-MM') AS qualify_month,
                COALESCE(segment, 'Unknown') AS segment,
                COUNT(DISTINCT deal_name) AS deal_count,
                ROUND(
                    COUNT(DISTINCT deal_name) * 100.0
                    / NULLIF(SUM(COUNT(DISTINCT deal_name)) OVER (PARTITION BY qualify_month), 0),
                    2
                ) AS pct_of_deals
            FROM "PORT_ANALYTICS_DEV"."SALES_ANALYTICS"."CLOSED_DEALS_JUN26"
            WHERE qualified_date IS NOT NULL
              AND deal_type = 'New Business'
              AND (date_entered_closed_won_classic IS NOT NULL OR date_entered_closed_lost_classic IS NOT NULL)
            GROUP BY qualify_month, segment
            ORDER BY qualify_month, segment
        """)
        st.session_state["qualify_segment_data"] = df_qualify_segment

        df_lost_reasons = conn.query("""
            WITH categorized AS (
                SELECT
                    close_date_quarter,
                    CASE
                        WHEN LOWER(COALESCE(closed_lost_details, '')) ILIKE '%duplicate%'
                          OR LOWER(COALESCE(closed_lost_details, '')) ILIKE '%dupe%'
                          OR LOWER(COALESCE(closed_lost_details, '')) ILIKE '%merging%'
                          OR LOWER(COALESCE(closed_lost_details, '')) ILIKE '%already closed won%'
                          OR LOWER(COALESCE(closed_lost_details, '')) ILIKE '%old opp%'
                          OR LOWER(COALESCE(closed_lost_details, '')) ILIKE '%opened in the past%'
                            THEN 'Data hygiene (dupe / old opp)'
                        WHEN LOWER(COALESCE(closed_lost_details, '')) ILIKE '%cortex%'
                          OR LOWER(COALESCE(closed_lost_details, '')) ILIKE '%backstage%'
                          OR LOWER(COALESCE(closed_lost_details, '')) ILIKE '%harness%'
                          OR LOWER(COALESCE(closed_lost_details, '')) ILIKE '%opslevel%'
                          OR LOWER(COALESCE(closed_lost_details, '')) ILIKE '%humanitec%'
                          OR LOWER(COALESCE(closed_lost_details, '')) ILIKE '%compass%'
                          OR LOWER(COALESCE(closed_lost_details, '')) ILIKE '%went with dx%'
                          OR LOWER(COALESCE(closed_lost_details, '')) ILIKE '%portal selected%'
                          OR LOWER(COALESCE(closed_lost_details, '')) ILIKE '%competitor%'
                          OR LOWER(COALESCE(closed_lost_details, '')) ILIKE '%another vendor%'
                            THEN 'Lost to competitor'
                        WHEN LOWER(COALESCE(closed_lost_details, '')) ILIKE '%in-house%'
                          OR LOWER(COALESCE(closed_lost_details, '')) ILIKE '%in house%'
                          OR LOWER(COALESCE(closed_lost_details, '')) ILIKE '%built their own%'
                          OR LOWER(COALESCE(closed_lost_details, '')) ILIKE '%build their own%'
                          OR LOWER(COALESCE(closed_lost_details, '')) ILIKE '%own internal solution%'
                          OR LOWER(COALESCE(closed_lost_details, '')) ILIKE '%homegrown%'
                          OR LOWER(COALESCE(closed_lost_details, '')) ILIKE '%vibe-code%'
                          OR LOWER(COALESCE(closed_lost_details, '')) ILIKE '%build vs buy%'
                          OR LOWER(COALESCE(closed_lost_details, '')) ILIKE '%bring idp in-house%'
                            THEN 'Build in-house'
                        WHEN LOWER(COALESCE(closed_lost_details, '')) ILIKE '%fedramp%'
                          OR LOWER(COALESCE(closed_lost_details, '')) ILIKE '%missing%'
                          OR LOWER(COALESCE(closed_lost_details, '')) ILIKE '%feature%'
                          OR LOWER(COALESCE(closed_lost_details, '')) ILIKE '%too complex%'
                          OR LOWER(COALESCE(closed_lost_details, '')) ILIKE '%heavy lift%'
                          OR LOWER(COALESCE(closed_lost_details, '')) ILIKE '%maintenance burden%'
                          OR LOWER(COALESCE(closed_lost_details, '')) ILIKE '%out of the box%'
                          OR LOWER(COALESCE(closed_lost_details, '')) ILIKE '%integration%'
                          OR LOWER(COALESCE(closed_lost_details, '')) ILIKE '%data model%'
                          OR LOWER(COALESCE(closed_lost_details, '')) ILIKE '%limitations%'
                          OR LOWER(COALESCE(closed_lost_details, '')) ILIKE '%not a fit%'
                          OR LOWER(COALESCE(closed_lost_details, '')) ILIKE '%misalignment%'
                          OR LOWER(COALESCE(closed_lost_details, '')) ILIKE '%release flows%'
                            THEN 'Product gap / fit / complexity'
                        WHEN LOWER(COALESCE(closed_lost_details, '')) ILIKE '%budget%'
                          OR LOWER(COALESCE(closed_lost_details, '')) ILIKE '%price%'
                          OR LOWER(COALESCE(closed_lost_details, '')) ILIKE '%pricing%'
                          OR LOWER(COALESCE(closed_lost_details, '')) ILIKE '%cost%'
                          OR LOWER(COALESCE(closed_lost_details, '')) ILIKE '%spend%freeze%'
                          OR LOWER(COALESCE(closed_lost_details, '')) ILIKE '%procurement freeze%'
                          OR LOWER(COALESCE(closed_lost_details, '')) ILIKE '%not charging for ai%'
                          OR LOWER(COALESCE(closed_lost_details, '')) ILIKE '%consumption pricing%'
                            THEN 'No budget / pricing'
                        WHEN LOWER(COALESCE(closed_lost_details, '')) ILIKE '%left the%'
                          OR LOWER(COALESCE(closed_lost_details, '')) ILIKE '%champion%'
                          OR LOWER(COALESCE(closed_lost_details, '')) ILIKE '%fired%'
                          OR LOWER(COALESCE(closed_lost_details, '')) ILIKE '%layoff%'
                          OR LOWER(COALESCE(closed_lost_details, '')) ILIKE '%lay off%'
                          OR LOWER(COALESCE(closed_lost_details, '')) ILIKE '%restructur%'
                          OR LOWER(COALESCE(closed_lost_details, '')) ILIKE '%acquisition%'
                          OR LOWER(COALESCE(closed_lost_details, '')) ILIKE '%new cio%'
                          OR LOWER(COALESCE(closed_lost_details, '')) ILIKE '%new leadership%'
                          OR LOWER(COALESCE(closed_lost_details, '')) ILIKE '%departure%'
                          OR LOWER(COALESCE(closed_lost_details, '')) ILIKE '%exited the org%'
                            THEN 'Champion loss / org change'
                        WHEN LOWER(COALESCE(closed_lost_details, '')) ILIKE '%deprioriti%'
                          OR LOWER(COALESCE(closed_lost_details, '')) ILIKE '%priorit%'
                          OR LOWER(COALESCE(closed_lost_details, '')) ILIKE '%postpon%'
                          OR LOWER(COALESCE(closed_lost_details, '')) ILIKE '%pushed%'
                          OR LOWER(COALESCE(closed_lost_details, '')) ILIKE '%timing%'
                          OR LOWER(COALESCE(closed_lost_details, '')) ILIKE '%on hold%'
                          OR LOWER(COALESCE(closed_lost_details, '')) ILIKE '%paus%'
                          OR LOWER(COALESCE(closed_lost_details, '')) ILIKE '%revisit%'
                          OR LOWER(COALESCE(closed_lost_details, '')) ILIKE '%not ready%'
                            THEN 'Deprioritized / bad timing'
                        WHEN LOWER(COALESCE(closed_lost_details, '')) ILIKE '%dark%'
                          OR LOWER(COALESCE(closed_lost_details, '')) ILIKE '%unresponsive%'
                          OR LOWER(COALESCE(closed_lost_details, '')) ILIKE '%no response%'
                          OR LOWER(COALESCE(closed_lost_details, '')) ILIKE '%never responded%'
                          OR LOWER(COALESCE(closed_lost_details, '')) ILIKE '%no show%'
                          OR LOWER(COALESCE(closed_lost_details, '')) ILIKE '%ghost%'
                          OR LOWER(COALESCE(closed_lost_details, '')) ILIKE '%gone silent%'
                          OR LOWER(COALESCE(closed_lost_details, '')) ILIKE '%stopped responding%'
                            THEN 'Ghosted / unresponsive'
                        WHEN LOWER(COALESCE(closed_lost_details, '')) ILIKE '%kicking tires%'
                          OR LOWER(COALESCE(closed_lost_details, '')) ILIKE '%no real project%'
                          OR LOWER(COALESCE(closed_lost_details, '')) ILIKE '%exploratory%'
                          OR LOWER(COALESCE(closed_lost_details, '')) ILIKE '%science project%'
                          OR LOWER(COALESCE(closed_lost_details, '')) ILIKE '%not interested%'
                            THEN 'No project / tire-kicking'
                        WHEN COALESCE(closed_lost_details, '') = '' THEN 'No reason given'
                        ELSE 'Other'
                    END AS lost_reason_category
                FROM "PORT_ANALYTICS_DEV"."SALES_ANALYTICS"."CLOSED_DEALS_JUN26"
                WHERE date_entered_closed_lost_classic IS NOT NULL
                  AND (date_entered_closed_won_classic IS NOT NULL OR date_entered_closed_lost_classic IS NOT NULL)
                  AND qualified_date IS NOT NULL
                  AND deal_type = 'New Business'
                  AND date_entered_closed_lost_classic >= DATEADD('month', -18, CURRENT_DATE)
            )
            SELECT
                close_date_quarter,
                lost_reason_category,
                COUNT(*) AS lost_deals,
                ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (PARTITION BY close_date_quarter), 1) AS pct_of_quarter_losses
            FROM categorized
            GROUP BY close_date_quarter, lost_reason_category
            ORDER BY close_date_quarter, lost_deals DESC
        """)
        st.session_state["lost_reasons_data"] = df_lost_reasons

if "deals_data" in st.session_state:
    df = st.session_state["deals_data"]

    import altair as alt

    st.subheader("% of Closed Lost by Stage Before Closed")

    df["DEAL_COUNT"] = df["DEAL_COUNT"].astype(int)
    df["PCT_COMPUTED"] = (
        df["DEAL_COUNT"] / df.groupby("CLOSE_DATE_QUARTER")["DEAL_COUNT"].transform("sum") * 100
    ).round(1)

    chart = alt.Chart(df).mark_bar().encode(
        x=alt.X("CLOSE_DATE_QUARTER:N", title="Close Date Quarter", sort=None),
        y=alt.Y("DEAL_COUNT:Q", title="% of Closed Lost Deals", stack="normalize", axis=alt.Axis(format="%")),
        color=alt.Color("DEAL_STAGE_BEFORE_CLOSED:N", title="Stage Before Closed", legend=alt.Legend(orient="bottom")),
        tooltip=[
            alt.Tooltip("CLOSE_DATE_QUARTER:N", title="Quarter"),
            alt.Tooltip("DEAL_STAGE_BEFORE_CLOSED:N", title="Stage"),
            alt.Tooltip("DEAL_COUNT:Q", title="Lost Deals"),
            alt.Tooltip("PCT_COMPUTED:Q", format=".1f", title="% of Quarter Losses"),
        ]
    ).properties(height=500)

    st.altair_chart(chart, use_container_width=True)

if "winrate_data" in st.session_state:
    import altair as alt

    df_wr = st.session_state["winrate_data"]

    st.subheader("Win Rate by Close Quarter")

    col1, col2 = st.columns(2)

    with col1:
        counts = df_wr.melt(
            id_vars=["CLOSE_DATE_QUARTER"],
            value_vars=["CLOSED_WON_COUNT", "CLOSED_LOST_COUNT"],
            var_name="outcome",
            value_name="count"
        )
        counts["outcome"] = counts["outcome"].replace({
            "CLOSED_WON_COUNT": "Closed Won",
            "CLOSED_LOST_COUNT": "Closed Lost"
        })

        line_chart = alt.Chart(counts).mark_line(point=True, strokeWidth=2).encode(
            x=alt.X("CLOSE_DATE_QUARTER:N", title="Close Date Quarter", sort=None),
            y=alt.Y("count:Q", title="Deal Count"),
            color=alt.Color("outcome:N", title="Outcome", scale=alt.Scale(domain=["Closed Won", "Closed Lost"], range=["#2ecc71", "#e74c3c"]), legend=alt.Legend(orient="bottom")),
            tooltip=["CLOSE_DATE_QUARTER", "outcome", "count"]
        ).properties(height=400, title="Won vs Lost Counts")

        st.altair_chart(line_chart, use_container_width=True)

    with col2:
        arr = df_wr.melt(
            id_vars=["CLOSE_DATE_QUARTER"],
            value_vars=["WON_NET_ARR", "LOST_NET_ARR"],
            var_name="outcome",
            value_name="net_arr"
        )
        arr["outcome"] = arr["outcome"].replace({
            "WON_NET_ARR": "Closed Won",
            "LOST_NET_ARR": "Closed Lost"
        })
        arr["net_arr_m"] = arr["net_arr"] / 1_000_000

        arr_chart = alt.Chart(arr).mark_line(point=True, strokeWidth=2).encode(
            x=alt.X("CLOSE_DATE_QUARTER:N", title="Close Date Quarter", sort=None),
            y=alt.Y("net_arr_m:Q", title="Net ARR", axis=alt.Axis(format="$,.0f", labelExpr="'$' + datum.value + 'M'")),
            color=alt.Color("outcome:N", title="Outcome", scale=alt.Scale(domain=["Closed Won", "Closed Lost"], range=["#2ecc71", "#e74c3c"]), legend=alt.Legend(orient="bottom")),
            tooltip=["CLOSE_DATE_QUARTER", "outcome", alt.Tooltip("net_arr_m:Q", format=".1f", title="Net ARR ($M)")]
        ).properties(height=400, title="Won vs Lost Net ARR")

        st.altair_chart(arr_chart, use_container_width=True)

    win_line = alt.Chart(df_wr).mark_line(point=True, strokeWidth=3).encode(
        x=alt.X("CLOSE_DATE_QUARTER:N", title="Close Date Quarter", sort=None),
        y=alt.Y("WIN_RATE_PCT:Q", title="Win Rate %", scale=alt.Scale(domain=[0, 100])),
        tooltip=["CLOSE_DATE_QUARTER", "WIN_RATE_PCT", "CLOSED_WON_COUNT", "CLOSED_LOST_COUNT"]
    ).properties(height=300, title="Win Rate % by Quarter")

    st.altair_chart(win_line, use_container_width=True)

if "poc_loss_data" in st.session_state:
    import altair as alt

    df_poc = st.session_state["poc_loss_data"]
    df_poc["LOSS_RATE_PCT"] = df_poc["LOSS_RATE_PCT"].astype(float)

    st.subheader("Loss Rate by POC Indication Over Time")

    poc_line = alt.Chart(df_poc).mark_line(point=True, strokeWidth=2).encode(
        x=alt.X("CLOSE_DATE_QUARTER:N", title="Close Date Quarter", sort=None),
        y=alt.Y("LOSS_RATE_PCT:Q", title="Loss Rate %", scale=alt.Scale(domain=[0, 100])),
        color=alt.Color("POC_INDICATION:N", title="POC Indication",
                        scale=alt.Scale(domain=["With POC", "No POC"], range=["#3498db", "#e67e22"]),
                        legend=alt.Legend(orient="bottom")),
        tooltip=[
            alt.Tooltip("CLOSE_DATE_QUARTER:N", title="Quarter"),
            alt.Tooltip("POC_INDICATION:N", title="POC"),
            alt.Tooltip("LOSS_RATE_PCT:Q", format=".1f", title="Loss Rate %"),
            alt.Tooltip("LOST_COUNT:Q", title="Lost Deals"),
            alt.Tooltip("TOTAL_COUNT:Q", title="Total Deals"),
        ]
    ).properties(height=400)

    st.altair_chart(poc_line, use_container_width=True)

if "bucket_quarter_data" in st.session_state:
    import altair as alt

    df_bq = st.session_state["bucket_quarter_data"]
    df_bq["LOSS_RATE_PCT"] = df_bq["LOSS_RATE_PCT"].astype(float)

    bucket_order = ["0-14d", "15-30d", "31-45d", "46-60d", "61-90d", "90d+"]

    st.subheader("Loss Rate by Pilot Duration Bucket Over Time")

    bucket_bar = alt.Chart(df_bq).mark_bar().encode(
        x=alt.X("CLOSE_DATE_QUARTER:N", title="Close Date Quarter", sort=None),
        y=alt.Y("LOSS_RATE_PCT:Q", title="Loss Rate %"),
        color=alt.Color("PILOT_BUCKET:N", title="Pilot Duration",
                        sort=bucket_order,
                        legend=alt.Legend(orient="bottom")),
        xOffset=alt.XOffset("PILOT_BUCKET:N", sort=bucket_order),
        tooltip=[
            alt.Tooltip("CLOSE_DATE_QUARTER:N", title="Quarter"),
            alt.Tooltip("PILOT_BUCKET:N", title="Duration Bucket"),
            alt.Tooltip("LOSS_RATE_PCT:Q", format=".1f", title="Loss Rate %"),
            alt.Tooltip("DEAL_COUNT:Q", title="Deal Count"),
        ]
    ).properties(height=450)

    st.altair_chart(bucket_bar, use_container_width=True)

if "team_loss_data" in st.session_state:
    import altair as alt

    df_team = st.session_state["team_loss_data"]
    df_team["LOSS_RATE_PCT"] = df_team["LOSS_RATE_PCT"].astype(float)

    st.subheader("Loss Rate Trend by Team")

    team_line = alt.Chart(df_team).mark_line(point=True, strokeWidth=2).encode(
        x=alt.X("CLOSE_DATE_QUARTER:N", title="Close Date Quarter", sort=None),
        y=alt.Y("LOSS_RATE_PCT:Q", title="Loss Rate %", scale=alt.Scale(domain=[0, 100])),
        color=alt.Color("HUBSPOT_TEAM:N", title="HubSpot Team", legend=alt.Legend(orient="bottom")),
        tooltip=[
            alt.Tooltip("CLOSE_DATE_QUARTER:N", title="Quarter"),
            alt.Tooltip("HUBSPOT_TEAM:N", title="Team"),
            alt.Tooltip("LOSS_RATE_PCT:Q", format=".1f", title="Loss Rate %"),
            alt.Tooltip("LOST_COUNT:Q", title="Lost Deals"),
            alt.Tooltip("TOTAL_COUNT:Q", title="Total Deals"),
        ]
    ).properties(height=450)

    st.altair_chart(team_line, use_container_width=True)

if "forecast_data" in st.session_state:
    import altair as alt

    df_fc = st.session_state["forecast_data"]
    df_fc["LOST_DEALS"] = df_fc["LOST_DEALS"].astype(int)
    df_fc["LOST_AMOUNT"] = df_fc["LOST_AMOUNT"].astype(float)

    forecast_order = ["Commit", "Most Likely", "Best case", "Pipeline", "Not forecasted"]
    forecast_colors = ["#e74c3c", "#e67e22", "#f1c40f", "#3498db", "#95a5a6"]

    st.subheader("What Were Lost Deals Forecast As?")
    st.caption("A growing Commit + Best Case share = forecast integrity degrading or reps sandbagging dead deals")

    count_bar = alt.Chart(df_fc).mark_bar().encode(
        x=alt.X("CLOSE_DATE_QUARTER:N", title="Close Date Quarter", sort=None),
        y=alt.Y("LOST_DEALS:Q", title="Share of Lost Deals", stack="normalize", axis=alt.Axis(format="%")),
        color=alt.Color("FORECAST_CATEGORY:N", title="Forecast Category",
                        sort=forecast_order,
                        scale=alt.Scale(domain=forecast_order, range=forecast_colors),
                        legend=alt.Legend(orient="bottom")),
        order=alt.Order("FORECAST_CATEGORY:N", sort="ascending"),
        tooltip=[
            alt.Tooltip("CLOSE_DATE_QUARTER:N", title="Quarter"),
            alt.Tooltip("FORECAST_CATEGORY:N", title="Forecast Category"),
            alt.Tooltip("LOST_DEALS:Q", title="Lost Deals"),
        ]
    ).properties(height=420)
    st.altair_chart(count_bar, use_container_width=True)

if "lost_reasons_data" in st.session_state:
    import altair as alt

    df_lr = st.session_state["lost_reasons_data"]
    df_lr["LOST_DEALS"] = df_lr["LOST_DEALS"].astype(int)
    df_lr["PCT_OF_QUARTER_LOSSES"] = df_lr["PCT_OF_QUARTER_LOSSES"].astype(float)

    reason_order = [
        "Lost to competitor", "Build in-house", "Product gap / fit / complexity",
        "No budget / pricing", "Champion loss / org change", "Deprioritized / bad timing",
        "Ghosted / unresponsive", "No project / tire-kicking",
        "Data hygiene (dupe / old opp)", "No reason given", "Other"
    ]
    reason_colors = [
        "#e74c3c", "#c0392b", "#e67e22", "#f39c12", "#9b59b6",
        "#3498db", "#1abc9c", "#2ecc71", "#95a5a6", "#bdc3c7", "#7f8c8d"
    ]

    st.subheader("Why Are We Losing? Lost Deal Reason Categories")
    st.caption("Last 18 months — Classic pipeline, qualified deals only")

    reasons_bar = alt.Chart(df_lr).mark_bar().encode(
        x=alt.X("CLOSE_DATE_QUARTER:N", title="Close Date Quarter", sort=None),
        y=alt.Y("LOST_DEALS:Q", title="% of Quarter Losses", stack="normalize", axis=alt.Axis(format="%")),
        color=alt.Color("LOST_REASON_CATEGORY:N", title="Lost Reason",
                        sort=reason_order,
                        scale=alt.Scale(domain=reason_order, range=reason_colors),
                        legend=alt.Legend(orient="bottom", columns=3)),
        order=alt.Order("LOST_REASON_CATEGORY:N", sort="ascending"),
        tooltip=[
            alt.Tooltip("CLOSE_DATE_QUARTER:N", title="Quarter"),
            alt.Tooltip("LOST_REASON_CATEGORY:N", title="Reason"),
            alt.Tooltip("LOST_DEALS:Q", title="Lost Deals"),
            alt.Tooltip("PCT_OF_QUARTER_LOSSES:Q", format=".1f", title="% of Quarter"),
        ]
    ).properties(height=500)

    st.altair_chart(reasons_bar, use_container_width=True)

if "rep_age_data" in st.session_state:
    import altair as alt

    df_ra = st.session_state["rep_age_data"]
    df_ra["LOSS_RATE_PCT"] = df_ra["LOSS_RATE_PCT"].astype(float)

    st.subheader("Loss Rate by Rep Tenure")
    st.caption("Under 7 Months includes reps not found in dim_employee")

    rep_age_line = alt.Chart(df_ra).mark_line(point=True, strokeWidth=2).encode(
        x=alt.X("CLOSE_QUARTER:N", title="Close Date Quarter", sort=None),
        y=alt.Y("LOSS_RATE_PCT:Q", title="Loss Rate %"),
        color=alt.Color("REP_AGE_GROUP:N", title="Rep Tenure",
                        scale=alt.Scale(domain=["Under 7 Months", "7+ Months"], range=["#e74c3c", "#2ecc71"]),
                        legend=alt.Legend(orient="bottom")),
        tooltip=[
            alt.Tooltip("CLOSE_QUARTER:N", title="Quarter"),
            alt.Tooltip("REP_AGE_GROUP:N", title="Rep Tenure"),
            alt.Tooltip("LOSS_RATE_PCT:Q", format=".1f", title="Loss Rate %"),
            alt.Tooltip("LOST_COUNT:Q", title="Lost Deals"),
            alt.Tooltip("TOTAL_COUNT:Q", title="Total Deals"),
        ]
    ).properties(height=400)

    st.altair_chart(rep_age_line, use_container_width=True)

if "source_loss_data" in st.session_state:
    import altair as alt

    df_src = st.session_state["source_loss_data"]
    df_src["LOSS_RATE_PCT"] = df_src["LOSS_RATE_PCT"].astype(float)

    st.subheader("Pipeline Source Mix Shift — Loss Rate by Lead Source")

    source_line = alt.Chart(df_src).mark_line(point=True, strokeWidth=2).encode(
        x=alt.X("CLOSE_DATE_QUARTER:N", title="Close Date Quarter", sort=None),
        y=alt.Y("LOSS_RATE_PCT:Q", title="Loss Rate %"),
        color=alt.Color("LEAD_SOURCE:N", title="Lead Source", legend=alt.Legend(orient="bottom", columns=3)),
        tooltip=[
            alt.Tooltip("CLOSE_DATE_QUARTER:N", title="Quarter"),
            alt.Tooltip("LEAD_SOURCE:N", title="Lead Source"),
            alt.Tooltip("LOSS_RATE_PCT:Q", format=".1f", title="Loss Rate %"),
            alt.Tooltip("LOST_COUNT:Q", title="Lost Deals"),
            alt.Tooltip("TOTAL_COUNT:Q", title="Total Deals"),
        ]
    ).properties(height=400)

    st.altair_chart(source_line, use_container_width=True)

if "cohort_data" in st.session_state:
    import altair as alt

    df_cohort = st.session_state["cohort_data"]
    df_cohort["LOSS_RATE_PCT"] = df_cohort["LOSS_RATE_PCT"].astype(float)

    st.subheader("Cohort Loss Rate by Qualify Month")
    st.caption("Each point = % of deals qualified that month that closed lost (New Business, qualified only)")

    cohort_line = alt.Chart(df_cohort).mark_line(point=True, strokeWidth=2).encode(
        x=alt.X("CREATION_COHORT:N", title="Qualify Month", sort=None,
                axis=alt.Axis(labelAngle=-45)),
        y=alt.Y("LOSS_RATE_PCT:Q", title="Loss Rate %"),
        tooltip=[
            alt.Tooltip("CREATION_COHORT:N", title="Qualify Month"),
            alt.Tooltip("LOSS_RATE_PCT:Q", format=".1f", title="Loss Rate %"),
            alt.Tooltip("LOST_COUNT:Q", title="Lost Deals"),
            alt.Tooltip("TOTAL_COUNT:Q", title="Total Deals"),
        ]
    ).properties(height=400)

    st.altair_chart(cohort_line, use_container_width=True)

if "cohort_create_data" in st.session_state:
    import altair as alt

    df_cc = st.session_state["cohort_create_data"]
    df_cc["LOSS_RATE_PCT"] = df_cc["LOSS_RATE_PCT"].astype(float)

    st.subheader("Cohort Loss Rate by Deal Creation Month")
    st.caption("Each point = % of deals created that month that closed lost (New Business, qualified only)")

    cohort_create_line = alt.Chart(df_cc).mark_line(point=True, strokeWidth=2).encode(
        x=alt.X("CREATE_COHORT:N", title="Creation Month", sort=None,
                axis=alt.Axis(labelAngle=-45)),
        y=alt.Y("LOSS_RATE_PCT:Q", title="Loss Rate %"),
        tooltip=[
            alt.Tooltip("CREATE_COHORT:N", title="Creation Month"),
            alt.Tooltip("LOSS_RATE_PCT:Q", format=".1f", title="Loss Rate %"),
            alt.Tooltip("LOST_COUNT:Q", title="Lost Deals"),
            alt.Tooltip("TOTAL_COUNT:Q", title="Total Deals"),
        ]
    ).properties(height=400)

    st.altair_chart(cohort_create_line, use_container_width=True)

if "segment_mix_data" in st.session_state:
    import altair as alt

    df_seg = st.session_state["segment_mix_data"]
    df_seg["PCT_OF_DEALS"] = df_seg["PCT_OF_DEALS"].astype(float)

    st.subheader("Closed Deals by Segment")

    segment_line = alt.Chart(df_seg).mark_line(point=True, strokeWidth=2).encode(
        x=alt.X("CLOSE_DATE_QUARTER:N", title="Close Date Quarter", sort=None),
        y=alt.Y("PCT_OF_DEALS:Q", title="% of Deals"),
        color=alt.Color("SEGMENT:N", title="Segment", legend=alt.Legend(orient="bottom", columns=3)),
        tooltip=[
            alt.Tooltip("CLOSE_DATE_QUARTER:N", title="Quarter"),
            alt.Tooltip("SEGMENT:N", title="Segment"),
            alt.Tooltip("PCT_OF_DEALS:Q", format=".1f", title="% of Deals"),
            alt.Tooltip("DEAL_COUNT:Q", title="Deals"),
        ]
    ).properties(height=400)

    st.altair_chart(segment_line, use_container_width=True)

if "qualify_segment_data" in st.session_state:
    import altair as alt

    df_qs = st.session_state["qualify_segment_data"]
    df_qs["PCT_OF_DEALS"] = df_qs["PCT_OF_DEALS"].astype(float)

    st.subheader("Qualify Deals by Segment")

    qualify_segment_line = alt.Chart(df_qs).mark_line(point=True, strokeWidth=2).encode(
        x=alt.X("QUALIFY_MONTH:N", title="Qualify Month", sort=None,
                axis=alt.Axis(labelAngle=-45)),
        y=alt.Y("PCT_OF_DEALS:Q", title="% of Deals"),
        color=alt.Color("SEGMENT:N", title="Segment", legend=alt.Legend(orient="bottom", columns=3)),
        tooltip=[
            alt.Tooltip("QUALIFY_MONTH:N", title="Qualify Month"),
            alt.Tooltip("SEGMENT:N", title="Segment"),
            alt.Tooltip("PCT_OF_DEALS:Q", format=".1f", title="% of Deals"),
            alt.Tooltip("DEAL_COUNT:Q", title="Deals"),
        ]
    ).properties(height=400)

    st.altair_chart(qualify_segment_line, use_container_width=True)

if "poc_to_close_data" in st.session_state:
    import altair as alt

    df_ptc = st.session_state["poc_to_close_data"]
    df_ptc["MEDIAN_POC_TO_CLOSE_DAYS"] = df_ptc["MEDIAN_POC_TO_CLOSE_DAYS"].astype(float)

    st.subheader("Median Time: POC to Close")

    series_order = ["Mid-Market", "Enterprise Won", "Enterprise Lost"]
    series_colors = ["#3498db", "#2ecc71", "#e74c3c"]

    poc_to_close_line = alt.Chart(df_ptc).mark_line(point=True, strokeWidth=2).encode(
        x=alt.X("CLOSE_DATE_QUARTER:N", title="Close Quarter", sort=None),
        y=alt.Y("MEDIAN_POC_TO_CLOSE_DAYS:Q", title="Median Days (POC to Close)"),
        color=alt.Color("SERIES:N", title="Segment / Outcome",
                        sort=series_order,
                        scale=alt.Scale(domain=series_order, range=series_colors),
                        legend=alt.Legend(orient="bottom")),
        tooltip=[
            alt.Tooltip("CLOSE_DATE_QUARTER:N", title="Close Quarter"),
            alt.Tooltip("SERIES:N", title="Series"),
            alt.Tooltip("MEDIAN_POC_TO_CLOSE_DAYS:Q", format=".0f", title="Median Days (POC to Close)"),
            alt.Tooltip("DEAL_COUNT:Q", title="Deals"),
        ]
    ).properties(height=400)

    st.altair_chart(poc_to_close_line, use_container_width=True)
