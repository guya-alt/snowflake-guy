# Weekly Sales Metrics Streamlit dashboard
# Co-authored with CoCo
import re as _re
import streamlit as st
import altair as alt
import pandas as pd
import os
from datetime import date, timedelta

st.set_page_config(page_title="Weekly Sales Metrics", layout="wide")

# Base schema path — all queries compose from here
DWH = "PORT_ANALYTICS_PROD.DWH"

# Global time boundary: all metrics cut off at the start of the current week (Monday).
# This ensures the dashboard only shows data from COMPLETED weeks (Mon-Sun).
# Use this SQL expression in all WHERE clauses as the upper bound.

conn = st.connection("snowflake", ttl=None)


@st.cache_data(ttl=60, show_spinner=False)
def get_snowflake_today():
    return conn.query("SELECT CURRENT_DATE() AS today").iloc[0]["TODAY"]


_today = get_snowflake_today()

# Snapshot date: all queries use this fixed date instead of CURRENT_DATE()
# so the entire dashboard is a consistent snapshot as of this date.
SNAPSHOT_DATE_SQL = f"'{_today.strftime('%Y-%m-%d') if hasattr(_today, 'strftime') else str(_today)}'::DATE"
WEEK_CUTOFF_SQL = f"DATE_TRUNC('WEEK', {SNAPSHOT_DATE_SQL})"

# --- Title & Last Update ---
st.title("Weekly Sales Metrics")
st.caption("Priority metrics for sales leadership: velocity, conversion, and pipeline health.")
st.markdown(
    f"_Updated: {_today.strftime('%B %d, %Y') if hasattr(_today, 'strftime') else str(_today)}_ · "
    f"Built by [Guy Amitai](https://getport.slack.com/team/U0B4FPPESSD)"
)
st.divider()


# --- Load filter options (cheap, cached 1h) ---
@st.cache_data(ttl=3600, show_spinner=False)
def load_filter_options():
    def _vals(sql):
        df = conn.query(sql)
        return sorted([str(r) for r in df.iloc[:, 0].dropna().unique() if str(r).strip()])

    # Only show values from recent relevant deals (Classic, last 13 months)
    recent_filter = f"deal_created_date >= DATEADD('MONTH', -13, {SNAPSHOT_DATE_SQL})"
    teams = _vals(f"SELECT DISTINCT deal_team_name FROM {DWH}.FACT_DEALS WHERE deal_team_name IS NOT NULL AND {recent_filter}")
    owners = _vals(f"""
        SELECT DISTINCT de.display_name
        FROM {DWH}.FACT_DEALS fd
        JOIN {DWH}.DIM_EMPLOYEE de ON fd.sk_sales_owner = de.sk_employee
        WHERE de.display_name IS NOT NULL AND fd.{recent_filter}
    """)
    types = _vals(f"SELECT DISTINCT deal_type FROM {DWH}.FACT_DEALS WHERE deal_type IS NOT NULL AND deal_created_date >= DATEADD('MONTH', -13, {SNAPSHOT_DATE_SQL})")
    stages = _vals(f"SELECT DISTINCT deal_stage FROM {DWH}.FACT_DEALS WHERE deal_stage IS NOT NULL AND {recent_filter}")
    segs = _vals(f"""
        SELECT DISTINCT dc.segment
        FROM {DWH}.FACT_DEALS fd
        JOIN {DWH}.DIM_COMPANY dc ON fd.sk_company = dc.sk_company
        WHERE dc.segment IS NOT NULL AND TRIM(dc.segment) <> '' AND fd.{recent_filter}
    """)
    mega_sources = _vals(f"SELECT DISTINCT mega_source FROM {DWH}.FACT_DEALS WHERE mega_source IS NOT NULL AND {recent_filter}")
    deal_sources = _vals(f"SELECT DISTINCT deal_source FROM {DWH}.FACT_DEALS WHERE deal_source IS NOT NULL AND {recent_filter}")
    pipelines = _vals(f"SELECT DISTINCT pipeline FROM {DWH}.FACT_DEALS WHERE pipeline IS NOT NULL AND {recent_filter}")
    nna_df = conn.query(f"SELECT MIN(deal_net_new_arr) AS mn, MAX(deal_net_new_arr) AS mx FROM {DWH}.FACT_DEALS WHERE deal_net_new_arr IS NOT NULL AND deal_created_date >= DATEADD('MONTH', -13, {SNAPSHOT_DATE_SQL})")
    mn = float(nna_df.iloc[0]["MN"] or 0)
    mx = float(nna_df.iloc[0]["MX"] or 1_000_000)
    return teams, owners, types, stages, segs, mega_sources, deal_sources, pipelines, mn, mx


teams_all, owners_all, types_all, stages_all, segs_all, mega_sources_all, deal_sources_all, pipelines_all, min_nna, max_nna = load_filter_options()

# --- Global Filters sidebar ---
st.sidebar.header("Global Filters")
load_data = st.sidebar.button("Load Data", type="primary", use_container_width=True)

f_teams = st.sidebar.multiselect("Hubspot Team", teams_all, default=[])
f_owners = st.sidebar.multiselect("Deal Owner", owners_all, default=[])
f_qualified = st.sidebar.selectbox("Qualified?", ["All", "Yes", "No"])
f_closed = st.sidebar.selectbox("Closed?", ["All", "Yes", "No"])
f_segments = st.sidebar.multiselect("Segment", segs_all, default=[])
f_deal_types = st.sidebar.multiselect("Deal Type", types_all, default=["newbusiness"] if "newbusiness" in types_all else [])
f_stages = st.sidebar.multiselect("Deal Stage", stages_all, default=[])
f_mega_sources = st.sidebar.multiselect("Mega Source", mega_sources_all, default=[])
f_deal_sources = st.sidebar.multiselect("Deal Source", deal_sources_all, default=[])
f_pipelines = st.sidebar.multiselect("Pipeline", pipelines_all, default=["Classic"] if "Classic" in pipelines_all else [])
f_nna = st.sidebar.slider(
    "Net New ARR ($)",
    min_value=int(min_nna), max_value=int(max_nna),
    value=(int(min_nna), int(max_nna)),
    step=1000,
)

today = pd.Timestamp(_today)
quarters = []
for i in range(6):
    q_date = today - timedelta(days=i * 91)
    q_label = f"Q{(q_date.month - 1) // 3 + 1} {q_date.year}"
    if q_label not in quarters:
        quarters.append(q_label)
f_closed_quarters = st.sidebar.multiselect("Closed Quarter", quarters, default=[])

f_qualify_start = st.sidebar.date_input("Qualify Date From", value=None)
f_qualify_end = st.sidebar.date_input("Qualify Date To", value=None)

st.sidebar.markdown("---")
st.sidebar.subheader("Breakdown")
st.sidebar.caption("Adds sub-rows to charts by dimension")
cohort_breakdown = st.sidebar.selectbox("Split by", ["None", "Segment", "HubSpot Team", "Mega Source", "Deal Source", "Won/Lost"], key="cohort_breakdown")

if load_data:
    st.session_state["data_loaded"] = True

if "data_loaded" not in st.session_state:
    st.info("Configure filters in the sidebar and click **Load Data** to query.")
    st.stop()



@st.cache_data(ttl=900, show_spinner="Querying Snowflake...")
def run_query(sql):
    return conn.query(sql)


def build_global_filters_sql(has_employee_join=False):
    """Build SQL WHERE clauses from active sidebar filters.
    
    Args:
        has_employee_join: If True, owner filter uses de.display_name.
                          If False, skips owner filter (caller must handle separately).
    """
    clauses = []
    if f_teams:
        vals = ",".join(f"'{v.replace(chr(39), chr(39)+chr(39))}'" for v in f_teams)
        clauses.append(f"fd.deal_team_name IN ({vals})")
    if f_owners and has_employee_join:
        vals = ",".join(f"'{v.replace(chr(39), chr(39)+chr(39))}'" for v in f_owners)
        clauses.append(f"de.display_name IN ({vals})")
    if f_segments:
        vals = ",".join(f"'{v.replace(chr(39), chr(39)+chr(39))}'" for v in f_segments)
        clauses.append(f"dc.segment IN ({vals})")
    if f_deal_types:
        vals = ",".join(f"'{v.replace(chr(39), chr(39)+chr(39))}'" for v in f_deal_types)
        clauses.append(f"fd.deal_type IN ({vals})")
    if f_stages:
        vals = ",".join(f"'{v.replace(chr(39), chr(39)+chr(39))}' " for v in f_stages)
        clauses.append(f"fd.deal_stage IN ({vals})")
    if f_mega_sources:
        vals = ",".join(f"'{v.replace(chr(39), chr(39)+chr(39))}' " for v in f_mega_sources)
        clauses.append(f"fd.mega_source IN ({vals})")
    if f_deal_sources:
        vals = ",".join(f"'{v.replace(chr(39), chr(39)+chr(39))}' " for v in f_deal_sources)
        clauses.append(f"fd.deal_source IN ({vals})")
    if f_pipelines:
        vals = ",".join(f"'{v.replace(chr(39), chr(39)+chr(39))}' " for v in f_pipelines)
        clauses.append(f"fd.pipeline IN ({vals})")
    if f_nna != (int(min_nna), int(max_nna)):
        clauses.append(f"fd.deal_net_new_arr BETWEEN {f_nna[0]} AND {f_nna[1]}")
    if f_qualified == "Yes":
        clauses.append("fd.qualified_date IS NOT NULL")
    elif f_qualified == "No":
        clauses.append("fd.qualified_date IS NULL")
    if f_closed == "Yes":
        clauses.append("fd.is_closed = TRUE")
    elif f_closed == "No":
        clauses.append("fd.is_closed = FALSE")
    if f_closed_quarters:
        vals = ",".join(f"'{q}'" for q in f_closed_quarters)
        clauses.append(f"CONCAT('Q', QUARTER(fd.deal_closed_date), ' ', YEAR(fd.deal_closed_date)) IN ({vals})")
    if f_qualify_start:
        clauses.append(f"fd.qualified_date >= '{f_qualify_start}'")
    if f_qualify_end:
        clauses.append(f"fd.qualified_date <= '{f_qualify_end}'")
    return ("\n      AND " + "\n      AND ".join(clauses)) if clauses else ""


def fmt_arr(value):
    """Format a number as abbreviated ARR: $300K or $2.2M."""
    if value is None:
        return "$0"
    abs_val = abs(value)
    sign = "-" if value < 0 else ""
    if abs_val >= 1_000_000:
        return f"{sign}${abs_val / 1_000_000:.1f}M"
    elif abs_val >= 1_000:
        return f"{sign}${abs_val / 1_000:.0f}K"
    return f"{sign}${abs_val:.0f}"


def build_filter_caption():
    """Build compact filter description from active global filters."""
    parts = []
    if f_segments and len(f_segments) < 4:
        parts.append(f"Segment: {' · '.join(f_segments)}")
    elif f_segments:
        parts.append(f"Segment: {len(f_segments)} selected")
    if f_teams and len(f_teams) < 3:
        parts.append(f"Team: {' · '.join(f_teams)}")
    elif f_teams:
        parts.append(f"Team: {len(f_teams)} selected")
    if f_owners and len(f_owners) < 3:
        parts.append(f"Owner: {' · '.join(f_owners)}")
    elif f_owners:
        parts.append(f"Owner: {len(f_owners)} selected")
    if f_deal_types:
        parts.append(f"Type: {len(f_deal_types)} selected")
    if f_stages:
        parts.append(f"Stage: {len(f_stages)} selected")
    if f_mega_sources:
        parts.append(f"Mega Source: {' · '.join(f_mega_sources) if len(f_mega_sources) < 4 else f'{len(f_mega_sources)} selected'}")
    if f_deal_sources:
        parts.append(f"Deal Source: {len(f_deal_sources)} selected")
    if f_closed_quarters:
        parts.append(f"Quarters: {len(f_closed_quarters)} selected")
    if f_qualify_start or f_qualify_end:
        parts.append(f"Qualify: {f_qualify_start or '...'} to {f_qualify_end or '...'}")
    return " · ".join(parts) if parts else "All deals (no filters)"


# =============================================================================
# KPI METRICS
# =============================================================================
kpi_sql = f"""
SELECT
    COUNT(DISTINCT dc.sk_company) AS num_customers,
    SUM(fd.deal_net_new_arr) AS total_arr
FROM {DWH}.FACT_DEALS fd
LEFT JOIN {DWH}.DIM_COMPANY dc
    ON fd.sk_company = dc.sk_company
WHERE (
    (fd.deal_stage = 'Closed Won' AND fd.pipeline IN ('Classic', 'Renewals'))
    OR (fd.deal_stage = 'Churn' AND fd.pipeline = 'Renewals')
  )
  AND dc.lifecycle_stage IN ('Churn', 'Customer')
  AND COALESCE(dc.company_name, '') NOT ILIKE '%KTM%'
  AND COALESCE(dc.company_name, '') NOT ILIKE '%test%'
  AND COALESCE(dc.company_name, '') != 'Port'
  AND dc._is_deleted = FALSE
  AND dc.archived = FALSE
  AND fd.deal_closed_date IS NOT NULL
"""

newbiz_sql = f"""
SELECT
    COALESCE(SUM(fd.deal_total_arr), 0) AS newbiz_arr,
    AVG(fd.deal_total_arr) AS asp
FROM {DWH}.FACT_DEALS fd
LEFT JOIN {DWH}.DIM_COMPANY dc
    ON fd.sk_company = dc.sk_company
   AND COALESCE(dc.company_name, '') NOT ILIKE '%test%'
   AND COALESCE(dc.company_name, '') != 'Port'
   AND dc._is_deleted = FALSE
   AND dc.archived = FALSE
WHERE fd.is_won = TRUE
  AND fd.deal_total_arr > 0

  AND fd.deal_type = 'newbusiness'
"""

pipe_creation_sql = f"""
WITH weeks AS (
    SELECT
        DATEADD('WEEK', -1, {WEEK_CUTOFF_SQL}) AS last_full_week_start,
        {WEEK_CUTOFF_SQL} AS last_full_week_end,
        DATEADD('WEEK', -2, {WEEK_CUTOFF_SQL}) AS prior_week_start
)
SELECT
    COUNT(CASE WHEN fd.qualified_date >= w.last_full_week_start AND fd.qualified_date < w.last_full_week_end THEN 1 END) AS pipe_count_last_full_week,
    COALESCE(SUM(CASE WHEN fd.qualified_date >= w.last_full_week_start AND fd.qualified_date < w.last_full_week_end THEN fd.deal_net_new_arr END), 0) AS pipe_arr_last_full_week,
    COUNT(CASE WHEN fd.qualified_date >= w.prior_week_start AND fd.qualified_date < w.last_full_week_start THEN 1 END) AS pipe_count_prior_week,
    COALESCE(SUM(CASE WHEN fd.qualified_date >= w.prior_week_start AND fd.qualified_date < w.last_full_week_start THEN fd.deal_net_new_arr END), 0) AS pipe_arr_prior_week
FROM {DWH}.FACT_DEALS fd
LEFT JOIN {DWH}.DIM_COMPANY dc
    ON fd.sk_company = dc.sk_company
   AND COALESCE(dc.company_name, '') NOT ILIKE '%test%'
   AND COALESCE(dc.company_name, '') != 'Port'
   AND dc._is_deleted = FALSE
   AND dc.archived = FALSE
CROSS JOIN weeks w
WHERE fd.qualified_date IS NOT NULL
  AND fd.qualified_date >= w.prior_week_start
  AND fd.qualified_date < w.last_full_week_end
  AND fd.deal_net_new_arr > 0

  AND fd.deal_type = 'newbusiness'
"""

df_kpi = run_query(kpi_sql)
df_newbiz = run_query(newbiz_sql)
df_pipe = run_query(pipe_creation_sql)

if not df_kpi.empty:
    row = df_kpi.iloc[0]
    cust_now = int(row["NUM_CUSTOMERS"]) if row["NUM_CUSTOMERS"] else 0
    arr_now = float(row["TOTAL_ARR"]) if row["TOTAL_ARR"] else 0

    nb_row = df_newbiz.iloc[0] if not df_newbiz.empty else {}
    nb_arr = float(nb_row.get("NEWBIZ_ARR", 0) or 0)
    asp = float(nb_row.get("ASP", 0) or 0)

    pipe_row = df_pipe.iloc[0] if not df_pipe.empty else {}
    pipe_count_lfw = int(pipe_row.get("PIPE_COUNT_LAST_FULL_WEEK", 0) or 0)
    pipe_arr_lfw = float(pipe_row.get("PIPE_ARR_LAST_FULL_WEEK", 0) or 0)
    pipe_count_pw = int(pipe_row.get("PIPE_COUNT_PRIOR_WEEK", 0) or 0)
    pipe_arr_pw = float(pipe_row.get("PIPE_ARR_PRIOR_WEEK", 0) or 0)

    pipe_count_delta = pipe_count_lfw - pipe_count_pw
    pipe_arr_delta = pipe_arr_lfw - pipe_arr_pw

    kpi_row1 = st.columns(4)
    kpi_row1[0].metric("Customers", f"{cust_now:,}")
    kpi_row1[1].metric("ASP", fmt_arr(asp))
    kpi_row1[2].metric("ARR", fmt_arr(arr_now))
    kpi_row1[3].metric("NewBiz ARR", fmt_arr(nb_arr))

    kpi_row2 = st.columns(2)
    kpi_row2[0].metric(
        "Pipe Created Last Full Week (#)",
        f"{pipe_count_lfw:,}",
        delta=f"{pipe_count_delta:+,} vs prior week",
    )
    kpi_row2[1].metric(
        "Pipe Created Last Full Week ($)",
        fmt_arr(pipe_arr_lfw),
        delta=f"{fmt_arr(pipe_arr_delta)} vs prior week",
    )

    st.caption(f"Filters: {build_filter_caption()}")
    st.markdown("---")


# =============================================================================
# COHORT VIEW
# =============================================================================
st.header("Cohort View")
st.caption("Cumulative conversion by cohort period — how deals progress from creation/qualification to outcome over time.")

cohort_col1, cohort_col2, cohort_col3, cohort_col4 = st.columns(4)
with cohort_col1:
    cohort_from = st.selectbox("From (cohort)", ["Created (Meeting)", "Qualified (Opp)"], key="cohort_from")
with cohort_col2:
    to_options = ["Qualified (Opp)", "Won", "Lost"] if cohort_from == "Created (Meeting)" else ["Won", "Lost"]
    cohort_to = st.selectbox("To (outcome)", to_options, key="cohort_to")
with cohort_col3:
    cohort_metric = st.radio("Metric", ["# (Count)", "$ (ARR)"], horizontal=True, key="cohort_metric")
with cohort_col4:
    cohort_granularity = st.selectbox("Granularity", ["Weekly", "Monthly"], key="cohort_gran")

# Granularity settings
TRUNC_MAP = {"Weekly": "WEEK", "Monthly": "MONTH"}
trunc_unit = TRUNC_MAP[cohort_granularity]
prefix = "W+" if cohort_granularity == "Weekly" else "M+"

# Determine from/to columns
if cohort_from == "Created (Meeting)":
    from_date_col = "fd.deal_created_date"
    from_label = "Create"
else:
    from_date_col = "fd.qualified_date"
    from_label = "Qualify"

if cohort_to == "Won":
    to_condition = "fd.is_won = TRUE"
    to_date_col = "fd.deal_closed_date"
elif cohort_to == "Lost":
    to_condition = "fd.is_won = FALSE AND fd.is_closed = TRUE"
    to_date_col = "fd.deal_closed_date"
else:  # Qualified (Opp)
    to_condition = "fd.qualified_date IS NOT NULL"
    to_date_col = "fd.qualified_date"


@st.cache_data(ttl=900, show_spinner="Loading cohort data...")
def load_cohort_data(from_col, to_col, to_cond, trunc, metric, global_filter_sql):
    """Load all deal-level data needed for cohort computation."""
    # All deals in the "from" population (base)
    base_sql = f"""
    SELECT
        fd.sk_deal,
        DATE_TRUNC('{trunc}', {from_col})::DATE AS cohort_period,
        fd.deal_net_new_arr,
        fd.deal_total_arr,
        fd.deal_name,
        dc.company_name,
        dc.segment,
        dc.geography AS geo,
        de.display_name AS owner,
        fd.deal_team_name AS team,
        fd.deal_stage,
        fd.mega_source,
        fd.deal_source
    FROM {DWH}.FACT_DEALS fd
    LEFT JOIN {DWH}.DIM_COMPANY dc
        ON fd.sk_company = dc.sk_company
       AND COALESCE(dc.company_name, '') NOT ILIKE '%test%'
       AND COALESCE(dc.company_name, '') != 'Port'
       AND dc._is_deleted = FALSE
       AND dc.archived = FALSE
    LEFT JOIN {DWH}.DIM_EMPLOYEE de
        ON fd.sk_sales_owner = de.sk_employee
    WHERE {from_col} IS NOT NULL
    
      AND fd.deal_type = 'newbusiness'

      AND {from_col} >= DATEADD('MONTH', -13, {SNAPSHOT_DATE_SQL})
      AND {from_col} < {WEEK_CUTOFF_SQL}
      {global_filter_sql}
    """
    df_base = conn.query(base_sql)

    # Deals that reached the outcome
    outcome_sql = f"""
    SELECT
        fd.sk_deal,
        DATE_TRUNC('{trunc}', {from_col})::DATE AS cohort_period,
        DATEDIFF('{trunc}', DATE_TRUNC('{trunc}', {from_col}), DATE_TRUNC('{trunc}', {to_col})) AS periods_elapsed,
        fd.deal_net_new_arr,
        fd.deal_total_arr,
        fd.deal_name,
        dc.company_name,
        dc.segment,
        de.display_name AS owner,
        fd.deal_team_name AS team,
        fd.deal_stage,
        fd.mega_source,
        fd.deal_source,
        {to_col}::DATE AS outcome_date
    FROM {DWH}.FACT_DEALS fd
    LEFT JOIN {DWH}.DIM_COMPANY dc
        ON fd.sk_company = dc.sk_company
       AND COALESCE(dc.company_name, '') NOT ILIKE '%test%'
       AND COALESCE(dc.company_name, '') != 'Port'
       AND dc._is_deleted = FALSE
       AND dc.archived = FALSE
    LEFT JOIN {DWH}.DIM_EMPLOYEE de
        ON fd.sk_sales_owner = de.sk_employee
    WHERE {from_col} IS NOT NULL
      AND {to_col} IS NOT NULL
      AND {to_cond}
      AND {to_col} < {WEEK_CUTOFF_SQL}
    
      AND fd.deal_type = 'newbusiness'

      AND {from_col} >= DATEADD('MONTH', -13, {SNAPSHOT_DATE_SQL})
      AND {from_col} < {WEEK_CUTOFF_SQL}
      {global_filter_sql}
    """
    df_outcome = conn.query(outcome_sql)
    return df_base, df_outcome


df_cohort_base, df_cohort_outcome = load_cohort_data(
    from_date_col, to_date_col, to_condition, trunc_unit, cohort_metric,
    build_global_filters_sql(has_employee_join=True)
)

# Apply sidebar filters to dataframes (pandas-level, supplements SQL-level filters)
def apply_filters(df):
    if df.empty:
        return df
    if f_teams and "TEAM" in df.columns:
        df = df[df["TEAM"].isin(f_teams)]
    if f_segments and "SEGMENT" in df.columns:
        df = df[df["SEGMENT"].isin(f_segments)]
    if f_owners and "OWNER" in df.columns:
        df = df[df["OWNER"].isin(f_owners)]
    if f_deal_types and "DEAL_TYPE" in df.columns:
        df = df[df["DEAL_TYPE"].isin(f_deal_types)]
    if f_stages and "DEAL_STAGE" in df.columns:
        df = df[df["DEAL_STAGE"].isin(f_stages)]
    if f_mega_sources and "MEGA_SOURCE" in df.columns:
        df = df[df["MEGA_SOURCE"].isin(f_mega_sources)]
    if f_deal_sources and "DEAL_SOURCE" in df.columns:
        df = df[df["DEAL_SOURCE"].isin(f_deal_sources)]
    if f_nna != (int(min_nna), int(max_nna)) and "DEAL_NET_NEW_ARR" in df.columns:
        df = df[(df["DEAL_NET_NEW_ARR"] >= f_nna[0]) & (df["DEAL_NET_NEW_ARR"] <= f_nna[1])]
    return df

df_cohort_base = apply_filters(df_cohort_base)
df_cohort_outcome = apply_filters(df_cohort_outcome)

if df_cohort_base.empty:
    st.info("No cohort data found for this period.")
else:
    # Compute base per cohort period
    base_by_cohort = df_cohort_base.groupby("COHORT_PERIOD").agg(
        base_count=("SK_DEAL", "count"),
        base_arr=("DEAL_NET_NEW_ARR", "sum"),
    ).reset_index()
    base_by_cohort = base_by_cohort.set_index("COHORT_PERIOD")

    # Compute cumulative conversion per cohort × periods_elapsed
    if not df_cohort_outcome.empty:
        if cohort_metric == "# (Count)":
            outcome_pivot = df_cohort_outcome.groupby(["COHORT_PERIOD", "PERIODS_ELAPSED"]).size().reset_index(name="VALUE")
        else:
            outcome_pivot = df_cohort_outcome.groupby(["COHORT_PERIOD", "PERIODS_ELAPSED"])["DEAL_NET_NEW_ARR"].sum().reset_index(name="VALUE")

        pivot = outcome_pivot.pivot_table(index="COHORT_PERIOD", columns="PERIODS_ELAPSED", values="VALUE", aggfunc="sum").fillna(0)
        # Ensure all period columns 0..max exist so cumsum fills gaps
        max_col = int(pivot.columns.max()) if len(pivot.columns) > 0 else 0
        all_cols = list(range(0, max_col + 1))
        pivot = pivot.reindex(columns=all_cols, fill_value=0)
        pivot_cumulative = pivot.cumsum(axis=1)
    else:
        pivot_cumulative = pd.DataFrame(index=base_by_cohort.index)

    # Max periods based on last full week/month (cutoff for TO date)
    now = pd.Timestamp.now().normalize()
    if cohort_granularity == "Weekly":
        # Start of current week (Monday) = end of last full week
        cutoff_period = now - pd.Timedelta(days=now.weekday())
    else:
        # Start of current month = end of last full month
        cutoff_period = now.replace(day=1)

    def get_max_periods(cohort_ts):
        ct = pd.Timestamp(cohort_ts)
        if cohort_granularity == "Weekly":
            return max(0, int((cutoff_period - ct).days // 7) - 1)
        else:
            return max(0, (cutoff_period.year - ct.year) * 12 + (cutoff_period.month - ct.month) - 1)

    # Determine period columns
    all_max_col = int(pivot_cumulative.columns.max()) if not pivot_cumulative.empty and len(pivot_cumulative.columns) > 0 else 0
    period_cols = list(range(0, all_max_col + 1))

    cohorts_sorted = sorted(base_by_cohort.index)
    # Default to last 15 rows
    cohorts_sorted = cohorts_sorted[-15:]

    def format_cohort_label(ts):
        ts = pd.Timestamp(ts)
        if cohort_granularity == "Weekly":
            return ts.strftime("%b %d, %Y")
        else:
            return ts.strftime("%b %Y")

    # Build HTML table
    html = """<style>
    .cohort-table { border-collapse: collapse; width: 100%; font-family: -apple-system, BlinkMacSystemFont, sans-serif; font-size: 12px; }
    .cohort-table th { background: #1a1a2e; color: #fff; padding: 8px 10px; text-align: center; font-weight: 500; position: sticky; top: 0; z-index: 1; }
    .cohort-table td { padding: 4px 6px; text-align: center; border: 1px solid #2a2a3e; font-weight: 600; vertical-align: middle; }
    .cohort-table tr:hover td { opacity: 0.9; }
    .cohort-header { text-align: left !important; background: #1e1e2e; color: #eee; font-weight: 600; min-width: 160px; border-bottom: 1px solid #444; }
    .cohort-sub-header { text-align: left !important; background: #252538; color: #ccc; font-weight: 500; min-width: 160px; font-size: 11px; }
    .cohort-meta { font-size: 10px; color: #aaa; font-weight: 400; }
    .cell-na { background: #1a1a2e; color: #444; }
    .cell-high { background: #2e7d32; color: #fff; }
    .cell-mid-high { background: #558b2f; color: #fff; }
    .cell-mid { background: #f9a825; color: #000; }
    .cell-low { background: #e65100; color: #fff; }
    .cell-very-low { background: #c62828; color: #fff; }
    .cell-zero { background: #1a1a2e; color: #555; }
    .cell-sub { font-size: 9px; font-weight: 400; opacity: 0.7; display: block; margin-top: 1px; }
    .cell-period { font-size: 9px; font-weight: 400; opacity: 0.5; display: block; margin-bottom: 1px; }
    .legend { display: flex; gap: 12px; margin-bottom: 12px; font-size: 12px; align-items: center; flex-wrap: wrap; }
    .legend-item { display: flex; align-items: center; gap: 4px; }
    .legend-box { width: 16px; height: 16px; border-radius: 3px; }
    </style>"""

    html += """<div class="legend">
    <span style="font-weight:600; margin-right:8px;">Conversion:</span>
    <span class="legend-item"><span class="legend-box" style="background:#2e7d32;"></span> &gt;40%</span>
    <span class="legend-item"><span class="legend-box" style="background:#558b2f;"></span> 25-40%</span>
    <span class="legend-item"><span class="legend-box" style="background:#f9a825;"></span> 15-25%</span>
    <span class="legend-item"><span class="legend-box" style="background:#e65100;"></span> 5-15%</span>
    <span class="legend-item"><span class="legend-box" style="background:#c62828;"></span> &lt;5%</span>
    </div>"""

    html += '<div style="overflow-x:auto;"><table class="cohort-table"><thead><tr>'
    html += f'<th style="text-align:left;">{from_label} Cohort</th>'
    for p in period_cols:
        html += f'<th>{prefix}{p}</th>'
    html += '</tr></thead><tbody>'

    # Breakdown column mapping
    BREAKDOWN_COL_MAP = {"Segment": "SEGMENT", "HubSpot Team": "TEAM", "Mega Source": "MEGA_SOURCE", "Deal Source": "DEAL_SOURCE"}
    breakdown_col = BREAKDOWN_COL_MAP.get(cohort_breakdown)

    def render_cohort_row(label, meta, base_val, cum_series, max_p, is_sub=False):
        """Render one HTML row for the cohort table."""
        td_cls = "cohort-sub-header" if is_sub else "cohort-header"
        indent = "&nbsp;&nbsp;&nbsp;" if is_sub else ""
        row = '<tr>'
        row += f'<td class="{td_cls}">{indent}{label}<br><span class="cohort-meta">{indent}{meta}</span></td>'

        for p in period_cols:
            if p > max_p:
                row += '<td class="cell-na"></td>'
            elif cum_series is not None and p in cum_series.index:
                cum_val = cum_series[p]
                pct = (cum_val / base_val * 100) if base_val > 0 else 0

                if pct == 0:
                    row += '<td class="cell-zero">—</td>'
                else:
                    if cohort_to == "Lost":
                        if pct >= 40:
                            cls = "cell-very-low"
                        elif pct >= 25:
                            cls = "cell-low"
                        elif pct >= 15:
                            cls = "cell-mid"
                        elif pct >= 5:
                            cls = "cell-mid-high"
                        else:
                            cls = "cell-high"
                    else:
                        if pct >= 40:
                            cls = "cell-high"
                        elif pct >= 25:
                            cls = "cell-mid-high"
                        elif pct >= 15:
                            cls = "cell-mid"
                        elif pct >= 5:
                            cls = "cell-low"
                        else:
                            cls = "cell-very-low"

                    if cohort_metric == "# (Count)":
                        sub = f'<span class="cell-sub">{int(cum_val)} / {int(base_val)}</span>'
                    else:
                        sub = f'<span class="cell-sub">{fmt_arr(cum_val)}</span>'

                    row += f'<td class="{cls}">{pct:.1f}%{sub}</td>'
            else:
                row += '<td class="cell-zero">—</td>'

        row += '</tr>'
        return row

    for cp in cohorts_sorted:
        cohort_label = format_cohort_label(cp)
        row_base = base_by_cohort.loc[cp]
        deals = int(row_base["base_count"])
        arr = float(row_base["base_arr"])
        meta = f"{deals} deals · {fmt_arr(arr)}"
        max_p = get_max_periods(cp)
        base_val = deals if cohort_metric == "# (Count)" else arr

        # Get cumulative series for this cohort
        cum_series = pivot_cumulative.loc[cp] if cp in pivot_cumulative.index else None

        html += render_cohort_row(cohort_label, meta, base_val, cum_series, max_p, is_sub=False)

        # Breakdown sub-rows
        if breakdown_col:
            cohort_base_deals = df_cohort_base[df_cohort_base["COHORT_PERIOD"] == cp]
            cohort_outcome_deals = df_cohort_outcome[df_cohort_outcome["COHORT_PERIOD"] == cp] if not df_cohort_outcome.empty else pd.DataFrame()
            groups = sorted(cohort_base_deals[breakdown_col].dropna().unique(), key=str)

            for group in groups:
                sub_base = cohort_base_deals[cohort_base_deals[breakdown_col] == group]
                sub_deals = len(sub_base)
                sub_arr = sub_base["DEAL_NET_NEW_ARR"].sum()
                sub_base_val = sub_deals if cohort_metric == "# (Count)" else sub_arr
                sub_meta = f"{sub_deals} deals · {fmt_arr(sub_arr)}"

                # Compute sub-group cumulative
                if not cohort_outcome_deals.empty:
                    sub_outcome = cohort_outcome_deals[cohort_outcome_deals[breakdown_col] == group] if breakdown_col in cohort_outcome_deals.columns else pd.DataFrame()
                    if not sub_outcome.empty:
                        if cohort_metric == "# (Count)":
                            sub_pivot = sub_outcome.groupby("PERIODS_ELAPSED").size()
                        else:
                            sub_pivot = sub_outcome.groupby("PERIODS_ELAPSED")["DEAL_NET_NEW_ARR"].sum()
                        sub_pivot = sub_pivot.reindex(range(0, all_max_col + 1), fill_value=0)
                        sub_cum = sub_pivot.cumsum()
                    else:
                        sub_cum = None
                else:
                    sub_cum = None

                html += render_cohort_row(str(group), sub_meta, sub_base_val, sub_cum, max_p, is_sub=True)

    html += '</tbody></table></div>'
    st.html(html)
    st.caption(f"Filters: {build_filter_caption()}")

    # Drill-down section
    st.markdown("**Drill into deals:**")
    cohort_options = [format_cohort_label(c) for c in cohorts_sorted]
    cohort_ts_map = {format_cohort_label(c): c for c in cohorts_sorted}

    dc1, dc2 = st.columns(2)
    with dc1:
        sel_cohort = st.selectbox(
            "Select Cohort",
            [""] + cohort_options,
            format_func=lambda x: "— Select cohort —" if x == "" else x,
            key="cohort_drill_cohort",
        )
    with dc2:
        period_options = ["All (entire cohort)"] + [f"{prefix}{p}" for p in period_cols]
        sel_period = st.selectbox("Select Period", period_options, key="cohort_drill_period")

    if sel_cohort:
        cohort_ts = cohort_ts_map.get(sel_cohort)
        if cohort_ts is not None:
            if sel_period == "All (entire cohort)":
                cell_deals = df_cohort_outcome[df_cohort_outcome["COHORT_PERIOD"] == cohort_ts]
                st.markdown(f"### Converted deals in cohort `{sel_cohort}` ({len(cell_deals)} deals)")
            else:
                p_val = int(sel_period.split("+")[1])
                cell_deals = df_cohort_outcome[
                    (df_cohort_outcome["COHORT_PERIOD"] == cohort_ts) & (df_cohort_outcome["PERIODS_ELAPSED"] == p_val)
                ]
                st.markdown(f"### Deals in `{sel_cohort}` at `{sel_period}` ({len(cell_deals)} deals)")

            if not cell_deals.empty:
                display_cols = ["COMPANY_NAME", "DEAL_NAME", "DEAL_STAGE", "DEAL_NET_NEW_ARR", "OUTCOME_DATE", "OWNER", "TEAM", "PERIODS_ELAPSED"]
                display_df = cell_deals[[c for c in display_cols if c in cell_deals.columns]].sort_values("OUTCOME_DATE").reset_index(drop=True)
                st.dataframe(display_df, use_container_width=True, hide_index=True)
            else:
                st.info("No deals found for this selection.")

st.markdown("---")

# =============================================================================

# PRIORITY CHARTS (2x2)


# =============================================================================
st.header("Priority Charts")

pri_row1_col1, pri_row1_col2 = st.columns(2)
with pri_row1_col1:
    st.subheader("Trend")
    st.caption("Full-period totals over time — no pacing comparison")

    trend_view = st.selectbox("View", [
        "Created Deals (#)",
        "CVR (Created \u2192 Qualified)",
        "CVR (Qualified \u2192 Closed)",
        "CVR (Qualified \u2192 Won)",
        "CVR (Qualified \u2192 Lost)",
        "Qualified Pipeline (#)",
        "Qualified Pipeline ($)",
        "Closed Won (#)",
        "Closed Won ($)",
        "Closed Lost (#)",
        "Closed Lost ($)",
        "Median Sales Cycle",
        "Win Rate (#)",
        "Win Rate ($)",
    ], key="trend_view")

    trend_gran = st.radio("Granularity", ["Weekly", "Monthly", "Quarterly"], horizontal=True, key="trend_gran")

    # Conversion window and #/$ toggle (shown for all CVR views)
    _t_cvr_window = None
    _t_cvr_mode = "#"
    if trend_view.startswith("CVR"):
        _cvr_opts_col1, _cvr_opts_col2 = st.columns(2)
        with _cvr_opts_col1:
            if trend_view == "CVR (Created \u2192 Qualified)":
                _t_cvr_window = st.selectbox("Time to convert", ["All Time", "1 Week", "1 Month", "1 Quarter"], key="trend_cvr_window")
            else:
                _t_cvr_window = st.selectbox("Time to convert", ["All Time", "1 Month", "1 Quarter", "1 Half", "1 Year"], key="trend_cvr_window")
        with _cvr_opts_col2:
            if trend_view != "CVR (Created \u2192 Qualified)":
                _t_cvr_mode = st.radio("Metric", ["#", "$"], horizontal=True, key="trend_cvr_mode")

    # Determine date column
    if trend_view.startswith("Created Deals") or trend_view == "CVR (Created \u2192 Qualified)":
        _t_date_col = "fd.deal_created_date"
    elif trend_view.startswith("Qualified Pipeline") or "Qualified" in trend_view and trend_view.startswith("CVR"):
        _t_date_col = "fd.qualified_date"
    else:
        _t_date_col = "fd.deal_closed_date"

    # Granularity settings
    if trend_gran == "Quarterly":
        _t_trunc = "QUARTER"
        _t_lookback = 14
    elif trend_gran == "Monthly":
        _t_trunc = "MONTH"
        _t_lookback = 14
    else:
        _t_trunc = "WEEK"
        _t_lookback = 14

    # Period label expression
    if trend_gran == "Quarterly":
        _t_period_label = f"TO_VARCHAR(DATE_TRUNC('QUARTER', {_t_date_col}), 'YYYY') || '-Q' || QUARTER({_t_date_col})"
    elif trend_gran == "Monthly":
        _t_period_label = f"TO_VARCHAR(DATE_TRUNC('MONTH', {_t_date_col}), 'YYYY-MM')"
    else:
        _t_period_label = f"TO_VARCHAR(DATE_TRUNC('WEEK', {_t_date_col}), 'YYYY-MM-DD')"

    # Value expression and filters
    if trend_view == "CVR (Created \u2192 Qualified)":
        _t_extra = ""
        if _t_cvr_window == "1 Week":
            _cvr_case = "CASE WHEN fd.qualified_date IS NOT NULL AND DATEDIFF('day', fd.deal_created_date, fd.qualified_date) <= 7 THEN 1 END"
        elif _t_cvr_window == "1 Month":
            _cvr_case = "CASE WHEN fd.qualified_date IS NOT NULL AND DATEDIFF('day', fd.deal_created_date, fd.qualified_date) <= 30 THEN 1 END"
        elif _t_cvr_window == "1 Quarter":
            _cvr_case = "CASE WHEN fd.qualified_date IS NOT NULL AND DATEDIFF('day', fd.deal_created_date, fd.qualified_date) <= 90 THEN 1 END"
        else:  # All Time
            _cvr_case = "CASE WHEN fd.qualified_date IS NOT NULL THEN 1 END"
        _t_val_expr = f"ROUND(COUNT({_cvr_case})::FLOAT / NULLIF(COUNT(*), 0) * 100, 1)"
        _t_y_title = f"CVR Created\u2192Qualified ({_t_cvr_window}) %"
        _t_y_fmt = ".1f"
        _t_label_fmt = ".1f"
        _t_cvr_numerator_label = "Qualified Deals"
    elif trend_view in ("CVR (Qualified \u2192 Closed)", "CVR (Qualified \u2192 Won)", "CVR (Qualified \u2192 Lost)"):
        _t_extra = "AND fd.qualified_date IS NOT NULL"
        if _t_cvr_mode == "$":
            _t_extra += " AND fd.deal_net_new_arr > 0"
        # Determine outcome condition
        if "Won" in trend_view:
            _outcome_cond = "fd.is_won = TRUE"
            _outcome_label = "Won"
        elif "Lost" in trend_view:
            _outcome_cond = "fd.is_won = FALSE AND fd.is_closed = TRUE"
            _outcome_label = "Lost"
        else:  # Closed (won or lost)
            _outcome_cond = "fd.is_closed = TRUE"
            _outcome_label = "Closed"
        # Time window
        if _t_cvr_window == "1 Month":
            _time_cond = "AND DATEDIFF('day', fd.qualified_date, fd.deal_closed_date) <= 30"
        elif _t_cvr_window == "1 Quarter":
            _time_cond = "AND DATEDIFF('day', fd.qualified_date, fd.deal_closed_date) <= 90"
        elif _t_cvr_window == "1 Half":
            _time_cond = "AND DATEDIFF('day', fd.qualified_date, fd.deal_closed_date) <= 180"
        elif _t_cvr_window == "1 Year":
            _time_cond = "AND DATEDIFF('day', fd.qualified_date, fd.deal_closed_date) <= 365"
        else:  # All Time
            _time_cond = "AND fd.deal_closed_date IS NOT NULL"

        if _t_cvr_mode == "$":
            _cvr_case = f"CASE WHEN {_outcome_cond} {_time_cond} THEN fd.deal_net_new_arr END"
            _t_val_expr = f"ROUND(COALESCE(SUM({_cvr_case}), 0)::FLOAT / NULLIF(SUM(fd.deal_net_new_arr), 0) * 100, 1)"
            _t_y_title = f"CVR $ Qualified\u2192{_outcome_label} ({_t_cvr_window}) %"
            _t_cvr_numerator_label = f"{_outcome_label} ARR"
        else:
            _cvr_case = f"CASE WHEN {_outcome_cond} {_time_cond} THEN 1 END"
            _t_val_expr = f"ROUND(COUNT({_cvr_case})::FLOAT / NULLIF(COUNT(*), 0) * 100, 1)"
            _t_y_title = f"CVR Qualified\u2192{_outcome_label} ({_t_cvr_window}) %"
            _t_cvr_numerator_label = f"{_outcome_label} Deals"
        _t_y_fmt = ".1f"
        _t_label_fmt = ".1f"
    elif trend_view == "Created Deals (#)":
        _t_extra = ""
        _t_val_expr = "COUNT(*)"
        _t_y_title = "Created Deals (#)"
        _t_y_fmt = ",.0f"
        _t_label_fmt = ",.0f"
    elif trend_view == "Qualified Pipeline (#)":
        _t_extra = "AND fd.qualified_date IS NOT NULL"
        _t_val_expr = "COUNT(*)"
        _t_y_title = "Deals Qualified (#)"
        _t_y_fmt = ",.0f"
        _t_label_fmt = ",.0f"
    elif trend_view == "Qualified Pipeline ($)":
        _t_extra = "AND fd.qualified_date IS NOT NULL"
        _t_val_expr = "SUM(fd.deal_net_new_arr)"
        _t_y_title = "Qualified ARR ($)"
        _t_y_fmt = "$,.2f"
        _t_label_fmt = "$.3s"
    elif trend_view == "Closed Won (#)":
        _t_extra = "AND fd.is_won = TRUE"
        _t_val_expr = "COUNT(*)"
        _t_y_title = "Won Deals (#)"
        _t_y_fmt = ",.0f"
        _t_label_fmt = ",.0f"
    elif trend_view == "Closed Won ($)":
        _t_extra = "AND fd.is_won = TRUE"
        _t_val_expr = "SUM(fd.deal_net_new_arr)"
        _t_y_title = "Won ARR ($)"
        _t_y_fmt = "$,.2f"
        _t_label_fmt = "$.3s"
    elif trend_view == "Closed Lost (#)":
        _t_extra = "AND fd.is_won = FALSE AND fd.is_closed = TRUE"
        _t_val_expr = "COUNT(*)"
        _t_y_title = "Lost Deals (#)"
        _t_y_fmt = ",.0f"
        _t_label_fmt = ",.0f"
    elif trend_view == "Closed Lost ($)":
        _t_extra = "AND fd.is_won = FALSE AND fd.is_closed = TRUE"
        _t_val_expr = "SUM(fd.deal_net_new_arr)"
        _t_y_title = "Lost ARR ($)"
        _t_y_fmt = "$,.2f"
        _t_label_fmt = "$.3s"
    elif trend_view == "Median Sales Cycle":
        _t_val_expr = "MEDIAN(DATEDIFF('day', fd.qualified_date, fd.deal_closed_date))"
        _t_extra = "AND fd.is_closed = TRUE AND fd.qualified_date IS NOT NULL"
        _t_y_title = "Median Days (Qualify -> Close)"
        _t_y_fmt = ",.0f"
        _t_label_fmt = ",.0f"
    elif trend_view == "Win Rate (#)":
        _t_val_expr = "ROUND(COUNT(CASE WHEN fd.is_won = TRUE THEN 1 END)::FLOAT / NULLIF(COUNT(*), 0) * 100, 1)"
        _t_extra = "AND fd.is_closed = TRUE AND fd.qualified_date IS NOT NULL"
        _t_y_title = "Win Rate - Count (%)"
        _t_y_fmt = ".1f"
        _t_label_fmt = ".1f"
    else:  # Win Rate ($)
        _t_val_expr = "ROUND(SUM(CASE WHEN fd.is_won = TRUE THEN fd.deal_net_new_arr END)::FLOAT / NULLIF(SUM(fd.deal_net_new_arr), 0) * 100, 1)"
        _t_extra = "AND fd.is_closed = TRUE AND fd.qualified_date IS NOT NULL"
        _t_y_title = "Win Rate - ARR (%)"
        _t_y_fmt = ".1f"
        _t_label_fmt = ".1f"

    # Breakdown
    if cohort_breakdown == "Segment":
        _t_bd_col = "dc.segment"
    elif cohort_breakdown == "HubSpot Team":
        _t_bd_col = "fd.deal_team_name"
    elif cohort_breakdown == "Mega Source":
        _t_bd_col = "fd.mega_source"
    elif cohort_breakdown == "Deal Source":
        _t_bd_col = "fd.deal_source"
    elif cohort_breakdown == "Won/Lost":
        _t_bd_col = "CASE WHEN fd.is_won = TRUE THEN 'Won' WHEN fd.is_closed = TRUE THEN 'Lost' ELSE 'Open' END"
    else:
        _t_bd_col = None

    _t_select_bd = f", COALESCE({_t_bd_col}, 'Unknown') AS breakdown" if _t_bd_col else ""
    _t_group_bd = ", 2" if _t_bd_col else ""

    # Extra columns for CVR tooltip (total deals, converted deals)
    _t_extra_cols = ""
    if trend_view.startswith("CVR"):
        if _t_cvr_mode == "$":
            _t_extra_cols = f", ROUND(SUM(fd.deal_net_new_arr))::INT AS total_deals, ROUND(COALESCE(SUM({_cvr_case}), 0))::INT AS converted_deals"
        else:
            _t_extra_cols = f", COUNT(*) AS total_deals, COUNT({_cvr_case}) AS converted_deals"
    elif trend_view == "Median Sales Cycle":
        _t_extra_cols = ", COUNT(*) AS closed_deals"

    trend_sql = f"""
    SELECT
        {_t_period_label} AS period_label{_t_select_bd},
        {_t_val_expr} AS period_value{_t_extra_cols}
    FROM {DWH}.FACT_DEALS fd
    LEFT JOIN {DWH}.DIM_COMPANY dc
        ON fd.sk_company = dc.sk_company
       AND COALESCE(dc.company_name, '') NOT ILIKE '%test%'
       AND COALESCE(dc.company_name, '') != 'Port'
       AND dc._is_deleted = FALSE
       AND dc.archived = FALSE
    LEFT JOIN {DWH}.DIM_EMPLOYEE de
        ON fd.sk_sales_owner = de.sk_employee
    WHERE 1=1
      {"AND fd.deal_net_new_arr > 0" if not trend_view.startswith("Created Deals") and not trend_view.startswith("CVR") else ""}
      {_t_extra}
      AND {_t_date_col} >= DATEADD('{_t_trunc}', -{_t_lookback}, DATE_TRUNC('{_t_trunc}', {SNAPSHOT_DATE_SQL}))
      AND {_t_date_col} < {WEEK_CUTOFF_SQL}
      {build_global_filters_sql(has_employee_join=True)}
    GROUP BY 1{_t_group_bd}
    ORDER BY 1
    """

    df_trend = run_query(trend_sql)

    if not df_trend.empty:
        df_trend["PERIOD_VALUE"] = pd.to_numeric(df_trend["PERIOD_VALUE"], errors="coerce").fillna(0)
        _t_has_bd = _t_bd_col is not None and "BREAKDOWN" in df_trend.columns

        # Fill missing periods
        if trend_gran == "Weekly":
            _t_start = pd.to_datetime(df_trend["PERIOD_LABEL"].min())
            _t_end_data = pd.to_datetime(df_trend["PERIOD_LABEL"].max())
            _t_end_expected = pd.Timestamp.today().normalize() - pd.Timedelta(days=pd.Timestamp.today().weekday()) - pd.Timedelta(days=7)
            _t_end = max(_t_end_data, _t_end_expected)
            _t_all_periods = pd.date_range(_t_start, _t_end, freq="W-MON").strftime("%Y-%m-%d").tolist()
        elif trend_gran == "Monthly":
            _t_start = pd.to_datetime(df_trend["PERIOD_LABEL"].min() + "-01")
            _t_end_data = pd.to_datetime(df_trend["PERIOD_LABEL"].max() + "-01")
            _t_end_expected = (pd.Timestamp.today().normalize().replace(day=1) - pd.Timedelta(days=1)).replace(day=1)
            _t_end = max(_t_end_data, _t_end_expected)
            _t_all_periods = pd.date_range(_t_start, _t_end, freq="MS").strftime("%Y-%m").tolist()
        else:
            _t_q_start = pd.to_datetime(df_trend["PERIOD_LABEL"].str.replace(r"(\d{4})-Q(\d)", lambda m: f"{m.group(1)}-{int(m.group(2))*3-2:02d}-01", regex=True).min())
            _t_q_end = pd.to_datetime(df_trend["PERIOD_LABEL"].str.replace(r"(\d{4})-Q(\d)", lambda m: f"{m.group(1)}-{int(m.group(2))*3-2:02d}-01", regex=True).max())
            _t_all_periods = [f"{d.year}-Q{d.quarter}" for d in pd.date_range(_t_q_start, _t_q_end, freq="QS")]

        if _t_has_bd:
            _t_bds = df_trend["BREAKDOWN"].unique().tolist()
            _t_full_idx = pd.MultiIndex.from_product([_t_all_periods, _t_bds], names=["PERIOD_LABEL", "BREAKDOWN"])
            df_trend = df_trend.set_index(["PERIOD_LABEL", "BREAKDOWN"]).reindex(_t_full_idx, fill_value=0).reset_index()
        else:
            _t_full = pd.DataFrame({"PERIOD_LABEL": _t_all_periods})
            df_trend = _t_full.merge(df_trend, on="PERIOD_LABEL", how="left").fillna(0)

        _t_label_order = sorted(df_trend["PERIOD_LABEL"].unique().tolist())
        _t_gran_label = trend_gran.rstrip("ly") if trend_gran != "Weekly" else "Week"
        if trend_view.startswith("Created Deals") or trend_view == "CVR (Created \u2192 Qualified)":
            _t_x_title = f"Create Date ({_t_gran_label})"
        elif trend_view.startswith("Qualified Pipeline") or trend_view.startswith("CVR (Qualified") or trend_view.startswith("CVR $ (Qualified"):
            _t_x_title = f"Qualify Date ({_t_gran_label})"
        else:
            _t_x_title = f"Close Date ({_t_gran_label})"
        _t_chart_color = "#EF553B" if "Lost" in trend_view else "#636EFA"

        # Build tooltip list — add deal counts for CVR view
        _t_tooltip_base = [alt.Tooltip("PERIOD_LABEL:N", title="Period")]
        if _t_has_bd:
            _t_tooltip_base.append(alt.Tooltip("BREAKDOWN:N", title=cohort_breakdown))
        _t_tooltip_base.append(alt.Tooltip("PERIOD_VALUE:Q", title=_t_y_title, format=_t_y_fmt))
        if trend_view.startswith("CVR") and "TOTAL_DEALS" in df_trend.columns:
            if _t_cvr_mode == "$":
                _t_tooltip_base.append(alt.Tooltip("TOTAL_DEALS:Q", title="Total ARR", format="$.3s"))
                _t_tooltip_base.append(alt.Tooltip("CONVERTED_DEALS:Q", title=_t_cvr_numerator_label, format="$.3s"))
            else:
                _t_tooltip_base.append(alt.Tooltip("TOTAL_DEALS:Q", title="Total Deals", format=",.0f"))
                _t_tooltip_base.append(alt.Tooltip("CONVERTED_DEALS:Q", title=_t_cvr_numerator_label, format=",.0f"))
        elif trend_view == "Median Sales Cycle" and "CLOSED_DEALS" in df_trend.columns:
            _t_tooltip_base.append(alt.Tooltip("CLOSED_DEALS:Q", title="Closed Deals", format=",.0f"))

        if _t_has_bd:
            _t_legend_selection = alt.selection_point(fields=["BREAKDOWN"], bind="legend")
            # End-of-line labels: show breakdown name at the last period
            _t_last_period = _t_label_order[-1] if _t_label_order else None
            _t_label_df = df_trend[df_trend["PERIOD_LABEL"] == _t_last_period] if _t_last_period else df_trend.head(0)
            trend_chart = (
                alt.Chart(df_trend)
                .mark_line(point=alt.OverlayMarkDef(size=40), strokeWidth=2)
                .encode(
                    x=alt.X("PERIOD_LABEL:N", title=_t_x_title, sort=_t_label_order, axis=alt.Axis(labelAngle=-45)),
                    y=alt.Y("PERIOD_VALUE:Q", title=_t_y_title, axis=alt.Axis(format="~s") if "ARR" in _t_y_title else alt.Axis()),
                    color=alt.Color("BREAKDOWN:N", title=cohort_breakdown, legend=alt.Legend(orient="bottom")),
                    opacity=alt.condition(_t_legend_selection, alt.value(1), alt.value(0.1)),
                    tooltip=_t_tooltip_base,
                )
                .add_params(_t_legend_selection)
                .properties(height=350)
            )
            _t_end_labels = (
                alt.Chart(_t_label_df)
                .mark_text(align="left", dx=5, fontSize=10)
                .encode(
                    x=alt.X("PERIOD_LABEL:N", sort=_t_label_order),
                    y=alt.Y("PERIOD_VALUE:Q"),
                    text=alt.Text("BREAKDOWN:N"),
                    color=alt.Color("BREAKDOWN:N", legend=None),
                    opacity=alt.condition(_t_legend_selection, alt.value(1), alt.value(0.1)),
                )
                .add_params(_t_legend_selection)
            )
            st.altair_chart(trend_chart + _t_end_labels, use_container_width=True)
        else:
            trend_chart = (
                alt.Chart(df_trend)
                .mark_line(point=alt.OverlayMarkDef(size=40), strokeWidth=2, color=_t_chart_color)
                .encode(
                    x=alt.X("PERIOD_LABEL:N", title=_t_x_title, sort=_t_label_order, axis=alt.Axis(labelAngle=-45)),
                    y=alt.Y("PERIOD_VALUE:Q", title=_t_y_title, axis=alt.Axis(format="~s") if "ARR" in _t_y_title else alt.Axis()),
                    tooltip=_t_tooltip_base,
                )
                .properties(height=350)
            )
            _t_labels = (
                alt.Chart(df_trend)
                .mark_text(dy=-12, fontSize=10, color="#eee")
                .encode(
                    x=alt.X("PERIOD_LABEL:N", sort=_t_label_order),
                    y=alt.Y("PERIOD_VALUE:Q"),
                    text=alt.Text("PERIOD_VALUE:Q", format=_t_label_fmt),
                )
            )
            st.altair_chart(trend_chart + _t_labels, use_container_width=True)
        st.caption(f"Full completed periods · {build_filter_caption()}")

        with st.expander("Show raw data", expanded=False):
            _raw_col1, _raw_col2 = st.columns(2)
            with _raw_col1:
                _raw_periods = sorted(df_trend["PERIOD_LABEL"].unique().tolist(), reverse=True)
                _raw_sel_period = st.selectbox("Period", ["All"] + _raw_periods, key="trend_raw_period")
            with _raw_col2:
                if _t_has_bd and "BREAKDOWN" in df_trend.columns:
                    _raw_bds = sorted(df_trend["BREAKDOWN"].dropna().unique().tolist())
                    _raw_sel_bd = st.selectbox(cohort_breakdown, ["All"] + _raw_bds, key="trend_raw_bd")
                else:
                    _raw_sel_bd = "All"

            # Build deal-level query
            _raw_period_filter = ""
            if _raw_sel_period != "All":
                _raw_period_filter = f"AND {_t_period_label} = '{_raw_sel_period}'"

            _raw_bd_filter = ""
            if _raw_sel_bd != "All" and _t_bd_col:
                _raw_bd_filter = f"AND COALESCE({_t_bd_col}, 'Unknown') = '{_raw_sel_bd}'"

            _raw_sql = f"""
            SELECT
                fd.deal_name,
                dc.company_name,
                de.display_name AS owner,
                fd.deal_team_name AS hubspot_team,
                dc.segment,
                fd.deal_net_new_arr,
                fd.deal_created_date::DATE AS created_date,
                fd.qualified_date::DATE AS qualified_date,
                fd.deal_closed_date::DATE AS closed_date,
                fd.deal_stage,
                fd.is_won,
                fd.mega_source,
                fd.deal_source,
                {_t_period_label} AS period_label
            FROM {DWH}.FACT_DEALS fd
            LEFT JOIN {DWH}.DIM_COMPANY dc
                ON fd.sk_company = dc.sk_company
               AND COALESCE(dc.company_name, '') NOT ILIKE '%test%'
               AND COALESCE(dc.company_name, '') != 'Port'
               AND dc._is_deleted = FALSE
               AND dc.archived = FALSE
            LEFT JOIN {DWH}.DIM_EMPLOYEE de
                ON fd.sk_sales_owner = de.sk_employee
            WHERE 1=1
              {"AND fd.deal_net_new_arr > 0" if not trend_view.startswith("Created Deals") and not trend_view.startswith("CVR") else ""}
              {_t_extra}
              AND {_t_date_col} >= DATEADD('{_t_trunc}', -{_t_lookback}, DATE_TRUNC('{_t_trunc}', {SNAPSHOT_DATE_SQL}))
              AND {_t_date_col} < {WEEK_CUTOFF_SQL}
              {build_global_filters_sql(has_employee_join=True)}
              {_raw_period_filter}
              {_raw_bd_filter}
            ORDER BY {_t_date_col} DESC
            LIMIT 500
            """
            _df_raw = run_query(_raw_sql)
            if not _df_raw.empty:
                st.dataframe(_df_raw, use_container_width=True, hide_index=True)
            else:
                st.info("No deals found for this selection.")
    else:
        st.warning("No trend data returned for selected filters.")

with pri_row1_col2:
    st.subheader("Pacing")
    st.caption("Compare same day-in-period across periods — apples-to-apples pacing")

    pacing_view = st.selectbox("View", [
        "Created Deals (#)",
        "Qualified Pipeline (#)",
        "Qualified Pipeline ($)",
        "Closed Won (#)",
        "Closed Won ($)",
        "Closed Lost (#)",
        "Closed Lost ($)",
        "Median Sales Cycle",
        "Win Rate (#)",
        "Win Rate ($)",
    ], key="pacing_view")

    pacing_gran = st.radio("Granularity", ["Monthly", "Quarterly"], horizontal=True, key="pacing_gran")

    # Calculate current day-in-period for pacing cutoff
    _pacing_today = pd.Timestamp.today()
    _pacing_cutoff_date = (_pacing_today - pd.Timedelta(days=_pacing_today.weekday()) - pd.Timedelta(days=1))
    _cutoff_from_sf = conn.query(f"SELECT ({WEEK_CUTOFF_SQL} - INTERVAL '1 DAY')::DATE AS d").iloc[0]["D"]
    st.caption(f"Data up to {_cutoff_from_sf.strftime('%B %d, %Y') if hasattr(_cutoff_from_sf, 'strftime') else _cutoff_from_sf} (end of last full week)")
    if pacing_gran == "Quarterly":
        _pacing_q_start = pd.Timestamp(_pacing_today.year, ((_pacing_today.quarter - 1) * 3) + 1, 1)
        _days_into_period = (_pacing_today - _pacing_q_start).days
        trunc_unit = "QUARTER"
        lookback_periods = 14
    elif pacing_gran == "Monthly":
        _pacing_m_start = pd.Timestamp(_pacing_today.year, _pacing_today.month, 1)
        _days_into_period = (_pacing_today - _pacing_m_start).days
        trunc_unit = "MONTH"
        lookback_periods = 14
    else:  # Weekly
        _pacing_w_start = _pacing_today - pd.Timedelta(days=_pacing_today.weekday())
        _days_into_period = (_pacing_today - _pacing_w_start).days
        trunc_unit = "WEEK"
        lookback_periods = 14

    # Build period label expression based on granularity
    # For qualified pipeline views, use qualified_date; for closed views, use deal_closed_date
    if pacing_view.startswith("Created Deals"):
        _date_col = "fd.deal_created_date"
    elif pacing_view.startswith("Qualified Pipeline"):
        _date_col = "fd.qualified_date"
    else:
        _date_col = "fd.deal_closed_date"

    if pacing_gran == "Quarterly":
        period_label_expr = f"TO_VARCHAR(DATE_TRUNC('QUARTER', {_date_col}), 'YYYY') || '-Q' || QUARTER({_date_col})"
    elif pacing_gran == "Monthly":
        period_label_expr = f"TO_VARCHAR(DATE_TRUNC('MONTH', {_date_col}), 'YYYY-MM')"
    else:
        period_label_expr = f"TO_VARCHAR(DATE_TRUNC('WEEK', {_date_col}), 'YYYY-MM-DD')"

    # Build value expression and filters based on pacing_view
    if pacing_view == "Created Deals (#)":
        extra_where = ""
        pacing_val_expr = "COUNT(*)"
        y_title = "Created Deals (#)"
        y_fmt = ",.0f"
        label_fmt = ",.0f"
    elif pacing_view == "Qualified Pipeline (#)":
        extra_where = "AND fd.qualified_date IS NOT NULL"
        pacing_val_expr = "COUNT(*)"
        y_title = "Deals Qualified (#)"
        y_fmt = ",.0f"
        label_fmt = ",.0f"
    elif pacing_view == "Qualified Pipeline ($)":
        extra_where = "AND fd.qualified_date IS NOT NULL"
        pacing_val_expr = "SUM(fd.deal_net_new_arr)"
        y_title = "Qualified ARR ($)"
        y_fmt = "$,.2f"
        label_fmt = "$.3s"
    elif pacing_view == "Closed Won (#)":
        extra_where = "AND fd.is_won = TRUE"
        pacing_val_expr = "COUNT(*)"
        y_title = "Won Deals (#)"
        y_fmt = ",.0f"
        label_fmt = ",.0f"
    elif pacing_view == "Closed Won ($)":
        extra_where = "AND fd.is_won = TRUE"
        pacing_val_expr = "SUM(fd.deal_net_new_arr)"
        y_title = "Won ARR ($)"
        y_fmt = "$,.2f"
        label_fmt = "$.3s"
    elif pacing_view == "Closed Lost (#)":
        extra_where = "AND fd.is_won = FALSE AND fd.is_closed = TRUE"
        pacing_val_expr = "COUNT(*)"
        y_title = "Lost Deals (#)"
        y_fmt = ",.0f"
        label_fmt = ",.0f"
    elif pacing_view == "Closed Lost ($)":
        extra_where = "AND fd.is_won = FALSE AND fd.is_closed = TRUE"
        pacing_val_expr = "SUM(fd.deal_net_new_arr)"
        y_title = "Lost ARR ($)"
        y_fmt = "$,.2f"
        label_fmt = "$.3s"
    elif pacing_view == "Median Sales Cycle":
        pacing_val_expr = "MEDIAN(DATEDIFF('day', fd.qualified_date, fd.deal_closed_date))"
        extra_where = "AND fd.is_closed = TRUE AND fd.qualified_date IS NOT NULL"
        y_title = "Median Days (Qualify → Close)"
        y_fmt = ",.0f"
        label_fmt = ",.0f"
    elif pacing_view == "Win Rate (#)":
        pacing_val_expr = "ROUND(COUNT(CASE WHEN fd.is_won = TRUE THEN 1 END)::FLOAT / NULLIF(COUNT(*), 0) * 100, 1)"
        extra_where = "AND fd.is_closed = TRUE AND fd.qualified_date IS NOT NULL"
        y_title = "Win Rate - Count (%)"
        y_fmt = ".1f"
        label_fmt = ".1f"
    else:  # Win Rate ($)
        pacing_val_expr = "ROUND(SUM(CASE WHEN fd.is_won = TRUE THEN fd.deal_net_new_arr END)::FLOAT / NULLIF(SUM(fd.deal_net_new_arr), 0) * 100, 1)"
        extra_where = "AND fd.is_closed = TRUE AND fd.qualified_date IS NOT NULL"
        y_title = "Win Rate - ARR (%)"
        y_fmt = ".1f"
        label_fmt = ".1f"

    # Determine breakdown column for SQL
    if cohort_breakdown == "Segment":
        _breakdown_sql_col = "dc.segment"
        _breakdown_alias = "breakdown"
    elif cohort_breakdown == "HubSpot Team":
        _breakdown_sql_col = "fd.deal_team_name"
        _breakdown_alias = "breakdown"
    elif cohort_breakdown == "Mega Source":
        _breakdown_sql_col = "fd.mega_source"
        _breakdown_alias = "breakdown"
    elif cohort_breakdown == "Deal Source":
        _breakdown_sql_col = "fd.deal_source"
        _breakdown_alias = "breakdown"
    elif cohort_breakdown == "Won/Lost":
        _breakdown_sql_col = "CASE WHEN fd.is_won = TRUE THEN 'Won' WHEN fd.is_closed = TRUE THEN 'Lost' ELSE 'Open' END"
        _breakdown_alias = "breakdown"
    else:
        _breakdown_sql_col = None
        _breakdown_alias = None

    _select_breakdown = f", COALESCE({_breakdown_sql_col}, 'Unknown') AS {_breakdown_alias}" if _breakdown_sql_col else ""
    _group_breakdown = ", 2" if _breakdown_sql_col else ""

    # All views cap at WEEK_CUTOFF_SQL = start of current week (Monday)
    # This ensures only completed Mon-Sun weeks are shown.
    # For weekly: no day-in-period filter (full weeks only)
    # For monthly/quarterly: apply day-in-period pacing relative to the last full Sunday
    _pacing_date_cap = WEEK_CUTOFF_SQL
    if pacing_gran == "Weekly":
        _pacing_day_filter = ""
    else:
        # For QoQ/MoM pacing: compute days into period based on last Sunday (end of last full week)
        _last_sunday = _pacing_today - pd.Timedelta(days=_pacing_today.weekday() + 1) if _pacing_today.weekday() != 6 else _pacing_today
        if pacing_gran == "Quarterly":
            _period_start = pd.Timestamp(_last_sunday.year, ((_last_sunday.quarter - 1) * 3) + 1, 1)
        else:
            _period_start = pd.Timestamp(_last_sunday.year, _last_sunday.month, 1)
        _days_into_period = (_last_sunday - _period_start).days
        _pacing_day_filter = f"AND DATEDIFF('day', DATE_TRUNC('{trunc_unit}', {_date_col}), {_date_col}) <= {_days_into_period}"

    pacing_cutoff_sql = f"""
    SELECT
        {period_label_expr} AS period_label{_select_breakdown},
        {pacing_val_expr} AS period_value
    FROM {DWH}.FACT_DEALS fd
    LEFT JOIN {DWH}.DIM_COMPANY dc
        ON fd.sk_company = dc.sk_company
       AND COALESCE(dc.company_name, '') NOT ILIKE '%test%'
       AND COALESCE(dc.company_name, '') != 'Port'
       AND dc._is_deleted = FALSE
       AND dc.archived = FALSE
    LEFT JOIN {DWH}.DIM_EMPLOYEE de
        ON fd.sk_sales_owner = de.sk_employee
    WHERE 1=1
      {"AND fd.deal_net_new_arr > 0" if pacing_view != "Created Deals (#)" else ""}
    

      {extra_where}
      AND {_date_col} >= DATEADD('{trunc_unit}', -{lookback_periods}, DATE_TRUNC('{trunc_unit}', {SNAPSHOT_DATE_SQL}))
      AND {_date_col} < {_pacing_date_cap}
      {_pacing_day_filter}
      {build_global_filters_sql(has_employee_join=True)}
    GROUP BY 1{_group_breakdown}
    ORDER BY 1
    """

    df_pacing_cutoff = run_query(pacing_cutoff_sql)

    if not df_pacing_cutoff.empty:
        df_pacing_cutoff["PERIOD_VALUE"] = pd.to_numeric(df_pacing_cutoff["PERIOD_VALUE"], errors="coerce").fillna(0)
        _has_breakdown = _breakdown_sql_col is not None and "BREAKDOWN" in df_pacing_cutoff.columns

        # Fill missing periods with 0 so chart has no gaps
        # Always extend to the last full period (even if no data exists there)
        if pacing_gran == "Weekly":
            _start = pd.to_datetime(df_pacing_cutoff["PERIOD_LABEL"].min())
            _end_data = pd.to_datetime(df_pacing_cutoff["PERIOD_LABEL"].max())
            _end_expected = pd.Timestamp.today().normalize() - pd.Timedelta(days=pd.Timestamp.today().weekday(), unit='D')
            _end_expected -= pd.Timedelta(days=7)  # last FULL week start
            _end = max(_end_data, _end_expected)
            all_periods = pd.date_range(_start, _end, freq="W-MON").strftime("%Y-%m-%d").tolist()
        elif pacing_gran == "Monthly":
            _start = pd.to_datetime(df_pacing_cutoff["PERIOD_LABEL"].min() + "-01")
            _end_data = pd.to_datetime(df_pacing_cutoff["PERIOD_LABEL"].max() + "-01")
            _end_expected = (pd.Timestamp.today().normalize().replace(day=1) - pd.Timedelta(days=1)).replace(day=1)
            _end = max(_end_data, _end_expected)
            all_periods = pd.date_range(_start, _end, freq="MS").strftime("%Y-%m").tolist()
        else:  # Quarterly - generate all quarters in range
            _q_start = pd.to_datetime(df_pacing_cutoff["PERIOD_LABEL"].str.replace(r"(\d{4})-Q(\d)", lambda m: f"{m.group(1)}-{int(m.group(2))*3-2:02d}-01", regex=True).min())
            _q_end = pd.to_datetime(df_pacing_cutoff["PERIOD_LABEL"].str.replace(r"(\d{4})-Q(\d)", lambda m: f"{m.group(1)}-{int(m.group(2))*3-2:02d}-01", regex=True).max())
            all_periods = [f"{d.year}-Q{d.quarter}" for d in pd.date_range(_q_start, _q_end, freq="QS")]

        if _has_breakdown:
            # Fill gaps per breakdown group
            breakdowns = df_pacing_cutoff["BREAKDOWN"].unique().tolist()
            full_index = pd.MultiIndex.from_product([all_periods, breakdowns], names=["PERIOD_LABEL", "BREAKDOWN"])
            df_pacing_cutoff = df_pacing_cutoff.set_index(["PERIOD_LABEL", "BREAKDOWN"]).reindex(full_index, fill_value=0).reset_index()
        else:
            full_index = pd.DataFrame({"PERIOD_LABEL": all_periods})
            df_pacing_cutoff = full_index.merge(df_pacing_cutoff, on="PERIOD_LABEL", how="left").fillna(0)

        label_order = sorted(df_pacing_cutoff["PERIOD_LABEL"].unique().tolist())
        x_title = pacing_gran.rstrip("ly") if pacing_gran != "Weekly" else "Week"

        # Chart color based on view type
        _chart_color = "#EF553B" if "Lost" in pacing_view else "#00CC96"

        if _has_breakdown:
            # Multi-line chart split by breakdown dimension
            _p_legend_selection = alt.selection_point(fields=["BREAKDOWN"], bind="legend")
            _p_last_period = label_order[-1] if label_order else None
            _p_label_df = df_pacing_cutoff[df_pacing_cutoff["PERIOD_LABEL"] == _p_last_period] if _p_last_period else df_pacing_cutoff.head(0)
            pacing_chart = (
                alt.Chart(df_pacing_cutoff)
                .mark_line(point=alt.OverlayMarkDef(size=40), strokeWidth=2)
                .encode(
                    x=alt.X("PERIOD_LABEL:N", title=x_title, sort=label_order, axis=alt.Axis(labelAngle=-45)),
                    y=alt.Y("PERIOD_VALUE:Q", title=y_title, axis=alt.Axis(format="~s") if "ARR" in y_title else alt.Axis()),
                    color=alt.Color("BREAKDOWN:N", title=cohort_breakdown, legend=alt.Legend(orient="bottom")),
                    opacity=alt.condition(_p_legend_selection, alt.value(1), alt.value(0.1)),
                    tooltip=[
                        alt.Tooltip("PERIOD_LABEL:N", title="Period"),
                        alt.Tooltip("BREAKDOWN:N", title=cohort_breakdown),
                        alt.Tooltip("PERIOD_VALUE:Q", title=y_title, format=y_fmt),
                    ],
                )
                .add_params(_p_legend_selection)
                .properties(height=350)
            )
            _p_end_labels = (
                alt.Chart(_p_label_df)
                .mark_text(align="left", dx=5, fontSize=10)
                .encode(
                    x=alt.X("PERIOD_LABEL:N", sort=label_order),
                    y=alt.Y("PERIOD_VALUE:Q"),
                    text=alt.Text("BREAKDOWN:N"),
                    color=alt.Color("BREAKDOWN:N", legend=None),
                    opacity=alt.condition(_p_legend_selection, alt.value(1), alt.value(0.1)),
                )
                .add_params(_p_legend_selection)
            )
            st.altair_chart(pacing_chart + _p_end_labels, use_container_width=True)
        else:
            # Single line chart
            pacing_chart = (
                alt.Chart(df_pacing_cutoff)
                .mark_line(point=alt.OverlayMarkDef(size=40), strokeWidth=2, color=_chart_color)
                .encode(
                    x=alt.X("PERIOD_LABEL:N", title=x_title, sort=label_order, axis=alt.Axis(labelAngle=-45)),
                    y=alt.Y("PERIOD_VALUE:Q", title=y_title, axis=alt.Axis(format="~s") if "ARR" in y_title else alt.Axis()),
                    tooltip=[
                        alt.Tooltip("PERIOD_LABEL:N", title="Period"),
                        alt.Tooltip("PERIOD_VALUE:Q", title=y_title, format=y_fmt),
                    ],
                )
                .properties(height=350)
            )
            labels = (
                alt.Chart(df_pacing_cutoff)
                .mark_text(dy=-12, fontSize=10, color="#eee")
                .encode(
                    x=alt.X("PERIOD_LABEL:N", sort=label_order),
                    y=alt.Y("PERIOD_VALUE:Q"),
                    text=alt.Text("PERIOD_VALUE:Q", format=label_fmt),
                )
            )
            st.altair_chart(pacing_chart + labels, use_container_width=True)
        _period_name = pacing_gran.lower().rstrip("ly") if pacing_gran != "Weekly" else "week"
        if pacing_gran == "Weekly":
            st.caption(f"Full completed weeks · {build_filter_caption()}")
        else:
            st.caption(f"Pacing: first {_days_into_period} days of each {_period_name} · {build_filter_caption()}")

        with st.expander("Show raw deal data", expanded=False):
            # Deal-level query for the raw data
            pacing_detail_sql = f"""
            SELECT
                fd.deal_name,
                dc.company_name,
                de.display_name AS owner,
                fd.deal_team_name AS hubspot_team,
                dc.segment,
                fd.deal_net_new_arr,
                fd.qualified_date::DATE AS qualified_date,
                fd.deal_closed_date::DATE AS closed_date,
                fd.deal_stage,
                fd.is_won,
                {period_label_expr} AS period_label
            FROM {DWH}.FACT_DEALS fd
            LEFT JOIN {DWH}.DIM_COMPANY dc
                ON fd.sk_company = dc.sk_company
               AND COALESCE(dc.company_name, '') NOT ILIKE '%test%'
               AND COALESCE(dc.company_name, '') != 'Port'
               AND dc._is_deleted = FALSE
               AND dc.archived = FALSE
            LEFT JOIN {DWH}.DIM_EMPLOYEE de
                ON fd.sk_sales_owner = de.sk_employee
            WHERE fd.deal_net_new_arr > 0
            
        
              {extra_where}
              AND {_date_col} >= DATEADD('{trunc_unit}', -{lookback_periods}, DATE_TRUNC('{trunc_unit}', {SNAPSHOT_DATE_SQL}))
              AND {_date_col} < {_pacing_date_cap}
              {_pacing_day_filter}
              {build_global_filters_sql(has_employee_join=True)}
            ORDER BY {_date_col} DESC
            """
            df_pacing_detail = run_query(pacing_detail_sql)

            if not df_pacing_detail.empty:
                # Filters for drill-down
                pd_col1, pd_col2, pd_col3 = st.columns(3)
                with pd_col1:
                    pd_periods = ["All"] + sorted(df_pacing_detail["PERIOD_LABEL"].dropna().unique().tolist())
                    pd_sel_period = st.selectbox("Period", pd_periods, key="pacing_detail_period")
                with pd_col2:
                    pd_owners = ["All"] + sorted(df_pacing_detail["OWNER"].dropna().unique().tolist())
                    pd_sel_owner = st.selectbox("Owner", pd_owners, key="pacing_detail_owner")
                with pd_col3:
                    pd_segments = ["All"] + sorted(df_pacing_detail["SEGMENT"].dropna().unique().tolist())
                    pd_sel_segment = st.selectbox("Segment", pd_segments, key="pacing_detail_segment")

                if pd_sel_period != "All":
                    df_pacing_detail = df_pacing_detail[df_pacing_detail["PERIOD_LABEL"] == pd_sel_period]
                if pd_sel_owner != "All":
                    df_pacing_detail = df_pacing_detail[df_pacing_detail["OWNER"] == pd_sel_owner]
                if pd_sel_segment != "All":
                    df_pacing_detail = df_pacing_detail[df_pacing_detail["SEGMENT"] == pd_sel_segment]

                st.dataframe(df_pacing_detail, use_container_width=True, hide_index=True)
                st.caption(f"{len(df_pacing_detail):,} deals")
            else:
                st.info("No deal-level data found.")
    else:
        st.warning("No pacing data returned for selected filters.")

pri_row2_col1, pri_row2_col2 = st.columns(2)
with pri_row2_col1:
    st.subheader("CRM Hygiene")
    st.caption("Targets: Open Missing Data **15%** · SDR w/ Meeting Date **45%** · Closed Missing Competitor **40%** · Not Filled Next Steps **25%** · 3+ Days in Handover **0%**")
    st.markdown("[Open in HubSpot](https://app.hubspot.com/reports-dashboard/21928972/view/21056530)")
    st.components.v1.iframe("https://app.hubspot.com/reports-dashboard/21928972/view/21056530", height=600, scrolling=True)

pri_row3_col1, _ = st.columns([2, 1])
with pri_row3_col1:
    st.subheader("Sales Velocity")
    st.caption("Revenue speed: (Deals x Avg Deal Value x Rate) / Avg Cycle Days. Each line = one quarter.")
    vel_outcome = st.radio("Outcome", ["Won", "Lost"], horizontal=True, key="vel_outcome")
    vel_is_won = "TRUE" if vel_outcome == "Won" else "FALSE"

    velocity_sql = f"""
    WITH weekly_metrics AS (
        SELECT
            CONCAT(YEAR(fd.deal_closed_date), '-Q', QUARTER(fd.deal_closed_date)) AS quarter_label,
            FLOOR(DATEDIFF('DAY', DATE_TRUNC('QUARTER', fd.deal_closed_date), fd.deal_closed_date) / 7) + 1 AS week_in_quarter,
            CASE
                WHEN fd.deal_team_name ILIKE '%Ent%' THEN 'Enterprise'
                WHEN fd.deal_team_name ILIKE '%MM%' THEN 'Mid-Market'
                ELSE dc.segment
            END AS segment,
            fd.deal_team_name AS hubspot_team,
            fd.deal_source,
            COUNT(CASE WHEN fd.is_won = {vel_is_won} THEN fd.sk_deal END) AS outcome_deals,
            AVG(CASE WHEN fd.is_won = {vel_is_won} THEN fd.deal_total_arr END) AS avg_deal_value,
            COUNT(CASE WHEN fd.is_won = {vel_is_won} THEN fd.sk_deal END)::FLOAT / NULLIF(COUNT(fd.sk_deal), 0) AS outcome_rate,
            AVG(CASE WHEN fd.is_won = {vel_is_won} THEN DATEDIFF('DAY', fd.deal_created_date, fd.deal_closed_date) END) AS avg_cycle_days
        FROM {DWH}.FACT_DEALS fd
        LEFT JOIN {DWH}.DIM_COMPANY dc
            ON fd.sk_company = dc.sk_company
           AND COALESCE(dc.company_name, '') NOT ILIKE '%test%'
           AND COALESCE(dc.company_name, '') != 'Port'
           AND dc._is_deleted = FALSE
           AND dc.archived = FALSE
        LEFT JOIN {DWH}.DIM_EMPLOYEE de
            ON fd.sk_sales_owner = de.sk_employee
        WHERE fd.is_closed = TRUE
          AND fd.deal_total_arr > 0
          AND fd.deal_closed_date >= DATEADD('QUARTER', -3, DATE_TRUNC('QUARTER', {SNAPSHOT_DATE_SQL}))
          AND fd.deal_closed_date < {WEEK_CUTOFF_SQL}
          {build_global_filters_sql(has_employee_join=True)}
    
        GROUP BY 1, 2, 3, 4, 5
    )
    SELECT
        quarter_label,
        week_in_quarter,
        segment,
        hubspot_team,
        deal_source,
        outcome_deals,
        ROUND(avg_deal_value, 0) AS avg_deal_value,
        ROUND(outcome_rate * 100, 1) AS outcome_rate_pct,
        ROUND(avg_cycle_days, 0) AS avg_cycle_days,
        ROUND(
            (outcome_deals::FLOAT * avg_deal_value::FLOAT * outcome_rate::FLOAT)
            / NULLIF(avg_cycle_days::FLOAT, 0),
        0) AS sales_velocity
    FROM weekly_metrics
    WHERE outcome_deals > 0
    ORDER BY quarter_label, week_in_quarter
    """
    df_velocity = run_query(velocity_sql)

    if not df_velocity.empty:
        import altair as alt

        # Aggregate to quarter + week level (summing across breakdown groups)
        def render_velocity_chart(df_v):
            df_agg = df_v.groupby(["QUARTER_LABEL", "WEEK_IN_QUARTER"], as_index=False).agg(
                OUTCOME_DEALS=("OUTCOME_DEALS", "sum"),
                AVG_DEAL_VALUE=("AVG_DEAL_VALUE", "mean"),
                OUTCOME_RATE_PCT=("OUTCOME_RATE_PCT", "mean"),
                AVG_CYCLE_DAYS=("AVG_CYCLE_DAYS", "mean"),
            )
            df_agg["SALES_VELOCITY"] = (
                df_agg["OUTCOME_DEALS"] * df_agg["AVG_DEAL_VALUE"] * (df_agg["OUTCOME_RATE_PCT"] / 100)
                / df_agg["AVG_CYCLE_DAYS"].replace(0, 1)
            ).round(0)

            _vel_quarters = sorted(df_agg["QUARTER_LABEL"].unique().tolist())[-4:]
            df_agg = df_agg[df_agg["QUARTER_LABEL"].isin(_vel_quarters)]

            quarter_colors = ["#636EFA", "#EF553B", "#00CC96", "#FFA15A"]
            vel_color_scale = alt.Scale(domain=_vel_quarters, range=quarter_colors[:len(_vel_quarters)])

            chart = (
                alt.Chart(df_agg)
                .mark_line(point=alt.OverlayMarkDef(size=50))
                .encode(
                    x=alt.X("WEEK_IN_QUARTER:Q", title="Week in Quarter", axis=alt.Axis(tickMinStep=1)),
                    y=alt.Y("SALES_VELOCITY:Q", title="Sales Velocity ($ / day)"),
                    color=alt.Color("QUARTER_LABEL:N", title="Quarter", scale=vel_color_scale),
                    tooltip=[
                        alt.Tooltip("SALES_VELOCITY:Q", title="Velocity ($/day)", format="$,.0f"),
                        alt.Tooltip("WEEK_IN_QUARTER:Q", title="Week #", format=".0f"),
                        alt.Tooltip("QUARTER_LABEL:N", title="Quarter"),
                        alt.Tooltip("OUTCOME_DEALS:Q", title=f"{vel_outcome} Deals", format=",.0f"),
                        alt.Tooltip("AVG_DEAL_VALUE:Q", title="Avg Deal ($)", format="$,.0f"),
                        alt.Tooltip("OUTCOME_RATE_PCT:Q", title=f"{vel_outcome} Rate (%)", format=".1f"),
                        alt.Tooltip("AVG_CYCLE_DAYS:Q", title="Avg Cycle Days", format=",.0f"),
                    ],
                )
                .properties(height=350)
                .configure_legend(orient="bottom")
            )
            st.altair_chart(chart, use_container_width=True)

        # Breakdown tabs
        if cohort_breakdown == "Segment":
            seg_values = sorted(df_velocity["SEGMENT"].dropna().unique().tolist())
            vel_tabs = st.tabs(["All"] + seg_values)
            for i, tab in enumerate(vel_tabs):
                with tab:
                    if i == 0:
                        render_velocity_chart(df_velocity)
                    else:
                        render_velocity_chart(df_velocity[df_velocity["SEGMENT"] == seg_values[i - 1]])
        elif cohort_breakdown == "HubSpot Team":
            team_values = sorted(df_velocity["HUBSPOT_TEAM"].dropna().unique().tolist())
            vel_tabs = st.tabs(["All"] + team_values)
            for i, tab in enumerate(vel_tabs):
                with tab:
                    if i == 0:
                        render_velocity_chart(df_velocity)
                    else:
                        render_velocity_chart(df_velocity[df_velocity["HUBSPOT_TEAM"] == team_values[i - 1]])
        elif cohort_breakdown == "Deal Source":
            src_values = sorted(df_velocity["DEAL_SOURCE"].dropna().unique().tolist())
            vel_tabs = st.tabs(["All"] + src_values)
            for i, tab in enumerate(vel_tabs):
                with tab:
                    if i == 0:
                        render_velocity_chart(df_velocity)
                    else:
                        render_velocity_chart(df_velocity[df_velocity["DEAL_SOURCE"] == src_values[i - 1]])
        else:
            render_velocity_chart(df_velocity)

        with st.expander("Show raw deal data", expanded=False):
            # Local filters for raw data
            vel_filter_col1, vel_filter_col2 = st.columns(2)
            with vel_filter_col1:
                vel_q_options = sorted(df_velocity["QUARTER_LABEL"].unique().tolist(), reverse=True)
                vel_sel_quarter = st.selectbox("Quarter", ["All"] + vel_q_options, key="vel_raw_q")
            with vel_filter_col2:
                if vel_sel_quarter != "All":
                    vel_w_options = sorted(df_velocity[df_velocity["QUARTER_LABEL"] == vel_sel_quarter]["WEEK_IN_QUARTER"].unique().tolist())
                else:
                    vel_w_options = sorted(df_velocity["WEEK_IN_QUARTER"].unique().tolist())
                vel_sel_week = st.selectbox("Week in Quarter", ["All"] + [str(int(w)) for w in vel_w_options], key="vel_raw_w")

            vel_detail_sql = f"""
            SELECT
                fd.deal_name,
                de.display_name AS owner,
                fd.deal_team_name AS hubspot_team,
                ROUND(fd.deal_total_arr / NULLIF(DATEDIFF('DAY', fd.deal_created_date, fd.deal_closed_date), 0), 0) AS velocity_per_day,
                FLOOR(DATEDIFF('DAY', DATE_TRUNC('QUARTER', fd.deal_closed_date), fd.deal_closed_date) / 7) + 1 AS week_in_quarter,
                CONCAT(YEAR(fd.deal_closed_date), '-Q', QUARTER(fd.deal_closed_date)) AS quarter,
                fd.is_won,
                fd.deal_total_arr AS deal_value,
                fd.deal_closed_date::DATE AS close_date,
                DATEDIFF('DAY', fd.deal_created_date, fd.deal_closed_date) AS cycle_days
            FROM {DWH}.FACT_DEALS fd
            LEFT JOIN {DWH}.DIM_COMPANY dc
                ON fd.sk_company = dc.sk_company
               AND COALESCE(dc.company_name, '') NOT ILIKE '%test%'
               AND COALESCE(dc.company_name, '') != 'Port'
               AND dc._is_deleted = FALSE
               AND dc.archived = FALSE
            LEFT JOIN {DWH}.DIM_EMPLOYEE de
                ON fd.sk_sales_owner = de.sk_employee
            WHERE fd.is_closed = TRUE
              AND fd.is_won = {vel_is_won}
              AND fd.deal_total_arr > 0
              AND fd.deal_closed_date >= DATEADD('QUARTER', -3, DATE_TRUNC('QUARTER', {SNAPSHOT_DATE_SQL}))
              AND fd.deal_closed_date < {WEEK_CUTOFF_SQL}
              {build_global_filters_sql(has_employee_join=True)}
            ORDER BY fd.deal_closed_date DESC
            """
            df_vel_detail = run_query(vel_detail_sql)
            if not df_vel_detail.empty:
                # Apply sidebar filters
                if f_teams:
                    df_vel_detail = df_vel_detail[df_vel_detail["HUBSPOT_TEAM"].isin(f_teams)]
                if f_owners:
                    df_vel_detail = df_vel_detail[df_vel_detail["OWNER"].isin(f_owners)]
                # Apply local filters
                if vel_sel_quarter != "All":
                    df_vel_detail = df_vel_detail[df_vel_detail["QUARTER"] == vel_sel_quarter]
                if vel_sel_week != "All":
                    df_vel_detail = df_vel_detail[df_vel_detail["WEEK_IN_QUARTER"] == int(vel_sel_week)]
                st.dataframe(df_vel_detail, use_container_width=True, hide_index=True)
            else:
                st.info("No deals found.")
    else:
        st.warning("No velocity data returned.")

with pri_row2_col2:
    st.subheader("SDR Pipeline Health")
    st.caption("Deal creation vs. bottleneck conversion — stagnant deals by segment threshold (MM=30d, ENT=45d)")
    ph_gran = st.radio("View", ["Weekly", "Monthly", "Quarterly"], horizontal=True, key="ph_gran")

    if ph_gran == "Weekly":
        ph_trunc = "WEEK"
        ph_periods = 14
        ph_date_fmt = "%Y-%m-%d"
        ph_x_title = "Week (Mon)"
    elif ph_gran == "Monthly":
        ph_trunc = "MONTH"
        ph_periods = 14
        ph_date_fmt = "%Y-%m"
        ph_x_title = "Month"
    else:
        ph_trunc = "QUARTER"
        ph_periods = 14
        ph_date_fmt = "%Y-Q%q"
        ph_x_title = "Quarter"

    pipeline_health_sql = f"""
    WITH deals AS (
        SELECT
            fd.sk_deal,
            DATE_TRUNC('{ph_trunc}', fd.deal_created_date)::DATE AS create_period,
            fd.deal_created_date,
            fd.qualified_date,
            fd.deal_team_name AS hubspot_team,
            fd.deal_source,
            CASE
                WHEN fd.deal_team_name ILIKE '%Ent%' THEN 'Enterprise'
                WHEN fd.deal_team_name ILIKE '%MM%' THEN 'Mid-Market'
                ELSE dc.segment
            END AS segment
        FROM {DWH}.FACT_DEALS fd
        LEFT JOIN {DWH}.DIM_COMPANY dc
            ON fd.sk_company = dc.sk_company
           AND COALESCE(dc.company_name, '') NOT ILIKE '%test%'
           AND COALESCE(dc.company_name, '') != 'Port'
           AND dc._is_deleted = FALSE
           AND dc.archived = FALSE
        LEFT JOIN {DWH}.DIM_EMPLOYEE de
            ON fd.sk_sales_owner = de.sk_employee
        WHERE fd.deal_created_date >= DATEADD('{ph_trunc}', -{ph_periods}, DATE_TRUNC('{ph_trunc}', {SNAPSHOT_DATE_SQL}))
          AND fd.deal_created_date < {WEEK_CUTOFF_SQL}
        
          AND fd.deal_type = 'newbusiness'
          {build_global_filters_sql(has_employee_join=True)}
    
    )
    SELECT
        create_period,
        segment,
        hubspot_team,
        deal_source,
        COUNT(*) AS total_created,
        COUNT(CASE WHEN qualified_date IS NOT NULL THEN 1 END) AS qualified_deals,
        COUNT(CASE
            WHEN segment = 'Mid-Market' AND (
                (qualified_date IS NULL AND DATEDIFF('DAY', deal_created_date, {WEEK_CUTOFF_SQL}) > 30)
                OR (qualified_date IS NOT NULL AND DATEDIFF('DAY', deal_created_date, qualified_date) > 30)
            ) THEN 1
            WHEN segment = 'Enterprise' AND (
                (qualified_date IS NULL AND DATEDIFF('DAY', deal_created_date, {WEEK_CUTOFF_SQL}) > 45)
                OR (qualified_date IS NOT NULL AND DATEDIFF('DAY', deal_created_date, qualified_date) > 45)
            ) THEN 1
        END) AS stagnant_deals
    FROM deals
    WHERE segment IN ('Enterprise', 'Mid-Market')
    GROUP BY create_period, segment, hubspot_team, deal_source
    ORDER BY create_period
    """
    df_pipe_health = run_query(pipeline_health_sql)

    if not df_pipe_health.empty:
        def render_pipeline_health_chart(df_ph):
            # Aggregate to period level
            df_agg = df_ph.groupby("CREATE_PERIOD", as_index=False).agg(
                TOTAL_CREATED=("TOTAL_CREATED", "sum"),
                QUALIFIED_DEALS=("QUALIFIED_DEALS", "sum"),
                STAGNANT_DEALS=("STAGNANT_DEALS", "sum"),
            )
            df_agg["CVR_CREATED_STAGNANT"] = (
                df_agg["STAGNANT_DEALS"] / df_agg["TOTAL_CREATED"].replace(0, 1) * 100
            ).fillna(0).round(1)
            df_agg["CVR_STAGNANT_QUALIFIED"] = pd.to_numeric(
                df_agg["QUALIFIED_DEALS"] / df_agg["STAGNANT_DEALS"].replace(0, float("nan")) * 100,
                errors="coerce"
            ).round(1)

            df_melted = df_agg.melt(
                id_vars=["CREATE_PERIOD", "CVR_CREATED_STAGNANT", "CVR_STAGNANT_QUALIFIED"],
                value_vars=["TOTAL_CREATED", "QUALIFIED_DEALS", "STAGNANT_DEALS"],
                var_name="Metric",
                value_name="Count",
            )
            df_melted["Metric"] = df_melted["Metric"].map({
                "TOTAL_CREATED": "Total Created",
                "QUALIFIED_DEALS": "Qualified",
                "STAGNANT_DEALS": "Stagnant",
            })
            if ph_gran == "Quarterly":
                df_melted["PERIOD_LABEL"] = pd.to_datetime(df_melted["CREATE_PERIOD"]).apply(
                    lambda d: f"{d.year}-Q{(d.month - 1) // 3 + 1}"
                )
            elif ph_gran == "Monthly":
                df_melted["PERIOD_LABEL"] = pd.to_datetime(df_melted["CREATE_PERIOD"]).dt.strftime("%Y-%m")
            else:
                df_melted["PERIOD_LABEL"] = pd.to_datetime(df_melted["CREATE_PERIOD"]).dt.strftime("%b %d")

            period_order = df_melted["PERIOD_LABEL"].unique().tolist()
            color_map = alt.Scale(domain=["Total Created", "Stagnant", "Qualified"], range=["#636EFA", "#EF553B", "#00CC96"])

            df_line = df_melted[df_melted["Metric"] == "Total Created"][["PERIOD_LABEL", "CVR_STAGNANT_QUALIFIED"]].drop_duplicates()
            df_line["Legend"] = "Stagnant→Qualified %"

            bars = (
                alt.Chart(df_melted)
                .mark_bar()
                .encode(
                    x=alt.X("PERIOD_LABEL:N", title=ph_x_title, sort=period_order),
                    y=alt.Y("Count:Q", title="# of Deals"),
                    color=alt.Color("Metric:N", title="", scale=color_map, sort=["Total Created", "Stagnant", "Qualified"]),
                    xOffset=alt.XOffset("Metric:N", sort=["Total Created", "Stagnant", "Qualified"]),
                    tooltip=[
                        alt.Tooltip("PERIOD_LABEL:N", title="Period"),
                        alt.Tooltip("Metric:N", title="Type"),
                        alt.Tooltip("Count:Q", title="Deals", format=","),
                        alt.Tooltip("CVR_CREATED_STAGNANT:Q", title="Created→Stagnant %", format=".1f"),
                        alt.Tooltip("CVR_STAGNANT_QUALIFIED:Q", title="Stagnant→Qualified %", format=".1f"),
                    ],
                )
            )

            line = (
                alt.Chart(df_line)
                .mark_line(strokeWidth=2, strokeDash=[6, 3], point=alt.OverlayMarkDef(size=50))
                .encode(
                    x=alt.X("PERIOD_LABEL:N", sort=period_order),
                    y=alt.Y("CVR_STAGNANT_QUALIFIED:Q", title="Stagnant→Qualified %", axis=alt.Axis(orient="right")),
                    color=alt.Color("Legend:N", scale=alt.Scale(domain=["Stagnant→Qualified %"], range=["#00CC96"]), title=""),
                    tooltip=[
                        alt.Tooltip("PERIOD_LABEL:N", title="Period"),
                        alt.Tooltip("CVR_STAGNANT_QUALIFIED:Q", title="Stagnant→Qualified %", format=".1f"),
                    ],
                )
            )

            chart = alt.layer(bars, line).resolve_scale(y="independent").properties(height=350).configure_legend(orient="bottom")
            st.altair_chart(chart, use_container_width=True)

        # Breakdown tabs
        if cohort_breakdown == "Segment":
            seg_values = sorted(df_pipe_health["SEGMENT"].dropna().unique().tolist())
            ph_tabs = st.tabs(["All"] + seg_values)
            for i, tab in enumerate(ph_tabs):
                with tab:
                    if i == 0:
                        render_pipeline_health_chart(df_pipe_health)
                    else:
                        render_pipeline_health_chart(df_pipe_health[df_pipe_health["SEGMENT"] == seg_values[i - 1]])
        elif cohort_breakdown == "HubSpot Team":
            team_values = sorted(df_pipe_health["HUBSPOT_TEAM"].dropna().unique().tolist())
            ph_tabs = st.tabs(["All"] + team_values)
            for i, tab in enumerate(ph_tabs):
                with tab:
                    if i == 0:
                        render_pipeline_health_chart(df_pipe_health)
                    else:
                        render_pipeline_health_chart(df_pipe_health[df_pipe_health["HUBSPOT_TEAM"] == team_values[i - 1]])
        elif cohort_breakdown == "Deal Source":
            src_values = sorted(df_pipe_health["DEAL_SOURCE"].dropna().unique().tolist())
            ph_tabs = st.tabs(["All"] + src_values)
            for i, tab in enumerate(ph_tabs):
                with tab:
                    if i == 0:
                        render_pipeline_health_chart(df_pipe_health)
                    else:
                        render_pipeline_health_chart(df_pipe_health[df_pipe_health["DEAL_SOURCE"] == src_values[i - 1]])
        else:
            render_pipeline_health_chart(df_pipe_health)

        with st.expander("Show raw deal data", expanded=False):
            ph_filter_col1, ph_filter_col2 = st.columns(2)
            with ph_filter_col1:
                ph_periods_list = sorted(df_pipe_health["CREATE_PERIOD"].astype(str).unique().tolist(), reverse=True)
                ph_sel_period = st.selectbox("Period", ["All"] + ph_periods_list, key="ph_raw_period")
            with ph_filter_col2:
                ph_sel_type = st.selectbox("Type", ["All", "Stagnant", "Qualified", "Not Qualified"], key="ph_raw_type")

            ph_detail_sql = f"""
            SELECT
                fd.deal_name,
                dc.company_name,
                de.display_name AS owner,
                fd.deal_team_name AS hubspot_team,
                CASE
                    WHEN fd.deal_team_name ILIKE '%Ent%' THEN 'Enterprise'
                    WHEN fd.deal_team_name ILIKE '%MM%' THEN 'Mid-Market'
                    ELSE dc.segment
                END AS segment,
                fd.deal_created_date::DATE AS create_date,
                fd.qualified_date::DATE AS qualify_date,
                CASE
                    WHEN fd.qualified_date IS NOT NULL THEN DATEDIFF('DAY', fd.deal_created_date, fd.qualified_date)
                    ELSE DATEDIFF('DAY', fd.deal_created_date, {WEEK_CUTOFF_SQL})
                END AS days_to_qualify,
                fd.deal_stage,
                fd.deal_net_new_arr AS net_new_arr
            FROM {DWH}.FACT_DEALS fd
            LEFT JOIN {DWH}.DIM_COMPANY dc
                ON fd.sk_company = dc.sk_company
               AND COALESCE(dc.company_name, '') NOT ILIKE '%test%'
               AND COALESCE(dc.company_name, '') != 'Port'
               AND dc._is_deleted = FALSE
               AND dc.archived = FALSE
            LEFT JOIN {DWH}.DIM_EMPLOYEE de
                ON fd.sk_sales_owner = de.sk_employee
            WHERE fd.deal_created_date >= DATEADD('{ph_trunc}', -{ph_periods}, DATE_TRUNC('{ph_trunc}', {SNAPSHOT_DATE_SQL}))
              AND fd.deal_created_date < {WEEK_CUTOFF_SQL}
            
              AND fd.deal_type = 'newbusiness'
              {build_global_filters_sql(has_employee_join=True)}
              AND (fd.deal_team_name ILIKE '%Ent%' OR fd.deal_team_name ILIKE '%MM%')
            ORDER BY fd.deal_created_date DESC
            """
            df_ph_detail = run_query(ph_detail_sql)
            if not df_ph_detail.empty:
                if f_teams:
                    df_ph_detail = df_ph_detail[df_ph_detail["HUBSPOT_TEAM"].isin(f_teams)]
                if f_owners:
                    df_ph_detail = df_ph_detail[df_ph_detail["OWNER"].isin(f_owners)]
                if ph_sel_period != "All":
                    df_ph_detail = df_ph_detail[df_ph_detail["CREATE_DATE"].astype(str).str[:10] >= ph_sel_period]
                if ph_sel_type == "Stagnant":
                    df_ph_detail = df_ph_detail[
                        ((df_ph_detail["SEGMENT"] == "Mid-Market") & (df_ph_detail["DAYS_TO_QUALIFY"] > 30)) |
                        ((df_ph_detail["SEGMENT"] == "Enterprise") & (df_ph_detail["DAYS_TO_QUALIFY"] > 45))
                    ]
                elif ph_sel_type == "Qualified":
                    df_ph_detail = df_ph_detail[df_ph_detail["QUALIFY_DATE"].notna()]
                elif ph_sel_type == "Not Qualified":
                    df_ph_detail = df_ph_detail[df_ph_detail["QUALIFY_DATE"].isna()]
                st.dataframe(df_ph_detail, use_container_width=True, hide_index=True)
            else:
                st.info("No deals found.")
    else:
        st.warning("No pipeline health data returned.")

st.markdown("---")

# =============================================================================
# SECONDARY CHARTS (2x2 + 1)
# =============================================================================
st.header("Deep Dives")

sec_row1_col1, sec_row1_col2 = st.columns(2)
with sec_row1_col1:
    st.subheader("Forecast")
    st.caption("Weighted pipeline forecast vs. target by close date")
    st.info("Coming soon")

with sec_row1_col2:
    st.subheader("Risk")
    st.caption("Deals at risk — aging, slipping close dates, stalled stages")
    st.info("Coming soon")

sec_row2_col1, sec_row2_col2 = st.columns(2)
with sec_row2_col1:
    st.subheader("Competition")
    st.caption("Win/loss rates by competitor presence")
    st.info("Coming soon")

with sec_row2_col2:
    st.subheader("Renewals")
    st.caption("Upcoming renewals and expansion pipeline")
    st.info("Coming soon")

st.subheader("Rep & Manager Calls")
st.caption("Activity metrics — calls, meetings, and engagement by rep/manager")
st.info("Coming soon")

st.markdown("---")
